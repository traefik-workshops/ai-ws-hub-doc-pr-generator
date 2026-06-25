"""preview.py — write generated files to a working branch, print diff, run linters."""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from scripts import _git


@dataclass
class FileEdit:
    path: str
    content: str
    mode: Literal["create", "overwrite"] = "create"


def _checkout_branch(repo_path: str, branch: str) -> None:
    try:
        _git.run(repo_path, ["checkout", "-q", branch])
    except _git.GitError:
        _git.run(repo_path, ["checkout", "-q", "-b", branch])


def apply_edits(*, repo_path: str, branch: str, edits: list[FileEdit]) -> list[str]:
    # Validate before touching the filesystem so we fail fast with a clear message.
    for e in edits:
        if e.mode not in ("create", "overwrite"):
            raise ValueError(
                f"unsupported mode {e.mode!r} for {e.path!r}; "
                "emit full file content with mode='create' or mode='overwrite'"
            )
    _checkout_branch(repo_path, branch)
    written: list[str] = []
    for e in edits:
        dest = Path(repo_path) / e.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(e.content, encoding="utf-8")
        written.append(e.path)
    # Stage so git_diff / git_diff_stat can show new (untracked) files too.
    if written:
        _git.run(repo_path, ["add", "--", *written])
    return written


def git_diff(repo_path: str) -> str:
    return _git.run(repo_path, ["diff", "--cached", "--no-color"])


def git_diff_stat(repo_path: str) -> str:
    return _git.run(repo_path, ["diff", "--cached", "--stat", "--no-color"])


# --- Optional pretty rendering ----------------------------------------------
# The JSON contract above stays plain (ANSI-free) so the orchestrator can parse
# it. Beautification is a *separate*, human-facing concern handled by `--render`,
# which uses external CLIs when present and degrades to plain text otherwise — no
# hard dependency, in keeping with the stdlib-only rule.

def _which(name: str) -> bool:
    return shutil.which(name) is not None


def detect_pretty_tools() -> dict:
    """Which optional renderers are available on PATH (None when absent)."""
    page = "glow" if _which("glow") else ("bat" if _which("bat") else None)
    return {"diff": "delta" if _which("delta") else None, "page": page}


def render_diff_to_stdout(repo_path: str) -> None:
    """Stream the staged diff, piped through `delta` when available."""
    diff = git_diff(repo_path)
    if not diff.strip():
        print("(no changes staged)")
        return
    if _which("delta"):
        # Inherit stdout so delta colorizes for the terminal; never page.
        # Flush first: child writes straight to the fd, so unflushed parent
        # output would otherwise appear after it.
        sys.stdout.flush()
        subprocess.run(["delta", "--paging", "never"], input=diff, text=True, check=False)
    else:
        sys.stdout.write(diff)


def render_pages_to_stdout(edits: list[FileEdit]) -> None:
    """Render each generated markdown page, via glow/bat when available."""
    tool = detect_pretty_tools()["page"]
    for e in edits:
        if not (e.path.endswith(".md") or e.path.endswith(".mdx")):
            continue
        print(f"\n===== {e.path} =====", flush=True)
        if tool == "glow":
            subprocess.run(["glow", "--style", "auto", "-"], input=e.content, text=True, check=False)
        elif tool == "bat":
            subprocess.run(
                ["bat", "--style", "plain", "--paging", "never", "--language", "markdown"],
                input=e.content, text=True, check=False,
            )
        else:
            sys.stdout.write(e.content)


@dataclass
class LintResult:
    ok: bool
    errors: str
    commands: list[str]


_HUB_LINT_COMMANDS = [["yarn", "docs:markdown"], ["yarn", "docs:alex"]]


def run_linter(*, repo_path: str, impl_repo: str) -> LintResult:
    site_dir: str | None = None
    if impl_repo == "traefik/traefik-hub":
        commands = _HUB_LINT_COMMANDS
    else:
        # Per-invocation temp dir so concurrent OSS lint runs don't collide; removed
        # in the finally below so repeated edit-loop previews don't leak build output.
        site_dir = tempfile.mkdtemp(prefix="mkdocs-preview-")
        commands = [["mkdocs", "build", "--strict", "-d", site_dir]]
    all_errors: list[str] = []
    ran: list[str] = []
    try:
        for cmd in commands:
            ran.append(" ".join(cmd))
            proc = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, check=False)
            if proc.returncode != 0:
                all_errors.append(f"$ {' '.join(cmd)}\n{proc.stdout}\n{proc.stderr}")
    finally:
        if site_dir:
            shutil.rmtree(site_dir, ignore_errors=True)
    return LintResult(ok=not all_errors, errors="\n".join(all_errors), commands=ran)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--impl-repo", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--edits", required=True,
                        help="path to JSON file with [{path, content, mode}, ...]")
    parser.add_argument("--render", action="store_true",
                        help="human-facing display mode: stream a pretty diff + rendered "
                             "pages to stdout (uses delta/glow/bat if installed). Does not "
                             "re-apply edits or emit JSON; run the default mode first.")
    args = parser.parse_args(argv)
    raw_edits = json.loads(Path(args.edits).read_text())
    edits = [FileEdit(**e) for e in raw_edits]

    # Display mode: render what the default run already staged. Kept separate so
    # the JSON contract below never carries ANSI.
    if args.render:
        print("===== DIFF =====", flush=True)
        render_diff_to_stdout(args.repo_path)
        render_pages_to_stdout(edits)
        return 0

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
        "pretty_tools": detect_pretty_tools(),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
