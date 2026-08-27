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
import json
import sys
from pathlib import Path
from typing import Optional

from scripts import _discover, _gh, _git

UPSTREAM_HUB_DOC = "traefik/hub-doc"


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


def commit_release_notes(*, doc_repo_root: str, branch: str, title: str) -> None:
    """preview.py writes and stages the new file but never commits it — without
    this, `git push` ships a branch identical to base and the draft PR is empty."""
    current = _git.head_branch(doc_repo_root)
    if current != branch:
        raise ValueError(
            f"hub-doc repo is on {current!r}, not the release-note branch {branch!r}; "
            "run preview first so the generated file is staged on that branch"
        )
    staged = _git.run(doc_repo_root, ["diff", "--cached", "--name-only"]).strip()
    if staged:
        _git.run(doc_repo_root, ["commit", "-m", title])
        return
    if _branch_has_commits_to_push(doc_repo_root, branch):
        return  # already committed by a previous run; nothing to stage
    raise ValueError(
        "no staged changes and the branch has no commits to push; "
        "run preview before pushing (it stages the generated file)"
    )


def open_release_notes_pr(*, doc_repo_root: str, branch: str, title: str, body: str) -> str:
    fork = detect_fork()
    if fork is None:
        raise RuntimeError(f"no fork of {UPSTREAM_HUB_DOC} detected for the current gh user; fork it first")
    commit_release_notes(doc_repo_root=doc_repo_root, branch=branch, title=title)
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
    args = parser.parse_args(argv)
    body = Path(args.body_file).read_text(encoding="utf-8")
    url = open_release_notes_pr(doc_repo_root=args.doc_repo_root, branch=args.branch, title=args.title, body=body)
    print(json.dumps({"pr_url": url}))
    return 0


if __name__ == "__main__":
    _discover.maybe_reexec()
    sys.exit(main(sys.argv[1:]))
