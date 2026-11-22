"""Review CAF's sealed case-file assessments and freeze human-selected reruns."""

import argparse
from contextlib import contextmanager, redirect_stdout
import fcntl
import json
import math
import os
from pathlib import Path
import random
import re
import sys
import tempfile

import evidence_study as study
from evidence_artifacts import KINDS, load_candidate, save_candidate
from evidence_study import condition_artifacts as condition_artifacts

CANDIDATE_ID = re.compile(r"(?:playbook|skill|tool|lora_suggestion)-[0-9]{3,}")
HEX = re.compile(r"[0-9a-f]{64}")
SECRET = re.compile(r"FLAG\{[^}\r\n]*\}|(?<![a-fA-F0-9])[a-fA-F0-9]{24}(?![a-fA-F0-9])", re.I)
ROW_FIELDS = (
    "condition",
    "repetition",
    "status",
    "flags_recovered",
    "flags_available",
    "flags_in_answer",
    "incorrect_submissions",
    "duplicate_submissions",
    "valid_format",
    "model_calls",
    "tool_calls",
    "tool_calls_by_name",
    "elapsed_seconds",
    "hints_released",
    "solutions_released",
    "progress_checks",
    "progress_check_errors",
    "final_judge_status",
    "final_judge_passed",
    "final_judge_score",
)


def _local(root, *parts):
    """Reject symlink traversal below a caller-authorized directory."""
    root = Path(root).absolute()
    if root.is_symlink():
        raise ValueError("Expected an ordinary study directory")
    path = root.joinpath(*parts)
    if path.resolve() != root.resolve().joinpath(*parts):
        raise ValueError("Study paths must stay within their directory")
    return path


def _stage(root, group, name):
    folder = _local(root, group, name)
    record = study.read(_local(folder, "stage.json"))
    attempt = record.get("attempt", "")
    if not isinstance(attempt, str) or not re.fullmatch(r"attempt-\d+", attempt):
        raise ValueError("Invalid study attempt")
    directory = _local(folder, attempt)
    stage = f"{group}/{name}"
    if (
        not directory.is_dir()
        or record.get("stage") != stage
        or study.digest([stage, study.tree_hash(directory), record["result"]]) != record.get("sha256")
    ):
        raise ValueError("Study checkpoint integrity check failed")
    return directory, record["result"], record["sha256"]


def _redact(text):
    if not isinstance(text, str):
        raise ValueError("Expected text in analysis")
    return SECRET.sub("[redacted]", text[:64_000])


def _candidate_meta(item, status):
    return {"status": status, "sha256": study.digest(item)}


def _candidate_rows(catalog, artifacts):
    seen = set()
    rows = []
    for key, meta in sorted(catalog.items()):
        if not CANDIDATE_ID.fullmatch(key):
            raise ValueError("Invalid candidate ID")
        kind = key.rsplit("-", 1)[0]
        status = meta["status"]
        row = dict(id=key, kind=kind, name=key, description="", preview="", status=status, eligible=False)
        if status == "rejected":
            row["description"] = _redact(meta.get("reason", "Candidate failed validation"))
        else:
            if status != ("advisory" if kind == "lora_suggestion" else "validated"):
                raise ValueError("Unexpected candidate status")
            item = artifacts[key]
            if item["kind"] != kind or study.digest(item) != meta["sha256"]:
                raise ValueError("Candidate differs from its review record")
            identity = study.digest({k: v for k, v in item.items() if k not in ("name", "description")})
            preview = item.get("markdown") or json.dumps(
                {k: item[k] for k in ("operation", "keyword") if k in item}
            )
            row.update(
                name=_redact(item["name"]), description=_redact(item["description"]), preview=_redact(preview)
            )
            row["eligible"] = status == "validated" and identity not in seen
            if identity in seen:
                row["status"] = "duplicate"
            seen.add(identity)
        rows.append(row)
    return rows


def _read_source(source):
    source = Path(source)
    manifest = study.read(_local(source, "manifest.json"))
    report = study.read(_local(source, "report.json"))
    case = report.get("case")
    package = manifest.get("package_hash", "")
    reps = manifest.get("configuration", {}).get("repetitions")
    if (
        manifest.get("version") != 1
        or not isinstance(package, str)
        or not HEX.fullmatch(package)
        or case not in study.REVIEW_FILES
        or report.get("metric") != "flags_recovered"
        or type(reps) is not int
        or reps < 1
        or reps != report.get("repetitions")
    ):
        raise ValueError("Expected a completed sealed case-file study")
    public_hashes = manifest["participant_sha256"]
    if set(public_hashes) != set(study.REVIEW_FILES[case]):
        raise ValueError("Unexpected case evidence files")
    for name in study.REVIEW_FILES[case]:
        study.checked_file(_local(source, "participant"), name, public_hashes[name])
    tasks = study.read(_local(source, "participant", "tasks.json"))
    if not isinstance(tasks, list) or len(tasks) != 1 or tasks[0].get("id") != case:
        raise ValueError("Unsupported evidence task")
    baseline, confirmation, locations, signatures, analyses = [], [], [], [], []
    for rep in range(1, reps + 1):
        for label, rows in (("baseline", baseline), ("confirmation", confirmation)):
            if label == "confirmation" and not report.get("confirmation_rows"):
                continue
            slot = f"{label}-{rep:03d}"
            path, row, sig = _stage(source, "trials", slot)
            signatures.append(sig)
            rows.append(dict({k: row[k] for k in ROW_FIELDS if k in row}, condition=label, repetition=rep))
            if label == "baseline":
                locations.append(path / "worker")
                if _local(source, "analysis", slot, "stage.json").is_file():
                    _, saved, sig = _stage(source, "analysis", slot)
                    signatures.append(sig)
                    analyses.append(_redact(saved["analysis"]))
                else:
                    analyses.append(None)
    catalog, artifacts = {}, {}
    for folder in sorted(_local(source, "candidates").glob("*")):
        key = folder.name
        if not CANDIDATE_ID.fullmatch(key):
            raise ValueError("Invalid source candidate")
        attempt, record, sig = _stage(source, "candidates", key)
        signatures.append(sig)
        if record["status"] == "rejected":
            catalog[key] = dict(status="rejected", reason=_redact(record.get("reason", "")))
        else:
            item = load_candidate(attempt / "artifact")
            artifacts[key] = item
            catalog[key] = _candidate_meta(item, record["status"])
    # Preserve manually enabled artifacts as choices when reviewing a derived run.
    if manifest.get("review_experiment_sha256"):
        for key, fingerprint in manifest["artifacts"].items():
            if not CANDIDATE_ID.fullmatch(key):
                raise ValueError("Invalid frozen candidate")
            item = load_candidate(_local(source, "artifacts", key))
            if study.digest(item) != fingerprint:
                raise ValueError("Frozen candidate differs from the experiment")
            artifacts[key] = item
            catalog[key] = _candidate_meta(item, "validated")
    summary = {
        "case": case,
        "package_hash": package,
        "baseline_rows": baseline,
        "baseline": study.summarize(baseline),
        "confirmation_rows": confirmation,
        "confirmation": study.summarize(confirmation) if confirmation else None,
    }
    source_id = study.digest([manifest, signatures, catalog])
    return summary, analyses, locations, artifacts, catalog, source_id, public_hashes


def _observations(summary):
    return [
        f"Baseline session {row['repetition']} received credit for {row['flags_recovered']} of "
        f"{row['flags_available']} flags. Submission format was "
        f"{'valid' if row['valid_format'] else 'invalid'}. Status was {row['status']}."
        for row in summary["baseline_rows"]
    ]


def inspect_study(source):
    summary, analyses, _, artifacts, catalog, _, _ = _read_source(source)
    return {
        **summary,
        "analysis": [a or b for a, b in zip(analyses, _observations(summary))],
        "analysis_complete": all(analyses),
        "candidates": _candidate_rows(catalog, artifacts),
    }


@contextmanager
def _work(path, identity):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Expected an ordinary output directory")
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    with _local(path, ".review.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another operation is active in this directory") from None
        marker = _local(path, "request.json")
        if marker.exists():
            if study.read(marker) != identity:
                raise ValueError("This directory belongs to a different request")
        elif {p.name for p in path.iterdir()} == {".review.lock"}:
            study.write(marker, identity)
        else:
            raise ValueError("Choose a new output directory")
        yield path


def trial_settings_digest(config):
    return study.digest({k: config[k] for k in ("model", "limits", "repetitions", "seed")})


def _check_locations(output, *inputs):
    output = Path(output).resolve()
    if any(
        output.is_relative_to(Path(path).resolve()) or Path(path).resolve().is_relative_to(output)
        for path in inputs
    ):
        raise ValueError("Use separate input and output directories")


def _copy_artifacts(root, artifacts):
    for key, item in artifacts.items():
        path = _local(root, "artifacts", key)
        if path.exists():
            if load_candidate(path) != item:
                raise ValueError("Saved artifact differs from its source")
        else:
            save_candidate(path, item)


def _review(source, instance, config_path, review, counts=None):
    _check_locations(review, source, instance)
    config = study.settings(Path(config_path))
    summary, saved_analyses, workers, artifacts, catalog, source_id, public_hashes = _read_source(source)
    files, flags, package = study.load_instance(Path(instance), for_review=True)
    if package != summary["package_hash"] or any(
        study.sha256(data).hexdigest() != public_hashes[name] for name, data in files.items()
    ):
        raise ValueError("Source evidence does not match the registered instance")
    request = {
        "type": "sealed-evidence-review-v1",
        "source_sha256": source_id,
        "config_sha256": study.digest(config),
    }
    with _work(review, request) as path:
        index = path / "review.json"
        plan = path / "proposals.json"
        if counts is not None:
            if (
                not isinstance(counts, dict)
                or counts.keys() - set(KINDS)
                or any(type(n) is not int or n < 0 for n in counts.values())
            ):
                raise ValueError("Supply nonnegative integer counts for supported artifact types")
            counts = {kind: counts.get(kind, 0) for kind in KINDS}
            if plan.exists() and study.read(plan) != counts:
                raise ValueError("Generation counts changed; start a new review")
            if not plan.exists():
                study.write(plan, counts)
        if index.exists():
            previous = _read_review(path)
            if counts is None or previous[0]["generation_complete"]:
                return _view(*previous)
        analyses = []
        for i, (saved, worker) in enumerate(zip(saved_analyses, workers), 1):
            if saved is None:
                _, result = study.checkpoint(
                    path / "analysis" / f"baseline-{i:03d}",
                    lambda dest: study.analyze_trial(
                        worker, dest / "analyst", config["analysis_model"], config["limits"]
                    ),
                )
                saved = _redact(result["analysis"])
            analyses.append(saved)
        if counts is not None:
            for kind, count in counts.items():
                indices = [int(k.rsplit("-", 1)[1]) for k in catalog if k.rsplit("-", 1)[0] == kind]
                start = max(indices, default=0) + 1
                names = [item["name"] for item in artifacts.values() if item["kind"] == kind]
                for i in range(start, start + count):
                    key = f"{kind}-{i:03d}"
                    attempt, record = study.generate_candidate(
                        path / "generation" / key, kind, "\n\n".join(analyses), config, flags, i, names
                    )
                    if record["status"] == "rejected":
                        catalog[key] = {"status": "rejected", "reason": _redact(record.get("reason", ""))}
                    else:
                        item = load_candidate(attempt / "artifact")
                        artifacts[key] = item
                        catalog[key] = _candidate_meta(item, record["status"])
                        names.append(item["name"])
        _copy_artifacts(path, artifacts)
        data = {
            **summary,
            "source_sha256": source_id,
            "participant_sha256": public_hashes,
            "runtime_sha256": trial_settings_digest(config),
            "repetitions": config["repetitions"],
            "wall_seconds": config["limits"]["wall_seconds"],
            "analysis": analyses,
            "catalog": catalog,
            "generation_complete": counts is not None,
        }
        study.write(index, {**data, "sha256": study.digest(data)})
        return _view(data, artifacts)


def analyze_study(source, instance, config, review):
    return _review(source, instance, config, review)


def generate_review(source, instance, config, review, counts):
    return _review(source, instance, config, review, counts)


def _read_review(review):
    record = study.read(_local(review, "review.json"))
    fingerprint = record.pop("sha256")
    if study.digest(record) != fingerprint or record["case"] not in study.REVIEW_FILES:
        raise ValueError("Review integrity check failed")
    artifacts = {}
    for key, meta in record["catalog"].items():
        if not CANDIDATE_ID.fullmatch(key):
            raise ValueError("Invalid review artifact ID")
        if meta["status"] != "rejected":
            artifacts[key] = load_candidate(_local(review, "artifacts", key))
    return record, artifacts


def _view(record, artifacts):
    fields = (
        "case",
        "package_hash",
        "baseline",
        "baseline_rows",
        "confirmation",
        "confirmation_rows",
        "analysis",
        "generation_complete",
    )
    return {
        **{k: record[k] for k in fields},
        "analysis_complete": True,
        "candidates": _candidate_rows(record["catalog"], artifacts),
    }


def inspect_review(review):
    return _view(*_read_review(Path(review)))


def save_experiment(review, enabled, experiment, name):
    _check_locations(experiment, review)
    record, items = _read_review(review)
    eligible = {r["id"] for r in _candidate_rows(record["catalog"], items) if r["eligible"]}
    if (
        not isinstance(enabled, list)
        or not all(isinstance(k, str) and k in eligible for k in enabled)
        or len(set(enabled)) != len(enabled)
    ):
        raise ValueError("Choose distinct, eligible artifacts from this review")
    if not isinstance(name, str) or not name.strip() or len(name) > 120 or not name.isprintable():
        raise ValueError("Provide a printable experiment name of at most 120 characters")
    spec = {
        "version": 1,
        "name": name.strip(),
        "status": "runnable",
        "case": record["case"],
        "enabled": list(enabled),
        "package_hash": record["package_hash"],
        "source_sha256": record["source_sha256"],
        "review_sha256": study.digest(record),
        "participant_sha256": record["participant_sha256"],
        "runtime_sha256": record["runtime_sha256"],
        "repetitions": record["repetitions"],
        "wall_seconds": record["wall_seconds"],
        "artifacts": {k: study.digest(items[k]) for k in enabled},
    }
    dst = Path(experiment)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dst.parent) as tmp:
        staged = Path(tmp) / "bundle"
        staged.mkdir(mode=0o700)
        _copy_artifacts(staged, {k: items[k] for k in enabled})
        study.write(staged / "experiment.json", {**spec, "sha256": study.digest(spec)})
        try:
            # Atomic publication; an existing valid bundle is never replaced.
            if not dst.exists() and not dst.is_symlink():
                os.rename(staged, dst)
        except OSError:
            if not dst.exists():
                raise
        if load_experiment(dst)[0] != spec:
            raise ValueError("Experiment name or selection differs from the saved experiment")
    return {k: spec[k] for k in ("name", "enabled", "case", "package_hash", "status")}


def load_experiment(directory):
    spec = study.read(_local(directory, "experiment.json"))
    fingerprint = spec.pop("sha256")
    if study.digest(spec) != fingerprint or spec.get("version") != 1 or spec.get("case") not in study.REVIEW_FILES:
        raise ValueError("Experiment integrity check failed")
    if (
        not isinstance(spec["enabled"], list)
        or not all(isinstance(k, str) and CANDIDATE_ID.fullmatch(k) for k in spec["enabled"])
        or len(spec["enabled"]) != len(set(spec["enabled"]))
        or set(spec["enabled"]) != set(spec["artifacts"])
    ):
        raise ValueError("Invalid frozen artifact selection")
    items = {}
    for key in spec["enabled"]:
        item = load_candidate(_local(directory, "artifacts", key))
        if (
            item["kind"] != key.rsplit("-", 1)[0]
            or item["kind"] == "lora_suggestion"
            or study.digest(item) != spec["artifacts"][key]
        ):
            raise ValueError("Invalid frozen artifact")
        items[key] = item
    return spec, items


def _run(experiment, instance, config_path, output):
    inputs = [instance, config_path] + ([experiment] if experiment is not None else [])
    _check_locations(output, *inputs)
    config = study.settings(Path(config_path))
    public, flags, package = study.load_instance(Path(instance))
    hashes = {k: study.sha256(v).hexdigest() for k, v in public.items()}
    spec, items = load_experiment(experiment) if experiment is not None else ({}, {})
    if spec and (
        package != spec["package_hash"]
        or hashes != spec["participant_sha256"]
        or trial_settings_digest(config) != spec["runtime_sha256"]
    ):
        raise ValueError("Experiment requires its registered case, model and trial settings")
    manifest = {
        "version": 1,
        "package_hash": package,
        "participant_sha256": hashes,
        "configuration": config,
        "runtime": study.sources(),
        "mode": "reviewed" if spec else "baseline",
    }
    if spec:
        manifest.update(
            review_experiment_sha256=study.digest(spec),
            source_sha256=spec["source_sha256"],
            artifacts=spec["artifacts"],
        )
    with _work(
        output, {"type": "sealed-evidence-rerun-v1", "manifest_sha256": study.digest(manifest)}
    ) as path:
        frozen = path / "manifest.json"
        if frozen.exists() and study.read(frozen) != manifest:
            raise ValueError("Study manifest changed")
        kit = path / "participant"
        kit.mkdir(exist_ok=True)
        for key, blob in public.items():
            file = _local(kit, key)
            if file.exists():
                study.checked_file(kit, key, hashes[key])
            else:
                file.write_bytes(blob)
        study.write(frozen, manifest)
        _copy_artifacts(path, items)
        decision = {"selection": "human" if spec else "baseline", "selected": list(items)}
        study.write(path / "selection.json", decision)
        rows = {"baseline": [], "confirmation": []}
        rng = random.Random(config["seed"])
        for rep in range(1, config["repetitions"] + 1):
            labels = ["baseline", "confirmation"] if spec else ["baseline"]
            rng.shuffle(labels)
            for label in labels:
                enabled = list(items.values()) if label == "confirmation" else []
                _, row = study.run_condition(path, kit, flags, config, label, rep, enabled)
                rows[label].append(row)
        baseline = study.summarize(rows["baseline"])
        confirmation = study.summarize(rows["confirmation"]) if spec else None
        report = {
            "case": study.TASK,
            "metric": "flags_recovered",
            "scope": "Same frozen sealed evidence case",
            "repetitions": config["repetitions"],
            "baseline": baseline,
            "individual": {},
            "confirmation": confirmation,
            "additional_flags": confirmation["flags_recovered"] - baseline["flags_recovered"]
            if spec
            else None,
            "retained": list(items),
            "selection_sha256": study.digest(decision),
            "baseline_rows": rows["baseline"],
            "confirmation_rows": rows["confirmation"],
            "individual_rows": {},
            "candidates": {},
        }
        study.write(path / "report.json", report)
        return report


def run_baseline(instance, config, output):
    return _run(None, instance, config, output)


def run_experiment(experiment, instance, config, output):
    return _run(experiment, instance, config, output)


def _import_row(row, flags, objectives, case):
    if not isinstance(row, dict) or row.get("condition") not in ("baseline", "confirmation"):
        raise ValueError("Imported rows require a baseline or confirmation condition")
    rep = row.get("repetition")
    if type(rep) is not int or rep < 1:
        raise ValueError("Each imported row requires a positive repetition number")
    worker = row["worker"]
    if not isinstance(worker, dict) or worker.get("status") not in (
        "completed",
        "timeout",
        "budget_exceeded",
    ):
        raise ValueError("Unsupported trial status in sealed evidence history")
    answer = worker.get("final_answer") or ""
    if not isinstance(answer, str):
        raise ValueError("Expected a textual final answer")
    outcomes = worker.get("tool_calls_by_name", {})
    if not isinstance(outcomes, dict) or any(
        not isinstance(k, str)
        or (k not in ("read_ticket", "open_case_notes") and not re.fullmatch(r"evidence_[a-z0-9_]{1,75}", k)
            and not (case == study.THREE_CHAINS_TASK and k == "unknown"))
        or type(v) is not int
        or v < 0
        for k, v in outcomes.items()
    ):
        raise ValueError("Imported tool counts must name fixed case readers or evidence parsers")
    metrics = {k: worker.get(k) for k in ("model_calls", "tool_calls", "elapsed_seconds")}
    for key in ("model_calls", "tool_calls"):
        if metrics[key] is not None and (type(metrics[key]) is not int or metrics[key] < 0):
            raise ValueError("Invalid call count")
    if (
        "tool_calls_by_name" in worker
        and metrics["tool_calls"] is not None
        and sum(outcomes.values()) != metrics["tool_calls"]
    ):
        raise ValueError("Per-tool counts disagree with total")
    elapsed = metrics["elapsed_seconds"]
    if elapsed is not None and (
        type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0
    ):
        raise ValueError("Invalid elapsed time")
    sanitized = {**metrics, "status": worker["status"], "tool_calls_by_name": outcomes}
    if case == study.THREE_CHAINS_TASK:
        blocked = worker.get("blocked_tool_attempts")
        if type(blocked) is not int or blocked < 0 or blocked != outcomes.get("unknown", 0):
            raise ValueError("Policy-blocked tool attempt count disagrees with native CAF projection")
        sanitized["blocked_tool_attempts"] = blocked
    assistance = worker.get("assistance_summary")
    if assistance is not None:
        fields = {"hints_released", "solutions_released", "progress_checks",
                  "progress_check_errors", "final_judge_status", "final_judge_passed",
                  "final_judge_score"}
        if not isinstance(assistance, dict) or set(assistance) != fields:
            raise ValueError("Invalid imported live judge summary")
        if any(type(assistance[key]) is not int or assistance[key] < 0
               for key in ("hints_released", "solutions_released", "progress_checks",
                           "progress_check_errors")):
            raise ValueError("Invalid live judge event count")
        if assistance["final_judge_status"] not in ("judged", "judge_error", "worker_error"):
            raise ValueError("Invalid final judge status")
        if assistance["final_judge_passed"] is not None and type(assistance["final_judge_passed"]) is not bool:
            raise ValueError("Invalid final judge outcome")
        judge_score = assistance["final_judge_score"]
        if judge_score is not None and (
            type(judge_score) not in (int, float) or not math.isfinite(judge_score)
            or not 0 <= judge_score <= 1
        ):
            raise ValueError("Invalid final judge score")
        sanitized["assistance_summary"] = assistance
    if "tool_events" in worker:
        from evidence_worker import verified_tool_projection
        verified_tool_projection(worker["tool_events"], outcomes,
                                 allow_blocked_unknown=case == study.THREE_CHAINS_TASK)
        sanitized["tool_events"] = worker["tool_events"]
    score = study.score(
        {
            **sanitized,
            "final_answer": answer,
            "turn_budget_exhausted": worker.get("turn_budget_exhausted") is True,
        },
        flags,
    )
    if case == study.THREE_CHAINS_TASK:
        score["blocked_tool_attempts"] = sanitized["blocked_tool_attempts"]
    if assistance is not None:
        score.update(assistance)
    official = row.get("score")
    if official is not None:
        if not isinstance(official, dict):
            raise ValueError("Host verifier result must be an object")
        expected = {
            k: score[k]
            for k in (
                "flags_recovered",
                "flags_available",
                "flags_in_answer",
                "incorrect_submissions",
                "duplicate_submissions",
                "valid_format",
            )
        }
        expected.update(
            unknown_flags_count=score["incorrect_submissions"],
            score=score["flags_recovered"] / score["flags_available"],
            passed=score["valid_format"]
            and score["flags_recovered"] == score["flags_available"]
            and not (score["incorrect_submissions"] or score["duplicate_submissions"]),
        )
        if not official.keys() & (expected.keys() | {"checks"}):
            raise ValueError("Host score contains no comparable metrics")
        for key, value in expected.items():
            if key in official and (
                isinstance(official[key], bool) != isinstance(value, bool) or official[key] != value
            ):
                raise ValueError(f"Host verification disagrees on {key}")
        if "checks" in official:
            actual = json.loads(answer)["flags"] if score["valid_format"] else []
            check_rows = official["checks"]
            if (
                not isinstance(check_rows, list)
                or len(check_rows) != len(objectives)
                or not all(
                    isinstance(c, dict) and isinstance(c.get("name"), str) and type(c.get("passed")) is bool
                    for c in check_rows
                )
                or {c["name"]: c["passed"] for c in check_rows}
                != {name: flag in actual for name, flag in objectives.items()}
            ):
                raise ValueError("Host verification differs on individual objectives")
    compact = {
        k: score[k]
        for k in (
            "flags_recovered",
            "flags_available",
            "flags_in_answer",
            "valid_format",
            "incorrect_submissions",
        )
    }
    compact["distinct_flag_like_values"] = len(set(re.findall(r"FLAG\{[a-zA-Z0-9_-]+\}", answer)))
    return (
        row["condition"],
        rep,
        score,
        {**sanitized, "status": score["status"], "assessment_summary": compact},
    )


def import_scored(instance, config, input, output):
    """Import host-scored history for the registered sealed instance without model or participant execution."""
    _check_locations(output, instance, config, input)
    study.settings(Path(config))
    instance = Path(instance)
    public, flags, package = study.load_instance(instance, for_review=True)
    case = json.loads(public["tasks.json"])[0]["id"]
    payload = study.read(Path(input))
    if not isinstance(payload, dict) or payload.get("package_hash") != package:
        raise ValueError("Imported history must match the registered case package")
    if (
        not isinstance(payload.get("rows"), list)
        or not payload["rows"]
        or not isinstance(payload.get("provenance"), dict)
    ):
        raise ValueError("Imported history needs provenance and at least one trial")
    suite = instance / "host/suite"
    name = "evaluator/verifiers.json"
    objectives = json.loads(
        study.checked_file(suite, name, study.read(suite / "manifest.json")["files"][name])
    )[case]["expected"]
    indexed = {"baseline": {}, "confirmation": {}}
    for row in payload["rows"]:
        label, rep, score, result = _import_row(row, flags, objectives, case)
        if rep in indexed[label]:
            raise ValueError("Duplicate condition and repetition in imported history")
        if case in (study.CATALOG_TASK, study.CATALOG_FIVE_TASK, study.THREE_CHAINS_TASK):
            result["review_case"] = case
        indexed[label][rep] = (score, result)
    reps = len(indexed["baseline"])
    if (
        not reps
        or set(indexed["baseline"]) != set(range(1, reps + 1))
        or (indexed["confirmation"] and indexed["baseline"].keys() != indexed["confirmation"].keys())
    ):
        raise ValueError("Expected consecutive baseline repetitions and matching confirmation repetitions")
    provenance = {"method": "host-scored-evidence", "sha256": study.digest(payload["provenance"])}
    manifest = {
        "version": 1,
        "mode": "imported",
        "configuration": {"repetitions": reps},
        "provenance": provenance,
        "package_hash": package,
        "participant_sha256": {k: study.sha256(v).hexdigest() for k, v in public.items()},
    }
    with _work(output, {"type": "sealed-history-import-v1", "input_sha256": study.digest(payload)}) as out:
        study.write(out / "manifest.json", manifest)
        kit = _local(out, "participant")
        kit.mkdir(exist_ok=True)
        for name, blob in public.items():
            f = _local(kit, name)
            if f.exists():
                study.checked_file(kit, name, manifest["participant_sha256"][name])
            else:
                f.write_bytes(blob)
        rows = {"baseline": [], "confirmation": []}
        for label, data in indexed.items():
            for rep, (score, result) in sorted(data.items()):

                def persist(attempt):
                    study.write(attempt / "worker" / "result.json", result)
                    return score

                attempt, verified = study.checkpoint(out / "trials" / f"{label}-{rep:03d}", persist)
                rows[label].append(
                    dict(verified, condition=label, repetition=rep, attempt=str(attempt.relative_to(out)))
                )
        base = study.summarize(rows["baseline"])
        compared = study.summarize(rows["confirmation"]) if indexed["confirmation"] else None
        study.write(
            out / "report.json",
            {
                "case": case,
                "metric": "flags_recovered",
                "scope": "Imported host-scored evidence assessment",
                "provenance": provenance,
                "repetitions": reps,
                "baseline": base,
                "confirmation": compared,
                "additional_flags": compared["flags_recovered"] - base["flags_recovered"]
                if compared
                else None,
                "retained": [],
                "individual": {},
                "individual_rows": {},
                "candidates": {},
                "baseline_rows": rows["baseline"],
                "confirmation_rows": rows["confirmation"],
            },
        )
    return inspect_study(output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in (
        "inspect",
        "baseline",
        "analyze",
        "generate",
        "show-review",
        "save",
        "run",
        "import-scored",
    ):
        cmd = commands.add_parser(action)
        if action in ("inspect", "analyze", "generate"):
            cmd.add_argument("source", type=Path)
        if action in ("baseline", "analyze", "generate", "run", "import-scored"):
            cmd.add_argument("--instance", type=Path, required=True)
            cmd.add_argument("--config", type=Path, required=True)
        if action in ("baseline", "run", "import-scored"):
            cmd.add_argument("--output", type=Path, required=True)
        if action in ("analyze", "generate"):
            cmd.add_argument("--review", type=Path, required=True)
        if action == "import-scored":
            cmd.add_argument("--input", type=Path, required=True)
        if action == "generate":
            cmd.add_argument("--counts", type=json.loads, required=True)
        if action in ("show-review", "save"):
            cmd.add_argument("review", type=Path)
        if action == "save":
            cmd.add_argument("--enabled", type=json.loads, required=True)
            cmd.add_argument("--experiment", type=Path, required=True)
            cmd.add_argument("--name", required=True)
        if action == "run":
            cmd.add_argument("experiment", type=Path)
    kwargs = vars(parser.parse_args(argv))
    action = kwargs.pop("action")
    handler = {
        "import-scored": import_scored,
        "inspect": inspect_study,
        "baseline": run_baseline,
        "analyze": analyze_study,
        "generate": generate_review,
        "show-review": inspect_review,
        "save": save_experiment,
        "run": run_experiment,
    }[action]
    try:
        with redirect_stdout(sys.stderr):
            result = handler(**kwargs)
    except (ValueError, TypeError, OSError, KeyError, RuntimeError) as exc:
        print(f"Evidence review: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
