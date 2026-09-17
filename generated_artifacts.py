"""Validate model-generated files before publishing any artifact."""

import json
import os
from pathlib import PurePosixPath
import re
import tempfile
from gen_tool_test_env.suite import validate_suite


def parse_tool_files(response_text, *, require_tests=False):
    blocks = re.findall(
        r"^###\s+FILE:[ \t]*(.+?)\s*\n```[^\n]*\n(.*?)^```[ \t]*(?=\n|$)",
        response_text.replace("\r\n", "\n"), re.MULTILINE | re.DOTALL,
    )
    if not blocks:
        raise ValueError("Model response did not contain any ### FILE: blocks.")
    files = {}
    for raw_name, content in blocks:
        name = raw_name.strip()
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or "\\" in name or ":" in name
                or any(part in {"", ".", ".."} for part in name.split("/"))
                or any(ord(char) < 32 for char in name)):
            raise ValueError("Generated file path must be a safe relative path.")
        if name in files or name == "PROVENANCE.md":
            raise ValueError("Duplicate or reserved generated filename.")
        files[name] = content

    return validate_tool_files(files, require_tests=require_tests)


def validate_file_paths(files):
    for name in files:
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or "\\" in name or ":" in name
                or any(part in {"", ".", ".."} for part in name.split("/"))
                or any(ord(char) < 32 for char in name)
                or name in {"PROVENANCE.md", "CLAUDE.md"} or ".claude" in path.parts):
            raise ValueError("Generated file path must be a safe, non-reserved relative path.")
    for name in files:
        if any(str(parent) in files for parent in PurePosixPath(name).parents):
            raise ValueError("Generated file paths conflict with a directory.")


def validate_tool_files(files, *, require_tests=False):
    files = dict(files)
    validate_file_paths(files)
    if "manifest.json" not in files:
        raise ValueError("Model response did not include a manifest.json file.")
    try:
        manifest = json.loads(files["manifest.json"])
    except json.JSONDecodeError as exc:
        raise ValueError("Generated manifest.json is not valid JSON.") from exc
    if not isinstance(manifest, dict) or any(
        not isinstance(manifest.get(key), str) or not manifest[key].strip()
        for key in ("name", "description", "command")
    ):
        raise ValueError("Generated manifest requires a name, description, and command.")
    base_args = manifest.get("base_args", manifest.get("args", []))
    if not isinstance(base_args, list) or any(
        not isinstance(arg, str) for arg in base_args
    ):
        raise ValueError("Generated manifest base_args must be a list of strings.")
    manifest["base_args"] = base_args
    manifest.pop("args", None)
    if "allow_args" in manifest and not isinstance(manifest["allow_args"], bool):
        raise ValueError("Generated manifest allow_args must be a boolean.")
    if require_tests and "tests/suite.json" not in files:
        raise ValueError("Generated tool must include tests/suite.json and test fixtures.")
    if "tests/suite.json" in files:
        validate_suite(json.loads(files["tests/suite.json"]))
    for name, content in files.items():
        if name.endswith(".py"):
            try:
                compile(content, name, "exec")
            except (SyntaxError, ValueError) as exc:
                raise ValueError(f"Generated Python file has invalid syntax: {name}") from exc
    files["manifest.json"] = json.dumps(manifest, indent=2) + "\n"
    return files


def publish_artifact(target_path, files, *, single_file=False, before_publish=None):
    """Stage complete output; preserve the previous artifact if publishing fails."""
    parent = os.path.dirname(os.path.abspath(target_path))
    os.makedirs(parent, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".generation-", dir=parent) as work:
        staged = os.path.join(work, "artifact")
        os.mkdir(staged)
        for name, content in files.items():
            destination = os.path.join(staged, name)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            with open(destination, "w", encoding="utf-8") as handle:
                handle.write(content)
        if before_publish:
            before_publish()
        if single_file:
            os.replace(os.path.join(staged, next(iter(files))), target_path)
            return
        backup = os.path.join(work, "previous")
        exists = os.path.lexists(target_path)
        if exists:
            os.replace(target_path, backup)
        try:
            os.replace(staged, target_path)
        except Exception:
            if exists:
                os.replace(backup, target_path)
            raise
