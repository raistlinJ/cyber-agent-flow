"""Storage and validation reports for generated text/document artifacts."""
import hashlib
import json
from pathlib import Path
import re

from artifact_catalog import ARTIFACT_TYPES, DOCUMENT_KINDS, validate_document_files
from gen_tool_tests import artifact_files, write_report, timestamp


def document_path(plugins_dir, kind, name, *, must_exist=True):
    if kind not in DOCUMENT_KINDS or not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("Invalid artifact type or name.")
    root = Path(plugins_dir)
    path = root / "playbooks" / f"{name}.md" if kind == "playbook" else root / "artifacts" / kind / name
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Artifact path must remain inside the artifact library.")
    if must_exist and not (path.is_file() if kind == "playbook" else path.is_dir()):
        raise ValueError("Generated artifact not found.")
    return path


def read_document(path, kind):
    path = Path(path)
    if kind == "playbook":
        if path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("Document exceeds the 20 MiB limit.")
        return {"playbook.md": path.read_text(encoding="utf-8")}
    return {file.relative_to(path).as_posix(): file.read_text(encoding="utf-8") for file in artifact_files(path)}


def document_fingerprint(path, kind):
    return hashlib.sha256(json.dumps(read_document(path, kind), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_document(plugins_dir, kind, name):
    path = document_path(plugins_dir, kind, name)
    report = {"kind": kind, "name": name, "status": "passed", "finished_at": timestamp(),
              "checks": ARTIFACT_TYPES[kind]["checks"]}
    try:
        files = read_document(path, kind)
        report["artifact_sha256"] = document_fingerprint(path, kind)
        normalized = validate_document_files(kind, files, name)
        if kind == "rag_document" and normalized.get("chunks.jsonl") != files.get("chunks.jsonl"):
            raise ValueError("RAG chunks are missing or stale. Update the artifact with Claude to rebuild them.")
    except (ValueError, OSError) as exc:
        report.update(status="failed", message=str(exc))
    write_report(Path(plugins_dir) / "validation_results" / kind / f"{name}.json", report)
    return report


def validation_report(plugins_dir, kind, name):
    path = document_path(plugins_dir, kind, name)
    report_path = Path(plugins_dir) / "validation_results" / kind / f"{name}.json"
    if not report_path.is_file():
        return {"status": "not_tested", "kind": kind, "name": name}
    report = json.loads(report_path.read_text(encoding="utf-8"))
    try:
        report["outdated"] = report.get("artifact_sha256") != document_fingerprint(path, kind)
    except (ValueError, OSError):
        report["outdated"] = True
    return report


def list_documents(plugins_dir):
    entries = []
    for kind in sorted(DOCUMENT_KINDS):
        directory = Path(plugins_dir) / ("playbooks" if kind == "playbook" else f"artifacts/{kind}")
        if not directory.is_dir():
            continue
        for candidate in sorted(directory.iterdir()):
            if kind == "playbook" and (candidate.suffix != ".md" or candidate.name.endswith(".PROVENANCE.md")):
                continue
            name = candidate.stem if kind == "playbook" else candidate.name
            try:
                path = document_path(plugins_dir, kind, name)
                files = read_document(path, kind)
                entries.append({"kind": kind, "name": name, "label": ARTIFACT_TYPES[kind]["label"],
                                "files": sorted(files), "validation": validation_report(plugins_dir, kind, name)})
            except (OSError, ValueError):
                continue
    return entries
