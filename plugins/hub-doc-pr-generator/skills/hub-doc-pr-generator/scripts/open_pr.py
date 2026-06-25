"""open_pr.py — push + draft PR (Hub) or commit (OSS)."""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional
from scripts import _gh, _git


def _parent_full_name(parent: dict) -> str:
    """Return the parent repo's ``owner/name`` from a `gh repo list --json parent` entry.

    The embedded parent object exposes ``name`` and ``owner.login`` but, unlike a
    top-level repo, no ``nameWithOwner`` field — so reading ``nameWithOwner`` always
    came back empty and no fork ever matched. Build the slug from owner+name, and
    still honor ``nameWithOwner`` when present for forward-compatibility.
    """
    if not parent:
        return ""
    if parent.get("nameWithOwner"):
        return parent["nameWithOwner"]
    owner = (parent.get("owner") or {}).get("login", "")
    name = parent.get("name", "")
    return f"{owner}/{name}" if owner and name else ""


def detect_fork(*, upstream: str) -> Optional[str]:
    user = _gh.current_user_login()
    repos = _gh.run_json([
        "repo", "list", user, "--fork", "--limit", "100",
        "--json", "name,parent",
    ])
    for r in repos:
        if _parent_full_name(r.get("parent") or {}) == upstream:
            return f"{user}/{r['name']}"
    return None


UPSTREAM_HUB_DOC = "traefik/hub-doc"


def _branch_has_commits_to_push(doc_repo_root: str, branch: str) -> bool:
    """True if *branch* already has commits beyond its base (e.g. a prior run
    committed but the push failed). Returns False when the base can't be found."""
    for base in ("origin/main", "origin/master", "main", "master"):
        try:
            n = _git.run(doc_repo_root, ["rev-list", "--count", f"{base}..{branch}"]).strip()
        except _git.GitError:
            continue
        if n.isdigit():
            return int(n) > 0
    return False


def commit_hub_docs(*, doc_repo_root: str, branch: str, title: str) -> None:
    """Turn the staged doc edits into a commit on the feature branch.

    preview.apply_edits writes and *stages* the generated files but never commits
    them. Without this step `git push` ships a branch identical to base and the
    draft PR is empty. `title` already carries the "docs: " prefix from the
    caller, so it's used verbatim as the commit subject.

    Refuses if the repo isn't on the expected branch. If nothing is staged, that's
    only an error when the branch also has no commits ahead of base — otherwise a
    prior run already committed (e.g. the push failed and we're retrying), so there
    is nothing to do and we let the push proceed."""
    current = _git.head_branch(doc_repo_root)
    if current != branch:
        raise ValueError(
            f"hub-doc repo is on {current!r}, not the doc branch {branch!r}; "
            "run preview first so the generated files are staged on that branch"
        )
    staged = _git.run(doc_repo_root, ["diff", "--cached", "--name-only"]).strip()
    if staged:
        _git.run(doc_repo_root, ["commit", "-m", title])
        return
    if _branch_has_commits_to_push(doc_repo_root, branch):
        return  # already committed by a previous run; nothing to stage
    raise ValueError(
        "no staged doc changes and the branch has no commits to push; "
        "run preview before pushing (it stages the generated files)"
    )


def open_hub_pr(*, doc_repo_root: str, fork: str, branch: str,
                title: str, body: str) -> str:
    # Commit the staged doc edits first — pushing without this would open an
    # empty draft PR.
    commit_hub_docs(doc_repo_root=doc_repo_root, branch=branch, title=title)
    fork_url = f"https://github.com/{fork}.git"
    # Add fork remote if missing; ignore failure if it already exists.
    try:
        _git.run(doc_repo_root, ["remote", "add", "fork", fork_url])
    except _git.GitError:
        _git.run(doc_repo_root, ["remote", "set-url", "fork", fork_url])
    _git.run(doc_repo_root, ["push", "-u", "fork", f"{branch}:{branch}"])
    url = _gh.run_text([
        "pr", "create",
        "--repo", UPSTREAM_HUB_DOC,
        "--base", "main",
        "--head", f"{fork.split('/')[0]}:{branch}",
        "--draft",
        "--title", title,
        "--body", body,
    ]).strip()
    return url


def commit_oss_docs(*, impl_repo_root: str, title: str,
                    doc_files: list[str], refs_other_prs: list[int]) -> None:
    if not doc_files:
        raise ValueError("commit_oss_docs: no doc files specified; nothing to commit")
    _git.run(impl_repo_root, ["add", *doc_files])
    msg_lines = [f"docs: {title}"]
    if refs_other_prs:
        msg_lines.append("")
        msg_lines.append("Refs: " + ", ".join(f"traefik#{n}" for n in refs_other_prs))
    msg = "\n".join(msg_lines)
    _git.run(impl_repo_root, ["commit", "-m", msg])


_NON_SLUG_RE = re.compile(r"[^a-z0-9]+")


def branch_slug_from_title(title: str, *, prefix: str = "docs/") -> str:
    stripped = re.sub(r"^(feat|fix|chore|refactor|test|docs|style|perf|build|ci)(\([^)]+\))?:\s*", "", title, flags=re.IGNORECASE)
    slug = _NON_SLUG_RE.sub("-", stripped.lower()).strip("-") or "feature"
    return prefix + slug[:40]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)

    hub = sub.add_parser("hub")
    hub.add_argument("--doc-repo-root", required=True)
    hub.add_argument("--branch", required=True)
    hub.add_argument("--title", required=True)
    hub.add_argument("--body-file", required=True)

    oss = sub.add_parser("oss")
    oss.add_argument("--impl-repo-root", required=True)
    oss.add_argument("--title", required=True)
    oss.add_argument("--doc-file", action="append", default=[])
    oss.add_argument("--ref-pr", type=int, action="append", default=[])

    args = parser.parse_args(argv)
    if args.mode == "hub":
        fork = detect_fork(upstream=UPSTREAM_HUB_DOC)
        if fork is None:
            print(json.dumps({"error": "no fork detected; manual fork required"}))
            return 2
        body = Path(args.body_file).read_text(encoding="utf-8")
        url = open_hub_pr(
            doc_repo_root=args.doc_repo_root,
            fork=fork, branch=args.branch,
            title=args.title, body=body,
        )
        print(json.dumps({"pr_url": url}))
        return 0
    else:
        commit_oss_docs(
            impl_repo_root=args.impl_repo_root,
            title=args.title,
            doc_files=args.doc_file,
            refs_other_prs=args.ref_pr,
        )
        print(json.dumps({"committed": True}))
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
