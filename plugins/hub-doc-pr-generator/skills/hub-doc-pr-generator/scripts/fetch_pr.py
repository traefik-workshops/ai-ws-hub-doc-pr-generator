"""fetch_pr.py — gather PR + linked issues + sub-issues + diff into a JSON bundle.

Usage:
  python -m scripts.fetch_pr --repo traefik/traefik-hub --pr 1234 [--pr 1240 ...]
  python -m scripts.fetch_pr --auto-detect          # cwd must be a checked-out PR branch
  python -m scripts.fetch_pr --pr https://github.com/owner/repo/pull/N [...]

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

# Patterns for file paths that carry no documentation value.
_FILTER_PATH_RES = [
    re.compile(r"_test\.go$"),
    re.compile(r"/testdata/"),
    re.compile(r"zz_generated.*\.go$"),
    re.compile(r"\.pb\.go$"),
    re.compile(r"_generated\.go$"),
]


def _is_noise_path(path: str) -> bool:
    """True for test/generated files that carry no documentation value."""
    return any(pat.search(path) for pat in _FILTER_PATH_RES)


def _filter_diff(diff_text: str) -> tuple[str, bool]:
    """Remove hunks for test and generated files from a unified diff.

    Returns (filtered_diff, was_filtered) where was_filtered is True if at
    least one hunk was dropped.
    """
    if not diff_text:
        return diff_text, False

    # Split into per-file hunks on the "diff --git" boundary.
    # Each element (except possibly a leading empty one) begins with that line.
    raw_hunks = re.split(r"(?=^diff --git )", diff_text, flags=re.MULTILINE)

    kept: list[str] = []
    dropped = 0
    for hunk in raw_hunks:
        if not hunk:
            continue
        # Extract the path from the "--- a/<path>" line (or the diff header).
        path_match = re.search(r"^(?:---|\+\+\+) [ab]/(.+)$", hunk, re.MULTILINE)
        if path_match:
            path = path_match.group(1)
            if _is_noise_path(path):
                dropped += 1
                continue
        kept.append(hunk)

    return "".join(kept), dropped > 0


_PR_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<num>\d+)/?$"
)


@dataclass(frozen=True)
class PrRef:
    repo: str   # "owner/name"
    number: int


def _closing_issue_nodes(ref) -> list:
    """`gh pr view --json closingIssuesReferences` returns a flat list, but the
    raw GraphQL shape is `{"nodes": [...]}`. Accept either."""
    if isinstance(ref, dict):
        return ref.get("nodes") or []
    return ref or []


_ISSUE_URL_RE = re.compile(r"github\.com/(?P<repo>[^/]+/[^/]+)/issues/\d+")


def _node_repo(node: dict, default: str) -> str:
    """A closing-issue reference can live in a different repo than the PR
    (e.g. traefik/traefik-hub PRs close traefik/hub-issues issues). Resolve the
    issue's own repo from the node, falling back to the PR's repo."""
    repo = node.get("repository") or {}
    owner = (repo.get("owner") or {}).get("login")
    name = repo.get("name")
    if owner and name:
        return f"{owner}/{name}"
    m = _ISSUE_URL_RE.search(node.get("url") or "")
    return m["repo"] if m else default


def fetch_single(ref: PrRef) -> dict:
    owner_repo = ref.repo
    view = _gh.run_json([
        "pr", "view", str(ref.number),
        "--repo", owner_repo,
        "--json",
        "number,title,body,labels,author,headRefName,baseRefName,headRefOid,"
        "isDraft,mergeable,mergedAt,files,closingIssuesReferences",
    ])
    diff_text = _gh.run_text(["pr", "diff", str(ref.number), "--repo", owner_repo, "--patch"])
    diff_text, diff_filtered = _filter_diff(diff_text)
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
        "merged_at": view.get("mergedAt"),
        "diff": diff_capped,
        "diff_truncated": truncated,
        "diff_filtered": diff_filtered,
        # Filter the structured file list with the same rule as the diff text, so
        # downstream heuristics (grounding, doc-kind, screenshots) don't key off
        # test/generated paths either.
        "files_changed": [
            {"path": f["path"], "additions": f["additions"], "deletions": f["deletions"]}
            for f in view.get("files", [])
            if not _is_noise_path(f["path"])
        ],
        "closingIssuesReferences": [
            {"number": n["number"], "repo": _node_repo(n, owner_repo)}
            for n in _closing_issue_nodes(view.get("closingIssuesReferences"))
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
                # Confirmed live (traefik-hub#1435 finding #3): running from a
                # directory that isn't a checkout of the impl repo raised this
                # with no pointer to either working alternative -- a full PR
                # URL (no repo inference needed at all), or `--repo
                # owner/name` (main() already threads this into cwd_remote
                # ahead of the git-remote lookup, so it doesn't require being
                # inside any particular checkout).
                raise ValueError(
                    f"PR number {arg!r} given without a way to resolve which repo it's "
                    "in — this only works when running from inside a checkout of the "
                    "impl repo (so its git remote can be inferred). Either pass the full "
                    f"PR URL instead of {arg!r}, or add --repo owner/name."
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


_BODY_LINK_RE = re.compile(
    r"(?:Closes|Fixes|Resolves):?\s+(?:(?P<repo>[\w.-]+/[\w.-]+))?#(?P<num>\d+)",
    re.IGNORECASE,
)
_BOT_AUTHOR_RE = re.compile(r"\[bot\]$", re.IGNORECASE)


def _fetch_sub_issues(repo: str, issue_number: int) -> list[dict]:
    try:
        return _gh.run_json([
            "api", f"repos/{repo}/issues/{issue_number}/sub_issues",
        ])
    except _gh.GhError:
        return []  # endpoint not enabled for this repo


def _fetch_issue(repo: str, number: int) -> dict:
    # labels/state/stateReason are additive: collect_issues() (linked-issue
    # path) still only plucks number/title/body/comments and ignores the
    # rest; fetch_issue.py (the standalone-issue entry point) is what
    # actually needs them.
    return _gh.run_json([
        "issue", "view", str(number), "--repo", repo,
        "--json", "number,title,body,comments,labels,state,stateReason",
    ])


def collect_issues(repo: str, pr_body: str, closing_refs: list[dict]) -> list[dict]:
    """`repo` is the PR's repo, used as the default when a reference doesn't name
    its own. Issues can live in a separate tracker (e.g. traefik/hub-issues), so
    each issue carries its own `repo` and dedup is keyed by (repo, number)."""
    seen: set[tuple[str, int]] = set()
    queue: list[tuple[str, int]] = []

    def _enqueue(r: str, n: int) -> None:
        if (r, n) not in queue:
            queue.append((r, n))

    for ref in closing_refs:
        _enqueue(ref.get("repo") or repo, ref["number"])
    for m in _BODY_LINK_RE.finditer(pr_body):
        _enqueue(m.group("repo") or repo, int(m.group("num")))

    out: list[dict] = []
    for issue_repo, num in queue:
        if (issue_repo, num) in seen:
            continue
        seen.add((issue_repo, num))
        raw = _fetch_issue(issue_repo, num)
        comments = [
            {"author": (c.get("author") or {}).get("login", ""), "body": c.get("body", "")}
            for c in raw.get("comments", [])
            if c.get("body")
            and not _BOT_AUTHOR_RE.search((c.get("author") or {}).get("login", ""))
        ]
        out.append({
            "number": raw["number"],
            "repo": issue_repo,
            "title": raw["title"],
            "body": raw.get("body") or "",
            "comments": comments,
            "is_sub_issue": False,
        })
        for sub in _fetch_sub_issues(issue_repo, num):
            if (issue_repo, sub["number"]) in seen:
                continue
            seen.add((issue_repo, sub["number"]))
            out.append({
                "number": sub["number"],
                "repo": issue_repo,
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

    seen_issue_keys: set[tuple] = set()
    linked_issues = []
    sub_issues = []
    for pr in prs:
        for iss in pr.get("linked_issues", []):
            key = (iss.get("repo"), iss["number"])
            if key in seen_issue_keys:
                continue
            seen_issue_keys.add(key)
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
            graph = fetch_issue_graph(iss.get("repo") or impl_repo, iss["number"])
            iss["parent"] = graph["parent"]
            iss["siblings"] = graph["siblings"]
            for rp in graph["related_prs"]:
                if rp["number"] in source_pr_numbers and rp["repo"] == impl_repo:
                    continue  # don't list the PR(s) we're documenting
                related_by_key[(rp["repo"], rp["number"])] = rp
        pr["related_prs"] = list(related_by_key.values())[:RELATED_PR_CAP]
        prs.append(pr)
    # Duplicate detection only searches by the first PR number. For multi-PR
    # invocations the search heuristic is less reliable, so we skip it and let
    # the engineer decide whether to update or create.
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
    parser.add_argument("--auto-detect", action="store_true",
                        help="detect PR number and repo from the current branch")
    args = parser.parse_args(argv)
    cwd_remote = args.repo or _cwd_remote()
    pr_args = args.pr

    # Explicit --pr always wins; --auto-detect with explicit PRs is contradictory.
    if pr_args and args.auto_detect:
        print("[fetch_pr] --pr given; ignoring --auto-detect.", file=sys.stderr)

    # No PRs passed (or --auto-detect alone): resolve from the current branch.
    if not pr_args:
        try:
            view = _gh.run_json(["pr", "view", "--json", "number,headRepository"])
        except _gh.GhError:
            print(
                "[fetch_pr] could not detect a PR for the current branch. Pass a PR "
                "number or URL with --pr, or run from a branch that has an open PR.",
                file=sys.stderr,
            )
            return 2
        number = view.get("number")
        if not number:
            print("[fetch_pr] `gh pr view` returned no PR for this branch; "
                  "pass --pr <number|url>.", file=sys.stderr)
            return 2
        detected_repo = (view.get("headRepository") or {}).get("nameWithOwner")
        if detected_repo:
            cwd_remote = detected_repo
        pr_args = [str(number)]

    refs = parse_pr_inputs(pr_args, cwd_remote)
    bundle = build_bundle(refs)
    print(_json.dumps(bundle, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
