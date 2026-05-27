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


@dataclass
class LintResult:
    ok: bool
    errors: str
    commands: list[str]


_HUB_LINT_COMMANDS = [["yarn", "docs:markdown"], ["yarn", "docs:alex"]]
_OSS_LINT_COMMANDS = [["mkdocs", "build", "--strict", "-d", "/tmp/.mkdocs-preview"]]


def run_linter(*, repo_path: str, impl_repo: str) -> LintResult:
    commands = _HUB_LINT_COMMANDS if impl_repo == "traefik/traefik-hub" else _OSS_LINT_COMMANDS
    all_errors: list[str] = []
    ran: list[str] = []
    for cmd in commands:
        ran.append(" ".join(cmd))
        proc = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            all_errors.append(f"$ {' '.join(cmd)}\n{proc.stdout}\n{proc.stderr}")
    return LintResult(ok=not all_errors, errors="\n".join(all_errors), commands=ran)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--impl-repo", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--edits", required=True,
                        help="path to JSON file with [{path, content, mode}, ...]")
    args = parser.parse_args(argv)
    raw_edits = json.loads(Path(args.edits).read_text())
    edits = [FileEdit(**e) for e in raw_edits]
    written = apply_edits(repo_path=args.repo_path, branch=args.branch, edits=edits)
    stat = git_diff_stat(args.repo_path)
    diff = git_diff(args.repo_path)
    lint = run_linter(repo_path=args.repo_path, impl_repo=args.impl_repo)
    print(json.dumps({
        "written": written,
        "diff_stat": stat,
        "diff": diff,
        "lint_ok": lint.ok,
        "lint_errors": lint.errors,
        "lint_commands": lint.commands,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
