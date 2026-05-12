"""
Tests for the Keylogger feature in AgentFlow

Run with: pytest test_keylogger.py -v
"""

import pytest
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, Mock


# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ============================================================================
# Xdotool Availability Tests
# ============================================================================

class TestCheckXdotoolAvailable:
    """Tests for xdotool availability checking."""

    def test_check_xdotool_available_with_mock(self):
        """Test xdotool check returns expected result with mocked subprocess."""
        from keylogger_daemon import _check_xdotool_available
        
        with patch('keylogger_daemon.subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = '/usr/bin/xdotool\n'
            mock_run.return_value = mock_result
            
            result = _check_xdotool_available()
            assert result is True

    def test_check_xdotool_available_not_found(self):
        """Test xdotool check returns False when not found."""
        from keylogger_daemon import _check_xdotool_available
        
        with patch('keylogger_daemon.subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = ''
            mock_run.return_value = mock_result
            
            result = _check_xdotool_available()
            assert result is False

    def test_check_xdotool_available_exception(self):
        """Test xdotool check returns False on exception."""
        from keylogger_daemon import _check_xdotool_available
        
        with patch('keylogger_daemon.subprocess.run') as mock_run:
            mock_run.side_effect = Exception("Command not found")
            
            result = _check_xdotool_available()
            assert result is False


# ============================================================================
# Session Logger Keystrokes Tests
# ============================================================================

class TestSessionLoggerKeystrokes:
    """Tests for session logger keystroke functionality."""

    def test_log_keystrokes_browser(self):
        """Test logging browser keystrokes."""
        from session_logger import SessionLogger
        
        with tempfile.TemporaryDirectory() as tmpdir:
            run_id = 'test_run_123'
            metadata = {'run_id': run_id}
            
            logger = SessionLogger(run_id, metadata, base_dir=tmpdir)
            
            keystrokes = [
                {'timestamp': '2024-01-01T00:00:00Z', 'key': 'a', 'type': 'press'},
                {'timestamp': '2024-01-01T00:00:01Z', 'key': 'b', 'type': 'release'},
            ]
            
            logger.log_keystrokes(keystrokes, source='browser')
            
            log_path = os.path.join(logger.run_dir, 'keystrokes', 'browser_log.jsonl')
            assert os.path.exists(log_path)
            
            with open(log_path) as f:
                lines = f.readlines()
                assert len(lines) == 2

    def test_log_keystrokes_system(self):
        """Test logging system keystrokes."""
        from session_logger import SessionLogger
        
        with tempfile.TemporaryDirectory() as tmpdir:
            run_id = 'test_run_123'
            metadata = {'run_id': run_id}
            
            logger = SessionLogger(run_id, metadata, base_dir=tmpdir)
            
            keystrokes = [
                {
                    'timestamp': '2024-01-01T00:00:00Z',
                    'key': 'n',
                    'type': 'press',
                    'window': {'title': 'Terminal', 'application': 'Terminal.app'}
                },
            ]
            
            logger.log_keystrokes(keystrokes, source='system')
            
            log_path = os.path.join(logger.run_dir, 'keystrokes', 'system_log.jsonl')
            assert os.path.exists(log_path)

    def test_get_keystrokes_browser(self):
        """Test retrieving browser keystrokes."""
        from session_logger import SessionLogger
        
        with tempfile.TemporaryDirectory() as tmpdir:
            run_id = 'test_run_123'
            metadata = {'run_id': run_id}
            
            logger = SessionLogger(run_id, metadata, base_dir=tmpdir)
            
            keystrokes_dir = os.path.join(logger.run_dir, 'keystrokes')
            os.makedirs(keystrokes_dir)
            
            with open(os.path.join(keystrokes_dir, 'browser_log.jsonl'), 'w') as f:
                f.write('{"key": "test", "timestamp": "2024-01-01T00:00:00Z"}\n')
            
            result = logger.get_keystrokes(source='browser')
            
            assert 'browser' in result
            assert len(result['browser']) == 1
            assert result['browser'][0]['key'] == 'test'

    def test_get_keystrokes_both_sources(self):
        """Test retrieving both browser and system keystrokes."""
        from session_logger import SessionLogger
        
        with tempfile.TemporaryDirectory() as tmpdir:
            run_id = 'test_run_123'
            metadata = {'run_id': run_id}
            
            logger = SessionLogger(run_id, metadata, base_dir=tmpdir)
            
            keystrokes_dir = os.path.join(logger.run_dir, 'keystrokes')
            os.makedirs(keystrokes_dir)
            
            with open(os.path.join(keystrokes_dir, 'browser_log.jsonl'), 'w') as f:
                f.write('{"key": "browser_key"}\n')
            
            with open(os.path.join(keystrokes_dir, 'system_log.jsonl'), 'w') as f:
                f.write('{"key": "system_key"}\n')
            
            result = logger.get_keystrokes()
            
            assert 'browser' in result
            assert 'system' in result
            assert len(result['browser']) == 1
            assert len(result['system']) == 1

    def test_get_keystrokes_empty(self):
        """Test retrieving keystrokes when none exist."""
        from session_logger import SessionLogger
        
        with tempfile.TemporaryDirectory() as tmpdir:
            run_id = 'test_run_123'
            metadata = {'run_id': run_id}
            
            logger = SessionLogger(run_id, metadata, base_dir=tmpdir)
            
            result = logger.get_keystrokes()
            
            assert 'browser' in result
            assert 'system' in result
            assert len(result['browser']) == 0
            assert len(result['system']) == 0


# ============================================================================
# Flask API Tests
# ============================================================================

class TestKeyloggerAPI:
    """Tests for keylogger API endpoints."""

    @pytest.fixture
    def app(self):
        """Create test Flask app."""
        from app import app
        
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        
        with patch('app.start_keylogger'):
            with patch('app.stop_keylogger'):
                with patch('app.pause_keylogger'):
                    with patch('app.resume_keylogger'):
                        with patch('app.get_keylogger_status'):
                            with patch('app.check_keylogger_prerequisites'):
                                yield app

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return app.test_client()

    def test_keylogger_status_endpoint(self, client):
        """Test keylogger status endpoint."""
        with patch('app.get_keylogger_status') as mock_status:
            mock_status.return_value = {
                'running': True,
                'paused': False,
                'run_id': 'test_run',
                'buffer_size': 0
            }
            
            response = client.get('/api/keylogger/status')
            
            assert response.status_code == 200
            data = response.get_json()
            assert data['running'] is True

    def test_keylogger_prerequisites_endpoint(self, client):
        """Test keylogger prerequisites endpoint."""
        with patch('app.check_keylogger_prerequisites') as mock_prereqs:
            mock_prereqs.return_value = {
                'platform': 'Linux',
                'xdotool_available': True,
                'xdotool_note': 'xdotool is installed'
            }
            
            response = client.get('/api/keylogger/prerequisites')
            
            assert response.status_code == 200
            data = response.get_json()
            assert data['platform'] == 'Linux'

    def test_keylogger_start_endpoint(self, client):
        """Test keylogger start endpoint."""
        with patch('app.start_keylogger') as mock_start:
            response = client.post('/api/keylogger/start', 
                                  json={'run_id': 'test_run'})
            
            assert response.status_code == 200
            data = response.get_json()
            assert data['success'] is True

    def test_keylogger_stop_endpoint(self, client):
        """Test keylogger stop endpoint."""
        with patch('app.stop_keylogger') as mock_stop:
            response = client.post('/api/keylogger/stop')
            
            assert response.status_code == 200
            data = response.get_json()
            assert data['success'] is True

    def test_keylogger_pause_endpoint(self, client):
        """Test keylogger pause endpoint."""
        with patch('app.pause_keylogger') as mock_pause:
            response = client.post('/api/keylogger/pause')
            
            assert response.status_code == 200
            data = response.get_json()
            assert data['success'] is True

    def test_keylogger_resume_endpoint(self, client):
        """Test keylogger resume endpoint."""
        with patch('app.resume_keylogger') as mock_resume:
            response = client.post('/api/keylogger/resume')
            
            assert response.status_code == 200
            data = response.get_json()
            assert data['success'] is True

    def test_keylogger_batch_empty(self, client):
        """Test keylogger batch endpoint with empty keystrokes."""
        response = client.post('/api/keylogger/batch',
                              json={'run_id': 'test_run', 'keystrokes': []})
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['logged'] == 0


# ============================================================================
# Integration Tests
# ============================================================================

class TestKeyloggerIntegration:
    """Integration tests for keylogger feature."""

    def test_full_keylogger_flow(self):
        """Test complete keylogger flow from start to retrieval."""
        from session_logger import SessionLogger
        
        with tempfile.TemporaryDirectory() as tmpdir:
            run_id = 'integration_test_run'
            logger = SessionLogger(run_id, {'run_id': run_id}, base_dir=tmpdir)
            
            browser_keystrokes = [
                {'timestamp': '2024-01-01T00:00:00Z', 'key': 'h', 'type': 'press'},
                {'timestamp': '2024-01-01T00:00:01Z', 'key': 'e', 'type': 'press'},
                {'timestamp': '2024-01-01T00:00:02Z', 'key': 'l', 'type': 'press'},
                {'timestamp': '2024-01-01T00:00:03Z', 'key': 'l', 'type': 'press'},
                {'timestamp': '2024-01-01T00:00:04Z', 'key': 'o', 'type': 'press'},
            ]
            logger.log_keystrokes(browser_keystrokes, source='browser')
            
            system_keystrokes = [
                {
                    'timestamp': '2024-01-01T00:01:00Z',
                    'key': 'n',
                    'type': 'press',
                    'window': {'title': 'Terminal', 'application': 'Terminal.app'}
                },
            ]
            logger.log_keystrokes(system_keystrokes, source='system')
            
            keystrokes = logger.get_keystrokes()
            
            assert len(keystrokes['browser']) == 5
            assert len(keystrokes['system']) == 1
            assert keystrokes['system'][0]['window']['title'] == 'Terminal'


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v'])