# CyberAgentFlow — Terminal CLI Reference

A full-featured terminal interface for CyberAgentFlow that requires no browser. The CLI shares the same `MCPSession` engine, `mcp_kali.py` server, `kali_tools.json` tool configuration, and `runs/` transcript format as the WebUI, giving you identical capabilities in a lightweight, scriptable terminal experience.

---

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Resuming a Previous Session](#resuming-a-previous-session)
- [Configuration](#configuration)
  - [CLI Flags Reference](#cli-flags-reference)
  - [Config File Format](#config-file-format)
  - [Secure API Key Handling](#secure-api-key-handling)
- [In-Chat Slash Commands](#in-chat-slash-commands)
  - [Tab Completion](#tab-completion)
- [Persistent Bottom Bar](#persistent-bottom-bar)
- [Scope and Urgency](#scope-and-urgency)
- [Transcripts and Run Logs](#transcripts-and-run-logs)

---

## Overview

The CyberAgentFlow CLI runs entirely in your terminal with no browser required. It is built on the same core engine as the WebUI:

| Component | Shared with WebUI |
|---|---|
| `MCPSession` agent engine | ✅ |
| `mcp_kali.py` MCP server | ✅ |
| `kali_tools.json` tool configuration | ✅ |
| `runs/<run_id>/` transcript format | ✅ |

**Key terminal-native features:**

- **Persistent split-screen bottom bar** — a live status line and `caf>` input prompt remain visible even while a tool is executing in the background
- **Real-time character-by-character input** — slash commands can be entered mid-run without waiting for the current task to finish
- **Full session transcript saving** — every run is automatically saved under `runs/` in both human-readable Markdown and structured JSONL formats

---

## Prerequisites

All prerequisites are the same as the main README:

- **Python 3.10+**
- **Ollama** running locally (or a compatible OpenAI-compatible API endpoint)
- A **virtual environment** with dependencies installed

Run the setup script once before using the CLI:

```bash
./install_prerequisites.sh
```

This script creates the `venv/` virtual environment and installs all required system and Python dependencies automatically.

---

## Quick Start

All CLI commands are launched via `./start_cli.sh`. The entry point accepts a subcommand followed by optional flags and arguments.

```bash
# Start an interactive chat session
# Automatically loads configs/cli.json if the file is present
./start_cli.sh chat

# Run a single prompt non-interactively, then exit
./start_cli.sh run --model llama3 "Run a fast nmap scan against scanme.nmap.org"

# List all saved session runs with their index numbers
./start_cli.sh list-runs
```

### Subcommands

| Subcommand | Description |
|---|---|
| `chat` | Start an interactive multi-turn chat session |
| `run` | Execute a single prompt and exit (batch/scripting mode) |
| `list-runs` | Print a numbered table of all saved runs under `runs/` |

---

## Resuming a Previous Session

You can resume any previous session to continue where you left off. The session's prior transcript is loaded into context before the new conversation begins.

**Step 1 — Find the session index:**

```bash
./start_cli.sh list-runs
```

Example output:

```
Idx  Run ID                    Started              Turns  Model
───  ────────────────────────  ───────────────────  ─────  ──────────────
  0  2026-06-09-143201-a3f2    2026-06-09 14:32:01     12  llama3
  1  2026-06-08-091445-b7c1    2026-06-08 09:14:45      8  llama3
  2  2026-06-07-204312-d9e0    2026-06-07 20:43:12     21  mistral
  3  2026-06-01-110053-f1a4    2026-06-01 11:00:53      5  llama3
```

**Step 2 — Resume by index or by run ID prefix:**

```bash
# Resume using the Idx column
./start_cli.sh chat --continue 3

# Or resume using a run ID prefix (any unambiguous prefix works)
./start_cli.sh chat --continue 2026-06-01
```

---

## Configuration

### Auto-load Behaviour

On startup, the CLI automatically loads `configs/cli.json` if the file exists. This is the recommended way to persist your preferred settings across sessions.

Override the default config path with the `--config` flag:

```bash
./start_cli.sh chat --config configs/my-profile.json
```

**Precedence order (highest → lowest):**

1. Explicit CLI flags
2. Config file values
3. Built-in defaults

### CLI Flags Reference

| Flag | Description |
|---|---|
| `--config PATH` | Path to a JSON config file to load |
| `--model MODEL` | Model name to use (e.g. `llama3`, `mistral`) |
| `--url URL` | API base URL (e.g. `http://localhost:11434`) |
| `--provider PROVIDER` | Provider type (e.g. `ollama_direct`, `openai`) |
| `--context-window N` | Context window size in tokens |
| `--max-turns N` | Maximum number of agent turns per session |
| `--scope VALUE` | Scan scope level (see [Scope and Urgency](#scope-and-urgency)) |
| `--urgency VALUE` | Execution urgency level (see [Scope and Urgency](#scope-and-urgency)) |
| `--no-scope` | Disable scope enforcement |
| `--no-urgency` | Disable urgency enforcement |
| `--allow CIDR` | Add a CIDR range to the network allow list |
| `--disallow CIDR` | Add a CIDR range to the network disallow list |
| `--api-key KEY` | API key (prefer `MCP_API_KEY` env var instead — see below) |
| `--tool-timeout N` | Per-tool execution timeout in seconds |
| `--verbose` | Enable verbose debug logging |
| `--continue ID` | Resume a previous run by index or run ID prefix |

### Config File Format

The config file is a JSON object. All keys are optional; omitted keys fall back to CLI flags or built-in defaults.

```json
{
    "provider": "ollama_direct",
    "url": "http://localhost:11434",
    "model": "llama3",
    "api_key_env": "MCP_API_KEY",
    "ssl_verify": true,
    "server_command": "venv/bin/python mcp_kali.py",
    "tools_config": "kali_tools.json",
    "context_window": 8192,
    "max_turns": 20,
    "network_policy": {
        "allow": ["192.168.56.0/24"],
        "disallow": ["192.168.56.1"]
    },
    "scope": "medium",
    "scope_enabled": true,
    "urgency": "balanced",
    "urgency_enabled": true,
    "tool_output_chars": 6000,
    "verbose": false
}
```

#### Config Key Reference

| Key | Type | Description |
|---|---|---|
| `provider` | string | API provider identifier |
| `url` | string | API base URL |
| `model` | string | Model name |
| `api_key_env` | string | Name of an environment variable holding the API key |
| `ssl_verify` | bool | Whether to verify TLS certificates |
| `server_command` | string | Command used to launch the MCP server |
| `tools_config` | string | Path to the tool configuration JSON file |
| `context_window` | integer | Token context window size |
| `max_turns` | integer | Maximum agent turns per session |
| `network_policy.allow` | string[] | CIDR ranges the agent is permitted to target |
| `network_policy.disallow` | string[] | CIDR ranges explicitly blocked |
| `scope` | string | Default scan scope level |
| `scope_enabled` | bool | Whether scope enforcement is active |
| `urgency` | string | Default urgency level |
| `urgency_enabled` | bool | Whether urgency enforcement is active |
| `tool_output_chars` | integer | Maximum characters of tool output forwarded to the LLM |
| `verbose` | bool | Enable verbose logging |

### Secure API Key Handling

> [!CAUTION]
> Passing `--api-key` directly on the command line embeds your credential in your shell history. Prefer one of the following approaches instead.

**Option 1 — Environment variable (inline):**

```bash
MCP_API_KEY=sk-... ./start_cli.sh chat
```

**Option 2 — `api_key_env` in config file:**

Set `"api_key_env": "MCP_API_KEY"` in your config file. The CLI will read the key from the named environment variable at runtime, keeping the key out of both shell history and config files committed to version control.

---

## In-Chat Slash Commands

All slash commands are available during an interactive `chat` session. Commands beginning with `/` are processed immediately by the CLI — they do not get sent to the LLM.

| Command | Description |
|---|---|
| `/help` | Show all available slash commands |
| `/exit` or `/quit` | Stop the session cleanly and save the transcript |
| `/cancel` | Cancel the active background task immediately |
| `/force_analyze` | Cancel the active task and queue an LLM analysis of the partial output collected so far |
| `/scope VALUE\|off` | Set the scan scope for the next prompt (`broad` / `medium-broad` / `medium` / `medium-narrow` / `narrow` / `off`) |
| `/urgency VALUE\|off` | Set the execution urgency (`stealthy` / `methodical` / `balanced` / `fast` / `speed` / `off`) |
| `/set KEY VALUE` | Change a session setting live (e.g. `scope`, `urgency`, `verbose`, `tool_output_chars`) |
| `/config` | Print the current session configuration as formatted JSON |
| `/save-config [PATH]` | Save the current session settings to a JSON config file (defaults to `configs/cli.json`) |
| `/tools` | List all MCP tools available in the current session |
| `/sessions` | List all preserved interactive sessions |
| `/refresh-sessions` | Refresh the session ID list used for Tab autocomplete |
| `/enter SESSION_ID` | Switch into interactive session mode for the given session (similar to switching tabs in a terminal multiplexer) |
| `/back` | Return to main chat mode from an interactive session |
| `/where` | Display the current mode and active session |
| `/read [SESSION_ID]` | Read buffered output from an interactive session |
| `/write [SESSION_ID] TEXT` | Send text input to an interactive session |
| `/close [SESSION_ID]` | Close and clean up an interactive session |

### Tab Completion

Press **Tab** after typing `/` to trigger autocomplete for command names. Tab completion also works for:

| Context | Completed Values |
|---|---|
| `/set KEY` | Known setting keys (`scope`, `urgency`, `verbose`, `tool_output_chars`, …) |
| `/set scope VALUE` | Valid scope levels (`broad`, `medium-broad`, `medium`, …) |
| `/set urgency VALUE` | Valid urgency levels (`stealthy`, `methodical`, `balanced`, …) |
| `/enter`, `/read`, `/write`, `/close` | Known interactive session IDs |
| `/save-config PATH` | Config file paths under `configs/` |

---

## Persistent Bottom Bar

During tool execution the terminal display is split into three regions:

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│   Scrolling output region                                        │
│   (streaming tool results and LLM responses appear here)        │
│                                                                  │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  [tool: nmap_scan]  elapsed: 00:12   status: running            │
├──────────────────────────────────────────────────────────────────┤
│  caf> _                                                          │
└──────────────────────────────────────────────────────────────────┘
```

| Region | Description |
|---|---|
| **Scrolling output** | Streaming tool output and LLM responses scroll upward here |
| **Status bar** | Shows the currently running tool name and elapsed time |
| **Input line** | The `caf>` prompt stays visible and interactive at all times |

Because input is processed character-by-character, you can type `/cancel` or `/force_analyze` at any moment during tool execution without waiting for it to finish.

---

## Scope and Urgency

Scope and urgency work identically to the WebUI. Refer to the main README for full descriptions of each level.

**Scope levels** (controls scan breadth):

| Value | Description |
|---|---|
| `broad` | Wide surface coverage |
| `medium-broad` | Slightly focused broad scan |
| `medium` | Balanced default |
| `medium-narrow` | Focused, targeted scanning |
| `narrow` | Minimal footprint, single target |
| `off` | No scope enforcement |

**Urgency levels** (controls execution speed vs. stealth):

| Value | Description |
|---|---|
| `stealthy` | Slow, low-noise execution |
| `methodical` | Careful, deliberate pacing |
| `balanced` | Balanced default |
| `fast` | Prioritise speed |
| `speed` | Maximum speed, higher noise |
| `off` | No urgency enforcement |

**Ways to set scope and urgency:**

1. **CLI flag** — `--scope medium --urgency balanced`
2. **Config file** — `"scope": "medium"`, `"urgency": "balanced"`
3. **Slash command at runtime** — `/scope narrow`, `/urgency stealthy`

---

## Transcripts and Run Logs

Every session — whether interactive `chat` or single-shot `run` — is automatically saved under `runs/<run_id>/`.

```
runs/
└── 2026-06-09-143201-a3f2/
    ├── transcript.md     ← Human-readable Markdown transcript
    └── events.jsonl      ← Structured JSON event log (one event per line)
```

| File | Format | Purpose |
|---|---|---|
| `transcript.md` | Markdown | Human-readable record of the full conversation including tool inputs and outputs |
| `events.jsonl` | JSON Lines | Machine-readable structured log suitable for parsing, replay, or analysis |

### Viewing Saved Runs

```bash
./start_cli.sh list-runs
```

The `Idx` column shown in the output can be passed directly to `--continue` to resume that session:

```bash
# Resume the session at index 2
./start_cli.sh chat --continue 2
```

> [!TIP]
> You can also open `runs/<run_id>/transcript.md` directly in any Markdown viewer for a clean, readable audit trail of what the agent did.
