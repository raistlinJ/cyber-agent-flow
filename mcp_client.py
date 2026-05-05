#!/usr/bin/env python3
"""
mcp_client.py — Persistent MCP session with chat-loop support.

Uses the official `mcp` SDK to connect to an MCP server via stdio,
and the `ollama` library to drive LLM chat completions with tool use.

Architecture:
  MCPSession — a long-lived object that manages the MCP server connection
  and conversation state.  Callers use:
      session.start()  → launch MCP server, discover tools
      session.chat()   → send a user prompt, run the agent loop
      session.stop()   → graceful teardown

Every event (prompt, LLM text, tool calls, errors) is pushed through
an `event_callback(event: dict)` so the Flask layer can broadcast it
over SSE and persist it via SessionLogger.

Includes context-window management: when the conversation approaches a
configurable token budget, older messages are summarised by the LLM and
replaced with a compact summary, keeping the most recent turns intact.
"""

import asyncio
import ipaddress
import json
import os
import re
import requests
import shlex
import time
import traceback
from pathlib import Path
from urllib.parse import urlparse
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

try:
    import ollama as _ollama_lib
    _HAVE_OLLAMA = True
except ImportError:
    _HAVE_OLLAMA = False

from session_logger import SessionLogger, make_run_id


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Rough chars-per-token ratio (conservative; real ratio is ~3.5–4 for English)
_CHARS_PER_TOKEN = 4

# Default context window budget (tokens).  Can be overridden via `context_window`.
DEFAULT_CONTEXT_WINDOW = 8192

# Default maximum LLM/tool iterations allowed for a single user prompt.
DEFAULT_MAX_TURNS = 20

# When estimated token usage exceeds this fraction of the budget, trigger
# summarisation of older messages.
_SUMMARISE_THRESHOLD = 0.75

# Number of most-recent messages to keep intact (never summarised).
_KEEP_RECENT = 6

_SUMMARISE_SYSTEM_PROMPT = (
    "You are a concise summariser. Condense the following conversation history "
    "into a brief summary that preserves all important facts, decisions, tool "
    "results, and any data the assistant will need to continue working. "
    "Output ONLY the summary, no preamble."
)

_URL_RE = re.compile(r'https?://[^\s]+', re.IGNORECASE)
_CIDR_OR_IP_RE = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b')
_HOSTNAME_RE = re.compile(r'^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\.?$', re.IGNORECASE)
_TIMEOUT_CONTROL_DIRNAME = "control"
_TIMEOUT_REQUEST_FILENAME = "tool_timeout_request.json"
_TIMEOUT_RESPONSE_FILENAME = "tool_timeout_response.json"
_TOOL_DOC_MAP = {
    "msf_run": "docs/tools/msf_run.md",
    "RIPv2": "docs/tools/RIPv2.md",
    "ospf_sniff": "docs/tools/ospf_sniff.md",
    "shell": "docs/tools/shell.md",
    "shell_extended": "docs/tools/shell_extended.md",
    "shell_sequence": "docs/tools/shell_sequence.md",
    "shell_dangerous": "docs/tools/shell_dangerous.md",
    "interactive_session_list": "docs/tools/interactive_sessions.md",
    "interactive_session_read": "docs/tools/interactive_sessions.md",
    "interactive_session_write": "docs/tools/interactive_sessions.md",
    "interactive_session_close": "docs/tools/interactive_sessions.md",
}
_TOOL_DOC_MAX_CHARS_PER_DOC = 3500
_TOOL_DOC_MAX_TOTAL_CHARS = 14000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize_tool_schema_value(value):
    """Normalize tool schema text so XML-based model adapters do not choke on it."""
    if isinstance(value, str):
        return value.replace("<", "[").replace(">", "]")
    if isinstance(value, list):
        return [_sanitize_tool_schema_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_tool_schema_value(item) for key, item in value.items()}
    return value

def _mcp_tool_to_ollama(tool) -> dict:
    """Convert an MCP Tool object to the Ollama function-calling schema."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": _sanitize_tool_schema_value(tool.description or f"Run {tool.name}"),
            "parameters": _sanitize_tool_schema_value(tool.inputSchema) if tool.inputSchema else {
                "type": "object",
                "properties": {},
            },
        },
    }


def _mcp_tool_to_ollama_minimal(tool) -> dict:
    """Minimal tool schema fallback for models that choke on richer XML/function payloads."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": f"Run {tool.name}",
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {"type": "string"},
                },
            },
        },
    }


def _mcp_tool_to_anthropic(tool) -> dict:
    return {
        "name": tool.name,
        "description": _sanitize_tool_schema_value(tool.description or f"Run {tool.name}"),
        "input_schema": _sanitize_tool_schema_value(tool.inputSchema) if tool.inputSchema else {
            "type": "object",
            "properties": {},
        },
    }


def _mcp_tool_to_anthropic_minimal(tool) -> dict:
    return {
        "name": tool.name,
        "description": f"Run {tool.name}",
        "input_schema": {
            "type": "object",
            "properties": {
                "args": {"type": "string"},
            },
        },
    }


def _is_xml_schema_error(exc: Exception) -> bool:
    message = str(exc or "")
    return "XML syntax error" in message and "status code: 500" in message


def _http_error_status_code(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)


def _http_error_response_text(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if response is None:
        return ""
    try:
        return str(response.text or "")
    except Exception:
        return ""


def _is_litellm_retryable_tool_error(exc: Exception) -> bool:
    status_code = _http_error_status_code(exc)
    if status_code not in {400, 422, 500, 502, 503, 504}:
        return False

    response_text = _http_error_response_text(exc).lower()
    if not response_text and status_code >= 500:
        return True

    retry_markers = (
        "tool",
        "function",
        "schema",
        "json",
        "invalid parameter",
        "bad request",
        "unsupported",
    )
    return any(marker in response_text for marker in retry_markers)


def _is_transient_transport_error(exc: Exception) -> bool:
    retry_markers = (
        "connection reset by peer",
        "readerror",
        "remoteprotocolerror",
        "server disconnected",
        "connection aborted",
        "broken pipe",
        "temporarily unavailable",
        "timed out",
        "connection closed",
    )

    cur: Exception | None = exc
    while cur is not None:
        text = f"{type(cur).__name__}: {cur}".lower()
        if any(marker in text for marker in retry_markers):
            return True
        cur = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)

    return False


def _normalize_provider_name(provider: str | None) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized in {"litellm", "lite-llm", "lite_llm"}:
        return "litellm"
    if normalized in {"openai", "open-ai"}:
        return "openai"
    if normalized in {"claude", "anthropic"}:
        return "claude"
    return "ollama_direct"


def _provider_display_name(provider: str | None) -> str:
    normalized = _normalize_provider_name(provider)
    if normalized == "litellm":
        return "LiteLLM"
    if normalized == "openai":
        return "OpenAI"
    if normalized == "claude":
        return "Claude"
    return "Ollama"


def _normalize_provider_base_url(provider: str | None, host: str) -> str:
    normalized_provider = _normalize_provider_name(provider)
    normalized_host = str(host or "").strip().rstrip("/")

    if not normalized_host:
        return normalized_host

    if normalized_provider == "ollama_direct":
        return normalized_host

    if normalized_provider in {"openai", "litellm", "claude"} and normalized_host.endswith("/v1"):
        return normalized_host[:-3]

    return normalized_host


def _provider_headers(provider: str | None, api_key: str | None) -> dict:
    normalized = _normalize_provider_name(provider)
    headers = {}

    if normalized == "claude":
        headers["anthropic-version"] = "2023-06-01"
        if api_key:
            headers["x-api-key"] = api_key
        return headers

    if not api_key:
        return headers

    headers["Authorization"] = f"Bearer {api_key}"
    if normalized == "litellm":
        headers["x-api-key"] = api_key
    return headers


def _tool_call_identifier(tool_call) -> str | None:
    if hasattr(tool_call, "get"):
        value = tool_call.get("id")
        if value:
            return str(value)
    value = getattr(tool_call, "id", None)
    if value:
        return str(value)
    return None


def _json_argument_string(arguments) -> str:
    if isinstance(arguments, str):
        return arguments
    try:
        return json.dumps(arguments or {}, ensure_ascii=True)
    except Exception:
        return "{}"


def _message_text_content(message) -> str:
    content = message.get("content", "") if hasattr(message, "get") else getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if content is None:
        content = []
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or item.get("output_text") or item.get("value")
                if text:
                    parts.append(str(text))
            elif item is not None:
                parts.append(str(item))
        if parts:
            return "\n".join(part for part in parts if part)

    if hasattr(message, "get"):
        for key in ("output_text", "reasoning_content", "refusal"):
            value = message.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return str(content)


def _message_tool_calls(message) -> list:
    if hasattr(message, "get"):
        tool_calls = message.get("tool_calls")
        if tool_calls:
            return list(tool_calls)
        function_call = message.get("function_call")
        if function_call:
            return [{
                "id": message.get("tool_call_id") or "call_1",
                "type": "function",
                "function": function_call,
            }]
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        return list(tool_calls)
    function_call = getattr(message, "function_call", None)
    if function_call:
        return [{
            "id": getattr(message, "tool_call_id", None) or "call_1",
            "type": "function",
            "function": function_call,
        }]
    return []


def _extract_json_object(text: str) -> dict | None:
    raw = str(text or "").strip()
    if not raw:
        return None

    candidates = [raw]
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", raw, flags=re.IGNORECASE | re.DOTALL)
    candidates.extend(item.strip() for item in fenced if item.strip())

    for candidate in list(candidates):
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidates.append(candidate[start:end + 1])

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _normalize_litellm_tool_plan(payload: dict, tool_names: list[str]) -> dict | None:
    if not isinstance(payload, dict):
        return None

    respond = payload.get("respond") or payload.get("response") or payload.get("reply") or payload.get("content")
    if isinstance(respond, str) and respond.strip() and not payload.get("tool") and not payload.get("name") and not payload.get("function"):
        return {"content": respond.strip(), "tool_calls": None}

    function = payload.get("function")
    if isinstance(function, dict):
        name = function.get("name")
        arguments = function.get("arguments")
    else:
        name = payload.get("tool") or payload.get("name")
        arguments = payload.get("arguments", payload.get("args", {}))

    if not isinstance(name, str) or name not in set(tool_names or []):
        return None

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except Exception:
            arguments = {"args": arguments}
    if not isinstance(arguments, dict):
        arguments = {}

    return {
        "content": "",
        "tool_calls": [{
            "id": "litellm_manual_plan_1",
            "type": "function",
            "function": {
                "name": name,
                "arguments": arguments,
            },
        }],
    }


def _looks_like_malformed_tool_planning(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return True

    if "the user wants to" in normalized:
        return True

    if ("{" in normalized or "}" in normalized) and any(token in normalized for token in ('"args"', '"name"', '"function"', '"scan ')):
        return True

    if len(normalized) < 320 and any(token in normalized for token in ("tool call", "function_call", "arguments", "assistant to=functions")):
        return True

    return False


def _to_openai_messages(messages: list[dict]) -> list[dict]:
    converted = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        payload = {
            "role": role,
            "content": content if isinstance(content, str) else _message_text_content({"content": content}),
        }

        if role == "assistant" and message.get("tool_calls"):
            payload["content"] = payload["content"] or None
            payload["tool_calls"] = []
            for index, tool_call in enumerate(message.get("tool_calls", []), start=1):
                tool_name, tool_args = _extract_tool_info(tool_call)
                tool_call_id = _tool_call_identifier(tool_call) or f"call_{index}"
                payload["tool_calls"].append({
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": _json_argument_string(tool_args),
                    },
                })

        if role == "tool":
            tool_call_id = message.get("tool_call_id")
            if tool_call_id:
                payload["tool_call_id"] = tool_call_id
            tool_name = message.get("name")
            if tool_name:
                payload["name"] = tool_name

        converted.append(payload)
    return converted


class _LiteLLMClient:
    def __init__(self, host: str, headers: dict | None = None, timeout: int = 90, verify: bool = True):
        self.host = host.rstrip("/")
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        self.timeout = timeout
        self.verify = verify

    def show(self, model: str) -> dict:
        response = requests.get(
            f"{self.host}/v1/models",
            headers=self.headers,
            timeout=min(self.timeout, 20),
            verify=self.verify,
        )
        response.raise_for_status()
        payload = response.json() or {}
        for item in payload.get("data", []):
            if isinstance(item, dict) and item.get("id") == model:
                return item
        return payload

    def chat(self, model: str, messages: list[dict], tools=None, options=None) -> dict:
        payload = {
            "model": model,
            "messages": _to_openai_messages(messages),
        }
        if tools:
            payload["tools"] = tools

        options = options or {}
        temperature = options.get("temperature")
        if temperature is not None:
            payload["temperature"] = temperature
        if tools and options.get("tool_choice", True) is not False:
            payload["tool_choice"] = "auto"

        response = requests.post(
            f"{self.host}/v1/chat/completions",
            headers=self.headers,
            json=payload,
            timeout=self.timeout,
            verify=self.verify,
        )
        response.raise_for_status()
        raw = response.json() or {}
        choices = raw.get("choices") or []
        choice = choices[0] if choices else {}
        message = choice.get("message") or {}
        tool_calls = []
        for index, tool_call in enumerate(_message_tool_calls(message), start=1):
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function") or {}
            arguments = function.get("arguments") or {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except Exception:
                    arguments = {"args": arguments}
            tool_calls.append({
                "id": tool_call.get("id") or f"call_{index}",
                "type": tool_call.get("type", "function"),
                "function": {
                    "name": function.get("name"),
                    "arguments": arguments if isinstance(arguments, dict) else {},
                },
            })

        return {
            "message": {
                "content": _message_text_content(message),
                "tool_calls": tool_calls or None,
            },
            "raw": raw,
        }


def _to_anthropic_messages(messages: list[dict]) -> tuple[str | None, list[dict]]:
    system_parts = []
    converted = []

    for message in messages:
        role = str(message.get("role", "user"))
        content = message.get("content", "")
        text_content = content if isinstance(content, str) else _message_text_content({"content": content})

        if role == "system":
            if text_content:
                system_parts.append(text_content)
            continue

        if role == "assistant":
            blocks = []
            if text_content:
                blocks.append({"type": "text", "text": text_content})
            for index, tool_call in enumerate(message.get("tool_calls", []) or [], start=1):
                tool_name, tool_args = _extract_tool_info(tool_call)
                tool_call_id = _tool_call_identifier(tool_call) or f"call_{index}"
                blocks.append({
                    "type": "tool_use",
                    "id": tool_call_id,
                    "name": tool_name,
                    "input": tool_args,
                })
            converted.append({"role": "assistant", "content": blocks or text_content or ""})
            continue

        if role == "tool":
            tool_result_block = {
                "type": "tool_result",
                "tool_use_id": message.get("tool_call_id") or "tool_result_1",
                "content": text_content or "",
            }
            if converted and converted[-1].get("role") == "user" and isinstance(converted[-1].get("content"), list):
                converted[-1]["content"].append(tool_result_block)
            else:
                converted.append({"role": "user", "content": [tool_result_block]})
            continue

        converted.append({"role": "user", "content": text_content or ""})

    system_text = "\n\n".join(part for part in system_parts if part) or None
    return system_text, converted


class _AnthropicClient:
    def __init__(self, host: str, headers: dict | None = None, timeout: int = 90, verify: bool = True):
        self.host = host.rstrip("/")
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        self.timeout = timeout
        self.verify = verify

    def show(self, model: str) -> dict:
        response = requests.get(
            f"{self.host}/v1/models",
            headers=self.headers,
            timeout=min(self.timeout, 20),
            verify=self.verify,
        )
        response.raise_for_status()
        payload = response.json() or {}
        for item in payload.get("data", []):
            if isinstance(item, dict) and item.get("id") == model:
                return item
        return payload

    def chat(self, model: str, messages: list[dict], tools=None, options=None) -> dict:
        options = options or {}
        system_text, anthropic_messages = _to_anthropic_messages(messages)
        payload = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": int(options.get("max_tokens") or 4096),
        }
        if system_text:
            payload["system"] = system_text
        if tools:
            payload["tools"] = tools
        temperature = options.get("temperature")
        if temperature is not None:
            payload["temperature"] = temperature

        response = requests.post(
            f"{self.host}/v1/messages",
            headers=self.headers,
            json=payload,
            timeout=self.timeout,
            verify=self.verify,
        )
        response.raise_for_status()
        raw = response.json() or {}
        text_parts = []
        tool_calls = []
        for block in raw.get("content", []) or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text"):
                text_parts.append(str(block.get("text")))
            if block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id") or f"call_{len(tool_calls) + 1}",
                    "type": "function",
                    "function": {
                        "name": block.get("name"),
                        "arguments": block.get("input") if isinstance(block.get("input"), dict) else {},
                    },
                })

        return {
            "message": {
                "content": "\n".join(text_parts),
                "tool_calls": tool_calls or None,
            },
            "raw": raw,
        }


def _normalize_network_policy(policy) -> dict:
    policy = policy or {}
    allow = [str(item).strip() for item in policy.get("allow", ["*"]) if str(item).strip()]
    disallow = [str(item).strip() for item in policy.get("disallow", []) if str(item).strip()]
    if not allow:
        allow = ["*"]
    return {"allow": allow, "disallow": disallow}


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
            host = (urlparse(url).hostname or '').lower()
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
            return ipaddress.ip_network(target_value, strict=False).num_addresses == 1 and ipaddress.ip_network(target_value, strict=False).network_address == entry_ip
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


def _emit(callback, event_type: str, data: dict):
    """Safely call the event callback."""
    if callback:
        try:
            callback({"type": event_type, **data})
        except Exception:
            pass


def _estimate_tokens(messages: list[dict]) -> int:
    """Estimate total token count from a messages list (rough heuristic)."""
    total_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        tcs = msg.get("tool_calls")
        if tcs:
            total_chars += len(str(tcs))
    return total_chars // _CHARS_PER_TOKEN


def _truncate_tool_output(text: str, max_chars: int = 8000) -> str:
    """Truncate large tool outputs to keep context lean."""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return (
        text[:half]
        + f"\n\n... [truncated {len(text) - max_chars} chars] ...\n\n"
        + text[-half:]
    )


def _extract_nmap_summary(result_text: str) -> tuple[str | None, str | None]:
    host_match = re.search(r'Nmap scan report for\s+(.+)', result_text)
    host = host_match.group(1).strip() if host_match else None

    if re.search(r'All\s+\d+\s+scanned\s+ports.*ignored states', result_text, re.IGNORECASE):
        return host, 'no open ports detected'

    open_ports = re.findall(r'^(\d+)/(tcp|udp)\s+open\s+([^\s]+)', result_text, re.MULTILINE)
    if open_ports:
        ports = ', '.join(f"{port}/{proto} ({service})" for port, proto, service in open_ports[:6])
        extra = '' if len(open_ports) <= 6 else f" +{len(open_ports) - 6} more"
        return host, f"open ports: {ports}{extra}"

    if re.search(r'0 hosts up', result_text, re.IGNORECASE):
        return host, 'host did not respond as up during the scan'

    return host, None


def _tool_arg_label(arguments: dict, fallback: str = 'the requested target') -> str:
    label = str((arguments or {}).get('args') or '').strip()
    return label or fallback


def _extract_benign_empty_summary(tool_name: str, result_text: str, arguments: dict) -> str | None:
    normalized = (result_text or '').strip()
    normalized_lower = normalized.lower()
    label = _tool_arg_label(arguments)

    if tool_name == 'msf_search' and 'no results from search' in normalized_lower:
        return f"Metasploit search returned no matching modules for {label}."

    if tool_name == 'msf_run' and 'exploit completed, but no session was created' in normalized_lower:
        return f"Metasploit ran for {label}, but it did not create a session."

    if tool_name == 'searchsploit' and ('no results' in normalized_lower or 'exploits: no results' in normalized_lower):
        return f"Searchsploit returned no matching entries for {label}."

    if tool_name == 'nmap':
        host, summary = _extract_nmap_summary(normalized)
        if summary == 'no open ports detected':
            target_label = host or label
            return f"{target_label}: no open ports detected."

    if tool_name == 'rustscan' and 'no open ports found' in normalized_lower:
        return f"Rustscan found no open ports for {label}."

    if tool_name == 'masscan' and ('found 0 hosts' in normalized_lower or '0 hosts scanned' in normalized_lower):
        return f"Masscan did not identify any responsive hosts or open ports for {label}."

    if tool_name in {'amass', 'subfinder'} and (not normalized or 'no names were discovered' in normalized_lower or 'no assets were discovered' in normalized_lower):
        return f"{tool_name} did not discover any subdomains for {label}."

    if tool_name in {'gobuster', 'dirb', 'ffuf', 'wfuzz'}:
        no_result_markers = [
            'no results',
            '0 hits',
            '0 words found',
            '0 directories found',
            '0 files found',
            'no valid results',
        ]
        if not normalized or any(marker in normalized_lower for marker in no_result_markers):
            return f"{tool_name} did not find any matching paths or content for {label}."

    if tool_name == 'nikto' and ('0 host(s) tested' in normalized_lower or '0 item(s) reported' in normalized_lower):
        return f"Nikto did not report any findings for {label}."

    if tool_name == 'sqlmap' and (
        'all tested parameters do not appear to be injectable' in normalized_lower
        or 'does not seem to be injectable' in normalized_lower
        or 'no injection point found' in normalized_lower
    ):
        return f"sqlmap did not identify injectable parameters for {label}."

    if tool_name == 'wpscan' and 'wordpress not detected' in normalized_lower:
        return f"WPScan did not detect a WordPress target for {label}."

    if tool_name == 'whatweb' and (not normalized or 'unassigned' == normalized_lower):
        return f"WhatWeb did not produce a fingerprint for {label}."

    if tool_name in {'john', 'hashcat'} and (
        '0g' in normalized_lower
        or 'recovered........: 0/' in normalized_lower
        or 'no hashes loaded' in normalized_lower
    ):
        return f"{tool_name} did not recover any credentials for {label}."

    if tool_name in {'hydra', 'medusa', 'crowbar'} and (
        '0 valid password found' in normalized_lower
        or '0 valid passwords found' in normalized_lower
        or 'no valid password found' in normalized_lower
        or 'no credentials were discovered' in normalized_lower
    ):
        return f"{tool_name} did not find valid credentials for {label}."

    if tool_name == 'commix' and (
        'does not seem injectable' in normalized_lower
        or '0 injection point' in normalized_lower
        or 'no injection points found' in normalized_lower
    ):
        return f"Commix did not identify command injection for {label}."

    if tool_name in {'proxychains', 'ssh', 'netcat', 'ncat', 'tcpdump', 'aircrack-ng', 'recon-ng', 'msfconsole', 'shell', 'shell_extended', 'shell_sequence', 'shell_dangerous'} and not normalized:
        return f"{tool_name} completed successfully with no output for {label}."

    if not normalized:
        return f"{tool_name} completed successfully but returned no output for {label}."

    return None


def _can_auto_finalize_benign_empty(tool_results: list[dict]) -> bool:
    if not tool_results:
        return False

    summaries = []
    for item in tool_results:
        if item.get('exit_code', 0) != 0:
            return False
        summary = _extract_benign_empty_summary(
            item.get('tool', 'unknown'),
            item.get('result', '') or '',
            item.get('args', {}) or {},
        )
        if not summary:
            return False
        summaries.append(summary)

    return bool(summaries)


def _build_benign_empty_finalization(tool_results: list[dict]) -> str:
    summaries = []
    for item in tool_results:
        summary = _extract_benign_empty_summary(
            item.get('tool', 'unknown'),
            item.get('result', '') or '',
            item.get('args', {}) or {},
        )
        if summary:
            summaries.append(summary)

    if summaries:
        return ' '.join(summaries)

    return _build_tool_result_fallback('', tool_results)


def _build_tool_result_fallback(prompt: str, tool_results: list[dict]) -> str:
    nmap_findings = []
    generic_findings = []

    for item in tool_results:
        tool_name = item.get('tool', 'unknown')
        result_text = item.get('result', '') or ''
        exit_code = item.get('exit_code', 0)

        if tool_name == 'nmap':
            host, summary = _extract_nmap_summary(result_text)
            if summary:
                label = host or item.get('args', {}).get('args', 'target')
                nmap_findings.append(f"{label}: {summary}")
                continue

        if exit_code == 0:
            preview = result_text.strip().splitlines()
            generic_findings.append(f"{tool_name}: {preview[0] if preview else 'completed with no output'}")
        else:
            generic_findings.append(f"{tool_name}: failed ({result_text.strip() or 'no error text'})")

    if nmap_findings and all('no open ports detected' in finding for finding in nmap_findings):
        joined = '; '.join(nmap_findings)
        return (
            f"I ran the follow-up scans, but they did not reveal any open ports or exposed services. {joined}. "
            "Without reachable services, there is nothing meaningful to vulnerability-scan at the service layer yet. "
            "The next step would be broader host discovery, UDP checks, or validating whether filtering is hiding services."
        )

    findings = nmap_findings + generic_findings
    if findings:
        return "I completed the follow-up tooling. Results: " + '; '.join(findings[:8]) + "."

    return (
        "The requested tools finished successfully, but the model failed to produce a final answer. "
        "The latest tool results are available in the log and can be used to continue from here."
    )


def _format_tool_invocation_summary(tool_name: str, args: dict | None) -> str:
    payload = args or {}
    if isinstance(payload, dict):
        shell_args = payload.get('args')
        if isinstance(shell_args, str) and shell_args.strip():
            return f"{tool_name} {shell_args.strip()}"

        compact = json.dumps(payload, ensure_ascii=True)
        if compact and compact != '{}':
            return f"{tool_name} {compact}"

    return tool_name


def _build_max_turn_summary(prompt: str, tool_results: list[dict], max_iterations: int) -> str:
    last_tool = tool_results[-1] if tool_results else None
    if not last_tool:
        return (
            f"I hit the max turn limit ({max_iterations}) before producing a final answer. "
            "No completed tool result was available to summarize."
        )

    last_command = _format_tool_invocation_summary(
        str(last_tool.get('tool', 'unknown')),
        last_tool.get('args', {}) or {},
    )
    result_summary = _build_tool_result_fallback(prompt, tool_results[-8:])
    return (
        f"I hit the max turn limit ({max_iterations}) before producing a final answer. "
        f"Last command run: {last_command}. {result_summary}"
    )


def _extract_tool_info(tc) -> tuple[str, dict]:
    """Safely extract function name and arguments from a tool call (dict or object)."""
    func = getattr(tc, "function", None)
    if func is None and hasattr(tc, "get"):
        func = tc.get("function", tc)
    if func is None:
        func = tc
        
    name = getattr(func, "name", None)
    if name is None and hasattr(func, "get"):
        name = func.get("name", "unknown")
        
    args = getattr(func, "arguments", None)
    if args is None and hasattr(func, "get"):
        args = func.get("arguments", {})

    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {"args": args}
        
    if not isinstance(args, dict):
        try:
            if hasattr(args, "model_dump"):
                args = args.model_dump()
            elif hasattr(args, "dict"):
                args = args.dict()
            else:
                args = dict(args)
        except Exception:
            pass
            
    return str(name or "unknown"), (args if isinstance(args, dict) else {})


async def _maybe_summarise(
    client,
    model: str,
    messages: list[dict],
    context_window: int,
    event_callback,
) -> list[dict]:
    """
    If estimated token usage exceeds the threshold, summarise older messages.

    Strategy:
      1. Split messages into OLD (candidates for summarisation) and RECENT
         (kept intact — the last `_KEEP_RECENT` messages).
      2. Ask the LLM to produce a concise summary of the OLD portion.
      3. Replace OLD messages with a single system message containing the summary.

    Returns the (possibly compacted) messages list.
    """
    est_tokens = _estimate_tokens(messages)
    budget = int(context_window * _SUMMARISE_THRESHOLD)

    if est_tokens <= budget or len(messages) <= _KEEP_RECENT + 1:
        return messages  # no action needed

    _emit(event_callback, "status", {
        "message": f"Context ~{est_tokens} tokens (budget {context_window}) — summarizing older history …"
    })

    # Split: keep the most recent messages intact
    old_messages = messages[:-_KEEP_RECENT]
    recent_messages = messages[-_KEEP_RECENT:]

    # Build a text dump of old messages for summarisation
    history_text = ""
    for msg in old_messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            history_text += f"[{role}]: {content[:2000]}\n\n"
        tcs = msg.get("tool_calls")
        if tcs:
            for tc in tcs:
                name, args = _extract_tool_info(tc)
                try:
                    args_str = json.dumps(args)
                except Exception:
                    args_str = str(args)
                history_text += f"[tool_call]: {name}({args_str})\n"

    # Ask the LLM to summarise
    try:
        summary_response = await asyncio.to_thread(
            client.chat,
            model=model,
            messages=[
                {"role": "system", "content": _SUMMARISE_SYSTEM_PROMPT},
                {"role": "user", "content": f"Conversation to summarise:\n\n{history_text}"},
            ],
        )
        summary_msg = summary_response.get("message", summary_response)
        summary_text = summary_msg.get("content", "").strip()
    except Exception as exc:
        # If summarisation fails, fall back to a naive truncation
        summary_text = history_text[:2000] + "\n[truncated]"
        _emit(event_callback, "status", {
            "message": f"Summarisation LLM call failed ({exc}), using truncated history."
        })

    if not summary_text:
        summary_text = "(summary unavailable)"

    new_tokens = _estimate_tokens([{"content": summary_text}]) + _estimate_tokens(recent_messages)
    _emit(event_callback, "status", {
        "message": f"Summarised {len(old_messages)} old messages → ~{_estimate_tokens([{'content': summary_text}])} tokens. New total ~{new_tokens} tokens."
    })

    # Rebuild: summary + recent
    compacted = [
        {"role": "system", "content": f"[Conversation summary so far]\n{summary_text}"},
        *recent_messages,
    ]
    return compacted


def _emit_chat_cancelled(event_callback):
    _emit(event_callback, "status", {"message": "Chat cancelled by user."})
    _emit(event_callback, "chat_done", {"message": "Prompt cancelled. Ready for next prompt."})


def _tool_timeout_control_dir(run_id: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "runs", run_id, _TIMEOUT_CONTROL_DIRNAME)


def _tool_timeout_request_path(run_id: str) -> str:
    return os.path.join(_tool_timeout_control_dir(run_id), _TIMEOUT_REQUEST_FILENAME)


def _tool_timeout_response_path(run_id: str) -> str:
    return os.path.join(_tool_timeout_control_dir(run_id), _TIMEOUT_RESPONSE_FILENAME)


def _load_enabled_tool_guidance(tool_names: list[str]) -> str:
    root_dir = Path(__file__).resolve().parent
    selected_docs: list[tuple[str, Path]] = []
    seen_paths = set()

    for name in tool_names or []:
        rel_path = _TOOL_DOC_MAP.get(str(name))
        if not rel_path:
            continue
        path = (root_dir / rel_path).resolve()
        if path in seen_paths:
            continue
        seen_paths.add(path)
        selected_docs.append((str(name), path))

    if not selected_docs:
        return ""

    sections: list[str] = []
    total = 0
    for tool_name, path in selected_docs:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue

        snippet = text.strip()
        if not snippet:
            continue
        if len(snippet) > _TOOL_DOC_MAX_CHARS_PER_DOC:
            snippet = snippet[:_TOOL_DOC_MAX_CHARS_PER_DOC].rstrip() + "\n\n[truncated]"

        block = (
            f"### Tool: {tool_name}\n"
            f"Source: {path.relative_to(root_dir)}\n\n"
            f"{snippet}\n"
        )
        if total + len(block) > _TOOL_DOC_MAX_TOTAL_CHARS:
            break
        sections.append(block)
        total += len(block)

    if not sections:
        return ""

    return (
        "Tool usage guides for enabled tools are provided below. "
        "Treat them as operational constraints and preferred usage patterns.\n\n"
        + "\n\n".join(sections)
    )


def _load_tool_timeout_request(run_id: str) -> dict | None:
    path = _tool_timeout_request_path(run_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            payload = json.load(f)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


# ---------------------------------------------------------------------------
# MCPSession — persistent connection with chat loop
# ---------------------------------------------------------------------------

class MCPSession:
    """
    Long-lived MCP session that holds the server connection open and supports
    multiple chat turns with full conversation continuity.

    Usage:
        session = MCPSession(...)
        tool_names = await session.start()
        await session.chat("scan 192.168.1.0/24")
        await session.chat("now check for open web ports")
        await session.stop()
    """

    def __init__(
        self,
        *,
        ollama_url: str,
        llm_provider: str = "ollama_direct",
        api_key: str | None = None,
        api_token: str | None = None,
        ssl_verify: bool = True,
        model: str,
        server_command: str,
        run_id: str | None = None,
        event_callback=None,
        context_window: int = DEFAULT_CONTEXT_WINDOW,
        max_turns: int = DEFAULT_MAX_TURNS,
        network_policy: dict | None = None,
        enabled_tool_guides: list[str] | None = None,
    ):
        self.llm_provider = str(llm_provider or "ollama_direct").strip() or "ollama_direct"
        self.ollama_url = _normalize_provider_base_url(self.llm_provider, ollama_url)
        self.api_key = str(api_key or api_token or "").strip() or None
        self.ssl_verify = bool(ssl_verify)
        self.model = model
        self.server_command = server_command
        self.context_window = context_window
        self.max_turns = max_turns
        self.event_callback = event_callback
        self.run_id = run_id or make_run_id("agent")
        self.network_policy = _normalize_network_policy(network_policy)
        self.enabled_tool_guides = list(enabled_tool_guides) if isinstance(enabled_tool_guides, list) else None

        # Internals
        self._exit_stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._client = None
        self._logger: SessionLogger | None = None
        self._started = False
        self._chat_lock = asyncio.Lock()
        self._pending_post_tool_reply = None
        self._pending_dangerous_tool_approval = None
        self._pending_tool_timeout_decision = None
        self._active_interactive_sessions = set()
        self._enabled_tool_guidance: str = ""
        
        # Initialize with a strong system prompt to ensure tools aren't sent to the background
        allow_text = ", ".join(self.network_policy['allow'])
        disallow_text = ", ".join(self.network_policy['disallow']) if self.network_policy['disallow'] else '(none)'
        self.messages: list[dict] = [
            {
                "role": "system",
                "content": self._build_initial_system_prompt(allow_text, disallow_text)
            }
        ]
        
        self.tool_names: list[str] = []
        self._ollama_tools: list[dict] = []
        self._ollama_tools_minimal: list[dict] = []
        self._anthropic_tools: list[dict] = []
        self._anthropic_tools_minimal: list[dict] = []
        self._model_max_ctx: int = context_window

    def _build_initial_system_prompt(self, allow_text: str, disallow_text: str) -> str:
        prompt = (
            "You are a network security assistant. You must wait for all tools to finish executing. "
            "NEVER attempt to run tools in the background (e.g., using `&` or `nohup`). "
            "You MUST allow the system to execute the tool synchronously so you can read and analyze the output before replying. "
            "The shell_dangerous tool requires explicit user verification before execution; do not try to bypass this gate "
            "with less privileged tools like `shell_extended` if you need to run complex, write-enabled, or blocked commands. "
            "Use `shell_dangerous` when necessary and expect an approval gate. If a tool reports that an interactive session "
            "was preserved with an id such as `isess-001`, continue through the dedicated interactive_session_list, "
            "interactive_session_read, interactive_session_write, and interactive_session_close tools instead of rerunning the exploit."
        )
        
        prompt += f" You must obey the target access policy without exception. Allowed targets: {allow_text}. Disallowed targets: {disallow_text}. If a target is out of scope, do not attempt the action."

        if self._enabled_tool_guidance:
            prompt += "\n\n" + self._enabled_tool_guidance
        
        if self._active_interactive_sessions:
            active_sessions_str = ", ".join(sorted(self._active_interactive_sessions))
            prompt += (
                f"\n\nCURRENTLY ACTIVE INTERACTIVE SESSIONS: [{active_sessions_str}]. "
                "You MUST use `interactive_session_write` to interact with these existing sessions "
                "instead of running exploit tools to recreate them."
            )
            
        return prompt

    def _client_headers(self) -> dict | None:
        headers = _provider_headers(self.llm_provider, self.api_key)
        return headers or None

    def _normalize_scope(self, scope: str | None) -> str:
        candidate = str(scope or "medium").strip().lower()
        allowed = {"broad", "medium-broad", "medium", "medium-narrow", "narrow"}
        return candidate if candidate in allowed else "medium"

    def _normalize_urgency(self, urgency: str | None) -> str:
        candidate = str(urgency or "balanced").strip().lower()
        allowed = {"stealthy", "methodical", "balanced", "fast", "speed"}
        return candidate if candidate in allowed else "balanced"

    def _scope_instruction(self, scope: str | None) -> str:
        normalized = self._normalize_scope(scope)
        guidance = {
            "broad": (
                "CRITICAL INSTRUCTION - BROAD SCOPE: You MUST favor wide network coverage over deep exploitation. "
                "You are required to scan entire subnets (e.g., /24) and enumerate all adjacent services before drilling down. "
                "Do NOT fixate on a single host or vulnerability. Prioritize breadth, discovery, and high-level triage."
            ),
            "medium-broad": (
                "CRITICAL INSTRUCTION - MEDIUM-BROAD SCOPE: You MUST cover adjacent attack surfaces and enumerate enough "
                "to avoid blind spots. Do not stop at the first plausible lead if nearby surfaces remain cheap to check. "
                "Scan multiple related targets before deciding which one to exploit."
            ),
            "medium": (
                "INSTRUCTION - BALANCED SCOPE: Combine sensible surface coverage with targeted follow-through. "
                "Explore enough to avoid obvious blind spots, then go deeper on the strongest result."
            ),
            "medium-narrow": (
                "CRITICAL INSTRUCTION - MEDIUM-NARROW SCOPE: You MUST stay tightly focused on the most promising paths. "
                "Do NOT perform wide subnet scans or full-port sweeps unless explicitly asked. Minimize side exploration."
            ),
            "narrow": (
                "CRITICAL INSTRUCTION - NARROW SCOPE: You MUST focus ONLY on the specific target, port, or vulnerability at hand. "
                "ABSOLUTELY NO broad enumeration, subnet scanning, or side-exploration is allowed. Stick to a single path of exploitation."
            ),
        }
        return (
            f"Scope mode for this user request: {normalized}. "
            f"{guidance[normalized]} Treat scope as an execution directive for this turn: it should materially change how much "
            "surface you cover before replying. Keep obeying the access policy and tool safety constraints."
        )

    def _urgency_instruction(self, urgency: str | None) -> str:
        normalized = self._normalize_urgency(urgency)
        guidance = {
            "stealthy": (
                "CRITICAL INSTRUCTION - STEALTHY URGENCY: You MUST operate with extreme caution and low noise. "
                "You are FORBIDDEN from using aggressive scanning profiles. You MUST use flags like -T1, -T2, or add "
                "delays to your commands to avoid detection. Do not batch commands heavily."
            ),
            "methodical": (
                "CRITICAL INSTRUCTION - METHODICAL URGENCY: Favor thorough, step-by-step validation over raw speed. "
                "Do not use aggressive timing flags. Keep concurrency low and deliberately sequence your work."
            ),
            "balanced": (
                "INSTRUCTION - BALANCED URGENCY: Trade off stealth, depth, and speed pragmatically. "
                "Use normal timing (e.g., -T3 for nmap) and normal validation unless the situation clearly calls for something else."
            ),
            "fast": (
                "CRITICAL INSTRUCTION - FAST URGENCY: You MUST bias toward quicker feedback. "
                "Use assertive timing flags (e.g., -T4 for nmap), broader batching, and higher parallelism. "
                "Do not waste time on slow, exhaustive validation."
            ),
            "speed": (
                "CRITICAL INSTRUCTION - MAX SPEED URGENCY: You MUST optimize for absolute maximum speed. "
                "You are REQUIRED to use aggressive timing flags (e.g., -T5, --min-rate, --max-retries=1 for nmap). "
                "Accept heavy noise and high unreliability to get immediate results. NEVER use slow-down or delay options."
            ),
        }
        return (
            f"Urgency mode for this user request: {normalized}. "
            f"{guidance[normalized]} Let this influence choices such as scan timing, concurrency, batching, and how much time to spend "
            "going deep before returning progress. Treat urgency as an execution directive for this turn, not just a stylistic hint, "
            "while still obeying the access policy and tool safety constraints."
        )

    def _turn_control_directive(self, scope: str | None, urgency: str | None) -> str:
        directives = []
        if scope is not None:
            directives.append(self._scope_instruction(scope))
        if urgency is not None:
            directives.append(self._urgency_instruction(urgency))
        if not directives:
            return ""
        return (
            "Turn-specific execution controls follow. These controls are mandatory for this turn and must materially affect "
            "tool choice, command shape, enumeration breadth, scan timing, batching, parallelism, and stopping criteria. "
            "Do not acknowledge the controls explicitly unless the user asks; apply them in the work itself.\n\n"
            + "\n\n".join(directives)
        )

    def _messages_for_turn(self, scope: str | None, urgency: str | None) -> list[dict]:
        if not self.messages:
            return []
        turn_directive = self._turn_control_directive(scope, urgency)
        if self.messages[0].get("role") == "system":
            if not turn_directive:
                return list(self.messages)
            merged_system = dict(self.messages[0])
            merged_system["content"] = f"{self.messages[0].get('content', '')}\n\n{turn_directive}"
            return [merged_system, *self.messages[1:]]
        if not turn_directive:
            return list(self.messages)
        return [{"role": "system", "content": turn_directive}, *self.messages]

    async def call_tool_direct(self, name: str, arguments: dict):
        """Execute an MCP tool directly (e.g., from manual UI interaction) without a model."""
        if not self._session:
            return {"error": "No active MCP session"}
        
        try:
            result = await self._session.call_tool(name, arguments)
            result_text = ""
            if result.content:
                result_text = "\n".join(
                    getattr(c, "text", str(c))
                    for c in result.content
                )
            return {
                "success": not getattr(result, "isError", False),
                "content": result_text
            }
        except Exception as e:
            return {"error": str(e), "success": False}

    async def _retry_empty_reply_after_tools(self, prompt: str, tool_results: list[dict]) -> str | None:
        _emit(self.event_callback, "status", {
            "message": "Model returned an empty post-tool reply; retrying once without tools for a final answer …"
        })

        recovery_prompt = (
            "Provide the final user-facing answer based only on these completed tool results. "
            "Do not call tools. Be concise and explicit. If scans show no open ports or exposed services, say that clearly and explain that vulnerability scanning cannot proceed meaningfully without reachable services.\n\n"
            f"Original user request:\n{prompt}\n\n"
            "Completed tool results:\n"
            f"{json.dumps(tool_results[-8:], ensure_ascii=True)}"
        )

        try:
            response = await asyncio.to_thread(
                self._client.chat,
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a network security assistant writing the final answer after tools have already completed. Do not call tools."
                    },
                    {
                        "role": "user",
                        "content": recovery_prompt,
                    },
                ],
                options={"num_ctx": self.context_window},
            )
            message = response.get("message", response)
            content = message.get("content", getattr(message, "content", "")) or ""
            if content.strip():
                return content.strip()
        except Exception as exc:
            _emit(self.event_callback, "status", {
                "message": f"Retry call failed ({exc})."
            })

        return None

    async def _repair_litellm_tool_reply(self, prompt: str, malformed_content: str, scope: str | None = None, urgency: str | None = None) -> dict | None:
        _emit(self.event_callback, "status", {
            "message": f"{_provider_display_name(self.llm_provider)} returned a malformed tool-planning reply; retrying once with stricter tool-calling instructions …"
        })

        repair_messages = [
            *self._messages_for_turn(scope, urgency),
            {
                "role": "system",
                "content": (
                    "You are in tool-calling mode. If a tool is needed, reply with tool_calls only and no explanatory prose. "
                    "Do not describe the intended tool call in natural language. Do not emit partial JSON. "
                    "If no tool is needed, reply with a short direct answer."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Your previous reply was malformed and could not be executed. "
                    "Re-answer the original user request now using a valid tool call if needed.\n\n"
                    f"Original request:\n{prompt}\n\n"
                    f"Malformed reply:\n{malformed_content}"
                ),
            },
        ]

        try:
            return await asyncio.to_thread(
                self._client.chat,
                model=self.model,
                messages=repair_messages,
                tools=(
                    self._anthropic_tools_minimal if _normalize_provider_name(self.llm_provider) == "claude" else self._ollama_tools_minimal
                ) or (
                    self._anthropic_tools if _normalize_provider_name(self.llm_provider) == "claude" else self._ollama_tools
                ) or None,
                options={"num_ctx": self.context_window},
            )
        except Exception as exc:
            _emit(self.event_callback, "status", {
                "message": f"{_provider_display_name(self.llm_provider)} malformed-reply retry failed ({exc})."
            })
            return None

    async def _recover_litellm_tool_plan(self, prompt: str, malformed_content: str, scope: str | None = None, urgency: str | None = None) -> dict | None:
        tool_catalog = []
        for tool in self._ollama_tools_minimal or self._ollama_tools:
            function = (tool or {}).get("function") or {}
            tool_catalog.append({
                "name": function.get("name"),
                "description": function.get("description"),
                "parameters": function.get("parameters"),
            })

        _emit(self.event_callback, "status", {
            "message": f"{_provider_display_name(self.llm_provider)} did not return usable native tool calls; attempting JSON tool-plan recovery …"
        })

        try:
            response = await asyncio.to_thread(
                self._client.chat,
                model=self.model,
                messages=[
                    *self._messages_for_turn(scope, urgency),
                    {
                        "role": "system",
                        "content": (
                            "Choose the next action for the agent. Output JSON only. "
                            "If a tool is needed, output exactly {\"tool\": \"<tool_name>\", \"arguments\": {...}}. "
                            "If no tool is needed, output exactly {\"respond\": \"<short answer>\"}. "
                            "Do not include markdown, commentary, or any extra text."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Original user request:\n{prompt}\n\n"
                            f"Available tools:\n{json.dumps(tool_catalog, ensure_ascii=True)}\n\n"
                            f"Previous malformed reply:\n{malformed_content or '(empty)'}"
                        ),
                    },
                ],
                options={"num_ctx": self.context_window, "tool_choice": False},
            )
        except Exception as exc:
            _emit(self.event_callback, "status", {
                "message": f"{_provider_display_name(self.llm_provider)} JSON tool-plan recovery failed ({exc})."
            })
            return None

        message = response.get("message", response)
        content = message.get("content", getattr(message, "content", "")) or ""
        payload = _extract_json_object(content)
        normalized = _normalize_litellm_tool_plan(payload or {}, self.tool_names)

        if self._logger and isinstance(response, dict) and response.get("raw") is not None:
            try:
                self._logger.log_artifact(
                    "litellm_json_tool_plan_raw.txt",
                    json.dumps(response.get("raw"), indent=2, ensure_ascii=True),
                )
            except Exception:
                pass

        if not normalized:
            return None

        return {"message": normalized, "raw": response.get("raw") if isinstance(response, dict) else None}

    async def _prompt_post_tool_reply_decision(self, prompt: str, tool_results: list[dict], cancel_event: asyncio.Event | None) -> str:
        loop = asyncio.get_running_loop()
        decision_future = loop.create_future()
        self._pending_post_tool_reply = {
            "future": decision_future,
            "loop": loop,
            "prompt": prompt,
            "tool_results": tool_results,
        }

        _emit(self.event_callback, "status", {
            "message": "Model still failed to produce a final reply after an automatic retry. Waiting for user decision: retry again or cancel and restore."
        })
        _emit(self.event_callback, "post_tool_reply_decision", {
            "message": "The model completed the tool calls, returned an empty final reply, and then failed one automatic final-answer retry. Retry once more, or cancel and restore to the state before the failed model response.",
            "options": ["retry", "cancel"],
        })

        try:
            while True:
                if cancel_event and cancel_event.is_set():
                    return "cancel"
                try:
                    return await asyncio.wait_for(asyncio.shield(decision_future), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
        finally:
            self._pending_post_tool_reply = None

    async def _prompt_dangerous_tool_approval(self, tool_name: str, tool_args: dict, cancel_event: asyncio.Event | None) -> str:
        loop = asyncio.get_running_loop()
        decision_future = loop.create_future()
        command_text = (tool_args or {}).get("args", "") if isinstance(tool_args, dict) else str(tool_args)
        self._pending_dangerous_tool_approval = {
            "future": decision_future,
            "loop": loop,
            "tool": tool_name,
            "args": tool_args,
            "command": command_text,
        }

        is_exit_cmd = (
            tool_name == "interactive_session_write" 
            and isinstance(tool_args, dict)
            and tool_args.get("input", "").strip().lower() in ["exit", "quit", "exit\n", "quit\n"]
        )

        if tool_name == "interactive_session_close" or is_exit_cmd:
            msg = "The model requested to kill/close an interactive session. Review the request below and approve or cancel execution."
        else:
            msg = "The model requested a dangerous shell command. Review the command below and approve or cancel execution."

        _emit(self.event_callback, "status", {
            "message": f"User approval required before executing {tool_name}."
        })
        _emit(self.event_callback, "dangerous_tool_approval", {
            "tool": tool_name,
            "args": tool_args,
            "command": command_text,
            "message": msg,
            "options": ["approve", "cancel"],
        })

        try:
            while True:
                if cancel_event and cancel_event.is_set():
                    return "cancel"
                try:
                    return await asyncio.wait_for(asyncio.shield(decision_future), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
        finally:
            self._pending_dangerous_tool_approval = None

    def resolve_post_tool_reply_decision(self, action: str) -> bool:
        if action not in {"retry", "cancel"}:
            return False

        pending = self._pending_post_tool_reply
        if not pending:
            return False

        loop = pending.get("loop")
        future = pending.get("future")
        if not loop or not future:
            return False

        def _resolve():
            if not future.done():
                future.set_result(action)

        loop.call_soon_threadsafe(_resolve)
        return True

    def resolve_dangerous_tool_approval(self, action: str) -> bool:
        if action not in {"approve", "cancel"}:
            return False

        pending = self._pending_dangerous_tool_approval
        if not pending:
            return False

        loop = pending.get("loop")
        future = pending.get("future")
        if not loop or not future:
            return False

        if self._logger:
            command_text = pending.get("command", "")
            tool_name = pending.get("tool", "shell_dangerous")
            decision_text = (
                f"Approved dangerous command for {tool_name}: {command_text}"
                if action == "approve"
                else f"Denied dangerous command for {tool_name}: {command_text}"
            )
            self._logger.log_human_decision(decision_text, category="dangerous_tool_approval")

        def _resolve():
            if not future.done():
                future.set_result(action)

        loop.call_soon_threadsafe(_resolve)
        return True

    async def _watch_tool_timeout_requests(self, active_tool_name: str, active_tool_args: dict, call_task: asyncio.Task):
        seen_request_id = None

        try:
            while not call_task.done():
                request = _load_tool_timeout_request(self.run_id)
                request_id = str((request or {}).get("request_id") or "")
                if request and request_id and request_id != seen_request_id:
                    seen_request_id = request_id
                    checkpoint_index = int(request.get("checkpoint_index") or 1)
                    timeout_seconds = int(request.get("timeout_seconds") or 0)
                    trigger = str(request.get("trigger") or "timeout").strip().lower()
                    elapsed_seconds = int(request.get("elapsed_seconds") or 0)
                    tool_name = str(request.get("tool") or active_tool_name)
                    command = str(request.get("command") or (active_tool_args or {}).get("args") or "")
                    self._pending_tool_timeout_decision = dict(request)

                    checkpoint_label = "idle-output checkpoint" if trigger == "idle" else "timeout checkpoint"
                    if elapsed_seconds > 0:
                        status_message = (
                            f"{tool_name} reached {checkpoint_label} {checkpoint_index} "
                            f"after {elapsed_seconds} seconds. Waiting for user decision: wait or kill."
                        )
                    else:
                        status_message = (
                            f"{tool_name} reached {checkpoint_label} {checkpoint_index} "
                            f"(interval: {timeout_seconds} seconds). Waiting for user decision: wait or kill."
                        )

                    _emit(self.event_callback, "status", {
                        "message": status_message
                    })

                    if trigger == "idle":
                        detail_message = (
                            f"{tool_name} has shown no new output for {timeout_seconds} seconds "
                            f"(elapsed: {max(0, elapsed_seconds)} seconds). "
                            "Wait keeps the process running. Kill terminates it and returns any partial output."
                        )
                    else:
                        detail_message = (
                            f"{tool_name} has been running for {timeout_seconds * checkpoint_index} seconds. "
                            "Wait keeps the process running until the next timeout checkpoint. Kill terminates it and returns any partial output."
                        )

                    _emit(self.event_callback, "tool_timeout_decision", {
                        "tool": tool_name,
                        "args": request.get("args") or active_tool_args,
                        "command": command,
                        "timeout_seconds": timeout_seconds,
                        "checkpoint_index": checkpoint_index,
                        "trigger": trigger,
                        "elapsed_seconds": elapsed_seconds,
                        "message": detail_message,
                        "options": ["wait", "kill"],
                    })

                await asyncio.sleep(0.25)
        finally:
            self._pending_tool_timeout_decision = None

    def resolve_tool_timeout_decision(self, action: str) -> bool:
        if action not in {"wait", "kill"}:
            return False

        pending = self._pending_tool_timeout_decision
        if not pending:
            return False

        request_id = str(pending.get("request_id") or "")
        if not request_id:
            return False

        response_path = _tool_timeout_response_path(self.run_id)
        os.makedirs(os.path.dirname(response_path), exist_ok=True)
        with open(response_path, "w") as f:
            json.dump({
                "request_id": request_id,
                "action": action,
                "timestamp": time.time(),
            }, f, indent=2)

        if self._logger:
            tool_name = str(pending.get("tool") or "tool")
            command_text = str(pending.get("command") or "")
            self._logger.log_human_decision(
                (
                    f"Chose to wait for {tool_name} after timeout checkpoint: {command_text}"
                    if action == "wait"
                    else f"Chose to kill {tool_name} after timeout checkpoint: {command_text}"
                ),
                category="tool_timeout_decision",
            )

        self._pending_tool_timeout_decision = None
        return True

    async def start(self) -> list[str]:
        """
        Launch the MCP server, connect, and discover tools.
        Returns a list of available tool names.
        """
        if _normalize_provider_name(self.llm_provider) == "ollama_direct" and not _HAVE_OLLAMA:
            _emit(self.event_callback, "error", {"message": "ollama Python library is not installed."})
            raise RuntimeError("ollama library not installed")

        self._logger = SessionLogger(
            run_id=self.run_id,
            metadata={
                "server_type": "agent",
                "model": self.model,
                "ollama_url": self.ollama_url,
                "llm_provider": self.llm_provider,
                "ssl_verify": self.ssl_verify,
                "llm_auth_enabled": bool(self.api_key),
                "context_window": self.context_window,
                "max_turns": self.max_turns,
                "network_policy": self.network_policy,
            },
            event_callback=self.event_callback,
        )

        _emit(self.event_callback, "status", {
            "message": f"Starting session {self.run_id} (context: {self.context_window} tokens, max turns: {self.max_turns}) …"
        })

        # Parse server command
        cmd_parts = shlex.split(self.server_command)
        server_params = StdioServerParameters(
            command=cmd_parts[0],
            args=cmd_parts[1:],
            env={
                **os.environ,
                "MCP_CURRENT_RUN_ID": self.run_id,
                "MCP_MODEL": self.model,
                "MCP_OLLAMA_URL": self.ollama_url,
                "MCP_NETWORK_POLICY": json.dumps(self.network_policy),
            },
        )

        # Configure model client
        provider_name = _normalize_provider_name(self.llm_provider)
        if provider_name in {"litellm", "openai"}:
            self._client = _LiteLLMClient(
                host=self.ollama_url,
                headers=self._client_headers() or {},
                verify=self.ssl_verify,
            )
        elif provider_name == "claude":
            self._client = _AnthropicClient(
                host=self.ollama_url,
                headers=self._client_headers() or {},
                verify=self.ssl_verify,
            )
        else:
            self._client = _ollama_lib.Client(
                host=self.ollama_url,
                headers=self._client_headers(),
                verify=self.ssl_verify,
            )

        # Discover model's actual context length
        try:
            model_info = await asyncio.to_thread(self._client.show, self.model)
            mi = model_info if isinstance(model_info, dict) else {}
            params = mi.get("model_info", {}) or {}
            for key, val in params.items():
                if "context_length" in key:
                    self._model_max_ctx = int(val)
                    break
            _emit(self.event_callback, "status", {
                "message": f"Model {self.model} context length: {self._model_max_ctx} tokens"
            })
        except Exception:
            _emit(self.event_callback, "status", {
                "message": f"Could not query model context size, using {self.context_window} as limit."
            })

        _emit(self.event_callback, "context_usage", {
            "used": 0,
            "budget": self.context_window,
            "model_max": self._model_max_ctx,
        })

        # Connect to MCP server
        self._exit_stack = AsyncExitStack()
        _emit(self.event_callback, "status", {"message": "Connecting to MCP server …"})

        stdio_transport = await self._exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        read_stream, write_stream = stdio_transport
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()

        # Discover tools
        tools_result = await self._session.list_tools()
        mcp_tools = tools_result.tools
        self._ollama_tools = [_mcp_tool_to_ollama(t) for t in mcp_tools]
        self._ollama_tools_minimal = [_mcp_tool_to_ollama_minimal(t) for t in mcp_tools]
        self._anthropic_tools = [_mcp_tool_to_anthropic(t) for t in mcp_tools]
        self._anthropic_tools_minimal = [_mcp_tool_to_anthropic_minimal(t) for t in mcp_tools]
        self.tool_names = [t.name for t in mcp_tools]
        if self.enabled_tool_guides is None:
            guidance_tools = list(self.tool_names)
        else:
            enabled_set = {str(name).strip() for name in self.enabled_tool_guides if str(name).strip()}
            guidance_tools = [name for name in self.tool_names if name in enabled_set]

        self._enabled_tool_guidance = _load_enabled_tool_guidance(guidance_tools)

        allow_text = ", ".join(self.network_policy["allow"])
        disallow_text = ", ".join(self.network_policy["disallow"]) if self.network_policy["disallow"] else "(none)"
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0]["content"] = self._build_initial_system_prompt(allow_text, disallow_text)

        if self._logger:
            self._logger.update_metadata({
                "available_tools": self.tool_names,
                "available_tool_count": len(self.tool_names),
                "max_turns": self.max_turns,
            })

        if not self.tool_names:
            _emit(self.event_callback, "error", {
                "message": "MCP server started but exposed 0 tools. Configure at least one Kali tool before starting the session."
            })
            raise RuntimeError("MCP server exposed 0 tools")

        _emit(self.event_callback, "status", {
            "message": f"MCP server ready — {len(mcp_tools)} tool(s): {', '.join(self.tool_names)}"
        })
        _emit(self.event_callback, "service_started", {
            "tools": self.tool_names,
            "run_id": self.run_id,
        })

        self._started = True
        return self.tool_names

    async def chat(self, prompt: str, cancel_event: asyncio.Event | None = None, scope: str | None = None, urgency: str | None = None):
        """
        Send a user prompt into the running session. Runs the full agent loop
        (LLM → tool calls → LLM … until text-only response), then returns.

        The conversation history carries over between calls.
        """
        if not self._started:
            _emit(self.event_callback, "error", {"message": "Session not started. Call start() first."})
            return

        # Serialise chat calls so two prompts don't overlap
        async with self._chat_lock:
            try:
                await self._run_agent_loop(prompt, cancel_event, scope=scope, urgency=urgency)
            except asyncio.CancelledError:
                # Top level task was aborted violently, cleanly exit
                if cancel_event:
                    cancel_event.set()
                _emit_chat_cancelled(self.event_callback)
            except Exception as e:
                if _is_transient_transport_error(e):
                    _emit(self.event_callback, "error", {
                        "message": "Connection to the LLM provider was reset mid-request. Please retry the prompt; if this repeats, verify the model server is healthy and reachable."
                    })
                else:
                    _emit(self.event_callback, "error", {
                        "message": "The session hit an internal runtime error. Check server logs for details."
                    })
                print(f"Crash in agent loop: {type(e).__name__}: {e}")
                traceback.print_exc()

    async def _chat_with_transient_retry(self, *, messages: list[dict], tools, options: dict, turn_label: str):
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            try:
                return await asyncio.to_thread(
                    self._client.chat,
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    options=options,
                )
            except Exception as exc:
                if attempt >= max_attempts or not _is_transient_transport_error(exc):
                    raise

                delay_seconds = 0.8 * attempt
                _emit(self.event_callback, "status", {
                    "message": f"Transient LLM connection issue during {turn_label}; retrying in {delay_seconds:.1f}s (attempt {attempt + 1}/{max_attempts}) …"
                })
                await asyncio.sleep(delay_seconds)

    async def _run_agent_loop(self, prompt: str, cancel_event: asyncio.Event | None, scope: str | None = None, urgency: str | None = None):
        """Core agent loop for a single chat turn."""
        self._logger.log_prompt(prompt)
        self.messages.append({"role": "user", "content": prompt})
        turn_tool_results: list[dict] = []
        provider_name = _normalize_provider_name(self.llm_provider)

        max_iterations = self.max_turns
        for iteration in range(max_iterations):
            if cancel_event and cancel_event.is_set():
                _emit_chat_cancelled(self.event_callback)
                return

            # Context management: summarise if needed
            self.messages = await _maybe_summarise(
                self._client, self.model, self.messages,
                self.context_window, self.event_callback,
            )

            # Emit context usage
            est = _estimate_tokens(self.messages)
            _emit(self.event_callback, "context_usage", {
                "used": est,
                "budget": self.context_window,
                "model_max": self._model_max_ctx,
            })

            turn_messages = self._messages_for_turn(scope, urgency)
            active_scope = self._normalize_scope(scope) if scope is not None else None
            active_urgency = self._normalize_urgency(urgency) if urgency is not None else None
            if active_scope or active_urgency:
                controls_summary = []
                if active_scope:
                    controls_summary.append(f"scope={active_scope}")
                if active_urgency:
                    controls_summary.append(f"urgency={active_urgency}")
                _emit(self.event_callback, "status", {
                    "message": f"Applying prompt controls for this turn: {', '.join(controls_summary)}."
                })

            # Call Ollama
            _emit(self.event_callback, "status", {
                "message": f"Calling {self.model} (turn {iteration + 1}) …"
            })
            try:
                response = await self._chat_with_transient_retry(
                    messages=turn_messages,
                    tools=(self._anthropic_tools if provider_name == "claude" else self._ollama_tools) or None,
                    options={"num_ctx": self.context_window},
                    turn_label=f"turn {iteration + 1}",
                )
            except Exception as exc:
                if self._ollama_tools and self._ollama_tools_minimal and _is_xml_schema_error(exc):
                    _emit(self.event_callback, "status", {
                        "message": "Model hit Ollama XML tool-schema bug; retrying with simplified tool metadata …"
                    })
                    response = await self._chat_with_transient_retry(
                        messages=turn_messages,
                        tools=self._ollama_tools_minimal,
                        options={"num_ctx": self.context_window},
                        turn_label=f"turn {iteration + 1} (simplified tools)",
                    )
                elif (
                    provider_name in {"litellm", "openai", "claude"}
                    and ((self._anthropic_tools if provider_name == "claude" else self._ollama_tools))
                    and ((self._anthropic_tools_minimal if provider_name == "claude" else self._ollama_tools_minimal))
                    and _is_litellm_retryable_tool_error(exc)
                ):
                    if self._logger:
                        error_body = _http_error_response_text(exc).strip()
                        if error_body:
                            try:
                                self._logger.log_artifact(
                                    f"litellm_http_error_turn_{iteration + 1}.txt",
                                    error_body,
                                )
                            except Exception:
                                pass

                    _emit(self.event_callback, "status", {
                        "message": f"{_provider_display_name(self.llm_provider)} rejected the initial tool request; retrying with simplified tool metadata …"
                    })
                    response = await self._chat_with_transient_retry(
                        messages=turn_messages,
                        tools=(self._anthropic_tools_minimal if provider_name == "claude" else self._ollama_tools_minimal),
                        options={"num_ctx": self.context_window, "tool_choice": False},
                        turn_label=f"turn {iteration + 1} (provider fallback)",
                    )
                else:
                    raise

            # Parse original message output
            original_msg = response.get("message", response)
            content = original_msg.get("content", getattr(original_msg, "content", "")) or ""
            tool_calls = original_msg.get("tool_calls", getattr(original_msg, "tool_calls", None))

            if (
                provider_name in {"litellm", "openai", "claude"}
                and self.tool_names
                and not turn_tool_results
                and not tool_calls
                and _looks_like_malformed_tool_planning(content)
            ):
                if self._logger and isinstance(response, dict) and response.get("raw") is not None:
                    try:
                        self._logger.log_artifact(
                            f"litellm_malformed_turn_{iteration + 1}.txt",
                            json.dumps(response.get("raw"), indent=2, ensure_ascii=True),
                        )
                    except Exception:
                        pass

                repaired_response = await self._repair_litellm_tool_reply(prompt, content, scope=scope, urgency=urgency)
                if repaired_response:
                    response = repaired_response
                    original_msg = response.get("message", response)
                    content = original_msg.get("content", getattr(original_msg, "content", "")) or ""
                    tool_calls = original_msg.get("tool_calls", getattr(original_msg, "tool_calls", None))

                if not tool_calls and _looks_like_malformed_tool_planning(content):
                    recovered_response = await self._recover_litellm_tool_plan(prompt, content, scope=scope, urgency=urgency)
                    if recovered_response:
                        response = recovered_response
                        original_msg = response.get("message", response)
                        content = original_msg.get("content", getattr(original_msg, "content", "")) or ""
                        tool_calls = original_msg.get("tool_calls", getattr(original_msg, "tool_calls", None))

            # The Ollama PyPI client returns a `Message` object. We must convert it
            # cleanly back to a dict with primitive values so it can be fed back in.
            assistant_message = {"role": "assistant", "content": content}
            if tool_calls:
                # Reconstruct tool_calls cleanly as dicts
                clean_tcs = []
                for tc in tool_calls:
                    tname, targs = _extract_tool_info(tc)
                    tool_call_id = _tool_call_identifier(tc)
                    clean_tcs.append({
                        "id": tool_call_id,
                        "function": {
                            "name": tname,
                            "arguments": targs
                        }
                    })
                assistant_message["tool_calls"] = clean_tcs

            self.messages.append(assistant_message)

            if content:
                self._logger.log_response(content)

            if not tool_calls and not content.strip():
                if turn_tool_results:
                    self.messages.pop()
                    if _can_auto_finalize_benign_empty(turn_tool_results):
                        benign_content = _build_benign_empty_finalization(turn_tool_results)
                        self.messages.append({"role": "assistant", "content": benign_content})
                        self._logger.log_response(benign_content)
                        _emit(self.event_callback, "chat_done", {
                            "message": "Finalized benign no-findings tool result without retry."
                        })
                        return

                    recovered_content = await self._retry_empty_reply_after_tools(prompt, turn_tool_results)
                    if recovered_content:
                        self.messages.append({"role": "assistant", "content": recovered_content})
                        self._logger.log_response(recovered_content)
                        _emit(self.event_callback, "chat_done", {
                            "message": "Recovered final answer after automatic retry."
                        })
                        return

                    action = await self._prompt_post_tool_reply_decision(prompt, turn_tool_results, cancel_event)
                    if action == "retry":
                        recovered_content = await self._retry_empty_reply_after_tools(prompt, turn_tool_results)
                        if recovered_content:
                            self.messages.append({"role": "assistant", "content": recovered_content})
                            self._logger.log_response(recovered_content)
                            _emit(self.event_callback, "chat_done", {
                                "message": "Recovered final answer after user-approved retry."
                            })
                            return

                        _emit(self.event_callback, "error", {
                            "message": "Retry failed to produce a final answer. The conversation was restored to before the failed model response."
                        })
                        _emit(self.event_callback, "chat_done", {
                            "message": "Retry failed. Conversation restored to before the failed model reply."
                        })
                        return

                    _emit(self.event_callback, "status", {
                        "message": "Discarded the failed post-tool reply and restored the conversation to the last valid state."
                    })
                    _emit(self.event_callback, "chat_done", {
                        "message": "Cancelled retry. Conversation restored to before the failed model reply."
                    })
                    return

                self.messages.pop()

                detail = "Model returned an empty reply with no tool calls."
                if self.tool_names:
                    provider_label = _provider_display_name(self.llm_provider)
                    detail += f" This usually indicates the selected model is not reliably using tools through {provider_label} for this prompt."
                else:
                    detail += " No tools are configured for this session."
                _emit(self.event_callback, "error", {"message": detail})
                _emit(self.event_callback, "chat_done", {
                    "message": "No response generated. Check tool configuration or switch to a stronger tool-calling model."
                })
                return

            # If no tool calls, this turn is done
            if not tool_calls:
                _emit(self.event_callback, "chat_done", {
                    "message": "Ready for next prompt."
                })
                return

            # Execute each tool call via MCP
            for tc in tool_calls:
                if cancel_event and cancel_event.is_set():
                    _emit_chat_cancelled(self.event_callback)
                    return

                tool_name, tool_args = _extract_tool_info(tc)
                tool_call_id = _tool_call_identifier(tc)

                policy_allowed, policy_message = _evaluate_network_policy(self.network_policy, tool_args)
                if not policy_allowed:
                    err_msg = f"Policy blocked tool call to {tool_name}: {policy_message}"
                    self._logger.log_tool_call(
                        name=tool_name,
                        args=tool_args,
                        result=err_msg,
                        duration_ms=0,
                        exit_code=-1,
                    )
                    self.messages.append({
                        "role": "tool",
                        "content": err_msg,
                        "name": tool_name,
                        "tool_call_id": tool_call_id,
                    })
                    _emit(self.event_callback, "status", {"message": err_msg})
                    continue

                is_exit_cmd = (
                    tool_name == "interactive_session_write" 
                    and isinstance(tool_args, dict)
                    and tool_args.get("input", "").strip().lower() in ["exit", "quit", "exit\n", "quit\n"]
                )

                if tool_name in ["shell_dangerous", "interactive_session_close"] or is_exit_cmd:
                    approval = await self._prompt_dangerous_tool_approval(tool_name, tool_args, cancel_event)
                    if approval != "approve":
                        denial_msg = "Command was cancelled by the user before execution."
                        self._logger.log_tool_call(
                            name=tool_name,
                            args=tool_args,
                            result=denial_msg,
                            duration_ms=0,
                            exit_code=-1,
                        )
                        self.messages.append({
                            "role": "tool",
                            "content": denial_msg,
                            "name": tool_name,
                            "tool_call_id": tool_call_id,
                        })
                        turn_tool_results.append({
                            "tool": tool_name,
                            "args": tool_args,
                            "result": denial_msg,
                            "exit_code": -1,
                            "duration_ms": 0,
                        })
                        _emit(self.event_callback, "status", {"message": denial_msg})
                        continue

                _emit(self.event_callback, "tool_call", {
                    "tool": tool_name,
                    "args": tool_args,
                })

                t0 = time.time()
                try:
                    tool_call_task = asyncio.create_task(self._session.call_tool(tool_name, tool_args))
                    timeout_monitor_task = asyncio.create_task(
                        self._watch_tool_timeout_requests(tool_name, tool_args, tool_call_task)
                    )
                    try:
                        result = await tool_call_task
                    finally:
                        timeout_monitor_task.cancel()
                        try:
                            await timeout_monitor_task
                        except asyncio.CancelledError:
                            pass
                    duration_ms = int((time.time() - t0) * 1000)

                    result_text = ""
                    if result.content:
                        result_text = "\n".join(
                            getattr(c, "text", str(c))
                            for c in result.content
                        )

                    is_error = getattr(result, "isError", False)
                    exit_code = -1 if is_error else 0

                    graceful_stop = result_text.startswith("[GRACEFUL STOP]")
                    is_cancelled = bool(cancel_event and cancel_event.is_set())
                    self._logger.log_tool_call(
                        name=tool_name,
                        args=tool_args,
                        result=result_text,
                        duration_ms=duration_ms,
                        exit_code=exit_code,
                        graceful_stop=graceful_stop,
                        cancelled=is_cancelled,
                    )

                    if "Interactive session preserved as" in result_text:
                        # Detect isess-XXX ID
                        isess_match = re.search(r"preserved as (isess-\w+)", result_text)
                        self._logger.debug(f"[isess_created] Checking for isess session in result_text. Match: {isess_match}")
                        if isess_match:
                            isess_id = isess_match.group(1)
                            self._logger.info(f"[isess_created] Interactive session detected: {isess_id}")
                            self._active_interactive_sessions.add(isess_id)
                            # Build a short summary of the args for the tab label
                            args_summary = ""
                            if isinstance(tool_args, dict):
                                args_summary = str(tool_args.get("args", ""))[:80]
                            elif isinstance(tool_args, str):
                                args_summary = tool_args[:80]
                            self._logger.info(f"[isess_created] Emitting isess_created event: session_id={isess_id}, tool={tool_name}, args={args_summary}")
                            _emit(self.event_callback, "isess_created", {
                                "session_id": isess_id,
                                "tool": tool_name or "",
                                "args_summary": args_summary,
                            })
                        else:
                            self._logger.warning(f"[isess_created] 'Interactive session preserved as' found but regex did not match. Result text:\n{result_text[:500]}")

                    if tool_name == "interactive_session_close" and exit_code == 0:
                        closed_id = ""
                        if isinstance(tool_args, dict):
                            closed_id = tool_args.get("session_id", "")
                        elif isinstance(tool_args, str):
                            closed_id = tool_args
                        if closed_id in self._active_interactive_sessions:
                            self._active_interactive_sessions.discard(closed_id)

                    context_result = _truncate_tool_output(result_text)
                    self.messages.append({
                        "role": "tool",
                        "content": context_result,
                        "name": tool_name,
                        "tool_call_id": tool_call_id,
                    })
                    turn_tool_results.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "result": result_text,
                        "exit_code": exit_code,
                        "duration_ms": duration_ms,
                    })

                    if is_cancelled:
                        _emit_chat_cancelled(self.event_callback)
                        return

                except Exception as exc:
                    duration_ms = int((time.time() - t0) * 1000)
                    err_msg = f"Tool execution failed before a result was returned: {exc}"
                    self._logger.log_tool_call(
                        name=tool_name,
                        args=tool_args,
                        result=err_msg,
                        duration_ms=duration_ms,
                        exit_code=-1,
                    )
                    self.messages.append({
                        "role": "tool",
                        "content": err_msg,
                        "name": tool_name,
                        "tool_call_id": tool_call_id,
                    })
                    turn_tool_results.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "result": err_msg,
                        "exit_code": -1,
                        "duration_ms": duration_ms,
                    })
                    _emit(self.event_callback, "tool_result", {
                        "tool": tool_name,
                        "args": tool_args,
                        "result": err_msg,
                        "exit_code": -1,
                        "duration_ms": duration_ms,
                        "error": True,
                    })

        # Hit iteration limit for this turn
        _emit(self.event_callback, "status", {
            "message": f"Reached maximum iterations ({max_iterations}) for this turn."
        })
        if turn_tool_results:
            max_turn_summary = _build_max_turn_summary(prompt, turn_tool_results, max_iterations)
            self.messages.append({"role": "assistant", "content": max_turn_summary})
            self._logger.log_response(max_turn_summary)
        _emit(self.event_callback, "chat_done", {
            "message": "Max iterations reached. Ready for next prompt."
        })

    async def stop(self):
        """Gracefully shut down the MCP connection and finalize logs."""
        if not self._started:
            return

        self._started = False
        _emit(self.event_callback, "status", {"message": "Stopping session …"})

        try:
            if self._exit_stack:
                await self._exit_stack.aclose()
                self._exit_stack = None
        except Exception as exc:
            _emit(self.event_callback, "status", {
                "message": f"Warning during shutdown: {exc}"
            })

        try:
            if self._logger:
                self._logger.finalize("completed")
        except Exception:
            pass

        _emit(self.event_callback, "service_stopped", {"message": "Session stopped."})
        _emit(self.event_callback, "done", {"message": "Session ended."})
