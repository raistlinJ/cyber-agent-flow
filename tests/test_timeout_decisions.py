import asyncio
import json
import os
import sys


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TestToolTimeoutDecisions:
    def test_wait_timeout_decision_writes_selected_interval(self, tmp_path, monkeypatch):
        import mcp_client

        response_path = tmp_path / "tool_timeout_response.json"
        monkeypatch.setattr(mcp_client, "_tool_timeout_response_path", lambda run_id: str(response_path))

        session = mcp_client.MCPSession(
            ollama_url="http://localhost:11434",
            model="test-model",
            server_command="python mcp_kali.py",
            run_id="test-run",
        )
        session._pending_tool_timeout_decision = {
            "request_id": "req-123",
            "tool": "nmap",
            "command": "nmap 127.0.0.1",
        }

        assert session.resolve_tool_timeout_decision("wait", wait_seconds=60) is True

        payload = json.loads(response_path.read_text())
        assert payload["request_id"] == "req-123"
        assert payload["action"] == "wait"
        assert payload["wait_seconds"] == 60

    def test_invalid_wait_timeout_decision_is_rejected(self, tmp_path, monkeypatch):
        import mcp_client

        response_path = tmp_path / "tool_timeout_response.json"
        monkeypatch.setattr(mcp_client, "_tool_timeout_response_path", lambda run_id: str(response_path))

        session = mcp_client.MCPSession(
            ollama_url="http://localhost:11434",
            model="test-model",
            server_command="python mcp_kali.py",
            run_id="test-run",
        )
        session._pending_tool_timeout_decision = {
            "request_id": "req-456",
            "tool": "nmap",
            "command": "nmap 127.0.0.1",
        }

        assert session.resolve_tool_timeout_decision("wait", wait_seconds=45) is False
        assert not response_path.exists()

    def test_background_timeout_decision_writes_background_action(self, tmp_path, monkeypatch):
        import mcp_client

        response_path = tmp_path / "tool_timeout_response.json"
        monkeypatch.setattr(mcp_client, "_tool_timeout_response_path", lambda run_id: str(response_path))

        session = mcp_client.MCPSession(
            ollama_url="http://localhost:11434",
            model="test-model",
            server_command="python mcp_kali.py",
            run_id="test-run",
        )
        session._pending_tool_timeout_decision = {
            "request_id": "req-789",
            "tool": "tcpdump",
            "command": "tcpdump -ni eth0",
        }

        assert session.resolve_tool_timeout_decision("background") is True

        payload = json.loads(response_path.read_text())
        assert payload["request_id"] == "req-789"
        assert payload["action"] == "background"
        assert "wait_seconds" not in payload

    def test_background_timeout_decision_sets_turn_completion_flag(self, tmp_path, monkeypatch):
        import mcp_client

        response_path = tmp_path / "tool_timeout_response.json"
        monkeypatch.setattr(mcp_client, "_tool_timeout_response_path", lambda run_id: str(response_path))

        session = mcp_client.MCPSession(
            ollama_url="http://localhost:11434",
            model="test-model",
            server_command="python mcp_kali.py",
            run_id="test-run",
        )
        session._pending_tool_timeout_decision = {
            "request_id": "req-999",
            "tool": "tcpdump",
            "command": "tcpdump -ni eth0",
        }

        assert session.resolve_tool_timeout_decision("background") is True
        assert session._pending_background_turn_completion == {
            "tool": "tcpdump",
            "command": "tcpdump -ni eth0",
            "request_id": "req-999",
        }
        assert session._consume_background_turn_completion("other-tool") is False
        assert session._pending_background_turn_completion == {
            "tool": "tcpdump",
            "command": "tcpdump -ni eth0",
            "request_id": "req-999",
        }
        assert session._consume_background_turn_completion("tcpdump") is True
        assert session._pending_background_turn_completion is None


class TestInteractiveSessionDiscovery:
    def test_discover_interactive_sessions_emits_isess_created_from_list_output(self):
        import mcp_client

        events = []

        class FakeText:
            def __init__(self, text):
                self.text = text

        class FakeSession:
            async def call_tool(self, name, arguments):
                assert name == "interactive_session_list"
                return type("FakeResult", (), {
                    "content": [
                        FakeText(
                            "isess-001: active; kind=interactive; writable=yes; tool=shell_dangerous; pending_chars=0; command=/bin/sh"
                        )
                    ]
                })()

        session = mcp_client.MCPSession(
            ollama_url="http://localhost:11434",
            model="test-model",
            server_command="python mcp_kali.py",
            run_id="test-run",
            event_callback=events.append,
        )
        session._session = FakeSession()

        asyncio.run(session._discover_interactive_sessions())

        assert session._active_interactive_sessions == {"isess-001"}
        assert events == [{
            "type": "isess_created",
            "session_id": "isess-001",
            "tool": "shell_dangerous",
            "args_summary": "",
            "writable": True,
            "session_kind": "interactive",
        }]