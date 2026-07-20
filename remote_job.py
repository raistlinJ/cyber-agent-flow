#!/usr/bin/env python3
"""Durable, SSH-friendly CyberAgentFlow remote job runner.

The runner deliberately has no HTTP server.  A job is a directory containing
an immutable specification, an append-only JSONL event journal, request files,
and an atomically replaced state document.  Clients can safely reconnect and
replay events by sequence through ordinary SSH/SFTP operations.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import traceback
from typing import Any

from mcp_client import MCPSession


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(_json_safe(data), separators=(",", ":")), encoding="utf-8")
    os.replace(temp, path)


def _load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else (default or {})
    except (OSError, json.JSONDecodeError):
        return default or {}


class EventJournal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.sequence = 0
        if path.exists():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    self.sequence = max(self.sequence, int(json.loads(line).get("sequence") or 0))
                except (ValueError, TypeError, json.JSONDecodeError):
                    pass

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        self.sequence += 1
        record = {
            "sequence": self.sequence,
            "timestamp": time.time(),
            **_json_safe(event),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record


def _state_path(job_dir: Path) -> Path:
    return job_dir / "state.json"


def _update_state(job_dir: Path, **updates: Any) -> dict[str, Any]:
    state = _load_json(_state_path(job_dir))
    state.update(updates)
    state["updated_at"] = time.time()
    _atomic_json(_state_path(job_dir), state)
    return state


def _request_files(job_dir: Path) -> list[Path]:
    return sorted((job_dir / "requests").glob("*.json"))


async def _worker(job_dir: Path) -> int:
    spec = _load_json(job_dir / "spec.json")
    journal = EventJournal(job_dir / "events.jsonl")
    current_prompt_id: str | None = None

    def emit(event: dict[str, Any]) -> None:
        payload = dict(event or {})
        if current_prompt_id:
            payload["prompt_id"] = current_prompt_id
        journal.append(payload)

    try:
        tools_path = str(spec["tools_config_path"])
        os.environ["CAF_TOOLS_CONFIG_PATH"] = tools_path
        os.environ["MCP_CURRENT_RUN_ID"] = str(spec["run_id"])
        _update_state(job_dir, status="starting", pid=os.getpid(), run_id=spec["run_id"], error="")
        emit({"type": "status", "message": f"Starting remote CAF job {spec['job_id']} …"})
        session = MCPSession(
            ollama_url=spec["url"], llm_provider=spec["provider"], api_key=spec.get("api_key") or None,
            ssl_verify=bool(spec.get("ssl_verify", True)), model=spec["model"],
            server_command=spec["server_command"], run_id=spec["run_id"], event_callback=emit,
            context_window=int(spec.get("context_window") or 8192), max_turns=int(spec.get("max_turns") or 20),
            tool_timeout=int(spec.get("tool_timeout") or 120), network_policy=spec.get("network_policy") or {"allow": ["*"], "disallow": []},
            auto_approve_dangerous=bool(spec.get("auto_approve_dangerous")),
        )
        tools = await session.start()
        _update_state(job_dir, status="ready", tools=tools)
        emit({"type": "job_ready", "tools": tools})
        handled: set[str] = set()
        while True:
            if (job_dir / "cancel.json").exists() or (job_dir / "close.json").exists():
                break
            requests = [path for path in _request_files(job_dir) if path.name not in handled]
            if not requests:
                await asyncio.sleep(0.2)
                continue
            request_path = requests[0]
            request = _load_json(request_path)
            if not request.get("prompt_id") or not request.get("prompt"):
                await asyncio.sleep(0.1)
                continue
            handled.add(request_path.name)
            current_prompt_id = str(request["prompt_id"])
            _update_state(job_dir, status="running", prompt_id=current_prompt_id)
            emit({"type": "prompt_started", "prompt_id": current_prompt_id})
            cancel_event = asyncio.Event()
            task = asyncio.create_task(session.chat(
                str(request["prompt"]), cancel_event=cancel_event,
                scope=request.get("scope"), urgency=request.get("urgency"),
            ))
            while not task.done():
                if (job_dir / "cancel.json").exists():
                    cancel_event.set()
                await asyncio.sleep(0.2)
            await task
            emit({"type": "prompt_done", "prompt_id": current_prompt_id})
            current_prompt_id = None
            _update_state(job_dir, status="ready", prompt_id=None)
        await session.stop()
        cancelled = (job_dir / "cancel.json").exists()
        _update_state(job_dir, status="cancelled" if cancelled else "completed", prompt_id=None)
        emit({"type": "job_done", "message": "Remote CAF job cancelled." if cancelled else "Remote CAF job completed."})
        return 0
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        _update_state(job_dir, status="failed", error=detail)
        journal.append({"type": "error", "message": detail})
        journal.append({"type": "job_done", "message": "Remote CAF job failed."})
        traceback.print_exc()
        return 1


def _start(job_dir: Path) -> int:
    spec = _load_json(job_dir / "spec.json")
    if not spec.get("job_id"):
        raise ValueError("spec.json is missing job_id")
    (job_dir / "requests").mkdir(parents=True, exist_ok=True)
    _update_state(job_dir, status="queued", job_id=spec["job_id"], run_id=spec.get("run_id"), pid=None, error="")
    log = (job_dir / "worker.log").open("ab", buffering=0)
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "worker", "--job-dir", str(job_dir)],
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
    )
    _update_state(job_dir, status="starting", pid=proc.pid)
    print(json.dumps({"success": True, "job_id": spec["job_id"], "pid": proc.pid}))
    return 0


def _wire_event(record: dict[str, Any]) -> dict[str, Any]:
    """Keep one SSH replay record comfortably below a channel window."""
    wire = dict(record)
    for key in ("result", "output", "content", "text"):
        value = wire.get(key)
        if isinstance(value, str) and len(value) > 12_000:
            wire[key] = value[:12_000] + "\n[output truncated for event replay; full artifact remains on the remote job]"
    return wire


def _events(job_dir: Path, after: int, limit: int) -> int:
    records: list[dict[str, Any]] = []
    encoded_bytes = 0
    for line in (job_dir / "events.jsonl").read_text(encoding="utf-8", errors="replace").splitlines() if (job_dir / "events.jsonl").exists() else []:
        try:
            record = json.loads(line)
            if int(record.get("sequence") or 0) > after:
                wire = _wire_event(record)
                wire_size = len(json.dumps(wire, separators=(",", ":")).encode("utf-8"))
                # Paramiko's command channel can deadlock if the server waits
                # for an exit status before draining a very large response.
                # Replay small bounded pages instead; the cursor makes this
                # lossless and reconnect-safe.
                if records and (len(records) >= limit or encoded_bytes + wire_size > 32_000):
                    break
                records.append(wire)
                encoded_bytes += wire_size
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
    print(json.dumps({"events": records, "next_sequence": records[-1]["sequence"] if records else after}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="CAF durable remote job runner")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "worker", "status", "cancel", "close", "purge"):
        command = sub.add_parser(name)
        command.add_argument("--job-dir", required=True)
        if name == "cancel":
            command.add_argument("--force", action="store_true", help="terminate the worker process group")
    events = sub.add_parser("events")
    events.add_argument("--job-dir", required=True)
    events.add_argument("--after", type=int, default=0)
    events.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    job_dir = Path(args.job_dir).resolve()
    if args.command == "start":
        return _start(job_dir)
    if args.command == "worker":
        return asyncio.run(_worker(job_dir))
    if args.command == "events":
        return _events(job_dir, args.after, max(1, min(args.limit, 100)))
    if args.command == "status":
        print(json.dumps(_load_json(_state_path(job_dir))))
        return 0
    if args.command == "purge":
        state = _load_json(_state_path(job_dir))
        status = str(state.get("status") or "")
        if status not in {"completed", "failed", "cancelled"}:
            print(json.dumps({"success": False, "error": f"Refusing to purge non-terminal job ({status or 'unknown'})."}))
            return 1
        shutil.rmtree(job_dir)
        print(json.dumps({"success": True}))
        return 0
    if args.command in {"cancel", "close"}:
        marker = job_dir / ("cancel.json" if args.command == "cancel" else "close.json")
        _atomic_json(marker, {"requested_at": time.time(), "force": bool(getattr(args, "force", False))})
        forced = False
        if args.command == "cancel" and args.force:
            state = _load_json(_state_path(job_dir))
            try:
                pid = int(state.get("pid") or 0)
                if pid > 1:
                    # The worker is launched in its own process group, so this
                    # also terminates its MCP child and any active tool (nmap).
                    os.killpg(pid, signal.SIGTERM)
                    forced = True
            except (OSError, TypeError, ValueError):
                pass
            _update_state(job_dir, status="cancelled", prompt_id=None, error="Cancelled by ModelScope.")
        print(json.dumps({"success": True, "forced": forced}))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
