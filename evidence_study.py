"""Run an artifact comparison on the offline ScenarioForge two-flag handoff."""

import argparse
import fcntl
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import random
import re
import sys
import tempfile
from urllib.parse import urlsplit

from evidence_artifacts import KINDS, load_candidate, save_candidate, validate_candidate
from evidence_worker import analyze_trial, propose_candidate, run_trial


PUBLIC = ("tasks.json", "handoff-ticket.txt", "case-notes.sealed")
TASK = "alderbank-case-file-handoff"
CATALOG_TASK = "catalog-ticket-checksum"
CATALOG_FIVE_TASK = "catalog-five-checksum"
THREE_CHAINS_TASK = "caf-three-independent-chains"
REVIEW_FILES = {TASK: PUBLIC, CATALOG_TASK: ("tasks.json",), CATALOG_FIVE_TASK: ("tasks.json",), THREE_CHAINS_TASK: ("tasks.json",)}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def encoded(obj):
    return (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def digest(obj):
    return sha256(encoded(obj)).hexdigest()


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        tmp = Path(handle.name)
        try:
            handle.write(encoded(obj))
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    os.replace(tmp, path)


def model_settings(value):
    allowed = {"provider", "url", "name", "api_key_env", "ssl_verify"}
    if not isinstance(value, dict) or value.keys() - allowed:
        raise ValueError("Model settings accept provider, url, name, ssl_verify and api_key_env")
    model = {"ssl_verify": True, "api_key_env": "", **value}
    if (
        model.get("provider") not in ("openai", "ollama_direct", "claude")
        or not isinstance(model.get("name"), str)
        or not model["name"].strip()
    ):
        raise ValueError("Set a supported model provider and model name")
    if not isinstance(model.get("url"), str) or not isinstance(model["api_key_env"], str):
        raise ValueError("Model URL and credential environment name must be strings")
    url = urlsplit(model["url"])
    if (
        url.scheme not in ("https", "http")
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("Supply a model base URL without credentials or a query")
    if type(model["ssl_verify"]) is not bool or not re.fullmatch(
        r"(?:[A-Za-z_][A-Za-z_0-9]*)?", model["api_key_env"]
    ):
        raise ValueError("Invalid TLS setting or credential environment variable name")
    return model


def settings(path):
    raw = read(path)
    defaults = {
        "version": 1,
        "generation_backend": "model",
        "keep_top": 1,
        "selection": "improve",
        "repetitions": 1,
        "seed": 42,
        "limits": {},
    }
    if not isinstance(raw, dict) or raw.keys() - (
        defaults.keys() | {"model", "analysis_model", "generator_model", "candidates", "generation_wall_seconds"}
    ):
        raise ValueError("Invalid study configuration or unknown field")
    if "generation_wall_seconds" in raw and (
        type(raw["generation_wall_seconds"]) is not int or raw["generation_wall_seconds"] < 1
    ):
        raise ValueError("generation_wall_seconds must be a positive integer")
    config = {**defaults, **raw}
    if (
        type(config["version"]) is not int
        or config["version"] != 1
        or config["generation_backend"] not in ("model", "claude_cli")
    ):
        raise ValueError("Expected version 1 and generation_backend model or claude_cli")
    if config["selection"] not in ("improve", "ranked"):
        raise ValueError("selection must be improve or ranked")
    counts = config.get("candidates")
    if (
        not isinstance(counts, dict)
        or counts.keys() - set(KINDS)
        or any(type(n) is not int or n < 0 for n in counts.values())
    ):
        raise ValueError("candidates must map supported artifact types to nonnegative integer counts")
    config["candidates"] = {k: counts.get(k, 0) for k in sorted(KINDS)}
    config["model"] = model_settings(config.get("model"))
    config["analysis_model"] = model_settings(config.get("analysis_model", config["model"]))
    config["generator_model"] = model_settings(config.get("generator_model", config["model"]))
    for key, minimum in (("keep_top", 0), ("repetitions", 1)):
        if type(config[key]) is not int or config[key] < minimum:
            raise ValueError(f"{key} must be an integer of at least {minimum}")
    if type(config["seed"]) is not int:
        raise ValueError("seed must be an integer")
    limits = {"max_turns": 8, "context_window": 8192, "wall_seconds": 120, "tool_timeout": 30}
    if not isinstance(config["limits"], dict) or config["limits"].keys() - limits.keys():
        raise ValueError("Unknown trial limit")
    limits.update(config["limits"])
    if any(type(n) is not int or n <= 0 for n in limits.values()):
        raise ValueError("All trial limits must be positive integers")
    config["limits"] = limits
    return config


def checked_file(root, name, fingerprint):
    p = root / name
    if p.resolve() != root.resolve() / name or not p.is_file():
        raise ValueError(f"Expected an ordinary file inside the instance: {name}")
    blob = p.read_bytes()
    if sha256(blob).hexdigest() != fingerprint:
        raise ValueError(f"Frozen file hash mismatch: {name}")
    return blob


def load_instance(instance, *, for_review=False):
    host = instance / "host"
    suite = host / "suite"
    receipt = read(host / "build-receipt.json")
    manifest = read(suite / "manifest.json")
    package_hash = manifest["package_hash"]
    task = manifest.get("id")
    if (
        task not in REVIEW_FILES
        or manifest.get("format") != "scenarioforge-evaluation"
        or receipt["evaluation_package_hash"] != package_hash
        or digest({k: v for k, v in manifest.items() if k != "package_hash"}) != package_hash
    ):
        raise ValueError("Expected a matching frozen ScenarioForge evidence case")
    if task in (CATALOG_TASK, CATALOG_FIVE_TASK, THREE_CHAINS_TASK) and not for_review:
        raise ValueError("Dispatch this catalog evidence case to its registered live CORE readers")
    files = {
        name: checked_file(instance / "participant", name, receipt["participant_sha256"][name])
        for name in REVIEW_FILES[task]
    }
    if sha256(files["tasks.json"]).hexdigest() != manifest["files"]["participant/tasks.json"]:
        raise ValueError("Participant task differs from the evaluation package")
    tasks = json.loads(files["tasks.json"])
    if len(tasks) != 1 or tasks[0]["id"] != task:
        raise ValueError("Expected one task matching the evaluation package")
    name = "evaluator/verifiers.json"
    verifier = json.loads(checked_file(suite, name, manifest["files"][name]))[task]
    flags = set(verifier["expected"].values())
    flag_pattern = r"FLAG\{[0-9a-f]{20}\}" if task in (CATALOG_TASK, CATALOG_FIVE_TASK, THREE_CHAINS_TASK) else r"FLAG\{[0-9a-f]{24}\}"
    expected_count = 5 if task in (CATALOG_FIVE_TASK, THREE_CHAINS_TASK) else 2
    if (
        verifier["type"] != "flags_found"
        or len(flags) != expected_count
        or not all(re.fullmatch(flag_pattern, f) for f in flags)
    ):
        raise ValueError("Expected two distinct native handoff flags")
    return files, flags, package_hash


def plan(config):
    counts = config["candidates"]
    active = sum(v for k, v in counts.items() if k != "lora_suggestion")
    return {
        "candidates": counts,
        "keep_top": config["keep_top"],
        "selection": config["selection"],
        "repetitions": config["repetitions"],
        "generation_backend": config["generation_backend"],
        "max_participant_trials": (2 + active) * config["repetitions"],
        "flags_per_trial": 2,
        "case_scope": "Same frozen case for baseline, individual evaluation and fresh confirmation",
    }


def sources():
    base = Path(__file__).resolve().parent
    deps = {}
    for package in ("mcp", "cryptography", "requests", "ollama", "PyYAML"):
        try:
            deps[package] = version(package)
        except PackageNotFoundError:
            deps[package] = None
    names = (
        "mcp_client.py",
        "session_logger.py",
        "claude_generation.py",
        "post_run_analysis.py",
        "app.py",
        "artifact_catalog.py",
        "artifact_store.py",
        "generated_artifacts.py",
        "gen_tool_tests.py",
    )
    files = {*base.glob("evidence_*.py"), *(base / name for name in names)}
    return {
        "code": {p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(files)},
        "python": sys.version,
        "dependencies": deps,
    }


def tree_hash(root):
    hashes = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Unexpected link in study output: {path}")
        if path.is_file():
            hashes[str(path.relative_to(root))] = sha256(path.read_bytes()).hexdigest()
    return digest(hashes)


def checkpoint(folder, operation):
    folder.mkdir(parents=True, exist_ok=True)
    stage_id = folder.parent.name + "/" + folder.name
    done = folder / "stage.json"
    if done.exists():
        item = read(done)
        name = item["attempt"]
        if not re.fullmatch(r"attempt-\d+", name):
            raise ValueError(f"Invalid checkpoint in {folder}")
        attempt = folder / name
        if (
            item.get("stage") != stage_id
            or not attempt.is_dir()
            or digest([stage_id, tree_hash(attempt), item["result"]]) != item["sha256"]
        ):
            raise ValueError(f"Checkpoint content changed in {folder}")
        return attempt, item["result"]
    count = max(
        (int(p.name.split("-")[1]) for p in folder.glob("attempt-*") if p.name[8:].isdigit()), default=0
    )
    attempt = folder / f"attempt-{count + 1:04d}"
    attempt.mkdir()
    print(folder.name, flush=True)
    result = operation(attempt)
    write(
        done,
        {
            "stage": stage_id,
            "attempt": attempt.name,
            "result": result,
            "sha256": digest([stage_id, tree_hash(attempt), result]),
        },
    )
    return attempt, result


def score(result, flags):
    status = result["status"]
    if status == "completed" and result.get("turn_budget_exhausted"):
        status = "budget_exceeded"
    if status not in ("completed", "timeout", "budget_exceeded"):
        raise RuntimeError(f"Participant worker returned {status}; inspect attempt and resume")
    try:
        answer = json.loads(result["final_answer"]) if status == "completed" else None
    except (ValueError, TypeError):
        answer = None
    valid = (
        isinstance(answer, dict)
        and set(answer) == {"flags"}
        and isinstance(answer["flags"], list)
        and all(isinstance(f, str) for f in answer["flags"])
    )
    submitted = set(answer["flags"]) if valid else set()
    return {
        "status": status,
        "valid_format": valid,
        "flags_recovered": len(flags & submitted),
        "flags_in_answer": sum(flag in result["final_answer"] for flag in flags)
        if isinstance(result.get("final_answer"), str)
        else None,
        "flags_available": len(flags),
        "incorrect_submissions": len(submitted - flags),
        "duplicate_submissions": len(answer["flags"]) - len(submitted) if valid else 0,
        "model_calls": result.get("model_calls"),
        "tool_calls": result.get("tool_calls"),
        "tool_calls_by_name": result.get("tool_calls_by_name", {}),
        "elapsed_seconds": result.get("elapsed_seconds"),
    }


def summarize(rows):
    return {
        key: sum(row[key] for row in rows)
        for key in ("flags_recovered", "flags_available", "incorrect_submissions")
    }


def rank(scores, baseline, config):
    order = sorted(
        scores, key=lambda n: (-scores[n]["flags_recovered"], scores[n]["incorrect_submissions"], n)
    )
    eligible = [
        n
        for n in order
        if config["selection"] == "ranked" or scores[n]["flags_recovered"] > baseline["flags_recovered"]
    ]
    selected = eligible[: config["keep_top"]]
    return {
        "ranked": order,
        "selected": selected,
        "selection": config["selection"],
        "keep_top": config["keep_top"],
    }


def condition_artifacts(enabled):
    if isinstance(enabled, dict):
        enabled = enabled.values()
    guidance = "\n\n".join(c["markdown"] for c in enabled if c["kind"] in ("skill", "playbook"))
    tools = [c for c in enabled if c["kind"] == "tool"]

    return guidance, tools


def run_condition(output, kit, flags, config, label, rep, enabled):
    guidance, tools = condition_artifacts(enabled)

    def perform(attempt):
        return score(
            run_trial(
                kit,
                attempt / "worker",
                config["model"],
                guidance=guidance,
                tools=tools,
                limits=config["limits"],
            ),
            flags,
        )

    attempt, result = checkpoint(output / "trials" / f"{label}-{rep:03d}", perform)
    return attempt, dict(result, condition=label, repetition=rep, attempt=str(attempt.relative_to(output)))


def generate_candidate(directory, kind, analysis, config, flags, index, previous):
    limits = dict(config["limits"])
    if "generation_wall_seconds" in config:
        limits["wall_seconds"] = config["generation_wall_seconds"]

    def generate(attempt):
        try:
            proposal = propose_candidate(
                kind,
                analysis,
                attempt / "generation",
                config["generator_model"],
                limits,
                index=index,
                previous=tuple(previous),
                backend=config["generation_backend"],
            )
            item = validate_candidate(kind, proposal)
            if any(f[5:-1].casefold() in json.dumps(item).casefold() for f in flags):
                raise ValueError("Candidate contains an answer from the current instance")
            save_candidate(attempt / "artifact", item)
        except (ValueError, TimeoutError) as exc:
            # The model used its generation opportunity. Host or transport failures propagate.
            reason = (
                type(exc).__name__
                if any(f[5:-1].casefold() in str(exc).casefold() for f in flags)
                else str(exc)
            )
            return {"kind": kind, "status": "rejected", "reason": reason[:320]}
        return {"kind": kind, "status": "advisory" if kind == "lora_suggestion" else "validated"}

    return checkpoint(directory, generate)


def conduct(output, kit, flags, config):
    limits = config["limits"]
    reps = config["repetitions"]

    def participant(label, rep, enabled):
        return run_condition(output, kit, flags, config, label, rep, enabled)

    base_runs = [participant("baseline", rep, []) for rep in range(1, reps + 1)]
    baseline = summarize([result for _, result in base_runs])
    analyses = []
    if any(config["candidates"].values()):
        for i, (path, _) in enumerate(base_runs, 1):

            def analyze(attempt):
                return analyze_trial(path / "worker", attempt / "analyst", config["analysis_model"], limits)

            _, result = checkpoint(output / "analysis" / f"baseline-{i:03d}", analyze)
            analysis = result["analysis"]
            for flag in flags:
                analysis = re.sub(re.escape(flag[5:-1]), "[redacted]", analysis, flags=re.IGNORECASE)
            analyses.append(analysis)
    candidates, catalog = {}, {}
    seen = {}
    for kind, count in config["candidates"].items():
        previous = []
        for i in range(1, count + 1):
            name = f"{kind}-{i:03d}"

            path, record = generate_candidate(
                output / "candidates" / name, kind, "\n\n".join(analyses), config, flags, i, previous
            )
            catalog[name] = dict(record, attempt=str(path.relative_to(output)))
            if record["status"] == "rejected":
                continue
            item = load_candidate(path / "artifact")
            catalog[name]["artifact"] = str((path / "artifact").relative_to(output))
            previous.append(item["name"])
            # Label changes alone do not make a different intervention.
            identity = digest({k: v for k, v in item.items() if k not in ("name", "description")})
            if identity in seen:
                catalog[name]["duplicate_of"] = seen[identity]
                continue
            seen[identity] = name
            if record["status"] == "validated":
                candidates[name] = item
    order = [(name, r) for name in candidates for r in range(1, reps + 1)]
    random.Random(config["seed"]).shuffle(order)
    rows = {name: [] for name in candidates}
    for name, rep in order:
        _, result = participant(name, rep, [candidates[name]])
        rows[name].append(result)
    scores = {name: summarize(values) for name, values in rows.items()}
    decision = dict(rank(scores, baseline, config), individual=scores, baseline=baseline, candidates=catalog)
    freeze = output / "selection.json"
    if freeze.exists() and read(freeze) != decision:
        raise ValueError("Saved selection differs from recovered stage results")
    if not freeze.exists():
        write(freeze, decision)
    enabled = [candidates[name] for name in decision["selected"]]
    confirm_rows = [participant("confirmation", rep, enabled)[1] for rep in range(1, reps + 1)]
    confirmation = summarize(confirm_rows)
    report = {
        "case": TASK,
        "metric": "flags_recovered",
        "scope": plan(config)["case_scope"],
        "repetitions": reps,
        "baseline": baseline,
        "individual": scores,
        "retained": decision["selected"],
        "confirmation": confirmation,
        "additional_flags": confirmation["flags_recovered"] - baseline["flags_recovered"],
        "selection_sha256": digest(decision),
        "candidates": catalog,
        "baseline_rows": [result for _, result in base_runs],
        "individual_rows": rows,
        "confirmation_rows": confirm_rows,
    }
    write(output / "report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instance", type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args(argv)
    config = settings(args.config)
    public, flags, package_hash = load_instance(args.instance.resolve())
    if args.plan:
        print(json.dumps(plan(config), indent=2))
        return 0
    if not args.output:
        parser.error("--output is required for a run")
    output = args.output.resolve()
    if output.is_relative_to(args.instance.resolve()):
        raise ValueError("Use a study directory outside the input instance")
    manifest = {
        "version": 1,
        "configuration": config,
        "package_hash": package_hash,
        "plan": plan(config),
        "participant_sha256": {k: sha256(v).hexdigest() for k, v in public.items()},
        "runtime": sources(),
    }
    if not args.resume:
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
    elif not (output / "manifest.json").is_file():
        raise ValueError("Cannot resume without the original manifest")
    with (output / ".study.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        kit = output / "participant"
        if args.resume:
            if read(output / "manifest.json") != manifest:
                raise ValueError("Instance, configuration or CAF source changed; use a new output directory")
            for name, fingerprint in manifest["participant_sha256"].items():
                checked_file(kit, name, fingerprint)
        else:
            kit.mkdir()
            for name, blob in public.items():
                (kit / name).write_bytes(blob)
            write(output / "manifest.json", manifest)
        report = conduct(output, kit, flags, config)
    print(
        json.dumps(
            {k: report[k] for k in ("baseline", "retained", "confirmation", "additional_flags")}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"Study error: {exc}", file=sys.stderr)
        raise SystemExit(2)
