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

_PYTHON_CANDIDATE_NAMES = ["python3.14", "python3.13", "python3.12", "python3.11"]
_PYTHON_CANDIDATE_ABS_PATHS = [
    f"{prefix}/bin/{name}"
    for prefix in ("/opt/homebrew", "/usr/local", "/usr")
    for name in _PYTHON_CANDIDATE_NAMES
]


def _python_version_at(path: str) -> tuple[int, int] | None:
    result = _run([path, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"])
    if result.returncode != 0:
        return None
    try:
        major_s, minor_s = result.stdout.strip().split(".")
        return int(major_s), int(minor_s)
    except (ValueError, AttributeError):
        return None


def find_compatible_python() -> str | None:
    """Search common locations for a Python 3.11+ interpreter when the default
    `python3` on PATH is too old — instead of leaving the engineer to manually
    `which -a python3`/`brew list` and then remember to prefix every subsequent
    command with the discovered path for the rest of the session. Returns the
    first candidate's resolved absolute path, or None if nothing qualifies."""
    seen: set[str] = set()
    candidates: list[str] = []
    for name in _PYTHON_CANDIDATE_NAMES:
        which = _run(["which", name])
        resolved = which.stdout.strip() if which.returncode == 0 else ""
        if resolved and resolved not in seen:
            seen.add(resolved)
            candidates.append(resolved)
    for abs_path in _PYTHON_CANDIDATE_ABS_PATHS:
        if abs_path not in seen and Path(abs_path).is_file():
            seen.add(abs_path)
            candidates.append(abs_path)

    for candidate in candidates:
        version = _python_version_at(candidate)
        if version and version >= (3, 11):
            return candidate
    return None


def check_python_version() -> bool:
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 11):
        _print_error(f"Python 3.11 or newer is required (found {major}.{minor}).")
        found = find_compatible_python()
        if found:
            _discover = _import_discover()
            _discover.persist_python_path(found)
            _print_info(f"Found a compatible interpreter: {found}")
            _print_info(
                f"Saved to {_discover.CONFIG_PATH} as 'python_path' — use it in place of "
                f"the literal `python3` for every subsequent command in this run, e.g.:"
            )
            _print_info(f'  PYTHONPATH="${{CLAUDE_SKILL_DIR}}" {found} -m scripts.X')
        else:
            _print_error(
                "No Python 3.11+ interpreter found in common locations either. "
                "Install one (e.g. `brew install python@3.11`) and re-run."
            )
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


def check_main_branch_state(path: str, *, label: str) -> None:
    """Advisory only, like check_working_tree. A new doc branch is always cut
    from a freshly-fetched origin/main (see preview.py's _checkout_branch), so
    this can't produce a broken PR on its own anymore — but a clone left
    checked out on a stale branch, or a local main that's behind origin, is
    still worth surfacing early rather than discovering it mid-run."""
    head = _run(["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"])
    current_branch = head.stdout.strip() if head.returncode == 0 else None
    if current_branch and current_branch != "main":
        _print_warn(
            f"{label} at {path} is checked out on '{current_branch}', not 'main'. "
            "New doc branches always fetch fresh from origin/main regardless, but "
            "consider switching back to main to avoid confusion."
        )

    fetch = _run(["git", "-C", path, "fetch", "-q", "origin", "main"])
    if fetch.returncode != 0:
        _print_warn(
            f"Could not fetch origin/main for {label} at {path}. "
            "Check the remote and network connectivity."
        )
        return
    behind = _run(["git", "-C", path, "rev-list", "--count", "main..origin/main"])
    if behind.returncode == 0 and behind.stdout.strip().isdigit() and int(behind.stdout.strip()) > 0:
        _print_warn(
            f"{label}'s local main is {behind.stdout.strip()} commit(s) behind origin/main. "
            "Run `git -C <path> pull` to sync before generating docs."
        )
    else:
        _print_ok(f"{label}'s local main is up to date with origin/main.")


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
        check_main_branch_state(path, label="hub-doc clone")
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
    check_main_branch_state(chosen_path, label="hub-doc clone")
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
    _import_discover().maybe_reexec()
    sys.exit(main())
