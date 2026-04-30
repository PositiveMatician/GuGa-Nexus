#!/usr/bin/env python3
"""
guga - Send notifications to your Android via the GuGa server.

Auto-detected mode:
  echo "msg" | guga
  guga "Build finished"
  guga python train.py

Explicit mode (overrides auto-detection):
  guga --message "build done"
  guga --run calc maintenance.cobol
"""

import argparse
from typing import List, Optional, Any
import sys
import json
import os
import shlex
import shutil
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


def run_command(cmd_args: List[str], port: int, silent: bool, title: str, target_id: Optional[str] = None):
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
    print('  -s, --status                  Show service status', file=sys.stderr)
    print('  -t, --title LABEL             Set notification title (e.g. "GPU Server")', file=sys.stderr)
    print('  --send-to DEVICE_ID           Send to a specific device', file=sys.stderr)
    print('  --silent                      Suppress internal output', file=sys.stderr)
    
    print("\nSetup & Background:", file=sys.stderr)
    print('  --install-service             Set up GuGa system components', file=sys.stderr)
    print('  --qr                          Show pairing QR code', file=sys.stderr)
    print('  --start-server                Start server in foreground', file=sys.stderr)
    print('  --reload-server               Restart background service', file=sys.stderr)
    
    print("\nFor more detail, check 'man guga'.", file=sys.stderr)


def main():
    args = parse_args()
    
    # ── Proxy modes ───────────────────────────────────────────────────────────
    if args.install_service or args.qr or args.approve or args.uninstall or args.status or args.url or args.start_server or args.reload_server:
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
        # If the user passed a single quoted string like "sleep 1" or "python train.py --lr 0.01",
        # split it into proper tokens so subprocess can execute it correctly.
        if len(positional) == 1:
            positional = shlex.split(positional[0])
        run_command(positional, args.server, args.silent, args.title, target_id=args.send_to)
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
    run_command(positional, args.server, args.silent, args.title, target_id=args.send_to)


if __name__ == "__main__":
    main()
