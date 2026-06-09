import asyncio
import asyncssh
import sys
import os
import argparse
import logging
from pathlib import Path

# Set up logging for asyncssh
logging.basicConfig(level=logging.INFO)

import cli
from mcp_client import MCPSession
from session_logger import make_run_id

class StreamAdapter:
    """Adapts an asyncssh process stream (which is a subclass of SSHWriter/SSHReader)
    so that it can be used by TerminalEventHandler which expects a minimal file-like API."""
    def __init__(self, process: asyncssh.SSHServerProcess):
        self.process = process
        
    def write(self, data: str):
        # asyncssh process.stdout.write is actually synchronous
        self.process.stdout.write(data)
        
    def flush(self):
        pass  # asyncssh handles flushing inherently
        
    def isatty(self) -> bool:
        # PTYs provide a terminal-like environment
        return bool(self.process.get_terminal_type())
        
    def fileno(self):
        raise NotImplementedError("SSH streams do not have file descriptors.")
        
    @property
    def stream_in(self):
        return self.process.stdin
        
    @property
    def stream_out(self):
        return self

class SSHAgentServer(asyncssh.SSHServer):
    def __init__(self, password: str):
        self._password = password

    def connection_made(self, conn: asyncssh.SSHServerConnection):
        print(f"SSH connection received from {conn.get_extra_info('peername')[0]}.")

    def connection_lost(self, exc: Exception):
        if exc:
            print(f"SSH connection error: {exc}")

    def begin_auth(self, username: str):
        # We allow any username for now, just check password
        return True

    def password_auth_supported(self):
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return password == self._password

    def pty_requested(self, term_type: str, term_size: tuple[int, int, int, int], term_modes: dict) -> bool:
        # We require a PTY for the terminal UI
        return True
        
    def shell_requested(self) -> bool:
        return True
        
    def exec_requested(self, command: str) -> bool:
        return True

async def handle_client(process: asyncssh.SSHServerProcess, base_args: argparse.Namespace):
    """Handles an individual SSH client session."""
    stream = StreamAdapter(process)
    
    # Send a welcome message
    process.stdout.write("Welcome to CyberAgentFlow SSH Server.\n")
    
    # Parse the command provided by the client, or default to base args
    client_cmd = process.command
    parser = cli._create_parser()
    
    if client_cmd:
        import shlex
        try:
            cmd_parts = shlex.split(client_cmd)
            args = parser.parse_args(cmd_parts)
        except SystemExit as e:
            process.stdout.write(f"Command parse error. Exit code {e.code}\n")
            process.exit(1)
            return
    else:
        # Default to a chat session using base args if no command passed
        # We need to construct a valid Namespace for the chat command
        # The easiest way is to clone base_args and set command='chat'
        args = argparse.Namespace(**vars(base_args))
        args.command = "chat"
    
    # Override settings from base_args if they aren't explicitly provided by client
    # (Simplified merging: if a client didn't specify it, take it from base_args)
    for k, v in vars(base_args).items():
        if getattr(args, k, None) is None:
            setattr(args, k, v)
            
    # Re-validate session args
    try:
        cli._validate_session_args(args)
    except ValueError as e:
        process.stdout.write(f"Configuration error: {e}\n")
        process.exit(1)
        return

    # Start the session
    try:
        event_handler = cli.TerminalEventHandler(
            tool_output_chars=args.tool_output_chars,
            verbose=args.verbose,
            stream_out=stream,
            stream_in=process.stdin
        )
        
        # We monkeypatch the _term_size method on this specific handler instance
        # so it pulls the dimensions directly from the SSH PTY instead of the host OS
        def _ssh_term_size():
            width, height, _, _ = process.get_terminal_size()
            return height or 24, width or 80
        event_handler._term_size = _ssh_term_size
        
        session = await cli._start_session(args, event_handler)
    except Exception as e:
        process.stdout.write(f"Failed to start session: {e}\n")
        process.exit(1)
        return
        
    try:
        if args.command == "chat":
            await cli._chat(args, event_handler=event_handler, session=session)
        elif args.command == "run":
            await cli._run_prompt(args, event_handler=event_handler, session=session)
    except Exception as e:
        process.stdout.write(f"\nSession crashed: {e}\n")
    finally:
        await session.stop()
        process.exit(0)

async def start_server(port: int, password: str, host_key: str = None):
    # If no host key provided, we generate an ephemeral one for testing
    if not host_key:
        print("Generating ephemeral SSH host key...")
        key = asyncssh.generate_private_key('ssh-rsa')
        server_keys = [key]
    else:
        server_keys = [host_key]

    print(f"Starting CyberAgentFlow SSH Server on port {port}...")
    await asyncssh.listen(
        '', port,
        server_host_keys=server_keys,
        server_factory=lambda: SSHAgentServer(password),
        process_factory=lambda proc: handle_client(proc, args)
    )

if __name__ == '__main__':
    parser = cli._create_parser()
    # We add server-specific arguments to the base parser
    # But wait, cli._create_parser requires a subcommand (chat/run).
    # We will create a custom server parser that inherits the session args.
    server_parser = argparse.ArgumentParser(description="CyberAgentFlow SSH Server")
    server_parser.add_argument("--port", type=int, default=2222, help="Port to listen on (default: 2222)")
    server_parser.add_argument("--password", type=str, default="admin", help="SSH login password (default: admin)")
    server_parser.add_argument("--host-key", type=str, help="Path to SSH host private key (default: ephemeral key)")
    cli._add_session_args(server_parser)
    
    args = server_parser.parse_args()
    
    # Use cli.py's internal config resolver to apply JSON + ENV vars
    # We must temporarily pretend we have a command so _resolve_session_args doesn't fail
    args.command = "chat"
    args = cli._resolve_session_args(args)
    args.command = None
    
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(start_server(args.port, args.password, args.host_key))
        loop.run_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
