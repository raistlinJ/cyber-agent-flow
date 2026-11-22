"""CAF artifact contracts for the read-only Alderbank case-file experiment."""

from hashlib import sha256
import json
from pathlib import Path
import re
import tempfile

from artifact_catalog import validate_document_files
from generated_artifacts import publish_artifact
from gen_tool_tests import artifact_files, write_report

KINDS = ("playbook", "tool", "skill", "lora_suggestion")
FLAG = re.compile(r"(?<![\w{])FLAG\{[A-Za-z0-9_-]+\}(?![\w}])")
LITERAL_FLAG = re.compile(r"FLAG\{[A-Za-z0-9_-]+\}")
MAX_TOOL_INPUT = 128 * 1024


def proposal_instructions(kind):
    """Specify exactly one model-authored candidate. Field names match validation."""
    if kind not in KINDS:
        raise ValueError("Unknown evidence artifact type")
    instructions = (
        'Return one JSON object. Use a lowercase, hyphen-separated slug of at most 64 characters for "name". '
        'Use one short sentence in "description". Omit literal flag values, keys, unique records and answers. '
    )
    if kind == "tool":
        return instructions + (
            'Create a tool for text already supplied by the participant. For "operation": "unique_flags", '
            "the exact fields are name, description, operation. It extracts distinct complete flag strings in order. "
            'For "operation": "matching_lines", also supply "keyword", a literal word or phrase to find '
            "case-insensitively. The tool returns matching input lines in order. No code or commands."
        )
    purpose = {
        "playbook": "Give a reusable case-file review procedure, prerequisites, and a completion check.",
        "skill": "Explain when to use this instruction-only skill, its steps, and an example. Frontmatter is added by CAF.",
        "lora_suggestion": "Propose a LoRA training objective, suitable evidence, and a held-out evaluation. Mark it as a proposal.",
    }
    return instructions + 'The exact fields are "name", "description", and "markdown". ' + purpose[kind]


def _text(value, maximum):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise ValueError(f"Expected nonempty text of at most {maximum} characters")
    if LITERAL_FLAG.search(value) or "\x00" in value:
        raise ValueError("Evidence artifacts cannot contain literal flags or NUL characters")
    return value.strip()


def validate_candidate(kind, proposal):
    """Normalize one closed-schema proposal, or raise ValueError before use."""
    if kind not in KINDS or not isinstance(proposal, dict) or proposal.get("kind", kind) != kind:
        raise ValueError("Invalid evidence artifact kind or proposal")
    name = _text(proposal.get("name"), 64)
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise ValueError("Use a lowercase alphanumeric, hyphen-separated artifact name")
    item = {"kind": kind, "name": name, "description": _text(proposal.get("description"), 512)}
    if kind == "tool":
        operation = proposal.get("operation")
        if operation not in ("unique_flags", "matching_lines"):
            raise ValueError("Unsupported text operation")
        item["operation"] = operation
        if operation == "matching_lines":
            keyword = _text(proposal.get("keyword"), 48)
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 -]*", keyword):
                raise ValueError("Use an ordinary literal word or phrase for the tool keyword")
            item["keyword"] = keyword
    else:
        item["markdown"] = _text(proposal.get("markdown"), 16_000)
    if set(proposal) | {"kind"} != set(item):
        raise ValueError("Unexpected fields in evidence artifact")
    return item


def use_tool(tool_dict, text):
    """Run a declared text operation entirely on the caller's supplied text."""
    tool = validate_candidate("tool", tool_dict)
    if not isinstance(text, str) or len(text) > MAX_TOOL_INPUT:
        raise ValueError(f"Supply text of at most {MAX_TOOL_INPUT} characters")
    if tool["operation"] == "unique_flags":
        return "\n".join(dict.fromkeys(FLAG.findall(text)))
    keyword = tool["keyword"].casefold()
    return "\n".join(line for line in text.splitlines() if keyword in line.casefold())


def _tool_checks(tool):
    # Expectations are independent of the model proposal and its development traces.
    if tool["operation"] == "unique_flags":
        fixtures = [
            ("distinct-in-order", "FLAG{demo_b} followed by FLAG{demo_a}", "FLAG{demo_b}\nFLAG{demo_a}"),
            ("duplicates", "FLAG{demo_b}\nFLAG{demo_b}", "FLAG{demo_b}"),
            ("boundaries", "xFLAG{demo} FLAG{demo}_x FLAG{demo}!", "FLAG{demo}"),
            ("empty-or-malformed", "flag{demo} FLAG{missing end", ""),
        ]
    else:
        keyword = tool["keyword"]
        match = "137 " + keyword.upper()
        fixtures = [
            ("case-insensitive", "123\n" + match, match),
            ("preserve-order", keyword + "\n123\n" + match, keyword + "\n" + match),
            ("preserve-duplicates", keyword + "\n" + keyword, keyword + "\n" + keyword),
            ("no-match", "123\n456", ""),
        ]
    checks = [{"name": name, "passed": use_tool(tool, text) == expected} for name, text, expected in fixtures]
    if not all(case["passed"] for case in checks):
        raise ValueError("Evidence tool failed fixed functional checks")
    return checks


def _json(obj):
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _files_and_checks(candidate):
    kind = candidate["kind"]
    name = candidate["name"]
    if kind == "tool":
        checks = _tool_checks(candidate)
        files = {"tool.json": _json(candidate)}
    else:
        body = candidate["markdown"] + "\n"
        if kind == "skill":
            description = json.dumps(candidate["description"], ensure_ascii=False)
            document = f"---\nname: {name}\ndescription: {description}\n---\n\n{body}"
            files = validate_document_files("skill", {"SKILL.md": document}, name)
        elif kind == "playbook":
            files = validate_document_files("playbook", {"playbook.md": body}, name)
        else:
            checked = validate_document_files("markdown", {"document.md": body}, name)
            files = {"suggestion.md": checked["document.md"]}
        checks = [{"name": "CAF document validation", "passed": True}]
    files["candidate.json"] = _json(candidate)
    return files, checks


def _report(candidate, files, checks):
    return {
        "status": "passed",
        "kind": candidate["kind"],
        "name": candidate["name"],
        "artifact_sha256": sha256(files["candidate.json"].encode()).hexdigest(),
        "file_sha256": {n: sha256(v.encode()).hexdigest() for n, v in files.items()},
        "cases": checks,
    }


def save_candidate(directory, normalized):
    """Publish one validated immutable bundle at a previously unused path."""
    candidate = validate_candidate(normalized.get("kind"), normalized)
    files, checks = _files_and_checks(candidate)
    report = _report(candidate, files, checks)
    target = Path(directory)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as staging:
        package = Path(staging) / "package"
        publish_artifact(package, files)
        write_report(package / "validation.json", report)
        package.rename(target)
    return report


def load_candidate(directory):
    """Check stored content and rerun functional checks before returning an artifact."""
    path = Path(directory)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Invalid candidate directory")
    paths = {item.relative_to(path).as_posix(): item for item in artifact_files(path)}
    if "candidate.json" not in paths or "validation.json" not in paths:
        raise ValueError("Missing evidence artifact or validation report")
    saved = json.loads(paths["candidate.json"].read_text(encoding="utf-8"))
    candidate = validate_candidate(saved.get("kind") if isinstance(saved, dict) else None, saved)
    files, checks = _files_and_checks(candidate)
    if {p.name for p in path.iterdir()} != set(files) | {"validation.json"}:
        raise ValueError("Unexpected files in saved artifact bundle")
    if any(paths[name].read_bytes() != content.encode() for name, content in files.items()):
        raise ValueError("Saved evidence artifact content changed")
    if json.loads(paths["validation.json"].read_text(encoding="utf-8")) != _report(candidate, files, checks):
        raise ValueError("Saved validation report differs from independent checks")
    return candidate
