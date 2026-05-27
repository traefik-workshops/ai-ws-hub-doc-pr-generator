"""Thin wrapper around the `gh` CLI. All GitHub I/O in this skill goes through here."""
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
