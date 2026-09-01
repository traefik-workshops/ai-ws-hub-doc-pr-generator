"""dedup_versions.py — cross-tag dedup for a combined release-note entry.

When two Hub lines (e.g. v3.20 and v3.19) patch-release close together, the
newer line typically merges the older line's fixes first (see the
"Merge vX.Y into vX.Z" commits classify_commits.py excludes) — so a shared
fix has the *identical commit SHA* on both tags' compare ranges. That makes
dedup a plain set intersection, no fuzzy title matching needed.

Real precedent for the combined shape this enables: traefik/hub-doc's
`## Gateway v3.20.6 & v3.19.11` entry (2026-07-01) — shared bullets
unprefixed, version-specific bullets prefixed "vX.Y.Z only:" / "vX.Y.Z:".

The sibling hub-doc-pr-generator skill's release-note-heuristics.md notes
that *it* never constructs a combined heading itself, treating that as a
hub-doc-team curation step. This skill exists specifically to take on that
job — but the decision still isn't auto-applied silently: `combine` is a
recommendation with its `reason` attached, and SKILL.md step 4 asks the
engineer to confirm it via AskUserQuestion before generation, exactly because
it determines the whole document's structure (one heading vs. two).

Usage:
  python -m scripts.dedup_versions --classified /tmp/classified.json [--max-date-gap-days 3]
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from scripts import _discover, _semver


def _included(tag_entry: dict) -> dict[str, str]:
    return {c["sha"]: c["subject"] for c in tag_entry["commits"] if c["verdict"] == "include"}


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


def dedup(classified: dict, *, max_date_gap_days: int) -> dict:
    tags = classified["tags"]
    per_tag = {t["tag"]: _included(t) for t in tags}

    shared_shas: set = set.intersection(*(set(d) for d in per_tag.values())) if len(per_tag) > 1 else set()
    shared = [
        {"sha": sha, "subject": next(d[sha] for d in per_tag.values() if sha in d)}
        for sha in shared_shas
    ]

    only: dict[str, list[dict]] = {}
    for tag, commits in per_tag.items():
        only[tag] = [
            {"sha": sha, "subject": subj} for sha, subj in commits.items() if sha not in shared_shas
        ]

    combine = False
    if len(tags) == 1:
        reason = "single tag — nothing to combine"
    elif not shared_shas:
        reason = "no shared commits between the given tags — these are likely unrelated releases; keep separate entries"
    else:
        dates = [_parse_date(t["date"]) for t in tags]
        gap = max(dates) - min(dates)
        if gap <= timedelta(days=max_date_gap_days):
            combine = True
            reason = f"{len(shared_shas)} shared commit(s), tagged within {gap.days}d of each other"
        else:
            reason = (
                f"{len(shared_shas)} shared commit(s) but tagged {gap.days}d apart "
                f"(over the {max_date_gap_days}d threshold) — confirm before combining into one entry"
            )

    ordered = sorted(
        ((t["tag"], _semver.parse(t["tag"])) for t in tags),
        key=lambda pair: pair[1].key(),
        reverse=True,
    )
    heading = " & ".join(tag for tag, _ in ordered) if combine else None

    return {
        "combine": combine,
        "reason": reason,
        "heading": heading,
        "ordered_tags": [tag for tag, _ in ordered],
        "dates": {t["tag"]: t["date"] for t in tags},
        "shared": shared,
        "only": only,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--classified", required=True, help="path to classify_commits.py output")
    parser.add_argument("--max-date-gap-days", type=int, default=3,
                         help="tagged-date gap under which combining is auto-recommended (default 3)")
    args = parser.parse_args(argv)
    classified = json.loads(Path(args.classified).read_text(encoding="utf-8"))
    print(json.dumps(dedup(classified, max_date_gap_days=args.max_date_gap_days), indent=2))
    return 0


if __name__ == "__main__":
    _discover.maybe_reexec()
    sys.exit(main(sys.argv[1:]))
