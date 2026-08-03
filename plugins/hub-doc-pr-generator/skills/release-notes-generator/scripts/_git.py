"""Thin wrapper around `git -C <path>`. Never `cd`s.

Verbatim copy of the sibling hub-doc-pr-generator skill's _git.py — see this
plugin's top-level note (SKILL.md "Shared code" section) about hoisting this
into a plugin-level lib/ instead of duplicating it.
"""
from __future__ import annotations
import subprocess


class GitError(RuntimeError):
    pass


def run(repo_path: str, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", "-C", repo_path, *args],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed in {repo_path}: {proc.stderr.strip()}")
    return proc.stdout


def head_branch(repo_path: str) -> str:
    return run(repo_path, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()


def is_dirty(repo_path: str) -> bool:
    return bool(run(repo_path, ["status", "--porcelain"]).strip())
