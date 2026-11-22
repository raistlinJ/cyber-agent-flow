"""Shared single-operator workspace for CAF's read-only evidence study interfaces."""

import argparse
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

from evidence_artifacts import KINDS
from evidence_study import read, write

PROJECT = Path(__file__).resolve().parent
ACTIONS = {
    "baseline": {"profile"},
    "study": {"profile", "counts", "keep_top", "selection", "repetitions"},
    "analyze": {"source"},
    "generate": {"source", "counts"},
    "save": {"source", "enabled", "name"},
    "run": {"source"},
}
PROFILE_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}")
JOB_ID = re.compile(r"[a-f0-9]{32}")


def workspace():
    return Path(os.environ.get("CAF_EVIDENCE_WORKSPACE", PROJECT / "eval-runs/evidence-workspace")).resolve()


def profiles():
    configured = os.environ.get("CAF_EVIDENCE_PROFILES")
    path = Path(configured or PROJECT / "eval-inputs/evidence-profiles.json").resolve()
    if not configured and not path.exists():
        return {}
    try:
        data = read(path)
        if not isinstance(data, dict):
            raise ValueError()
        result = {}
        for key, value in data.items():
            if not PROFILE_ID.fullmatch(key) or not isinstance(value, dict):
                raise ValueError()
            if not {"instance", "config"} <= value.keys() <= {"instance", "config", "source"}:
                raise ValueError()
            if any(not isinstance(v, str) or not v.strip() for v in value.values()):
                raise ValueError()
            result[key] = {name: (path.parent / item).resolve() for name, item in value.items()}
        return result
    except (OSError, ValueError) as exc:
        raise ValueError("The host evidence profile registry is unavailable or invalid") from exc


def item_dir(ident):
    if not isinstance(ident, str) or not JOB_ID.fullmatch(ident):
        raise ValueError("Invalid workspace item ID")
    return workspace() / ident


def registered(ident):
    if not isinstance(ident, str):
        raise ValueError("Choose a registered source")
    if ident.startswith("source-"):
        profile = ident[7:]
        if "source" not in profiles().get(profile, {}):
            raise ValueError("Unknown registered study")
        return {
            "id": ident,
            "profile": profile,
            "kind": "baseline",
            "name": profile,
            "status": "complete",
            "registered": True,
        }
    folder = item_dir(ident)
    if not (folder / "item.json").is_file():
        raise ValueError("Unknown workspace item")
    row = read(folder / "item.json")
    if row["status"] == "running":
        # The worker inherits this advisory lock from the submitting process.
        with (folder / "worker.lock").open("a+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return row
            row = read(folder / "item.json")
            if row["status"] == "running":
                row["status"] = "interrupted"
    return row


def source_data(item, config):
    if item.get("registered"):
        return config["source"]
    return item_dir(item["id"]) / "data"


def list_items():
    registry = profiles()
    items = [registered("source-" + key) for key, value in registry.items() if "source" in value]
    if workspace().is_dir():
        dirs = sorted(
            (f for f in workspace().iterdir() if JOB_ID.fullmatch(f.name) and (f / "item.json").is_file()),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        items.extend(registered(f.name) for f in dirs)
    return {"profiles": sorted(registry), "items": items}


def describe(ident):
    from evidence_review import inspect_review, inspect_study

    item = registered(ident)
    if item["status"] != "complete":
        return item
    config = profiles().get(item["profile"])
    if config is None:
        raise ValueError("The source profile is no longer registered")
    data = source_data(item, config)
    if item["kind"] in ("analyze", "generate"):
        detail = inspect_review(data)
    elif item["kind"] == "save":
        detail = read(item_dir(ident) / "summary.json")
    else:
        detail = inspect_study(data)
    # Project the public evidence-study fields. Internal source paths, provider
    # profiles, private answer keys and raw participant transcripts stay on the host.
    keys = (
        "case",
        "package_hash",
        "analysis",
        "baseline",
        "confirmation",
        "candidates",
        "enabled",
        "name",
        "baseline_rows",
        "confirmation_rows",
        "additional_flags",
    )
    return dict(item, detail={k: detail[k] for k in keys if k in detail})


def compare(ids):
    if (
        not isinstance(ids, list)
        or not all(isinstance(i, str) for i in ids)
        or len(set(ids)) < 2
        or len(set(ids)) != len(ids)
    ):
        raise ValueError("Choose at least two distinct completed runs")
    rows = []
    for ident in ids:
        item = describe(ident)
        if item["kind"] not in ("baseline", "study", "run") or item["status"] != "complete":
            raise ValueError("Only completed runs can be compared")
        detail = item["detail"]
        for field in ("baseline", "confirmation"):
            if not detail.get(field):
                continue
            value = detail[field]
            trials = detail.get(field + "_rows", [])
            observed = [r.get("flags_in_answer") for r in trials]
            formats = [r.get("valid_format") for r in trials]
            rows.append(
                {
                    "id": ident,
                    "name": item["name"],
                    "condition": field,
                    "case": detail.get("case"),
                    "package_hash": detail.get("package_hash"),
                    **{
                        k: value.get(k)
                        for k in ("flags_recovered", "flags_available", "incorrect_submissions")
                    },
                    "flags_in_answer": sum(observed)
                    if observed and all(type(i) is int for i in observed)
                    else None,
                    "valid_submissions": sum(formats)
                    if formats and all(type(i) is bool for i in formats)
                    else None,
                    "sessions": len(trials) if trials else None,
                }
            )
    return {"rows": rows}


def validate(action, payload):
    if action not in ACTIONS or not isinstance(payload, dict) or payload.keys() != ACTIONS[action]:
        raise ValueError("Invalid action or fields")
    if action in ("generate", "study"):
        counts = payload["counts"]
        if (
            not isinstance(counts, dict)
            or counts.keys() - set(KINDS)
            or any(type(n) is not int or n < 0 for n in counts.values())
        ):
            raise ValueError("Use nonnegative integer counts for the supported artifact types")
    if action == "study":
        for field, minimum in (("keep_top", 0), ("repetitions", 1)):
            if type(payload[field]) is not int or payload[field] < minimum:
                raise ValueError(f"Invalid {field}")
        if payload["selection"] not in ("improve", "ranked"):
            raise ValueError("Choose improve or ranked")
    if action in ("baseline", "study"):
        profile = payload["profile"]
        if not isinstance(profile, str) or profile not in profiles():
            raise ValueError("Choose a registered profile")
        return profile, None
    source = registered(payload["source"])
    allowed = {
        "analyze": ("baseline", "study", "run"),
        "generate": ("analyze",),
        "save": ("generate",),
        "run": ("save",),
    }
    if source["status"] != "complete" or source["kind"] not in allowed[action]:
        raise ValueError("The selected item is not ready for this action")
    if action == "save":
        ids = payload["enabled"]
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids) or len(ids) != len(set(ids)):
            raise ValueError("Choose distinct candidate IDs")
        if (
            not isinstance(payload["name"], str)
            or not payload["name"].isprintable()
            or not 0 < len(payload["name"].strip()) <= 120
        ):
            raise ValueError("Give this experiment a name (up to 120 characters)")
        eligible = {c["id"] for c in describe(source["id"])["detail"]["candidates"] if c.get("eligible")}
        if set(ids) - eligible:
            raise ValueError("Choose only eligible candidates from this review")
    return source["profile"], source


def study_config(payload):
    from evidence_study import settings

    validate("study", payload)
    config = settings(profiles()[payload["profile"]]["config"])
    config.update(
        candidates={k: payload["counts"].get(k, 0) for k in sorted(KINDS)},
        keep_top=payload["keep_top"],
        selection=payload["selection"],
        repetitions=payload["repetitions"],
    )
    return config


def preview(payload):
    from evidence_study import plan

    return plan(study_config(payload))


def submit(action, payload):
    profile, source = validate(action, payload)
    root = workspace()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    ident = uuid.uuid4().hex
    folder = item_dir(ident)
    folder.mkdir(mode=0o700)
    name = payload["name"].strip() if action == "save" else (source["name"] if source else profile)
    row = {
        "id": ident,
        "kind": action,
        "profile": profile,
        "name": name,
        "created": datetime.now(timezone.utc).isoformat(),
        "status": "running",
    }
    if source:
        row["source"] = source["id"]
    write(folder / "request.json", payload)
    return start_worker(row, retry=False)


def resume(ident):
    item = registered(ident)
    if item["status"] not in ("failed", "interrupted"):
        raise ValueError("Only a failed or interrupted job can be resumed")
    return start_worker(item, retry=True)


def start_worker(row, *, retry):
    ident = row["id"]
    folder = item_dir(ident)
    with (folder / "worker.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("This job is already active") from None
        if retry:
            latest = read(folder / "item.json")
            if latest["status"] not in ("running", "failed"):
                raise ValueError("This job has already finished")
        row = dict(row, status="running")
        row.pop("error", None)
        write(folder / "item.json", row)
        if row["kind"] == "save":
            execute(ident)
        else:
            try:
                subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), ident],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    pass_fds=(lock.fileno(),),
                    start_new_session=True,
                )
            except OSError:
                write(
                    folder / "item.json", dict(row, status="failed", error="Could not start the CAF worker")
                )
                raise
    return registered(ident)


def execute(ident):
    from evidence_review import analyze_study, generate_review, run_baseline, run_experiment, save_experiment

    folder = item_dir(ident)
    row = read(folder / "item.json")
    try:
        payload = read(folder / "request.json")
        cfg = profiles()[row["profile"]]
        action = row["kind"]
        data = folder / "data"
        if action == "study":
            from evidence_study import main as run_study

            config_file = folder / "study-config.json"
            if not config_file.exists():
                write(config_file, study_config(payload))
            args = [str(cfg["instance"]), "--config", str(config_file), "--output", str(data)]
            if (data / "manifest.json").is_file():
                args.append("--resume")
            if run_study(args) != 0:
                raise RuntimeError("Evidence study failed")
        elif action == "baseline":
            run_baseline(cfg["instance"], cfg["config"], data)
        else:
            parent = registered(row["source"])
            parent_data = source_data(parent, cfg)
            if action == "analyze":
                analyze_study(parent_data, cfg["instance"], cfg["config"], data)
            elif action == "generate":
                # Preserve the reviewed analysis and let users create alternate proposals.
                if not data.exists():
                    with tempfile.TemporaryDirectory(dir=folder) as staging:
                        draft = Path(staging) / "review"
                        shutil.copytree(parent_data, draft)
                        draft.rename(data)
                original = source_data(registered(parent["source"]), cfg)
                generate_review(original, cfg["instance"], cfg["config"], data, payload["counts"])
            elif action == "save":
                result = save_experiment(parent_data, payload["enabled"], data, row["name"])
                write(folder / "summary.json", result)
            elif action == "run":
                run_experiment(parent_data, cfg["instance"], cfg["config"], data)
        row["status"] = "complete"
    except Exception as exc:
        # Full diagnostics are local; exclude arbitrary model responses or private paths
        # from the browser and SSH account's shared status payload.
        write(folder / "error.json", {"type": type(exc).__name__, "error": str(exc)})
        row.update(
            status="failed", error=f"{type(exc).__name__} during {row['kind']}. See the host job diagnostics."
        )
    write(folder / "item.json", row)


def add_commands(parent):
    actions = parent.add_subparsers(dest="artifact_action", required=True)
    actions.add_parser("list", help="List study profiles, source runs, reviews and experiments")
    actions.add_parser("resume", help="Resume a failed or interrupted workspace job").add_argument("id")
    actions.add_parser("show", help="Read results or a review").add_argument("id")
    actions.add_parser("baseline", help="Start a baseline run").add_argument("profile")
    for name in ("plan", "study"):
        parser = actions.add_parser(name, help="Preview or run an automatically ranked study")
        parser.add_argument("profile")
        for kind in sorted(KINDS):
            parser.add_argument("--" + kind.replace("_", "-"), type=int, default=1, dest=kind)
        parser.add_argument("--keep-top", type=int, default=2)
        parser.add_argument("--selection", choices=("improve", "ranked"), default="improve")
        parser.add_argument("--repetitions", type=int, default=1)
    actions.add_parser("analyze", help="Analyze a completed baseline").add_argument("source")
    generate = actions.add_parser("generate", help="Generate candidates from a reviewed analysis")
    generate.add_argument("source")
    for kind in sorted(KINDS):
        generate.add_argument("--" + kind.replace("_", "-"), type=int, default=0, dest=kind)
    save = actions.add_parser("save", help="Add a reviewed configuration to runnable experiments")
    save.add_argument("source")
    save.add_argument("--name", required=True)
    save.add_argument("--enable", action="append", default=[])
    actions.add_parser("run", help="Run a saved experiment").add_argument("source")
    actions.add_parser("compare", help="Compare distinct completed runs").add_argument("ids", nargs="+")


def command(args):
    action = args.artifact_action
    if action == "list":
        return list_items()
    if action == "show":
        return describe(args.id)
    if action == "resume":
        return resume(args.id)
    if action == "compare":
        return compare(args.ids)
    if action in ("plan", "study"):
        payload = {
            "profile": args.profile,
            "counts": {k: getattr(args, k) for k in KINDS},
            "keep_top": args.keep_top,
            "selection": args.selection,
            "repetitions": args.repetitions,
        }
        return preview(payload) if action == "plan" else submit(action, payload)
    if action == "baseline":
        return submit(action, {"profile": args.profile})
    payload = {"source": args.source}
    if action == "generate":
        payload["counts"] = {k: getattr(args, k) for k in KINDS}
    if action == "save":
        payload.update(name=args.name, enabled=args.enable)
    return submit(action, payload)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CAF evidence workspace worker")
    parser.add_argument("id")
    execute(parser.parse_args().id)
