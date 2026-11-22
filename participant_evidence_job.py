"""Run reviewed evidence-only comparisons on an operator-bound participant VM."""

import argparse
import base64
import json
from pathlib import Path
import re
import tempfile

from evidence_review import condition_artifacts, load_experiment, trial_settings_digest
from evidence_study import PUBLIC, checked_file, settings, write
from evidence_worker import run_trial


def _filename(name):
    if name == "experiment.json":
        return True
    return bool(
        re.fullmatch(
            r"artifacts/(?:playbook|skill|tool)-[0-9]{3,}/(?:candidate\.json|validation\.json|SKILL\.md|playbook\.md|tool\.json)",
            name,
        )
    )


def execute(request_path, instance, config_path, result_path):
    request = json.loads(request_path.read_bytes())
    work = request_path.parent
    config = settings(config_path)
    request_files = request["files"]
    if len(request_files) > 1024 or request_path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Reviewed experiment exceeds transfer limit")
    experiment = work / "experiment"
    experiment.mkdir(mode=0o700)
    for name, content in request_files.items():
        if not _filename(name):
            raise ValueError("Unexpected reviewed artifact filename")
        file = experiment / name
        file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        file.write_bytes(base64.b64decode(content, validate=True))
    spec, assets = load_experiment(experiment)
    if spec["package_hash"] != request["package_hash"] or spec["runtime_sha256"] != trial_settings_digest(
        config
    ):
        raise ValueError("Participant configuration or scenario differs from the reviewed experiment")
    source = instance / "participant" if (instance / "participant").is_dir() else instance
    selected = [assets[name] for name in spec["enabled"]]
    records = []
    for label, enabled in (("baseline", []), ("confirmation", selected)):
        guidance, tools = condition_artifacts(enabled)
        for rep in range(1, config["repetitions"] + 1):
            # Re-read the mounted evidence for each session. Only these three public files enter CAF.
            trial = work / "trials" / f"{label}-{rep:03d}" / "attempt-0001"
            trial.mkdir(parents=True)
            with tempfile.TemporaryDirectory(dir=trial) as temp:
                kit = Path(temp)
                for name in PUBLIC:
                    (kit / name).write_bytes(checked_file(source, name, spec["participant_sha256"][name]))
                outcome = run_trial(
                    kit,
                    trial / "worker",
                    config["model"],
                    guidance=guidance,
                    tools=tools,
                    limits=config["limits"],
                )
            # Provider error details and transcripts remain with the participant.
            fields = (
                "status",
                "turn_budget_exhausted",
                "final_answer",
                "elapsed_seconds",
                "tool_calls",
                "tool_calls_by_name",
                "model_calls",
            )
            records.append(
                {
                    "condition": label,
                    "repetition": rep,
                    "worker": {key: outcome[key] for key in fields if key in outcome},
                }
            )
    write(result_path, {"package_hash": spec["package_hash"], "enabled": spec["enabled"], "rows": records})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("request", "instance", "config", "response"):
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    execute(args.request, args.instance, args.config, args.response)
