import os
import json
import time
import pytest
from unittest.mock import patch, MagicMock

import mcp_kali
import mcp_client


def test_process_output_text_decodes_timeout_bytes_without_repr_markers():
    assert mcp_kali._process_output_text(b"Starting Nmap\\n") == "Starting Nmap\\n"
    assert mcp_kali._merge_process_stream_text(b"first\\n", b"first\\nsecond\\n") == "first\\nsecond\\n"


def test_tool_status_ipc_flow(tmp_path):
    run_id = "test_run_status"
    
    # Mock the directory methods to point to our tmp_path
    def mock_dir(run_id_arg=None):
        dir_path = os.path.join(tmp_path, mcp_kali._TIMEOUT_CONTROL_DIRNAME)
        os.makedirs(dir_path, exist_ok=True)
        return dir_path

    with patch('mcp_kali._timeout_control_dir', side_effect=mock_dir), \
         patch('mcp_client._tool_timeout_control_dir', side_effect=mock_dir):
        
        # 1. Server writes status
        mcp_kali._write_tool_status("my_tool", 5, 100, 10, "Working...")
        
        # 2. Verify file exists
        status_path = mcp_kali._tool_status_path()
        assert os.path.exists(status_path)
        with open(status_path) as f:
            data = json.load(f)
            assert data["tool"] == "my_tool"
            assert data["elapsed_seconds"] == 5
            assert data["stdout_len"] == 100
            assert data["stderr_len"] == 10
            assert data["extra_msg"] == "Working..."
            
        # 3. Client reads status
        client_status_path = mcp_client._tool_status_path(run_id)
        assert client_status_path == status_path
        
        # Clear files
        mcp_kali._clear_timeout_control_files()
        assert not os.path.exists(status_path)


@pytest.mark.parametrize('logged',[False,True])
def test_binary_service_output_does_not_abort_execution(tmp_path,monkeypatch,logged):
    import sys
    monkeypatch.setattr(mcp_kali,'_run_dir_for_current_session',lambda: str(tmp_path) if logged else None)
    monkeypatch.setattr(mcp_kali,'_clear_timeout_control_files',lambda: None)
    result=mcp_kali._run_subprocess_with_timeout_prompt(
        [sys.executable,'-c','import sys;sys.stdout.buffer.write(bytes([255,65]));sys.exit(7)'],
        5,'curl',{},idle_timeout_seconds=0)
    assert result['stdout']=='\ufffdA'
    assert result['returncode']==7


@pytest.mark.parametrize('code',[0,7,28])
def test_mcp_results_expose_actual_exit_code(monkeypatch,code):
    import asyncio
    monkeypatch.setattr(mcp_kali,'_get_tools_config',lambda:{'tools':[{'name':'curl','command':'curl'}]})
    monkeypatch.setattr(mcp_kali,'_NETWORK_POLICY',{'allow':['10.0.0.0/24'],'disallow':[]})
    monkeypatch.setattr(mcp_kali,'_run_subprocess_with_timeout_prompt',lambda *a,**k:{'stdout':'output','stderr':'failure' if code else '', 'returncode':code,'duration_ms':1})
    result=asyncio.run(mcp_kali.call_tool('curl',{'args':'http://10.0.0.2/'}))
    assert result.structuredContent=={'exit_code':code}
    assert result.isError is (code!=0)
