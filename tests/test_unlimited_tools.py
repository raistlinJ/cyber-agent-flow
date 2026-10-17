"""Unlimited tool actions skip elapsed/idle checkpoints but retain cancellation."""
import asyncio
import sys
import pytest
import mcp_kali


@pytest.mark.parametrize('logged,interactive',[(False,False),(True,False),(True,True)])
def test_no_timeout_waits_past_elapsed_and_idle_checkpoints(tmp_path,monkeypatch,logged,interactive):
    monkeypatch.setattr(mcp_kali,'_run_dir_for_current_session',lambda:str(tmp_path) if logged else None)
    monkeypatch.setattr(mcp_kali,'_clear_timeout_control_files',lambda:None)
    monkeypatch.setattr(mcp_kali,'_cancel_requested',lambda:False)
    monkeypatch.setattr(mcp_kali,'_tool_stop_requested',lambda:False)
    monkeypatch.setattr(mcp_kali,'_looks_like_preservable_interactive_session',lambda *a:False)
    monkeypatch.setattr(mcp_kali,'_await_timeout_decision',lambda *a,**k:pytest.fail('Unlimited tools must not reach a timeout checkpoint'))
    result=mcp_kali._run_subprocess_with_timeout_prompt([sys.executable,'-c','import time;time.sleep(1.1);print("finished")'],0,'test',{},preserve_interactive=interactive,first_checkpoint_seconds=1,idle_timeout_seconds=1)
    assert result['returncode']==0 and 'finished' in result['stdout']
    assert not result['timed_out_kill']


@pytest.mark.parametrize('interactive',[False,True])
def test_unlimited_tool_can_still_be_cancelled(tmp_path,monkeypatch,interactive):
    monkeypatch.setattr(mcp_kali,'_run_dir_for_current_session',lambda:str(tmp_path))
    monkeypatch.setattr(mcp_kali,'_clear_timeout_control_files',lambda:None)
    monkeypatch.setattr(mcp_kali,'_cancel_requested',lambda:True)
    monkeypatch.setattr(mcp_kali,'_looks_like_preservable_interactive_session',lambda *a:False)
    result=mcp_kali._run_subprocess_with_timeout_prompt([sys.executable,'-c','import time;time.sleep(30)'],0,'test',{},preserve_interactive=interactive)
    assert result['cancelled']


def test_global_no_timeout_overrides_catalog_checkpoint_and_wrapper(monkeypatch):
    captured=[]
    monkeypatch.setenv('MCP_TOOL_TIMEOUT','0')
    monkeypatch.setattr(mcp_kali,'_NETWORK_POLICY',{'allow':['*'],'disallow':[]})
    monkeypatch.setattr(mcp_kali,'_get_tools_config',lambda:{'tools':[dict(name='probe',command='timeout',base_args=['{timeout}','echo','ok'],timeout_seconds=45)]})
    def execute(cmd,seconds,*args,**kwargs):
        captured.append((cmd,seconds));return dict(stdout='ok',stderr='',returncode=0,duration_ms=1)
    monkeypatch.setattr(mcp_kali,'_run_subprocess_with_timeout_prompt',execute)
    asyncio.run(mcp_kali.call_tool('probe',{}))
    assert captured[0][0][:2]==['timeout','0'] and captured[0][1]==0
