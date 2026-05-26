"""preview.py — write generated files to a working branch, print diff, run linters."""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from scripts import _git


@dataclass
class FileEdit:
    path: str
    content: str
    mode: Literal["create", "overwrite", "patch"] = "create"


def _checkout_branch(repo_path: str, branch: str) -> None:
    try:
        _git.run(repo_path, ["checkout", "-q", branch])
    except _git.GitError:
        _git.run(repo_path, ["checkout", "-q", "-b", branch])


def apply_edits(*, repo_path: str, branch: str, edits: list[FileEdit]) -> list[str]:
    _checkout_branch(repo_path, branch)
    written: list[str] = []
    for e in edits:
        dest = Path(repo_path) / e.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(e.content)
        written.append(e.path)
    return written


def git_diff(repo_path: str) -> str:
    return _git.run(repo_path, ["diff", "--no-color"])


def git_diff_stat(repo_path: str) -> str:
    return _git.run(repo_path, ["diff", "--stat", "--no-color"])
