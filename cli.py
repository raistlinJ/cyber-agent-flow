#!/usr/bin/env python3
"""Command-line interface for CyberAgentFlow."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import shlex
import signal
import shutil
import sys
import time
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import ANSI

# ANSI color codes for terminal output (matching web UI colors)
class Colors:
    """ANSI color codes matching web UI CSS variables."""
    RESET = "\033[0m"
    
    # Background
    BG_DARK = "\033[38;5;235m"  # #0f1115
    
    # Text
    TEXT_PRIMARY = "\033[38;5;255m"   # #e2e8f0
    TEXT_SECONDARY = "\033[38;5;246m"  # #94a3b8
    
    # Accents
    ACCENT_PRIMARY = "\033[38;5;69m"   # #3b82f6 (blue)
    ACCENT_SUCCESS = "\033[38;5;40m"   # #10b981 (green)
    ACCENT_ERROR = "\033[38;5;196m"    # #ef4444 (red)
    ACCENT_WARNING = "\033[38;5;220m"  # #fbbf24 (yellow)
    
    # Styles
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"

try:
    import readline
except Exception:
    readline = None

try:
    import termios
    import tty
    _HAS_TERMIOS = True
except ImportError:
    _HAS_TERMIOS = False

from mcp_client import MCPSession
from session_logger import load_session_list, make_run_id


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PROJECT_DIR / "configs" / "cli.json"
DEFAULT_PROVIDER = os.environ.get("MCP_LLM_PROVIDER", "ollama_direct")
DEFAULT_URL = os.environ.get("MCP_OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("MCP_MODEL", "")
DEFAULT_API_KEY = os.environ.get("MCP_API_KEY") or os.environ.get("OLLAMA_API_KEY") or ""
DEFAULT_SERVER_COMMAND = f"{shlex.quote(sys.executable)} {shlex.quote(str(PROJECT_DIR / 'mcp_kali.py'))}"
SCOPE_CHOICES = ("broad", "medium-broad", "medium", "medium-narrow", "narrow")
URGENCY_CHOICES = ("stealthy", "methodical", "balanced", "fast", "speed")
TIMEOUT_WAIT_CHOICES = (30, 60, 90, 120, 300)
SLASH_COMMANDS = (
    "/help",
    "/exit",
    "/quit",
    "/cancel",
    "/force_analyze",
    "/enter",
    "/back",
    "/main",
    "/where",
    "/config",
    "/set",
    "/save-config",
    "/tools",
    "/scope",
    "/urgency",
    "/sessions",
    "/refresh-sessions",
    "/read",
    "/write",
    "/close",
)
SETTABLE_CONFIG_KEYS = (
    "provider",
    "url",
    "model",
    "api_key",
    "ssl_verify",
    "server_command",
    "tools_config",
    "context_window",
    "max_turns",
    "allow",
    "disallow",
    "scope",
    "scope_enabled",
    "urgency",
    "urgency_enabled",
    "tool_output_chars",
    "verbose",
)
SESSION_ID_RE = re.compile(r"\bisess-[a-zA-Z0-9_-]+\b")
BUILTIN_SESSION_DEFAULTS: dict[str, Any] = {
    "provider": DEFAULT_PROVIDER,
    "url": DEFAULT_URL,
    "model": DEFAULT_MODEL,
    "api_key": DEFAULT_API_KEY,
    "ssl_verify": True,
    "server_command": DEFAULT_SERVER_COMMAND,
    "tools_config": "kali_tools.json",
    "context_window": 8192,
    "max_turns": 20,
    "tool_timeout": 120,
    "network_policy": {"allow": ["*"], "disallow": []},
    "scope": "medium",
    "scope_enabled": True,
    "urgency": "balanced",
    "urgency_enabled": True,
    "tool_output_chars": 4000,
    "verbose": False,
    "prompt": None,
}


def _compact_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    except Exception:
        return str(value)


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"{text[:max_chars]}\n...[truncated {omitted} chars; full output is in runs/]"


def _split_entries(values: list[str] | None, default: list[str]) -> list[str]:
    if not values:
        return default
    entries: list[str] = []
    for raw_value in values:
        for part in str(raw_value).replace("\n", ",").split(","):
            entry = part.strip()
            if entry:
                entries.append(entry)
    return entries or default


def _coerce_list(value: Any, default: list[str]) -> list[str]:
    if value is None:
        return list(default)
    if isinstance(value, str):
        return _split_entries([value], default)
    if isinstance(value, list):
        return _split_entries([str(item) for item in value], default)
    raise ValueError(f"Expected a string or list, got {type(value).__name__}")


def _network_policy_from_args(args: argparse.Namespace) -> dict[str, list[str]]:
    return {
        "allow": _split_entries(getattr(args, "allow", None), []),
        "disallow": _split_entries(getattr(args, "disallow", None), []),
    }


def _network_policy_from_config(config: dict[str, Any]) -> dict[str, list[str]]:
    policy = config.get("network_policy") or {}
    if not isinstance(policy, dict):
        raise ValueError("network_policy must be an object with allow/disallow lists.")
    return {
        "allow": _coerce_list(policy.get("allow"), ["*"]),
        "disallow": _coerce_list(policy.get("disallow"), []),
    }


def _resolve_path(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def _to_bool(value_text: str) -> bool:
    value = str(value_text or "").strip().lower()
    if value in {"1", "true", "yes", "on", "enable", "enabled"}:
        return True
    if value in {"0", "false", "no", "off", "disable", "disabled"}:
        return False
    raise ValueError("Expected boolean value: true|false")


def _extract_session_ids_from_text(text: str) -> list[str]:
    values = []
    seen = set()
    for match in SESSION_ID_RE.findall(str(text or "")):
        if match not in seen:
            values.append(match)
            seen.add(match)
    return values


async def _refresh_known_session_ids(session: MCPSession, known_session_ids: set[str]) -> int:
    result = await session.call_tool_direct("interactive_session_list", {})
    if not bool(result.get("success")):
        return 0

    discovered = set(_extract_session_ids_from_text(str(result.get("content") or "")))
    if discovered:
        known_session_ids.update(discovered)
    return len(discovered)


def _load_session_config(path_text: str | None) -> dict[str, Any]:
    if not path_text:
        if not DEFAULT_CONFIG_PATH.exists():
            return {}
        config_path = DEFAULT_CONFIG_PATH
    else:
        config_path = _resolve_path(path_text)

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with config_path.open() as config_file:
        config = json.load(config_file)
    if not isinstance(config, dict):
        raise ValueError("Config file must contain a JSON object.")
    return config


def _apply_config_value(resolved: dict[str, Any], key: str, value: Any) -> None:
    if key in {"context_window", "max_turns", "tool_timeout", "tool_output_chars"}:
        resolved[key] = int(value)
    elif key in {"ssl_verify", "scope_enabled", "urgency_enabled", "verbose"}:
        resolved[key] = bool(value)
    elif key == "api_key_env":
        env_val = os.environ.get(str(value or ""))
        if env_val:
            resolved["api_key"] = env_val
    elif key in {"provider", "url", "model", "api_key", "server_command", "tools_config", "scope", "urgency", "prompt"}:
        resolved[key] = None if value is None else str(value)
    else:
        raise ValueError(f"Unsupported session config key: {key}")


def _resolve_session_args(args: argparse.Namespace) -> argparse.Namespace:
    config = _load_session_config(getattr(args, "config", None))
    resolved = dict(BUILTIN_SESSION_DEFAULTS)

    for key, value in config.items():
        if key == "network_policy":
            resolved["network_policy"] = _network_policy_from_config(config)
            continue
        _apply_config_value(resolved, key, value)

    cli_value_keys = (
        "provider",
        "url",
        "model",
        "api_key",
        "server_command",
        "tools_config",
        "context_window",
        "max_turns",
        "tool_timeout",
        "scope",
        "urgency",
        "tool_output_chars",
    )
    for key in cli_value_keys:
        value = getattr(args, key, None)
        if value is not None:
            _apply_config_value(resolved, key, value)

    if getattr(args, "no_ssl_verify", False):
        resolved["ssl_verify"] = False
    if getattr(args, "no_scope", False):
        resolved["scope_enabled"] = False
    if getattr(args, "no_urgency", False):
        resolved["urgency_enabled"] = False
    if getattr(args, "verbose", None) is True:
        resolved["verbose"] = True

    if getattr(args, "allow", None) is not None or getattr(args, "disallow", None) is not None:
        policy = dict(resolved["network_policy"])
        cli_policy = _network_policy_from_args(args)
        if getattr(args, "allow", None) is not None:
            policy["allow"] = cli_policy["allow"] or ["*"]
        if getattr(args, "disallow", None) is not None:
            policy["disallow"] = cli_policy["disallow"]
        resolved["network_policy"] = policy

    prompt_parts = list(getattr(args, "prompt", []) or [])
    if prompt_parts and prompt_parts[0] == "--":
        prompt_parts = prompt_parts[1:]
    if prompt_parts:
        resolved["prompt"] = " ".join(prompt_parts).strip()

    merged = argparse.Namespace(**vars(args))
    merged.provider = resolved["provider"]
    merged.url = resolved["url"]
    merged.model = resolved["model"]
    merged.api_key = resolved["api_key"]
    merged.no_ssl_verify = not bool(resolved["ssl_verify"])
    merged.server_command = resolved["server_command"]
    merged.tools_config = resolved["tools_config"]
    merged.context_window = resolved["context_window"]
    merged.max_turns = resolved["max_turns"]
    merged.tool_timeout = resolved["tool_timeout"]
    merged.network_policy = resolved["network_policy"]
    merged.scope = resolved["scope"]
    merged.no_scope = not bool(resolved["scope_enabled"])
    merged.urgency = resolved["urgency"]
    merged.no_urgency = not bool(resolved["urgency_enabled"])
    merged.tool_output_chars = resolved["tool_output_chars"]
    merged.verbose = bool(resolved["verbose"])
    merged.dangerous_no_prompt = bool(getattr(args, "dangerous_no_prompt", False))
    merged.prompt_text = str(resolved.get("prompt") or "").strip()
    return merged


def _validate_choice(name: str, value: str | None, choices: tuple[str, ...]) -> None:
    if value is None:
        return
    if value not in choices:
        raise ValueError(f"{name} must be one of: {', '.join(choices)}")


def _safe_split_command(text: str) -> list[str]:
    candidate = str(text or "").strip()
    if not candidate:
        return []
    try:
        return shlex.split(candidate)
    except ValueError:
        return candidate.split()


def _config_path_suggestions(prefix: str) -> list[str]:
    candidates = {"configs/cli.json", "configs/cli.example.json"}
    for path in PROJECT_DIR.glob("configs/*.json"):
        try:
            rel_path = str(path.relative_to(PROJECT_DIR))
        except ValueError:
            rel_path = str(path)
        candidates.add(rel_path)
    if prefix:
        return sorted(path for path in candidates if path.startswith(prefix))
    return sorted(candidates)


def _quote_aware_completion(value: str, token_prefix: str) -> str:
    if " " not in value:
        return value

    prefix = str(token_prefix or "")
    if prefix.startswith('"'):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    if prefix.startswith("'"):
        escaped = value.replace("'", "\\'")
        return f"'{escaped}'"

    return value.replace(" ", "\\ ")


def _filesystem_path_suggestions(prefix: str, *, only_dirs: bool = False) -> list[str]:
    raw_prefix = str(prefix or "")
    normalized_prefix = raw_prefix
    if normalized_prefix.startswith('"') or normalized_prefix.startswith("'"):
        normalized_prefix = normalized_prefix[1:]

    base_dir = PROJECT_DIR
    partial_name = normalized_prefix
    home_dir = Path.home().resolve()
    use_tilde_output = normalized_prefix.startswith("~")

    if normalized_prefix:
        prefix_path = Path(normalized_prefix).expanduser()
        if prefix_path.is_absolute():
            base_dir = prefix_path.parent if str(normalized_prefix).endswith("/") is False else prefix_path
            partial_name = "" if str(normalized_prefix).endswith("/") else prefix_path.name
        else:
            candidate_path = (PROJECT_DIR / prefix_path)
            if str(normalized_prefix).endswith("/"):
                base_dir = candidate_path
                partial_name = ""
            else:
                base_dir = candidate_path.parent
                partial_name = prefix_path.name

    try:
        entries = list(base_dir.iterdir())
    except Exception:
        return []

    suggestions: list[str] = []
    for entry in sorted(entries, key=lambda p: p.name):
        if partial_name and not entry.name.startswith(partial_name):
            continue
        if only_dirs and not entry.is_dir():
            continue

        resolved_entry = entry.resolve()
        if use_tilde_output:
            try:
                rel_home = resolved_entry.relative_to(home_dir)
                display = "~" if str(rel_home) in {"", "."} else f"~/{rel_home}"
            except ValueError:
                display = str(resolved_entry)
        else:
            if resolved_entry.is_relative_to(PROJECT_DIR):
                display = str(resolved_entry.relative_to(PROJECT_DIR))
            else:
                display = str(resolved_entry)

        if entry.is_dir():
            display += "/"
        suggestions.append(_quote_aware_completion(display, raw_prefix))

    return suggestions


def _completion_candidates(
    *,
    buffer: str,
    text: str,
    start_idx: int,
    get_session_ids,
) -> list[str]:
    if not buffer.startswith("/"):
        return []

    prefix_before_cursor = buffer[:start_idx]
    tokens_before = _safe_split_command(prefix_before_cursor)
    if not tokens_before:
        return [cmd for cmd in SLASH_COMMANDS if cmd.startswith(text)]

    cmd = tokens_before[0]
    at_new_token = start_idx > 0 and buffer[start_idx - 1].isspace()
    arg_index = len(tokens_before) if at_new_token else max(len(tokens_before) - 1, 0)
    session_ids = sorted(str(sid) for sid in (get_session_ids() or []) if str(sid).strip())

    if cmd == "/set":
        if arg_index == 1:
            return [key for key in SETTABLE_CONFIG_KEYS if key.startswith(text)]
        if arg_index == 2 and len(tokens_before) >= 2:
            key = tokens_before[1]
            if key == "scope":
                return [v for v in (*SCOPE_CHOICES, "off") if v.startswith(text)]
            if key == "urgency":
                return [v for v in (*URGENCY_CHOICES, "off") if v.startswith(text)]
            if key in {"verbose", "scope_enabled", "urgency_enabled", "ssl_verify"}:
                return [v for v in ("true", "false") if v.startswith(text)]
            if key == "provider":
                return [v for v in ("ollama", "openai", "anthropic", "google") if v.startswith(text)]
            if key == "tools_config":
                preferred = _config_path_suggestions(text)
                fs = _filesystem_path_suggestions(text)
                return sorted(dict.fromkeys(preferred + fs))
            if key == "server_command":
                # Suggest likely executables/paths; user can append arguments after completion.
                preferred_bins = [
                    "venv/bin/python",
                    "venv/bin/python3",
                    "python3",
                    "python",
                ]
                preferred = [value for value in preferred_bins if value.startswith(text)]
                fs = _filesystem_path_suggestions(text)
                suggestions = sorted(dict.fromkeys(preferred + fs))
                return [candidate if candidate.endswith("/") else f"{candidate} " for candidate in suggestions]
        return []

    if cmd == "/scope" and arg_index == 1:
        return [v for v in (*SCOPE_CHOICES, "off") if v.startswith(text)]
    if cmd == "/urgency" and arg_index == 1:
        return [v for v in (*URGENCY_CHOICES, "off") if v.startswith(text)]
    if cmd in {"/enter", "/read", "/close"} and arg_index == 1:
        return [sid for sid in session_ids if sid.startswith(text)]
    if cmd == "/write" and arg_index == 1:
        return [sid for sid in session_ids if sid.startswith(text)]
    if cmd == "/save-config" and arg_index == 1:
        preferred = _config_path_suggestions(text)
        fs = _filesystem_path_suggestions(text)
        return sorted(dict.fromkeys(preferred + fs))

    return []





class SlashCompleter(Completer):
    """prompt_toolkit Completer that delegates to _completion_candidates()."""

    def __init__(self, get_session_ids):
        self.get_session_ids = get_session_ids

    def get_completions(self, document, complete_event):
        buffer = document.text
        cursor = document.cursor_position

        # Find start of the current token by looking for the last space before cursor
        start_idx = buffer.rfind(' ', 0, cursor) + 1
        text = buffer[start_idx:cursor]

        suggestions = _completion_candidates(
            buffer=buffer,
            text=text,
            start_idx=start_idx,
            get_session_ids=self.get_session_ids,
        )
        for s in suggestions:
            yield Completion(s, start_position=-len(text))


def _install_slash_completion(get_session_ids=None) -> None:
    """Legacy stub — tab completion is now handled by prompt_toolkit PromptSession."""
    pass


def _copy_tools_config_if_requested(path_text: str | None) -> list[str] | None:
    if not path_text:
        config_path = PROJECT_DIR / "kali_tools.json"
        if not config_path.exists():
            raise FileNotFoundError(f"Tools config not found: {config_path}")
        return None

    config_path = _resolve_path(path_text)

    if not config_path.exists():
        raise FileNotFoundError(f"Tools config not found: {config_path}")

    with config_path.open() as config_file:
        config = json.load(config_file)

    tool_names = [
        str(tool.get("name", "")).strip()
        for tool in config.get("tools", [])
        if isinstance(tool, dict) and str(tool.get("name", "")).strip()
    ]

    target_path = PROJECT_DIR / "kali_tools.json"
    if config_path.resolve() != target_path.resolve():
        with target_path.open("w") as target_file:
            json.dump(config, target_file, indent=2)
            target_file.write("\n")

    return tool_names or None


def _format_run_path(run_id: str, filename: str = "") -> str:
    path = PROJECT_DIR / "runs" / run_id
    if filename:
        path = path / filename
    return str(path.relative_to(PROJECT_DIR))


class _InputBuffer:
    """Character buffer with tab-completion for slash commands during task execution."""

    COMPLETIONS = ("/cancel", "/force_analyze", "/exit", "/help")

    def __init__(self):
        self.text = ""
        self._in_escape = False

    def add_char(self, ch: str) -> str | None:
        """Process one character.  Returns the submitted line on Enter, else None."""
        # Swallow ANSI escape sequences (arrow keys, etc.)
        if self._in_escape:
            if ch.isalpha() or ch == '~':
                self._in_escape = False
            return None
        if ch == '\033':
            self._in_escape = True
            return None

        if ch in ('\n', '\r'):
            line = self.text
            self.text = ""
            return line
        elif ch in ('\x7f', '\x08'):  # backspace / ctrl-h
            if self.text:
                self.text = self.text[:-1]
            return None
        elif ch == '\x15':  # Ctrl-U  – clear line
            self.text = ""
            return None
        elif ch == '\x17':  # Ctrl-W  – delete last word
            self.text = self.text.rstrip()
            if ' ' in self.text:
                self.text = self.text[:self.text.rfind(' ') + 1]
            else:
                self.text = ""
            return None
        elif ch.isprintable() and ord(ch) >= 32:
            self.text += ch
            return None
        return None

    def tab_complete(self) -> list[str] | None:
        """Try to complete.  Returns a list of matches to display, or None if uniquely completed."""
        if not self.text:
            return list(self.COMPLETIONS)
        matches = [c for c in self.COMPLETIONS if c.startswith(self.text)]
        if len(matches) == 1:
            self.text = matches[0]
            return None  # completed
        elif matches:
            prefix = os.path.commonprefix(matches)
            if len(prefix) > len(self.text):
                self.text = prefix
            return matches
        return None

    def clear(self):
        self.text = ""
        self._in_escape = False


class TerminalEventHandler:
    """Handles agent events and renders them in the terminal.

    When the persistent prompt is activated (during task execution), the
    terminal is split into two regions using ANSI scroll regions:

        ┌─────────────────────────────────────────┐
        │  (output scrolls here)                  │  ← scroll region rows 1..H-3
        │  [tool] bash {"cmd":"..."}              │
        │  [result] ...                           │
        ├─────────────────────────────────────────┤
        │  ⏱ bash 5s │ /cancel  /force_analyze    │  ← status row H-2
        │  ─────────────────────────────────────── │  ← separator row H-1
        │  caf> /canc█                            │  ← input row H (cursor here)
        └─────────────────────────────────────────┘

    During task execution the terminal is placed in cbreak mode (no echo,
    character-at-a-time input) so we can manage cursor position, echo typed
    text at the prompt line, and provide tab-completion for slash commands.

    All output is routed through ``_output()`` which writes inside the
    scroll region and uses save/restore cursor to keep the prompt intact.
    """

    _SEPARATOR_CHAR = "─"
    _RESERVED_LINES = 3  # status + separator + input line

    def __init__(self, *, tool_output_chars: int = 6000, verbose: bool = False, known_session_ids: set[str] | None = None, stream_out=None, stream_in=None):
        import sys
        self.stream_out = stream_out or sys.stdout
        self.stream_in = stream_in or sys.stdin
        self.session: MCPSession | None = None
        self.tool_output_chars = tool_output_chars
        self.verbose = verbose
        self.known_session_ids = known_session_ids
        self._active_tool_name: str | None = None
        self._tool_start_time: float = 0.0
        self._timer_task: asyncio.Task | None = None
        self.prompt_prefix = f"{Colors.ACCENT_PRIMARY}caf>{Colors.RESET} "
        # Persistent prompt state
        self._bar_active = False
        # Character-by-character input buffer (used during task execution)
        self._input_buffer = _InputBuffer()
        self._old_term_settings: list | None = None

    def _is_tty(self) -> bool:
        return hasattr(self.stream_in, "isatty") and self.stream_in.isatty() and hasattr(self.stream_in, "fileno")

    # ── Persistent bottom-bar management ──────────────────────────────

    def _term_size(self) -> tuple[int, int]:
        """Return (lines, columns)."""
        ts = shutil.get_terminal_size()
        return ts.lines, ts.columns

    def activate_bar(self) -> None:
        """Enter split-terminal mode: scroll region on top, fixed bar at bottom."""
        if self._bar_active:
            return
        self._bar_active = True
        self._input_buffer.clear()
        h, w = self._term_size()
        scroll_end = max(h - self._RESERVED_LINES, 1)
        # Set scroll region to top portion
        self.stream_out.write(f"\033[1;{scroll_end}r")
        # Draw the 3 fixed bottom lines
        self._draw_bottom_area()
        # Position cursor at the prompt line for user input
        self.stream_out.write(f"\033[{h};1H")
        self.stream_out.write(self.prompt_prefix)
        self.stream_out.flush()
        # Switch to cbreak mode so we get characters one-at-a-time with no echo
        if _HAS_TERMIOS and self._is_tty():
            try:
                self._old_term_settings = termios.tcgetattr(self.stream_in)
                tty.setcbreak(self.stream_in.fileno())
            except Exception:
                self._old_term_settings = None
        self._ensure_timer_started()

    def deactivate_bar(self) -> None:
        """Exit split-terminal mode and restore normal scrolling."""
        if not self._bar_active:
            return
        self._bar_active = False
        # Restore terminal settings BEFORE any I/O so readline works again.
        # Use TCSAFLUSH to discard any pending cbreak input.
        if self._old_term_settings is not None:
            try:
                termios.tcsetattr(self.stream_in, termios.TCSAFLUSH, self._old_term_settings)
            except Exception:
                pass
            self._old_term_settings = None
        # Safety net: explicitly re-enable canonical mode + echo regardless
        # of whether TCSAFLUSH succeeded. Ensures input() always works.
        if _HAS_TERMIOS and self._is_tty():
            try:
                attrs = termios.tcgetattr(self.stream_in)
                attrs[3] |= termios.ECHO | termios.ICANON
                termios.tcsetattr(self.stream_in, termios.TCSANOW, attrs)
            except Exception:
                pass
        self._input_buffer.clear()
        h, _ = self._term_size()
        scroll_end = max(h - self._RESERVED_LINES, 1)
        # Position cursor at last row of the scroll region BEFORE resetting,
        # so the reset doesn't teleport the cursor to an unexpected position.
        self.stream_out.write(f"\033[{scroll_end};1H")
        # Reset scroll region to full terminal
        self.stream_out.write("\033[r")
        # Ensure cursor is visible
        self.stream_out.write("\033[?25h")
        # Clear everything below the old scroll region (old bar area)
        self.stream_out.write(f"\033[{scroll_end + 1};1H\033[J")
        # Move cursor back to scroll_end and advance with a newline.
        # This ensures the cursor lands right after the last output line,
        # cleanly separated from the old bar area.
        self.stream_out.write(f"\033[{scroll_end};1H\n")
        self.stream_out.flush()
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
            self._timer_task = None

    def _draw_bottom_area(self) -> None:
        """Draw all 3 fixed lines: status (H-2), separator (H-1), prompt (H)."""
        h, w = self._term_size()
        # Row H-2: Tool status
        self.stream_out.write(f"\033[{h - 2};1H\033[K")
        self._write_status_content()
        # Row H-1: Separator
        self.stream_out.write(f"\033[{h - 1};1H\033[K")
        self.stream_out.write(f"{Colors.DIM}{self._SEPARATOR_CHAR * w}{Colors.RESET}")
        # Row H: Prompt
        self.stream_out.write(f"\033[{h};1H\033[K")
        self.stream_out.write(self.prompt_prefix)

    def _write_status_content(self) -> None:
        """Write the status text (no cursor movement, no flush)."""
        if self._active_tool_name:
            elapsed = int(time.monotonic() - self._tool_start_time)
            self.stream_out.write(
                f" {Colors.ACCENT_PRIMARY}\u23f1{Colors.RESET} "
                f"{Colors.TEXT_PRIMARY}{self._active_tool_name}{Colors.RESET} "
                f"{Colors.DIM}{elapsed}s "
                f"\u2502 /cancel  /force_analyze{Colors.RESET}"
            )
        else:
            self.stream_out.write(f" {Colors.DIM}waiting\u2026{Colors.RESET}")

    def _update_status_line(self) -> None:
        """Update just the tool status line (H-2) without touching the prompt."""
        h, _ = self._term_size()
        self.stream_out.write("\033[s")  # save cursor
        self.stream_out.write(f"\033[{h - 2};1H\033[K")
        self._write_status_content()
        self.stream_out.write("\033[u")  # restore cursor
        self.stream_out.flush()

    def _echo_input(self) -> None:
        """Redraw the prompt line with the current input buffer text."""
        if not self._bar_active:
            return
        h, _ = self._term_size()
        buf_text = self._input_buffer.text
        self.stream_out.write(f"\033[{h};1H\033[K")  # move to row H, clear
        self.stream_out.write(f"{self.prompt_prefix}{buf_text}")
        self.stream_out.flush()

    def _redraw_prompt_line(self) -> None:
        """Redraw the prompt line (H), clearing any typed text."""
        if not self._bar_active:
            return
        self._input_buffer.clear()
        self._echo_input()

    def _print(self, *args, **kwargs) -> None:
        """Like print() but routes through stream_out instead of sys.stdout."""
        import io
        buf = io.StringIO()
        kwargs.setdefault("file", buf)
        print(*args, **kwargs)
        self.stream_out.write(buf.getvalue())
        try:
            self.stream_out.flush()
        except Exception:
            pass

    def _print_separator(self) -> None:
        """Print a separator line (used in normal REPL mode between output and prompt)."""
        _, w = self._term_size()
        self._print(f"{Colors.DIM}{self._SEPARATOR_CHAR * w}{Colors.RESET}")

    # ── Output routing ────────────────────────────────────────────────

    def _output(self, text: str) -> None:
        """Print *text* in the scroll region; cursor returns to prompt."""
        if not self._bar_active:
            self._print(text)
            return
        h, _ = self._term_size()
        scroll_end = max(h - self._RESERVED_LINES, 1)
        self.stream_out.write("\033[s")  # save cursor (at prompt line)
        self.stream_out.write(f"\033[{scroll_end};1H")  # move to bottom of scroll region
        for line in text.split("\n"):
            self.stream_out.write(f"\n\033[K{line}")  # newline scrolls, then write
        self.stream_out.write("\033[u")  # restore cursor to prompt
        self.stream_out.flush()

    def _output_err(self, text: str) -> None:
        """Print error text (routes to scroll region when bar active)."""
        self._output(text)

    # ── Timer ─────────────────────────────────────────────────────────

    async def _timer_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(1.0)
                if self._bar_active:
                    self._update_status_line()
                elif self._active_tool_name:
                    elapsed = int(time.monotonic() - self._tool_start_time)
                    self.stream_out.write(f"\r\033[K{self.prompt_prefix}{Colors.DIM}[running {self._active_tool_name} for {elapsed}s...]{Colors.RESET}")
                    self.stream_out.flush()
        except asyncio.CancelledError:
            pass

    def _clear_timer_line(self) -> None:
        if not self._bar_active and self._active_tool_name:
            self.stream_out.write("\r\033[K")
            self.stream_out.flush()

    def _ensure_timer_started(self) -> None:
        if self._timer_task is None or self._timer_task.done():
            try:
                asyncio.get_running_loop()
                self._timer_task = asyncio.create_task(self._timer_loop())
            except RuntimeError:
                pass

    def bind(self, session: MCPSession) -> None:
        self.session = session

    # ── Event dispatch ────────────────────────────────────────────────

    def __call__(self, event: dict[str, Any]) -> None:
        self._clear_timer_line()
        self._ensure_timer_started()

        event_type = str(event.get("type") or "")

        if event_type == "tool_call":
            self._active_tool_name = str(event.get("tool") or "tool")
            self._tool_start_time = time.monotonic()
        elif event_type in {"tool_result", "error", "chat_done"}:
            self._active_tool_name = None

        if event_type == "status":
            self._print_status(str(event.get("message") or ""))
        elif event_type == "service_started":
            tools = event.get("tools") or []
            run_id = event.get("run_id") or "unknown"
            self._output(f"\n{Colors.ACCENT_SUCCESS}[started]{Colors.RESET} run_id={Colors.TEXT_PRIMARY}{run_id}{Colors.RESET} tools={Colors.TEXT_PRIMARY}{len(tools)}{Colors.RESET}")
        elif event_type == "service_stopped":
            self._output(f"\n{Colors.ACCENT_WARNING}[stopped]{Colors.RESET} Session stopped.")
        elif event_type == "response":
            text = str(event.get("text") or "").strip()
            if text:
                self._output(f"\n{Colors.ACCENT_PRIMARY}Assistant:{Colors.RESET}\n{text}\n")
        elif event_type == "tool_call":
            tool = event.get("tool") or "tool"
            args = _compact_json(event.get("args") or {})
            self._output(f"\n{Colors.ACCENT_PRIMARY}[tool]{Colors.RESET} {Colors.TEXT_PRIMARY}{tool}{Colors.RESET} {Colors.TEXT_SECONDARY}{args}{Colors.RESET}")
        elif event_type == "tool_result":
            self._print_tool_result(event)
        elif event_type == "error":
            self._output_err(f"\n{Colors.ACCENT_ERROR}[error] {event.get('message') or 'Unknown error.'}{Colors.RESET}")
        elif event_type == "context_usage":
            if self.verbose:
                used = event.get("used", "?")
                budget = event.get("budget", "?")
                model_max = event.get("model_max", "?")
                self._output(f"{Colors.TEXT_SECONDARY}[context] used={used} budget={budget} model_max={model_max}{Colors.RESET}")
        elif event_type == "post_tool_reply_decision":
            self._resolve_post_tool_reply(event)
        elif event_type == "dangerous_tool_approval":
            self._resolve_dangerous_tool(event)
        elif event_type == "tool_timeout_decision":
            self._resolve_tool_timeout(event)
        elif event_type == "chat_done":
            self._output(f"{Colors.ACCENT_SUCCESS}[done]{Colors.RESET} {Colors.BOLD}{event.get('message') or 'Ready for next prompt.'}{Colors.RESET}")
        elif event_type == "isess_created":
            session_id = event.get("session_id") or "unknown"
            session_kind = event.get("session_kind") or "interactive"
            if self.known_session_ids is not None and str(session_id).strip():
                self.known_session_ids.add(str(session_id).strip())
            self._output(f"{Colors.ACCENT_PRIMARY}[interactive]{Colors.RESET} Preserved {session_kind} session {Colors.TEXT_PRIMARY}{session_id}{Colors.RESET}.")
        elif event_type == "isess_output":
            session_id = event.get("session_id") or "unknown"
            output = str(event.get("output") or "")
            self._output(f"\n{Colors.ACCENT_PRIMARY}[interactive:{Colors.TEXT_PRIMARY}{session_id}{Colors.ACCENT_PRIMARY}]{Colors.RESET}\n{output}")
        elif event_type == "isess_closed":
            session_id = event.get("session_id") or "unknown"
            if self.known_session_ids is not None and str(session_id).strip():
                self.known_session_ids.discard(str(session_id).strip())
            self._output(f"{Colors.ACCENT_PRIMARY}[interactive]{Colors.RESET} Session {Colors.TEXT_PRIMARY}{session_id}{Colors.RESET} closed.")

        # When bar is active, update the status line immediately.
        # When bar is NOT active, draw an inline status after output.
        if self._bar_active:
            self._update_status_line()
        elif self._active_tool_name:
            elapsed = int(time.monotonic() - self._tool_start_time)
            self.stream_out.write(f"\r\033[K{self.prompt_prefix}{Colors.DIM}[running {self._active_tool_name} for {elapsed}s...]{Colors.RESET}")
            self.stream_out.flush()

    def _print_status(self, message: str) -> None:
        if message:
            self._output(f"{Colors.TEXT_SECONDARY}[status]{Colors.RESET} {message}")

    def _print_tool_result(self, event: dict[str, Any]) -> None:
        tool = event.get("tool") or "tool"
        exit_code = event.get("exit_code", "?")
        duration_ms = event.get("duration_ms", "?")
        result = _truncate(str(event.get("result") or ""), self.tool_output_chars)
        exit_color = Colors.ACCENT_SUCCESS if exit_code == 0 else Colors.ACCENT_ERROR
        self._output(f"{Colors.ACCENT_PRIMARY}[result]{Colors.RESET} {Colors.TEXT_PRIMARY}{tool}{Colors.RESET} exit={exit_color}{exit_code}{Colors.RESET} duration_ms={Colors.TEXT_PRIMARY}{duration_ms}{Colors.RESET}")
        if result.strip():
            self._output(f"{Colors.TEXT_SECONDARY}{result}{Colors.RESET}")

    def _prompt_choice(self, question: str, options: tuple[str, ...], default: str) -> str:
        if not self._is_tty():
            self._print(f"{Colors.TEXT_SECONDARY}[decision]{Colors.RESET} Non-interactive input; choosing {default}.")
            return default

        # Temporarily deactivate the bar so input() works normally
        was_active = self._bar_active
        if was_active:
            self.deactivate_bar()

        option_text = "/".join(options)
        try:
            while True:
                answer = input(f"{Colors.TEXT_PRIMARY}{question}{Colors.RESET} ({Colors.ACCENT_PRIMARY}{option_text}{Colors.RESET}) [{Colors.ACCENT_SUCCESS}{default}{Colors.RESET}]: ").strip().lower()
                if not answer:
                    return default
                matches = [option for option in options if option.startswith(answer)]
                if len(matches) == 1:
                    return matches[0]
                print(f"Please choose one of: {', '.join(options)}")
        finally:
            if was_active:
                self.activate_bar()

    def _resolve_post_tool_reply(self, event: dict[str, Any]) -> None:
        self._output(f"\n{Colors.ACCENT_WARNING}[decision]{Colors.RESET} {event.get('message') or 'Retry the final answer or cancel?'}")
        action = self._prompt_choice("Decision", ("retry", "cancel"), "cancel")
        if self.session and not self.session.resolve_post_tool_reply_decision(action):
            self._output_err(f"{Colors.ACCENT_WARNING}[decision]{Colors.RESET} Could not apply post-tool reply decision.")

    def _resolve_dangerous_tool(self, event: dict[str, Any]) -> None:
        tool = event.get("tool") or "shell_dangerous"
        command = str(event.get("command") or "")
        self._output(f"\n{Colors.ACCENT_ERROR}[approval]{Colors.RESET} {event.get('message') or 'Approval required.'}")
        self._output(f"Tool: {tool}")
        if command:
            self._output(f"Command: {command}")
        action = self._prompt_choice("Approve execution", ("approve", "cancel"), "cancel")
        if self.session and not self.session.resolve_dangerous_tool_approval(action):
            self._output_err(f"{Colors.ACCENT_ERROR}[approval]{Colors.RESET} Could not apply dangerous-tool decision.")

    def _resolve_tool_timeout(self, event: dict[str, Any]) -> None:
        self._output(f"\n{Colors.ACCENT_WARNING}[timeout]{Colors.RESET} {event.get('message') or 'Tool reached a timeout checkpoint.'}")
        command = str(event.get("command") or "")
        if command:
            self._output(f"Command: {command}")
        action = self._prompt_choice("Timeout action", ("wait", "background", "kill"), "wait")
        wait_seconds = None
        if action == "wait":
            wait_seconds = self._prompt_wait_seconds(default=60)
        if self.session and not self.session.resolve_tool_timeout_decision(action, wait_seconds=wait_seconds):
            self._output_err(f"{Colors.ACCENT_WARNING}[timeout]{Colors.RESET} Could not apply timeout decision.")

    def _prompt_wait_seconds(self, default: int) -> int:
        if not self._is_tty():
            self._print(f"{Colors.TEXT_SECONDARY}[decision]{Colors.RESET} Non-interactive input; skipping prompt.")
            return default
        was_active = self._bar_active
        if was_active:
            self.deactivate_bar()
        allowed_text = ", ".join(str(value) for value in TIMEOUT_WAIT_CHOICES)
        try:
            while True:
                answer = input(f"Ask again after seconds ({allowed_text}) [{default}]: ").strip()
                if not answer:
                    return default
                try:
                    wait_seconds = int(answer)
                except ValueError:
                    print("Enter a number from the allowed list.")
                    continue
                if wait_seconds in TIMEOUT_WAIT_CHOICES:
                    return wait_seconds
                print(f"Choose one of: {allowed_text}")
        finally:
            if was_active:
                self.activate_bar()


def _add_session_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="Path to a JSON session config file (default: configs/cli.json, required). CLI flags override config values. See docs/configuration.md for details.")
    parser.add_argument("--provider", help="LLM provider: ollama_direct, litellm, openai, or claude.")
    parser.add_argument("--url", help="LLM provider base URL.")
    parser.add_argument("--model", help="Model name. Can also be set with MCP_MODEL or in config.")
    parser.add_argument("--api-key", help="Optional API key. Prefer MCP_API_KEY for shell history safety.")
    parser.add_argument("--no-ssl-verify", action="store_true", help="Disable TLS verification for proxied HTTPS providers.")
    parser.add_argument("--server-command", help="Command used to launch the MCP server.")
    parser.add_argument("--tools-config", help="Path to a kali_tools.json-compatible file. Defaults to ./kali_tools.json.")
    parser.add_argument("--continue", dest="continue_run", type=str, metavar="RUN_ID_OR_INDEX",
                        help="Restore a previous interaction by run ID or index (view the 'Idx' column via 'cli.py list-runs').")
    parser.add_argument("--context-window", type=int, help="LLM context window budget in tokens.")
    parser.add_argument("--max-turns", type=int, help="Maximum LLM/tool iterations per prompt.")
    parser.add_argument("--tool-timeout", type=int, help="Default timeout for tool executions in seconds.")
    parser.add_argument("--allow", action="append", help="Allowed target entry. Repeat or comma-separate values. Default: *")
    parser.add_argument("--disallow", action="append", help="Disallowed target entry. Repeat or comma-separate values.")
    parser.add_argument("--scope", choices=SCOPE_CHOICES, help="Per-prompt scope control.")
    parser.add_argument("--no-scope", action="store_true", help="Do not inject scope guidance.")
    parser.add_argument("--urgency", choices=URGENCY_CHOICES, help="Per-prompt urgency control.")
    parser.add_argument("--no-urgency", action="store_true", help="Do not inject urgency guidance.")
    parser.add_argument("--tool-output-chars", type=int, help="Maximum tool output chars printed to terminal; full output is logged.")
    parser.add_argument("--verbose", action="store_true", help="Print context usage events.")
    parser.add_argument("--dangerous-no-prompt", action="store_true", default=False,
                        help="Auto-approve dangerous commands without prompting the user. Use with caution.")


def _create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Terminal interface for CyberAgentFlow. Use --config to load settings from a JSON file (required: configs/cli.json or custom path).")
    subparsers = parser.add_subparsers(dest="command", required=True)

    chat_parser = subparsers.add_parser("chat", help="Start an interactive terminal chat session.")
    _add_session_args(chat_parser)

    run_parser = subparsers.add_parser("run", help="Run one prompt, then stop the session.")
    _add_session_args(run_parser)
    run_parser.add_argument("prompt", nargs="*", help="Prompt to send to the agent. Use -- before the prompt if it contains dashes.")

    list_parser = subparsers.add_parser("list-runs", help="List saved run metadata.")
    list_parser.add_argument("--limit", type=int, default=20, help="Maximum number of runs to show.")

    return parser


def _validate_session_args(args: argparse.Namespace) -> None:
    if not args.model:
        raise ValueError("A model is required. Pass --model or set MCP_MODEL.")
    _validate_choice("scope", None if args.no_scope else args.scope, SCOPE_CHOICES)
    _validate_choice("urgency", None if args.no_urgency else args.urgency, URGENCY_CHOICES)
    if args.max_turns < 1 or args.max_turns > 100:
        raise ValueError("--max-turns must be between 1 and 100.")
    if args.context_window < 1024:
        raise ValueError("--context-window must be at least 1024.")
    if args.tool_timeout < 1 or args.tool_timeout > 3600:
        raise ValueError("--tool-timeout must be between 1 and 3600.")


def _effective_scope(args: argparse.Namespace) -> str | None:
    return None if args.no_scope else args.scope


def _effective_urgency(args: argparse.Namespace) -> str | None:
    return None if args.no_urgency else args.urgency


async def _start_session(args: argparse.Namespace, event_handler: TerminalEventHandler) -> MCPSession:
    _validate_session_args(args)
    enabled_tool_guides = _copy_tools_config_if_requested(args.tools_config)
    server_type = "apt" if "/usr/share/mcp-kali-server/mcp_server.py" in args.server_command else "cli"
    
    run_id = None
    if getattr(args, "continue_run", None) is not None:
        sessions = load_session_list(str(PROJECT_DIR))
        target = args.continue_run
        if target.isdigit():
            idx = int(target)
            if idx < len(sessions):
                run_id = sessions[idx].get("run_id")
            else:
                print(f"Run index {idx} out of range. Found {len(sessions)} runs.")
                sys.exit(1)
        else:
            matches = [s.get("run_id") for s in sessions if s.get("run_id", "").startswith(target)]
            if matches:
                run_id = matches[0]
            else:
                print(f"Run '{target}' not found.")
                sys.exit(1)
        print(f"Restoring interaction from run_id: {run_id}")

    if not run_id:
        run_id = make_run_id(server_type)

    auto_approve = bool(getattr(args, "dangerous_no_prompt", False))
    if auto_approve:
        print(f"{Colors.ACCENT_ERROR}[WARNING]{Colors.RESET} {Colors.BOLD}--dangerous-no-prompt is active.{Colors.RESET} "
              f"Dangerous commands will be executed {Colors.ACCENT_ERROR}without user confirmation{Colors.RESET}.")
    session = MCPSession(
        ollama_url=args.url,
        llm_provider=args.provider,
        api_key=args.api_key or None,
        ssl_verify=not args.no_ssl_verify,
        model=args.model,
        server_command=args.server_command,
        run_id=run_id,
        event_callback=event_handler,
        context_window=args.context_window,
        max_turns=args.max_turns,
        tool_timeout=args.tool_timeout,
        network_policy=args.network_policy,
        enabled_tool_guides=enabled_tool_guides,
        auto_approve_dangerous=auto_approve,
    )
    event_handler.bind(session)
    await session.start()
    return session


async def _run_chat_with_bar(
    session: MCPSession,
    prompt: str,
    event_handler: TerminalEventHandler,
    *,
    cancel_event: asyncio.Event | None = None,
    scope: str | None = None,
    urgency: str | None = None,
) -> str | None:
    """Run a single chat turn with full bar UI, signal handling, and stdin reader.

    Returns a ``next_prompt_override`` string if the user triggered
    ``/force_analyze``, otherwise ``None``.
    """
    if cancel_event is None:
        cancel_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    next_prompt_override: str | None = None
    _cancel_fired = False

    chat_task = asyncio.create_task(
        session.chat(prompt, cancel_event=cancel_event, scope=scope, urgency=urgency)
    )

    # Mutable cells so the stdin handler can be re-targeted to a follow-up
    # task without needing a separate handler function.
    _task_ref: list[asyncio.Task] = [chat_task]
    _event_ref: list[asyncio.Event] = [cancel_event]
    _exit_fired = False

    def _sigint_handler():
        nonlocal _cancel_fired
        if _cancel_fired:
            event_handler._output(f"{Colors.DIM}[status] Already cancelling, please wait...{Colors.RESET}")
            return
        _cancel_fired = True
        event_handler._output(f"{Colors.ACCENT_WARNING}[status] Interrupt received, cancelling...{Colors.RESET}")
        _event_ref[0].set()
        _task_ref[0].cancel()

    def _handle_char(ch: str):
        nonlocal next_prompt_override, _cancel_fired, _exit_fired
        if ch == '\t':
            matches = event_handler._input_buffer.tab_complete()
            event_handler._echo_input()
            if matches:
                event_handler._output(f"{Colors.DIM}  {' '.join(matches)}{Colors.RESET}")
            return
        line = event_handler._input_buffer.add_char(ch)
        event_handler._echo_input()
        if line is None:
            return
        cmd = line.strip().lower()
        if not cmd:
            return
        if cmd in {"/force_analyze", "/cancel", "/exit"}:
            if _cancel_fired:
                event_handler._output(f"{Colors.DIM}[status] Already cancelling, please wait...{Colors.RESET}")
                return
            _cancel_fired = True
            event_handler._output(f"{Colors.ACCENT_WARNING}[status] {cmd} received, cancelling...{Colors.RESET}")
            if cmd == "/force_analyze":
                tool = event_handler._active_tool_name or "tool"
                next_prompt_override = (
                    f"The user chose Stop And Analyze for the just-stopped tool {tool}.\n"
                    "Analyze the partial output from the stopped tool in the immediately preceding tool results and conversation context. "
                    "Summarize what completed, what remains incomplete, any findings or blockers, and the best next step. "
                    "Do not rerun the stopped tool unless the user explicitly asks."
                )
            elif cmd == "/exit":
                _exit_fired = True
            _event_ref[0].set()
            _task_ref[0].cancel()

    async def _async_ssh_reader():
        while True:
            try:
                ch = await event_handler.stream_in.read(1)
                if not ch:
                    break
                _handle_char(ch)
            except Exception:
                break

    def _sync_stdin_handler():
        ch = event_handler.stream_in.read(1)
        if ch:
            _handle_char(ch)

    event_handler.activate_bar()
    
    # Add signal handler safely (only works on main thread/local)
    try:
        loop.add_signal_handler(signal.SIGINT, _sigint_handler)
    except NotImplementedError:
        pass  # Windows or not main thread

    is_async_stream = hasattr(event_handler.stream_in, "readexactly") or __import__("asyncio").iscoroutinefunction(getattr(event_handler.stream_in, "read", None))
    reader_task = None
    if is_async_stream:
        reader_task = asyncio.create_task(_async_ssh_reader())
    else:
        loop.add_reader(event_handler.stream_in, _sync_stdin_handler)

    try:
        await chat_task
    except asyncio.CancelledError:
        pass
    except Exception:
        pass

    if reader_task:
        reader_task.cancel()
        try:
            await reader_task
        except BaseException:
            pass
    elif not is_async_stream:
        try:
            loop.remove_reader(event_handler.stream_in)
        except Exception:
            pass

    if next_prompt_override:
        event_handler._output(
            f"{Colors.DIM}[status] Cleaning up cancelled task, then analysing...{Colors.RESET}"
        )
        _cancel_fired = False
        next_prompt_override_2 = next_prompt_override
        next_prompt_override = None
        cancel_event_2 = asyncio.Event()
        chat_task_2 = asyncio.create_task(
            session.chat(next_prompt_override_2, cancel_event_2,
                         scope=scope, urgency=urgency)
        )
        _task_ref[0] = chat_task_2
        _event_ref[0] = cancel_event_2
        event_handler._input_buffer.clear()
        event_handler._echo_input()

        # Restart reader so user can cancel the analysis too
        reader_task_2 = None
        if is_async_stream:
            reader_task_2 = asyncio.create_task(_async_ssh_reader())
        else:
            loop.add_reader(event_handler.stream_in, _sync_stdin_handler)

        try:
            await chat_task_2
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

        if reader_task_2:
            reader_task_2.cancel()
            try:
                await reader_task_2
            except BaseException:
                pass
        elif not is_async_stream:
            try:
                loop.remove_reader(event_handler.stream_in)
            except Exception:
                pass

    # ── Tear down ──────────────────────────────────────────────────────
    try:
        loop.remove_signal_handler(signal.SIGINT)
    except Exception:
        pass
    event_handler.deactivate_bar()

    if _exit_fired:
        raise EOFError("User exited during running task")

    return next_prompt_override


async def _run_prompt(args: argparse.Namespace, event_handler: TerminalEventHandler = None, session: MCPSession = None) -> int:
    if event_handler is None:
        event_handler = TerminalEventHandler(tool_output_chars=args.tool_output_chars, verbose=args.verbose)
    prompt = args.prompt_text
    if not prompt:
        raise ValueError("A prompt is required for the run command.")
    
    _owns_session = (session is None)
    try:
        if session is None:
            session = await _start_session(args, event_handler)

        await _run_chat_with_bar(
            session, prompt, event_handler,
            scope=_effective_scope(args), urgency=_effective_urgency(args),
        )

        event_handler._print(f"[run] Transcript: {_format_run_path(session.run_id, 'transcript.md')}")
        return 0
    finally:
        if _owns_session and session:
            await session.stop()


async def _chat(args: argparse.Namespace, event_handler: TerminalEventHandler = None, session: MCPSession = None) -> int:
    known_session_ids: set[str] = set()
    if event_handler is None:
        event_handler = TerminalEventHandler(
            tool_output_chars=args.tool_output_chars,
            verbose=args.verbose,
            known_session_ids=known_session_ids,
        )
    else:
        event_handler.known_session_ids = known_session_ids
    _owns_session = session is None
    session_ref: MCPSession | None = session
    current_scope = _effective_scope(args)
    current_urgency = _effective_urgency(args)
    active_session_id: str | None = None
    session_config: dict[str, Any] = {
        "provider": args.provider,
        "url": args.url,
        "model": args.model,
        "api_key": args.api_key or "",
        "ssl_verify": not args.no_ssl_verify,
        "server_command": args.server_command,
        "tools_config": args.tools_config,
        "context_window": args.context_window,
        "max_turns": args.max_turns,
        "tool_timeout": args.tool_timeout,
        "network_policy": {
            "allow": list((args.network_policy or {}).get("allow", ["*"])),
            "disallow": list((args.network_policy or {}).get("disallow", [])),
        },
        "scope": args.scope,
        "scope_enabled": not args.no_scope,
        "urgency": args.urgency,
        "urgency_enabled": not args.no_urgency,
        "tool_output_chars": args.tool_output_chars,
        "verbose": bool(args.verbose),
    }
    config_target_path = args.config or str(DEFAULT_CONFIG_PATH)
    next_session_refresh_at = 0.0
    session_refresh_interval_seconds = 2.5
    try:
        if _owns_session:
            session_ref = await _start_session(args, event_handler)
        session = session_ref
        _install_slash_completion(get_session_ids=lambda: sorted(known_session_ids))
        event_handler._print("Type /help for CLI commands, /exit to stop.")
        while True:
            now = time.monotonic()
            if now >= next_session_refresh_at:
                # Fire refresh in background so the prompt appears immediately
                asyncio.create_task(_refresh_known_session_ids(session, known_session_ids))
                next_session_refresh_at = now + session_refresh_interval_seconds

            try:
                prompt_str = f"{Colors.ACCENT_PRIMARY}caf[{active_session_id}]>{Colors.RESET} " if active_session_id else f"{Colors.ACCENT_PRIMARY}caf>{Colors.RESET} "
                event_handler.prompt_prefix = prompt_str
                
                # Safety net: ensure terminal is in canonical (cooked) mode
                if _HAS_TERMIOS and event_handler._is_tty():
                    try:
                        _attrs = termios.tcgetattr(event_handler.stream_in)
                        _attrs[3] |= termios.ECHO | termios.ICANON
                        termios.tcsetattr(event_handler.stream_in, termios.TCSANOW, _attrs)
                    except Exception:
                        pass
                event_handler._print_separator()
                
                if not hasattr(event_handler, "prompt_session"):
                    # Create the PromptSession once per event_handler
                    event_handler.prompt_session = PromptSession(
                        completer=SlashCompleter(lambda: sorted(known_session_ids)),
                        # output will automatically be correctly routed by prompt_toolkit 
                        # in both local and SSH mode (when using PromptToolkitSSHSession)
                    )
                
                line = await event_handler.prompt_session.prompt_async(ANSI(prompt_str))
                prompt = line.strip() if line else ""
            except EOFError:
                event_handler._print()
                break
            except KeyboardInterrupt:
                event_handler._print("\nUse /exit to stop the session cleanly.")
                continue

            if not prompt:
                continue
            if prompt.startswith("/"):
                should_continue, current_scope, current_urgency, active_session_id = await _handle_repl_command(
                    prompt,
                    session,
                    current_scope,
                    current_urgency,
                    active_session_id,
                    event_handler,
                    session_config,
                    config_target_path,
                    known_session_ids,
                )
                if not should_continue:
                    break
                continue

            if active_session_id:
                result = await session.call_tool_direct(
                    "interactive_session_write",
                    {"session_id": active_session_id, "input": prompt},
                )
                event_handler._print(str(result.get("content") or result.get("error") or result))
            else:
                override = await _run_chat_with_bar(
                    session, prompt, event_handler,
                    scope=current_scope, urgency=current_urgency,
                )
                # Note: force_analyze follow-up is now handled INSIDE
                # _run_chat_with_bar, so override is always None here.
        event_handler._print(f"[chat] Transcript: {_format_run_path(session.run_id, 'transcript.md')}")
        return 0
    finally:
        if _owns_session and session:
            await session.stop()


async def _handle_repl_command(
    command_text: str,
    session: MCPSession,
    current_scope: str | None,
    current_urgency: str | None,
    active_session_id: str | None,
    event_handler: TerminalEventHandler,
    session_config: dict[str, Any],
    config_target_path: str,
    known_session_ids: set[str],
) -> tuple[bool, str | None, str | None, str | None]:
    parts = shlex.split(command_text)
    command = parts[0].lower()

    if command in {"/exit", "/quit"}:
        return False, current_scope, current_urgency, active_session_id
    if command == "/help":
        event_handler._print(
            f"{Colors.BOLD}Commands:{Colors.RESET}\n"
            f"  {Colors.ACCENT_PRIMARY}/help{Colors.RESET}                       Show this help.\n"
            f"  {Colors.ACCENT_PRIMARY}/exit{Colors.RESET}                       Stop the session.\n"
            f"  {Colors.ACCENT_PRIMARY}/cancel{Colors.RESET}                     Cancel active background task immediately.\n"
            f"  {Colors.ACCENT_PRIMARY}/force_analyze{Colors.RESET}               Cancel active background task and queue an analysis prompt.\n"
            f"  {Colors.ACCENT_PRIMARY}/enter SESSION_ID{Colors.RESET}           Enter interactive session mode (like a tab).\n"
            f"  {Colors.ACCENT_PRIMARY}/back{Colors.RESET}                       Return to main chat mode.\n"
            f"  {Colors.ACCENT_PRIMARY}/where{Colors.RESET}                      Show current mode and selected session.\n"
            f"  {Colors.ACCENT_PRIMARY}/config{Colors.RESET}                     Show current config values.\n"
            f"  {Colors.ACCENT_PRIMARY}/set KEY VALUE{Colors.RESET}              Update settings from chat.\n"
            f"  {Colors.ACCENT_PRIMARY}/save-config [PATH]{Colors.RESET}         Save current settings to JSON config file.\n"
            f"  {Colors.ACCENT_PRIMARY}/tools{Colors.RESET}                      List available MCP tools.\n"
            f"  {Colors.ACCENT_PRIMARY}/scope VALUE|off{Colors.RESET}            Set scope for later prompts.\n"
            f"  {Colors.ACCENT_PRIMARY}/urgency VALUE|off{Colors.RESET}          Set urgency for later prompts.\n"
            f"  {Colors.ACCENT_PRIMARY}/sessions{Colors.RESET}                   List preserved interactive sessions.\n"
            f"  {Colors.ACCENT_PRIMARY}/refresh-sessions{Colors.RESET}           Refresh session IDs from backend for autocomplete.\n"
            f"  {Colors.ACCENT_PRIMARY}/read [SESSION_ID]{Colors.RESET}          Read output (defaults to entered session).\n"
            f"  {Colors.ACCENT_PRIMARY}/write ...{Colors.RESET}                  Send text: /write ID TEXT or /write TEXT in entered mode.\n"
            f"  {Colors.ACCENT_PRIMARY}/close [SESSION_ID]{Colors.RESET}         Close session (defaults to entered session).\n"
            f"\n"
            f"{Colors.TEXT_SECONDARY}When entered into a session via /enter, plain text is sent directly to that session.{Colors.RESET}"
        )
        return True, current_scope, current_urgency, active_session_id
    if command == "/config":
        event_handler._print(json.dumps(session_config, indent=2, ensure_ascii=True))
        return True, current_scope, current_urgency, active_session_id
    if command == "/set":
        if len(parts) == 1:
            event_handler._print(f"Possible keys: {', '.join(SETTABLE_CONFIG_KEYS)}")
            return True, current_scope, current_urgency, active_session_id
        if len(parts) == 2:
            key = parts[1].strip().lower()
            if key == "scope":
                event_handler._print(f"Possible values for {key}: {', '.join(SCOPE_CHOICES)}, off")
            elif key == "urgency":
                event_handler._print(f"Possible values for {key}: {', '.join(URGENCY_CHOICES)}, off")
            elif key in {"verbose", "scope_enabled", "urgency_enabled", "ssl_verify"}:
                event_handler._print(f"Possible values for {key}: true, false")
            elif key == "provider":
                event_handler._print(f"Possible values for {key}: ollama, openai, anthropic, google")
            else:
                event_handler._print(f"Usage: /set {key} <value>")
            return True, current_scope, current_urgency, active_session_id

        key = parts[1].strip().lower()
        raw_value = " ".join(parts[2:]).strip()

        if key == "scope":
            value = raw_value.lower()
            if value == "off":
                session_config["scope_enabled"] = False
                current_scope = None
                event_handler._print("Scope disabled for this chat session.")
                return True, current_scope, current_urgency, active_session_id
            if value not in SCOPE_CHOICES:
                event_handler._print("scope must be one of: " + ", ".join(SCOPE_CHOICES) + " or off")
                return True, current_scope, current_urgency, active_session_id
            session_config["scope"] = value
            session_config["scope_enabled"] = True
            current_scope = value
            event_handler._print(f"Scope set to {value}.")
            return True, current_scope, current_urgency, active_session_id

        if key == "urgency":
            value = raw_value.lower()
            if value == "off":
                session_config["urgency_enabled"] = False
                current_urgency = None
                event_handler._print("Urgency disabled for this chat session.")
                return True, current_scope, current_urgency, active_session_id
            if value not in URGENCY_CHOICES:
                event_handler._print("urgency must be one of: " + ", ".join(URGENCY_CHOICES) + " or off")
                return True, current_scope, current_urgency, active_session_id
            session_config["urgency"] = value
            session_config["urgency_enabled"] = True
            current_urgency = value
            event_handler._print(f"Urgency set to {value}.")
            return True, current_scope, current_urgency, active_session_id

        if key == "scope_enabled":
            try:
                enabled = _to_bool(raw_value)
            except ValueError as exc:
                event_handler._print(str(exc))
                return True, current_scope, current_urgency, active_session_id
            session_config["scope_enabled"] = enabled
            current_scope = session_config.get("scope") if enabled else None
            event_handler._print(f"scope_enabled set to {enabled}.")
            return True, current_scope, current_urgency, active_session_id

        if key == "urgency_enabled":
            try:
                enabled = _to_bool(raw_value)
            except ValueError as exc:
                event_handler._print(str(exc))
                return True, current_scope, current_urgency, active_session_id
            session_config["urgency_enabled"] = enabled
            current_urgency = session_config.get("urgency") if enabled else None
            event_handler._print(f"urgency_enabled set to {enabled}.")
            return True, current_scope, current_urgency, active_session_id

        if key == "verbose":
            try:
                enabled = _to_bool(raw_value)
            except ValueError as exc:
                event_handler._print(str(exc))
                return True, current_scope, current_urgency, active_session_id
            session_config["verbose"] = enabled
            event_handler.verbose = enabled
            event_handler._print(f"verbose set to {enabled}.")
            return True, current_scope, current_urgency, active_session_id

        if key == "tool_output_chars":
            try:
                chars = int(raw_value)
            except ValueError:
                event_handler._print("tool_output_chars must be an integer")
                return True, current_scope, current_urgency, active_session_id
            if chars < 0:
                event_handler._print("tool_output_chars must be >= 0")
                return True, current_scope, current_urgency, active_session_id
            session_config["tool_output_chars"] = chars
            event_handler.tool_output_chars = chars
            event_handler._print(f"tool_output_chars set to {chars}.")
            return True, current_scope, current_urgency, active_session_id

        if key in {
            "provider", "url", "model", "api_key", "ssl_verify",
            "server_command", "tools_config", "context_window", "max_turns", "tool_timeout",
            "allow", "disallow",
        }:
            restart_required_message = "Saved in config state. Restart the chat session for this to take effect."
            if key == "ssl_verify":
                try:
                    session_config["ssl_verify"] = _to_bool(raw_value)
                except ValueError as exc:
                    event_handler._print(str(exc))
                    return True, current_scope, current_urgency, active_session_id
            elif key in {"context_window", "max_turns", "tool_timeout"}:
                try:
                    session_config[key] = int(raw_value)
                except ValueError:
                    event_handler._print(f"{key} must be an integer")
                    return True, current_scope, current_urgency, active_session_id
            elif key in {"allow", "disallow"}:
                values = _split_entries([raw_value], ["*"] if key == "allow" else [])
                session_config["network_policy"][key] = values
            else:
                session_config[key] = raw_value
            event_handler._print(restart_required_message)
            return True, current_scope, current_urgency, active_session_id

        event_handler._print("Unsupported key. Try /config to inspect available settings.")
        return True, current_scope, current_urgency, active_session_id
    if command == "/save-config":
        target_path = _resolve_path(parts[1]) if len(parts) > 1 else _resolve_path(config_target_path)
        os.makedirs(target_path.parent, exist_ok=True)
        with target_path.open("w") as config_file:
            json.dump(session_config, config_file, indent=2)
            config_file.write("\n")
        event_handler._print(f"Saved config to {target_path}")
        return True, current_scope, current_urgency, active_session_id
    if command in {"/back", "/main"}:
        if active_session_id:
            event_handler._print(f"Returned to main chat mode from {active_session_id}.")
        else:
            event_handler._print("Already in main chat mode.")
        return True, current_scope, current_urgency, None
    if command == "/where":
        if active_session_id:
            event_handler._print(f"Mode: interactive session ({active_session_id})")
        else:
            event_handler._print("Mode: main chat")
        return True, current_scope, current_urgency, active_session_id
    if command == "/enter":
        if len(parts) != 2:
            event_handler._print("Usage: /enter SESSION_ID")
            return True, current_scope, current_urgency, active_session_id
        selected = parts[1]
        known_session_ids.add(selected)
        event_handler._print(f"Entered interactive session mode: {selected}")
        return True, current_scope, current_urgency, selected
    if command == "/tools":
        event_handler._print("Available tools: " + ", ".join(session.tool_names))
        return True, current_scope, current_urgency, active_session_id
    if command == "/scope":
        if len(parts) != 2 or (parts[1] != "off" and parts[1] not in SCOPE_CHOICES):
            event_handler._print("Usage: /scope broad|medium-broad|medium|medium-narrow|narrow|off")
            return True, current_scope, current_urgency, active_session_id
        if parts[1] == "off":
            current_scope = None
            session_config["scope_enabled"] = False
        else:
            current_scope = parts[1]
            session_config["scope"] = parts[1]
            session_config["scope_enabled"] = True
        event_handler._print(f"Scope set to {current_scope or 'off'}.")
        return True, current_scope, current_urgency, active_session_id
    if command == "/urgency":
        if len(parts) != 2 or (parts[1] != "off" and parts[1] not in URGENCY_CHOICES):
            event_handler._print("Usage: /urgency stealthy|methodical|balanced|fast|speed|off")
            return True, current_scope, current_urgency, active_session_id
        if parts[1] == "off":
            current_urgency = None
            session_config["urgency_enabled"] = False
        else:
            current_urgency = parts[1]
            session_config["urgency"] = parts[1]
            session_config["urgency_enabled"] = True
        event_handler._print(f"Urgency set to {current_urgency or 'off'}.")
        return True, current_scope, current_urgency, active_session_id
    if command == "/sessions":
        try:
            result = await session.call_tool_direct("interactive_session_list", {})
            content = result.get("content", "")
            error = result.get("error", "")
            if content:
                for sid in _extract_session_ids_from_text(content):
                    known_session_ids.add(sid)
                event_handler._print(content)
            elif error:
                event_handler._print(f"{Colors.ACCENT_WARNING}[sessions] Error: {error}{Colors.RESET}")
            else:
                event_handler._print("No preserved interactive sessions are currently available.")
        except Exception as exc:
            event_handler._print(f"{Colors.ACCENT_WARNING}[sessions] Could not list sessions: {exc}{Colors.RESET}")
        return True, current_scope, current_urgency, active_session_id
    if command == "/refresh-sessions":
        try:
            count = await _refresh_known_session_ids(session, known_session_ids)
            event_handler._print(f"Refreshed {count} session ID(s): {', '.join(sorted(known_session_ids)) or '(none)'}")
        except Exception as exc:
            event_handler._print(f"Could not refresh sessions: {exc}")
        return True, current_scope, current_urgency, active_session_id
    if command == "/read":
        target_session_id = parts[1] if len(parts) == 2 else active_session_id
        if not target_session_id:
            event_handler._print("Usage: /read SESSION_ID  (or /enter SESSION_ID first)")
            return True, current_scope, current_urgency, active_session_id
        known_session_ids.add(target_session_id)
        result = await session.call_tool_direct("interactive_session_read", {"session_id": target_session_id})
        event_handler._print(str(result.get("content") or result.get("error") or result))
        return True, current_scope, current_urgency, active_session_id
    if command == "/write":
        if len(parts) >= 3:
            target_session_id = parts[1]
            user_input = " ".join(parts[2:])
        elif len(parts) == 2 and active_session_id:
            target_session_id = active_session_id
            user_input = parts[1]
        else:
            event_handler._print("Usage: /write SESSION_ID TEXT  (or /enter SESSION_ID then /write TEXT)")
            return True, current_scope, current_urgency, active_session_id
        known_session_ids.add(target_session_id)
        result = await session.call_tool_direct("interactive_session_write", {"session_id": target_session_id, "input": user_input})
        event_handler._print(str(result.get("content") or result.get("error") or result))
        return True, current_scope, current_urgency, active_session_id
    if command == "/close":
        target_session_id = parts[1] if len(parts) == 2 else active_session_id
        if not target_session_id:
            event_handler._print("Usage: /close SESSION_ID  (or /enter SESSION_ID first)")
            return True, current_scope, current_urgency, active_session_id
        result = await session.call_tool_direct("interactive_session_close", {"session_id": target_session_id})
        event_handler._print(str(result.get("content") or result.get("error") or result))
        if bool(result.get("success")):
            known_session_ids.discard(target_session_id)
        if target_session_id == active_session_id:
            active_session_id = None
        return True, current_scope, current_urgency, active_session_id

    event_handler._print(f"Unknown command: {command}. Type /help for commands.")
    return True, current_scope, current_urgency, active_session_id


def _list_runs(args: argparse.Namespace) -> int:
    sessions = load_session_list(str(PROJECT_DIR))[: max(args.limit, 0)]
    if not sessions:
        print("No runs found.")
        return 0

    print(f"{'Idx':>3} {'Run ID':36} {'Status':12} {'Model':24} {'Tools':>5} Transcript")
    print(f"{'-'*3} {'-' * 36} {'-' * 12} {'-' * 24} {'-' * 5} {'-' * 20}")
    for idx, metadata in enumerate(sessions):
        run_id = str(metadata.get("run_id") or "unknown")[:36]
        status = str(metadata.get("status") or "unknown")[:12]
        model = str(metadata.get("model") or "unknown")[:24]
        tool_count = metadata.get("total_tool_calls", metadata.get("available_tool_count", ""))
        transcript = _format_run_path(str(metadata.get("run_id") or "unknown"), "transcript.md")
        print(f"{idx:>3} {run_id:36} {status:12} {model:24} {str(tool_count):>5} {transcript}")
    return 0


async def _dispatch_async(args: argparse.Namespace) -> int:
    if args.command == "run":
        return await _run_prompt(args)
    if args.command == "chat":
        return await _chat(args)
    raise ValueError(f"Unsupported async command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    os.chdir(PROJECT_DIR)
    parser = _create_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "list-runs":
            return _list_runs(args)
        args = _resolve_session_args(args)
        return asyncio.run(_dispatch_async(args))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())