"""push.py — commit the release-notes.mdx edit and open a draft PR against
traefik/hub-doc.

Hub-only, single-file version of the sibling hub-doc-pr-generator skill's
open_pr.py (that one also handles the OSS traefik/traefik commit-to-impl-PR
flow, which doesn't apply here — release notes are always in hub-doc, never
committed into traefik/traefik).

Usage:
  python -m scripts.push --doc-repo-root <path> --branch <branch> \
      --title "docs: release notes for v3.20.8 & v3.19.13" --body-file /tmp/pr-body.md
"""
from __future__ import annotations
import argparse
import fnmatch
import json
import sys
from pathlib import Path
from typing import Optional

from scripts import _discover, _gh, _git
from scripts.preview import DEFAULT_REL_PATH

UPSTREAM_HUB_DOC = "traefik/hub-doc"
# Glob (matched against a repo-relative path) for fragment files
# commit_release_notes() auto-discovers among what's already staged -- see
# _staged_paths_matching()'s docstring.
FRAGMENT_GLOB = "docs/api-gateway/release-notes.d/*.mdx"


def _staged_paths(doc_repo_root: str) -> list[str]:
    """Repo-relative paths currently staged in `doc_repo_root` -- one `git
    diff --cached --name-only` call, read once and reused by both the
    fragment-auto-discovery step and the "did anything actually get staged"
    check in commit_release_notes(), instead of running the same unscoped
    diff against the same unchanged index twice (PR #32 review finding 8)."""
    staged = _git.run(doc_repo_root, ["diff", "--cached", "--name-only"]).strip()
    return staged.splitlines() if staged else []


def _staged_paths_matching(staged: list[str], pattern: str) -> list[str]:
    """The subset of `staged` repo-relative paths that match `pattern`
    (fnmatch against the full path).

    This is what makes finding F's fix self-enforcing instead of prose-only
    (PR #32 review finding 1): assign_target_version.py's --doc-repo-root
    already `git add`s a reassigned fragment, so by the time `push` runs,
    the ground truth for "which fragments got reassigned this run" is
    already sitting in the git index -- reading it directly here means
    commit_release_notes() no longer depends on the orchestrating agent
    correctly maintaining an external list (SKILL.md's earlier
    /tmp/reassigned_fragment_paths.txt approach, which had no way to catch
    a lost or incomplete list, and whose shell plumbing had its own bug:
    review finding 2, unquoted `sed` word-splitting a path containing a
    space). If nothing matching `pattern` is staged, this simply returns an
    empty list -- not an error, since most cuts reassign zero fragments."""
    return [p for p in staged if fnmatch.fnmatch(p, pattern)]


def _fragments_with_staged_reassignment(doc_repo_root: str, fragment_paths: list[str]) -> list[str]:
    """The subset of `fragment_paths` whose staged diff actually contains a
    `target_version` reassignment (a `+target_version: <non-unassigned>`
    line), not just any staged edit under FRAGMENT_GLOB.

    Matching FRAGMENT_GLOB alone re-opens the exact shared-clone risk finding
    E's explicit-pathspec commit was written to close (PR #32 review finding
    6, altitude): it can't tell "a fragment THIS run's
    assign_target_version.py --doc-repo-root staged" apart from "a fragment
    someone else in a concurrent session on the same shared clone happens to
    have staged for an unrelated reason" (a body typo fix, say) -- the exact
    CLAUDE.md "ec2.md nearly got committed into an unrelated PR" failure
    mode, just moved from "any staged file" down to "any staged fragment".
    Checking the staged diff's actual content for what a real reassignment
    looks like closes that gap without needing per-caller bookkeeping.

    One `git diff --cached` call for ALL candidates at once (not one per
    fragment) -- parsing the multi-file diff by its `diff --git a/... b/...`
    headers keeps this from re-introducing the redundant-git-call pattern
    finding 8 removed elsewhere in this same fix."""
    if not fragment_paths:
        return []
    diff = _git.run(doc_repo_root, ["diff", "--cached", "--", *fragment_paths])
    reassigned: list[str] = []
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            current = line.rsplit(" b/", 1)[-1] if " b/" in line else None
        elif current and current not in reassigned and line.startswith("+target_version:") \
                and "unassigned" not in line:
            reassigned.append(current)
    return reassigned


def _parent_full_name(parent: dict) -> str:
    """`gh repo list --json parent`'s embedded parent object has no
    `nameWithOwner` field (unlike a top-level repo) — build it from
    owner+name, still honoring `nameWithOwner` if a future gh version adds it."""
    if not parent:
        return ""
    if parent.get("nameWithOwner"):
        return parent["nameWithOwner"]
    owner = (parent.get("owner") or {}).get("login", "")
    name = parent.get("name", "")
    return f"{owner}/{name}" if owner and name else ""


def detect_fork(*, upstream: str = UPSTREAM_HUB_DOC) -> Optional[str]:
    user = _gh.current_user_login()
    repos = _gh.run_json([
        "repo", "list", user, "--fork", "--limit", "100", "--json", "name,parent",
    ])
    for r in repos:
        if _parent_full_name(r.get("parent") or {}) == upstream:
            return f"{user}/{r['name']}"
    return None


def _branch_has_commits_to_push(doc_repo_root: str, branch: str) -> bool:
    for base in ("origin/main", "origin/master", "main", "master"):
        try:
            n = _git.run(doc_repo_root, ["rev-list", "--count", f"{base}..{branch}"]).strip()
        except _git.GitError:
            continue
        if n.isdigit():
            return int(n) > 0
    return False


def commit_release_notes(*, doc_repo_root: str, branch: str, title: str, paths: list[str] | None = None) -> None:
    """preview.py writes and stages the new file but never commits it — without
    this, `git push` ships a branch identical to base and the draft PR is empty.

    Always commits via an explicit `--` pathspec rather than a bare `git
    commit` -- cutmode audit finding E: a bare commit ships whatever else
    happens to be staged in `doc_repo_root`, which in a shared clone another
    session is using concurrently can sweep in a completely unrelated file
    (the exact CLAUDE.md "ec2.md nearly got committed into an unrelated PR"
    failure mode).

    The pathspec is always `DEFAULT_REL_PATH` PLUS whatever extra `paths` the
    caller passed (PR #32 review finding 2: `--path`'s own help text calls it
    an "extra path to commit alongside" the default -- additive, not a
    replacement; an earlier version of this function swapped in `paths` INSTEAD
    of the default whenever any were given, so a caller following that exact
    help text silently dropped `DEFAULT_REL_PATH`, the actual release-notes.mdx
    edit, out of the commit) PLUS whatever is currently staged under
    `FRAGMENT_GLOB` -- that last part is auto-discovered from git, not passed
    in, so a cut's fragment reassignment (assign_target_version.py's
    --doc-repo-root stages it) rides along in the same commit as the
    release-notes.mdx splice without the caller having to track and pass every
    reassigned fragment path itself (finding F, and PR #32 review finding 1:
    an earlier version of this fix made that tracking the *caller's* job via
    an external SKILL.md scratch file, which had no way to catch a lost or
    incomplete list -- reading it directly from git's own staged-file list
    removes that dependency entirely). `paths` still exists for anything
    outside the fragment glob a caller explicitly wants included.

    A staged fragment is only auto-discovered if its own staged diff shows an
    actual target_version reassignment, not merely a path match on
    FRAGMENT_GLOB (PR #32 review finding 6, altitude) -- see
    _fragments_with_staged_reassignment's docstring for why a glob match
    alone isn't enough in a shared clone."""
    current = _git.head_branch(doc_repo_root)
    if current != branch:
        raise ValueError(
            f"hub-doc repo is on {current!r}, not the release-note branch {branch!r}; "
            "run preview first so the generated file is staged on that branch"
        )
    staged_now = _staged_paths(doc_repo_root)
    explicit = set(paths or [])
    # Fragments the caller already named explicitly are trusted as-is (that's
    # what `paths` is for); only fragments NOT already explicit go through
    # the reassignment-content check below -- a caller that already knows
    # exactly which fragment it wants committed shouldn't be second-guessed.
    fragment_candidates = [p for p in _staged_paths_matching(staged_now, FRAGMENT_GLOB) if p not in explicit]
    auto_fragment_paths = _fragments_with_staged_reassignment(doc_repo_root, fragment_candidates)
    # dict.fromkeys dedupes while preserving order, in case a caller's
    # explicit `paths` already names one of the auto-discovered fragments.
    all_paths = list(dict.fromkeys([DEFAULT_REL_PATH, *(paths or []), *auto_fragment_paths]))
    staged = set(staged_now) & set(all_paths)
    if staged:
        _git.run(doc_repo_root, ["commit", "-m", title, "--", *all_paths])
        return
    if _branch_has_commits_to_push(doc_repo_root, branch):
        return  # already committed by a previous run; nothing to stage
    raise ValueError(
        "no staged changes among the expected paths and the branch has no commits to push; "
        "run preview before pushing (it stages the generated file)"
    )


def open_release_notes_pr(
    *, doc_repo_root: str, branch: str, title: str, body: str, paths: list[str] | None = None,
) -> str:
    fork = detect_fork()
    if fork is None:
        raise RuntimeError(f"no fork of {UPSTREAM_HUB_DOC} detected for the current gh user; fork it first")
    commit_release_notes(doc_repo_root=doc_repo_root, branch=branch, title=title, paths=paths)
    fork_url = f"https://github.com/{fork}.git"
    try:
        _git.run(doc_repo_root, ["remote", "add", "fork", fork_url])
    except _git.GitError:
        _git.run(doc_repo_root, ["remote", "set-url", "fork", fork_url])
    _git.run(doc_repo_root, ["push", "-u", "fork", f"{branch}:{branch}"])
    return _gh.run_text([
        "pr", "create",
        "--repo", UPSTREAM_HUB_DOC,
        "--base", "main",
        "--head", f"{fork.split('/')[0]}:{branch}",
        "--draft",
        "--title", title,
        "--body", body,
    ]).strip()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--doc-repo-root", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--body-file", required=True)
    parser.add_argument(
        "--path", action="append", dest="paths",
        help=f"extra repo-relative path to commit alongside {DEFAULT_REL_PATH!r} (repeatable). "
             f"Rarely needed: any fragment reassigned this run (see assign_target_version.py's "
             f"--doc-repo-root) is auto-discovered from what's already staged under "
             f"{FRAGMENT_GLOB!r} and committed together, without needing to be listed here.",
    )
    args = parser.parse_args(argv)
    body = Path(args.body_file).read_text(encoding="utf-8")
    url = open_release_notes_pr(
        doc_repo_root=args.doc_repo_root, branch=args.branch, title=args.title, body=body,
        paths=args.paths,
    )
    print(json.dumps({"pr_url": url}))
    return 0


if __name__ == "__main__":
    _discover.maybe_reexec()
    sys.exit(main(sys.argv[1:]))
