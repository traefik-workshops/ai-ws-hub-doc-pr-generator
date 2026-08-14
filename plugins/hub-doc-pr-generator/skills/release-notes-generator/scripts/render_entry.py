"""render_entry.py — splice a new release-note entry into release-notes.mdx.

Insertion order is a hard, mechanical rule (see the sibling hub-doc-pr-generator
skill's references/release-note-heuristics.md, "Insertion order — newest on
top"), not a judgment call: a brand-new entry always goes immediately above the
first existing `## Gateway v...` heading, never appended at the end and never
inside `## Earlier releases` (which sits below all versioned sections). This
enforces that mechanically instead of leaving it to the generation step to
get right by hand every time.

Re-running `cut` against a version that's still open (a straggler fragment
lands after an earlier cut, before the release actually ships) is an expected
workflow, not an error case — so if `entry`'s own heading names a version that
already has a section in `existing`, that section is REPLACED in place rather
than duplicated above it. Confirmed live that splicing the same version twice
without this produced two `## Gateway v<version>` headings for one release.

Usage:
  python -m scripts.render_entry --release-notes /path/to/release-notes.mdx \
      --entry /tmp/new-entry.mdx
Prints {"content": "<full new file>"} — feed straight into preview.py's
--content-file (write the "content" field to a file first).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

_HEADING_RE = re.compile(r"^## Gateway v", re.MULTILINE)
_ENTRY_VERSION_RE = re.compile(r"^## Gateway (?P<version>v\S+)")
_EARLIER_RELEASES_RE = re.compile(r"^## Earlier releases", re.MULTILINE)


def _entry_version(entry: str) -> str | None:
    m = _ENTRY_VERSION_RE.match(entry.strip())
    return m["version"] if m else None


def _existing_section_span(existing: str, version: str) -> tuple[int, int] | None:
    """[start, end) of an existing `## Gateway <version>` section (its heading
    line through everything up to the next `## Gateway v...` heading, the
    `## Earlier releases` archive boundary, or end of file — whichever comes
    first). None if no section for this exact version exists yet. Doesn't
    attempt to match a hub-doc-team-curated combined heading (e.g. `## Gateway
    v3.19.4 & v3.18.8`) — this pipeline never generates those itself (see
    "Structure of the target file" in the sibling skill's
    release-note-heuristics.md), so falling back to the default insert-above-
    first-heading behavior for that case is correct, not a gap."""
    heading_re = re.compile(
        rf"^## Gateway {re.escape(version)}(?: <EarlyAccessBadge />)?\s*$", re.MULTILINE,
    )
    m = heading_re.search(existing)
    if not m:
        return None
    stops = [x.start() for x in (
        _HEADING_RE.search(existing, m.end()),
        _EARLIER_RELEASES_RE.search(existing, m.end()),
    ) if x]
    return m.start(), (min(stops) if stops else len(existing))


def splice(existing: str, entry: str) -> str:
    entry_block = entry.strip("\n") + "\n\n"

    version = _entry_version(entry)
    if version:
        span = _existing_section_span(existing, version)
        if span:
            start, end = span
            return existing[:start] + entry_block + existing[end:]

    m = _HEADING_RE.search(existing)
    if not m:
        raise ValueError(
            "no existing '## Gateway v...' heading found in release-notes.mdx — "
            "refusing to guess an insertion point; check the file wasn't fetched empty/truncated"
        )
    return existing[:m.start()] + entry_block + existing[m.start():]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release-notes", required=True, help="path to the current release-notes.mdx")
    parser.add_argument("--entry", required=True, help="path to the new entry's mdx content")
    args = parser.parse_args(argv)
    existing = Path(args.release_notes).read_text(encoding="utf-8")
    entry = Path(args.entry).read_text(encoding="utf-8")
    print(json.dumps({"content": splice(existing, entry)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
