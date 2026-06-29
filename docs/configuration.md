# Configuration Guide

CyberAgentFlow uses a JSON-based configuration system for both CLI, WebUI, and SSH Server sessions. This document describes all available configuration options.

## Configuration File Location

- **CLI**: `configs/cli.json` (if present, loaded automatically)
- **Example**: `configs/cli.example.json`

## Configuration Options

### LLM Provider Settings

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `provider` | string | `"ollama_direct"` | LLM provider to use. Valid values: `ollama_direct`, `litellm`, `openai`, `claude` |
| `url` | string | `"http://localhost:11434"` | Base URL for the LLM provider endpoint |
| `model` | string | `""` | Model name to use (e.g., `llama3`, `llama3.1`, `claude-3-5-sonnet`) |
| `api_key` | string | `""` | API key for authenticated providers (use `api_key_env` instead for security) |
| `api_key_env` | string | `"MCP_API_KEY"` | Environment variable name containing the API key (safer than embedding the key directly — see [Secure API Key Handling](#secure-api-key-handling)) |
| `ssl_verify` | boolean | `true` | Enable SSL certificate verification for HTTPS endpoints |

### Server Settings

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `server_command` | string | `"venv/bin/python mcp_kali.py"` | Command to launch the MCP server (Kali tools wrapper) |
| `tools_config` | string | `"kali_tools.json"` | Path to the JSON file defining available tools |

### Context & Performance

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `context_window` | integer | `8192` | Maximum context window size in tokens. Minimum: 1024 |
| `max_turns` | integer | `20` | Maximum number of LLM-to-tool iterations per user prompt. Range: 1-100 |
| `tool_output_chars` | integer | `6000` | Maximum characters of tool output to include in context. Larger outputs are truncated |

### Network Policy

Controls which targets the agent is allowed to scan or attack.

| Key | Type | Description |
|-----|------|-------------|
| `network_policy.allow` | array | List of allowed target patterns. Use `["*"]` for all targets |
| `network_policy.disallow` | array | List of blocked target patterns |

**Network Policy Examples:**
```json
{
  "network_policy": {
    "allow": ["*"],              // Allow all targets
    "disallow": []               // No exclusions
  }
}
```

```json
{
  "network_policy": {
    "allow": ["192.168.56.0/24"],  // Only scan this subnet
    "disallow": ["192.168.56.1"]   // Exclude gateway
  }
}
```

### Scope Control (Per-Prompt Guidance)

Controls how broadly the agent explores targets.

| Value | Description |
|-------|-------------|
| `broad` | Maximum coverage across target surface. Best for blue-team reviews or general exposure discovery |
| `medium-broad` | Strong adjacent attack surfaces while prioritizing best leads. Good for situational awareness |
| `medium` | Balanced coverage with targeted follow-through. Default for general engagements |
| `medium-narrow` | Stay focused on strongest paths. Minimize side exploration unless needed |
| `narrow` | Pursue most promising route to foothold. Avoid broad enumeration |

**Usage:** Set `scope_enabled: true` to use scope guidance. Set `scope: "off"` to disable per-prompt scope injection.

### Urgency Control (Per-Prompt Tempo)

Controls how aggressively the agent operates.

| Value | Description |
|-------|-------------|
| `stealthy` | Quieter, lower-noise commands. Slower timing, smaller batches, deeper verification |
| `methodical` | Cautious and thorough. Modest concurrency, validated progress over speed |
| `balanced` | Middle-ground tempo. Pragmatic tradeoff of stealth, depth, and speed. Default |
| `fast` | Quicker iteration. More assertive timing, higher parallelism |
| `speed` | Rapid answers. Aggressive timing, higher parallelism. Accept more noise |

**Usage:** Set `urgency_enabled: true` to use urgency guidance. Set `urgency: "off"` to disable per-prompt urgency injection.

### Logging & Debugging

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `verbose` | boolean | `false` | Enable verbose logging output |

---

## Complete Example Configuration

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
    "allow": ["192.168.1.0/24"],
    "disallow": ["192.168.1.1"]
  },
  "scope": "medium",
  "scope_enabled": true,
  "urgency": "balanced",
  "urgency_enabled": true,
  "tool_output_chars": 6000,
  "verbose": false
}
```

---

## CLI Usage

### Loading Configuration

The CLI automatically loads configuration from `configs/cli.json` if it exists:

```bash
./start_cli.sh chat
```

To use a different config file, specify it with `--config`:

```bash
./start_cli.sh chat --config configs/my-profile.json
```

CLI flags override values from the config file:

```bash
./start_cli.sh chat \
  --config configs/my-profile.json \
  --scope broad \
  --urgency fast \
  --model llama3.1
```

### Available Commands

| Command | Description |
|---------|-------------|
| `chat` | Start an interactive chat session |
| `run "prompt"` | Run a single prompt and exit |
| `list-runs` | List all saved session runs |

### Examples

**Quick scan with custom model:**
```bash
./start_cli.sh run --model llama3 "Run a fast nmap scan against scanme.nmap.org"
```

**Interactive chat with config:**
```bash
./start_cli.sh chat --config configs/prod.json
```

**Run with custom scope and urgency:**
```bash
./start_cli.sh chat --scope broad --urgency fast
```

**Save current session config:**
In interactive chat, use: `/save-config configs/my-profile.json`

---

## Secure API Key Handling

> [!CAUTION]
> Passing `--api-key` directly on the command line embeds your credential in your shell history. Prefer one of the approaches below.

The `api_key_env` configuration field instructs the CLI (and SSH server) to read the API key from a **named environment variable** at runtime, rather than embedding the key in a config file or command-line argument.

**Option 1 — Environment variable (inline):**

```bash
MCP_API_KEY=sk-... ./start_cli.sh chat
```

**Option 2 — `api_key_env` in config file:**

```json
{
  "api_key_env": "MCP_API_KEY"
}
```

Export the key in your shell profile (e.g., `~/.bashrc` or `~/.zshrc`):

```bash
export MCP_API_KEY=sk-...
```

The CLI reads `$MCP_API_KEY` at startup. The key never appears in config files committed to version control or in process listings.

---

## Environment Variables

The following environment variables can be used as defaults:

| Variable | Default Value |
|----------|---------------|
| `MCP_LLM_PROVIDER` | `ollama_direct` |
| `MCP_OLLAMA_URL` | `http://localhost:11434` |
| `MCP_MODEL` | (empty — must be set via config or CLI) |
| `MCP_API_KEY` | (empty — used when `api_key_env` references this) |

---

## WebUI Configuration

The WebUI uses the same configuration structure. Settings are saved per-session and persisted to `runs/<run_id>/` directories. The Configuration tab in the WebUI allows you to:

1. Set provider URL and API key
2. Select model from available models
3. Adjust context window and max turns
4. Configure network policy
5. Set scope and urgency defaults
6. Enable keylogging and other loggers

---

## SSH Server Configuration

The SSH server (`cli-server.py`, launched via `start_server.sh`) accepts all standard session config flags **plus** three server-specific flags:

### SSH-Specific Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | `2222` | TCP port the SSH daemon listens on |
| `--password` | `admin` | Shared password for all connecting clients |
| `--host-key` | *(ephemeral)* | Path to a persistent SSH host private key file. If omitted, a new RSA key is generated on each startup — clients will see a "host key changed" warning on every reconnect. Generate once with `ssh-keygen -t ed25519 -f server_host_key -N ""` and reuse it. |

These flags are **in addition to** all session-level flags (`--model`, `--config`, `--scope`, `--urgency`, `--allow`, `--disallow`, etc.) which set the default configuration applied to every new client session.

### Config Loading Order

The server resolves its configuration in the following precedence order (highest wins):

1. **Explicit command-line flags** — values passed directly to `start_server.sh` / `cli-server.py`
2. **Config file values** — loaded from the path given by `--config` (default: `configs/cli.json`)
3. **Environment variables** — `MCP_LLM_PROVIDER`, `MCP_OLLAMA_URL`, `MCP_MODEL`, `MCP_API_KEY`
4. **Built-in defaults** — hardcoded fallbacks in `cli.py`

This is identical to the CLI resolution order (see `cli._resolve_session_args`).

### Per-Connection Client Overrides

When a client connects, they can append arguments after `--` in the SSH command to override the server's defaults **for their session only**:

```bash
# Use a different model for this connection
ssh -p 2222 kali@host -- --model qwen3-coder

# Enable verbose logging for this session only
ssh -p 2222 kali@host -- --verbose

# Narrow the network policy for this session
ssh -p 2222 kali@host -- --allow 10.10.0.0/16 --disallow 10.10.0.1
```

Any flags not specified by the client fall back to the server's base configuration. The `--port`, `--password`, and `--host-key` flags are server-only and cannot be overridden per-connection.

### `asyncssh` Dependency

The SSH server requires the `asyncssh` Python package, which is listed in `requirements.txt`. It is installed automatically by `./install_prerequisites.sh` or by running:

```bash
./start_server.sh --build
```

If `asyncssh` is not present in the virtualenv, `cli-server.py` will fail to import and the server will not start. See the [SSH Server Troubleshooting](server.md#troubleshooting) section for details.