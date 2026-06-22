"""
Setup / onboarding script for hub-doc-pr-generator.

Usage:
    python -m scripts.setup          # full interactive setup
    python -m scripts.setup --check  # non-interactive preflight check
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], *, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
    )


def _print_info(msg: str) -> None:
    print(f"[setup] {msg}")


def _print_ok(msg: str) -> None:
    print(f"[setup] OK: {msg}")


def _print_warn(msg: str) -> None:
    print(f"[setup] WARNING: {msg}")


def _print_error(msg: str) -> None:
    print(f"[setup] ERROR: {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Step 1 — Python version
# ---------------------------------------------------------------------------

def check_python_version(*, check_mode: bool) -> bool:
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 11):
        _print_error(
            f"Python 3.11 or newer is required (found {major}.{minor})."
        )
        return False
    _print_ok(f"Python {major}.{minor} detected.")
    return True


# ---------------------------------------------------------------------------
# Step 2 — gh CLI
# ---------------------------------------------------------------------------

def check_gh_cli(*, check_mode: bool) -> bool:
    # Check gh is on PATH
    result = _run(["which", "gh"])
    if result.returncode != 0:
        _print_error(
            "gh CLI not found on PATH. "
            "Install it from https://cli.github.com/ and re-run."
        )
        return False

    # Check gh is authenticated
    result = _run(["gh", "auth", "status"])
    if result.returncode != 0:
        _print_error(
            "gh CLI is not authenticated. "
            "Run `gh auth login` to authenticate, then re-run setup."
        )
        return False

    _print_ok("gh CLI found and authenticated.")
    return True


# ---------------------------------------------------------------------------
# Step 3 — hub-doc clone
# ---------------------------------------------------------------------------

def _import_discover():
    """Import _discover lazily so we only fail here if the package is broken."""
    try:
        from scripts import _discover  # type: ignore[import]
        return _discover
    except ImportError:
        # Fallback: try importing from the package root
        import importlib
        return importlib.import_module("scripts._discover")


def check_hub_doc_path(*, check_mode: bool) -> tuple[bool, str | None]:
    """
    Returns (ok, path_or_None).
    In check_mode, never prompts or clones.
    """
    _discover = _import_discover()

    path = _discover.discover_hub_doc()

    if path:
        _print_ok(f"hub-doc clone found at: {path}")
        return True, path

    # Not found
    _print_info("hub-doc clone not found automatically.")

    if check_mode:
        _print_error(
            "hub-doc clone could not be located. "
            f"Set the path in {_discover.CONFIG_PATH} or run `python -m scripts.setup` "
            "to configure interactively."
        )
        return False, None

    # Interactive: prompt
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
        result = _run(
            ["gh", "repo", "clone", "traefik/hub-doc", default_clone_dest],
            capture=False,
        )
        if result.returncode != 0:
            _print_error("Failed to clone traefik/hub-doc. Check your gh authentication and network.")
            return False, None
        chosen_path = default_clone_dest
    else:
        chosen_path = user_input

    # Validate the chosen/cloned path exists
    if not Path(chosen_path).is_dir():
        _print_error(f"Path does not exist or is not a directory: {chosen_path}")
        return False, None

    _discover.persist_hub_doc(chosen_path)
    _print_ok(f"hub-doc path saved: {chosen_path}")
    return True, chosen_path


# ---------------------------------------------------------------------------
# Step 4 — working tree cleanliness
# ---------------------------------------------------------------------------

def check_working_tree(path: str) -> bool:
    result = _run(["git", "-C", path, "status", "--porcelain"])
    if result.returncode != 0:
        _print_warn(
            f"Could not determine git status of hub-doc clone at {path}. "
            "Is it a valid git repository?"
        )
        return True  # warn only, don't fail

    if result.stdout.strip():
        _print_warn(
            f"hub-doc clone at {path} has uncommitted changes. "
            "This may cause unexpected behaviour."
        )
    else:
        _print_ok("hub-doc working tree is clean.")
    return True


# ---------------------------------------------------------------------------
# Step 5 — success summary
# ---------------------------------------------------------------------------

def print_summary(hub_doc_path: str) -> None:
    major, minor = sys.version_info[:2]

    gh_user = "<unknown>"
    result = _run(["gh", "api", "user", "--jq", ".login"])
    if result.returncode == 0:
        gh_user = result.stdout.strip()

    _print_info("--- Setup complete ---")
    _print_info(f"Python version : {major}.{minor}")
    _print_info(f"gh user        : {gh_user}")
    _print_info(f"hub-doc path   : {hub_doc_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Setup / preflight check for hub-doc-pr-generator."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Non-interactive check only; exit 1 if anything is missing.",
    )
    args = parser.parse_args()
    check_mode: bool = args.check

    if check_mode:
        _print_info("Running preflight check (--check mode) ...")
    else:
        _print_info("Starting interactive setup ...")

    # Step 1 — Python version
    if not check_python_version(check_mode=check_mode):
        return 1

    # Step 2 — gh CLI
    if not check_gh_cli(check_mode=check_mode):
        return 1

    # Step 3 — hub-doc clone
    ok, hub_doc_path = check_hub_doc_path(check_mode=check_mode)
    if not ok:
        return 1

    # Step 4 — working tree
    assert hub_doc_path is not None
    check_working_tree(hub_doc_path)

    # Step 5 — summary (interactive mode only)
    if not check_mode:
        print_summary(hub_doc_path)

    if check_mode:
        _print_ok("All preflight checks passed.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
