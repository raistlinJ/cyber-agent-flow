from unittest.mock import AsyncMock, MagicMock

import pytest
import requests

import mcp_client


@pytest.mark.asyncio
@pytest.mark.parametrize('error,expected', [
    (requests.exceptions.ConnectionError('secret endpoint detail'), 'Could not connect to the LLM provider'),
    (requests.exceptions.ConnectTimeout('secret endpoint detail'), 'Connection to the LLM provider timed out'),
])
async def test_provider_failure_is_actionable_without_exposing_exception(error, expected):
    events = []
    session = mcp_client.MCPSession(
        ollama_url='http://localhost', model='test', server_command='unused',
        event_callback=lambda event: events.append(event),
    )
    session._started = True
    session._logger = MagicMock()
    session._run_agent_loop = AsyncMock(side_effect=error)
    session._save_messages = MagicMock()
    await session.chat('task')
    failures = [event for event in events if event.get('type') == 'error']
    assert len(failures) == 1
    assert expected in failures[0]['message']
    assert 'secret endpoint detail' not in failures[0]['message']
