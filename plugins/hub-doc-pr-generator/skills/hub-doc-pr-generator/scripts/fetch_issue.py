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
import concurrent.futures
import json
import re
import sys
from dataclasses import dataclass
from typing import Optional

from scripts import _discover
from scripts.fetch_pr import (
    _fetch_issue,
    _fetch_sub_issues,
    _cwd_remote,
    _BOT_AUTHOR_RE,
    fetch_issue_graph,
    RELATED_PR_CAP,
)


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
    # The issue body, its sub-issue/related-PR graph, and native GitHub
    # sub-issues are three independent `gh` calls, keyed only off
    # ref.repo/ref.number -- none reads another's result -- so they run
    # concurrently instead of one after another (traefik/hub-doc PR #988
    # round-3 finding #6). Threads, not asyncio: each call is a blocking
    # `gh` subprocess invocation via _gh.run_json(), which releases the GIL
    # while it waits, so this is a straightforward I/O-bound win without
    # having to make _gh/fetch_pr's helpers async.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        raw_future = pool.submit(_fetch_issue, ref.repo, ref.number)
        graph_future = pool.submit(fetch_issue_graph, ref.repo, ref.number)
        raw_sub_issues_future = pool.submit(_fetch_sub_issues, ref.repo, ref.number)
        raw = raw_future.result()
        # Native GitHub sub-issue relationship (parent + siblings) and any PR
        # that closes this issue or a sibling, cross-repo included -- this
        # entry point previously never queried this at all, so it always came
        # back `parent: null` / `siblings: []` / `related_prs: []` even when
        # GitHub's graph had all three populated (see fetch_pr.py's
        # fetch_issue_graph, already used by the impl-PR path; this is the
        # same call, just also wired into the issue-only path).
        graph = graph_future.result()
        raw_sub_issues = raw_sub_issues_future.result()

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
        "parent": graph["parent"],
        "siblings": graph["siblings"],
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
        for sub in raw_sub_issues
    ]

    return {
        "impl_repo": impl_repo,
        "prs": [],
        "merged": {
            "files_changed": [],
            "primary_pr": None,
            "linked_issues": [issue],
            "sub_issues": sub_issues,
            "related_prs": graph["related_prs"][:RELATED_PR_CAP],
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
    _discover.maybe_reexec()
    sys.exit(main(sys.argv[1:]))
