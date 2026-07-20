import asyncio
import json
import sys
import subprocess
import time
import os
import shlex
import re
import errno
import fcntl
import ipaddress
import pty
import select
import signal
import termios
import atexit
from urllib.parse import urlparse
from mcp.server import Server
from mcp.types import Tool, TextContent

server = Server("mcp-kali")

_ALLOWED_SHELL_COMMANDS = {
    "ls",
    "cat",
    "grep",
    "docker",
    "ip",
    "ss",
    "ps",
    "uname",
    "id",
    "pwd",
    "whoami",
    "find",
    "netstat",
}
_ALLOWED_EXTENDED_SHELL_COMMANDS = {
    "curl",
    "dig",
    "host",
    "nslookup",
    "openssl",
    "tracepath",
    "traceroute",
    "ping",
}
_DISALLOWED_SHELL_TOKENS = {"|", "||", "&", "&&", ";", ">", ">>", "<", "<<"}
_DISALLOWED_CURL_FLAGS = {
    "-d",
    "--data",
    "--data-ascii",
    "--data-binary",
    "--data-raw",
    "--data-urlencode",
    "-F",
    "--form",
    "--form-string",
    "-o",
    "--output",
    "-O",
    "--remote-name",
    "--remote-name-all",
    "-T",
    "--upload-file",
    "-K",
    "--config",
    "-X",
    "--request",
}
_DISALLOWED_CURL_SCHEMES = ("file://", "ftp://", "ftps://", "scp://", "sftp://", "ldap://", "dict://", "gopher://")
_DEFAULT_CURL_CONNECT_TIMEOUT_SECONDS = 5
_DEFAULT_CURL_MAX_TIME_SECONDS = 30
_MAX_ALLOWED_CURL_MAX_TIME_SECONDS = 90
_DEFAULT_FIRST_TIMEOUT_CHECKPOINT_SECONDS = 30
# Many normal security tools (notably nmap) are silent until they finish.  A
# 20-second idle-output checkpoint turns a valid longer scan into a hidden
# pause even when its configured tool timeout is much larger.  Keep idle
# checkpoints opt-in per tool; the regular tool timeout still limits runtime.
_DEFAULT_IDLE_TIMEOUT_SECONDS = 0
_DISALLOWED_OPENSSL_FLAGS = {
    "-key",
    "-cert",
    "-CAfile",
    "-CApath",
    "-CRL",
    "-CRLform",
    "-CRL_download",
    "-pass",
    "-passin",
    "-proxy",
    "-sess_out",
    "-keylogfile",
}
_ANSI_ESCAPE_RE = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')
_URL_RE = re.compile(r'https?://[^\s]+', re.IGNORECASE)
_CIDR_OR_IP_RE = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b')
_HOSTNAME_RE = re.compile(r'^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\.?$', re.IGNORECASE)
_INTERACTIVE_SESSION_OPEN_RE = re.compile(r'(?:meterpreter|command shell|perl|python|shell|bash|sh)\s+session\s+\d+\s+opened', re.IGNORECASE)
_SESSION_OPEN_GENERIC_RE = re.compile(r'session\s+\d+\s+(?:opened|created)', re.IGNORECASE)
_METERPRETER_PROMPT_RE = re.compile(r'^\s*meterpreter(?:\s+[^\n>]*)?>\s*$', re.IGNORECASE | re.MULTILINE)
_SHELL_PROMPT_RE = re.compile(r'^\s*shell>\s*$', re.IGNORECASE | re.MULTILINE)
_MSF_PROMPT_RE = re.compile(r'^\s*msf\d*(?:\s+[^\n>]*)?>\s*$', re.IGNORECASE | re.MULTILINE)
_STTY_IOCTL_WARNING_RE = re.compile(r"stty:\s+'standard input':\s+Inappropriate ioctl for device", re.IGNORECASE)
_POWERSHELL_PROMPT_RE = re.compile(r'^\s*PS\s+[^\n>]*>\s*$', re.IGNORECASE)
_CMD_PROMPT_RE = re.compile(r'^[A-Za-z]:\\[^\n>]*>\s*$')
_UNIX_SHELL_PROMPT_RE = re.compile(r'^(?:[^\n]{0,120}[#$])\s*$')
_MSF_RUN_DEFAULT_TIMEOUT = 90
_MSF_RUN_DEFAULT_WFS_DELAY = 10
_MAX_SHELL_SEQUENCE_COMMANDS = 3
_TIMEOUT_CONTROL_DIRNAME = "control"
_TIMEOUT_REQUEST_FILENAME = "tool_timeout_request.json"
_TIMEOUT_RESPONSE_FILENAME = "tool_timeout_response.json"
_TOOL_STATUS_FILENAME = "tool_status.json"


def _tools_config_path() -> str:
    """Allow isolated remote jobs to supply a per-run tool catalog."""
    return os.environ.get("CAF_TOOLS_CONFIG_PATH") or "kali_tools.json"

_tools_config_cache: dict | None = None
_tools_config_mtime: float = 0.0

def _get_tools_config() -> dict:
    global _tools_config_cache, _tools_config_mtime
    path = _tools_config_path()
    try:
        mtime = os.path.getmtime(path)
        if _tools_config_cache is not None and mtime <= _tools_config_mtime:
            return _tools_config_cache
        with open(path) as f:
            config = json.load(f)
            _tools_config_cache = config
            _tools_config_mtime = mtime
            return config
    except Exception:
        return {"tools": []}
_TIMEOUT_DECISION_POLL_SECONDS = 0.25
_TIMEOUT_DECISION_MAX_WAIT_SECONDS = int(os.environ.get("MCP_TIMEOUT_DECISION_MAX_WAIT_SECONDS", "30") or 30)
_CANCEL_REQUEST_FILENAME = "tool_cancel_request.json"
_TOOL_STOP_REQUEST_FILENAME = "tool_graceful_stop.json"
_PROCESS_CANCEL_POLL_SECONDS = 0.25
_DEFAULT_INTERACTIVE_SESSION_START_TOOLS = {"msf_run", "shell", "shell_sequence", "shell_extended", "shell_dangerous"}
_INTERACTIVE_SESSION_HISTORY_LIMIT = 200000
_INTERACTIVE_SESSION_PENDING_LIMIT = 65536
_INTERACTIVE_SESSION_DEFAULT_WAIT_SECONDS = 0.75
_INTERACTIVE_SESSION_MAX_WAIT_SECONDS = 5.0
_INTERACTIVE_SESSION_READ_CHUNK = 8192
_BUILTIN_INTERACTIVE_TOOLS = {
    "interactive_session_list",
    "interactive_session_read",
    "interactive_session_write",
    "interactive_session_close",
}

try:
    _NETWORK_POLICY = json.loads(os.environ.get("MCP_NETWORK_POLICY", ""))
except Exception:
    _NETWORK_POLICY = {"allow": ["*"], "disallow": []}

_interactive_sessions: dict[str, dict] = {}

def _cleanup_interactive_sessions():
    for session_id, session in list(_interactive_sessions.items()):
        proc = session.get("proc")
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
atexit.register(_cleanup_interactive_sessions)
_interactive_session_counter = 0


def _process_output_text(value: object) -> str:
    """Normalize subprocess output without exposing Python ``b'…'`` reprs.

    ``TimeoutExpired.output`` may be bytes even when the process was created
    with ``text=True``.  Progress previews must decode that payload before it
    is written to the shared status file.
    """
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _strip_ansi(text: str) -> str:
    if not text:
        return text
    return _ANSI_ESCAPE_RE.sub("", text)


def _normalize_interactive_detection_text(text: str) -> str:
    normalized = _strip_ansi(text or "")
    if not normalized:
        return ""
    normalized = _STTY_IOCTL_WARNING_RE.sub("", normalized)
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    return normalized.strip()


def _merge_process_stream_text(snapshot: str | None, final_text: str | None) -> str:
    snapshot_text = _process_output_text(snapshot)
    final_stream_text = _process_output_text(final_text)
    if not snapshot_text:
        return final_stream_text
    if not final_stream_text:
        return snapshot_text
    if final_stream_text.startswith(snapshot_text) or snapshot_text in final_stream_text:
        return final_stream_text
    if snapshot_text.startswith(final_stream_text) or final_stream_text in snapshot_text:
        return snapshot_text
    separator = "\n" if not snapshot_text.endswith("\n") else ""
    return snapshot_text + separator + final_stream_text


def _manual_recreation_instructions(tool_name: str, arguments: dict, cmd: list[str]) -> str:
    if tool_name == "msf_run":
        prepared_args = _prepare_msf_run_args((arguments.get("args", "") or "").strip())
        commands = [part.strip() for part in prepared_args.split(";") if part.strip()]
        if commands:
            command_block = "\n".join(commands)
            return (
                "To recreate it manually in your own terminal, start `msfconsole` and enter these commands interactively:\n"
                f"{command_block}\n\n"
                "If the final `run` or `exploit` command includes `-z`, remove it if you want to keep the session attached in your own terminal. "
                "Once the session opens, interact with it there directly, for example with `sessions -i <id>` or the `meterpreter >` prompt."
            )

    return (
        "To recreate it manually in your own terminal, run:\n"
        f"{shlex.join(cmd)}"
    )


def _looks_like_interactive_session(tool_name: str, cmd: list[str], stdout: str, stderr: str) -> bool:
    combined = _normalize_interactive_detection_text("\n".join(part for part in [stdout or "", stderr or ""] if part))
    if not combined:
        return False

    command_name = os.path.basename(cmd[0]) if cmd else ""
    if _INTERACTIVE_SESSION_OPEN_RE.search(combined):
        return True
    if _SESSION_OPEN_GENERIC_RE.search(combined):
        return True
    if _METERPRETER_PROMPT_RE.search(combined):
        return True
    if _SHELL_PROMPT_RE.search(combined):
        return True
    if tool_name == "msf_run" or command_name == "msfconsole":
        return bool(_MSF_PROMPT_RE.search(combined))
    return False


def _looks_like_preservable_interactive_session(tool_name: str, stdout: str, stderr: str) -> bool:
    combined = _normalize_interactive_detection_text("\n".join(part for part in [stdout or "", stderr or ""] if part))
    if not combined:
        return False

    # Positive success indicators
    if _INTERACTIVE_SESSION_OPEN_RE.search(combined):
        return True
    if _SESSION_OPEN_GENERIC_RE.search(combined):
        return True
    if "You have active sessions open" in combined:
        return True
    if "created in the background" in combined and "Session " in combined:
        return True
    # We no longer auto-preserve 'msf_run' just because it returns to the msf prompt.
    # This prevents idle consoles from spawning tabs. Real sessions are caught above.
    # For shell-backed tools, a plain msf prompt means the user explicitly launched
    # an interactive Metasploit console and expects to keep it open.
    if tool_name != "msf_run" and _MSF_PROMPT_RE.search(combined):
        return True
    if _METERPRETER_PROMPT_RE.search(combined):
        return True
    if _SHELL_PROMPT_RE.search(combined):
        return True

    # Error/Failure indicators that suggest the tool is stuck at a prompt after a fail
    failure_patterns = [
        "[-] Unknown command:",
        "[-] Unknown option:",
        "[-] Exploit failed",
        "[-] Exploit completed, but no session was created",
        "[-] No sessions were created",
        "command not found",
        "Syntax error:",
    ]
    if any(p in combined for p in failure_patterns):
        return True

    lines = [line.rstrip() for line in combined.splitlines() if line.strip()]
    if not lines:
        return False
    last_line = lines[-1]
    if _POWERSHELL_PROMPT_RE.match(last_line):
        return True
    if _CMD_PROMPT_RE.match(last_line):
        return True
    if _UNIX_SHELL_PROMPT_RE.match(last_line):
        return True
    return False


def _tool_supports_interactive_sessions(tool_name: str, tool_config: dict | None) -> bool:
    if isinstance(tool_config, dict) and "interactive_capable" in tool_config:
        return bool(tool_config.get("interactive_capable"))
    return tool_name in _DEFAULT_INTERACTIVE_SESSION_START_TOOLS


def _build_interactive_session_handoff(tool_name: str, arguments: dict, cmd: list[str]) -> str:
    return (
        "Interactive session detected. The WebUI cannot safely keep an interactive shell attached over the MCP stdio transport, "
        "so the process was stopped before it could hang the agent.\n\n"
        + _manual_recreation_instructions(tool_name, arguments, cmd)
    )


def _terminate_process_with_output(proc: subprocess.Popen) -> tuple[str, str, int]:
    if proc.poll() is None:
        proc.terminate()
        try:
            stdout, stderr = proc.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
    else:
        stdout, stderr = proc.communicate()
    return stdout or "", stderr or "", int(proc.returncode or 0)


def _next_interactive_session_id() -> str:
    global _interactive_session_counter
    _interactive_session_counter += 1
    return f"isess-{_interactive_session_counter:03d}"


def _set_nonblocking(fd: int):
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)


def _attach_controlling_tty():
    try:
        if os.isatty(0) and hasattr(termios, "TIOCSCTTY"):
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    except Exception:
        pass


def _truncate_tail(text: str, limit: int) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[-limit:]


def _append_session_output(session: dict, text: str, *, pending: bool):
    chunk = _strip_ansi(text or "")
    if not chunk:
        return
    session["history"] = _truncate_tail(session.get("history", "") + chunk, _INTERACTIVE_SESSION_HISTORY_LIMIT)
    if pending:
        session["pending_output"] = _truncate_tail(session.get("pending_output", "") + chunk, _INTERACTIVE_SESSION_PENDING_LIMIT)
    session["last_output_at"] = time.time()


def _close_session_master_fd(session: dict):
    master_fd = session.get("master_fd")
    if master_fd is None:
        return
    try:
        os.close(master_fd)
    except OSError:
        pass
    session["master_fd"] = None


def _close_master_fd_value(master_fd: int | None):
    if master_fd is None:
        return
    try:
        os.close(master_fd)
    except OSError:
        pass


def _terminate_process_group(proc: subprocess.Popen):
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=1)
    except Exception:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                proc.kill()


def _read_pty_available(master_fd: int | None, timeout_seconds: float = 0.0) -> str:
    if master_fd is None:
        return ""

    collected: list[bytes] = []
    end_at = time.time() + max(0.0, float(timeout_seconds))
    first_pass = True

    while True:
        remaining = max(0.0, end_at - time.time()) if not first_pass else max(0.0, float(timeout_seconds))
        ready, _, _ = select.select([master_fd], [], [], remaining)
        first_pass = False
        if not ready:
            break

        while True:
            try:
                chunk = os.read(master_fd, _INTERACTIVE_SESSION_READ_CHUNK)
            except OSError as exc:
                if exc.errno in {errno.EAGAIN, errno.EWOULDBLOCK}:
                    chunk = b""
                    break
                if exc.errno == errno.EIO:
                    chunk = b""
                    break
                raise

            if not chunk:
                break
            collected.append(chunk)

        if time.time() >= end_at:
            break

    return b"".join(collected).decode(errors="replace")


def _close_session_stream_fds(session: dict):
    for key in ("stdout_fd", "stderr_fd"):
        fd = session.get(key)
        if fd is None:
            continue
        try:
            os.close(fd)
        except OSError:
            pass
        session[key] = None


def _read_session_stream_fds_available(session: dict, timeout_seconds: float = 0.0) -> str:
    fds = [fd for fd in (session.get("stdout_fd"), session.get("stderr_fd")) if fd is not None]
    if not fds:
        return ""

    collected: list[bytes] = []
    end_at = time.time() + max(0.0, float(timeout_seconds))
    first_pass = True

    while True:
        if not fds:
            break

        remaining = max(0.0, end_at - time.time()) if not first_pass else max(0.0, float(timeout_seconds))
        ready, _, _ = select.select(fds, [], [], remaining)
        first_pass = False
        if not ready:
            break

        for fd in list(ready):
            while True:
                try:
                    chunk = os.read(fd, _INTERACTIVE_SESSION_READ_CHUNK)
                except OSError as exc:
                    if exc.errno in {errno.EAGAIN, errno.EWOULDBLOCK}:
                        break
                    if exc.errno == errno.EIO:
                        chunk = b""
                    else:
                        raise

                if not chunk:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    if session.get("stdout_fd") == fd:
                        session["stdout_fd"] = None
                    if session.get("stderr_fd") == fd:
                        session["stderr_fd"] = None
                    fds = [candidate for candidate in fds if candidate != fd]
                    break

                collected.append(chunk)

            if time.time() >= end_at:
                break

        if time.time() >= end_at:
            break

    return b"".join(collected).decode(errors="replace")


def _compose_background_session_output(stdout: str, stderr: str) -> str:
    output = _strip_ansi(stdout or "")
    stderr_text = _strip_ansi(stderr or "")
    if stderr_text:
        if output:
            output += f"\n\nSTDERR:\n{stderr_text}"
        else:
            output = f"STDERR:\n{stderr_text}"
    return output


def _refresh_interactive_session(session: dict, wait_seconds: float = 0.0) -> str:
    if session.get("closed"):
        return ""

    if session.get("master_fd") is not None:
        chunk = _read_pty_available(session.get("master_fd"), wait_seconds)
    else:
        chunk = _read_session_stream_fds_available(session, wait_seconds)
    if chunk:
        _append_session_output(session, chunk, pending=True)

    proc = session.get("proc")
    if proc and proc.poll() is not None:
        if session.get("master_fd") is not None:
            trailing = _read_pty_available(session.get("master_fd"), 0.0)
        else:
            trailing = _read_session_stream_fds_available(session, 0.0)
        if trailing:
            _append_session_output(session, trailing, pending=True)
            chunk += trailing
        session["closed"] = True
        session["returncode"] = int(proc.returncode or 0)
        session["closed_at"] = time.time()
        _close_session_master_fd(session)
        _close_session_stream_fds(session)

        # Log the auto-close so the session lifecycle is fully captured
        sid = session.get("id", "unknown")
        rc = session["returncode"]
        _logger.log_tool_call(
            name="interactive_session_auto_close",
            args={"session_id": sid, "reason": "process_exited"},
            result=f"Interactive session {sid} closed automatically (process exited with code {rc}).",
            duration_ms=0,
            exit_code=rc,
        )

    return chunk


def _preserve_interactive_session(
    proc: subprocess.Popen,
    master_fd: int | None,
    tool_name: str,
    arguments: dict,
    cmd: list[str],
    initial_output: str,
    *,
    stdout_fd: int | None = None,
    stderr_fd: int | None = None,
    writable: bool = True,
    session_kind: str = "interactive",
) -> str:
    session_id = _next_interactive_session_id()
    session = {
        "id": session_id,
        "tool": tool_name,
        "args": dict(arguments or {}),
        "command": list(cmd),
        "proc": proc,
        "master_fd": master_fd,
        "stdout_fd": stdout_fd,
        "stderr_fd": stderr_fd,
        "writable": bool(writable),
        "session_kind": str(session_kind or "interactive"),
        "history": "",
        "pending_output": "",
        "created_at": time.time(),
        "last_output_at": time.time(),
        "closed": False,
        "closed_at": None,
        "returncode": None,
    }
    _append_session_output(session, initial_output, pending=False)
    _interactive_sessions[session_id] = session
    return session_id


def _interactive_session_status_line(session: dict) -> str:
    proc = session.get("proc")
    running = bool(proc and proc.poll() is None and not session.get("closed"))
    status = "active" if running else f"closed (exit {session.get('returncode', 0)})"
    command = shlex.join(session.get("command") or [])
    pending_chars = len(session.get("pending_output") or "")
    writable = "yes" if session.get("writable", True) else "no"
    session_kind = str(session.get("session_kind") or "interactive")
    return f"{session.get('id')}: {status}; kind={session_kind}; writable={writable}; tool={session.get('tool')}; pending_chars={pending_chars}; command={command}"


def _coerce_wait_seconds(value, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = float(default)
    return min(max(numeric, 0.0), _INTERACTIVE_SESSION_MAX_WAIT_SECONDS)


def _builtin_interactive_tools(enabled: bool) -> list[Tool]:
    if not enabled:
        return []
    return [
        Tool(
            name="interactive_session_list",
            description="List all preserved interactive sessions (isess-XXX). These are sessions created by prior tool calls such as msf_run. Returns session IDs in the format isess-001, isess-002, etc.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="interactive_session_read",
            description="Read newly available output from a preserved interactive session. IMPORTANT: The session_id MUST be an isess-XXX identifier (e.g. isess-001) as returned by the preservation message or interactive_session_list. Do NOT use Metasploit session numbers like '1' or commands like 'sessions -i 1'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "The isess-XXX identifier, e.g. isess-001. NOT a Metasploit session number."},
                    "wait_seconds": {"type": "number", "description": "Optional short wait before reading, between 0 and 2 seconds"},
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="interactive_session_write",
            description="Send a command or input to a preserved interactive session and return any resulting output. IMPORTANT: The session_id MUST be an isess-XXX identifier (e.g. isess-001). The 'input' field is the command to run inside the session (e.g. 'sysinfo', 'ls', 'whoami'). Do NOT use Metasploit session numbers or commands like 'sessions -i 1' as the session_id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "The isess-XXX identifier, e.g. isess-001. NOT a Metasploit session number."},
                    "input": {"type": "string", "description": "The command or input to send to the session, e.g. 'sysinfo', 'ls -la', 'whoami'"},
                    "wait_seconds": {"type": "number", "description": "Optional short wait after sending input, between 0 and 2 seconds"},
                },
                "required": ["session_id", "input"],
            },
        ),
        Tool(
            name="interactive_session_close",
            description="Terminate a preserved interactive session and return any final buffered output. The session_id MUST be an isess-XXX identifier (e.g. isess-001).",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "The isess-XXX identifier, e.g. isess-001. NOT a Metasploit session number."},
                },
                "required": ["session_id"],
            },
        ),
    ]


def _interactive_session_tool_result(name: str, arguments: dict) -> tuple[str, int]:
    arguments = arguments or {}
    session_id = str(arguments.get("session_id") or "").strip()

    # Fallback: the agent often sends {"args": "isess-001"} via the generic tool schema
    # instead of {"session_id": "isess-001"}.  Parse session_id (and optional input) from args.
    if not session_id:
        raw_args = str(arguments.get("args") or "").strip()
        if raw_args:
            parts = raw_args.split(None, 1)
            candidate = parts[0]
            # Accept anything that looks like an isess-XXX id
            if candidate.startswith("isess-") or candidate in _interactive_sessions:
                session_id = candidate
                # For write commands, the remainder after the session_id is the input
                if name == "interactive_session_write" and not arguments.get("input") and len(parts) > 1:
                    arguments = dict(arguments)
                    arguments["input"] = parts[1]
            elif name == "interactive_session_list":
                pass  # list doesn't need a session_id
            else:
                # Maybe the whole args string is the session_id
                session_id = raw_args

    if name == "interactive_session_list":
        if not _interactive_sessions:
            return "No preserved interactive sessions are currently available.", 0
        lines = []
        for session in _interactive_sessions.values():
            _refresh_interactive_session(session, 0.0)
            lines.append(_interactive_session_status_line(session))
        return "\n".join(lines), 0

    if not session_id:
        return "Error: session_id is required. Use interactive_session_list to see available sessions (format: isess-001, isess-002, etc).", -1

    session = _interactive_sessions.get(session_id)
    if not session:
        available = ", ".join(_interactive_sessions.keys()) if _interactive_sessions else "none"
        return (
            f"Error: Interactive session '{session_id}' was not found. "
            f"Available sessions: [{available}]. "
            f"IMPORTANT: Use the isess-XXX identifier (e.g. isess-001), NOT a Metasploit session number or 'sessions -i' command."
        ), -1

    if name == "interactive_session_read":
        wait_seconds = _coerce_wait_seconds((arguments or {}).get("wait_seconds", 0), 0.0)
        _refresh_interactive_session(session, wait_seconds)
        pending_output = session.get("pending_output") or ""
        session["pending_output"] = ""
        if pending_output:
            return pending_output, 0
        if session.get("closed"):
            return f"Interactive session {session_id} is closed and no new output is pending.", 0
        return f"Interactive session {session_id} has no new output yet.", 0

    if name == "interactive_session_write":
        _refresh_interactive_session(session, 0.0)
        if session.get("closed"):
            return f"Error: Interactive session {session_id} is already closed.", -1
        if not session.get("writable", True):
            return f"Error: Interactive session {session_id} is read-only and does not accept input.", -1
        if session.get("master_fd") is None:
            return f"Error: Interactive session {session_id} is not writable because its terminal is no longer attached.", -1
        user_input = str((arguments or {}).get("input") or "")
        if not user_input:
            return "Error: input is required.", -1
        normalized_input, normalization_note = _normalize_interactive_network_command(user_input)
        payload = normalized_input if normalized_input.endswith("\n") else f"{normalized_input}\n"
        os.write(session["master_fd"], payload.encode())
        wait_seconds = _coerce_wait_seconds((arguments or {}).get("wait_seconds", _INTERACTIVE_SESSION_DEFAULT_WAIT_SECONDS), _INTERACTIVE_SESSION_DEFAULT_WAIT_SECONDS)
        _refresh_interactive_session(session, wait_seconds)
        pending_output = session.get("pending_output") or ""
        session["pending_output"] = ""
        if pending_output:
            if normalization_note:
                return f"{normalization_note}\n\n{pending_output}", 0
            return pending_output, 0
        if session.get("closed"):
            if normalization_note:
                return f"{normalization_note}\n\nInteractive session {session_id} closed after sending input.", 0
            return f"Interactive session {session_id} closed after sending input.", 0
        if normalization_note:
            return f"{normalization_note}\n\nInput sent to interactive session {session_id}; no output is available yet.", 0
        return f"Input sent to interactive session {session_id}; no output is available yet.", 0

    if name == "interactive_session_close":
        proc = session.get("proc")
        if proc and proc.poll() is None:
            _terminate_process_group(proc)
        _refresh_interactive_session(session, 0.1)
        session["closed"] = True
        session["closed_at"] = time.time()
        session["returncode"] = int(proc.returncode or 0) if proc else 0
        _close_session_master_fd(session)
        _close_session_stream_fds(session)
        pending_output = session.get("pending_output") or ""
        session["pending_output"] = ""
        if pending_output:
            return f"Closed interactive session {session_id}.\n\n{pending_output}", 0
        return f"Closed interactive session {session_id}.", 0

    return f"Error: Unsupported interactive session tool {name}.", -1


def _normalize_network_policy(policy) -> dict:
    policy = policy or {}
    allow = [str(item).strip() for item in policy.get("allow", ["*"]) if str(item).strip()]
    disallow = [str(item).strip() for item in policy.get("disallow", []) if str(item).strip()]
    if not allow:
        allow = ["*"]
    return {"allow": allow, "disallow": disallow}


def _prepare_msf_run_args(user_args: str) -> str:
    commands = [part.strip() for part in (user_args or "").split(";") if part.strip()]
    if not commands:
        return (user_args or "").strip()

    module_type = None
    for command in commands:
        lower = command.lower()
        if lower.startswith("use "):
            module_path = command[4:].strip().lower()
            if module_path.startswith("exploit/"):
                module_type = "exploit"
            elif module_path.startswith("auxiliary/"):
                module_type = "auxiliary"
            break

    is_exploit_workflow = module_type == "exploit"
    has_wfsdelay = any(
        cmd.lower().startswith("set wfsdelay ") or cmd.lower().startswith("setg wfsdelay ")
        for cmd in commands
    )
    has_autocheck = any(
        cmd.lower().startswith("set autocheck ") or cmd.lower().startswith("setg autocheck ")
        for cmd in commands
    )

    normalized = []
    inserted_wfsdelay = False
    inserted_autocheck = False
    for command in commands:
        lower = command.lower()
        is_run_command = lower == "exploit" or lower.startswith("exploit ") or lower == "run" or lower.startswith("run ")

        if is_exploit_workflow and is_run_command and not has_autocheck and not inserted_autocheck:
            normalized.append("set AutoCheck false")
            inserted_autocheck = True

        if is_exploit_workflow and is_run_command and not has_wfsdelay and not inserted_wfsdelay:
            normalized.append(f"set WfsDelay {_MSF_RUN_DEFAULT_WFS_DELAY}")
            inserted_wfsdelay = True

        if is_exploit_workflow and is_run_command:
            tokens = command.split()
            if "-z" not in tokens:
                command = f"{command} -z"

        normalized.append(command)

    return "; ".join(normalized)


def _next_shell_token(tokens: list[str], index: int) -> str | None:
    if index + 1 >= len(tokens):
        return None
    return tokens[index + 1]


def _normalize_extended_shell_command(shell_parts: list[str]) -> tuple[list[str] | None, str | None]:
    shell_command = shell_parts[0]

    if shell_command == "curl":
        has_connect_timeout = False
        has_max_time = False
        has_silent = False
        has_show_error = False
        for token in shell_parts[1:]:
            if token in _DISALLOWED_CURL_FLAGS:
                blocked = ", ".join(sorted(_DISALLOWED_CURL_FLAGS))
                return None, f"Error: curl in shell_extended is limited to read-only requests. Disallowed flags: {blocked}"
            lowered = token.lower()
            if lowered.startswith(_DISALLOWED_CURL_SCHEMES):
                blocked_schemes = ", ".join(_DISALLOWED_CURL_SCHEMES)
                return None, f"Error: curl in shell_extended only allows HTTP(S) targets. Disallowed schemes: {blocked_schemes}"
            if token in {"--connect-timeout"}:
                has_connect_timeout = True
            if token in {"-m", "--max-time"}:
                has_max_time = True
            if token in {"-s", "--silent"}:
                has_silent = True
            if token in {"-S", "--show-error"}:
                has_show_error = True
            if token.startswith("-") and not token.startswith("--"):
                if "s" in token[1:]:
                    has_silent = True
                if "S" in token[1:]:
                    has_show_error = True
            if lowered.startswith("--connect-timeout="):
                has_connect_timeout = True
            if lowered.startswith("--max-time="):
                has_max_time = True

        normalized = list(shell_parts)

        if not has_connect_timeout:
            normalized.extend(["--connect-timeout", str(_DEFAULT_CURL_CONNECT_TIMEOUT_SECONDS)])
        if not has_max_time:
            normalized.extend(["--max-time", str(_DEFAULT_CURL_MAX_TIME_SECONDS)])
        if has_silent and not has_show_error:
            normalized.append("--show-error")

        # Validate explicit max-time values so a single call cannot run indefinitely.
        for index, token in enumerate(normalized[:-1]):
            if token in {"-m", "--max-time"}:
                value = _next_shell_token(normalized, index)
                if value is None:
                    return None, "Error: curl max-time flag requires a numeric value"
                try:
                    max_time = int(float(value))
                except ValueError:
                    return None, "Error: curl max-time flag requires a numeric value"
                if max_time <= 0 or max_time > _MAX_ALLOWED_CURL_MAX_TIME_SECONDS:
                    return None, (
                        "Error: curl --max-time in shell_extended must be between 1 and "
                        f"{_MAX_ALLOWED_CURL_MAX_TIME_SECONDS} seconds"
                    )

        for token in normalized:
            lowered = token.lower()
            if lowered.startswith("--max-time="):
                value = lowered.split("=", 1)[1]
                try:
                    max_time = int(float(value))
                except ValueError:
                    return None, "Error: curl max-time flag requires a numeric value"
                if max_time <= 0 or max_time > _MAX_ALLOWED_CURL_MAX_TIME_SECONDS:
                    return None, (
                        "Error: curl --max-time in shell_extended must be between 1 and "
                        f"{_MAX_ALLOWED_CURL_MAX_TIME_SECONDS} seconds"
                    )

        return normalized, None

    if shell_command == "openssl":
        if len(shell_parts) < 2 or shell_parts[1] != "s_client":
            return None, "Error: openssl in shell_extended only allows the 's_client' subcommand"
        for token in shell_parts[2:]:
            if token in _DISALLOWED_OPENSSL_FLAGS:
                blocked = ", ".join(sorted(_DISALLOWED_OPENSSL_FLAGS))
                return None, f"Error: openssl s_client in shell_extended disallows local file, proxy, and session output flags: {blocked}"
        return shell_parts, None

    if shell_command in {"tracepath", "traceroute"}:
        has_max_hops = any(token in {"-m", "--max-hops"} for token in shell_parts[1:])
        normalized = list(shell_parts)
        if not has_max_hops:
            normalized.extend(["-m", "16"])
        return normalized, None

    if shell_command == "ping":
        if any(token == "-f" for token in shell_parts[1:]):
            return None, "Error: ping in shell_extended does not allow flood mode (-f)"

        normalized = list(shell_parts)
        count_index = None
        for index, token in enumerate(normalized[1:], start=1):
            if token == "-c":
                count_index = index
                break

        if count_index is None:
            normalized.extend(["-c", "4"])
            return normalized, None

        count_value = _next_shell_token(normalized, count_index)
        if count_value is None:
            return None, "Error: ping count flag (-c) requires a numeric value"

        try:
            count = int(count_value)
        except ValueError:
            return None, "Error: ping count flag (-c) requires a numeric value"

        if count < 1 or count > 5:
            return None, "Error: ping in shell_extended only allows counts between 1 and 5"
        return normalized, None

    return shell_parts, None


def _parse_shell_sequence(raw_args: str, has_dangerous: bool = False) -> tuple[list[str] | None, str | None]:
    raw_text = (raw_args or "").strip()
    if not raw_text:
        return None, "Error: shell_sequence requires commands, either as a JSON array or one command per line"

    commands: list[str]
    if raw_text.startswith("["):
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            return None, f"Error: Invalid shell_sequence JSON array: {exc}"
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            return None, "Error: shell_sequence JSON input must be an array of command strings"
        commands = [item.strip() for item in parsed if item.strip()]
    else:
        commands = [line.strip() for line in raw_text.splitlines() if line.strip()]

    if not commands:
        return None, "Error: shell_sequence requires at least one non-empty command"
    if not has_dangerous and len(commands) > _MAX_SHELL_SEQUENCE_COMMANDS:
        return None, f"Error: shell_sequence allows at most {_MAX_SHELL_SEQUENCE_COMMANDS} commands per call"

    return commands, None


def _run_dir_for_current_session() -> str | None:
    run_id = os.environ.get("MCP_CURRENT_RUN_ID")
    if not run_id:
        return None
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "runs", run_id)


def _timeout_control_dir() -> str | None:
    run_dir = _run_dir_for_current_session()
    if not run_dir:
        return None
    return os.path.join(run_dir, _TIMEOUT_CONTROL_DIRNAME)


def _timeout_request_path() -> str | None:
    control_dir = _timeout_control_dir()
    if not control_dir:
        return None
    return os.path.join(control_dir, _TIMEOUT_REQUEST_FILENAME)


def _timeout_response_path() -> str | None:
    control_dir = _timeout_control_dir()
    if not control_dir:
        return None
    return os.path.join(control_dir, _TIMEOUT_RESPONSE_FILENAME)


def _tool_status_path() -> str | None:
    control_dir = _timeout_control_dir()
    if not control_dir:
        return None
    return os.path.join(control_dir, _TOOL_STATUS_FILENAME)


def _cancel_request_path() -> str | None:
    control_dir = _timeout_control_dir()
    if not control_dir:
        return None
    return os.path.join(control_dir, _CANCEL_REQUEST_FILENAME)


def _tool_stop_request_path() -> str | None:
    control_dir = _timeout_control_dir()
    if not control_dir:
        return None
    return os.path.join(control_dir, _TOOL_STOP_REQUEST_FILENAME)


def _cancel_requested() -> bool:
    path = _cancel_request_path()
    return bool(path and os.path.exists(path))


def _tool_stop_requested() -> bool:
    path = _tool_stop_request_path()
    return bool(path and os.path.exists(path))


def _clear_timeout_control_files():
    for path in (_timeout_request_path(), _timeout_response_path(), _cancel_request_path(), _tool_stop_request_path(), _tool_status_path()):
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


def _write_tool_status(
    tool_name: str,
    elapsed_seconds: int,
    stdout_len: int,
    stderr_len: int,
    extra_msg: str = "",
    output_preview: str = "",
):
    status_path = _tool_status_path()
    if not status_path:
        return
    status_data = {
        "tool": tool_name,
        "elapsed_seconds": elapsed_seconds,
        "stdout_len": stdout_len,
        "stderr_len": stderr_len,
        "extra_msg": extra_msg,
        # The most recently captured output fragment.  The receiver de-dupes
        # it, so retaining it is deliberate: a watcher that attaches after
        # the first status write must still be able to show what the tool has
        # actually produced.
        "output_preview": output_preview,
        "timestamp": time.time()
    }
    try:
        with open(status_path + ".tmp", "w") as f:
            json.dump(status_data, f)
        os.replace(status_path + ".tmp", status_path)
    except OSError:
        pass


def _write_timeout_request(
    tool_name: str,
    arguments: dict,
    cmd: list[str],
    timeout_seconds: int,
    checkpoint_index: int,
    trigger: str = "timeout",
    elapsed_seconds: int = 0,
) -> str | None:
    request_path = _timeout_request_path()
    response_path = _timeout_response_path()
    if not request_path or not response_path:
        return None

    os.makedirs(os.path.dirname(request_path), exist_ok=True)
    if os.path.exists(response_path):
        try:
            os.remove(response_path)
        except OSError:
            pass

    request_id = f"{int(time.time() * 1000)}-{checkpoint_index}"
    payload = {
        "request_id": request_id,
        "tool": tool_name,
        "args": arguments,
        "command": shlex.join(cmd),
        "timeout_seconds": int(timeout_seconds),
        "checkpoint_index": int(checkpoint_index),
        "trigger": str(trigger or "timeout"),
        "elapsed_seconds": max(0, int(elapsed_seconds or 0)),
        "timestamp": time.time(),
    }
    with open(request_path, "w") as f:
        json.dump(payload, f, indent=2)
    return request_id


def _await_timeout_decision(
    proc: subprocess.Popen,
    tool_name: str,
    arguments: dict,
    cmd: list[str],
    timeout_seconds: int,
    checkpoint_index: int,
    trigger: str = "timeout",
    elapsed_seconds: int = 0,
) -> tuple[str, int | None]:
    request_id = _write_timeout_request(
        tool_name,
        arguments,
        cmd,
        timeout_seconds,
        checkpoint_index,
        trigger=trigger,
        elapsed_seconds=elapsed_seconds,
    )
    if not request_id:
        return "kill", None

    response_path = _timeout_response_path()
    request_path = _timeout_request_path()
    wait_started_at = time.time()

    try:
        while True:
            if proc.poll() is not None:
                return "finished", None

            if time.time() - wait_started_at >= max(1, _TIMEOUT_DECISION_MAX_WAIT_SECONDS):
                return "kill_no_decision", None

            if _cancel_requested():
                return "kill", None

            if response_path and os.path.exists(response_path):
                try:
                    with open(response_path) as f:
                        response = json.load(f)
                except Exception:
                    response = None

                if isinstance(response, dict) and response.get("request_id") == request_id:
                    action = str(response.get("action") or "").strip().lower()
                    if action in {"wait", "kill", "background"}:
                        try:
                            wait_seconds = int(response.get("wait_seconds")) if action == "wait" else None
                        except (TypeError, ValueError):
                            wait_seconds = None
                        return action, wait_seconds

            time.sleep(_TIMEOUT_DECISION_POLL_SECONDS)
    finally:
        for path in (request_path, response_path):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass


def _run_subprocess_with_timeout_prompt(
    cmd: list[str],
    timeout_seconds: int,
    tool_name: str,
    arguments: dict,
    preserve_interactive: bool = False,
    first_checkpoint_seconds: int | None = None,
    idle_timeout_seconds: int | None = None,
) -> dict:
    if preserve_interactive:
        return _run_interactive_subprocess_with_timeout_prompt(
            cmd,
            timeout_seconds,
            tool_name,
            arguments,
            first_checkpoint_seconds=first_checkpoint_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
        )

    run_dir = _run_dir_for_current_session()
    t0 = time.time()

    if not run_dir:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            stdin=subprocess.DEVNULL,
        )
        return {
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "returncode": result.returncode,
            "duration_ms": int((time.time() - t0) * 1000),
            "timed_out_kill": False,
            "checkpoint_index": 0,
        }

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    checkpoint_index = 0
    _clear_timeout_control_files()
    checkpoint_interval = max(1, int(timeout_seconds))
    first_checkpoint = int(first_checkpoint_seconds or _DEFAULT_FIRST_TIMEOUT_CHECKPOINT_SECONDS)
    first_checkpoint = max(1, min(first_checkpoint, checkpoint_interval))
    next_checkpoint_at = t0 + first_checkpoint
    idle_limit = int(idle_timeout_seconds or _DEFAULT_IDLE_TIMEOUT_SECONDS)
    idle_limit = max(0, idle_limit)
    last_activity_at = t0
    last_status_at = t0
    last_seen_sizes = (0, 0)
    last_reported_sizes = (0, 0)
    last_output_preview = ""

    def _background_noninteractive_session(partial_stdout: str, partial_stderr: str) -> dict:
        stdout_fd = proc.stdout.fileno() if proc.stdout else None
        stderr_fd = proc.stderr.fileno() if proc.stderr else None
        for fd in (stdout_fd, stderr_fd):
            if fd is not None:
                _set_nonblocking(fd)

        session_id = _preserve_interactive_session(
            proc,
            None,
            tool_name,
            arguments,
            cmd,
            _compose_background_session_output(partial_stdout, partial_stderr),
            stdout_fd=stdout_fd,
            stderr_fd=stderr_fd,
            writable=False,
            session_kind="background",
        )
        return {
            "stdout": partial_stdout,
            "stderr": partial_stderr or "",
            "returncode": 0,
            "duration_ms": int((time.time() - t0) * 1000),
            "timed_out_kill": False,
            "cancelled": False,
            "interactive_preserved": True,
            "interactive_session_id": session_id,
            "interactive_session_writable": False,
            "interactive_session_kind": "background",
            "checkpoint_index": checkpoint_index,
        }

    while True:
        try:
            remaining_to_checkpoint = max(0.0, next_checkpoint_at - time.time())
            wait_slice = min(_PROCESS_CANCEL_POLL_SECONDS, remaining_to_checkpoint)
            stdout, stderr = proc.communicate(timeout=wait_slice)
            return {
                "stdout": stdout or "",
                "stderr": stderr or "",
                "returncode": proc.returncode,
                "duration_ms": int((time.time() - t0) * 1000),
                "timed_out_kill": False,
                "cancelled": False,
                "checkpoint_index": checkpoint_index,
            }
        except subprocess.TimeoutExpired as exc:
            partial_stdout = _process_output_text(getattr(exc, "output", None))
            partial_stderr = _process_output_text(getattr(exc, "stderr", None))
            current_sizes = (len(partial_stdout), len(partial_stderr))
            now = time.time()
            if current_sizes != last_seen_sizes:
                last_seen_sizes = current_sizes
                last_activity_at = now
            
            if now - last_status_at >= 2.0:
                out_len = len(partial_stdout)
                err_len = len(partial_stderr)
                new_output = partial_stdout[last_reported_sizes[0]:] + partial_stderr[last_reported_sizes[1]:]
                new_preview = _strip_ansi(new_output)[-2000:]
                if new_preview.strip():
                    # Preserve the latest nonempty fragment.  The client may
                    # begin observing status after this subprocess has already
                    # emitted its first bytes; in that case a delta-only
                    # preview would be permanently lost.
                    last_output_preview = new_preview
                # Status events are progress telemetry, not a replacement for
                # the final tool artifact.  Keep each preview bounded.
                _write_tool_status(
                    tool_name,
                    int(now - t0),
                    out_len,
                    err_len,
                    output_preview=last_output_preview,
                )
                last_reported_sizes = (out_len, err_len)
                last_status_at = now

            if _looks_like_interactive_session(tool_name, cmd, partial_stdout, partial_stderr):
                # Non-interactive subprocesses (stdin=DEVNULL) cannot be preserved safely.
                # Gracefully hand off instructions instead of trying to create an isess.
                final_stdout, final_stderr, returncode = _terminate_process_with_output(proc)
                merged_stdout = _merge_process_stream_text(partial_stdout, final_stdout)
                merged_stderr = _merge_process_stream_text(partial_stderr, final_stderr)
                return {
                    "stdout": merged_stdout,
                    "stderr": merged_stderr,
                    "returncode": returncode,
                    "duration_ms": int((time.time() - t0) * 1000),
                    "timed_out_kill": False,
                    "cancelled": False,
                    "interactive_handoff": True,
                    "handoff_message": _build_interactive_session_handoff(tool_name, arguments, cmd),
                    "checkpoint_index": checkpoint_index,
                }

            if _cancel_requested():
                if proc.poll() is None:
                    proc.kill()
                stdout, stderr = proc.communicate()
                return {
                    "stdout": stdout or "",
                    "stderr": stderr or "",
                    "returncode": -1,
                    "duration_ms": int((time.time() - t0) * 1000),
                    "timed_out_kill": False,
                    "cancelled": True,
                    "checkpoint_index": checkpoint_index,
                }

            if _tool_stop_requested():
                final_stdout, final_stderr, returncode = _terminate_process_with_output(proc)
                merged_stdout = _merge_process_stream_text(partial_stdout, final_stdout)
                merged_stderr = _merge_process_stream_text(partial_stderr, final_stderr)
                return {
                    "stdout": merged_stdout,
                    "stderr": merged_stderr,
                    "returncode": returncode,
                    "duration_ms": int((time.time() - t0) * 1000),
                    "timed_out_kill": False,
                    "cancelled": False,
                    "graceful_stop": True,
                    "checkpoint_index": checkpoint_index,
                }

            now = time.time()
            if idle_limit > 0 and (now - last_activity_at) >= idle_limit:
                checkpoint_index += 1
                action, wait_seconds = _await_timeout_decision(
                    proc,
                    tool_name,
                    arguments,
                    cmd,
                    idle_limit,
                    checkpoint_index,
                    trigger="idle",
                    elapsed_seconds=int(now - t0),
                )
                if action == "wait":
                    delay_seconds = max(1, int(wait_seconds or checkpoint_interval))
                    checkpoint_interval = delay_seconds
                    idle_limit = delay_seconds
                    last_activity_at = time.time()
                    next_checkpoint_at = time.time() + delay_seconds
                    continue
                if action == "background":
                    return _background_noninteractive_session(partial_stdout, partial_stderr)

                if action != "finished" and proc.poll() is None:
                    proc.kill()
                stdout, stderr = proc.communicate()
                return {
                    "stdout": stdout or "",
                    "stderr": stderr or "",
                    "returncode": -1,
                    "duration_ms": int((time.time() - t0) * 1000),
                    "timed_out_kill": action in {"kill", "kill_no_decision"},
                    "cancelled": False,
                    "timeout_trigger": "idle",
                    "timeout_kill_reason": "no_timeout_decision"
                    if action == "kill_no_decision" else "user_kill_decision",
                    "checkpoint_index": checkpoint_index,
                }

            if time.time() < next_checkpoint_at:
                continue

            checkpoint_index += 1
            action, wait_seconds = _await_timeout_decision(
                proc,
                tool_name,
                arguments,
                cmd,
                checkpoint_interval,
                checkpoint_index,
                trigger="timeout",
                elapsed_seconds=int(time.time() - t0),
            )
            if action == "wait":
                delay_seconds = max(1, int(wait_seconds or checkpoint_interval))
                checkpoint_interval = delay_seconds
                idle_limit = delay_seconds if idle_limit > 0 else 0
                next_checkpoint_at = time.time() + delay_seconds
                last_activity_at = time.time()
                continue
            if action == "background":
                return _background_noninteractive_session(partial_stdout, partial_stderr)

            if action != "finished" and proc.poll() is None:
                proc.kill()
            stdout, stderr = proc.communicate()
            return {
                "stdout": stdout or "",
                "stderr": stderr or "",
                "returncode": -1,
                "duration_ms": int((time.time() - t0) * 1000),
                "timed_out_kill": action in {"kill", "kill_no_decision"},
                "cancelled": False,
                "timeout_trigger": "timeout",
                "timeout_kill_reason": "no_timeout_decision"
                if action == "kill_no_decision" else "user_kill_decision",
                "checkpoint_index": checkpoint_index,
            }


def _run_interactive_subprocess_with_timeout_prompt(
    cmd: list[str],
    timeout_seconds: int,
    tool_name: str,
    arguments: dict,
    first_checkpoint_seconds: int | None = None,
    idle_timeout_seconds: int | None = None,
) -> dict:
    t0 = time.time()
    master_fd, slave_fd = pty.openpty()
    import tty
    try:
        tty.setraw(master_fd)
        tty.setraw(slave_fd)
    except Exception:
        pass
    _set_nonblocking(master_fd)

    proc = subprocess.Popen(
        cmd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        text=False,
        start_new_session=True,
        close_fds=True,
        preexec_fn=_attach_controlling_tty,
    )
    os.close(slave_fd)

    checkpoint_index = 0
    _clear_timeout_control_files()
    checkpoint_interval = max(1, int(timeout_seconds))
    first_checkpoint = int(first_checkpoint_seconds or _DEFAULT_FIRST_TIMEOUT_CHECKPOINT_SECONDS)
    first_checkpoint = max(1, min(first_checkpoint, checkpoint_interval))
    next_checkpoint_at = t0 + first_checkpoint
    idle_limit = int(idle_timeout_seconds or _DEFAULT_IDLE_TIMEOUT_SECONDS)
    idle_limit = max(0, idle_limit)
    transcript = ""
    last_activity_at = t0
    last_status_at = t0

    while True:
        chunk = _read_pty_available(master_fd, _PROCESS_CANCEL_POLL_SECONDS)
        now = time.time()
        if chunk:
            transcript = _merge_process_stream_text(transcript, chunk)
            last_activity_at = now
            
        if now - last_status_at >= 2.0:
            _write_tool_status(tool_name, int(now - t0), len(transcript), 0)
            last_status_at = now

        if _looks_like_preservable_interactive_session(tool_name, transcript, ""):
            session_id = _preserve_interactive_session(proc, master_fd, tool_name, arguments, cmd, transcript)
            return {
                "stdout": transcript,
                "stderr": "",
                "returncode": 0,
                "duration_ms": int((time.time() - t0) * 1000),
                "timed_out_kill": False,
                "cancelled": False,
                "interactive_preserved": True,
                "interactive_session_id": session_id,
                "checkpoint_index": checkpoint_index,
            }

        if proc.poll() is not None:
            trailing = _read_pty_available(master_fd, 0.1)
            transcript = _merge_process_stream_text(transcript, trailing)
            _close_master_fd_value(master_fd)
            return {
                "stdout": transcript,
                "stderr": "",
                "returncode": int(proc.returncode or 0),
                "duration_ms": int((time.time() - t0) * 1000),
                "timed_out_kill": False,
                "cancelled": False,
                "checkpoint_index": checkpoint_index,
            }

        if _cancel_requested():
            _terminate_process_group(proc)
            trailing = _read_pty_available(master_fd, 0.1)
            transcript = _merge_process_stream_text(transcript, trailing)
            _close_master_fd_value(master_fd)
            return {
                "stdout": transcript,
                "stderr": "",
                "returncode": -1,
                "duration_ms": int((time.time() - t0) * 1000),
                "timed_out_kill": False,
                "cancelled": True,
                "checkpoint_index": checkpoint_index,
            }

        if _tool_stop_requested():
            _terminate_process_group(proc)
            trailing = _read_pty_available(master_fd, 0.1)
            transcript = _merge_process_stream_text(transcript, trailing)
            _close_master_fd_value(master_fd)
            return {
                "stdout": transcript,
                "stderr": "",
                "returncode": int(proc.returncode or 0),
                "duration_ms": int((time.time() - t0) * 1000),
                "timed_out_kill": False,
                "cancelled": False,
                "graceful_stop": True,
                "checkpoint_index": checkpoint_index,
            }

        now = time.time()
        if idle_limit > 0 and (now - last_activity_at) >= idle_limit:
            checkpoint_index += 1
            action, wait_seconds = _await_timeout_decision(
                proc,
                tool_name,
                arguments,
                cmd,
                idle_limit,
                checkpoint_index,
                trigger="idle",
                elapsed_seconds=int(now - t0),
            )
            if action == "wait":
                delay_seconds = max(1, int(wait_seconds or checkpoint_interval))
                checkpoint_interval = delay_seconds
                idle_limit = delay_seconds
                next_checkpoint_at = time.time() + delay_seconds
                last_activity_at = time.time()
                continue
            if action == "background":
                session_id = _preserve_interactive_session(
                    proc,
                    master_fd,
                    tool_name,
                    arguments,
                    cmd,
                    transcript,
                    writable=True,
                    session_kind="interactive",
                )
                return {
                    "stdout": transcript,
                    "stderr": "",
                    "returncode": 0,
                    "duration_ms": int((time.time() - t0) * 1000),
                    "timed_out_kill": False,
                    "cancelled": False,
                    "interactive_preserved": True,
                    "interactive_session_id": session_id,
                    "interactive_session_writable": True,
                    "interactive_session_kind": "interactive",
                    "checkpoint_index": checkpoint_index,
                }

            if action != "finished":
                _terminate_process_group(proc)
            trailing = _read_pty_available(master_fd, 0.1)
            transcript = _merge_process_stream_text(transcript, trailing)
            _close_master_fd_value(master_fd)
            return {
                "stdout": transcript,
                "stderr": "",
                "returncode": -1 if action != "finished" else int(proc.returncode or 0),
                "duration_ms": int((time.time() - t0) * 1000),
                "timed_out_kill": action in {"kill", "kill_no_decision"},
                "cancelled": False,
                "timeout_trigger": "idle",
                "timeout_kill_reason": "no_timeout_decision"
                if action == "kill_no_decision" else "user_kill_decision",
                "checkpoint_index": checkpoint_index,
            }

        if time.time() < next_checkpoint_at:
            continue

        checkpoint_index += 1
        action, wait_seconds = _await_timeout_decision(
            proc,
            tool_name,
            arguments,
            cmd,
            checkpoint_interval,
            checkpoint_index,
            trigger="timeout",
            elapsed_seconds=int(time.time() - t0),
        )
        if action == "wait":
            delay_seconds = max(1, int(wait_seconds or checkpoint_interval))
            checkpoint_interval = delay_seconds
            idle_limit = delay_seconds if idle_limit > 0 else 0
            next_checkpoint_at = time.time() + delay_seconds
            last_activity_at = time.time()
            continue
        if action == "background":
            session_id = _preserve_interactive_session(
                proc,
                master_fd,
                tool_name,
                arguments,
                cmd,
                transcript,
                writable=True,
                session_kind="interactive",
            )
            return {
                "stdout": transcript,
                "stderr": "",
                "returncode": 0,
                "duration_ms": int((time.time() - t0) * 1000),
                "timed_out_kill": False,
                "cancelled": False,
                "interactive_preserved": True,
                "interactive_session_id": session_id,
                "interactive_session_writable": True,
                "interactive_session_kind": "interactive",
                "checkpoint_index": checkpoint_index,
            }

        if action != "finished":
            _terminate_process_group(proc)
        trailing = _read_pty_available(master_fd, 0.1)
        transcript = _merge_process_stream_text(transcript, trailing)
        _close_master_fd_value(master_fd)
        return {
            "stdout": transcript,
            "stderr": "",
            "returncode": -1 if action != "finished" else int(proc.returncode or 0),
            "duration_ms": int((time.time() - t0) * 1000),
            "timed_out_kill": action in {"kill", "kill_no_decision"},
            "cancelled": False,
            "timeout_trigger": "timeout",
            "timeout_kill_reason": "no_timeout_decision"
            if action == "kill_no_decision" else "user_kill_decision",
            "checkpoint_index": checkpoint_index,
        }


def _build_shell_command(name: str, arguments: dict) -> tuple[list[str] | None, str | None]:
    user_args = (arguments.get("args", "") or "").strip()
    if not user_args:
        examples = {
            "shell": "'ls -la', 'ip addr', or 'docker ps'",
            "shell_extended": "'curl -I https://example.com', 'dig example.com', or 'host example.com'",
            "shell_sequence": "'[\"curl -I https://example.com\", \"host example.com\"]' or one command per line",
        }
        return None, f"Error: {name} requires a command, e.g. {examples.get(name, 'a command')}"

    try:
        shell_parts = shlex.split(user_args)
    except ValueError as exc:
        return None, f"Error: Invalid {name} arguments: {exc}"

    if not shell_parts:
        return None, f"Error: {name} requires a command"

    shell_command = shell_parts[0]
    allowed_commands = _ALLOWED_SHELL_COMMANDS if name == "shell" else _ALLOWED_EXTENDED_SHELL_COMMANDS
    if shell_command not in allowed_commands:
        allowed = ", ".join(sorted(allowed_commands))
        return None, f"Error: '{shell_command}' is not allowed. Allowed commands: {allowed}"

    if any(token in _DISALLOWED_SHELL_TOKENS for token in shell_parts[1:]):
        return None, f"Error: {name} does not allow command chaining, pipes, or redirection"

    if name == "shell_extended":
        return _normalize_extended_shell_command(shell_parts)

    return shell_parts, None


def _requested_shell_command(arguments: dict) -> str | None:
    raw_args = (arguments.get("args", "") or "").strip()
    if not raw_args:
        return None
    try:
        shell_parts = shlex.split(raw_args)
    except Exception:
        shell_parts = raw_args.split()
    if not shell_parts:
        return None
    return shell_parts[0]


def _requested_shell_parts(arguments: dict) -> list[str]:
    raw_args = (arguments.get("args", "") or "").strip()
    if not raw_args:
        return []
    try:
        return shlex.split(raw_args)
    except Exception:
        return raw_args.split()


def _normalize_interactive_network_command(user_input: str) -> tuple[str, str | None]:
    raw = str(user_input or "")
    stripped = raw.strip()
    if not stripped:
        return raw, None

    try:
        parts = shlex.split(stripped)
    except Exception:
        return raw, None

    if not parts:
        return raw, None

    # Keep complex shell expressions untouched; only normalize simple one-liners.
    shell_operators = {"|", "||", "&&", ";", "&", ">", ">>", "<", "<<"}
    if any(token in shell_operators for token in parts):
        return raw, None

    command = os.path.basename(parts[0]).strip().lower()
    updated = list(parts)
    added_flags: list[str] = []

    if command == "curl":
        has_connect_timeout = any(
            token == "--connect-timeout" or token.lower().startswith("--connect-timeout=")
            for token in updated
        )
        has_max_time = any(
            token == "--max-time" or token.lower().startswith("--max-time=")
            for token in updated
        )
        has_silent = False
        has_show_error = False
        for token in updated:
            lowered = token.lower()
            if token in {"-s", "--silent"}:
                has_silent = True
            if token in {"-S", "--show-error"}:
                has_show_error = True
            if token.startswith("-") and not token.startswith("--"):
                if "s" in token[1:]:
                    has_silent = True
                if "S" in token[1:]:
                    has_show_error = True
            if lowered == "--silent":
                has_silent = True
            if lowered == "--show-error":
                has_show_error = True
        if not has_connect_timeout:
            updated.extend(["--connect-timeout", "5"])
            added_flags.append("--connect-timeout 5")
        if not has_max_time:
            updated.extend(["--max-time", "30"])
            added_flags.append("--max-time 30")
        if has_silent and not has_show_error:
            updated.append("--show-error")
            added_flags.append("--show-error")
    elif command == "wget":
        has_timeout = any(token.lower().startswith("--timeout") for token in updated)
        has_dns_timeout = any(token.lower().startswith("--dns-timeout") for token in updated)
        has_connect_timeout = any(token.lower().startswith("--connect-timeout") for token in updated)
        has_read_timeout = any(token.lower().startswith("--read-timeout") for token in updated)
        has_tries = any(token.lower().startswith("--tries") for token in updated)

        if not has_timeout:
            updated.append("--timeout=20")
            added_flags.append("--timeout=20")
        if not has_dns_timeout:
            updated.append("--dns-timeout=10")
            added_flags.append("--dns-timeout=10")
        if not has_connect_timeout:
            updated.append("--connect-timeout=10")
            added_flags.append("--connect-timeout=10")
        if not has_read_timeout:
            updated.append("--read-timeout=20")
            added_flags.append("--read-timeout=20")
        if not has_tries:
            updated.append("--tries=1")
            added_flags.append("--tries=1")

    if not added_flags:
        return raw, None

    normalized_command = shlex.join(updated)
    note = (
        "Applied safety flags to keep this interactive network command bounded: "
        + ", ".join(added_flags)
        + "."
    )
    return normalized_command, note


def _resolve_shell_delegation(config: dict, current_tool_name: str, arguments: dict) -> tuple[str, dict, dict] | None:
    shell_parts = _requested_shell_parts(arguments)
    if not shell_parts:
        return None

    tools_by_name = {}
    # Build a lookup: map tool name, command binary, and base_args binaries → tool
    for tool in config.get("tools", []):
        if not isinstance(tool, dict):
            continue
        tname = str(tool.get("name", "")).strip()
        if not tname:
            continue
        tools_by_name[tname] = tool
        # Also index by the command binary (e.g., "arp-scan" → arp_scan tool)
        cmd_bin = str(tool.get("command", "")).rsplit('/', 1)[-1].strip()
        if cmd_bin and cmd_bin not in ("timeout", "sudo", "env") and cmd_bin not in tools_by_name:
            tools_by_name[cmd_bin] = tool
        # Also index by binary names found in base_args (for timeout-wrapped tools)
        for ba in tool.get("base_args", []):
            ba_str = str(ba).strip()
            if ba_str and not ba_str.startswith("{") and ba_str not in tools_by_name:
                tools_by_name[ba_str] = tool

    # Try to find a matching tool name in the first few tokens of the command.
    # This handles patterns like: "tcpdump -i eth0", "timeout 20 tcpdump -i eth0",
    # "sudo tcpdump ...", "arp-scan -l", "/usr/bin/nmap ...", etc.
    matched_tool_name = None
    matched_index = None
    for i, part in enumerate(shell_parts[:5]):
        # Strip path prefixes (e.g. /usr/bin/tcpdump → tcpdump)
        basename = part.rsplit('/', 1)[-1]
        if basename in tools_by_name and basename != current_tool_name:
            matched_tool_name = tools_by_name[basename].get("name", basename)
            matched_index = i
            break

    if matched_tool_name is None:
        return None

    delegated_tool = tools_by_name[matched_tool_name]

    # Extract only the args AFTER the tool name, stripping prefix words
    # like "timeout", "sudo", etc.
    remaining_parts = shell_parts[matched_index + 1:]

    # Sanitize: strip shell chaining from the delegated args
    import re
    delegated_args_str = shlex.join(remaining_parts) if remaining_parts else ""
    # Strip everything after semicolons
    delegated_args_str = delegated_args_str.split(';')[0].strip()
    # Strip backgrounding: " & <command>" pattern
    delegated_args_str = re.sub(r'\s+&\s+\S.*$', '', delegated_args_str).strip()
    # Strip backtick and subshell patterns
    delegated_args_str = re.sub(r'`[^`]*`', '', delegated_args_str)
    delegated_args_str = re.sub(r'\$\([^)]*\)', '', delegated_args_str)
    delegated_args_str = delegated_args_str.strip()

    new_arguments = {"args": delegated_args_str}

    # If the original command had "timeout <N>" before the tool, pass it
    # through as timeout_seconds for {timeout}-wrapped tools.
    if matched_index >= 1 and shell_parts[0] in ("timeout",):
        try:
            new_arguments["timeout_seconds"] = int(shell_parts[1])
        except (ValueError, IndexError):
            pass

    return matched_tool_name, delegated_tool, new_arguments


def _run_shell_sequence(arguments: dict, timeout_seconds: int, config: dict | None = None) -> tuple[str, int, int]:
    # Check if shell_dangerous is available for fallback
    has_dangerous = False
    if config:
        has_dangerous = any(t.get("name") == "shell_dangerous" for t in config.get("tools", []))

    raw_args = arguments.get("args", "")
    commands, parse_error = _parse_shell_sequence(raw_args, has_dangerous)
    if parse_error:
        return parse_error, -1, 0

    output_chunks = []
    t0 = time.time()
    overall_exit_code = 0

    for index, command in enumerate(commands, start=1):
        cmd, error_text = _build_shell_command("shell_extended", {"args": command})
        
        if error_text and has_dangerous:
            # Fall back to dangerous command if allowed
            cmd, error_text = _build_dangerous_shell_command({"args": command})

        if error_text:
            output_chunks.append(f"Step {index}: {command}\n{error_text}")
            overall_exit_code = -1
            break

        try:
            execution = _run_subprocess_with_timeout_prompt(cmd, timeout_seconds, "shell_sequence", {"args": command}, preserve_interactive=True)
        except subprocess.TimeoutExpired:
            output_chunks.append(
                f"Step {index}: {command}\nExecution error: Command timed out after {int(timeout_seconds)} seconds"
            )
            overall_exit_code = -1
            break
            
        if execution.get("interactive_preserved"):
            session_id = execution.get("interactive_session_id")
            step_output = f"Interactive session preserved as {session_id}."
            if execution.get('stdout'):
                step_output += f"\nSTDOUT:\n{execution.get('stdout')}"
            output_chunks.append(f"Step {index}: {command}\n{step_output}")
            overall_exit_code = 0
            break

        if execution.get("timed_out_kill"):
            elapsed_seconds = max(int(execution.get("duration_ms", 0) / 1000), int(timeout_seconds))
            if execution.get("timeout_kill_reason") == "no_timeout_decision":
                step_output = (
                    f"Execution stopped after {elapsed_seconds} seconds because no timeout checkpoint "
                    f"decision was provided for checkpoint {execution.get('checkpoint_index', 1)}."
                )
            else:
                step_output = (
                    f"Execution stopped after {elapsed_seconds} seconds because the user chose kill "
                    f"at timeout checkpoint {execution.get('checkpoint_index', 1)}."
                )
            partial_stdout = _strip_ansi(execution.get("stdout") or "")
            partial_stderr = _strip_ansi(execution.get("stderr") or "")
            if partial_stdout:
                step_output += f"\n\nPartial STDOUT:\n{partial_stdout}"
            if partial_stderr:
                step_output += f"\n\nPartial STDERR:\n{partial_stderr}"
            output_chunks.append(f"Step {index}: {command}\n{step_output}")
            overall_exit_code = -1
            break

        step_output = _strip_ansi(execution.get("stdout") or "")
        step_stderr = _strip_ansi(execution.get("stderr") or "")
        if step_stderr:
            step_output += f"\nSTDERR:\n{step_stderr}"
        step_output = step_output or "Command executed successfully (no output)"
        output_chunks.append(f"Step {index}: {command}\n{step_output}")

        if execution.get("returncode") != 0:
            overall_exit_code = int(execution.get("returncode") or 0)
            break

    duration_ms = int((time.time() - t0) * 1000)
    return "\n\n".join(output_chunks), overall_exit_code, duration_ms


def _build_dangerous_shell_command(arguments: dict) -> tuple[list[str] | None, str | None]:
    user_args = (arguments.get("args", "") or "").strip()
    if not user_args:
        return None, "Error: shell_dangerous requires a command"
    if "\x00" in user_args:
        return None, "Error: shell_dangerous command contains a null byte"
    normalized_args, _ = _normalize_interactive_network_command(user_args)
    return ["/bin/sh", "-lc", normalized_args], None


def _collect_string_values(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        values = []
        for item in value.values():
            values.extend(_collect_string_values(item))
        return values
    if isinstance(value, (list, tuple, set)):
        values = []
        for item in value:
            values.extend(_collect_string_values(item))
        return values
    return []


def _extract_targets_from_args(arguments: dict) -> list[dict]:
    targets = []
    seen = set()

    for text in _collect_string_values(arguments):
        for url in _URL_RE.findall(text):
            host = (urlparse(url).hostname or "").lower()
            target = {"kind": "url", "value": url, "host": host}
            key = (target["kind"], target["value"])
            if key not in seen:
                seen.add(key)
                targets.append(target)

        try:
            tokens = shlex.split(text)
        except Exception:
            tokens = text.split()

        for token in tokens:
            cleaned = token.strip().strip(',;()[]{}')
            if not cleaned or cleaned.startswith('-'):
                continue
            if '://' in cleaned:
                continue

            host_candidate = cleaned
            if '/' in host_candidate and not _CIDR_OR_IP_RE.fullmatch(host_candidate):
                host_candidate = host_candidate.split('/', 1)[0]
            if ':' in host_candidate and host_candidate.count(':') == 1 and not _CIDR_OR_IP_RE.fullmatch(host_candidate):
                host_candidate = host_candidate.rsplit(':', 1)[0]

            if _CIDR_OR_IP_RE.fullmatch(host_candidate):
                kind = 'cidr' if '/' in host_candidate else 'ip'
                key = (kind, host_candidate)
                if key not in seen:
                    seen.add(key)
                    targets.append({"kind": kind, "value": host_candidate})
                continue

            hostname = host_candidate.rstrip('.').lower()
            if _HOSTNAME_RE.fullmatch(hostname):
                key = ('hostname', hostname)
                if key not in seen:
                    seen.add(key)
                    targets.append({"kind": 'hostname', "value": hostname})

    return targets


def _entry_matches_target(entry: str, target: dict) -> bool:
    entry = entry.strip()
    if not entry:
        return False
    if entry == '*':
        return True

    entry_lower = entry.lower().rstrip('.')
    target_kind = target.get('kind')
    target_value = str(target.get('value', '')).lower().rstrip('.')
    target_host = str(target.get('host', '')).lower().rstrip('.')

    if entry_lower.startswith('http://') or entry_lower.startswith('https://'):
        parsed = urlparse(entry_lower)
        if target_kind == 'url':
            return target_value.startswith(entry_lower)
        if target_host:
            return target_host == (parsed.hostname or '').lower().rstrip('.')
        return False

    try:
        if '/' in entry_lower:
            entry_net = ipaddress.ip_network(entry_lower, strict=False)
            if target_kind == 'ip':
                return ipaddress.ip_address(target_value) in entry_net
            if target_kind == 'cidr':
                return ipaddress.ip_network(target_value, strict=False).subnet_of(entry_net)
            return False
        entry_ip = ipaddress.ip_address(entry_lower)
        if target_kind == 'ip':
            return ipaddress.ip_address(target_value) == entry_ip
        if target_kind == 'cidr':
            target_net = ipaddress.ip_network(target_value, strict=False)
            return target_net.num_addresses == 1 and target_net.network_address == entry_ip
        return False
    except ValueError:
        pass

    if target_kind == 'hostname':
        return target_value == entry_lower or target_value.endswith('.' + entry_lower)
    if target_host:
        return target_host == entry_lower or target_host.endswith('.' + entry_lower)
    return False


def _evaluate_network_policy(policy: dict, arguments: dict) -> tuple[bool, str | None]:
    normalized = _normalize_network_policy(policy)
    targets = _extract_targets_from_args(arguments)
    if not targets:
        return True, None

    disallow_entries = normalized['disallow']
    allow_entries = normalized['allow']
    allow_any = '*' in allow_entries

    for target in targets:
        for entry in disallow_entries:
            if _entry_matches_target(entry, target):
                return False, f"Target '{target['value']}' is blocked by disallow rule '{entry}'."

        if not allow_any and not any(_entry_matches_target(entry, target) for entry in allow_entries):
            return False, f"Target '{target['value']}' is outside the allow list."

    return True, None

# Session logging — optional: if session_logger.py is unavailable the server still works
try:
    from session_logger import SessionLogger, make_run_id as _make_run_id

    # If the web UI is driving this session, use its exact run ID so all
    # logs end up in the same folder. Otherwise generate a fresh ID per invocation.
    if "MCP_CURRENT_RUN_ID" in os.environ:
        _run_id = os.environ["MCP_CURRENT_RUN_ID"]
    else:
        _label = os.environ.get("MCP_RUN_ID", "native")
        _run_id = _make_run_id(_label)
    _logger = SessionLogger(
        run_id=_run_id,
        metadata={
            "server_type": "native",
            "model": os.environ.get("MCP_MODEL", "unknown"),
            "ollama_url": os.environ.get("MCP_OLLAMA_URL", "unknown"),
        }
    )
except Exception:
    # Fallback no-op logger so the server runs even without session_logger
    class _NoopLogger:
        def log_tool_call(self, *a, **kw): pass
        def finalize(self, *a, **kw): pass
    _logger = _NoopLogger()


@server.list_tools()
async def list_tools() -> list[Tool]:
    config = _get_tools_config()
    
    tools = []
    for t in config.get("tools", []):
        # Skip interactive session tools from kali_tools.json — always use builtins
        if t["name"] in _BUILTIN_INTERACTIVE_TOOLS:
            continue
        properties = {
            "args": {"type": "string", "description": "Arguments to pass to the tool"}
        }
        
        has_timeout = any("{timeout}" in str(a) for a in t.get("base_args", []))
        if has_timeout:
            properties["timeout_seconds"] = {
                "type": "integer",
                "description": (
                    "REQUIRED: How many seconds this command should run before being terminated. "
                    "If the user says 'run for 15 seconds', set this to 15. Default is 60. "
                    "Do NOT put duration or time limits in the 'args' field — use this parameter instead."
                ),
                "default": 60
            }
            properties["args"]["description"] = (
                "Arguments to pass to the tool (e.g., filters, interfaces, flags). "
                "Do NOT include any duration, timeout, or time-limit flags here (e.g., no -G, -W, -c, -a duration). "
                "Use the timeout_seconds parameter to control execution time."
            )

        tools.append(Tool(
            name=t["name"],
            description=t.get("description", f"Run {t['name']}"),
            inputSchema={
                "type": "object",
                "properties": properties,
                "required": ["timeout_seconds"] if has_timeout else []
            }
        ))
    existing_tool_names = {t.name for t in tools}
    builtin_tools = _builtin_interactive_tools(bool(config.get("tools")) or bool(_interactive_sessions))
    for bt in builtin_tools:
        if bt.name not in existing_tool_names:
            tools.append(bt)
    return tools

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name in _BUILTIN_INTERACTIVE_TOOLS:
        t0 = time.time()
        output, exit_code = _interactive_session_tool_result(name, arguments or {})
        duration_ms = int((time.time() - t0) * 1000)

        # Only log meaningful interactions — skip noisy polling reads
        should_log = True
        if name in ("interactive_session_read", "interactive_session_list"):
            # Don't log polling reads that return status messages (no real output)
            if not output or "has no new output" in output or "no preserved interactive sessions" in output.lower():
                should_log = False

        if should_log:
            _logger.log_tool_call(
                name=name,
                args=arguments or {},
                result=output or "Command executed successfully (no output)",
                duration_ms=duration_ms,
                exit_code=exit_code,
            )
        return [TextContent(type="text", text=output or "Command executed successfully (no output)")]

    config = _get_tools_config()
        
    tool_config = next((t for t in config.get("tools", []) if t["name"] == name), None)
    if not tool_config:
        return [TextContent(type="text", text=f"Error: Tool {name} not found in config")]

    policy_allowed, policy_message = _evaluate_network_policy(_NETWORK_POLICY, arguments)
    if not policy_allowed:
        return [TextContent(type="text", text=f"Policy blocked tool call to {name}: {policy_message}")]

    delegated_from_shell = False
    if name in {"shell", "shell_extended"}:
        delegation = _resolve_shell_delegation(config, name, arguments)
        if delegation:
            name, tool_config, arguments = delegation
            delegated_from_shell = True
        else:
            cmd, error_text = _build_shell_command(name, arguments)
            if error_text:
                dangerous_config = next(
                    (t for t in config.get("tools", []) if t.get("name") == "shell_dangerous"),
                    None,
                )
                if dangerous_config:
                    name = "shell_dangerous"
                    tool_config = dangerous_config
                    cmd, error_text = _build_dangerous_shell_command(arguments)
                    if error_text:
                        return [TextContent(type="text", text=error_text)]
                else:
                    return [TextContent(type="text", text=error_text)]
    elif name == "shell_sequence":
        default_timeout = int(os.environ.get("MCP_TOOL_TIMEOUT", 120))
        timeout_seconds = int(tool_config.get("timeout_seconds", default_timeout) or default_timeout)
        output, exit_code, duration_ms = await asyncio.to_thread(_run_shell_sequence, arguments, timeout_seconds, config=config)
        _logger.log_tool_call(
            name=name,
            args=arguments,
            result=output or "Command executed successfully (no output)",
            duration_ms=duration_ms,
            exit_code=exit_code,
        )
        return [TextContent(type="text", text=output or "Command executed successfully (no output)")]
    elif name == "shell_dangerous":
        cmd, error_text = _build_dangerous_shell_command(arguments)
        if error_text:
            return [TextContent(type="text", text=error_text)]
    if name not in {"shell", "shell_extended", "shell_sequence", "shell_dangerous"} or delegated_from_shell:
        cmd = [tool_config["command"]]
        base_args = tool_config.get("base_args", [])
        user_args = arguments.get("args", "")
        has_timeout_ph = any("{timeout}" in str(a) for a in base_args)
        
        # For timeout-wrapped tools: extract duration hints the LLM may have
        # embedded in args instead of using the timeout_seconds parameter.
        explicit_timeout = arguments.get("timeout_seconds")
        timeout_val = str(explicit_timeout if explicit_timeout is not None else 60)
        
        if has_timeout_ph and user_args and explicit_timeout is None:
            import re
            extracted = None
            
            # Pattern 1: bare trailing number (e.g., "-w /tmp/x.pcap 10")
            m = re.search(r'\s+(\d+)\s*$', user_args)
            if m:
                extracted = int(m.group(1))
                user_args = user_args[:m.start()].strip()
            
            # Pattern 2: -G <seconds> flag (tcpdump rotation timer)
            if extracted is None:
                m = re.search(r'-G\s+(\d+)', user_args)
                if m:
                    extracted = int(m.group(1))
                    user_args = user_args[:m.start()] + user_args[m.end():]
                    user_args = user_args.strip()
                    # Also strip -W if present (rotation count paired with -G)
                    user_args = re.sub(r'-W\s+\d+', '', user_args).strip()
            
            # Pattern 3: -a duration:<seconds> (tshark)
            if extracted is None:
                m = re.search(r'-a\s+duration:(\d+)', user_args)
                if m:
                    extracted = int(m.group(1))
                    user_args = user_args[:m.start()] + user_args[m.end():]
                    user_args = user_args.strip()
            
            # Pattern 4: -c <count> — leave it alone, it's packet count not time
            
            if extracted and extracted > 0:
                timeout_val = str(extracted)
        
        # Sanitize: strip shell command-chaining that the LLM sometimes injects.
        # These tools run via subprocess (not a shell), so chained commands break.
        # We preserve && and || since they are valid BPF filter operators for
        # tcpdump/tshark (e.g., "host 10.0.0.1 && port 80").
        if user_args and name not in {"shell", "shell_extended", "shell_dangerous"}:
            import re
            # Strip everything after a semicolon (always shell chaining)
            user_args = user_args.split(';')[0].strip()
            # Strip backgrounding: " & <command>" pattern (space-ampersand-space-word)
            user_args = re.sub(r'\s+&\s+\S.*$', '', user_args).strip()
            # Remove backtick and $() subshell patterns
            user_args = re.sub(r'`[^`]*`', '', user_args)
            user_args = re.sub(r'\$\([^)]*\)', '', user_args)
            user_args = user_args.strip()
        
        if name == "msf_run":
            user_args = _prepare_msf_run_args(user_args)
        
        if base_args:
            has_args_ph = any("{args}" in a for a in base_args)
            
            if has_args_ph or has_timeout_ph:
                cmd.extend([
                    a.replace("{args}", user_args).replace("{timeout}", timeout_val) 
                    for a in base_args
                ])
                # If there was a {timeout} but no {args} placeholder, we still
                # need to append user arguments after the substituted base_args.
                if not has_args_ph and tool_config.get("allow_args", False) and user_args:
                    cmd.extend(shlex.split(user_args))
            else:
                cmd.extend(base_args)
                if tool_config.get("allow_args", False) and user_args:
                    cmd.extend(shlex.split(user_args))
        elif tool_config.get("allow_args", False) and user_args:
            cmd.extend(shlex.split(user_args))
        
        _logger.log_tool_call(
            name=f"{name}:cmd_debug",
            args={"constructed_cmd": cmd},
            result="(pre-execution debug)",
            duration_ms=0,
            exit_code=None,
        )

    interactive_capable = _tool_supports_interactive_sessions(name, tool_config)
        
    try:
        t0 = time.time()
        default_timeout = int(os.environ.get("MCP_TOOL_TIMEOUT", 300))
        timeout_seconds = int(tool_config.get("timeout_seconds", default_timeout) or default_timeout)
        first_checkpoint_seconds = int(
            tool_config.get("first_checkpoint_seconds", _DEFAULT_FIRST_TIMEOUT_CHECKPOINT_SECONDS)
            or _DEFAULT_FIRST_TIMEOUT_CHECKPOINT_SECONDS
        )
        idle_timeout_seconds = int(
            tool_config.get("idle_timeout_seconds", _DEFAULT_IDLE_TIMEOUT_SECONDS)
            or _DEFAULT_IDLE_TIMEOUT_SECONDS
        )
        execution = await asyncio.to_thread(
            _run_subprocess_with_timeout_prompt,
            cmd,
            timeout_seconds,
            name,
            arguments,
            preserve_interactive=interactive_capable,
            first_checkpoint_seconds=first_checkpoint_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
        )
        duration_ms = int(execution.get("duration_ms") or int((time.time() - t0) * 1000))

        output = _strip_ansi(execution.get("stdout") or "")
        stderr = _strip_ansi(execution.get("stderr") or "")
        if execution.get("interactive_preserved"):
            session_id = str(execution.get("interactive_session_id") or "").strip()
            session_writable = bool(execution.get("interactive_session_writable", True))
            session_kind = str(execution.get("interactive_session_kind") or "interactive")
            if session_kind == "background" and not session_writable:
                preserved_message = (
                    f"Interactive session preserved as {session_id}.\n"
                    f"IMPORTANT: This is a read-only background session for the running tool.\n"
                    f"- Use interactive_session_read with session_id=\"{session_id}\" to collect output.\n"
                    f"- interactive_session_write is unavailable because this session does not accept input.\n"
                    f"- Use interactive_session_list to see all active sessions.\n"
                    f"- Use interactive_session_close with session_id=\"{session_id}\" when you are done."
                )
            else:
                preserved_message = (
                    f"Interactive session preserved as {session_id}.\n"
                    f"IMPORTANT: To interact with this session, you MUST use session_id=\"{session_id}\" (not a Metasploit session number).\n"
                    f"- Use interactive_session_write with session_id=\"{session_id}\" and input=\"<your command>\" to send commands.\n"
                    f"- Use interactive_session_read with session_id=\"{session_id}\" to collect output.\n"
                    f"- Use interactive_session_list to see all active sessions.\n"
                    f"- Use interactive_session_close with session_id=\"{session_id}\" when you are done."
                )
            output = preserved_message
            if execution.get("stdout"):
                output += f"\n\nCaptured output before preservation:\n{_strip_ansi(execution.get('stdout') or '')}"
            output += "\n\n" + _manual_recreation_instructions(name, arguments, cmd)
        elif execution.get("interactive_handoff"):
            output = str(execution.get("handoff_message") or "Interactive session detected.")
            if execution.get("stdout"):
                output += f"\n\nCaptured STDOUT before handoff:\n{_strip_ansi(execution.get('stdout') or '')}"
            if stderr:
                output += f"\n\nCaptured STDERR before handoff:\n{stderr}"
        elif execution.get("cancelled"):
            elapsed_seconds = max(1, int(duration_ms / 1000))
            output = f"Execution cancelled after {elapsed_seconds} seconds by the user."
            if execution.get("stdout"):
                output += f"\n\nPartial STDOUT:\n{_strip_ansi(execution.get('stdout') or '')}"
            if stderr:
                output += f"\n\nPartial STDERR:\n{stderr}"
        elif execution.get("graceful_stop"):
            output = "[GRACEFUL STOP] Tool was manually stopped by the user. The output below is partial but should be analyzed."
            if execution.get("stdout"):
                output += f"\n\nPartial STDOUT:\n{_strip_ansi(execution.get('stdout') or '')}"
            if stderr:
                output += f"\n\nPartial STDERR:\n{stderr}"
        elif execution.get("timed_out_kill"):
            elapsed_seconds = max(int(duration_ms / 1000), int(timeout_seconds))
            checkpoint_kind = "idle-output checkpoint" if execution.get("timeout_trigger") == "idle" else "timeout checkpoint"
            if execution.get("timeout_kill_reason") == "no_timeout_decision":
                output = (
                    f"Execution stopped after {elapsed_seconds} seconds because no {checkpoint_kind} decision "
                    f"was provided for checkpoint {execution.get('checkpoint_index', 1)}."
                )
            else:
                output = (
                    f"Execution stopped after {elapsed_seconds} seconds because the user chose kill "
                    f"at {checkpoint_kind} {execution.get('checkpoint_index', 1)} instead of waiting longer."
                )
            if execution.get("stdout"):
                output += f"\n\nPartial STDOUT:\n{_strip_ansi(execution.get('stdout') or '')}"
            if stderr:
                output += f"\n\nPartial STDERR:\n{stderr}"
        elif stderr:
            output += f"\nSTDERR:\n{stderr}"

        # Log the tool call
        _logger.log_tool_call(
            name=name,
            args=arguments,
            result=output or "Command executed successfully (no output)",
            duration_ms=duration_ms,
            exit_code=0 if execution.get("interactive_handoff") or execution.get("interactive_preserved") or execution.get("graceful_stop") else int(execution.get("returncode") or 0),
            stderr=stderr,
            graceful_stop=execution.get("graceful_stop", False),
        )

        return [TextContent(type="text", text=output or "Command executed successfully (no output)")]
    except subprocess.TimeoutExpired as e:
        if name == "msf_run":
            err_msg = (
                f"Execution error: msf_run timed out after {int(e.timeout)} seconds. "
                "This usually means the Metasploit exploit workflow kept waiting for a session or module completion. "
                "The wrapper already forces batch mode defaults (`set WfsDelay 10` and `exploit/run -z`) for exploit modules unless you override them. "
                "If you need different behavior, set `WfsDelay` explicitly, use `check` when supported, or use an auxiliary/scanner module instead of a full exploit."
            )
        else:
            err_msg = f"Execution error: Command timed out after {int(e.timeout)} seconds"
        _logger.log_tool_call(name=name, args=arguments, result=err_msg, exit_code=-1)
        return [TextContent(type="text", text=err_msg)]
    except Exception as e:
        err_msg = f"Execution error: {str(e)}"
        _logger.log_tool_call(name=name, args=arguments, result=err_msg, exit_code=-1)
        return [TextContent(type="text", text=err_msg)]

async def main():
    try:
        from mcp.server.stdio import stdio_server
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        _logger.finalize()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
