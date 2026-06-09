import pytest
import argparse
from unittest.mock import patch, MagicMock
from cli import _start_session
from mcp_client import MCPSession

@pytest.mark.asyncio
@patch("cli.load_session_list")
@patch("cli.MCPSession.start")
async def test_start_session_continue_by_index(mock_start, mock_load, monkeypatch):
    mock_load.return_value = [
        {"run_id": "run_0"},
        {"run_id": "run_1"},
        {"run_id": "run_2"},
    ]
    
    args = argparse.Namespace(
        provider="ollama_direct",
        url="http://localhost",
        api_key=None,
        no_ssl_verify=False,
        model="test-model",
        server_command="cli",
        tools_config=None,
        context_window=8192,
        max_turns=5,
        tool_timeout=120,
        network_policy={"allow": ["*"], "disallow": []},
        continue_run="1",
        no_scope=True,
        no_urgency=True,
    )
    
    event_handler = MagicMock()
    session = await _start_session(args, event_handler)
    assert session.run_id == "run_1"

@pytest.mark.asyncio
@patch("cli.load_session_list")
@patch("cli.MCPSession.start")
async def test_start_session_continue_by_id(mock_start, mock_load, monkeypatch):
    mock_load.return_value = [
        {"run_id": "run_0"},
        {"run_id": "test-uuid-here"},
    ]
    
    args = argparse.Namespace(
        provider="ollama_direct",
        url="http://localhost",
        api_key=None,
        no_ssl_verify=False,
        model="test-model",
        server_command="cli",
        tools_config=None,
        context_window=8192,
        max_turns=5,
        tool_timeout=120,
        network_policy={"allow": ["*"], "disallow": []},
        continue_run="test-uuid",
        no_scope=True,
        no_urgency=True,
    )
    
    event_handler = MagicMock()
    session = await _start_session(args, event_handler)
    assert session.run_id == "test-uuid-here"

import os
import json
import tempfile
from session_logger import SessionLogger

def test_session_logger_save_load_messages():
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = SessionLogger("test-run", {}, base_dir=tmpdir)
        
        # Test empty load
        assert logger.load_messages() == []
        
        # Test save and load simple messages
        messages = [
            {"role": "system", "content": "hello world"},
            {"role": "user", "content": "how are you?"}
        ]
        logger.save_messages(messages)
        
        loaded = logger.load_messages()
        assert len(loaded) == 2
        assert loaded[0]["content"] == "hello world"
        
        # Test complex nested structures (like Anthropic tool calls)
        complex_msgs = [
            {"role": "assistant", "content": [{"type": "text", "text": "I will do that."}, {"type": "tool_use", "id": "123", "name": "foo", "input": {"bar": 1}}]}
        ]
        logger.save_messages(complex_msgs)
        loaded2 = logger.load_messages()
        assert len(loaded2) == 1
        assert loaded2[0]["content"][0]["type"] == "text"
        assert loaded2[0]["content"][1]["name"] == "foo"

@pytest.mark.asyncio
@patch("cli.load_session_list")
@patch("cli.MCPSession.start")
async def test_start_session_continue_out_of_bounds(mock_start, mock_load, monkeypatch, capsys):
    mock_load.return_value = [{"run_id": "run_0"}]
    args = argparse.Namespace(
        provider="ollama_direct",
        url="http://localhost",
        api_key=None,
        no_ssl_verify=False,
        model="test-model",
        server_command="cli",
        tools_config=None,
        context_window=8192,
        max_turns=5,
        tool_timeout=120,
        network_policy={"allow": ["*"], "disallow": []},
        continue_run="5",  # out of bounds
        no_scope=True,
        no_urgency=True,
    )
    event_handler = MagicMock()
    with pytest.raises(SystemExit) as exc:
        await _start_session(args, event_handler)
    assert exc.value.code == 1
    
    out, err = capsys.readouterr()
    assert "out of range" in out
