"""
Tests the messaging between server and clients.

This file contains the following tests:
- test_broadcast_message: Sends a broadcast message to all the clients.
- test_private_messages: Sends a private message to a specific client and ensures others don't get it.
"""

import time
import unittest
import socketio
import threading
import os
import sys
import json
import tempfile

# Add server directory to path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server')))

# 1. We must set these BEFORE importing daemon to prevent real alerts/tunnels
os.environ["ENABLE_OS_NOTIFICATIONS"] = "False"
os.environ["MODE"] = "lan"
os.environ["GUGA_VERBOSE"] = "false"

# Create a temporary database — must be done BEFORE importing daemon/db_utils
tmp_dir = tempfile.mkdtemp()
tmp_db = os.path.join(tmp_dir, "guga_test.db")
tmp_trusted = os.path.join(tmp_dir, "trusted_devices.json")
os.environ["GUGA_DB_PATH"] = tmp_db
os.environ["GUGA_TRUSTED_DEVICES_FILE"] = tmp_trusted

with open(tmp_trusted, "w") as f:
    json.dump({}, f)

from guga.db_utils import Database
db_test = Database(tmp_db)
# Pre-populate trusted devices before daemon loads
db_test.save_trusted_device("browser-1", "test-token-1", "browser", time.time() + 3600, "Device 1")
db_test.save_trusted_device("browser-2", "test-token-2", "browser", time.time() + 3600, "Device 2")

from guga import daemon
from guga.daemon import app, socketio as server_socketio


class VirtualBrowser:
    def __init__(self, device_id, token):
        self.sio = socketio.Client()
        self.device_id = device_id
        self.token = token
        self.received_messages = []
        self.sio.on('guga_response', self.on_message)

    def on_message(self, data):
        self.received_messages.append(data)

    def connect(self, url):
        self.sio.connect(f"{url}?device_id={self.device_id}&token={self.token}")

    def disconnect(self):
        if self.sio.connected:
            self.sio.disconnect()


class TestPrivateMessagesToClient(unittest.TestCase):
    server_thread = None

    @classmethod
    def setUpClass(cls):
        from test_utils import kill_port
        kill_port(6769)
        cls.server_url = "http://127.0.0.1:6769"

        def run_server():
            os.environ["PORT"] = "6769"
            daemon.run_server()

        cls.server_thread = threading.Thread(target=run_server, daemon=True)
        cls.server_thread.start()

        # Give the server a moment to start up
        time.sleep(2)

    def test_broadcast_message(self):
        """Sends a broadcast message to all the clients."""
        client1 = VirtualBrowser("browser-1", "test-token-1")
        client2 = VirtualBrowser("browser-2", "test-token-2")

        try:
            client1.connect(self.server_url)
            client2.connect(self.server_url)
            time.sleep(1)

            import urllib.request
            req = urllib.request.Request(f"{self.server_url}/send", data=json.dumps({"message": "Hello", "title": "test"}).encode(), headers={'Content-Type': 'application/json'})
            urllib.request.urlopen(req)

            time.sleep(1)

            # Each client gets 2 messages: Welcome + Broadcast
            self.assertEqual(len(client1.received_messages), 2)
            self.assertEqual(len(client2.received_messages), 2)
            self.assertEqual(client1.received_messages[1]["message"], "Hello")
            self.assertEqual(client1.received_messages[1]["title"], "test")

        finally:
            client1.disconnect()
            client2.disconnect()
            time.sleep(1)  # Let server clean up sessions before next test

    def test_private_messages(self):
        """Sends a private message to a specific client and ensures others don't get it."""
        client1 = VirtualBrowser("browser-1", "test-token-1")
        client2 = VirtualBrowser("browser-2", "test-token-2")

        try:
            client1.connect(self.server_url)
            client2.connect(self.server_url)
            time.sleep(1)

            import urllib.request
            def post_api(path, data):
                req = urllib.request.Request(f"{self.server_url}{path}", data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'})
                urllib.request.urlopen(req)

            post_api(f"/send/{client1.device_id}", {"message": "Secret for 1", "title": "Private"})
            post_api(f"/send/{client2.device_id}", {"message": "Secret for 2", "title": "Private"})

            time.sleep(1)

            # Each should have 2 messages total (1 Welcome + 1 their own secret)
            self.assertEqual(len(client1.received_messages), 2)
            self.assertEqual(len(client2.received_messages), 2)
            self.assertEqual(client1.received_messages[1]["message"], "Secret for 1")
            self.assertEqual(client2.received_messages[1]["message"], "Secret for 2")

        finally:
            client1.disconnect()
            client2.disconnect()


if __name__ == '__main__':
    unittest.main()