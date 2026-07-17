import os
import json
import time
import pytest
from unittest.mock import patch, MagicMock

import mcp_kali
import mcp_client

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
