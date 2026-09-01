"""check_implementation_signal.py — deterministic gate for the issue-only path:
is there actually something to document yet?

SKILL.md's "confirm there is actually something to document" step (added
after the Transparency Logs investigation, 2026-08-24: an issue whose bundle
had no implementation signal at all was drafted into a doc page anyway) used
to be pure prose telling the orchestrating LLM to check related_prs/siblings
and stop if nothing looked like a real implementation. Prose alone has no
test coverage -- a future SKILL.md edit could drop or reorder the check with
nothing to catch it. This script is the same heuristic, made mechanical and
tested, so SKILL.md can call it and act on a real verdict instead of relying
on the LLM to reliably re-derive the check every run.

This is deliberately advisory, not a hard gate: a real implementation can
exist with none of these signals present (e.g. an impl PR the bundle's graph
query missed), so a "no" verdict here is a strong "go double-check", not
proof of "run classify.py anyway" being safe. SKILL.md still instructs a
direct repo search as a last resort before stopping -- this script only
covers what's mechanically checkable from the bundle alone.

Usage:
  python -m scripts.check_implementation_signal --bundle /tmp/bundle.json
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from scripts import _discover

# Titles that read as "someone investigated/found a problem", not "someone is
# building the fix" -- a sibling issue matching one of these is evidence
# AGAINST there being an implementation yet, even though it's linked under
# the same parent epic as the issue being drafted for.
_INVESTIGATION_MARKERS = (
    "qa finding", "investigat", "bug report", "regression report",
    "working as intended", "wai", "reproduc",
)
# Titles that read as "this is the implementation work" -- a positive signal,
# used only when a sibling isn't already ruled out by _INVESTIGATION_MARKERS.
_IMPLEMENTATION_MARKERS = (
    "implement", "add support", "add ", "support for", "ship ",
)


def _pr_looks_landed(pr: dict) -> bool:
    """A merged PR is the strongest signal. An open, non-draft PR still
    counts -- SKILL.md explicitly says not to wait for merge if docs should
    be drafted in parallel -- but a closed-without-merging PR (abandoned or
    superseded) does not."""
    state = (pr.get("state") or "").upper()
    return state in ("MERGED", "OPEN")


def _sibling_reads_as_implementation(title: str) -> bool:
    title_l = title.lower()
    if any(m in title_l for m in _INVESTIGATION_MARKERS):
        return False
    return any(m in title_l for m in _IMPLEMENTATION_MARKERS)


def has_implementation_signal(bundle: dict) -> dict:
    """Returns {"has_signal": bool, "reasons": [str, ...]}.

    `has_signal` is trivially True for a PR-backed bundle (`prs` non-empty) --
    this check only has teeth on the issue-only path, where `prs == []`."""
    if bundle.get("prs"):
        return {"has_signal": True, "reasons": ["bundle is PR-backed"]}

    reasons: list[str] = []
    merged = bundle.get("merged", {})

    landed_prs = [pr for pr in merged.get("related_prs", []) if _pr_looks_landed(pr)]
    for pr in landed_prs:
        state = (pr.get("state") or "").upper()
        reasons.append(f"related PR #{pr.get('number')} is {state.lower()}")

    implementation_siblings = [
        sub for sub in merged.get("sub_issues", [])
        if _sibling_reads_as_implementation(sub.get("title", ""))
    ]
    for sub in implementation_siblings:
        reasons.append(f"sibling issue #{sub.get('number')} reads as implementation: "
                        f"{sub.get('title', '')!r}")

    issue = bundle.get("issue") or {}
    for sibling in issue.get("siblings", []):
        if _sibling_reads_as_implementation(sibling.get("title", "")):
            reasons.append(f"sibling issue #{sibling.get('number')} reads as implementation: "
                            f"{sibling.get('title', '')!r}")

    return {"has_signal": bool(reasons), "reasons": reasons}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, help="path to bundle.json")
    args = parser.parse_args(argv)
    bundle = json.loads(Path(args.bundle).read_text())
    print(json.dumps(has_implementation_signal(bundle), indent=2))
    return 0


if __name__ == "__main__":
    _discover.maybe_reexec()
    sys.exit(main(sys.argv[1:]))
