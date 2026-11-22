"""Trusted local reader for ScenarioForge's Alderbank case-file handoff format."""

import hashlib
import io
import json
from pathlib import Path
import re
import sys
import zipfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from mcp.server.fastmcp import FastMCP

from evidence_artifacts import use_tool, validate_candidate

MAGIC = b"SF-CASE-NOTES\x01"
MEMBERS = ("case/README.txt", "case/chain-of-custody.txt", "case/evidence/recovery-note.txt")
MAX_FILE = 1024 * 1024


def kit_file(kit, name):
    path = Path(kit) / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE:
        raise ValueError(f"Missing or invalid public case file: {name}")
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise ValueError(f"Oversized public case file: {name}")
    return data


def case_prompt(kit):
    tasks = json.loads(kit_file(kit, "tasks.json"))
    if not isinstance(tasks, list) or len(tasks) != 1 or not isinstance(tasks[0], dict):
        raise ValueError("Expected one Alderbank handoff task")
    task = tasks[0]
    if task.get("id") != "alderbank-case-file-handoff" or task.get("family") != "case-file-handoff":
        raise ValueError("This reader supports the Alderbank case-file handoff")
    if not isinstance(task.get("prompt"), str) or not 1 <= len(task["prompt"].strip()) <= 16_000:
        raise ValueError("Invalid public task prompt")
    return task["prompt"]


def tool_name(spec):
    slug = spec["name"].replace("-", "_")
    digest = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:8]
    return f"evidence_{slug[:46]}_{digest}"


def open_notes(sealed, first_flag):
    # Implements the frozen SF-CASE-NOTES v1 envelope. Never import a reader from the kit.
    if not re.fullmatch(r"FLAG\{[A-Za-z0-9_-]{1,256}\}", first_flag):
        raise ValueError("The exact first flag is required")
    start, end = len(MAGIC), len(MAGIC) + 28
    if not sealed.startswith(MAGIC) or len(sealed) < end + 16:
        raise ValueError("Invalid sealed notes")
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=sealed[start : start + 16], info=MAGIC).derive(
        first_flag.encode()
    )
    try:
        plain = AESGCM(key).decrypt(sealed[start + 16 : end], sealed[end:], sealed[:end])
    except InvalidTag:
        raise ValueError("Case notes failed authentication") from None
    with zipfile.ZipFile(io.BytesIO(plain)) as archive:
        bodies = []
        for name in MEMBERS:
            info = archive.getinfo(name)
            if info.file_size > MAX_FILE:
                raise ValueError("Oversized case note")
            bodies.append(f"{name}\n{archive.read(info).decode('utf-8')}")
        return "\n".join(bodies)


def create_server(kit, tools):
    case_prompt(kit)
    ticket = kit_file(kit, "handoff-ticket.txt").decode("utf-8")
    sealed = kit_file(kit, "case-notes.sealed")
    disclosed = set()
    server = FastMCP("alderbank-case-files")

    @server.tool()
    def read_ticket() -> str:
        """Read the incident handoff ticket."""
        disclosed.add(ticket)
        return ticket

    @server.tool()
    def open_case_notes(first_flag: str) -> str:
        """Read the archived case notes with the exact first flag recovered from the ticket."""
        notes = open_notes(sealed, first_flag)
        disclosed.add(notes)
        return notes

    def register(spec):
        def process(text: str) -> str:
            if not text or not any(text in source for source in disclosed):
                raise ValueError("Supply text previously read in this session")
            return use_tool(spec, text)

        server.tool(name=tool_name(spec), description=spec["description"])(process)

    names = set()
    for raw in tools:
        spec = validate_candidate("tool", raw)
        name = tool_name(spec)
        if name not in names:
            register(spec)
            names.add(name)
    return server


if __name__ == "__main__":
    kit, tool_specs = sys.argv[1:]
    create_server(kit, json.loads(Path(tool_specs).read_text())).run(transport="stdio")
