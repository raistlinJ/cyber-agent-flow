# CyberAgentFlow SSH Server

The CyberAgentFlow SSH server (`cli-server.py`) turns the terminal CLI into a **multi-user, remotely accessible service**. It is a self-contained Python SSH daemon built on [`asyncssh`](https://asyncssh.readthedocs.io/) — it does not touch or replace your operating system's normal SSH daemon.

When a client connects, they are dropped directly into the familiar `caf>` interface with the full persistent bottom bar, slash-command support, and live tool execution streaming — identical to the local CLI experience but over a secured SSH channel.

---

## How It Works

1. You start `cli-server.py` on the server machine, specifying a port and password.
2. Clients connect with any standard SSH client: `ssh -p 2222 user@your-server-ip`.
3. After password authentication, the client enters the `caf>` chat REPL immediately — no shell, no bash, just the agent.
4. Each connection gets its own independent MCP session, so multiple users can run concurrent sessions without interfering with each other.

Because it is a real SSH server with PTY negotiation, the client's terminal size is automatically detected and used to lay out the split-screen UI correctly. Resize your terminal window and the layout adjusts.

---

## Prerequisites

- All [base prerequisites](../README.md#installation--setup) must be satisfied on the server machine.
- `asyncssh` must be installed (it is included in `requirements.txt`):
  ```bash
  ./install_prerequisites.sh
  # or manually:
  pip install asyncssh
  ```

---

## Starting the Server

Use the `start_server.sh` wrapper (recommended — it uses the project virtualenv):

```bash
./start_server.sh --port 2222 --password mysecret
```

Or install dependencies and run directly:

```bash
./start_server.sh --build  # installs/updates requirements into venv first
./start_server.sh --port 2222 --password mysecret
```

---

## Server Options

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | `2222` | TCP port to listen on |
| `--password` | `admin` | SSH login password (same for all users) |
| `--host-key` | *(ephemeral)* | Path to a persistent SSH host private key file. If omitted, a new key is generated each startup (clients will see a host-key-changed warning on reconnect). |
| `--model` | *(required)* | LLM model to use (e.g. `llama3`, `qwen3-coder`) |
| `--config` | `configs/cli.json` | Base config file. All session-level flags accepted by the CLI are also accepted here. |
| All CLI flags | | See [CLI docs](cli.md#configuration) for the full list |

### Persisting the Host Key

Generate a key once and reuse it on every restart so clients don't see warnings:

```bash
ssh-keygen -t ed25519 -f server_host_key -N ""
./start_server.sh --host-key server_host_key --port 2222 --password mysecret
```

---

## Connecting as a Client

Any standard SSH client works:

```bash
# Basic connection — uses server's default settings
ssh -p 2222 kali@your-server-ip
```

> The username can be anything. Authentication is password-only and the same password applies to all users.

### Overriding Settings Per-Connection

Clients can append arguments after `--` to override the server's default config for their session:

```bash
# Use a different model for this session
ssh -p 2222 kali@your-server-ip -- --model qwen3-coder

# Enable verbose logging for this session only
ssh -p 2222 kali@your-server-ip -- --verbose

# Narrow the network policy for this session
ssh -p 2222 kali@your-server-ip -- --allow 10.0.0.0/8 --disallow 10.0.0.1
```

Arguments not specified by the client fall back to the server's defaults.

---

## Skipping the Host Key Check (Lab Use)

For local lab environments where you trust the server, skip the host key check:

```bash
ssh -p 2222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null kali@localhost
```

---

## Security Notes

> [!WARNING]
> `cli-server.py` is designed for **trusted lab and internal network use**. It uses password-only authentication with a single shared password. Do not expose it directly to the public internet without additional hardening (firewall rules, VPN, key-based auth, etc.).

- All traffic is encrypted by the SSH transport layer.
- The password is passed on the command line, which means it may appear in `ps` output. For production use, consider reading it from an environment variable or config file.
- Each client session starts a fresh MCP session and LLM context — sessions are isolated from each other.
- Tool execution happens under the server process's OS user account. Ensure the server user has appropriate (but not excessive) privileges.

---

## Running as a Background Service

To keep the server running after you log out, use `nohup` or a `screen`/`tmux` session:

```bash
# With nohup
nohup ./start_server.sh --port 2222 --password mysecret > server.log 2>&1 &

# With screen
screen -S caf-server
./start_server.sh --port 2222 --password mysecret
# Ctrl+A, D to detach
```

---

## Relationship to the Local CLI

The SSH server uses the exact same `cli.py` code path, `MCPSession` engine, `mcp_kali.py` tool server, and transcript format as the local CLI. The only difference is that stdin/stdout are routed through the SSH channel instead of the local terminal. All slash commands, tab completion, `/force_analyze`, `/cancel`, `--continue`, and session transcripts work identically.

See the [CLI documentation](cli.md) for the full list of in-session commands and options.


## Troubleshooting

### "Session stops immediately after `/force_analyze`"
This was a bug with how Python 3.8+ handles `CancelledError` during reader teardown. It has been fixed in the latest version. Ensure you have pulled the latest code.

### "Prompt appears on server console, not client"
This means you likely ran `cli-server.py` directly with an older version of the codebase, or I/O isn't routing correctly. Update to the latest code and run `./start_server.sh --port 2222 --password admin` instead.

### "coroutine 'SSHReader.readline' was never awaited"
This is a `RuntimeWarning` indicating that the async SSH streams are not being awaited properly. It is usually caused by running an older version of `cli.py` or a mismatched `asyncssh` installation. Run `./start_server.sh --build` to reinstall dependencies into the virtual environment, and ensure you have the latest code.

### "asyncssh: module not found"
The `asyncssh` package is not installed in the current environment. Run `./start_server.sh --build` to automatically install it into the project's virtual environment.
