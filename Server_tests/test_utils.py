"""
Shared test utilities for GuGa server tests.
"""
import os
import signal
import subprocess


def kill_port(port: int) -> None:
    """Kill any process listening on the given TCP port."""
    try:
        result = subprocess.run(
            ["fuser", f"{port}/tcp"],
            capture_output=True, text=True
        )
        pids = result.stdout.strip().split()
        for pid in pids:
            pid = pid.strip()
            if pid.isdigit():
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
    except FileNotFoundError:
        # fuser not available, try lsof
        try:
            result = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}"],
                capture_output=True, text=True
            )
            for pid in result.stdout.strip().split("\n"):
                pid = pid.strip()
                if pid.isdigit():
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        except FileNotFoundError:
            pass
