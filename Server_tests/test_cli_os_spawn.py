import os
import sys
import pytest
from unittest.mock import patch, mock_open, MagicMock

# Make sure the server package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from guga.cli import spawn_background_server


def test_spawn_background_server_os_kwargs():
    """Test that OS variable changes Popen kwargs correctly."""
    
    with patch("guga.cli.subprocess.Popen") as mock_popen, \
         patch("builtins.open", mock_open()), \
         patch("os.makedirs"), \
         patch("guga.cli.time.sleep"), \
         patch("guga.cli.os.kill"):
        
        # Mock Popen return value to have a pid
        mock_popen.return_value = MagicMock(pid=1234)
        
        # Test default/Linux behavior (OS not set to Windows)
        with patch.dict(os.environ, {"OS": "Linux"}, clear=True):
            spawn_background_server(6769, "lan")
            mock_popen.assert_called_once()
            kwargs = mock_popen.call_args[1]
            assert "start_new_session" in kwargs
            assert kwargs["start_new_session"] is True
            assert "creationflags" not in kwargs

        mock_popen.reset_mock()

        # Test Windows behavior
        with patch.dict(os.environ, {"OS": "Windows"}, clear=True):
            spawn_background_server(6770, "lan")
            mock_popen.assert_called_once()
            kwargs = mock_popen.call_args[1]
            assert "creationflags" in kwargs
            assert kwargs["creationflags"] == 0x00000200
            assert "start_new_session" not in kwargs
