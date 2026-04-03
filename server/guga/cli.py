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

def send_notification(message, port, silent, title=None):
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


def run_command(cmd_args, port, silent, title):
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
        send_notification(f"⚠️ {cmd_label} interrupted after {elapsed}", port, silent, title)
        sys.exit(130)

    elapsed = format_duration(time.time() - start)
    last_line = last_meaningful_line("".join(captured_lines))

    status, verb = ("✅", "done") if exit_code == 0 else ("❌", f"failed (exit {exit_code})")
    parts = [f"{status} {cmd_label} {verb} — {elapsed}"]
    if last_line:
        parts.append(last_line)

    send_notification("\n".join(parts), port, silent, title)
    sys.exit(exit_code)


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
  guga -r ./deploy.sh --title "Prod Server"        # explicit: run + title

  guga -r python train.py --silent --title "GPU"   # run silently, labelled notification

setup & pairing:
  guga --qr                                        # show pairing QR code
  guga --show-pin                                  # show the latest pairing PIN
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
        "--show-pin",
        action="store_true",
        help="Show the most recent pairing PIN and exit.",
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
    parser.add_argument(
        "--reconfigure",
        action="store_true",
        help="Force re-run of configuration questions during --install-service.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show the current version and exit.",
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
        "-f", "--from", "--title",
        dest="title",
        default=defaults["title"],
        metavar="LABEL",
        help='Label shown in the notification, e.g. "GPU Server".',
    )

    if argcomplete:
        argcomplete.autocomplete(parser)

    return parser.parse_args()


def main():
    args = parse_args()
    
    # ── Proxy modes ───────────────────────────────────────────────────────────
    if args.install_service or args.qr or args.show_pin or args.uninstall or args.status or args.url:
        from guga.installer import run_system_installer, run_system_uninstaller, run_status, run_url
        if args.uninstall:
            run_system_uninstaller()
            return
        if args.status:
            run_status()
            return
        if args.url:
            run_url()
            return
        run_system_installer(qr_only=args.qr, pin_only=args.show_pin, setup_only=args.install_service)
        return

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
        send_notification(message, args.server, args.silent, args.title)
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
        run_command(positional, args.server, args.silent, args.title)
        return

    # ── Auto-detection ────────────────────────────────────────────────────────

    # 1. Stdin pipe with no positional args
    if not sys.stdin.isatty() and not positional:
        message = sys.stdin.read().strip()
        if not message:
            print("❌ Received empty stdin.", file=sys.stderr)
            sys.exit(1)
        send_notification(message, args.server, args.silent, args.title)
        return

    # 2. Nothing at all
    if not positional:
        print("❌ No message or command provided.\n", file=sys.stderr)
        print("Usage:", file=sys.stderr)
        print('  echo "msg" | guga', file=sys.stderr)
        print('  guga "msg"', file=sys.stderr)
        print('  guga python train.py', file=sys.stderr)
        print('  guga --message "msg"       # explicit message mode', file=sys.stderr)
        print('  guga --run python train.py # explicit run mode', file=sys.stderr)
        sys.exit(1)

    # 3. Single non-executable string → message
    if len(positional) == 1 and not is_runnable(positional[0]):
        send_notification(positional[0], args.server, args.silent, args.title)
        return

    # 4. Otherwise → run mode
    run_command(positional, args.server, args.silent, args.title)


if __name__ == "__main__":
    main()
