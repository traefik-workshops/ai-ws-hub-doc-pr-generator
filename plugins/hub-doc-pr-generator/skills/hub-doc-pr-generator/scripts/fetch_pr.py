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


PARENT_BODY_CAP = 4000
RELATED_PR_CAP = 30

_ISSUE_GRAPH_QUERY = """
query($owner:String!,$repo:String!,$num:Int!){
  repository(owner:$owner,name:$repo){
    issue(number:$num){
      number
      closedByPullRequestsReferences(first:20, includeClosedPrs:true){
        nodes { number title url repository { nameWithOwner } }
      }
      parent {
        number title body
        subIssues(first:50){
          nodes {
            number title
            closedByPullRequestsReferences(first:10, includeClosedPrs:true){
              nodes { number title url repository { nameWithOwner } }
            }
          }
        }
      }
    }
  }
}
"""


def _pr_refs(node_block: Optional[dict]) -> list[dict]:
    out = []
    for n in (node_block or {}).get("nodes", []):
        out.append({
            "number": n["number"],
            "title": n.get("title", ""),
            "url": n.get("url", ""),
            "repo": (n.get("repository") or {}).get("nameWithOwner", ""),
        })
    return out


def fetch_issue_graph(repo: str, number: int) -> dict:
    """Upward context for one issue: its parent (1 level, with body), the
    parent's other sub-issues (siblings, number+title), and the PRs that close
    the issue and each sibling. Degrades to empty when the repo doesn't use
    native sub-issues or the API call fails."""
    empty = {"parent": None, "siblings": [], "related_prs": []}
    owner, name = repo.split("/", 1)
    try:
        resp = _gh.run_json([
            "api", "graphql",
            "-f", f"query={_ISSUE_GRAPH_QUERY}",
            "-F", f"owner={owner}",
            "-F", f"repo={name}",
            "-F", f"num={number}",
        ])
    except _gh.GhError:
        return empty

    issue = (((resp or {}).get("data") or {}).get("repository") or {}).get("issue") or {}
    if not issue:
        return empty

    related = _pr_refs(issue.get("closedByPullRequestsReferences"))
    parent = None
    siblings: list[dict] = []
    parent_raw = issue.get("parent")
    if parent_raw:
        parent = {
            "number": parent_raw["number"],
            "title": parent_raw.get("title", ""),
            "body": (parent_raw.get("body") or "")[:PARENT_BODY_CAP],
        }
        for s in (parent_raw.get("subIssues") or {}).get("nodes", []):
            if s["number"] == number:
                continue  # skip the issue itself
            siblings.append({"number": s["number"], "title": s.get("title", "")})
            related.extend(_pr_refs(s.get("closedByPullRequestsReferences")))

    return {"parent": parent, "siblings": siblings, "related_prs": related}


def merge_prs(prs: list[dict]) -> dict:
    if not prs:
        return {"files_changed": [], "linked_issues": [], "sub_issues": [],
                "related_prs": [], "primary_pr": None, "title_synthesis": ""}

    by_path: dict[str, dict] = {}
    for pr in prs:
        for f in pr.get("files_changed", []):
            entry = by_path.setdefault(
                f["path"], {"path": f["path"], "additions": 0, "deletions": 0}
            )
            entry["additions"] += f.get("additions", 0)
            entry["deletions"] += f.get("deletions", 0)

    seen_issue_nums: set[int] = set()
    linked_issues = []
    sub_issues = []
    for pr in prs:
        for iss in pr.get("linked_issues", []):
            if iss["number"] in seen_issue_nums:
                continue
            seen_issue_nums.add(iss["number"])
            (sub_issues if iss.get("is_sub_issue") else linked_issues).append(iss)

    related_by_key: dict[tuple, dict] = {}
    for pr in prs:
        for rp in pr.get("related_prs", []):
            related_by_key[(rp["repo"], rp["number"])] = rp

    primary = max(
        prs,
        key=lambda p: sum(f.get("additions", 0) for f in p.get("files_changed", [])),
    )

    return {
        "files_changed": list(by_path.values()),
        "linked_issues": linked_issues,
        "sub_issues": sub_issues,
        "related_prs": list(related_by_key.values()),
        "primary_pr": primary["number"],
        "title_synthesis": " / ".join(p["title"] for p in prs),
    }


def find_existing_doc_pr(impl_repo: str, pr_number: int) -> Optional[dict]:
    if impl_repo != "traefik/traefik-hub":
        return None
    short = impl_repo.split("/")[-1]
    results = _gh.run_json([
        "pr", "list", "--repo", "traefik/hub-doc",
        "--state", "open",
        "--search", f"{short}#{pr_number}",
        "--json", "number,title,url",
    ])
    return results[0] if results else None


def build_bundle(refs: list[PrRef]) -> dict:
    impl_repo = refs[0].repo
    source_pr_numbers = {ref.number for ref in refs}
    prs = []
    for ref in refs:
        pr = fetch_single(ref)
        pr["linked_issues"] = collect_issues(
            impl_repo, pr["body"], pr["closingIssuesReferences"]
        )
        pr["sub_issues"] = [i for i in pr["linked_issues"] if i.get("is_sub_issue")]
        pr["linked_issues"] = [i for i in pr["linked_issues"] if not i.get("is_sub_issue")]

        related_by_key: dict[tuple, dict] = {}
        for iss in pr["linked_issues"]:
            graph = fetch_issue_graph(impl_repo, iss["number"])
            iss["parent"] = graph["parent"]
            iss["siblings"] = graph["siblings"]
            for rp in graph["related_prs"]:
                if rp["number"] in source_pr_numbers and rp["repo"] == impl_repo:
                    continue  # don't list the PR(s) we're documenting
                related_by_key[(rp["repo"], rp["number"])] = rp
        pr["related_prs"] = list(related_by_key.values())[:RELATED_PR_CAP]
        prs.append(pr)
    existing = find_existing_doc_pr(impl_repo, refs[0].number) if len(refs) == 1 else None
    return {
        "impl_repo": impl_repo,
        "prs": prs,
        "merged": merge_prs(prs),
        "existing_doc_pr": existing,
    }


def _cwd_remote() -> Optional[str]:
    from scripts import _git
    try:
        url = _git.run(".", ["config", "--get", "remote.origin.url"]).strip()
    except Exception:
        return None
    m = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/\s]+?)(?:\.git)?$", url)
    return f"{m['owner']}/{m['name']}" if m else None


def main(argv: list[str]) -> int:
    import json as _json
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr", action="append", default=[],
                        help="PR number or full URL; repeat for multi-PR")
    parser.add_argument("--repo", default=None,
                        help="Override owner/name; otherwise inferred from cwd remote")
    args = parser.parse_args(argv)
    cwd_remote = args.repo or _cwd_remote()
    refs = parse_pr_inputs(args.pr, cwd_remote)
    bundle = build_bundle(refs)
    print(_json.dumps(bundle, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
