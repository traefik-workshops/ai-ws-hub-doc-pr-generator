"""open_pr.py — push + draft PR (Hub) or commit (OSS)."""
from __future__ import annotations
import argparse
import json
import sys
from typing import Optional
from scripts import _gh, _git


def detect_fork(*, upstream: str) -> Optional[str]:
    user = _gh.current_user_login()
    repos = _gh.run_json([
        "repo", "list", user, "--fork",
        "--json", "name,parent",
    ])
    for r in repos:
        parent = (r.get("parent") or {}).get("nameWithOwner", "")
        if parent == upstream:
            return f"{user}/{r['name']}"
    return None


UPSTREAM_HUB_DOC = "traefik/hub-doc"


def open_hub_pr(*, doc_repo_root: str, fork: str, branch: str,
                title: str, body: str) -> str:
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
        "--base", "master",
        "--head", f"{fork.split('/')[0]}:{branch}",
        "--draft",
        "--title", title,
        "--body", body,
    ]).strip()
    return url


def commit_oss_docs(*, impl_repo_root: str, title: str,
                    doc_files: list[str], refs_other_prs: list[int]) -> None:
    if doc_files:
        _git.run(impl_repo_root, ["add", *doc_files])
    msg_lines = [f"docs: {title}", ""]
    if refs_other_prs:
        msg_lines.append("Refs: " + ", ".join(f"traefik#{n}" for n in refs_other_prs))
        msg_lines.append("")
    msg_lines.append("Co-Authored-By: Claude <noreply@anthropic.com>")
    msg = "\n".join(msg_lines)
    _git.run(impl_repo_root, ["commit", "-m", msg])


import re

_NON_SLUG_RE = re.compile(r"[^a-z0-9]+")


def branch_slug_from_title(title: str, *, prefix: str = "docs/") -> str:
    stripped = re.sub(r"^(feat|fix|chore|refactor|test|docs|style|perf|build|ci)(\([^)]+\))?:\s*", "", title, flags=re.IGNORECASE)
    slug = _NON_SLUG_RE.sub("-", stripped.lower()).strip("-")
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
        body = open(args.body_file).read()
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
