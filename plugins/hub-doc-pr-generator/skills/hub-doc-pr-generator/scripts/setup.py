"""
Setup / preflight for hub-doc-pr-generator.

Preflight is split into two phases by design, because a precondition is only
meaningful once you know which flow you're in:

  * Universal gate — Python version + ``gh`` present and authenticated. Required
    for every flow regardless of impl repo, and a hard prerequisite for no-arg PR
    auto-detection (which shells out to ``gh``). Runs first, before the impl repo
    is known.
  * Flow-specific resources — only what the chosen impl repo needs:
      - ``traefik/traefik-hub`` : a local ``hub-doc`` clone (docs live in a
        separate repo), with a clean-tree advisory.
      - ``traefik/traefik``     : the current working tree is the impl repo (OSS
        docs are committed in-repo), with a clean-tree advisory.
      - anything else           : nothing — unsupported repos are refused by the
        routing step, not here.

Usage:
    python -m scripts.setup --check                          # universal gate only
    python -m scripts.setup --check --impl-repo <owner/name>  # gate + that repo's resources
    python -m scripts.setup --impl-repo <owner/name>          # interactive provisioning for that repo
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HUB_REPO = "traefik/traefik-hub"
OSS_REPO = "traefik/traefik"


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


def _import_discover():
    """Import _discover lazily so we only fail here if the package is broken."""
    try:
        from scripts import _discover  # type: ignore[import]
        return _discover
    except ImportError:
        import importlib
        return importlib.import_module("scripts._discover")


# ---------------------------------------------------------------------------
# Universal gate — required for every flow
# ---------------------------------------------------------------------------

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
            "gh CLI not found on PATH. "
            "Install it from https://cli.github.com/ and re-run."
        )
        return False
    if _run(["gh", "auth", "status"]).returncode != 0:
        _print_error(
            "gh CLI is not authenticated. "
            "Run `gh auth login` to authenticate, then re-run setup."
        )
        return False
    _print_ok("gh CLI found and authenticated.")
    return True


# ---------------------------------------------------------------------------
# Working-tree advisory (shared by both flows)
# ---------------------------------------------------------------------------

def check_working_tree(path: str, *, label: str) -> None:
    """Advisory only — a dirty tree warns but never fails preflight."""
    result = _run(["git", "-C", path, "status", "--porcelain"])
    if result.returncode != 0:
        _print_warn(
            f"Could not determine git status of {label} at {path}. "
            "Is it a valid git repository?"
        )
        return
    if result.stdout.strip():
        _print_warn(
            f"{label} at {path} has uncommitted changes. "
            "This may cause unexpected behaviour."
        )
    else:
        _print_ok(f"{label} working tree is clean.")


# ---------------------------------------------------------------------------
# Flow-specific resource — Hub (separate hub-doc clone)
# ---------------------------------------------------------------------------

def ensure_hub_doc(*, check_mode: bool) -> tuple[bool, str | None]:
    """Locate (or, interactively, clone) the hub-doc repo. Returns (ok, path)."""
    _discover = _import_discover()

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
            "`python -m scripts.setup --impl-repo traefik/traefik-hub` to configure interactively."
        )
        return False, None

    # Interactive provisioning.
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

    if not Path(chosen_path).is_dir():
        _print_error(f"Path does not exist or is not a directory: {chosen_path}")
        return False, None

    _discover.persist_hub_doc(chosen_path)
    _print_ok(f"hub-doc path saved: {chosen_path}")
    check_working_tree(chosen_path, label="hub-doc clone")
    return True, chosen_path


# ---------------------------------------------------------------------------
# Flow-specific resource — OSS (docs committed in the impl repo itself)
# ---------------------------------------------------------------------------

def ensure_oss_repo(*, check_mode: bool) -> tuple[bool, str | None]:
    """Confirm cwd is inside a git repo (the OSS impl repo). Returns (ok, path)."""
    _discover = _import_discover()
    path = _discover.discover_oss()
    if path is None:
        _print_error(
            "Current directory is not inside a git repository. "
            "For the OSS flow, run the skill from a checkout of traefik/traefik on the impl PR branch."
        )
        return False, None
    _print_ok(f"OSS impl repo detected at: {path}")
    check_working_tree(path, label="impl repo")
    return True, path


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def ensure_flow_resources(impl_repo: str, *, check_mode: bool) -> tuple[bool, str | None]:
    if impl_repo == HUB_REPO:
        return ensure_hub_doc(check_mode=check_mode)
    if impl_repo == OSS_REPO:
        return ensure_oss_repo(check_mode=check_mode)
    # Unsupported repos need no resources here; routing refuses them in step 1.
    _print_info(f"No flow-specific resources required for {impl_repo}.")
    return True, None


def print_summary(impl_repo: str | None, resource_path: str | None) -> None:
    major, minor = sys.version_info[:2]
    gh_user = "<unknown>"
    result = _run(["gh", "api", "user", "--jq", ".login"])
    if result.returncode == 0:
        gh_user = result.stdout.strip()

    _print_info("--- Setup complete ---")
    _print_info(f"Python version : {major}.{minor}")
    _print_info(f"gh user        : {gh_user}")
    _print_info(f"impl repo      : {impl_repo or '<not specified>'}")
    if resource_path:
        _print_info(f"resource path  : {resource_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Setup / preflight check for hub-doc-pr-generator."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Non-interactive check only; exit 1 if anything is missing.",
    )
    parser.add_argument(
        "--impl-repo",
        default=None,
        help="owner/name of the impl repo; gates which flow-specific resources are checked. "
             "Omit to run the universal gate only.",
    )
    args = parser.parse_args(argv)
    check_mode: bool = args.check

    if check_mode:
        _print_info("Running preflight check (--check mode) ...")
    else:
        _print_info("Starting interactive setup ...")

    # Phase 1 — universal gate (flow-independent; must pass before anything else).
    if not check_python_version():
        return 1
    if not check_gh_cli():
        return 1

    # Phase 2 — flow-specific resources (only once the impl repo is known).
    resource_path: str | None = None
    if args.impl_repo:
        ok, resource_path = ensure_flow_resources(args.impl_repo, check_mode=check_mode)
        if not ok:
            return 1
    else:
        _print_info("No --impl-repo given; ran universal gate only.")

    if not check_mode:
        print_summary(args.impl_repo, resource_path)
    else:
        _print_ok("All preflight checks passed.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
