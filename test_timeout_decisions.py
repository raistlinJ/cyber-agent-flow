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