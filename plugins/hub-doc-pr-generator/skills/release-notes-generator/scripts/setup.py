"""Setup / preflight for release-notes-generator.

Always Hub-only — release notes only exist in traefik/hub-doc, never in the
OSS traefik/traefik repo — so this is simpler than the sibling
hub-doc-pr-generator skill's two-flow setup: universal gate (Python + gh),
then the hub-doc clone. No --impl-repo branching needed.

Usage:
    python -m scripts.setup --check   # non-interactive; exit 1 if anything is missing
    python -m scripts.setup           # interactive provisioning
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _print_info(msg: str) -> None:
    print(f"[setup] {msg}")


def _print_ok(msg: str) -> None:
    print(f"[setup] OK: {msg}")


def _print_warn(msg: str) -> None:
    print(f"[setup] WARNING: {msg}")


def _print_error(msg: str) -> None:
    print(f"[setup] ERROR: {msg}", file=sys.stderr)


def check_python_version() -> bool:
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 11):
        _print_error(f"Python 3.11 or newer is required (found {major}.{minor}).")
        return False
    _print_ok(f"Python {major}.{minor} detected.")
    return True


def check_gh_cli() -> bool:
    if _run(["which", "gh"]).returncode != 0:
        _print_error(
            "gh CLI not found on PATH. Install it from https://cli.github.com/ and re-run."
        )
        return False
    if _run(["gh", "auth", "status"]).returncode != 0:
        _print_error(
            "gh CLI is not authenticated. Run `gh auth login` to authenticate, then re-run setup."
        )
        return False
    _print_ok("gh CLI found and authenticated.")
    return True


def check_working_tree(path: str, *, label: str) -> None:
    """Advisory only — a dirty tree warns but never fails preflight."""
    result = _run(["git", "-C", path, "status", "--porcelain"])
    if result.returncode != 0:
        _print_warn(f"Could not determine git status of {label} at {path}. Is it a valid git repository?")
        return
    if result.stdout.strip():
        _print_warn(f"{label} at {path} has uncommitted changes. This may cause unexpected behaviour.")
    else:
        _print_ok(f"{label} working tree is clean.")


def ensure_hub_doc(*, check_mode: bool) -> tuple[bool, Optional[str]]:
    """Locate (or, interactively, clone) the hub-doc repo. Returns (ok, path)."""
    from scripts import _discover

    path = _discover.discover_hub_doc()
    if path:
        _print_ok(f"hub-doc clone found at: {path}")
        check_working_tree(path, label="hub-doc clone")
        return True, path

    _print_info("hub-doc clone not found automatically.")

    if check_mode:
        _print_error(
            "hub-doc clone could not be located. "
            f"Set the path in {_discover.CONFIG_PATH}, or run "
            "`python -m scripts.setup` to configure interactively."
        )
        return False, None

    default_clone_dest = str(Path.home() / "code" / "hub-doc")
    try:
        user_input = input(
            f"[setup] Enter the path to your hub-doc clone "
            f"(or press Enter to clone it to {default_clone_dest}): "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        _print_error("Setup cancelled.")
        return False, None

    if user_input == "":
        _print_info(f"Cloning traefik/hub-doc to {default_clone_dest} ...")
        result = subprocess.run(["gh", "repo", "clone", "traefik/hub-doc", default_clone_dest])
        if result.returncode != 0:
            _print_error("Failed to clone traefik/hub-doc. Check your gh authentication and network.")
            return False, None
        chosen_path = default_clone_dest
    else:
        chosen_path = user_input

    if not Path(chosen_path).is_dir():
        _print_error(f"Path does not exist or is not a directory: {chosen_path}")
        return False, None

    _discover.persist_hub_doc(chosen_path)
    _print_ok(f"hub-doc path saved: {chosen_path}")
    check_working_tree(chosen_path, label="hub-doc clone")
    return True, chosen_path


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Setup / preflight check for release-notes-generator.")
    parser.add_argument("--check", action="store_true", help="Non-interactive check only; exit 1 if anything is missing.")
    args = parser.parse_args(argv)
    check_mode: bool = args.check

    if check_mode:
        _print_info("Running preflight check (--check mode) ...")
    else:
        _print_info("Starting interactive setup ...")

    if not check_python_version():
        return 1
    if not check_gh_cli():
        return 1

    ok, path = ensure_hub_doc(check_mode=check_mode)
    if not ok:
        return 1

    if check_mode:
        _print_ok("All preflight checks passed.")
    else:
        _print_info("--- Setup complete ---")
        _print_info(f"hub-doc path: {path}")
    return 0


if __name__ == "__main__":
    from scripts import _discover

    _discover.maybe_reexec()
    sys.exit(main())
