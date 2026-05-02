"""
Session Logger for Kali MCP WebUI
Provides structured, timestamped logging of MCP sessions including
tool calls, arguments, outputs, and artifacts.
"""

import json
import os
import re
import time
from datetime import datetime

from timestamp_utils import now_timestamp


def _now_formatted() -> str:
    return now_timestamp()


def _sanitize(name: str) -> str:
    """Make a name safe for use as a filename component."""
    return re.sub(r'[^\w\-]', '_', name)[:64]


class SessionLogger:
    """
    Creates and manages a run directory under `runs/` with the structure:

        runs/<run_id>/
            metadata.json
            transcript.md
            tool_calls/
                001_<tool>.json
            artifacts/
                001_<tool>_output.txt   (saved when output > 1KB)
    """

    def __init__(self, run_id: str, metadata: dict, base_dir: str = None,
                 event_callback=None):
        """
        Args:
            run_id:         Unique run identifier, e.g. "2026-03-05_02-15-00_run001"
            metadata:       Dict with keys like model, server_type, ollama_url, etc.
            base_dir:       Parent directory for runs/ (defaults to cwd)
            event_callback: Optional callable(dict) invoked for every log event
                            to enable real-time SSE broadcasting.
        """
        self._event_callback = event_callback

        if base_dir is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))

        self.run_dir = os.path.join(base_dir, "runs", run_id)
        self.tool_calls_dir = os.path.join(self.run_dir, "tool_calls")
        self.artifacts_dir = os.path.join(self.run_dir, "artifacts")
        self._tool_counter = 0

        os.makedirs(self.tool_calls_dir, exist_ok=True)
        os.makedirs(self.artifacts_dir, exist_ok=True)

        self._transcript_path = os.path.join(self.run_dir, "transcript.md")
        self._metadata_path = os.path.join(self.run_dir, "metadata.json")
        self._annotations_path = os.path.join(self.run_dir, "annotations.jsonl")

        # Write initial metadata
        self._metadata = {
            "run_id": run_id,
            "start_time": _now_formatted(),
            "end_time": None,
            "status": "running",
            **metadata
        }
        self._write_metadata()

        # Init transcript (append mode so multiple processes share safely)
        is_new = not os.path.exists(self._transcript_path)
        with open(self._transcript_path, "a") as f:
            if is_new:
                started = _now_formatted()
                f.write(f"# MCP Session Transcript\n\n")
                f.write(f"**Run ID:** `{run_id}`  \n")
                f.write(f"**Started:** {started}  \n")
                f.write(f"**Model:** {metadata.get('model', 'unknown')}  \n")
                f.write(f"**Server:** {metadata.get('server_type', 'unknown')}  \n\n")
                f.write("---\n\n")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit_event(self, event_type: str, data: dict):
        """Push a structured event to the callback if registered."""
        if self._event_callback:
            try:
                self._event_callback({"type": event_type, **data})
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_prompt(self, text: str):
        """Append a USER prompt turn to the transcript."""
        ts = _now_formatted()
        with open(self._transcript_path, "a") as f:
            f.write(f"### 👤 User [{ts}]\n\n{text}\n\n")
        self._emit_event("prompt", {"text": text})

    def log_response(self, text: str):
        """Append an ASSISTANT response turn to the transcript."""
        ts = _now_formatted()
        with open(self._transcript_path, "a") as f:
            f.write(f"### 🤖 Assistant [{ts}]\n\n{text}\n\n")
        self._emit_event("response", {"text": text})

    def log_tool_call(self, name: str, args: dict, result: str,
                      duration_ms: int = 0, exit_code: int = 0, stderr: str = "",
                      graceful_stop: bool = False, cancelled: bool = False):
        """
        Write a timestamped JSON file for a single tool invocation.

        Args:
            name:          Tool name (e.g. "nmap")
            args:          Dict of arguments passed to the tool
            result:        stdout / main result text
            duration_ms:   How long the tool took in milliseconds
            exit_code:     Process exit code (0 = success)
            stderr:        stderr output if any
            graceful_stop: Whether the tool was stopped manually by the user
        """
        self._tool_counter += 1
        safe_name = _sanitize(name)
        filename = f"{self._tool_counter:03d}_{safe_name}.json"
        path = os.path.join(self.tool_calls_dir, filename)

        record = {
            "seq": self._tool_counter,
            "timestamp": _now_formatted(),
            "tool": name,
            "args": args,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "result_length": len(result),
            "result": result if len(result) <= 4096 else result[:4096] + "\n...[truncated, see artifacts]",
            "stderr": stderr,
            "graceful_stop": graceful_stop,
            "cancelled": cancelled,
        }

        with open(path, "w") as f:
            json.dump(record, f, indent=2)

        # Save large outputs as separate artifact
        if len(result) > 1024:
            self.log_artifact(f"{self._tool_counter:03d}_{safe_name}_output.txt", result)

        # Append a brief tool call note to the transcript
        ts = _now_formatted()
        args_str = json.dumps(args) if args else "(no args)"
        with open(self._transcript_path, "a") as f:
            f.write(f"#### 🔧 Tool Call [{ts}]: `{name}`\n\n")
            f.write(f"**Args:** `{args_str}`  \n")
            f.write(f"**Duration:** {duration_ms}ms  \n")
            f.write(f"**Exit code:** {exit_code}  \n")
            if graceful_stop:
                f.write(f"**Status:** `Manually Stopped`  \n")
            elif cancelled:
                f.write(f"**Status:** `Cancelled`  \n")
            f.write(f"\n")
            preview = result[:512] + ("..." if len(result) > 512 else "")
            f.write(f"```\n{preview}\n```\n\n")

        self._emit_event("tool_result", {
            "tool": name,
            "args": args,
            "result": result[:1024],
            "duration_ms": duration_ms,
            "exit_code": exit_code,
            "graceful_stop": graceful_stop,
            "cancelled": cancelled,
        })

        return filename

    def log_artifact(self, name: str, content: str):
        """Save raw content as an artifact file."""
        safe_name = _sanitize(name) if not name.endswith(".txt") else name
        path = os.path.join(self.artifacts_dir, safe_name)
        with open(path, "w") as f:
            f.write(content)
        return safe_name

    def log_annotation(self, text: str, span: str):
        """Append a user annotation (observation) to annotations.jsonl."""
        record = {
            "timestamp": _now_formatted(),
            "span_relevance": span,
            "note": text
        }
        with open(self._annotations_path, "a") as f:
            f.write(json.dumps(record) + "\n")
            
        # Also put a visual marker into the transcript
        ts = _now_formatted()
        with open(self._transcript_path, "a") as f:
            f.write(f"### 📝 Human Annotation [{ts}] (Relevance: {span})\n\n> {text}\n\n")
        
        self._emit_event("annotation", {"text": text, "span": span})

    def log_human_decision(self, text: str, category: str = "decision"):
        """Append an explicit human approval/denial decision to the transcript."""
        record = {
            "timestamp": _now_formatted(),
            "category": category,
            "decision": text,
        }
        with open(self._annotations_path, "a") as f:
            f.write(json.dumps(record) + "\n")

        ts = _now_formatted()
        with open(self._transcript_path, "a") as f:
            f.write(f"### 👤 Human Decision [{ts}] ({category})\n\n> {text}\n\n")

        self._emit_event("annotation", {"text": text, "span": category})

    def update_metadata(self, updates: dict):
        """Merge new fields into session metadata and persist them."""
        if not updates:
            return
        self._metadata.update(updates)
        self._write_metadata()

    def finalize(self, status: str = "completed"):
        """Mark the session as finished and write end time to metadata."""
        self._metadata["end_time"] = _now_formatted()
        self._metadata["status"] = status
        self._metadata["total_tool_calls"] = self._tool_counter
        self._write_metadata()

        ts = _now_formatted()
        with open(self._transcript_path, "a") as f:
            f.write(f"---\n\n**Session ended** [{ts}] — {self._tool_counter} tool call(s)\n")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _write_metadata(self):
        with open(self._metadata_path, "w") as f:
            json.dump(self._metadata, f, indent=2)

    def log_keystrokes(self, keystrokes: list, source: str = "browser"):
        """
        Log a batch of keystrokes to the session's keystrokes directory.
        
        Args:
            keystrokes: List of keystroke dicts with timestamp, key, type, etc.
            source: Either "browser" or "system"
        """
        if not keystrokes:
            return
        
        keystrokes_dir = os.path.join(self.run_dir, "keystrokes")
        os.makedirs(keystrokes_dir, exist_ok=True)
        
        if source == "browser":
            log_path = os.path.join(keystrokes_dir, "browser_log.jsonl")
        else:
            log_path = os.path.join(keystrokes_dir, "system_log.jsonl")
        
        with open(log_path, "a") as f:
            for entry in keystrokes:
                f.write(json.dumps(entry) + "\n")

    def get_keystrokes(self, source: str = None) -> dict:
        """
        Retrieve keystrokes from the session's keystrokes directory.
        
        Args:
            source: Either "browser", "system", or None for both
            
        Returns:
            Dict with 'browser' and/or 'system' keys containing lists of keystrokes
        """
        result = {"browser": [], "system": []}
        
        keystrokes_dir = os.path.join(self.run_dir, "keystrokes")
        if not os.path.isdir(keystrokes_dir):
            return result
        
        def load_log(path):
            entries = []
            if os.path.isfile(path):
                with open(path) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                entries.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass
            return entries
        
        if source is None or source == "browser":
            result["browser"] = load_log(os.path.join(keystrokes_dir, "browser_log.jsonl"))
        if source is None or source == "system":
            result["system"] = load_log(os.path.join(keystrokes_dir, "system_log.jsonl"))
        
        return result


def make_run_id(prefix: str = "") -> str:
    """Generate a unique run ID based on current timestamp."""
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"{ts}_{prefix}" if prefix else ts


def load_session_list(base_dir: str = None) -> list:
    """Return a sorted list of session metadata dicts from the runs/ directory."""
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    runs_dir = os.path.join(base_dir, "runs")
    if not os.path.isdir(runs_dir):
        return []

    sessions = []
    for run_id in sorted(os.listdir(runs_dir), reverse=True):
        meta_path = os.path.join(runs_dir, run_id, "metadata.json")
        if os.path.isfile(meta_path):
            try:
                with open(meta_path) as f:
                    sessions.append(json.load(f))
            except Exception:
                pass
    return sessions


# ============================================================================
# End of File
# ============================================================================
