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


def _import_discover():
    """Import _discover lazily so we only fail here if the package is broken.
    Same pattern as the sibling hub-doc-pr-generator skill's setup.py."""
    try:
        from scripts import _discover  # type: ignore[import]
        return _discover
    except ImportError:
        import importlib
        return importlib.import_module("scripts._discover")


# ---------------------------------------------------------------------------
# Interpreter discovery -- ported from the sibling hub-doc-pr-generator
# skill's setup.py (Fix E, PR #30 round 2 review): this skill previously had
# no find_compatible_python()-equivalent and never persisted a discovered
# interpreter path, so an engineer who only ever ran THIS skill's setup left
# nothing on disk for the re-exec guard in _discover.py to act on later.
# ---------------------------------------------------------------------------

_PYTHON_CANDIDATE_NAMES = ["python3.14", "python3.13", "python3.12", "python3.11"]
_PYTHON_CANDIDATE_ABS_PATHS = [
    f"{prefix}/bin/{name}"
    for prefix in ("/opt/homebrew", "/usr/local", "/usr")
    for name in _PYTHON_CANDIDATE_NAMES
]


def python_version_at(path: str) -> tuple[int, int] | None:
    """What Python version the interpreter at `path` actually reports right
    now, or None if it can't be run / doesn't answer sanely. No leading
    underscore: also imported by _discover.py's reexec_target() to verify a
    *persisted* interpreter path is still actually compatible before
    re-exec'ing into it (same pattern as the sibling hub-doc-pr-generator
    skill's setup.py). OSError from subprocess.run (e.g. the path was moved
    or removed since it was persisted) is caught the same as a bad exit
    code -- both just mean "not usable"."""
    try:
        result = _run([path, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"])
    except OSError:
        return None
    if result.returncode != 0:
        return None
    try:
        major_s, minor_s = result.stdout.strip().split(".")
        return int(major_s), int(minor_s)
    except (ValueError, AttributeError):
        return None


def find_compatible_python() -> str | None:
    """Search common locations for a Python 3.11+ interpreter when the default
    `python3` on PATH is too old. Returns the first candidate's resolved
    absolute path, or None if nothing qualifies."""
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
        version = python_version_at(candidate)
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
    # Deliberately NOT calling the _discover re-exec guard here (see Fix F,
    # PR #30 round 2 review): this script's job is to observe and report on
    # the REAL invoked interpreter's version via check_python_version().
    # Silently re-exec'ing into a persisted good interpreter first would
    # make that check report success from under the already-correct
    # interpreter, masking that the operator's actual `python3` on PATH is
    # still too old.
    sys.exit(main())
