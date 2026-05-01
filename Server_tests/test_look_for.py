"""
Self-contained test for the --look-for tag and logging functionality in GuGa CLI.
"""

import unittest
import threading
import time
import os
import sys
import json
import tempfile
import subprocess
import socketio
import uuid
from typing import List, Tuple

# Add server directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server')))

# Setup environment
tmp_dir = tempfile.mkdtemp()
os.environ["GUGA_CONFIG_DIR"] = tmp_dir
os.environ["ENABLE_OS_NOTIFICATIONS"] = "False"
os.environ["MODE"] = "lan"
os.environ["GUGA_VERBOSE"] = "false"

# Setup DB
tmp_db = os.path.join(tmp_dir, "guga_test.db")
os.environ["GUGA_DB_PATH"] = tmp_db

from guga.db_utils import Database
db_test = Database(tmp_db)
db_test.save_trusted_device("browser-test", "test-token", "browser", time.time() + 3600, "Test Device")
db_test.save_capabilities({
    "installed_stages": ["system_packages", "env_config", "man_page", "systemd_service"],
    "capabilities": {"background_service": True}
})

from guga import daemon
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

class TestLookForTag(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_utils import kill_port
        cls.server_port = 6780
        kill_port(cls.server_port)
        cls.server_url = f"http://127.0.0.1:{cls.server_port}"
        
        def run_server():
            os.environ["PORT"] = str(cls.server_port)
            daemon.run_server()

        cls.server_thread = threading.Thread(target=run_server, daemon=True)
        cls.server_thread.start()
        time.sleep(2)

    def setUp(self):
        self.browser = VirtualBrowser("browser-test", "test-token")
        self.browser.connect(self.server_url)
        time.sleep(1)
        self.browser.received_messages = [] # Clear welcome

    def tearDown(self):
        self.browser.disconnect()

    def run_cli(self, args: List[str]) -> Tuple[int, str, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server'))
        env["PORT"] = str(self.server_port)
        env["GUGA_CONFIG_DIR"] = tmp_dir
        
        if "--server" not in args:
            args.extend(["--server", str(self.server_port)])
            
        cmd = [sys.executable, "-m", "guga.cli"] + args
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        return result.returncode, result.stdout, result.stderr

    def test_look_for_functionality(self):
        """Verify that --look-for sends real-time notifications and logs output."""
        pattern = "ALERT"
        # Command that prints 3 lines, one of which matches the pattern
        cmd_args = ["-r", "--look-for", pattern, 
                    "echo 'Starting'; echo 'ALERT: Security breach!'; echo 'Ending'"]
        
        code, stdout, stderr = self.run_cli(cmd_args)
        self.assertEqual(code, 0)
        
        # Give some time for SocketIO messages to arrive
        time.sleep(2)
        
        # Should have received at least 2 messages: 
        # 1. The intermediate match for "ALERT: Security breach!"
        # 2. The final "done" message
        self.assertGreaterEqual(len(self.browser.received_messages), 2)
        
        # Find the alert message
        alert_msg = next((m for m in self.browser.received_messages if "Security breach" in m["message"]), None)
        self.assertIsNotNone(alert_msg, "Did not receive intermediate regex match notification")
        
        # Find the final message
        final_msg = next((m for m in self.browser.received_messages if "done" in m["message"]), None)
        self.assertIsNotNone(final_msg, "Did not receive final completion notification")
        
        # Verify unique_message_id is used for final message
        final_id = final_msg.get("unique_message_id")
        self.assertIsNotNone(final_id)
        
        # Verify log file exists
        logs_dir = os.path.join(tmp_dir, "logs")
        log_file = os.path.join(logs_dir, f"{final_id}.log")
        self.assertTrue(os.path.exists(log_file), f"Log file {log_file} was not created")
        
        with open(log_file, "r") as f:
            content = f.read()
            self.assertIn("Starting", content)
            self.assertIn("ALERT: Security breach!", content)
            self.assertIn("Ending", content)

    def test_unique_message_id_consistency(self):
        """Verify that the final message ID matches the log filename."""
        code, stdout, stderr = self.run_cli(["-r", "echo", "test-consistency"])
        self.assertEqual(code, 0)
        time.sleep(1.5)
        
        final_msg = self.browser.received_messages[-1]
        msg_id = final_msg.get("unique_message_id")
        
        log_file = os.path.join(tmp_dir, "logs", f"{msg_id}.log")
        self.assertTrue(os.path.exists(log_file), f"Log file {msg_id}.log not found")

if __name__ == '__main__':
    unittest.main()
