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
