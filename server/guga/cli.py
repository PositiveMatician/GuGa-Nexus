#!/usr/bin/env python3
"""
guga - Send notifications to your Android via the GuGa server.

Usage:
  guga [options] "message"           Send a notification
  guga [options] command args        Run a command and notify when finished
  guga --ask-user "Question"         Ask a question to your phone and wait for reply
  guga --run --interactive python    Run interactively (forwards prompts to phone)

Options:
  -m, --message                      Force message mode
  -r, --run                          Force run mode
  -i, --interactive                  Remote interactive mode (PTY wrapping)
  --ask-user PROMPT                  Synchronous request-reply loop
  --delay DURATION                   Timeout for replies (e.g. 5m, 1200s, never)
  --send-to DEVICE_ID                Target a specific device
"""

import argparse
from typing import List, Optional, Any
import sys
import json
import os
import shlex
import shutil
import re
import subprocess
import time
import urllib.request
import urllib.error
import configparser
try:
    import argcomplete
except ImportError:
    argcomplete = None
from guga import __version__

# ── Colour helpers ────────────────────────────────────────────────────────────
RESET  = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
GREEN  = "\033[32m"; YELLOW = "\033[33m"; RED = "\033[31m"; CYAN = "\033[36m"

CONFIG_DIR = os.path.expanduser("~/.guga")
CAPABILITIES_FILE = os.path.join(CONFIG_DIR, "capabilities.json")

def load_capabilities():
    if os.path.exists(CAPABILITIES_FILE):
        try:
            with open(CAPABILITIES_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"installed_stages": [], "capabilities": {}}

def parse_duration(duration: str) -> Optional[int]:
    """Parses duration strings like 1200s, 10m, 1h, or 'never' into seconds."""
    if not duration: return None
    duration = duration.lower().strip()
    if duration == "never": return None
    
    match = re.match(r"^(\d+)([smh]?)$", duration)
    if not match:
        raise ValueError(f"Invalid duration format: {duration} (use e.g. 120s, 5m, 1h, or never)")
    
    val, unit = match.groups()
    val = int(val)
    if unit == 'm': val *= 60
    elif unit == 'h': val *= 3600
    return val

def check_capabilities(args):
    """Checks if the system has the required capabilities for the given arguments."""
    state = load_capabilities()
    caps = state.get("capabilities", {})
    
    # Example checks:
    if args.status and not caps.get("background_service"):
        # If they ask for status but no background service, it's fine, but we can warn
        pass
        
    if not state.get("installed_stages"):
        # If no stages are installed, they probably haven't run --install-service
        if not (args.install_service or args.uninstall or args.version):
            print(f"⚠️  {BOLD}{YELLOW}Warning:{RESET} GuGa hasn't been fully initialized.")
            print(f"   Run {BOLD}guga --install-service{RESET} to set up the system.\n")


# ── Helpers ───────────────────────────────────────────────────────────────────

def format_duration(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s}s"
    else:
        h, rem = divmod(seconds, 3600)
        m, _ = divmod(rem, 60)
        return f"{h}h {m}m"


def is_runnable(token):
    return shutil.which(token) is not None or os.path.isfile(token)


def last_meaningful_line(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return lines[-1] if lines else None


# ── Core actions ──────────────────────────────────────────────────────────────

def broadcast_message(message: str, port: int, silent: bool, title: Optional[str] = None):
    """
    Sends a notification message to the GuGa server (broadcast).

    Args:
        message (str): The text message to send.
        port (int): The port where the GuGa server is listening.
        silent (bool): If True, suppresses success/error messages in the console.
        title (str, optional): An optional title/label for the notification.
    """
    url = f"http://localhost:{port}/send"

    payload = {"message": message}
    if title:
        payload["title"] = title

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            if not silent:
                print(f"✅ Sent ({response.status}): {message}")
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", str(e))
        if not silent:
            print(f"❌ Could not reach GuGa server on port {port}: {reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        if not silent:
            print(f"❌ Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


def send_message_to(target_id: str, message: str, port: int, silent: bool, title: Optional[str] = None):
    """
    Sends a notification message to a specific device via the GuGa server.

    Args:
        target_id (str): The device_id or session_id of the recipient.
        message (str): The text message to send.
        port (int): The port where the GuGa server is listening.
        silent (bool): If True, suppresses success/error messages in the console.
        title (str, optional): An optional title/label for the notification.
    """
    url = f"http://localhost:{port}/send/{target_id}"

    payload = {"message": message}
    if title:
        payload["title"] = title

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            if not silent:
                print(f"✅ Sent to {target_id} ({response.status}): {message}")
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", str(e))
        if not silent:
            print(f"❌ Could not reach GuGa server on port {port}: {reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        if not silent:
            print(f"❌ Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)

def guga_ask_user(prompt: str, port: int, device_id: str, title: Optional[str] = None, timeout: Optional[int] = None, quiet: bool = False) -> str:
    """
    Sends a synchronous request-reply prompt to a specific device.
    Blocks the local CLI until the user replies from the Android app
    or the request times out.
    
    Args:
        prompt (str): The question to show the user.
        port (int): GuGa server port.
        device_id (str): Target device identifier.
        title (str, optional): Label for the notification.
        timeout (int, optional): Seconds to wait before expiring.
        quiet (bool): If True, suppresses printing the reply to stdout.
        
    Returns:
        str: The user's reply.
    """
    url = f"http://localhost:{port}/api/ask"
    payload = {"message": prompt, "device_id": device_id, "timeout": timeout}
    if title:
        payload["title"] = title
    
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    
    try:
        # urlopen timeout should be slightly more than the server wait time
        req_timeout = (timeout + 5) if timeout is not None else None
        with urllib.request.urlopen(req, timeout=req_timeout) as response:
            res_data = json.load(response)
            if "reply" in res_data:
                reply = res_data["reply"]
                if not quiet:
                    print(reply)
                return reply
            elif "error" in res_data:
                print(f"❌ Error: {res_data['error']}", file=sys.stderr)
                sys.exit(1)
    except (urllib.error.HTTPError) as e:
        if e.code == 408:
            print("❌ Expired: Timed out waiting for user reply.", file=sys.stderr)
            sys.exit(1)
        try:
            error_data = json.loads(e.read().decode())
            print(f"❌ Error: {error_data.get('error', e.reason)}", file=sys.stderr)
        except Exception:
            print(f"❌ Server error: {e.reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        # Check if it's a timeout error (socket.timeout or similar)
        if "timeout" in str(e).lower() or "timed out" in str(e).lower():
            print("❌ Expired: Timed out waiting for user reply.", file=sys.stderr)
        else:
            print(f"❌ Request failed: {e}", file=sys.stderr)
        sys.exit(1)


def run_interactive_command(cmd_args: List[str], port: int, silent: bool, title: str, target_id: Optional[str] = None):
    """
    Spawns a command in a pseudo-terminal (PTY) using pexpect.
    Monitors stdout for common terminal prompts (ends with :, ?, or >).
    When a prompt is detected, it is forwarded to the user's phone.
    The process blocks until a reply is received and fed back into the PTY.
    """
    try:
        import pexpect
    except ImportError:
        print(f"\n  {RED}✗  ERROR:{RESET} 'pexpect' package is required for interactive mode.")
        print(f"  {DIM}Install it with: {RESET}{BOLD}pip install pexpect{RESET}\n")
        sys.exit(1)

    cmd_label = " ".join(cmd_args)
    start = time.time()
    if not silent:
        print(f"▶ guga interactive: {cmd_label}\n")

    # This regex matches any line that ends with :, ?, or >, plus optional spaces.
    generic_prompt_regex = r'[:?>]\s*$'
    captured_lines = []

    try:
        # Spawn the process. shlex.join ensures the command is a single string for spawn
        # which is often more reliable than passing a list to spawn on Linux.
        full_cmd = shlex.join(cmd_args)
        child = pexpect.spawn(full_cmd, encoding='utf-8', timeout=None)
        
        while child.isalive():
            # Wait for a prompt or end of process
            try:
                # We use a 1s timeout loop to keep checking isalive and avoid blocking forever
                index = child.expect([generic_prompt_regex, pexpect.EOF], timeout=1)
                
                # Print and capture what happened
                output = child.before
                if output:
                    print(output, end="", flush=True)
                    captured_lines.append(output)

                if index == 0: # Prompt detected!
                    prompt = child.after
                    print(prompt, end="", flush=True)
                    captured_lines.append(prompt)

                    if not silent:
                        print(f"\n{YELLOW}🔔 [REMOTE ASK]{RESET} Forwarding prompt to {target_id or 'devices'}...")
                    
                    # Forward the prompt context (last line of before + after)
                    context = (output.splitlines()[-1] if "\n" in output else output) + prompt
                    
                    # Blocking call to get reply from phone
                    # We pass quiet=True because we'll feed the reply into the PTY which will echo it anyway
                    reply = guga_ask_user(context.strip(), port, target_id, title="Interactive Prompt", quiet=True)
                    
                    # Feed reply back to the process
                    child.sendline(reply)
                
                elif index == 1: # EOF
                    break

            except pexpect.TIMEOUT:
                # Still running, just no prompt yet. Print any intermediate output.
                output = child.before
                if output:
                    print(output, end="", flush=True)
                    captured_lines.append(output)
                continue
            except pexpect.EOF:
                break

        child.wait()
        exit_code = child.exitstatus if child.exitstatus is not None else 0

    except Exception as e:
        print(f"❌ Error during interactive execution: {e}", file=sys.stderr)
        sys.exit(1)

    elapsed = format_duration(time.time() - start)
    last_line = last_meaningful_line("".join(captured_lines))

    status, verb = ("✅", "done") if exit_code == 0 else ("❌", f"failed (exit {exit_code})")
    parts = [f"{status} {cmd_label} {verb} — {elapsed}"]
    if last_line:
        parts.append(last_line)

    msg = "\n".join(parts)
    if target_id:
        send_message_to(target_id, msg, port, silent, title)
    else:
        broadcast_message(msg, port, silent, title)
    
    # Final cleanup print
    if not silent:
        print(f"\n{parts[0]}")
    
    sys.exit(exit_code)


def run_command(cmd_args: List[str], port: int, silent: bool, title: str, target_id: Optional[str] = None, interactive: bool = False):
    """
    Executes a shell command, streams its output to the console, and sends a 
    notification via GuGa when the command completes or is interrupted.

    Args:
        cmd_args (list of str): The command and its arguments to execute.
        port (int): The port where the GuGa server is running.
        silent (bool): If True, suppresses GuGa's own progress messages.
        title (str): The label shown in the notification.
        target_id (str, optional): The device_id or session_id of the recipient.
    """
    cmd_label = " ".join(cmd_args)
    start = time.time()

    if not silent:
        print(f"▶ guga watching: {cmd_label}\n")

    captured_lines = []
    if interactive:
        return run_interactive_command(cmd_args, port, silent, title, target_id)

    try:
        process = subprocess.Popen(
            cmd_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in process.stdout:
            print(line, end="")
            captured_lines.append(line)

        process.wait()
        exit_code = process.returncode

    except FileNotFoundError:
        print(f"❌ Command not found: {cmd_args[0]}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        elapsed = format_duration(time.time() - start)
        msg = f"⚠️ {cmd_label} interrupted after {elapsed}"
        if target_id:
            send_message_to(target_id, msg, port, silent, title)
        else:
            broadcast_message(msg, port, silent, title)
        sys.exit(130)

    elapsed = format_duration(time.time() - start)
    last_line = last_meaningful_line("".join(captured_lines))

    status, verb = ("✅", "done") if exit_code == 0 else ("❌", f"failed (exit {exit_code})")
    parts = [f"{status} {cmd_label} {verb} — {elapsed}"]
    if last_line:
        parts.append(last_line)

    msg = "\n".join(parts)
    if target_id:
        send_message_to(target_id, msg, port, silent, title)
    else:
        broadcast_message(msg, port, silent, title)
    sys.exit(exit_code)


def guga_approve(port: int, watch: bool = False):
    """Interactive loop to approve pending pairings."""
    base_url = f"http://localhost:{port}/api"
    
    def get_pending() -> List[dict]:
        try:
            req = urllib.request.Request(f"{base_url}/pending")
            with urllib.request.urlopen(req, timeout=2) as r:
                return json.load(r).get("pending", [])
        except Exception as e:
            print(f"  {RED}✗{RESET} Error reaching server: {e}")
            return []

    def format_time(ts: float) -> str:
        diff = int(time.time() - ts)
        if diff < 10: return "just now"
        if diff < 60: return f"{diff}s ago"
        return f"{diff // 60} min ago"

    def print_list(pending: List[dict]) -> None:
        print(f"\n  {DIM}{'─' * 42}{RESET}")
        print(f"   {BOLD}Pending pairing requests{RESET}")
        print(f"  {DIM}{'─' * 42}{RESET}")
        for i, p in enumerate(pending):
            name = p['device_name'][:14].ljust(14)
            did  = p['device_id'][:8]
            pin  = " ".join(p['pin'])
            ago  = format_time(p['requested_at'])
            print(f"  {i+1})  {BOLD}{name}{RESET}  {DIM}{did}{RESET}   {CYAN}{pin}{RESET}   {ago}")
        print(f"  {DIM}{'─' * 42}{RESET}")

    if watch:
        print(f"\n  Watching for pairing requests... {DIM}(Ctrl+C to stop){RESET}")
        seen_ids = set()
        try:
            while True:
                pending = get_pending()
                new_entries = [p for p in pending if p['device_id'] not in seen_ids]
                if new_entries:
                    for p in new_entries:
                        print(f"\n  {BOLD}{YELLOW}New request:{RESET}")
                        print(f"  1)  {BOLD}{p['device_name'][:14].ljust(14)}{RESET}  {DIM}{p['device_id'][:8]}{RESET}   {CYAN}{' '.join(p['pin'])}{RESET}   just now")
                        print(f"  {DIM}{'─' * 42}{RESET}")
                        
                        choice = input(f"  {BOLD}[A] approve   [R] reject   [S] skip{RESET}\n\n  Your choice: ").strip().lower()
                        if choice == 'a':
                            action_url = f"{base_url}/approve"
                            payload = json.dumps({"device_id": p['device_id'], "action": "approve"}).encode()
                            req = urllib.request.Request(action_url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
                            urllib.request.urlopen(req)
                            print(f"  {GREEN}✓ Approved{RESET}")
                        elif choice == 'r':
                            action_url = f"{base_url}/approve"
                            payload = json.dumps({"device_id": p['device_id'], "action": "reject"}).encode()
                            req = urllib.request.Request(action_url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
                            urllib.request.urlopen(req)
                            print(f"  {RED}✗ Rejected{RESET}")
                        
                        seen_ids.add(p['device_id'])
                time.sleep(2)
        except KeyboardInterrupt:
            print("\n  Stopped watching.")
            return

    pending = get_pending()
    if not pending:
        print(f"\n  {DIM}No pending pairing requests.{RESET}\n")
        return

    print_list(pending)
    print(f"  {BOLD}[A] approve all   [R] reject all   [1,2,...] choose{RESET}")
    choice = input(f"\n  Your choice: ").strip().lower()

    if choice == 'a':
        for p in pending:
            payload = json.dumps({"device_id": p['device_id'], "action": "approve"}).encode()
            req = urllib.request.Request(f"{base_url}/approve", data=payload, headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req)
        print(f"  {GREEN}✓ All approved{RESET}")
    elif choice == 'r':
        for p in pending:
            payload = json.dumps({"device_id": p['device_id'], "action": "reject"}).encode()
            req = urllib.request.Request(f"{base_url}/approve", data=payload, headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req)
        print(f"  {RED}✗ All rejected{RESET}")
    else:
        try:
            indices = [int(x.strip()) - 1 for x in choice.replace(',', ' ').split() if x.strip().isdigit()]
            for i, p in enumerate(pending):
                action = "approve" if i in indices else "reject"
                payload = json.dumps({"device_id": p['device_id'], "action": action}).encode()
                req = urllib.request.Request(f"{base_url}/approve", data=payload, headers={"Content-Type": "application/json"}, method="POST")
                urllib.request.urlopen(req)
                status = f"{GREEN}Approved{RESET}" if action == "approve" else f"{RED}Rejected{RESET}"
                print(f"  {status}: {p['device_name']}")
        except Exception:
            print(f"  {RED}Invalid input.{RESET}")


def guga_rename_device(port: int):
    """Interactive loop to rename/tag connected devices."""
    base_url = f"http://localhost:{port}/api"
    
    def get_devices() -> List[dict]:
        try:
            req = urllib.request.Request(f"{base_url}/devices")
            with urllib.request.urlopen(req, timeout=2) as r:
                return json.load(r).get("devices", [])
        except Exception as e:
            print(f"  {RED}✗{RESET} Error reaching server: {e}")
            return []

    def print_list(devices: List[dict]) -> None:
        print(f"\n  {DIM}{'─' * 52}{RESET}")
        print(f"   {BOLD}Connected devices{RESET}")
        print(f"  {DIM}{'─' * 52}{RESET}")
        for i, d in enumerate(devices):
            name = d['device_name'][:14].ljust(14)
            did  = d['device_id'][:8]
            tag  = d.get('tag') or "-"
            tag_display = f"{CYAN}{tag.ljust(12)}{RESET}"
            print(f"  {i+1})  {BOLD}{name}{RESET}  {DIM}{did}{RESET}   Tag: {tag_display}")
        print(f"  {DIM}{'─' * 52}{RESET}")

    devices = get_devices()
    if not devices:
        print(f"\n  {DIM}No connected devices found.{RESET}\n")
        return

    print_list(devices)
    choice = input(f"  {BOLD}Choose a device (1-{len(devices)}): {RESET}").strip()
    
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(devices):
            device = devices[idx]
            print(f"\n  Renaming {BOLD}{device['device_name']}{RESET} ({DIM}{device['device_id'][:8]}{RESET})")
            new_tag = input(f"  Enter new tag (empty to clear): ").strip()
            
            payload = json.dumps({"device_id": device['device_id'], "tag": new_tag}).encode()
            req = urllib.request.Request(f"{base_url}/rename", data=payload, headers={"Content-Type": "application/json"}, method="POST")
            
            try:
                with urllib.request.urlopen(req) as r:
                    print(f"\n  {GREEN}✓ Device tagged: {BOLD}{new_tag or 'None'}{RESET}")
            except urllib.error.HTTPError as e:
                try:
                    err_data = json.load(e)
                    print(f"\n  {RED}✗ Error: {err_data.get('error', 'Unknown error')}{RESET}")
                except Exception:
                    print(f"\n  {RED}✗ Error: {e.reason}{RESET}")
        else:
            print(f"  {RED}Invalid choice.{RESET}")
    except ValueError:
        print(f"  {RED}Invalid input.{RESET}")


# ── Configuration ─────────────────────────────────────────────────────────────

def load_config():
    """Loads default values from ~/.config/guga/config"""
    config = configparser.ConfigParser()
    config_path = os.path.expanduser("~/.config/guga/config")
    
    defaults = {
        "title": None,
        "port": 6769,
        "silent": False
    }
    
    if os.path.exists(config_path):
        try:
            config.read(config_path)
            if "default" in config:
                section = config["default"]
                if "title" in section:
                    defaults["title"] = section["title"]
                if "port" in section:
                    defaults["port"] = int(section["port"])
                if "silent" in section:
                    defaults["silent"] = section.getboolean("silent")
        except Exception:
            pass # Ignore invalid config files
            
    return defaults


# ── Entry point ───────────────────────────────────────────────────────────────

def parse_args():
    defaults = load_config()

    parser = argparse.ArgumentParser(
        prog="guga",
        description="Send notifications to Android, or watch a command and notify on completion.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
mode flags (override auto-detection):
  -m / --message    Force message mode — treat all args as a plain string.
  -r / --run        Force run mode    — treat all args as a command to execute.

auto-detection rules:
  1. stdin piped, no args  →  message mode
  2. single non-executable string  →  message mode
  3. everything else  →  run mode

examples:
  echo "Deploy done" | guga                         # auto: message via stdin
  guga "Build finished"                             # auto: plain message
  guga python train.py --epochs 100                # auto: run mode
  guga calc maintenance.cobol                      # auto: run mode

  guga -m "build done"                             # explicit: message
  guga -m "python train.py"                        # sends the literal string, does not run
  guga -r "sleep 5"                                # explicit: run (splits into tokens)
  guga -r ./deploy.sh --from "Prod Server"         # explicit: run + title alias

  guga -r python train.py --silent -f "GPU"        # run silently, short title alias

configuration:
  ~/.config/guga/config                            # set default title, port, silent

shell completion:
  guga <tab>                                       # autocompletes all flags
  (requires: `activate-global-python-argcomplete --user` or similar initialization)

setup & pairing:
  guga --qr                                        # show pairing QR code
  guga --approve                                   # list and approve pairing requests
  guga --install-service                           # initialise background service
  guga --install-service --reconfigure             # re-run configuration questions
  guga --status                                    # show service status and connections
  guga --url                                       # show raw pairing URL
  guga --version                                   # show current version
  guga --uninstall                                 # remove all GuGa system components

for more details:
  man guga
  tldr guga
        """,
    )

    parser.add_argument(
        "args",
        nargs="*",
        help="Message string, or command + arguments.",
    )

    # Proxy mode flags
    proxy_mode = parser.add_mutually_exclusive_group()
    proxy_mode.add_argument(
        "--qr",
        action="store_true",
        help="Show the pairing QR code and exit.",
    )
    proxy_mode.add_argument(
        "--approve",
        action="store_true",
        help="List and approve pending pairing requests.",
    )
    proxy_mode.add_argument(
        "--rename-device",
        action="store_true",
        help="List connected devices and assign custom tags/names.",
    )
    proxy_mode.add_argument(
        "--install-service",
        action="store_true",
        help="Initializes the Linux background systemd service and components.",
    )
    proxy_mode.add_argument(
        "--uninstall",
        action="store_true",
        help="Safely remove all GuGa system components (service, man pages, config).",
    )
    proxy_mode.add_argument(
        "--status",
        action="store_true",
        help="Show the current service status and connected devices.",
    )
    proxy_mode.add_argument(
        "--url",
        action="store_true",
        help="Output the raw pairing URL (scriptable).",
    )
    proxy_mode.add_argument(
        "--reload-server",
        action="store_true",
        help="Reload (restart) the background GuGa service.",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Stay open and watch for pairing requests (used with --approve).",
    )
    parser.add_argument(
        "--reconfigure",
        action="store_true",
        help="Force re-run of configuration questions during --install-service.",
    )
    proxy_mode.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show the current version and exit.",
    )
    proxy_mode.add_argument(
        "--start-server",
        action="store_true",
        help="Start the GuGa server in the foreground.",
    )

    # Explicit mode flags — mutually exclusive
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "-m", "--message",
        action="store_true",
        help="Force message mode. Joins all positional args as a single string.",
    )
    mode.add_argument(
        "-r", "--run",
        action="store_true",
        help="Force run mode. Executes positional args as a command.",
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Enable remote interaction for --run mode (forwards prompts to phone).",
    )

    parser.add_argument(
        "--server",
        type=int,
        default=defaults["port"],
        metavar="PORT",
        help=f"GuGa server port (default: {defaults['port']}).",
    )
    parser.add_argument(
        "--silent",
        action="store_true",
        default=defaults["silent"],
        help="Suppress guga's own output.",
    )
    parser.add_argument(
        "-t", "-f", "--from", "--title",
        dest="title",
        default=defaults["title"],
        metavar="LABEL",
        help='Label shown in the notification, e.g. "GPU Server".',
    )
    parser.add_argument(
        "--send-to",
        dest="send_to",
        metavar="DEVICE_ID",
        help="Send the notification to a specific device ID or session ID.",
    )
    parser.add_argument(
        "--ask-user",
        metavar="PROMPT",
        help="Send a prompt to the device and wait for a reply.",
    )
    parser.add_argument(
        "--delay",
        metavar="DURATION",
        default="never",
        help="How long to wait for --ask-user reply (e.g. 120s, 5m, never). Default: never.",
    )

    if argcomplete:
        argcomplete.autocomplete(parser)

    args, unknown = parser.parse_known_args()
    if unknown:
        args.args.extend(unknown)
    return args


def show_help(error: Optional[str] = None) -> None:
    """
    Displays a descriptive help message for the guga CLI.
    
    Args:
        error (str, optional): An optional error message to display before the help text.
    """
    if error:
        print(f"❌ {error}\n", file=sys.stderr)

    print("GuGa Nexus - Notification & Command Watcher\n", file=sys.stderr)
    print("Usage:", file=sys.stderr)
    print('  guga [options] "message"      Send a simple notification', file=sys.stderr)
    print('  guga [options] command args   Run a command and notify when done', file=sys.stderr)
    print('  echo "msg" | guga             Pipe message into guga', file=sys.stderr)
    
    print("\nCommon Options:", file=sys.stderr)
    print('  -m, --message                 Force message mode', file=sys.stderr)
    print('  -r, --run                     Force run mode', file=sys.stderr)
    print('  -i, --interactive             Remote interaction (PTY) for --run mode', file=sys.stderr)
    print('  -t, --title LABEL             Set notification title (e.g. "GPU Server")', file=sys.stderr)
    print('  --send-to DEVICE_ID           Send to a specific device', file=sys.stderr)
    print('  --ask-user PROMPT             Ask user for input and wait for reply', file=sys.stderr)
    print('  --delay DURATION              Timeout for reply (e.g. 1200s, 10m, never)', file=sys.stderr)
    print('  --silent                      Suppress internal output', file=sys.stderr)

    print("\nAdvanced Mode:", file=sys.stderr)
    print('  guga -r -i python train.py    Automatically forwards stdin prompts to phone', file=sys.stderr)
    
    print("\nSetup & Background:", file=sys.stderr)
    print('  --install-service             Set up GuGa system components', file=sys.stderr)
    print('  --qr                          Show pairing QR code', file=sys.stderr)
    print('  --start-server                Start server in foreground', file=sys.stderr)
    print('  --reload-server               Restart background service', file=sys.stderr)
    
    print("\nFor more detail, check 'man guga'.", file=sys.stderr)


def main():
    args = parse_args()
    
    # ── Proxy modes ───────────────────────────────────────────────────────────
    if args.install_service or args.qr or args.approve or args.rename_device or args.uninstall or args.status or args.url or args.start_server or args.reload_server:
        from guga.installer import run_system_installer, run_system_uninstaller, run_status, run_url, run_reload
        if args.uninstall:
            run_system_uninstaller()
            return
        if args.status:
            run_status()
            return
        if args.url:
            run_url()
            return
        if args.reload_server:
            run_reload()
            return
        if args.approve:
            guga_approve(args.server, watch=args.watch)
            return
        if args.rename_device:
            guga_rename_device(args.server)
            return
        if args.start_server:
            try:
                from guga.daemon import run_server
                run_server()
            except ImportError:
                # Fallback if run_server isn't defined yet
                import guga.daemon
            return
        run_system_installer(qr_only=args.qr, setup_only=args.install_service)
        return

    if args.ask_user:
        if not args.send_to:
            print("❌ Error: --send-to DEVICE_ID is mandatory when using --ask-user.", file=sys.stderr)
            sys.exit(1)
        try:
            timeout_sec = parse_duration(args.delay)
            guga_ask_user(args.ask_user, args.server, args.send_to, args.title, timeout_sec)
        except ValueError as e:
            print(f"❌ Error: {e}", file=sys.stderr)
            sys.exit(1)
        return

    # Check capabilities for general usage
    check_capabilities(args)

    positional = args.args

    # ── Explicit message mode ─────────────────────────────────────────────────
    if args.message:
        if not positional:
            # Fall back to stdin if no positional args given with --message
            if not sys.stdin.isatty():
                message = sys.stdin.read().strip()
            else:
                print("❌ --message requires a string argument.", file=sys.stderr)
                sys.exit(1)
        else:
            message = " ".join(positional)   # join so --message hello world works too
        
        if args.send_to:
            send_message_to(args.send_to, message, args.server, args.silent, args.title)
        else:
            broadcast_message(message, args.server, args.silent, args.title)
        return

    # ── Explicit run mode ─────────────────────────────────────────────────────
    if args.run:
        if not positional:
            print("❌ --run requires a command to execute.", file=sys.stderr)
            sys.exit(1)
            
        if args.interactive and not args.send_to:
            print("❌ Error: --send-to DEVICE_ID is mandatory when using --interactive.", file=sys.stderr)
            sys.exit(1)

        # If the user passed a single quoted string like "sleep 1" or "python train.py --lr 0.01",
        # split it into proper tokens so subprocess can execute it correctly.
        if len(positional) == 1:
            positional = shlex.split(positional[0])
        run_command(positional, args.server, args.silent, args.title, target_id=args.send_to, interactive=args.interactive)
        return

    # ── Auto-detection ────────────────────────────────────────────────────────

    # 1. Stdin pipe with no positional args
    if not sys.stdin.isatty() and not positional:
        message = sys.stdin.read().strip()
        if not message:
            print("❌ Received empty stdin.", file=sys.stderr)
            sys.exit(1)
        
        if args.send_to:
            send_message_to(args.send_to, message, args.server, args.silent, args.title)
        else:
            broadcast_message(message, args.server, args.silent, args.title)
        return

    # 2. Nothing at all
    if not positional:
        show_help("No message or command provided.")
        sys.exit(1)

    # 3. Single non-executable string → message
    if len(positional) == 1 and not is_runnable(positional[0]):
        if args.send_to:
            send_message_to(args.send_to, positional[0], args.server, args.silent, args.title)
        else:
            broadcast_message(positional[0], args.server, args.silent, args.title)
        return

    # 4. Otherwise → run mode
    run_command(positional, args.server, args.silent, args.title, target_id=args.send_to, interactive=args.interactive)


if __name__ == "__main__":
    main()
