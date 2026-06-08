# Configuration Guide

CyberAgentFlow uses a JSON-based configuration system for both CLI and WebUI sessions. This document describes all available configuration options.

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
| `api_key_env` | string | `"MCP_API_KEY"` | Environment variable name containing the API key (safer than `api_key`) |
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

## Environment Variables

The following environment variables can be used as defaults:

| Variable | Default Value |
|----------|---------------|
| `MCP_LLM_PROVIDER` | `ollama_direct` |
| `MCP_OLLAMA_URL` | `http://localhost:11434` |
| `MCP_MODEL` | (empty - must be set via config or CLI) |
| `MCP_API_KEY` | (empty - used when `api_key_env` references this) |

## WebUI Configuration

The WebUI uses the same configuration structure. Settings are saved per-session and persisted to `runs/<run_id>/` directories. The Configuration tab in the WebUI allows you to:

1. Set provider URL and API key
2. Select model from available models
3. Adjust context window and max turns
4. Configure network policy
5. Set scope and urgency defaults
6. Enable keylogging and other loggers