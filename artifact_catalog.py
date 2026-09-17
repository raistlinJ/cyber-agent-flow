"""Artifact formats, generation instructions, and deterministic document validation."""
import hashlib
import json
from pathlib import PurePosixPath
import re

import yaml

from generated_artifacts import validate_file_paths


ARTIFACT_TYPES = {
    "mcp_tool": {"label": "MCP Tool", "checks": "Container tests", "instructions": ""},
    "playbook": {"label": "Markdown Playbook", "checks": "Document validation",
                 "instructions": "Create only playbook.md: complete operational guidance with prerequisites, steps, and success criteria."},
    "markdown": {"label": "Markdown Document", "checks": "Document validation",
                 "instructions": "Create only document.md: a standalone Markdown document with a title, organized sections, and source context."},
    "skill": {"label": "Agent Skill", "checks": "Skill validation",
              "instructions": "Create SKILL.md with YAML frontmatter containing name and description (what it does and when to use it), followed by actionable instructions and examples. The name must match the supplied artifact folder name. Optional supporting text files belong under references/ or assets/. Use only .md, .txt, or .json files. This is an instruction-only skill; do not generate executable scripts."},
    "rag_document": {"label": "RAG Document", "checks": "Document and chunk validation",
                     "instructions": 'Create document.md and metadata.json. The Markdown must be a self-contained knowledge document, grounded in the supplied analysis, separating evidence from recommendations and unknowns. metadata.json must be an object with a nonempty title and summary and a tags list of strings. The application generates chunks.jsonl from the document; do not create embeddings or claim the document is indexed.'},
    "template": {"label": "Reusable Template", "checks": "Template validation",
                 "instructions": "Create TEMPLATE.md with reusable {{variable_name}} placeholders, plus README.md explaining its purpose, each variable, and an example of use."},
    "structured_data": {"label": "Structured JSON", "checks": "JSON validation",
                        "instructions": "Create data.json as a nonempty JSON object or array and README.md describing the schema, source context, and how to consume it. Use only information supported by the analysis; label estimates and unknowns."},
}
DOCUMENT_KINDS = set(ARTIFACT_TYPES) - {"mcp_tool"}
PACKAGE_KINDS = DOCUMENT_KINDS - {"playbook"}


def infer_kind(explicit, prompt=""):
    aliases = {"mcp": "mcp_tool", "md": "markdown", "rag": "rag_document", "document": "markdown", "json": "structured_data"}
    if explicit:
        value = str(explicit).strip().lower()
        value = aliases.get(value, value)
        if value not in ARTIFACT_TYPES:
            raise ValueError("Unsupported artifact type.")
        return value
    match = re.search(r'\*\*Type\*\*:\s*(.+)', prompt)
    value = match[1].lower() if match else ""
    for pattern, kind in [(r"playbook", "playbook"), (r"skill", "skill"), (r"\brag\b|knowledge", "rag_document"),
                          (r"template", "template"), (r"json|structured", "structured_data"),
                          (r"markdown|\bmd\b|document", "markdown")]:
        if re.search(pattern, value):
            return kind
    return "mcp_tool"


def document_instructions(kind, name):
    if kind not in DOCUMENT_KINDS:
        raise ValueError("Unsupported document type.")
    return ARTIFACT_TYPES[kind]["instructions"] + f"\nArtifact folder name: {name}. Use UTF-8 text files."


def rag_chunks(document, title, name):
    """Derive stable, source-grounded chunks without requiring an embedding service."""
    chunks, offset = [], 0
    while offset < len(document):
        end = min(offset + 1800, len(document))
        if end < len(document):
            boundary = max(document.rfind("\n", offset + 900, end), document.rfind(" ", offset + 900, end))
            if boundary > offset:
                end = boundary
        text = document[offset:end].strip()
        if text:
            digest = hashlib.sha256(text.encode()).hexdigest()[:16]
            chunks.append({"id": f"{name}-{len(chunks) + 1}-{digest}", "text": text, "title": title,
                           "source": "document.md", "metadata_file": "metadata.json"})
        offset = end
    return "".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks)


def validate_document_files(kind, files, name):
    if kind not in DOCUMENT_KINDS:
        raise ValueError("Unsupported document type.")
    files = dict(files)
    validate_file_paths(files)
    if not files or any(not isinstance(text, str) or not text.strip() for text in files.values()):
        raise ValueError("Artifact files must contain nonempty UTF-8 text.")
    required = {"playbook": {"playbook.md"}, "markdown": {"document.md"}, "skill": {"SKILL.md"},
                "rag_document": {"document.md", "metadata.json"}, "template": {"TEMPLATE.md", "README.md"},
                "structured_data": {"data.json", "README.md"}}[kind]
    if not required.issubset(files):
        raise ValueError("Missing required files: " + ", ".join(sorted(required - files.keys())))
    allowed = required | ({"chunks.jsonl"} if kind == "rag_document" else set())
    for path in files:
        if path in allowed:
            continue
        if kind == "skill" and PurePosixPath(path).parts[0] in {"references", "assets"} and PurePosixPath(path).suffix in {".md", ".txt", ".json"}:
            continue
        raise ValueError(f"File is not supported for {kind}: {path}")
    for path, text in files.items():
        if path.endswith(".json"):
            json.loads(text)
    if kind == "skill":
        match = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", files["SKILL.md"], re.DOTALL)
        if not match or not match[2].strip():
            raise ValueError("SKILL.md requires YAML frontmatter and instruction content.")
        try:
            meta = yaml.safe_load(match[1])
        except yaml.YAMLError as exc:
            raise ValueError("SKILL.md contains invalid YAML frontmatter.") from exc
        if not isinstance(meta, dict) or meta.get("name") != name or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
            raise ValueError("Skill name must match its folder and use 1–64 lowercase letters, numbers, and single hyphens.")
        if not isinstance(meta.get("description"), str) or not 1 <= len(meta["description"].strip()) <= 1024:
            raise ValueError("Skill description must contain 1–1024 characters.")
    elif kind == "rag_document":
        metadata = json.loads(files["metadata.json"])
        if not isinstance(metadata, dict) or any(not isinstance(metadata.get(key), str) or not metadata[key].strip() for key in ("title", "summary")):
            raise ValueError("RAG metadata requires a title and summary.")
        if not isinstance(metadata.get("tags"), list) or any(not isinstance(tag, str) or not tag.strip() for tag in metadata["tags"]):
            raise ValueError("RAG metadata tags must be a list of nonempty strings.")
        files["chunks.jsonl"] = rag_chunks(files["document.md"], metadata["title"], name)
    elif kind == "template":
        variables = set(re.findall(r"\{\{([a-zA-Z][a-zA-Z0-9_]*)\}\}", files["TEMPLATE.md"]))
        if not variables or any(variable not in files["README.md"] for variable in variables):
            raise ValueError("Template requires {{variable_name}} placeholders documented in README.md.")
    elif kind == "structured_data":
        data = json.loads(files["data.json"])
        if not isinstance(data, (dict, list)) or not data:
            raise ValueError("data.json must be a nonempty object or array.")
    return files
