"""preview.py — write generated files to a working branch, print diff, run linters."""
from __future__ import annotations
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal

from scripts import _git


@dataclass
class FileEdit:
    path: str
    content: str
    mode: Literal["create", "overwrite"] = "create"


def _checkout_branch(repo_path: str, branch: str) -> None:
    """Check out `branch`, creating it fresh from `origin/main` if it doesn't
    exist locally yet.

    A NEW branch must never be cut from whatever happens to be checked out in
    the working tree: if a stale, already-merged feature branch was left
    checked out, the new branch would silently inherit all of its commits,
    producing a huge, unrelated diff on the resulting PR. Always fetch and
    branch from `origin/main` instead. An already-existing local branch (the
    update-existing-doc-PR flow) is left as-is — it has its own legitimate
    history diverging from main, which isn't this bug.
    """
    try:
        _git.run(repo_path, ["rev-parse", "--verify", f"refs/heads/{branch}"])
    except _git.GitError:
        try:
            _git.run(repo_path, ["fetch", "-q", "origin", "main"])
        except _git.GitError as e:
            raise _git.GitError(
                f"could not fetch origin/main to branch {branch!r} from — "
                f"check the clone has an 'origin' remote pointing at the doc repo "
                f"and network access to it: {e}"
            ) from e
        _git.run(repo_path, ["checkout", "-q", "-b", branch, "origin/main"])
        return
    _git.run(repo_path, ["checkout", "-q", branch])


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


_MD_SUFFIXES = (".md", ".mdx")


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


def _dirty_paths(repo_path: str) -> list[str]:
    """Paths with uncommitted changes (tracked or untracked), from porcelain
    status. Empty (not raised) if git status itself fails — this is a best-
    effort safety net, and shouldn't be able to take down the whole lint-fix
    pipeline over it."""
    try:
        out = _git.run(repo_path, ["status", "--porcelain"])
    except _git.GitError:
        return []
    paths: list[str] = []
    for line in out.splitlines():
        if not line:
            continue
        path = line[3:]
        if " -> " in path:  # rename: "old -> new"
            path = path.split(" -> ", 1)[1]
        paths.append(path)
    return paths


@contextmanager
def _stash_unrelated_changes(repo_path: str, keep: list[str]) -> Iterator[None]:
    """Temporarily stash any working-tree changes NOT in `keep` (our own written
    files) before running a repo-wide lint tool. `yarn docs:markdown --fix` and
    friends operate on the whole tree, not a file list — without this, a hub-doc
    clone left dirty from unrelated in-progress work gets reformatted and left
    dirty by the fixer, twice over if the run is ever redone. Best-effort: a
    failed stash push just means we proceed without this protection, same as
    before this existed, rather than blocking doc generation over it. Restored
    unconditionally on exit whenever the push did succeed, even if the lint
    step itself raises."""
    keep_set = set(keep)
    unrelated = [p for p in _dirty_paths(repo_path) if p not in keep_set]
    stashed = False
    if unrelated:
        try:
            _git.run(repo_path, ["stash", "push", "-u", "--", *unrelated])
            stashed = True
        except _git.GitError:
            pass
    try:
        yield
    finally:
        if stashed:
            try:
                _git.run(repo_path, ["stash", "pop"])
            except _git.GitError as e:
                # Surface a short, actionable message instead of the raw
                # multi-file merge-conflict dump: the caller can't do anything
                # useful with the full conflict list, only with the recovery
                # command itself.
                raise _git.GitError(
                    f"git stash pop conflicted while restoring pre-existing changes "
                    f"in {repo_path} — run `git checkout -- . && git stash drop` there, "
                    f"then retry. Original error: {e}"
                ) from e


_PATH_LEFT_BOUNDARY = r"(?<![A-Za-z0-9_])"
_PATH_RIGHT_BOUNDARY = r"(?![A-Za-z0-9_])"


def _filter_to_written_paths(output: str, written: list[str]) -> str:
    """Repo-wide lint commands report on the whole tree; keep only the lines
    that mention one of our own written files, so pre-existing, unrelated
    lint noise elsewhere in the repo never reaches the PR body. If nothing in
    the output mentions a written file, the whole thing is dropped rather than
    surfaced as ours to fix.

    Matches are bounded so a written path like `api.md` doesn't false-positive
    on an unrelated `old-api.md` — plain substring matching would."""
    if not written:
        return output
    patterns = [
        re.compile(_PATH_LEFT_BOUNDARY + re.escape(w) + _PATH_RIGHT_BOUNDARY)
        for w in written
    ]
    kept = [line for line in output.splitlines() if any(p.search(line) for p in patterns)]
    return "\n".join(kept)


def run_lint_fix(*, repo_path: str, impl_repo: str, written: list[str]) -> LintFixResult:
    """Auto-fix what's mechanical; never block on what isn't.

    Hub: markdownlint fixes what it can fix in place; alex (inclusive language)
    has no --fix — flags are always unresolved. Both are invoked directly via
    their node_modules/.bin binaries, scoped to just the written .md/.mdx
    files — never repo-wide. `yarn docs:markdown`/`yarn docs:alex` are npm
    script aliases with the target glob (`docs/**/*.md`) baked into the
    script string itself; passing extra file args to the yarn wrapper only
    appends to that glob, it can't replace it, so scoping requires calling
    the underlying binary directly instead. Running repo-wide left ~70
    unrelated files dirty after every run, which then broke the next run's
    `_stash_unrelated_changes()` (the regenerated repo-wide diff conflicted
    with the stashed copy of itself on `stash pop`).
    OSS: `mkdocs build --strict` is a structural check with nothing to auto-fix.
    Either way, whatever remains goes to `unresolved` for the PR body, not a blocker.
    """
    fixed = _fix_file_permissions(repo_path, written)
    unresolved: list[str] = []
    commands: list[str] = []

    with _stash_unrelated_changes(repo_path, written):
        if impl_repo == "traefik/traefik-hub":
            md_written = [w for w in written if w.endswith(_MD_SUFFIXES)]
            if md_written:
                markdownlint = str(Path(repo_path) / "node_modules" / ".bin" / "markdownlint")
                alex = str(Path(repo_path) / "node_modules" / ".bin" / "alex")

                try:
                    fix_cmd = [markdownlint, "--fix", *md_written]
                    commands.append(" ".join(fix_cmd))
                    proc = subprocess.run(fix_cmd, cwd=repo_path, capture_output=True, text=True, check=False)
                    if proc.returncode == 0:
                        fixed.append(f"Ran `{' '.join(fix_cmd)}` — auto-fixed mechanical markdown issues")

                    for cmd, label in (
                        ([markdownlint, *md_written], "markdownlint"),
                        ([alex, "--quiet", *md_written], "alex (inclusive language)"),
                    ):
                        commands.append(" ".join(cmd))
                        proc = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, check=False)
                        if proc.returncode != 0:
                            filtered = _filter_to_written_paths((proc.stdout + proc.stderr).strip(), written)
                            if filtered.strip():
                                unresolved.append(f"{label}: {filtered}")
                except FileNotFoundError:
                    # Calling the binaries directly (see docstring) means a
                    # clone that hasn't had `yarn install` run yet -- or one
                    # where hoisting puts binaries somewhere else -- hits a
                    # bare FileNotFoundError instead of yarn's own "command
                    # not found" framing. Surface that as an actionable
                    # unresolved note rather than letting the whole preview
                    # step crash.
                    unresolved.append(
                        f"markdownlint/alex not found under {repo_path}/node_modules/.bin — "
                        "run `yarn install` in the doc repo, then retry"
                    )
        else:
            site_dir = tempfile.mkdtemp(prefix="mkdocs-preview-")
            try:
                cmd = ["mkdocs", "build", "--strict", "-d", site_dir]
                commands.append(" ".join(cmd))
                proc = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, check=False)
                if proc.returncode != 0:
                    filtered = _filter_to_written_paths((proc.stdout + proc.stderr).strip(), written)
                    if filtered.strip():
                        unresolved.append(f"mkdocs build --strict: {filtered}")
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


_VNEXT_RE = re.compile(r"\bvNEXT\b")


def check_placeholder_version(edits: list[FileEdit]) -> list[str]:
    """Flag the vNEXT release-version placeholder (see release-note-heuristics.md
    "Which version") left in generated content, so it can't merge un-replaced
    without at least one visible flag in the PR body."""
    findings: list[str] = []
    for e in edits:
        if not (e.path.endswith(".md") or e.path.endswith(".mdx")):
            continue
        for line in e.content.splitlines():
            if _VNEXT_RE.search(line):
                findings.append(
                    f"{e.path}: contains the vNEXT placeholder — replace with the real "
                    f"Hub release version before merging: {line.strip()}"
                )
    return findings


_FRAGMENT_PATH_RE = re.compile(r"release-notes\.d/")
_UNASSIGNED_TARGET_VERSION_RE = re.compile(r"^target_version:\s*unassigned\s*$", re.MULTILINE)


def check_unassigned_fragment(edits: list[FileEdit]) -> list[str]:
    """Flag a release-note fragment (docs/api-gateway/release-notes.d/*.mdx) whose
    front matter has target_version: unassigned — not an error (it's the expected
    state until the EA cut number is known, see release-note-heuristics.md "Which
    version"), but worth a visible reminder in the PR body so it isn't forgotten
    before `release-notes-generator cut` runs."""
    findings: list[str] = []
    for e in edits:
        if not _FRAGMENT_PATH_RE.search(e.path):
            continue
        if _UNASSIGNED_TARGET_VERSION_RE.search(e.content):
            findings.append(
                f"{e.path}: target_version is `unassigned` — release-notes-generator's "
                f"`cut` command will prompt for this fragment once the release version is known"
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
    lint.unresolved.extend(check_placeholder_version(edits))
    lint.unresolved.extend(check_unassigned_fragment(edits))
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
