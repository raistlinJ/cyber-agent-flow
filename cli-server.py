#!/usr/bin/env python3
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
from prompt_toolkit.contrib.ssh.server import PromptToolkitSSHSession
from prompt_toolkit.shortcuts import print_formatted_text


class CyberAgentFlowSSHSession(PromptToolkitSSHSession):
    def __init__(self, base_args):
        self.base_args = base_args
        self.client_cmd = None
        super().__init__(self.handle_client, enable_cpr=False)

    def exec_requested(self, command: str) -> bool:
        self.client_cmd = command
        return True

    async def handle_client(self):
        # This runs inside the app_session context!
        # sys.stdout and sys.stdin are redirected to the SSH stream!
        print("Welcome to CyberAgentFlow SSH Server.")
        
        # Parse the command provided by the client, or default to base args
        parser = cli._create_parser()
        
        if self.client_cmd:
            import shlex
            try:
                cmd_parts = shlex.split(self.client_cmd)
                # If the user only provided flags (e.g. --context-window), default to chat command
                if cmd_parts and cmd_parts[0] not in ("chat", "run", "list-runs"):
                    cmd_parts.insert(0, "chat")
                args = parser.parse_args(cmd_parts)
            except SystemExit as e:
                print(f"Command parse error. Exit code {e.code}")
                return
        else:
            args = argparse.Namespace(**vars(self.base_args))
            args.command = "chat"
            
        for k, v in vars(self.base_args).items():
            if getattr(args, k, None) is None:
                setattr(args, k, v)
                
        prompt_parts = list(getattr(args, "prompt", []) or [])
        if prompt_parts and prompt_parts[0] == "--":
            prompt_parts = prompt_parts[1:]
        args.prompt_text = " ".join(prompt_parts).strip() if prompt_parts else ""
        
        try:
            cli._validate_session_args(args)
        except ValueError as e:
            print(f"Configuration error: {e}")
            return

        import sys
        event_handler = cli.TerminalEventHandler(
            tool_output_chars=args.tool_output_chars,
            verbose=args.verbose,
            stream_out=sys.stdout,
            stream_in=sys.stdin
        )
        
        # prompt_toolkit handles terminal size natively, so we just return it
        def _ssh_term_size():
            from prompt_toolkit.application.current import get_app_session
            output = get_app_session().output
            size = output.get_size()
            return size.rows, size.columns
            
        event_handler._term_size = _ssh_term_size
        
        try:
            session = await cli._start_session(args, event_handler)
        except Exception as e:
            print(f"Failed to start session: {e}")
            return
            
        try:
            if args.command == "chat":
                await cli._chat(args, event_handler=event_handler, session=session)
            elif args.command == "run":
                await cli._run_prompt(args, event_handler=event_handler, session=session)
        except Exception as e:
            import traceback
            err = traceback.format_exc()
            print(f"\nSession crashed: {e}\n{err}\n")
        finally:
            await session.stop()

class SSHAgentServer(asyncssh.SSHServer):
    def __init__(self, password: str):
        self._password = password

    def password_auth_supported(self):
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return password == self._password

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
        session_factory=lambda: CyberAgentFlowSSHSession(args)
    )

if __name__ == '__main__':
    import traceback

    server_parser = argparse.ArgumentParser(description="CyberAgentFlow SSH Server")
    server_parser.add_argument("--port", type=int, default=2222, help="Port to listen on (default: 2222)")
    server_parser.add_argument("--password", type=str, default="admin", help="SSH login password (default: admin)")
    server_parser.add_argument("--host-key", type=str, dest="host_key", help="Path to SSH host private key (default: ephemeral key)")
    cli._add_session_args(server_parser)

    args = server_parser.parse_args()

    # Use cli.py's internal config resolver to apply JSON + ENV vars
    args.command = "chat"
    args = cli._resolve_session_args(args)
    args.command = None

    async def _main():
        await start_server(args.port, args.password, args.host_key)
        # Keep the server running indefinitely
        await asyncio.get_running_loop().create_future()

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nShutting down server.")

