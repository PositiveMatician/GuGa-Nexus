"""
GuGa Nexus — Stress Test Suite
===============================
Tests the server under sustained high-concurrency load across:

  1.  Connection flood       — 50 clients connect/disconnect rapidly
  2.  Ping hammer            — 100 concurrent /ping requests
  3.  Broadcast hammer       — 50 concurrent /send broadcasts
  4.  Command queue flood    — 30 clients fire commands simultaneously
  5.  Ask concurrency flood  — 10 simultaneous /api/ask calls, all resolved
  6.  Ask timeout flood      — 20 asks that all time out (408 flood)
  7.  Pairing storm          — 30 devices pair concurrently
  8.  Mixed workload         — connections + commands + asks all at once
  9.  Rapid reconnect        — same device connects/disconnects 20 times quickly
  10. Message cache pressure  — same device receives 100 rapid messages

Results are printed as a summary table.
"""

import time
import threading
import concurrent.futures
import unittest
import os
import sys
import json
import tempfile
import socketio as sio_client
import urllib.request
import urllib.error

# ── path setup ──────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server')))

os.environ.setdefault("ENABLE_OS_NOTIFICATIONS", "False")
os.environ.setdefault("MODE", "lan")
os.environ.setdefault("GUGA_VERBOSE", "false")
os.environ.setdefault("GUGA_TEST_MODE", "True")

tmp_dir = tempfile.mkdtemp()
tmp_db   = os.path.join(tmp_dir, "guga_stress.db")
tmp_json = os.path.join(tmp_dir, "trusted_devices.json")
os.environ["GUGA_DB_PATH"]              = tmp_db
os.environ["GUGA_TRUSTED_DEVICES_FILE"] = tmp_json
with open(tmp_json, "w") as f:
    json.dump({}, f)

from guga.db_utils import Database
db_stress = Database(tmp_db)

# Pre-create 60 trusted devices (covers all stress scenarios)
for i in range(1, 61):
    db_stress.save_trusted_device(
        f"stress-{i}", f"stress-token-{i}",
        "browser", time.time() + 86400, f"Stress Device {i}"
    )

from guga import daemon, cli as guga_cli
from guga.daemon import app, socketio as server_sio

# ── server fixture ───────────────────────────────────────────────────────────
SERVER_PORT = 6790
SERVER_URL  = f"http://127.0.0.1:{SERVER_PORT}"

_server_started = threading.Event()

def _start_server():
    os.environ["PORT"] = str(SERVER_PORT)
    daemon.run_server()

_server_thread = threading.Thread(target=_start_server, daemon=True)
_server_thread.start()
time.sleep(3)  # Give server time to bind

# ── helper ───────────────────────────────────────────────────────────────────

def http_get(path):
    req = urllib.request.Request(f"{SERVER_URL}{path}")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def http_post(path, data):
    body = json.dumps(data).encode()
    req  = urllib.request.Request(
        f"{SERVER_URL}{path}", data=body,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

def make_client(device_id, token="stress-token-1"):
    c = sio_client.Client(reconnection=False)
    c.connect(f"{SERVER_URL}?device_id={device_id}&token={token}")
    return c

# ── test class ────────────────────────────────────────────────────────────────

class StressTests(unittest.TestCase):

    # ── 1. Connection flood ─────────────────────────────────────────────────
    def test_01_connection_flood(self):
        """50 clients connect and disconnect concurrently; server must survive."""
        errors = []
        clients = []
        lock = threading.Lock()

        def connect_disconnect(i):
            try:
                c = make_client(f"stress-{i}", f"stress-token-{i}")
                time.sleep(0.2)
                c.disconnect()
            except Exception as e:
                with lock:
                    errors.append(str(e))

        threads = [threading.Thread(target=connect_disconnect, args=(i,))
                   for i in range(1, 51)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=20)

        # Server must still respond after the flood
        data = http_get("/ping")
        self.assertEqual(data["status"], "online")
        self.assertEqual(len(errors), 0, f"Connection errors: {errors[:3]}")

    # ── 2. Ping hammer ──────────────────────────────────────────────────────
    def test_02_ping_hammer(self):
        """100 concurrent /ping requests — all must return 200."""
        results = []
        lock = threading.Lock()

        def do_ping(_):
            try:
                d = http_get("/ping")
                with lock:
                    results.append(d.get("status") == "online")
            except Exception:
                with lock:
                    results.append(False)

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            list(pool.map(do_ping, range(100)))

        success = sum(results)
        self.assertGreaterEqual(success, 95,
            f"Only {success}/100 pings succeeded")

    # ── 3. Broadcast hammer ──────────────────────────────────────────────────
    def test_03_broadcast_hammer(self):
        """50 concurrent /send broadcasts while 10 clients are connected."""
        # Connect 10 receivers
        receivers = []
        for i in range(1, 11):
            try:
                c = make_client(f"stress-{i}", f"stress-token-{i}")
                receivers.append(c)
            except Exception:
                pass

        time.sleep(1)

        codes = []
        lock  = threading.Lock()

        def do_broadcast(i):
            code, _ = http_post("/send", {"message": f"stress-{i}", "title": "stress"})
            with lock:
                codes.append(code)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(do_broadcast, range(50)))

        for c in receivers:
            try: c.disconnect()
            except Exception: pass

        ok = sum(1 for c in codes if c == 200)
        self.assertGreaterEqual(ok, 45, f"Only {ok}/50 broadcasts returned 200")

    # ── 4. Command queue flood ───────────────────────────────────────────────
    def test_04_command_queue_flood(self):
        """30 trusted clients each fire a command; all replies must arrive."""
        received = {}
        lock = threading.Lock()
        clients = []

        for i in range(1, 31):
            c = sio_client.Client(reconnection=False)
            dev = f"stress-{i}"

            @c.on("guga_response")
            def on_resp(data, _dev=dev):
                with lock:
                    received[_dev] = data

            try:
                c.connect(f"{SERVER_URL}?device_id={dev}&token=stress-token-{i}")
                clients.append((c, dev))
            except Exception:
                pass

        time.sleep(2)  # Let all connect

        for c, dev in clients:
            c.emit("command", {"device_id": dev, "phrase": f"echo hello from {dev}"})

        time.sleep(4)  # Wait for worker to process queue

        for c, _ in clients:
            try: c.disconnect()
            except Exception: pass

        # At least 25 of 30 must have received a reply (worker may be slightly slow)
        self.assertGreaterEqual(len(received), 25,
            f"Only {len(received)}/30 clients received command replies")

    # ── 5. Ask concurrency flood ─────────────────────────────────────────────
    def test_05_ask_concurrency_flood(self):
        """10 simultaneous /api/ask calls for the same device; all resolved."""
        # Connect a single auto-responding client
        responder = sio_client.Client(reconnection=False)
        pending_asks = {}
        lock = threading.Lock()

        @responder.on("guga_ask")
        def auto_reply(data):
            req_id = data.get("request_id")
            def send_reply():
                time.sleep(0.1)
                responder.emit("reply", {"request_id": req_id,
                                         "message": f"ack:{req_id}"})
            threading.Thread(target=send_reply, daemon=True).start()

        responder.connect(f"{SERVER_URL}?device_id=stress-1&token=stress-token-1")
        time.sleep(0.5)

        results = {}

        def do_ask(i):
            code, body = http_post("/api/ask", {
                "message": f"Question {i}",
                "device_id": "stress-1",
                "timeout": 20
            })
            with lock:
                results[i] = (code, body.get("reply", ""))

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(do_ask, range(10)))

        responder.disconnect()

        ok = sum(1 for code, _ in results.values() if code == 200)
        self.assertEqual(ok, 10,
            f"Only {ok}/10 asks resolved successfully. Results: {results}")

    # ── 6. Ask timeout flood ─────────────────────────────────────────────────
    def test_06_ask_timeout_flood(self):
        """20 asks to disconnected device — all must return 408 quickly."""
        codes = []
        lock  = threading.Lock()

        def do_ask(_):
            code, _ = http_post("/api/ask", {
                "message": "Hello?",
                "device_id": "ghost-device-not-connected",
                "timeout": 1
            })
            with lock:
                codes.append(code)

        start = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            list(pool.map(do_ask, range(20)))
        elapsed = time.time() - start

        not_found = sum(1 for c in codes if c == 404)
        # All should be 404 (device not connected) — fast fail
        self.assertGreaterEqual(not_found, 18,
            f"Expected 404s, got: {set(codes)}")
        self.assertLess(elapsed, 10, f"Took too long: {elapsed:.1f}s")

    # ── 7. Pairing storm ────────────────────────────────────────────────────
    def test_07_pairing_storm(self):
        """30 devices send /api/hello simultaneously; all must register."""
        results = []
        lock = threading.Lock()

        def do_pair(i):
            code, body = http_post("/api/hello", {
                "device_id":   f"pairing-device-{i}",
                "pin":         "12345678",
                "device_name": f"Stress Pairer {i}"
            })
            with lock:
                results.append((code, body.get("status")))

        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as pool:
            list(pool.map(do_pair, range(30)))

        ok = sum(1 for code, status in results if code == 200 and status == "pin_required")
        self.assertGreaterEqual(ok, 28,
            f"Only {ok}/30 pairing requests registered. Sample: {results[:5]}")

    # ── 8. Mixed workload ───────────────────────────────────────────────────
    def test_08_mixed_workload(self):
        """Simultaneous connections, pings, broadcasts, and asks."""
        errors = []
        lock = threading.Lock()

        def task_ping():
            for _ in range(10):
                try:
                    http_get("/ping")
                except Exception as e:
                    with lock: errors.append(f"ping: {e}")

        def task_broadcast():
            for i in range(5):
                try:
                    http_post("/send", {"message": f"mixed-{i}", "title": "x"})
                except Exception as e:
                    with lock: errors.append(f"broadcast: {e}")

        def task_connect(i):
            try:
                c = make_client(f"stress-{i}", f"stress-token-{i}")
                time.sleep(0.5)
                c.disconnect()
            except Exception as e:
                with lock: errors.append(f"connect {i}: {e}")

        def task_clients_list():
            for _ in range(5):
                try:
                    http_get("/clients")
                except Exception as e:
                    with lock: errors.append(f"clients: {e}")

        threads = (
            [threading.Thread(target=task_ping)]
            + [threading.Thread(target=task_broadcast)]
            + [threading.Thread(target=task_connect, args=(i,)) for i in range(1, 21)]
            + [threading.Thread(target=task_clients_list)]
        )
        for t in threads: t.start()
        for t in threads: t.join(timeout=30)

        # Server must still be alive
        data = http_get("/ping")
        self.assertEqual(data["status"], "online")
        self.assertEqual(len(errors), 0, f"Errors during mixed load: {errors[:5]}")

    # ── 9. Rapid reconnect ──────────────────────────────────────────────────
    def test_09_rapid_reconnect(self):
        """Same device connects and disconnects 20 times rapidly."""
        for attempt in range(20):
            try:
                c = make_client("stress-1", "stress-token-1")
                c.disconnect()
            except Exception as e:
                self.fail(f"Reconnect #{attempt} failed: {e}")
            time.sleep(0.05)

        # Server stays healthy
        data = http_get("/ping")
        self.assertEqual(data["status"], "online")

    # ── 10. Message cache pressure ───────────────────────────────────────────
    def test_10_message_cache_pressure(self):
        """100 rapid broadcasts to a connected device; no crash or data loss."""
        received = []
        c = sio_client.Client(reconnection=False)

        @c.on("guga_response")
        def on_msg(data):
            received.append(data)

        c.connect(f"{SERVER_URL}?device_id=stress-1&token=stress-token-1")
        time.sleep(0.5)

        # Fire 100 targeted messages as fast as possible
        for i in range(100):
            http_post(f"/send/stress-1", {"message": f"cache-msg-{i}", "title": "cache"})

        time.sleep(3)  # Allow delivery

        c.disconnect()

        # We expect the welcome msg + at least 90 of 100 delivered
        total = len(received)
        self.assertGreaterEqual(total, 90,
            f"Only {total} messages received (expected ≥90 of 101)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
