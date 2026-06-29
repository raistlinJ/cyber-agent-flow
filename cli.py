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
import sys
import time
from typing import Any

try:
    import readline
except Exception:
    readline = None

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
    "tools_config": None,
    "context_window": 8192,
    "max_turns": 20,
    "network_policy": {"allow": ["*"], "disallow": []},
    "scope": "medium",
    "scope_enabled": True,
    "urgency": "balanced",
    "urgency_enabled": True,
    "tool_output_chars": 6000,
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
    if key in {"context_window", "max_turns", "tool_output_chars"}:
        resolved[key] = int(value)
    elif key in {"ssl_verify", "scope_enabled", "urgency_enabled", "verbose"}:
        resolved[key] = bool(value)
    elif key == "api_key_env":
        resolved["api_key"] = os.environ.get(str(value or ""), "")
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
    merged.network_policy = resolved["network_policy"]
    merged.scope = resolved["scope"]
    merged.no_scope = not bool(resolved["scope_enabled"])
    merged.urgency = resolved["urgency"]
    merged.no_urgency = not bool(resolved["urgency_enabled"])
    merged.tool_output_chars = resolved["tool_output_chars"]
    merged.verbose = bool(resolved["verbose"])
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


def _install_slash_completion(get_session_ids=None) -> None:
    if readline is None:
        return

    session_id_getter = get_session_ids or (lambda: [])

    def _completer(text: str, state: int) -> str | None:
        buffer = readline.get_line_buffer() or ""
        start_idx = readline.get_begidx()
        suggestions = _completion_candidates(
            buffer=buffer,
            text=text,
            start_idx=start_idx,
            get_session_ids=session_id_getter,
        )

        if state < len(suggestions):
            return suggestions[state]
        return None

    try:
        readline.parse_and_bind("tab: complete")
        readline.set_completer_delims(" \t\n")
        readline.set_completer(_completer)
    except Exception:
        return


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


class TerminalEventHandler:
    def __init__(self, *, tool_output_chars: int = 6000, verbose: bool = False, known_session_ids: set[str] | None = None):
        self.session: MCPSession | None = None
        self.tool_output_chars = tool_output_chars
        self.verbose = verbose
        self.known_session_ids = known_session_ids

    def bind(self, session: MCPSession) -> None:
        self.session = session

    def __call__(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")

        if event_type == "status":
            self._print_status(str(event.get("message") or ""))
        elif event_type == "service_started":
            tools = event.get("tools") or []
            run_id = event.get("run_id") or "unknown"
            print(f"\n[started] run_id={run_id} tools={len(tools)}")
        elif event_type == "service_stopped":
            print("\n[stopped] Session stopped.")
        elif event_type == "response":
            text = str(event.get("text") or "").strip()
            if text:
                print(f"\nAssistant:\n{text}\n")
        elif event_type == "tool_call":
            tool = event.get("tool") or "tool"
            args = _compact_json(event.get("args") or {})
            print(f"\n[tool] {tool} {args}")
        elif event_type == "tool_result":
            self._print_tool_result(event)
        elif event_type == "error":
            print(f"\n[error] {event.get('message') or 'Unknown error.'}", file=sys.stderr)
        elif event_type == "context_usage":
            if self.verbose:
                used = event.get("used", "?")
                budget = event.get("budget", "?")
                model_max = event.get("model_max", "?")
                print(f"[context] used={used} budget={budget} model_max={model_max}")
        elif event_type == "post_tool_reply_decision":
            self._resolve_post_tool_reply(event)
        elif event_type == "dangerous_tool_approval":
            self._resolve_dangerous_tool(event)
        elif event_type == "tool_timeout_decision":
            self._resolve_tool_timeout(event)
        elif event_type == "chat_done":
            print(f"[done] {event.get('message') or 'Ready for next prompt.'}")
        elif event_type == "isess_created":
            session_id = event.get("session_id") or "unknown"
            session_kind = event.get("session_kind") or "interactive"
            if self.known_session_ids is not None and str(session_id).strip():
                self.known_session_ids.add(str(session_id).strip())
            print(f"[interactive] Preserved {session_kind} session {session_id}.")
        elif event_type == "isess_output":
            session_id = event.get("session_id") or "unknown"
            output = str(event.get("output") or "")
            print(f"\n[interactive:{session_id}]\n{output}")
        elif event_type == "isess_closed":
            session_id = event.get("session_id") or "unknown"
            if self.known_session_ids is not None and str(session_id).strip():
                self.known_session_ids.discard(str(session_id).strip())
            print(f"[interactive] Session {session_id} closed.")

    def _print_status(self, message: str) -> None:
        if message:
            print(f"[status] {message}")

    def _print_tool_result(self, event: dict[str, Any]) -> None:
        tool = event.get("tool") or "tool"
        exit_code = event.get("exit_code", "?")
        duration_ms = event.get("duration_ms", "?")
        result = _truncate(str(event.get("result") or ""), self.tool_output_chars)
        print(f"[result] {tool} exit={exit_code} duration_ms={duration_ms}")
        if result.strip():
            print(result)

    def _prompt_choice(self, question: str, options: tuple[str, ...], default: str) -> str:
        if not sys.stdin.isatty():
            print(f"[decision] Non-interactive input; choosing {default}.")
            return default

        option_text = "/".join(options)
        while True:
            answer = input(f"{question} ({option_text}) [{default}]: ").strip().lower()
            if not answer:
                return default
            matches = [option for option in options if option.startswith(answer)]
            if len(matches) == 1:
                return matches[0]
            print(f"Please choose one of: {', '.join(options)}")

    def _resolve_post_tool_reply(self, event: dict[str, Any]) -> None:
        print(f"\n[decision] {event.get('message') or 'Retry the final answer or cancel?'}")
        action = self._prompt_choice("Decision", ("retry", "cancel"), "cancel")
        if self.session and not self.session.resolve_post_tool_reply_decision(action):
            print("[decision] Could not apply post-tool reply decision.", file=sys.stderr)

    def _resolve_dangerous_tool(self, event: dict[str, Any]) -> None:
        tool = event.get("tool") or "shell_dangerous"
        command = str(event.get("command") or "")
        print(f"\n[approval] {event.get('message') or 'Approval required.'}")
        print(f"Tool: {tool}")
        if command:
            print(f"Command: {command}")
        action = self._prompt_choice("Approve execution", ("approve", "cancel"), "cancel")
        if self.session and not self.session.resolve_dangerous_tool_approval(action):
            print("[approval] Could not apply dangerous-tool decision.", file=sys.stderr)

    def _resolve_tool_timeout(self, event: dict[str, Any]) -> None:
        print(f"\n[timeout] {event.get('message') or 'Tool reached a timeout checkpoint.'}")
        command = str(event.get("command") or "")
        if command:
            print(f"Command: {command}")
        action = self._prompt_choice("Timeout action", ("wait", "background", "kill"), "wait")
        wait_seconds = None
        if action == "wait":
            wait_seconds = self._prompt_wait_seconds(default=60)
        if self.session and not self.session.resolve_tool_timeout_decision(action, wait_seconds=wait_seconds):
            print("[timeout] Could not apply timeout decision.", file=sys.stderr)

    def _prompt_wait_seconds(self, default: int) -> int:
        if not sys.stdin.isatty():
            return default
        allowed_text = ", ".join(str(value) for value in TIMEOUT_WAIT_CHOICES)
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


def _add_session_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="Path to a JSON session config file (default: configs/cli.json, required). CLI flags override config values. See docs/configuration.md for details.")
    parser.add_argument("--provider", help="LLM provider: ollama_direct, litellm, openai, or claude.")
    parser.add_argument("--url", help="LLM provider base URL.")
    parser.add_argument("--model", help="Model name. Can also be set with MCP_MODEL or in config.")
    parser.add_argument("--api-key", help="Optional API key. Prefer MCP_API_KEY for shell history safety.")
    parser.add_argument("--no-ssl-verify", action="store_true", help="Disable TLS verification for proxied HTTPS providers.")
    parser.add_argument("--server-command", help="Command used to launch the MCP server.")
    parser.add_argument("--tools-config", help="Path to a kali_tools.json-compatible file. Defaults to ./kali_tools.json.")
    parser.add_argument("--context-window", type=int, help="LLM context window budget in tokens.")
    parser.add_argument("--max-turns", type=int, help="Maximum LLM/tool iterations per prompt.")
    parser.add_argument("--allow", action="append", help="Allowed target entry. Repeat or comma-separate values. Default: *")
    parser.add_argument("--disallow", action="append", help="Disallowed target entry. Repeat or comma-separate values.")
    parser.add_argument("--scope", choices=SCOPE_CHOICES, help="Per-prompt scope control.")
    parser.add_argument("--no-scope", action="store_true", help="Do not inject scope guidance.")
    parser.add_argument("--urgency", choices=URGENCY_CHOICES, help="Per-prompt urgency control.")
    parser.add_argument("--no-urgency", action="store_true", help="Do not inject urgency guidance.")
    parser.add_argument("--tool-output-chars", type=int, help="Maximum tool output chars printed to terminal; full output is logged.")
    parser.add_argument("--verbose", action="store_true", help="Print context usage events.")


def _create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Terminal interface for CyberAgentFlow. Use --config to load settings from a JSON file (required: configs/cli.json or custom path).")
    subparsers = parser.add_subparsers(dest="command", required=True)

    chat_parser = subparsers.add_parser("chat", help="Start an interactive terminal chat session.")
    _add_session_args(chat_parser)

    run_parser = subparsers.add_parser("run", help="Run one prompt, then stop the session.")
    _add_session_args(run_parser)
    run_parser.add_argument("prompt", nargs=argparse.REMAINDER, help="Prompt to send to the agent.")

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


def _effective_scope(args: argparse.Namespace) -> str | None:
    return None if args.no_scope else args.scope


def _effective_urgency(args: argparse.Namespace) -> str | None:
    return None if args.no_urgency else args.urgency


async def _start_session(args: argparse.Namespace, event_handler: TerminalEventHandler) -> MCPSession:
    _validate_session_args(args)
    enabled_tool_guides = _copy_tools_config_if_requested(args.tools_config)
    server_type = "apt" if "/usr/share/mcp-kali-server/mcp_server.py" in args.server_command else "cli"
    run_id = make_run_id(server_type)
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
        network_policy=args.network_policy,
        enabled_tool_guides=enabled_tool_guides,
    )
    event_handler.bind(session)
    await session.start()
    return session


async def _run_prompt(args: argparse.Namespace) -> int:
    event_handler = TerminalEventHandler(tool_output_chars=args.tool_output_chars, verbose=args.verbose)
    session: MCPSession | None = None
    prompt = args.prompt_text
    if not prompt:
        raise ValueError("A prompt is required for the run command.")
    try:
        session = await _start_session(args, event_handler)
        await session.chat(prompt, scope=_effective_scope(args), urgency=_effective_urgency(args))
        print(f"[run] Transcript: {_format_run_path(session.run_id, 'transcript.md')}")
        return 0
    finally:
        if session:
            await session.stop()


async def _chat(args: argparse.Namespace) -> int:
    known_session_ids: set[str] = set()
    event_handler = TerminalEventHandler(
        tool_output_chars=args.tool_output_chars,
        verbose=args.verbose,
        known_session_ids=known_session_ids,
    )
    session: MCPSession | None = None
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
        session = await _start_session(args, event_handler)
        _install_slash_completion(get_session_ids=lambda: sorted(known_session_ids))
        print("Type /help for CLI commands, /exit to stop.")
        while True:
            now = time.monotonic()
            if now >= next_session_refresh_at:
                try:
                    await _refresh_known_session_ids(session, known_session_ids)
                except Exception:
                    pass
                next_session_refresh_at = now + session_refresh_interval_seconds

            try:
                prompt_prefix = f"caf[{active_session_id}]> " if active_session_id else "caf> "
                prompt = input(prompt_prefix).strip()
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print("\nUse /exit to stop the session cleanly.")
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
                print(str(result.get("content") or result.get("error") or result))
            else:
                await session.chat(prompt, scope=current_scope, urgency=current_urgency)
        print(f"[chat] Transcript: {_format_run_path(session.run_id, 'transcript.md')}")
        return 0
    finally:
        if session:
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
        print(
            "Commands:\n"
            "  /help                       Show this help.\n"
            "  /exit                       Stop the session.\n"
            "  /enter SESSION_ID           Enter interactive session mode (like a tab).\n"
            "  /back                       Return to main chat mode.\n"
            "  /where                      Show current mode and selected session.\n"
            "  /config                     Show current config values.\n"
            "  /set KEY VALUE              Update settings from chat.\n"
            "  /save-config [PATH]         Save current settings to JSON config file.\n"
            "  /tools                      List available MCP tools.\n"
            "  /scope VALUE|off            Set scope for later prompts.\n"
            "  /urgency VALUE|off          Set urgency for later prompts.\n"
            "  /sessions                   List preserved interactive sessions.\n"
            "  /refresh-sessions           Refresh session IDs from backend for autocomplete.\n"
            "  /read [SESSION_ID]          Read output (defaults to entered session).\n"
            "  /write ...                  Send text: /write ID TEXT or /write TEXT in entered mode.\n"
            "  /close [SESSION_ID]         Close session (defaults to entered session).\n"
            "\n"
            "When entered into a session via /enter, plain text is sent directly to that session."
        )
        return True, current_scope, current_urgency, active_session_id
    if command == "/config":
        print(json.dumps(session_config, indent=2, ensure_ascii=True))
        return True, current_scope, current_urgency, active_session_id
    if command == "/set":
        if len(parts) < 3:
            print("Usage: /set KEY VALUE")
            print("Examples: /set urgency fast | /set scope_enabled false | /set tool_output_chars 12000")
            return True, current_scope, current_urgency, active_session_id

        key = parts[1].strip().lower()
        raw_value = " ".join(parts[2:]).strip()

        if key == "scope":
            value = raw_value.lower()
            if value == "off":
                session_config["scope_enabled"] = False
                current_scope = None
                print("Scope disabled for this chat session.")
                return True, current_scope, current_urgency, active_session_id
            if value not in SCOPE_CHOICES:
                print("scope must be one of: " + ", ".join(SCOPE_CHOICES) + " or off")
                return True, current_scope, current_urgency, active_session_id
            session_config["scope"] = value
            session_config["scope_enabled"] = True
            current_scope = value
            print(f"Scope set to {value}.")
            return True, current_scope, current_urgency, active_session_id

        if key == "urgency":
            value = raw_value.lower()
            if value == "off":
                session_config["urgency_enabled"] = False
                current_urgency = None
                print("Urgency disabled for this chat session.")
                return True, current_scope, current_urgency, active_session_id
            if value not in URGENCY_CHOICES:
                print("urgency must be one of: " + ", ".join(URGENCY_CHOICES) + " or off")
                return True, current_scope, current_urgency, active_session_id
            session_config["urgency"] = value
            session_config["urgency_enabled"] = True
            current_urgency = value
            print(f"Urgency set to {value}.")
            return True, current_scope, current_urgency, active_session_id

        if key == "scope_enabled":
            try:
                enabled = _to_bool(raw_value)
            except ValueError as exc:
                print(str(exc))
                return True, current_scope, current_urgency, active_session_id
            session_config["scope_enabled"] = enabled
            current_scope = session_config.get("scope") if enabled else None
            print(f"scope_enabled set to {enabled}.")
            return True, current_scope, current_urgency, active_session_id

        if key == "urgency_enabled":
            try:
                enabled = _to_bool(raw_value)
            except ValueError as exc:
                print(str(exc))
                return True, current_scope, current_urgency, active_session_id
            session_config["urgency_enabled"] = enabled
            current_urgency = session_config.get("urgency") if enabled else None
            print(f"urgency_enabled set to {enabled}.")
            return True, current_scope, current_urgency, active_session_id

        if key == "verbose":
            try:
                enabled = _to_bool(raw_value)
            except ValueError as exc:
                print(str(exc))
                return True, current_scope, current_urgency, active_session_id
            session_config["verbose"] = enabled
            event_handler.verbose = enabled
            print(f"verbose set to {enabled}.")
            return True, current_scope, current_urgency, active_session_id

        if key == "tool_output_chars":
            try:
                chars = int(raw_value)
            except ValueError:
                print("tool_output_chars must be an integer")
                return True, current_scope, current_urgency, active_session_id
            if chars < 0:
                print("tool_output_chars must be >= 0")
                return True, current_scope, current_urgency, active_session_id
            session_config["tool_output_chars"] = chars
            event_handler.tool_output_chars = chars
            print(f"tool_output_chars set to {chars}.")
            return True, current_scope, current_urgency, active_session_id

        if key in {
            "provider", "url", "model", "api_key", "ssl_verify",
            "server_command", "tools_config", "context_window", "max_turns",
            "allow", "disallow",
        }:
            restart_required_message = "Saved in config state. Restart the chat session for this to take effect."
            if key == "ssl_verify":
                try:
                    session_config["ssl_verify"] = _to_bool(raw_value)
                except ValueError as exc:
                    print(str(exc))
                    return True, current_scope, current_urgency, active_session_id
            elif key in {"context_window", "max_turns"}:
                try:
                    session_config[key] = int(raw_value)
                except ValueError:
                    print(f"{key} must be an integer")
                    return True, current_scope, current_urgency, active_session_id
            elif key in {"allow", "disallow"}:
                values = _split_entries([raw_value], ["*"] if key == "allow" else [])
                session_config["network_policy"][key] = values
            else:
                session_config[key] = raw_value
            print(restart_required_message)
            return True, current_scope, current_urgency, active_session_id

        print("Unsupported key. Try /config to inspect available settings.")
        return True, current_scope, current_urgency, active_session_id
    if command == "/save-config":
        target_path = _resolve_path(parts[1]) if len(parts) > 1 else _resolve_path(config_target_path)
        os.makedirs(target_path.parent, exist_ok=True)
        with target_path.open("w") as config_file:
            json.dump(session_config, config_file, indent=2)
            config_file.write("\n")
        print(f"Saved config to {target_path}")
        return True, current_scope, current_urgency, active_session_id
    if command in {"/back", "/main"}:
        if active_session_id:
            print(f"Returned to main chat mode from {active_session_id}.")
        else:
            print("Already in main chat mode.")
        return True, current_scope, current_urgency, None
    if command == "/where":
        if active_session_id:
            print(f"Mode: interactive session ({active_session_id})")
        else:
            print("Mode: main chat")
        return True, current_scope, current_urgency, active_session_id
    if command == "/enter":
        if len(parts) != 2:
            print("Usage: /enter SESSION_ID")
            return True, current_scope, current_urgency, active_session_id
        selected = parts[1]
        known_session_ids.add(selected)
        print(f"Entered interactive session mode: {selected}")
        return True, current_scope, current_urgency, selected
    if command == "/tools":
        print("Available tools: " + ", ".join(session.tool_names))
        return True, current_scope, current_urgency, active_session_id
    if command == "/scope":
        if len(parts) != 2 or (parts[1] != "off" and parts[1] not in SCOPE_CHOICES):
            print("Usage: /scope broad|medium-broad|medium|medium-narrow|narrow|off")
            return True, current_scope, current_urgency, active_session_id
        if parts[1] == "off":
            current_scope = None
            session_config["scope_enabled"] = False
        else:
            current_scope = parts[1]
            session_config["scope"] = parts[1]
            session_config["scope_enabled"] = True
        print(f"Scope set to {current_scope or 'off'}.")
        return True, current_scope, current_urgency, active_session_id
    if command == "/urgency":
        if len(parts) != 2 or (parts[1] != "off" and parts[1] not in URGENCY_CHOICES):
            print("Usage: /urgency stealthy|methodical|balanced|fast|speed|off")
            return True, current_scope, current_urgency, active_session_id
        if parts[1] == "off":
            current_urgency = None
            session_config["urgency_enabled"] = False
        else:
            current_urgency = parts[1]
            session_config["urgency"] = parts[1]
            session_config["urgency_enabled"] = True
        print(f"Urgency set to {current_urgency or 'off'}.")
        return True, current_scope, current_urgency, active_session_id
    if command == "/sessions":
        result = await session.call_tool_direct("interactive_session_list", {})
        for sid in _extract_session_ids_from_text(str(result.get("content") or "")):
            known_session_ids.add(sid)
        print(str(result.get("content") or result.get("error") or result))
        return True, current_scope, current_urgency, active_session_id
    if command == "/refresh-sessions":
        try:
            count = await _refresh_known_session_ids(session, known_session_ids)
            print(f"Refreshed {count} session ID(s): {', '.join(sorted(known_session_ids)) or '(none)'}")
        except Exception as exc:
            print(f"Could not refresh sessions: {exc}")
        return True, current_scope, current_urgency, active_session_id
    if command == "/read":
        target_session_id = parts[1] if len(parts) == 2 else active_session_id
        if not target_session_id:
            print("Usage: /read SESSION_ID  (or /enter SESSION_ID first)")
            return True, current_scope, current_urgency, active_session_id
        known_session_ids.add(target_session_id)
        result = await session.call_tool_direct("interactive_session_read", {"session_id": target_session_id})
        print(str(result.get("content") or result.get("error") or result))
        return True, current_scope, current_urgency, active_session_id
    if command == "/write":
        if len(parts) >= 3:
            target_session_id = parts[1]
            user_input = " ".join(parts[2:])
        elif len(parts) == 2 and active_session_id:
            target_session_id = active_session_id
            user_input = parts[1]
        else:
            print("Usage: /write SESSION_ID TEXT  (or /enter SESSION_ID then /write TEXT)")
            return True, current_scope, current_urgency, active_session_id
        known_session_ids.add(target_session_id)
        result = await session.call_tool_direct("interactive_session_write", {"session_id": target_session_id, "input": user_input})
        print(str(result.get("content") or result.get("error") or result))
        return True, current_scope, current_urgency, active_session_id
    if command == "/close":
        target_session_id = parts[1] if len(parts) == 2 else active_session_id
        if not target_session_id:
            print("Usage: /close SESSION_ID  (or /enter SESSION_ID first)")
            return True, current_scope, current_urgency, active_session_id
        result = await session.call_tool_direct("interactive_session_close", {"session_id": target_session_id})
        print(str(result.get("content") or result.get("error") or result))
        if bool(result.get("success")):
            known_session_ids.discard(target_session_id)
        if target_session_id == active_session_id:
            active_session_id = None
        return True, current_scope, current_urgency, active_session_id

    print(f"Unknown command: {command}. Type /help for commands.")
    return True, current_scope, current_urgency, active_session_id


def _list_runs(args: argparse.Namespace) -> int:
    sessions = load_session_list(str(PROJECT_DIR))[: max(args.limit, 0)]
    if not sessions:
        print("No runs found.")
        return 0

    print(f"{'Run ID':36} {'Status':12} {'Model':24} {'Tools':>5} Transcript")
    print(f"{'-' * 36} {'-' * 12} {'-' * 24} {'-' * 5} {'-' * 20}")
    for metadata in sessions:
        run_id = str(metadata.get("run_id") or "unknown")[:36]
        status = str(metadata.get("status") or "unknown")[:12]
        model = str(metadata.get("model") or "unknown")[:24]
        tool_count = metadata.get("total_tool_calls", metadata.get("available_tool_count", ""))
        transcript = _format_run_path(str(metadata.get("run_id") or "unknown"), "transcript.md")
        print(f"{run_id:36} {status:12} {model:24} {str(tool_count):>5} {transcript}")
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