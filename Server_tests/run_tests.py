#!/usr/bin/env python3
"""
Runs all GuGa server tests in isolated subprocesses.

Since the server (Flask+Eventlet) cannot be restarted inside a single
process, each test file runs in its own subprocess with its own DB
and temp directory. Failures are collected and summarised at the end.
"""
import subprocess
import sys
import os
import tempfile
import shutil
import json
import time

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server'))

# Tests that need no server (pure unit tests — run inline for speed)
# Tests that start a real server thread — each runs in its own subprocess
TEST_FILES = [
    "testing_the_pairing.py",
    "testing_the_server.py",
    "testing_the_clients.py",
    "test_concurrent_asks.py",
    "testing_interactive_mode.py",
    "testing_the_guga_cli.py",
    "testing_the_installer.py",
]

TIMEOUT = 120  # seconds per test file


def make_clean_env(extra=None):
    """Build a clean os.environ copy with an isolated temp DB."""
    tmp = tempfile.mkdtemp()
    tmp_db = os.path.join(tmp, "guga_test.db")
    tmp_trusted = os.path.join(tmp, "trusted_devices.json")
    tmp_cfg = os.path.join(tmp, ".guga_config")
    os.makedirs(tmp_cfg, exist_ok=True)
    with open(tmp_trusted, "w") as f:
        json.dump({}, f)

    env = os.environ.copy()
    env["GUGA_DB_PATH"] = tmp_db
    env["GUGA_TRUSTED_DEVICES_FILE"] = tmp_trusted
    env["GUGA_CONFIG_DIR"] = tmp_cfg
    env["PYTHONPATH"] = SERVER_DIR
    env["ENABLE_OS_NOTIFICATIONS"] = "False"
    env["MODE"] = "lan"
    env["GUGA_VERBOSE"] = "false"

    if extra:
        env.update(extra)

    return env, tmp


def run_test(test_file):
    path = os.path.join(os.path.dirname(__file__), test_file)
    env, tmp = make_clean_env()
    try:
        result = subprocess.run(
            [sys.executable, path],
            env=env,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", f"TIMEOUT after {TIMEOUT}s"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    results = {}
    total = len(TEST_FILES)
    passed = 0

    for test_file in TEST_FILES:
        print(f"  ▶  {test_file}", flush=True)
        code, stdout, stderr = run_test(test_file)
        ok = code == 0
        results[test_file] = (ok, stdout, stderr)
        if ok:
            passed += 1
            # Extract summary line
            for line in stderr.splitlines() + stdout.splitlines():
                if line.strip().startswith("Ran ") or line.strip() in ("OK",):
                    print(f"       {line.strip()}")
            print(f"     ✓  PASS")
        else:
            print(f"     ✗  FAIL")
            # Show failure details
            combined = stderr + stdout
            for line in combined.splitlines():
                stripped = line.strip()
                if any(k in stripped for k in ("FAIL:", "ERROR:", "AssertionError", "Traceback", "Ran ", "FAILED")):
                    print(f"       {stripped}")

    print()
    print("  " + "─" * 50)
    print(f"  Results: {passed}/{total} passed")
    print("  " + "─" * 50)
    for f, (ok, _, _) in results.items():
        status = "✓ PASS" if ok else "✗ FAIL"
        print(f"    {status}  {f}")
    print()

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
