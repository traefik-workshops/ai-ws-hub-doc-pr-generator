"""preview.py — write generated files to a working branch, print diff, run linters."""
from __future__ import annotations
import argparse
import json
import re
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
class LintFixResult:
    fixed: list[str]
    unresolved: list[str]
    commands: list[str]


_HUB_AUTOFIX_COMMANDS = [["yarn", "docs:markdown", "--fix"]]
_HUB_CHECK_COMMANDS = [["yarn", "docs:markdown"], ["yarn", "docs:alex"]]
_CHECK_LABELS = {"yarn docs:markdown": "markdownlint", "yarn docs:alex": "alex (inclusive language)"}


def _fix_file_permissions(repo_path: str, written: list[str]) -> list[str]:
    """Doc pages are never executable; clear stray +x bits picked up from generation."""
    fixed: list[str] = []
    for rel in written:
        p = Path(repo_path) / rel
        try:
            mode = p.stat().st_mode
        except OSError:
            continue
        if mode & 0o111:
            p.chmod(0o644)
            fixed.append(f"Fixed file permissions: {rel} (was executable, set to 644)")
    return fixed


def run_lint_fix(*, repo_path: str, impl_repo: str, written: list[str]) -> LintFixResult:
    """Auto-fix what's mechanical; never block on what isn't.

    Hub: `yarn docs:markdown --fix` fixes what markdownlint-cli can fix in place.
    `yarn docs:alex` (inclusive language) has no --fix — flags are always unresolved.
    OSS: `mkdocs build --strict` is a structural check with nothing to auto-fix.
    Either way, whatever remains goes to `unresolved` for the PR body, not a blocker.
    """
    fixed = _fix_file_permissions(repo_path, written)
    unresolved: list[str] = []
    commands: list[str] = []

    if impl_repo == "traefik/traefik-hub":
        for cmd in _HUB_AUTOFIX_COMMANDS:
            commands.append(" ".join(cmd))
            proc = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, check=False)
            if proc.returncode == 0:
                fixed.append(f"Ran `{' '.join(cmd)}` — auto-fixed mechanical markdown issues")
        for cmd in _HUB_CHECK_COMMANDS:
            commands.append(" ".join(cmd))
            proc = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, check=False)
            if proc.returncode != 0:
                label = _CHECK_LABELS[" ".join(cmd)]
                unresolved.append(f"{label}: {(proc.stdout + proc.stderr).strip()}")
    else:
        site_dir = tempfile.mkdtemp(prefix="mkdocs-preview-")
        try:
            cmd = ["mkdocs", "build", "--strict", "-d", site_dir]
            commands.append(" ".join(cmd))
            proc = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, check=False)
            if proc.returncode != 0:
                unresolved.append(f"mkdocs build --strict: {(proc.stdout + proc.stderr).strip()}")
        finally:
            shutil.rmtree(site_dir, ignore_errors=True)

    return LintFixResult(fixed=fixed, unresolved=unresolved, commands=commands)


_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_PLACEHOLDER_RE = re.compile(r"…|\.\.\.|\betc\.?\b", re.IGNORECASE)


def check_table_completeness(edits: list[FileEdit]) -> list[str]:
    """Flag markdown table rows that look truncated (an ellipsis or 'etc.'
    placeholder standing in for values) instead of enumerating every row — see
    style-guide.md's Tables section. Purely mechanical: no LLM judgment, so it
    can't itself introduce a false confirmation prompt."""
    findings: list[str] = []
    for e in edits:
        if not (e.path.endswith(".md") or e.path.endswith(".mdx")):
            continue
        for line in e.content.splitlines():
            if _TABLE_ROW_RE.match(line) and _PLACEHOLDER_RE.search(line):
                findings.append(
                    f"{e.path}: table row looks truncated (ellipsis/'etc.' placeholder "
                    f"instead of an enumerated value): {line.strip()}"
                )
    return findings


def apply_edits_with_lint_fix(
    *, repo_path: str, branch: str, impl_repo: str, edits: list[FileEdit],
) -> tuple[list[str], LintFixResult]:
    """apply_edits + run_lint_fix, re-staging afterward so auto-fixed content and
    permissions actually show up in the staged diff apply_edits already prepared."""
    written = apply_edits(repo_path=repo_path, branch=branch, edits=edits)
    lint = run_lint_fix(repo_path=repo_path, impl_repo=impl_repo, written=written)
    lint.unresolved.extend(check_table_completeness(edits))
    if lint.fixed and written:
        _git.run(repo_path, ["add", "--", *written])
    return written, lint


def render_manual_checks_section(unresolved: list[str]) -> str:
    """Markdown for the doc PR body; empty string when there's nothing to flag."""
    if not unresolved:
        return ""
    bullets = "\n".join(f"- [ ] {item}" for item in unresolved)
    return (
        "\n## Manual checks required\n\n"
        "The lint auto-fixer could not resolve these automatically:\n\n"
        f"{bullets}\n"
    )


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

    written, lint = apply_edits_with_lint_fix(
        repo_path=args.repo_path, branch=args.branch,
        impl_repo=args.impl_repo, edits=edits,
    )
    stat = git_diff_stat(args.repo_path)
    diff = git_diff(args.repo_path)
    print(json.dumps({
        "written": written,
        "diff_stat": stat,
        "diff": diff,
        "lint_fixed": lint.fixed,
        "lint_unresolved": lint.unresolved,
        "lint_commands": lint.commands,
        "manual_checks_md": render_manual_checks_section(lint.unresolved),
        "pretty_tools": detect_pretty_tools(),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
