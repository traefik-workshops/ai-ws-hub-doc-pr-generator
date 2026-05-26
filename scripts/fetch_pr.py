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
