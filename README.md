# CyberAgentFlow

A privacy-preserving, fully localized agentic penetration testing platform. CyberAgentFlow bridges the gap between Large Language Models (LLMs) and native cybersecurity toolchains via the Model Context Protocol (MCP).

Unlike cloud-dependent conversational hacking tools, this platform ensures that your proprietary network layouts, vulnerability telemetry, and zero-day discoveries **never leave your perimeter** — everything is orchestrated through a local LLM instance (such as Ollama).

---

## Interfaces

| Interface | Description | Documentation |
|-----------|-------------|---------------|
| **WebUI** | Browser-based dashboard with live chat, session browser, and analysis tools | *This document* |
| **Terminal CLI** | Full-featured REPL with persistent split-screen UI, slash commands, and tab completion | [docs/cli.md](docs/cli.md) |
| **SSH Server** | Remote-access CLI server — connect from anywhere with `ssh -p 2222 user@host` | [docs/server.md](docs/server.md) |

---

## Core Capabilities

- **Fully Localized Execution** — Runs entirely on your local machine or trusted VM. Optional API key auth is supported for authenticated Ollama-compatible endpoints, but credentials stay local and are never written into run logs.
- **Agentic Tool Execution** — The LLM autonomously triggers local Kali Linux utilities (`nmap`, `tshark`, `arpspoof`, etc.) via the MCP server and integrates raw output directly into its reasoning loop.
- **Synchronous Subprocess Blocking** — Prevents LLM hallucinations by forcing the agent to wait for long-running processes to complete in the foreground.
- **Comprehensive Audit Trails** — Structured JSON event logs and human-readable Markdown transcripts for every session, saved under `runs/<run_id>/`.
- **Human-in-the-Loop (HITL) Annotations** — Insert timestamped notes mid-execution to guide the agent or flag data for later review.
- **Live Span Analysis** — Analyze the last *N* minutes of a live engagement with a one-shot LLM inference to generate rapid pivoting strategies.
- **Post-Mortem Session Analysis** — Feed a completed session transcript back into the LLM to auto-generate narrative summaries, highlight critical vulnerabilities, and identify methodological optimizations.
- **Session Archiving** — Download entire session directories (artifacts, tool schemas, transcripts) as self-contained ZIP archives without interrupting an active session.
- **User Keylogger** — Optional browser and system-wide keystroke logging for interaction pattern analysis.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  WebUI  (HTML/JS/CSS)                               │
│  Browser dashboard — live chat, session browser     │
└──────────────────────────┬──────────────────────────┘
                           │ SSE / REST
┌──────────────────────────▼──────────────────────────┐
│  Flask Middleware  (app.py)                         │
│  RESTful routing + Server-Sent Events stream        │
└──────────────────────────┬──────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────┐
│  MCP Client Engine  (mcp_client.py)                 │
│  Context management, LLM calls, tool dispatch       │
└────────────┬──────────────────────────┬─────────────┘
             │                          │
┌────────────▼────────────┐  ┌──────────▼──────────────┐
│  LLM Backend (Ollama)   │  │  MCP Server (mcp_kali)  │
│  Local or proxied model │  │  Kali tool wrappers     │
└─────────────────────────┘  └─────────────────────────┘
```

---

## Requirements

- **OS**: Kali Linux (recommended) or any Debian-based distribution with standard security tools installed
- **Python**: 3.10+
- **LLM Provider**: [Ollama](https://ollama.com/) or another Ollama-compatible endpoint
- **Model**: A capable tool-calling model (e.g. `ollama pull llama3` or `qwen3-coder`)

---

## Installation & Setup

### 1. Clone the Repository

```bash
git clone https://github.com/raistlinJ/cyber-agentflow.git
cd cyber-agentflow
```

### 2. Install Prerequisites

Run the setup script (installs system packages and sets up the Python virtualenv):

```bash
sudo ./install_prerequisites.sh
```

This installs `xdotool`, `x11-utils`, npm, Claude Code, and all Python dependencies from `requirements.txt` into a local `venv/`.

### 3. Start Ollama and Pull a Model

```bash
ollama serve &
ollama pull llama3
```

### 4. (Optional) Configure the Application

```bash
cp configs/cli.example.json configs/cli.json
# Edit configs/cli.json to set your provider, model, network policy, etc.
```

See [docs/configuration.md](docs/configuration.md) for all available options.

---

## Running the WebUI

```bash
./start_local.sh
```

This bootstraps the virtualenv if needed and starts the Flask server. By default it listens on **`http://localhost:5055`**.

Alternatively, run directly:

```bash
source venv/bin/activate
python3 app.py
```

---

## Using the WebUI

### 1. Configure and Start the Engine

1. Open **`http://localhost:5055`** in your browser.
2. Navigate to the **Configuration** tab.
3. Set your **Provider** and **URL** (default: `ollama_direct` → `http://localhost:11434`).
4. Click **Fetch Models** and select your model.
5. Set the **Context Window** (default: 8K) and **Max Turns**.
6. Click **Start Service** — the status dot turns green when the MCP connection is established.

### 2. Issue Commands

- Set **Scope** and **Urgency** in the Prompt Controls bar.
- Type a natural language command and press **Send** (e.g. *"Run a fast nmap scan against scanme.nmap.org"*).
- The agent autonomously executes tools, streams bounded live output inline, and returns a structured analysis.

### 3. Scope Control

Controls how broadly the agent explores during a turn.

| Setting | Behavior |
|---------|----------|
| **Broad** | Maximum surface coverage — good for blue-team review or exposure discovery |
| **Medium-Broad** | Strong adjacent surfaces with primary leads prioritized |
| **Medium** *(default)* | Balanced coverage and targeted follow-through |
| **Medium-Narrow** | Focused on strongest paths, minimal side exploration |
| **Narrow** | Direct pursuit of the most promising route to a foothold |

Toggle **Scope off** to send a prompt with no scope directive appended.

### 4. Urgency Control

Controls how aggressively the agent operates (timing, batching, parallelism).

| Setting | Behavior |
|---------|----------|
| **Stealthy** | Quiet, low-noise, slower timing — favors depth over speed |
| **Methodical** | Cautious and thorough, modest concurrency |
| **Balanced** *(default)* | Pragmatic trade-off between stealth, depth, and speed |
| **Fast** | Quicker iteration, more assertive timing |
| **Speed** | Aggressive timing and concurrency, accepts more noise |

Toggle **Urgency off** to omit the urgency directive for that prompt.

---

## Interactive Sessions

When a tool launches a preserved interactive session (e.g. a Metasploit shell), the backend issues a session ID. The agent can continue interacting via dedicated `interactive_session_*` tools without hanging. You can also take over manually in your own terminal using the recreation guidance shown in the result.

Enable interactive session support for a tool by setting `"interactive_capable": true` in `kali_tools.json`.

---

## Live Span & Post-Mortem Analysis

### Live Span Analysis
1. Click the **Annotate** (pencil) button next to the chat prompt.
2. Set the action dropdown to **🪄 Analyze Logs**.
3. Select a timeframe (e.g. *Last 5 Minutes*).
4. Click **Run Analysis** to inject tactical suggestions into your active chat feed.

### Post-Mortem Analysis
1. Navigate to the **Past Sessions** tab.
2. Select a previous run.
3. Click **🪄 Analyze Session** — an AI-generated review renders in an **Analysis** tab, highlighting unused tools and efficiency optimizations.

---

## Keylogger Feature

The WebUI includes an optional keystroke logger for interaction pattern analysis.

### Enabling
1. Go to **Configuration → Logging**.
2. Check **Enable Keylogging**.
3. Start a session.

### What Is Captured
- **Browser keylogger** — keystrokes within the WebUI (URL, page context)
- **System keylogger** — system-wide keystrokes with active application/window title
- Sensitive fields (password inputs, API key fields) are automatically excluded

### Storage
Keystrokes are saved to `runs/<run_id>/keystrokes/`:
- `browser_log.jsonl` — browser keystrokes
- `system_log.jsonl` — system keystrokes

### Linux Prerequisites
System keylogger window detection requires `xdotool`:
```bash
sudo ./install_prerequisites.sh
```

---

## Additional Logging Options

Available under **Configuration → Logging**:

- **Network Capture** — Continuously captures packets on all active interfaces. Persisted to separate `.pcap` files under `runs/<run_id>/network_capture/`. High resource usage.
- **System Call Logger** — Captures syscall activity via `strace` under `runs/<run_id>/syscalls/`.

---

## Session Transcripts

Every session is saved to `runs/<run_id>/`:
- `transcript.md` — Human-readable Markdown transcript
- `events.jsonl` — Structured JSON event log

Completed sessions are browsable in the **Past Sessions** tab and downloadable as ZIP archives.

---

## Terminal CLI & SSH Server

For headless environments, automation, or remote access, CyberAgentFlow also ships a full terminal interface:

- **[Terminal CLI →](docs/cli.md)** — Interactive REPL with persistent split-screen UI, slash commands, tab completion, session resume (`--continue`), and single-shot `run` mode.
- **[SSH Server →](docs/server.md)** — Self-contained SSH daemon that serves the CLI interface to remote clients. Connect from anywhere with `ssh -p 2222 user@host`.

---

*Developed for advanced, privacy-first agentic infrastructure.*
