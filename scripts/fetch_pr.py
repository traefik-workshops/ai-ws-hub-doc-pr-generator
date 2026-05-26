"""fetch_pr.py — gather PR + linked issues + sub-issues + diff into a JSON bundle.

Usage:
  python -m scripts.fetch_pr --repo traefik/traefik-hub --pr 1234 [--pr 1240 ...]
  python -m scripts.fetch_pr --auto-detect          # cwd must be a checked-out PR branch
  python -m scripts.fetch_pr --url https://github.com/owner/repo/pull/N [...]

Emits a single JSON document on stdout.
"""
from __future__ import annotations
import argparse
import re
import sys
from dataclasses import dataclass
from typing import Optional

from scripts import _gh


DIFF_LINE_CAP = 2000


_PR_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<num>\d+)/?$"
)


@dataclass(frozen=True)
class PrRef:
    repo: str   # "owner/name"
    number: int


def fetch_single(ref: PrRef) -> dict:
    owner_repo = ref.repo
    view = _gh.run_json([
        "pr", "view", str(ref.number),
        "--repo", owner_repo,
        "--json",
        "number,title,body,labels,author,headRefName,baseRefName,headRefOid,"
        "isDraft,mergeable,files,closingIssuesReferences",
    ])
    diff_text = _gh.run_text(["pr", "diff", str(ref.number), "--repo", owner_repo, "--patch"])
    diff_lines = diff_text.splitlines()
    truncated = len(diff_lines) > DIFF_LINE_CAP
    diff_capped = "\n".join(diff_lines[:DIFF_LINE_CAP])

    return {
        "number": view["number"],
        "title": view["title"],
        "body": view.get("body") or "",
        "labels": [l["name"] for l in view.get("labels", [])],
        "author": (view.get("author") or {}).get("login", ""),
        "branch": view["headRefName"],
        "base": view["baseRefName"],
        "head": view["headRefOid"],
        "isDraft": view.get("isDraft", False),
        "mergeable": view.get("mergeable", "UNKNOWN"),
        "diff": diff_capped,
        "diff_truncated": truncated,
        "files_changed": [
            {"path": f["path"], "additions": f["additions"], "deletions": f["deletions"]}
            for f in view.get("files", [])
        ],
        "closingIssuesReferences": [
            n["number"] for n in (view.get("closingIssuesReferences") or {}).get("nodes", [])
        ],
    }


def parse_pr_inputs(args: list[str], cwd_remote: Optional[str]) -> list[PrRef]:
    refs: list[PrRef] = []
    for arg in args:
        m = _PR_URL_RE.match(arg)
        if m:
            refs.append(PrRef(f"{m['owner']}/{m['repo']}", int(m["num"])))
            continue
        if arg.isdigit():
            if cwd_remote is None:
                raise ValueError(
                    f"PR number {arg!r} given without a cwd remote — pass a full URL "
                    "or run from inside the impl repo."
                )
            refs.append(PrRef(cwd_remote, int(arg)))
            continue
        raise ValueError(f"unrecognized PR input: {arg!r}")

    if not refs:
        raise ValueError("no PRs given")

    repos = {ref.repo for ref in refs}
    if len(repos) > 1:
        raise ValueError(
            f"cross-repo multi-PR not supported (got {sorted(repos)}). "
            "Run the skill once per impl repo."
        )
    return refs


_BODY_LINK_RE = re.compile(r"(?:Closes|Fixes|Resolves):?\s+#(\d+)", re.IGNORECASE)
_BOT_AUTHOR_RE = re.compile(r"\[bot\]$", re.IGNORECASE)


def _fetch_sub_issues(repo: str, issue_number: int) -> list[dict]:
    try:
        return _gh.run_json([
            "api", f"repos/{repo}/issues/{issue_number}/sub_issues",
        ])
    except _gh.GhError:
        return []  # endpoint not enabled for this repo


def _fetch_issue(repo: str, number: int) -> dict:
    return _gh.run_json([
        "issue", "view", str(number), "--repo", repo,
        "--json", "number,title,body,comments",
    ])


def collect_issues(repo: str, pr_body: str, closing_refs: list[int]) -> list[dict]:
    seen: set[int] = set()
    queue: list[int] = list(dict.fromkeys(closing_refs))
    for m in _BODY_LINK_RE.finditer(pr_body):
        n = int(m.group(1))
        if n not in queue:
            queue.append(n)

    out: list[dict] = []
    for num in queue:
        if num in seen:
            continue
        seen.add(num)
        raw = _fetch_issue(repo, num)
        comments = [
            {"author": (c.get("author") or {}).get("login", ""), "body": c.get("body", "")}
            for c in raw.get("comments", [])
            if c.get("body")
            and not _BOT_AUTHOR_RE.search((c.get("author") or {}).get("login", ""))
        ]
        out.append({
            "number": raw["number"],
            "title": raw["title"],
            "body": raw.get("body") or "",
            "comments": comments,
            "is_sub_issue": False,
        })
        for sub in _fetch_sub_issues(repo, num):
            if sub["number"] in seen:
                continue
            seen.add(sub["number"])
            out.append({
                "number": sub["number"],
                "title": sub.get("title", ""),
                "body": sub.get("body", ""),
                "comments": [],
                "is_sub_issue": True,
            })
    return out


def main(argv: list[str]) -> int:
    # Filled in by later tasks.
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr", action="append", default=[])
    parser.add_argument("--url", action="append", default=[])
    parser.add_argument("--repo", default=None)
    parser.add_argument("--auto-detect", action="store_true")
    parser.parse_args(argv)
    print("{}", file=sys.stdout)  # placeholder
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
