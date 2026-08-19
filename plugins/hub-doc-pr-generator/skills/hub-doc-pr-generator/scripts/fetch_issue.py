"""fetch_issue.py — gather a standalone GitHub issue (no implementation PR)
into a pipeline-compatible bundle.

Usage:
  python -m scripts.fetch_issue --issue https://github.com/owner/repo/issues/N [--impl-repo owner/repo]
  python -m scripts.fetch_issue --issue N --repo owner/repo

fetch_pr.py has no entry point for a documentation-worthy issue that has no
implementation PR at all — every downstream step assumes a PR's diff exists.
That's not one narrow scenario: a QA finding investigated and closed as
working-as-intended, a config/usage gotcha that never needed a PR, and a
content gap or correction someone filed directly against the docs (no code
change involved, ever) all land here the same way. Nothing here is gated on
the issue's state, labels, or author -- any issue URL works. This produces a
bundle shaped closely enough to fetch_pr.py's that classify.py and
locate_targets.py run against it unmodified: `prs: []`, empty
`files_changed`, and a new `issue` key that classify() substitutes for its
usual PR-derived `primary` when `prs` is empty.

Emits a single JSON document on stdout.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass
from typing import Optional

from scripts.fetch_pr import _fetch_issue, _fetch_sub_issues, _cwd_remote, _BOT_AUTHOR_RE


_ISSUE_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<num>\d+)/?$"
)


@dataclass(frozen=True)
class IssueRef:
    repo: str   # "owner/name"
    number: int


def parse_issue_input(arg: str, cwd_remote: Optional[str]) -> IssueRef:
    m = _ISSUE_URL_RE.match(arg)
    if m:
        return IssueRef(f"{m['owner']}/{m['repo']}", int(m["num"]))
    if arg.isdigit():
        if cwd_remote is None:
            raise ValueError(
                f"issue number {arg!r} given without a cwd remote — pass a full "
                "URL, or --repo, or run from inside the issue's own repo."
            )
        return IssueRef(cwd_remote, int(arg))
    raise ValueError(f"unrecognized issue input: {arg!r}")


def build_bundle(ref: IssueRef, *, impl_repo: str) -> dict:
    """`impl_repo` is the repo the documented FEATURE lives in (e.g.
    traefik/traefik-hub) — separate from `ref.repo`, the issue's own repo,
    since issues frequently live in a separate tracker (traefik/hub-issues)
    from the impl repo they're actually about."""
    raw = _fetch_issue(ref.repo, ref.number)
    comments = [
        {"author": (c.get("author") or {}).get("login", ""), "body": c.get("body", "")}
        for c in raw.get("comments", [])
        if c.get("body")
        and not _BOT_AUTHOR_RE.search((c.get("author") or {}).get("login", ""))
    ]
    issue = {
        "number": raw["number"],
        "repo": ref.repo,
        "title": raw["title"],
        "body": raw.get("body") or "",
        "labels": [l["name"] for l in raw.get("labels", [])],
        "state": raw.get("state", ""),
        "state_reason": raw.get("stateReason", ""),
        "comments": comments,
        "is_sub_issue": False,
    }
    sub_issues = [
        {
            "number": sub["number"],
            "repo": ref.repo,
            "title": sub.get("title", ""),
            "body": sub.get("body", ""),
            "comments": [],
            "is_sub_issue": True,
        }
        for sub in _fetch_sub_issues(ref.repo, ref.number)
    ]

    return {
        "impl_repo": impl_repo,
        "prs": [],
        "merged": {
            "files_changed": [],
            "primary_pr": None,
            "linked_issues": [issue],
            "sub_issues": sub_issues,
            "related_prs": [],
            "title_synthesis": issue["title"],
        },
        "existing_doc_pr": None,
        "issue": issue,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue", required=True, help="issue number or full URL")
    parser.add_argument("--repo", default=None,
                        help="the issue's own repo; otherwise inferred from the URL or cwd remote")
    parser.add_argument("--impl-repo", default=None,
                        help="repo the documented feature lives in; defaults to the issue's own repo")
    args = parser.parse_args(argv)
    cwd_remote = args.repo or _cwd_remote()
    ref = parse_issue_input(args.issue, cwd_remote)
    impl_repo = args.impl_repo or ref.repo
    bundle = build_bundle(ref, impl_repo=impl_repo)
    print(json.dumps(bundle, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
