"""
GuGa Nexus — MCP Server Installer
Installs the guga stdio MCP server entry into the Antigravity mcp_config.json.
Run with: python -m guga.install_mcp  [--config PATH] [--python PATH] [--dry-run]
"""

import argparse
import json
import os
import shutil
import sys

# ── Colour helpers ────────────────────────────────────────────────────────────
RESET  = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
GREEN  = "\033[32m"; YELLOW = "\033[33m"; RED = "\033[31m"; CYAN = "\033[36m"

def step(msg):  print(f"\n  {BOLD}{CYAN}→{RESET}  {msg}")
def ok(msg):    print(f"  {GREEN}✓{RESET}  {msg}")
def warn(msg):  print(f"  {YELLOW}⚠{RESET}  {msg}")
def fail(msg):  print(f"\n  {RED}✗  ERROR:{RESET} {msg}\n"); sys.exit(1)
def dim(msg):   print(f"  {DIM}{msg}{RESET}")

# ── Paths ─────────────────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_ROOT = os.path.dirname(HERE)                         # …/MyApplication/server
ANTIGRAVITY_DIR = os.path.join(os.path.expanduser("~"), ".gemini", "antigravity")
DEFAULT_MCP_CONFIG = os.path.join(ANTIGRAVITY_DIR, "mcp_config.json")

# ── Python resolution ─────────────────────────────────────────────────────────

def _find_best_python() -> str:
    """
    Return the Python interpreter that can import both `jwt` and `mcp`.
    Preference order:
      1. Active virtualenv ($VIRTUAL_ENV/bin/python)
      2. Sibling venvs relative to SERVER_ROOT (test-env, venv, .venv, env)
      3. sys.executable (current interpreter)
      4. system python3 / python
    """
    candidates = []

    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        candidates.append(os.path.join(venv, "bin", "python3"))
        candidates.append(os.path.join(venv, "bin", "python"))

    repo_root = os.path.dirname(SERVER_ROOT)
    for name in ("test-env", "venv", ".venv", "env"):
        for base in (SERVER_ROOT, repo_root):
            for exe in ("python3", "python"):
                candidates.append(os.path.join(base, name, "bin", exe))

    candidates.append(sys.executable)
    for exe in ("python3", "python"):
        found = shutil.which(exe)
        if found:
            candidates.append(found)

    for py in candidates:
        if not os.path.isfile(py):
            continue
        try:
            import subprocess
            result = subprocess.run(
                [py, "-c", "import jwt, mcp"],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                return py
        except Exception:
            continue

    return sys.executable   # fallback — may not have all deps


# ── Config helpers ────────────────────────────────────────────────────────────

def _load_config(path: str) -> dict:
    if not os.path.exists(path):
        return {"mcpServers": {}}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        fail(f"Invalid JSON in {path}: {e}")


def _save_config(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _build_guga_entry(python_exe: str) -> dict:
    return {
        "command": python_exe,
        "args": ["-m", "guga.mcp_server"],
        "env": {
            "PYTHONPATH": SERVER_ROOT
        }
    }


# ── Main install logic ────────────────────────────────────────────────────────

def install_mcp(config_path: str, python_exe: str | None, dry_run: bool) -> None:
    print()
    print(f"  {BOLD}{'─' * 44}{RESET}")
    print(f"  {BOLD}  GuGa Nexus  —  MCP Server Installer{RESET}")
    print(f"  {BOLD}{'─' * 44}{RESET}")

    # 1. Resolve Python
    step("Resolving Python interpreter…")
    py = python_exe or _find_best_python()
    dim(f"Using: {py}")

    # Quick sanity-check
    import subprocess
    check = subprocess.run([py, "-c", "import jwt, mcp"], capture_output=True)
    if check.returncode != 0:
        warn(f"Interpreter {py!r} is missing 'jwt' or 'mcp' packages.")
        warn("The entry will still be written, but the MCP server may fail to start.")
        dim(f"Install with: {py} -m pip install PyJWT mcp")
    else:
        ok("Interpreter has required packages (jwt, mcp)")

    # 2. Resolve config path
    step("Locating Antigravity MCP config…")
    dim(f"Config path: {config_path}")
    if not os.path.exists(config_path):
        warn("Config file not found — will create it.")

    # 3. Load existing config
    config = _load_config(config_path)
    if "mcpServers" not in config:
        config["mcpServers"] = {}

    # 4. Build entry
    step("Building MCP server entry…")
    entry = _build_guga_entry(py)

    existing = config["mcpServers"].get("guga")
    if existing == entry:
        ok("Entry already up to date — nothing to do.")
        return

    if existing:
        warn("Existing 'guga' entry found — will overwrite.")
        dim(f"Old: {json.dumps(existing)}")

    dim(f"New: {json.dumps(entry)}")

    # 5. Write
    if dry_run:
        print()
        print(f"  {YELLOW}[DRY RUN]{RESET} Would write to: {config_path}")
        print(f"  {YELLOW}[DRY RUN]{RESET} New 'guga' entry:")
        print(f"    {json.dumps(entry, indent=4)}")
        return

    step("Writing config…")
    config["mcpServers"]["guga"] = entry
    _save_config(config_path, config)
    ok(f"Config written to: {config_path}")

    # 6. Done
    print()
    print(f"  {BOLD}{'─' * 44}{RESET}")
    print(f"  {GREEN}{BOLD}  MCP server installed successfully!{RESET}")
    print(f"  {BOLD}{'─' * 44}{RESET}")
    print()
    dim("Reload the Antigravity MCP panel (Refresh button) to pick up the change.")
    dim("Verify with: guga --mcp   (should print 'GuGa MCP Server started')")
    print()


# ── Uninstall logic ───────────────────────────────────────────────────────────

def uninstall_mcp(config_path: str, dry_run: bool) -> None:
    print()
    print(f"  {BOLD}{'─' * 44}{RESET}")
    print(f"  {BOLD}  GuGa Nexus  —  MCP Server Uninstaller{RESET}")
    print(f"  {BOLD}{'─' * 44}{RESET}")

    step("Loading config…")
    if not os.path.exists(config_path):
        ok("Config file not found — nothing to uninstall.")
        return

    config = _load_config(config_path)
    if "guga" not in config.get("mcpServers", {}):
        ok("'guga' entry not present — nothing to remove.")
        return

    dim(f"Found entry: {json.dumps(config['mcpServers']['guga'])}")

    if dry_run:
        print(f"  {YELLOW}[DRY RUN]{RESET} Would remove 'guga' from {config_path}")
        return

    step("Removing entry…")
    del config["mcpServers"]["guga"]
    _save_config(config_path, config)
    ok("'guga' entry removed from MCP config.")
    print()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m guga.install_mcp",
        description="Install or remove the GuGa stdio MCP server entry in Antigravity's mcp_config.json.",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_MCP_CONFIG,
        metavar="PATH",
        help=f"Path to mcp_config.json (default: {DEFAULT_MCP_CONFIG})",
    )
    parser.add_argument(
        "--python",
        default=None,
        metavar="PATH",
        help="Python interpreter to use. Auto-detected if omitted.",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove the 'guga' entry from the config instead of adding it.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without writing any files.",
    )

    args = parser.parse_args()

    if args.uninstall:
        uninstall_mcp(args.config, args.dry_run)
    else:
        install_mcp(args.config, args.python, args.dry_run)


if __name__ == "__main__":
    main()
