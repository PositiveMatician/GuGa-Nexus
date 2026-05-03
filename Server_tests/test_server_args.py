import subprocess
import time
import socket
import os
import signal
import pytest
import re
import sys

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def wait_for_server(port, timeout=10):
    start_time = time.time()
    while time.time() - start_time < timeout:
        if is_port_in_use(port):
            return True
        time.sleep(0.5)
    return False

@pytest.mark.parametrize("mode, port", [
    ("lan", 8989),
    ("lan", 9090),
])
def test_server_args(mode, port):
    """Tests that the server starts with the specified mode and port."""
    
    # Ensure port is free
    if is_port_in_use(port):
        pytest.skip(f"Port {port} is already in use")

    env = os.environ.copy()
    # Add 'server' to PYTHONPATH so guga can be imported
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    server_dir = os.path.join(project_root, "server")
    env["PYTHONPATH"] = server_dir + (":" + env.get("PYTHONPATH", "") if env.get("PYTHONPATH") else "")

    cmd = [
        sys.executable, "-m", "guga.cli", 
        "--start-server", 
        "--mode", mode, 
        "--server", str(port)
    ]
    
    # We use a new process group so we can kill all children (like cloudflared if it started)
    process = subprocess.Popen(
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.STDOUT, 
        text=True,
        env=env,
        preexec_fn=os.setsid
    )

    try:
        # Wait for the server to bind to the port
        started = wait_for_server(port, timeout=15)
        assert started, f"Server failed to start on port {port} within timeout"

        # Check the output for correct mode and port
        # We read a few lines of output
        output = ""
        start_wait = time.time()
        while time.time() - start_wait < 5:
            line = process.stdout.readline()
            if line:
                output += line
                if "mode" in line.lower() and mode.upper() in line.upper():
                    break
            else:
                time.sleep(0.1)

        print(output)
        
        # Verify mode in output
        assert mode.upper() in output.upper(), f"Expected mode {mode.upper()} not found in output"
        
        # Verify port in address
        assert str(port) in output, f"Expected port {port} not found in output address"

    finally:
        # Kill the process group
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        process.wait(timeout=5)

def test_mode_override_env():
    """Tests that CLI --mode overrides MODE environment variable."""
    port = 9191
    if is_port_in_use(port):
        pytest.skip(f"Port {port} is already in use")

    env = os.environ.copy()
    env["MODE"] = "public" # Env says public
    # Add 'server' to PYTHONPATH
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    server_dir = os.path.join(project_root, "server")
    env["PYTHONPATH"] = server_dir + (":" + env.get("PYTHONPATH", "") if env.get("PYTHONPATH") else "")
    
    cmd = [
        sys.executable, "-m", "guga.cli", 
        "--start-server", 
        "--mode", "lan", # CLI says lan
        "--server", str(port)
    ]
    
    process = subprocess.Popen(
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.STDOUT, 
        text=True,
        env=env,
        preexec_fn=os.setsid
    )

    try:
        started = wait_for_server(port, timeout=15)
        assert started

        output = ""
        start_wait = time.time()
        while time.time() - start_wait < 5:
            line = process.stdout.readline()
            if line:
                output += line
                if "mode" in line.lower():
                    break
            else:
                time.sleep(0.1)

        # Should be LAN because CLI overrides ENV
        assert "LAN" in output.upper()
        assert "PUBLIC" not in output.upper()

    finally:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        process.wait(timeout=5)
