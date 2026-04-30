"""
Tests the GuGa CLI functionality.

This file verifies:
- Help message when no arguments are passed.
- Message mode (-m, --message).
- Run mode (-r, --run).
- Title/Label flags (-t, --title).
- Auto-detection of message vs command.
- Stdin support.
"""

import unittest
from unittest.mock import patch, MagicMock
import threading
import time
import os
import sys
import json
import tempfile
import subprocess
import socketio
from typing import List, Tuple

# Add server directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server')))

# Setup environment to prevent real notifications/systemd interaction during tests
os.environ["ENABLE_OS_NOTIFICATIONS"] = "False"
os.environ["MODE"] = "lan"
os.environ["GUGA_VERBOSE"] = "false"

# Create a temporary trusted devices file for the virtual browser
tmp_dir = tempfile.mkdtemp()
tmp_trusted = os.path.join(tmp_dir, "trusted_devices.json")
with open(tmp_trusted, "w") as f:
    json.dump({
        "browser-cli": {"token": "cli-token", "type": "browser", "expires_at": time.time() + 3600},
        "browser-cli-2": {"token": "cli-token-2", "type": "browser", "expires_at": time.time() + 3600}
    }, f)

from guga import daemon
daemon.TRUSTED_DEVICES_FILE = tmp_trusted
from guga.daemon import app, socketio as server_socketio

class VirtualBrowser:
    def __init__(self, device_id: str, token: str):
        self.sio = socketio.Client()
        self.device_id = device_id
        self.token = token
        self.received_messages = []
        self.sio.on('guga_response', self.on_message)
    
    def on_message(self, data):
        self.received_messages.append(data)
    
    def connect(self, url: str):
        self.sio.connect(f"{url}?device_id={self.device_id}&token={self.token}")
        
    def disconnect(self):
        if self.sio.connected:
            self.sio.disconnect()

class TestGuGaCLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server_port = 6775
        cls.server_url = f"http://127.0.0.1:{cls.server_port}"
        
        def run_server():
            server_socketio.run(app, host="127.0.0.1", port=cls.server_port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)

        cls.server_thread = threading.Thread(target=run_server, daemon=True)
        cls.server_thread.start()
        time.sleep(2)

    def setUp(self):
        self.browser = VirtualBrowser("browser-cli", "cli-token")
        self.browser.connect(self.server_url)
        time.sleep(1)
        # Clear welcome message
        self.browser.received_messages = []

    def tearDown(self):
        self.browser.disconnect()

    def run_cli(self, args: List[str], input_data: str = None) -> Tuple[int, str, str]:
        """Runs the CLI and returns (exit_code, stdout, stderr)"""
        env = os.environ.copy()
        # Ensure we point to the local package
        env["PYTHONPATH"] = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server'))
        
        # We must tell guga which server to use in these tests
        if "--server" not in args:
            args.extend(["--server", str(self.server_port)])
            
        cmd = [sys.executable, "-m", "guga.cli"] + args
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, input=input_data)
        return result.returncode, result.stdout, result.stderr

    def test_no_args_shows_help(self):
        """3. check whether running guga.cli without any arguements shows help or not."""
        code, stdout, stderr = self.run_cli([])
        self.assertEqual(code, 1)
        # Check for the descriptive help message we created
        self.assertIn("GuGa Nexus - Notification & Command Watcher", stderr)
        self.assertIn("Usage:", stderr)
        self.assertIn("man guga", stderr)

    def test_message_modes(self):
        """2. Check both versions of all arguements like -m and --message"""
        # Test -m
        code, stdout, stderr = self.run_cli(["-m", "Hello Short"])
        self.assertEqual(code, 0)
        time.sleep(1)
        self.assertEqual(len(self.browser.received_messages), 1)
        self.assertEqual(self.browser.received_messages[0]["message"], "Hello Short")
        self.browser.received_messages = []

        # Test --message
        code, stdout, stderr = self.run_cli(["--message", "Hello Long"])
        self.assertEqual(code, 0)
        time.sleep(1)
        self.assertEqual(len(self.browser.received_messages), 1)
        self.assertEqual(self.browser.received_messages[0]["message"], "Hello Long")

    def test_run_modes(self):
        """2. Check both versions of all arguements like -r and --run"""
        # Test -r
        code, stdout, stderr = self.run_cli(["-r", "echo", "run-short"])
        self.assertEqual(code, 0)
        time.sleep(1.5)
        self.assertEqual(len(self.browser.received_messages), 1)
        self.assertIn("run-short done", self.browser.received_messages[0]["message"])
        self.browser.received_messages = []

        # Test --run
        code, stdout, stderr = self.run_cli(["--run", "echo", "run-long"])
        self.assertEqual(code, 0)
        time.sleep(1.5)
        self.assertEqual(len(self.browser.received_messages), 1)
        self.assertIn("run-long done", self.browser.received_messages[0]["message"])

    def test_title_modes(self):
        """Check both versions of -t and --title"""
        # Test -t
        code, stdout, stderr = self.run_cli(["Test -t", "-t", "ShortTitle"])
        self.assertEqual(code, 0)
        time.sleep(1)
        self.assertEqual(self.browser.received_messages[0]["title"], "ShortTitle")
        self.browser.received_messages = []

        # Test --title
        code, stdout, stderr = self.run_cli(["Test --title", "--title", "LongTitle"])
        self.assertEqual(code, 0)
        time.sleep(1)
        self.assertEqual(self.browser.received_messages[0]["title"], "LongTitle")

    def test_stdin_input(self):
        """Check if piped input works as intended."""
        code, stdout, stderr = self.run_cli([], input_data="Message from Stdin")
        self.assertEqual(code, 0)
        time.sleep(1)
        self.assertEqual(len(self.browser.received_messages), 1)
        self.assertEqual(self.browser.received_messages[0]["message"], "Message from Stdin")

    def test_auto_detection_logic(self):
        """Check if positional arguments are correctly identified as message or command."""
        # Single string should be message
        code, stdout, stderr = self.run_cli(["Hello World"])
        self.assertEqual(code, 0)
        time.sleep(1)
        self.assertEqual(self.browser.received_messages[0]["message"], "Hello World")
        self.browser.received_messages = []

        # Runnable command should be run mode
        # 'ls' is usually runnable
        code, stdout, stderr = self.run_cli(["ls", "-d", "."])
        self.assertEqual(code, 0)
        time.sleep(1.5)
        self.assertEqual(len(self.browser.received_messages), 1)
        self.assertIn("ls -d . done", self.browser.received_messages[0]["message"])

    def test_send_to_and_broadcast(self):
        """
        Tests:
        1. Targeted message via --send-to.
        2. Broadcast message (default behavior).
        3. Help update verification.
        """
        # 1. Setup second client
        browser2 = VirtualBrowser("browser-cli-2", "cli-token-2")
        browser2.connect(self.server_url)
        time.sleep(1)
        browser2.received_messages = [] # Clear welcome
        self.browser.received_messages = [] # Clear welcome
        
        try:
            # 2. Check broadcast_message (default) still works
            code, stdout, stderr = self.run_cli(["Broadcast Test"])
            self.assertEqual(code, 0)
            time.sleep(1)
            # Both should receive it
            self.assertEqual(len(self.browser.received_messages), 1)
            self.assertEqual(len(browser2.received_messages), 1)
            self.assertEqual(self.browser.received_messages[0]["message"], "Broadcast Test")
            self.assertEqual(browser2.received_messages[0]["message"], "Broadcast Test")
            
            # Clear for next check
            self.browser.received_messages = []
            browser2.received_messages = []
            
            # 3. Check --send-to targeted message
            # Send specifically to browser2
            code, stdout, stderr = self.run_cli(["--send-to", "browser-cli-2", "Targeted Test"])
            self.assertEqual(code, 0)
            time.sleep(1)
            # browser1 (self.browser) should NOT receive it
            self.assertEqual(len(self.browser.received_messages), 0)
            # browser2 SHOULD receive it
            self.assertEqual(len(browser2.received_messages), 1)
            self.assertEqual(browser2.received_messages[0]["message"], "Targeted Test")

            # 4. Check targeted message in run mode
            self.browser.received_messages = []
            browser2.received_messages = []
            code, stdout, stderr = self.run_cli(["--send-to", "browser-cli-2", "echo", "run-targeted"])
            self.assertEqual(code, 0)
            time.sleep(1.5)
            self.assertEqual(len(self.browser.received_messages), 0)
            self.assertEqual(len(browser2.received_messages), 1)
            self.assertIn("run-targeted done", browser2.received_messages[0]["message"])

        finally:
            browser2.disconnect()

    def test_help_updated_correctly(self):
        """Check if the help output contains the new --send-to argument."""
        # Check argparse help (stdout)
        code, stdout, stderr = self.run_cli(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("--send-to DEVICE_ID", stdout)
        
        # Check manual help (stderr, exit 1)
        code, stdout, stderr = self.run_cli([])
        self.assertEqual(code, 1)
        self.assertIn("--send-to DEVICE_ID", stderr)

    def test_reload_server_help(self):
        """Check if --reload-server is in help."""
        code, stdout, stderr = self.run_cli(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("--reload-server", stdout)

    @patch('guga.cli.parse_args')
    @patch('guga.installer.run_reload')
    def test_reload_server_calls_installer(self, mock_run_reload, mock_parse_args):
        """Check if --reload-server correctly invokes the installer logic."""
        from guga import cli
        mock_args = MagicMock()
        # Set the flag we want to test
        mock_args.reload_server = True
        # Ensure other flags are false
        flags = ['install_service', 'qr', 'approve', 'uninstall', 'status', 'url', 'start_server']
        for f in flags:
            setattr(mock_args, f, False)
        
        mock_parse_args.return_value = mock_args
        
        try:
            cli.main()
        except SystemExit:
            pass
            
        mock_run_reload.assert_called_once()

if __name__ == '__main__':
    unittest.main()
