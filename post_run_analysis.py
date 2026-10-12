"""Headless post-run analysis used by the orchestrator and CAF operators.

The input contains participant-visible evidence only.  The command writes its
result to a caller-selected file so model/library chatter on stdout cannot
corrupt the machine-readable response.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_HELPER_CHARS = 16_000


def extract_trial_helper(markdown: str) -> str:
    """Return the generated helper section from a structured CAF analysis."""
    match = re.search(
        r"(?im)^#{1,6}\s+Generated Trial Helper\s*$\n?(.*?)(?=^#{1,6}\s+|\Z)",
        str(markdown or ""),
        re.DOTALL,
    )
    helper = match.group(1).strip() if match else ""
    if len(helper) < 40:
        raise ValueError("CAF analysis did not produce a usable Generated Trial Helper section")
    if len(helper) > MAX_HELPER_CHARS:
        raise ValueError("Generated Trial Helper exceeds the supported size")
    # A generated helper is process guidance, never an answer key.  Keep this
    # guard even though the analysis prompt also forbids secret disclosure.
    forbidden = [
        r"FLAG\{[^}\r\n]+\}",
        r"(?i)\b(?:password|passwd)\s*[:=]\s*[^\s`]+",
        r"(?i)\b(?:api[_ -]?key|access[_ -]?token)\s*[:=]\s*[^\s`]+",
    ]
    for pattern in forbidden:
        if re.search(pattern, helper):
            raise ValueError("Generated Trial Helper contains answer-like secret material")
    return helper


def _bounded_text(value, name, limit):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"Invalid {name}")
    return value


def _load_input(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("Invalid post-run analysis input")
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or set(value) != {
        "run_id", "transcript", "annotations", "tool_calls", "metadata", "model"
    }:
        raise ValueError("Invalid post-run analysis fields")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", value["run_id"]):
        raise ValueError("Invalid analysis run ID")
    _bounded_text(value["transcript"], "transcript", 2_500_000)
    _bounded_text(value["annotations"], "annotations", 500_000)
    if not isinstance(value["tool_calls"], list) or len(value["tool_calls"]) > 2_000:
        raise ValueError("Invalid tool-call evidence")
    if not isinstance(value["metadata"], dict) or not isinstance(value["model"], dict):
        raise ValueError("Invalid analysis metadata")
    model = value["model"]
    if set(model) != {"provider", "name", "url", "ssl_verify", "api_key_env"}:
        raise ValueError("Invalid analysis model fields")
    for key in ("provider", "name", "url"):
        _bounded_text(model[key], f"model {key}", 2048)
    if type(model["ssl_verify"]) is not bool:
        raise ValueError("Invalid model ssl_verify")
    if not isinstance(model["api_key_env"], str) or (model["api_key_env"] and not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]{0,127}", model["api_key_env"]
    )):
        raise ValueError("Invalid model API-key environment variable")
    return value


def run(input_path: Path, output_path: Path) -> dict:
    value = _load_input(input_path)
    model = value["model"]
    api_key = os.environ.get(model["api_key_env"]) if model["api_key_env"] else None

    with tempfile.TemporaryDirectory(prefix="caf-post-analysis-") as temporary:
        root = Path(temporary)
        session = root / value["run_id"]
        calls = session / "tool_calls"
        calls.mkdir(parents=True)
        (session / "transcript.md").write_text(value["transcript"])
        (session / "annotations.jsonl").write_text(value["annotations"])
        metadata = dict(value["metadata"], model=model["name"], ollama_url=model["url"],
                        llm_provider=model["provider"], ssl_verify=model["ssl_verify"])
        (session / "metadata.json").write_text(json.dumps(metadata))
        for index, record in enumerate(value["tool_calls"], 1):
            if not isinstance(record, dict):
                raise ValueError("Invalid tool-call record")
            (calls / f"{index:04d}_evidence.json").write_text(json.dumps(record))

        import app as caf_app

        caf_app.RUNS_DIR = str(root)
        result = caf_app._perform_llm_analysis(
            value["run_id"],
            "Entire Session",
            ollama_url_override=model["url"],
            model_override=model["name"],
            analysis_outputs=["progress_analysis", "tooling_assets", "trial_helper"],
            api_key_override=api_key,
            llm_provider_override=model["provider"],
            ssl_verify_override=model["ssl_verify"],
        )
    response = result["response"]
    payload = {
        "version": 1,
        "run_id": value["run_id"],
        "model": {key: model[key] for key in ("provider", "name", "url", "ssl_verify")},
        "completion_path": result.get("completion_path"),
        "analysis": response,
        "helper": extract_trial_helper(response),
        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "analysis_sha256": hashlib.sha256(response.encode()).hexdigest(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(payload, stream, indent=2)
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Analyze a completed CAF run and generate a safe rerun helper")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        run(args.input, args.output)
        return 0
    except Exception as exc:
        parser.exit(1, f"Post-run analysis failed: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
