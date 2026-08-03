"""fetch_release_range.py — commit range for a Hub release tag, diffed against
the previous tag on the same minor line.

Traefik Hub release notes are organized per patch tag, but nothing records
"what shipped since last time" on its own — that's a diff against whichever
tag preceded this one on the same X.Y line. This resolves that previous tag
automatically and pulls the commit list via GitHub's compare API, replacing
the manual copy-paste of a raw changelog this used to require.

Automatic resolution assumes patch tags are sequential on a line (vX.Y.(N-1)
exists for vX.Y.N). That breaks for the first patch after a branch cut, or
if a patch was skipped — those are genuinely unknowable from tag history
alone, so --prev-tag is an escape hatch, not a fallback to guess with.

Usage:
  python -m scripts.fetch_release_range --tag v3.19.13 --tag v3.20.8 \
      [--prev-tag v3.19.13:v3.19.11]
"""
from __future__ import annotations
import argparse
import json
import sys
from typing import Optional

from scripts import _gh, _semver

REPO = "traefik/traefik-hub"


def _all_tag_names() -> list[str]:
    raw = _gh.run_text(["api", f"repos/{REPO}/tags", "--paginate", "--jq", ".[].name"])
    return [line for line in raw.splitlines() if line.strip()]


def resolve_prev_tag(tag: str, *, override: Optional[str], all_tags: list[str]) -> str:
    if override:
        return override
    target = _semver.parse(tag)
    if target is None:
        raise ValueError(f"cannot parse semver from tag {tag!r}")
    candidates = [
        s for s in _semver.sorted_tags(all_tags)
        if _semver.same_line(s, target) and s.key() < target.key()
    ]
    if not candidates:
        raise ValueError(
            f"no earlier tag found on the v{target.major}.{target.minor} line for {tag!r} — "
            f"this may be the first patch on the line (nothing to diff against) or a gap in "
            f"tag history. Pass --prev-tag {tag}:<prev> to specify the base explicitly."
        )
    return candidates[-1].raw


def tag_commit_date(tag: str) -> str:
    sha = _gh.run_text(["api", f"repos/{REPO}/git/refs/tags/{tag}", "--jq", ".object.sha"]).strip()
    return _gh.run_text(["api", f"repos/{REPO}/commits/{sha}", "--jq", ".commit.committer.date"]).strip()


def compare_commits(base: str, head: str) -> list[dict]:
    data = _gh.run_json(["api", f"repos/{REPO}/compare/{base}...{head}"])
    return [
        {"sha": c["sha"], "subject": c["commit"]["message"].splitlines()[0]}
        for c in data.get("commits", [])
    ]


def fetch_range(tag: str, *, prev_override: Optional[str], all_tags: list[str]) -> dict:
    prev = resolve_prev_tag(tag, override=prev_override, all_tags=all_tags)
    return {
        "tag": tag,
        "prev_tag": prev,
        "date": tag_commit_date(tag),
        "commits": compare_commits(prev, tag),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag", action="append", required=True, dest="tags",
                         help="release tag to fetch, e.g. v3.19.13 (repeatable)")
    parser.add_argument("--prev-tag", action="append", default=[], dest="prev_tags",
                         help="override in TAG:PREV form, e.g. v3.19.13:v3.19.11 (repeatable)")
    args = parser.parse_args(argv)

    overrides = dict(pt.split(":", 1) for pt in args.prev_tags)
    all_tags = _all_tag_names()

    result = {
        "repo": REPO,
        "tags": [
            fetch_range(tag, prev_override=overrides.get(tag), all_tags=all_tags)
            for tag in args.tags
        ],
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
