"""Thin wrapper around the `gh` CLI. All GitHub I/O in this skill goes through here.

Verbatim copy of the sibling hub-doc-pr-generator skill's _gh.py — see this
plugin's top-level note (SKILL.md "Shared code" section) about hoisting this
into a plugin-level lib/ instead of duplicating it, once both skills are
touched in the same pass.
"""
from __future__ import annotations
import json
import shutil
import subprocess
from typing import Any


class GhError(RuntimeError):
    """Raised when `gh` fails or is not usable."""


def _run(args: list[str]) -> str:
    if shutil.which("gh") is None:
        raise GhError("gh CLI not found on PATH. Install: https://cli.github.com/")
    proc = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise GhError(f"gh {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def run_json(args: list[str]) -> Any:
    return json.loads(_run(args))


def run_text(args: list[str]) -> str:
    return _run(args)


def assert_auth() -> None:
    try:
        _run(["auth", "status"])
    except GhError as e:
        raise GhError(f"gh not authenticated. Run `gh auth login`. ({e})") from e


def current_user_login() -> str:
    return run_json(["api", "user", "--jq", "{login: .login}"])["login"]
