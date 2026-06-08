# CyberAgentFlow

A privacy-preserving, fully localized agentic penetration testing platform. CyberAgentFlow bridges the gap between Large Language Models (LLMs) and native cybersecurity toolchains by utilizing the Model Context Protocol (MCP).

Unlike cloud-dependent conversational hacking tools, this platform ensures that your proprietary network layouts, vulnerability telemetry, and zero-day discoveries never leave your perimeter by orchestrating everything through a local LLM instance (like Ollama).

## Core Capabilities

*   **Fully Localized Execution**: Runs entirely on your local machine or trusted VM. Optional API key auth is supported for authenticated Ollama-compatible endpoints, but credentials stay local and are not written into run logs.
*   **Agentic Tool Execution**: The LLM autonomously triggers local Kali Linux utilities (e.g., `nmap`, `gobuster`, `ping`) via the MCP server and integrates the raw output directly into its reasoning loop.
*   **Synchronous Subprocess Blocking**: Prevents LLM hallucinations by forcing the agent to wait for long-running processes to complete in the foreground.
*   **Comprehensive Audit Trails**: Generates structured JSON tool execution logs and beautiful, human-readable Markdown transcripts for every session.
*   **Human-in-the-Loop (HITL) Annotations**: Analysts can actively insert timestamped notes and tag areas of interest mid-execution to guide the agent or flag data for later review.
*   **Live Span Analysis**: Seamlessly analyze the last *N* minutes of a live engagement using a one-shot LLM inference to generate rapid pivoting strategies or identify execution bottlenecks in real-time.
*   **Post-Mortem Session Analysis**: Feed an entire past session transcript (along with your manual annotations) back into the LLM to auto-generate narrative success summaries, highlight critical vulnerabilities, and pinpoint areas for methodological optimization.
*   **Session Archiving**: Download entire session directories—including the generated artifacts, tool schemas, and transcription—as self-contained ZIP archives without interrupting the active Live Chat stream.
*   **User Keylogger**: Optional browser and system-wide keystroke logging for interaction pattern analysis. Captures which applications/windows were active during each keystroke.

## Architecture

*   **Frontend**: A responsive Vanilla HTML/JS/CSS WebUI with a persistent chat console, real-time token tracking, inline tool execution runtime indicators, bounded scrollable live output, and a session browser.
*   **Middleware Orchestrator**: A Python Flask server (`app.py`) that handles RESTful routing and streams real-time interaction events to the frontend via Server-Sent Events (SSE).
*   **MCP Client Engine**: `mcp_client.py` acts as the intelligent broker, managing the context window, parsing LLM payloads, and mapping them to standard I/O subprocess executions.
*   **LLM Backend**: Powered by the Python `ollama` library, driving conversational endpoints against a local or proxied Ollama-compatible model endpoint (e.g., `llama3`).
*   **MCP Server (Kali)**: A localized script (`mcp_kali.py`) that securely wraps standard Kali utilities and exposes them as callable functions to the Client Engine.

## Requirements

*   **OS**: Kali Linux (recommended) or any Debian-based distribution with standard security tools installed.
*   **Python**: 3.10+
*   **LLM Provider**: [Ollama](https://ollama.com/) or another Ollama-compatible endpoint. If your endpoint is behind a proxy such as LiteLLM and requires bearer auth, provide the API key in the UI.
*   **Model**: A capable tool-calling model pulled into Ollama (e.g., `ollama run llama3` or `llama3.1`).
*   **Python Dependencies**:
    *   `Flask`
    *   `requests`
    *   `mcp` (Official Model Context Protocol SDK)
    *   `ollama`
    *   `pynput` (for system keylogger)

*   **System Keylogger Prerequisites (Linux)**:
    *   `xdotool` - Required for active window detection
    *   `x11-utils` - Provides `xprop` for application name detection
    *   `python3-psutil` - Required for process information
    
    Install these packages with:
    ```bash
    sudo ./install_prerequisites.sh
    ```
    Or manually:
    ```bash
    sudo apt install xdotool x11-utils python3-psutil
    ```

## Installation & Setup

1.  **Clone the Repository**
    ```bash
    git clone https://github.com/raistlinJ/cyber-agentflow.git
    cd cyber-agentflow
    ```

2.  **Install Dependencies**
    Preferred local launcher:
    ```bash
    ./start_local.sh
    ```
    This bootstraps `uv` if needed and runs the WebUI with the required Python dependencies.

    Manual installation alternative:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

3.  **Ensure Ollama is Running**
    *   Start the Ollama service on your machine, or point the UI at an authenticated Ollama-compatible proxy.
    *   Ensure you have downloaded your preferred model: `ollama pull llama3`

## Running the Application

    ```bash
    python3 app.py
    ```
    *(By default, the Flask server will launch on `http://localhost:5055`.)*

2.  **Access the Dashboard**
    Open a web browser and navigate to `http://localhost:5055`.

3.  **Configure and Start the Engine**
    *   Navigate to the **Configuration** tab in the WebUI.
    *   If needed, enter an optional **API Key** for authenticated endpoints.
    *   Click **Fetch Models** to populate the dropdown with your available models.
    *   Select your model (e.g., `llama3`).
    *   Allocate your desired Context Window (Default: 8K).
    *   Click **Start Service**. The dot indicator should turn green.

4.  **Begin Testing**
    *   Set the **Scope** and **Urgency** sliders to control how broadly and how aggressively the agent should approach the current request.
    *   Issue a natural language command (e.g., *"Run a fast nmap scan against scanme.nmap.org"*).
    *   Watch as the agent dynamically executes the tool in the foreground, shows the active runtime inline on the tool-call row, streams bounded live output, and returns an analysis.

## Terminal CLI

CyberAgentFlow can also run directly from your terminal. The CLI uses the same `MCPSession` engine, `mcp_kali.py` server, `kali_tools.json` tool configuration, and `runs/` transcript format as the WebUI.

Run an interactive terminal chat session:

```

For config-file based sessions, copy the example profile once:

```bash

Then edit `configs/cli.json` and launch without repeating the same flags:

```bash
./start_cli.sh chat

You can also keep multiple named profiles:

```

Run a single prompt and exit:

```bash
./start_cli.sh run --model llama3 "Run a fast nmap scan against scanme.nmap.org"
```

List saved run directories:

```bash
./start_cli.sh list-runs
```

The launcher reuses the persistent `venv/` created by `start_local.sh`. If dependencies have not been installed yet, run:

```bash
```
In interactive chat, pressing **Tab** after typing `/` enables command autocomplete. It also completes `/set` keys and common values, known interactive session IDs for `/enter`, `/read`, `/write`, `/close`, and config paths for `/save-config`.

Common CLI options:

*   `--config configs/cli.json` loads a JSON session profile. If `configs/cli.json` exists, it is loaded automatically.
*   `--url http://localhost:11434` sets the Ollama or provider base URL.
*   `--provider ollama_direct|litellm|openai|claude` selects the LLM backend adapter.
*   `--context-window 8192` and `--max-turns 20` match the WebUI runtime controls.
*   `--scope medium` and `--urgency balanced` apply the same per-prompt controls used by Live Chat. Use `--no-scope` or `--no-urgency` to disable them.
*   `--allow` and `--disallow` define the target access policy, for example `--allow 192.168.56.0/24 --disallow 192.168.56.10`.
*   `--api-key` provides authenticated-provider credentials, but `MCP_API_KEY=... ./start_cli.sh ...` is safer for shell history.

CLI flags override values from the config file, so you can keep a stable profile and temporarily change one setting:

```bash
./start_cli.sh chat --config configs/home-lab.json --urgency fast
```

Supported config keys:

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

Use `api_key_env` instead of storing API keys in config files. The CLI reads the named environment variable at startup.

Inside `chat` mode, use `/help` to see terminal commands. The REPL supports `/enter SESSION_ID`, `/back`, `/where`, `/config`, `/set KEY VALUE`, `/save-config [PATH]`, `/tools`, `/scope`, `/urgency`, `/sessions`, `/read [SESSION_ID]`, `/write ...`, and `/close [SESSION_ID]` for preserved interactive sessions.

`/set` lets you change settings from the running CLI (for example scope, urgency, verbose logging, and output truncation). Some settings are applied immediately, while connection-level settings (model, provider, context window, network policy, etc.) are stored and marked as requiring a restart.

`/save-config` writes the current settings state to a JSON profile, similar to CLI tools that persist in-session configuration changes.

### Live Chat Behavior

The Live Chat pane is intentionally bounded and scrollable so long runs do not keep stretching the page. The UI keeps only a recent window of prompt output in the live pane, while the full session remains available in the downloaded archive and run directory.

When a tool is running, its current elapsed time is shown inline on the matching **Tool Call** row. If a tool pauses at a timeout checkpoint, that same row changes state to indicate it is waiting for a decision.

If a tool launches an interactive session that the backend can preserve safely, the result now returns a preserved session id and the agent can continue through dedicated interactive session tools instead of hanging. For Metasploit-style flows, the result also includes manual recreation guidance so you can move the session into your own terminal if you prefer direct control there. When a session cannot be preserved safely, the backend falls back to a handoff message instead of letting the agent hang.

Tools can opt into preserved interactive-session handling by setting `"interactive_capable": true` in `kali_tools.json`. `msf_run` is enabled this way by default in the generated tool config, and you can add the same flag to other tools you explicitly want the backend to treat as interactive-capable.

If a turn hits the configured max-turn limit before the model produces a normal final reply, the backend now emits a synthesized assistant summary that includes the **last command run** and a concise summary of the recent tool results, instead of leaving the Live Chat view stranded on the last raw tool result.

### Scope Control

The **Scope** control sits inside **Prompt Controls** above the Live Chat prompt box and changes the per-turn execution guidance sent to the model before your prompt is processed.

It does **not** change the configured context window size. Instead, it changes the **instructional scope** for that specific prompt: whether the agent should cast a wide net and look broadly for anything useful, or stay tightly focused on the most promising path.

You can toggle **Scope** off for any prompt. When it is off, no extra scope directive is appended for that turn.

Each setting adds different scope guidance to the turn context:

*   **Broad**: Instructs the model to maximize coverage across the reachable target surface, look for any meaningful weakness or misconfiguration, and favor breadth and triage over deep pursuit of one path. Best fit for blue-team style review or general exposure discovery.
*   **Medium-Broad**: Instructs the model to cover the strongest adjacent attack surfaces while still prioritizing the best leads. Useful when you want broad situational awareness without fully exhaustive exploration.
*   **Medium**: Instructs the model to balance surface coverage with targeted follow-through. This is the default setting and is meant for general-purpose engagements.
*   **Medium-Narrow**: Instructs the model to stay focused on the strongest-looking paths and minimize side exploration unless needed to validate a hypothesis or unblock the current line of work.
*   **Narrow**: Instructs the model to pursue the most promising route to at least one viable foothold or concrete way in, while avoiding broad enumeration unless it directly supports that goal. Best fit for tightly targeted red-team style probing.

Scope is applied **per prompt**, so you can widen or narrow the agent's behavior as the engagement evolves. The active setting is injected into the main turn system directive for that request rather than being treated as a passive UI hint.

### Urgency Control

The **Urgency** control sits next to **Scope** inside **Prompt Controls** and changes the per-turn execution tempo guidance sent to the model.

It is meant to influence how aggressively the agent operates: scan timing, batching, parallelism, and how much time it should spend validating and going deep before returning progress.

You can also toggle **Urgency** off for any prompt. When it is off, no extra urgency directive is appended for that turn.

Each setting adds different urgency guidance to the turn context:

*   **Stealthy**: Biases the agent toward quieter, lower-noise commands, slower timing, smaller batches, and deeper verification before escalating.
*   **Methodical**: Keeps the agent cautious and thorough, with modest concurrency and a preference for explainable, validated progress over speed.
*   **Balanced**: Uses a middle-ground tempo and trades off stealth, depth, and speed pragmatically. This is the default setting.
*   **Fast**: Pushes the agent toward quicker iteration, more assertive timing, and higher parallelism when appropriate.
*   **Speed**: Optimizes for rapid answers using aggressive but still policy-compliant timing and concurrency, accepting more noise and less depth when useful.

Urgency is also applied **per prompt**, so you can slow the agent down for quiet enumeration and then turn it up when you want faster feedback. Like Scope, the active urgency setting is folded into the main system directive for the turn so it has stronger weight during tool planning.

## User Keylogger Feature

The WebUI includes an optional keylogger feature that captures all user keystrokes for interaction pattern analysis.

### Features

- **Browser Keylogger**: Captures all keystrokes within the WebUI
- **System Keylogger**: Captures system-wide keystrokes (requires `xdotool` on Linux)
- **Window Tracking**: Records which application/window was active for each keystroke
- **Privacy Protection**: Sensitive fields (passwords, API keys) are automatically excluded
- **Session Correlation**: Keystrokes are linked to the current session for analysis
- **Archive Support**: Captured keystrokes are written into `runs/<run_id>/keystrokes/` and included in session downloads

### Enabling Keylogging

1. Navigate to the **Configuration** tab
2. Open the **Logging** subtab
3. Check **Enable Keylogging**
4. Start a session

### Linux Prerequisites

For full system keylogger functionality on Linux, you need `xdotool` installed:

```bash
sudo ./install_prerequisites.sh
```

This script will:
- Detect your distribution (Kali 2025.x/2026.x, Debian, Ubuntu)
- Install `xdotool`, `x11-utils`, and `python3-psutil`
- Verify the installation

Without `xdotool`, the system keylogger will still capture keystrokes but won't be able to detect which application/window was active.


### Data Storage

Keystrokes are stored in `runs/<run_id>/keystrokes/`:
- `browser_log.jsonl` - Browser keystrokes with URL and page context
- `system_log.jsonl` - System keystrokes with application and window title

## Additional Logging Options

The **Logging** subtab also includes optional runtime loggers:

- **Network Capture (High Resource)**: Continuously captures packets on all interfaces currently marked `UP`. If an interface goes down and later comes back up, capture resumes automatically. Each interface is persisted to separate `.pcap` files under `runs/<run_id>/network_capture/`.
- **System Call Logger**: Captures syscall activity with `strace` (when available) and stores logs under `runs/<run_id>/syscalls/`.

## Timestamp Format

Session and logger timestamps now use a single format with millisecond precision:

- `MM-DD-YYYY HH:MM:SS.mmm`

### Privacy Notes

- Password fields and API key fields are automatically excluded
- Sensitive field names (password, api_key, secret, token, etc.) are detected by class/id/name
- Only metadata about sensitive field interaction is logged (not the actual keystrokes)

## Using the Observation & Analysis Engine

### Live Span Analysis
If you get stuck during an engagement:
1. Click the **Annotate (pencil icon)** button next to the chat prompt.
2. Change the action dropdown to **🪄 Analyze Logs**.
3. Select a timeframe (e.g., **"Last 5 Minutes"**).
4. Click **Run Analysis**. The LLM will parse only that specific window of execution and inject tactical suggestions directly into your active chat feed.

### Post-Mortem Analysis
To review completed work:
1. Ensure the backend Service is active in the Configuration tab.
2. Navigate to the **Past Sessions** tab and select a previous run.
3. Click the **🪄 Analyze Session** button in the top right.
4. An **Analysis** tab will render an AI-generated review of the session, highlighting unused tools and efficiency optimizations. 

---
*Developed for advanced, privacy-first agentic infrastructure.*
