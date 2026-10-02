import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
import mcp_client


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled', [False, True])
async def test_hints_continue_same_loop_within_budget(monkeypatch, enabled):
    session = mcp_client.MCPSession(ollama_url='http://localhost:11434', model='test',
                                  server_command='unused', max_turns=3)
    session._started = True
    session._logger = MagicMock()
    session._client = MagicMock()
    session._chat_with_transient_retry = AsyncMock(return_value={'message': {'content': 'stuck'}})
    monkeypatch.setattr(mcp_client, '_maybe_summarise', AsyncMock(side_effect=lambda client, model, messages, *args: messages))
    callback = AsyncMock(return_value='Inspect the next link')
    await session.chat('task', **({'progress_callback': callback} if enabled else {}))
    assert session._chat_with_transient_retry.await_count == (3 if enabled else 1)
    assert callback.await_count == (2 if enabled else 0)
    if enabled:
        assert [c.args[0]['turn'] for c in callback.await_args_list] == [1, 2]
        assert sum(m.get('content') == 'Evaluator assistance: Inspect the next link' for m in session.messages) == 2


@pytest.mark.asyncio
async def test_no_hint_after_cancel():
    session = mcp_client.MCPSession(ollama_url='http://localhost', model='test', server_command='unused')
    session._started = True
    session._logger = MagicMock()
    callback = AsyncMock()
    cancel = asyncio.Event(); cancel.set()
    await session.chat('task', cancel_event=cancel, progress_callback=callback)
    callback.assert_not_called()
