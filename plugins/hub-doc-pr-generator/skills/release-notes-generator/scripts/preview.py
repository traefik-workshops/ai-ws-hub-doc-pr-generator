"""preview.py — write the generated release-notes.mdx to a working branch,
run Hub's markdown lint auto-fix, and print the diff for review.

Hub-only, single-file trim of the sibling hub-doc-pr-generator skill's
preview.py (that one also branches on OSS's `mkdocs build --strict` check,
which doesn't apply here — release notes are never an OSS doc). See this
plugin's top-level note about hoisting the genuinely shared bits (diff/lint
plumbing) into one place instead of two copies drifting apart.

Usage:
  python -m scripts.preview --repo-path <hub-doc> --branch <branch> \
      --content-file /tmp/full-content.mdx [--rel-path docs/api-gateway/release-notes.mdx]
  python -m scripts.preview --repo-path <hub-doc> --branch <branch> \
      --content-file /tmp/full-content.mdx --render   # human-facing colorized diff, no JSON
"""
from __future__ import annotations
import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from scripts import _discover, _git
from scripts._frontmatter import VNEXT_RE

_HUB_LINT_AUTOFIX = [["yarn", "docs:markdown", "--fix"]]
_HUB_LINT_CHECK = [["yarn", "docs:markdown"], ["yarn", "docs:alex"]]
_CHECK_LABELS = {"yarn docs:markdown": "markdownlint", "yarn docs:alex": "alex (inclusive language)"}

_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_PLACEHOLDER_RE = re.compile(r"…|\.\.\.|\betc\.?\b", re.IGNORECASE)

DEFAULT_REL_PATH = "docs/api-gateway/release-notes.mdx"


def _checkout_branch(repo_path: str, branch: str) -> None:
    """Check out `branch`, creating it fresh from `origin/main` if it doesn't
    exist locally yet.

    A NEW branch must never be cut from whatever happens to be checked out in
    the working tree: if a stale, already-merged branch was left checked out,
    the new branch would silently inherit all of its commits, producing a
    huge, unrelated diff on the resulting PR (the exact failure behind
    traefik/hub-doc#965, from the sibling hub-doc-pr-generator skill's
    identical bug). An already-existing local branch is left as-is — it has
    its own legitimate history diverging from main, which isn't this bug.
    """
    try:
        _git.run(repo_path, ["rev-parse", "--verify", f"refs/heads/{branch}"])
    except _git.GitError:
        _git.run(repo_path, ["fetch", "-q", "origin", "main"])
        _git.run(repo_path, ["checkout", "-q", "-b", branch, "origin/main"])
        return
    _git.run(repo_path, ["checkout", "-q", branch])


def apply_edit(*, repo_path: str, branch: str, rel_path: str, content: str) -> None:
    _checkout_branch(repo_path, branch)
    dest = Path(repo_path) / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    mode = dest.stat().st_mode
    if mode & 0o111:  # doc pages are never executable
        dest.chmod(0o644)
    _git.run(repo_path, ["add", "--", rel_path])


def git_diff(repo_path: str) -> str:
    return _git.run(repo_path, ["diff", "--cached", "--no-color"])


def git_diff_stat(repo_path: str) -> str:
    return _git.run(repo_path, ["diff", "--cached", "--stat", "--no-color"])


def _which(name: str) -> bool:
    return shutil.which(name) is not None


def detect_pretty_tools() -> dict:
    page = "glow" if _which("glow") else ("bat" if _which("bat") else None)
    return {"diff": "delta" if _which("delta") else None, "page": page}


def render_diff_to_stdout(repo_path: str) -> None:
    diff = git_diff(repo_path)
    if not diff.strip():
        print("(no changes staged)")
        return
    if _which("delta"):
        sys.stdout.flush()
        subprocess.run(["delta", "--paging", "never"], input=diff, text=True, check=False)
    else:
        sys.stdout.write(diff)


def run_lint_fix(*, repo_path: str) -> tuple[list[str], list[str]]:
    """Auto-fix what's mechanical (markdownlint --fix); never block on what isn't
    (alex has no --fix, so its flags always land in `unresolved`)."""
    fixed: list[str] = []
    unresolved: list[str] = []
    for cmd in _HUB_LINT_AUTOFIX:
        proc = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, check=False)
        if proc.returncode == 0:
            fixed.append(f"Ran `{' '.join(cmd)}` — auto-fixed mechanical markdown issues")
    for cmd in _HUB_LINT_CHECK:
        proc = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            label = _CHECK_LABELS[" ".join(cmd)]
            unresolved.append(f"{label}: {(proc.stdout + proc.stderr).strip()}")
    return fixed, unresolved


def _added_or_changed_line_indices(old_content: str, new_content: str) -> set[int]:
    """Line INDICES (0-based, into new_content.splitlines()) that are genuinely
    new or changed relative to `old_content` (line-level diff, so an
    unmodified line that merely sits near an edit isn't swept in). Used to
    scope check_table_completeness to this run's actual additions instead of
    every line in the whole assembled file.

    Ported from the sibling hub-doc-pr-generator skill's preview.py (Fix D,
    PR #30 round 2 review) -- same rationale, including tracking POSITION
    rather than line TEXT: difflib.SequenceMatcher aligns by content
    similarity, so if a genuinely new/changed row's exact text happens to
    match an unrelated PRE-EXISTING row elsewhere in the same file, a
    text-based `set[str]` of changed line content would flag BOTH rows --
    checking by index instead ties each opcode strictly to the specific line
    it actually describes."""
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    changed: set[int] = set()
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            changed.update(range(j1, j2))
    return changed


def check_table_completeness(content: str, rel_path: str, *, repo_path: str | None = None) -> list[str]:
    """Flag compatibility-matrix (or any) table rows abbreviated with an
    ellipsis/'etc.' placeholder instead of an enumerated value.

    Confirmed live (traefik-hub#1435 finding #5, ported here as Fix D, PR #30
    round 2 review): without scoping, this flagged ANY matching table row
    anywhere in the assembled content, including a pre-existing, untouched
    row this `cut` run never changed (e.g. an example value like "123..." --
    a truncated-looking string, not a truncated row). When `repo_path` is
    given, this diffs `content` against the pre-run version of `rel_path`
    (`git show HEAD:<rel_path>`) and only checks lines that are genuinely new
    or changed. Without `repo_path`, every matching line is checked, same as
    before this fix."""
    checkable_indices: set[int] | None = None
    if repo_path is not None:
        try:
            old_content = _git.run(repo_path, ["show", f"HEAD:{rel_path}"])
        except _git.GitError:
            old_content = None
        if old_content is not None:
            checkable_indices = _added_or_changed_line_indices(old_content, content)

    findings = []
    for idx, line in enumerate(content.splitlines()):
        if not (_TABLE_ROW_RE.match(line) and _PLACEHOLDER_RE.search(line)):
            continue
        if checkable_indices is not None and idx not in checkable_indices:
            continue
        findings.append(f"{rel_path}: table row looks truncated: {line.strip()}")
    return findings


def check_vnext_placeholder(content: str, rel_path: str) -> list[str]:
    """Flag a leftover vNEXT placeholder in the assembled release-notes.mdx
    content. assign_target_version.py (sibling hub-doc-pr-generator's cut-mode
    dependency) only ever rewrites a fragment's front-matter target_version,
    never its body prose -- so a fragment generated with the page-level Early
    Access callout's `vNEXT` placeholder (see that skill's style-guide.md,
    "Early Access features") can still literally say `vNEXT` in its body even
    after the front matter gets a real version assigned, and nothing catches
    that mismatch before it ships. Uses the shared _frontmatter.VNEXT_RE so
    this agrees with the sibling skill's preview.py check_placeholder_version
    on what counts as an unresolved placeholder."""
    findings = []
    for line in content.splitlines():
        if VNEXT_RE.search(line):
            findings.append(
                f"{rel_path}: contains the vNEXT placeholder — replace with the real "
                f"Hub release version before merging: {line.strip()}"
            )
    return findings


def render_manual_checks_section(unresolved: list[str]) -> str:
    if not unresolved:
        return ""
    bullets = "\n".join(f"- [ ] {item}" for item in unresolved)
    return f"\n## Manual checks required\n\n{bullets}\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--rel-path", default=DEFAULT_REL_PATH)
    parser.add_argument("--content-file", required=True, help="path to the full new file content")
    parser.add_argument("--render", action="store_true",
                         help="human-facing display mode: stream a pretty diff to stdout "
                              "(delta if installed). Does not re-apply edits or emit JSON; "
                              "run the default mode first.")
    args = parser.parse_args(argv)
    content = Path(args.content_file).read_text(encoding="utf-8")

    if args.render:
        print("===== DIFF =====", flush=True)
        render_diff_to_stdout(args.repo_path)
        return 0

    apply_edit(repo_path=args.repo_path, branch=args.branch, rel_path=args.rel_path, content=content)
    fixed, unresolved = run_lint_fix(repo_path=args.repo_path)
    unresolved.extend(check_table_completeness(content, args.rel_path, repo_path=args.repo_path))
    unresolved.extend(check_vnext_placeholder(content, args.rel_path))
    if fixed:
        _git.run(args.repo_path, ["add", "--", args.rel_path])

    print(json.dumps({
        "written": [args.rel_path],
        "diff_stat": git_diff_stat(args.repo_path),
        "diff": git_diff(args.repo_path),
        "lint_fixed": fixed,
        "lint_unresolved": unresolved,
        "manual_checks_md": render_manual_checks_section(unresolved),
        "pretty_tools": detect_pretty_tools(),
    }, indent=2))
    return 0


if __name__ == "__main__":
    _discover.maybe_reexec()
    sys.exit(main(sys.argv[1:]))
