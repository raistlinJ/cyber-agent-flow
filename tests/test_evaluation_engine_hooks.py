"""Shared engine controls used by the separate evaluation application."""
import pytest


@pytest.mark.asyncio
async def test_excluded_tool_blocked_before_dispatch():
    from mcp_client import MCPSession
    from unittest.mock import AsyncMock, MagicMock
    session = MCPSession(ollama_url='http://localhost', model='test', server_command='unused', allowed_tools=[])
    session._session = MagicMock()
    session._session.call_tool = AsyncMock()
    session._logger = MagicMock()
    assert (await session.call_tool_direct('shell', {}))['success'] is False
    await session._execute_tool_calls([{'function': {'name': 'shell', 'arguments': {}}}], [], None)
    session._session.call_tool.assert_not_called()
    assert 'excluded' in session.messages[-1]['content']



def test_hidden_policy_prompt_rebuild_and_enforcement():
    from mcp_client import MCPSession, _evaluate_network_policy
    policy = {'allow': ['10.78.0.0/24'], 'disallow': ['10.78.0.128/25']}
    session = MCPSession(ollama_url='http://localhost', model='test', server_command='unused',
                         network_policy=policy, reveal_network_policy=False)
    initial = session.messages[0]['content']
    rebuilt = session._build_initial_system_prompt('10.78.0.0/24', '10.78.0.128/25')
    assert '10.78.' not in initial + rebuilt
    assert _evaluate_network_policy(policy, {'target': '10.78.0.10'})[0]
    for target in ('10.78.0.200', '10.79.0.10'):
        allowed, message = _evaluate_network_policy(policy, {'target': target})
        assert not allowed
        assert '10.78.' not in message and '10.79.' not in message
    normal = MCPSession(ollama_url='http://localhost', model='test', server_command='unused',
                        network_policy=policy)
    assert '10.78.0.0/24' in normal.messages[0]['content']

