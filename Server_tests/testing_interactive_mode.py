import unittest
import threading
import time
import os
import sys
import json
import socketio
import eventlet
from unittest.mock import patch, MagicMock

# Add server directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server')))

from guga import daemon
from guga.daemon import app, socketio as server_socketio, connected_clients

class TestInteractiveModeExtended(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server_port = 6781
        cls.server_url = f"http://127.0.0.1:{cls.server_port}"
        
        # Prevent real notifications
        os.environ["ENABLE_OS_NOTIFICATIONS"] = "False"
        
        def run_server():
            # Ensure the server uses the test port
            os.environ["PORT"] = str(cls.server_port)
            daemon.run_server()

        cls.server_thread = threading.Thread(target=run_server, daemon=True)
        cls.server_thread.start()
        time.sleep(2)

    def setUp(self):
        self.sio = socketio.Client()
        self.patcher_trusted = patch('guga.daemon.is_device_trusted', return_value=True)
        self.patcher_trusted.start()
        self.patcher_load = patch('guga.daemon.load_trusted_devices', return_value={'test-device': {'token': 'test-token', 'type': 'browser'}})
        self.patcher_load.start()
        
        # Connect client
        self.sio.connect(f"{self.server_url}?device_id=test-device&token=test-token")
        time.sleep(0.5)

    def tearDown(self):
        if self.sio.connected:
            self.sio.disconnect()
        self.patcher_trusted.stop()
        self.patcher_load.stop()

    def test_ask_user_tag_combinations(self):
        """Test combinations of --title, --delay, --ask-user"""
        from guga import cli
        
        received_payloads = []
        @self.sio.on('guga_ask')
        def on_ask(data):
            received_payloads.append(data)
            self.sio.emit('reply', {'message': 'Confirmed'})

        # Test with title
        with patch('sys.stdout.write'):
            cli.guga_ask_user("Prompt", self.server_port, "test-device", title="My Title", timeout=10)
        
        self.assertEqual(len(received_payloads), 1)
        self.assertEqual(received_payloads[0]['title'], "My Title")
        self.assertEqual(received_payloads[0]['message'], "Prompt")

    def test_delay_parsing(self):
        """Test parse_duration logic with various formats."""
        from guga.cli import parse_duration
        self.assertEqual(parse_duration("1200s"), 1200)
        self.assertEqual(parse_duration("10m"), 600)
        self.assertEqual(parse_duration("1h"), 3600)
        self.assertEqual(parse_duration("never"), None)
        self.assertEqual(parse_duration(""), None)
        with self.assertRaises(ValueError):
            parse_duration("invalid")

    def test_smart_separation_intercept(self):
        """Verify that a 'command' event is treated as a 'reply' when an ask is pending."""
        from guga import cli
        
        @self.sio.on('guga_ask')
        def on_ask(data):
            # Client sends a COMMAND instead of a REPLY
            self.sio.emit('command', {'device_id': 'test-device', 'phrase': 'Intercepted Command'})

        replies = []
        def call_cli():
            with patch('sys.stdout.write') as mock_write:
                cli.guga_ask_user("Wait for command", self.server_port, "test-device", timeout=5)
                output = "".join(call.args[0] for call in mock_write.call_args_list)
                replies.append(output.strip())

        cli_thread = threading.Thread(target=call_cli)
        cli_thread.start()
        cli_thread.join(timeout=5)
        
        self.assertIn("Intercepted Command", replies[0])

    def test_smart_separation_subsequent_commands(self):
        """Verify that after a reply, subsequent commands are processed normally."""
        from guga import cli
        
        received_replies = []
        @self.sio.on('guga_ask')
        def on_ask(data):
            self.sio.emit('reply', {'message': 'First Reply'})

        # 1. Complete an ask
        with patch('sys.stdout.write'):
            cli.guga_ask_user("Ask 1", self.server_port, "test-device", timeout=5)
        
        # 2. Send a command - should NOT be intercepted
        # We'll check this by seeing if the server logs it as a normal command
        # or by checking if we get the 'not found' response
        server_responses = []
        @self.sio.on('guga_response')
        def on_msg(data):
            server_responses.append(data)

        self.sio.emit('command', {'device_id': 'test-device', 'phrase': 'Normal Command'})
        time.sleep(1)
        
        self.assertTrue(any("Normal Command" in r['message'] for r in server_responses))

    def test_command_queuing(self):
        """Verify that multiple commands sent rapidly are all processed."""
        server_responses = []
        @self.sio.on('guga_response')
        def on_msg(data):
            server_responses.append(data)

        # Send 5 commands rapidly
        for i in range(5):
            self.sio.emit('command', {'device_id': 'test-device', 'phrase': f'Command {i}'})
        
        time.sleep(2)
        
        # Verify all 5 responses received
        self.assertEqual(len(server_responses), 5)
        for i in range(5):
            self.assertTrue(any(f"Command {i}" in r['message'] for r in server_responses))

    def test_remote_interactive_execution(self):
        """Test guga -r -i logic: detects prompt, forwards to phone, feeds back reply."""
        from guga import cli
        
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'scratch', 'prompt_script.py'))
        
        @self.sio.on('guga_ask')
        def on_ask(data):
            # Verify we got the prompt
            if "Enter your name" in data['message']:
                self.sio.emit('reply', {'message': 'GuGaUser'})

        # Run interactive command
        # We'll capture output to verify the script finished with the reply
        with patch('sys.stdout.write') as mock_write:
            # We must use a real thread because run_interactive_command is blocking
            # and it will wait for guga_ask_user which will wait for our mock client
            try:
                cli.run_interactive_command([sys.executable, script_path], self.server_port, False, "Test Title", "test-device")
            except SystemExit as e:
                self.assertEqual(e.code, 0)
            
            output = "".join(call.args[0] for call in mock_write.call_args_list)
            self.assertIn("Hello, GuGaUser!", output)

if __name__ == '__main__':
    unittest.main()
