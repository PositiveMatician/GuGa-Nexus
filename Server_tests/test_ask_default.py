"""
Test for --ask-user with --default value on timeout.
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
from typing import List, Tuple

# Add server directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server')))

# Setup environment
tmp_dir = tempfile.mkdtemp()
os.environ["GUGA_CONFIG_DIR"] = tmp_dir
os.environ["ENABLE_OS_NOTIFICATIONS"] = "False"
os.environ["MODE"] = "lan"

# Setup DB
tmp_db = os.path.join(tmp_dir, "guga_test.db")
os.environ["GUGA_DB_PATH"] = tmp_db

from guga.db_utils import Database
db_test = Database(tmp_db)
db_test.save_trusted_device("browser-ask", "ask-token", "browser", time.time() + 3600, "Ask Device")
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
        self.received_asks = []
        self.sio.on('guga_ask', self.on_ask)
    
    def on_ask(self, data):
        self.received_asks.append(data)
    
    def connect(self, url: str):
        self.sio.connect(f"{url}?device_id={self.device_id}&token={self.token}")
        
    def disconnect(self):
        if self.sio.connected:
            self.sio.disconnect()

class TestAskDefault(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_utils import kill_port
        cls.server_port = 6785
        kill_port(cls.server_port)
        cls.server_url = f"http://127.0.0.1:{cls.server_port}"
        
        def run_server():
            os.environ["PORT"] = str(cls.server_port)
            daemon.run_server()

        cls.server_thread = threading.Thread(target=run_server, daemon=True)
        cls.server_thread.start()
        time.sleep(2)

    def setUp(self):
        self.browser = VirtualBrowser("browser-ask", "ask-token")
        self.browser.connect(self.server_url)
        time.sleep(1)

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

    def test_ask_user_timeout_with_default(self):
        """Verify that --ask-user returns the --default value when it times out."""
        # Use a short timeout of 2 seconds
        # We don't reply from the browser, so it should time out.
        default_val = "MyDefaultValue"
        args = ["--ask-user", "Will you timeout?", "--default", default_val, "--delay", "2s", "--send-to", "browser-ask"]
        
        start_time = time.time()
        code, stdout, stderr = self.run_cli(args)
        elapsed = time.time() - start_time
        
        self.assertEqual(code, 0)
        self.assertIn(default_val, stdout)
        self.assertGreaterEqual(elapsed, 2)
        
    def test_ask_user_timeout_no_default_fails(self):
        """Verify that --ask-user fails if no default is provided and it times out."""
        args = ["--ask-user", "Will you fail?", "--delay", "1s", "--send-to", "browser-ask"]
        
        code, stdout, stderr = self.run_cli(args)
        self.assertEqual(code, 1)
        self.assertIn("Expired", stderr)

if __name__ == '__main__':
    unittest.main()
