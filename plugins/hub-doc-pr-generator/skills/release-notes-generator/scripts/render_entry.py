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
_HEADING_IDENTITY_RE = re.compile(
    r"^## Gateway (?P<identity>.+?)(?:\s*<EarlyAccessBadge\s*/>)?\s*$", re.MULTILINE,
)
_EARLIER_RELEASES_RE = re.compile(r"^## Earlier releases", re.MULTILINE)


def _heading_identity(text: str) -> str | None:
    """The version (or hub-doc-team-curated combined version pair) a `##
    Gateway ...` heading represents -- e.g. `v3.20.6` or `v3.20.6 & v3.19.11`
    -- with any `<EarlyAccessBadge />` decoration stripped off (in any
    spacing), read from `text`'s first line. None if that line isn't a Gateway
    heading at all.

    This is the FULL remaining heading text, not just the leading version
    token: an earlier version of this function extracted only the leading
    token (e.g. `v3.20.6` out of `v3.20.6 & v3.19.11`), which made
    `_existing_section_span` match on a bare prefix -- unsafe. Confirmed live
    that splicing a plain single-version entry (`## Gateway v3.20.6`) against
    an existing COMBINED heading (`## Gateway v3.20.6 & v3.19.11`) then
    matched and replaced the whole combined section, silently destroying
    v3.19.11's content. Comparing the full identity instead means a combined
    heading is only ever replaced by a re-splice that represents that exact
    same combined pair, never by an unrelated single-version entry that
    merely shares a leading version."""
    m = _HEADING_IDENTITY_RE.match(text.strip())
    return m["identity"].strip() if m else None


def _existing_section_span(existing: str, identity: str) -> tuple[int, int] | None:
    """[start, end) of an existing `## Gateway <identity>` section (its
    heading line through everything up to the next `## Gateway v...` heading,
    the `## Earlier releases` archive boundary, or end of file — whichever
    comes first). None if no section with this exact identity exists yet.

    `identity` must match exactly (modulo the optional badge) -- confirmed
    live this needs to recognize a hub-doc-team-curated combined heading
    (`## Gateway v3.20.6 & v3.19.11`) as identical to itself when tag mode's
    edit-loop re-prompt path re-splices a regenerated combined entry against a
    file that already has that same heading from an earlier splice attempt
    (previously fell through to the default insert-above-first path and
    duplicated it -- the very bug this function exists to prevent), while
    still refusing to match a DIFFERENT identity that merely shares a leading
    version (see `_heading_identity`'s docstring)."""
    heading_re = re.compile(
        rf"^## Gateway {re.escape(identity)}(?:\s*<EarlyAccessBadge\s*/>)?\s*$", re.MULTILINE,
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

    identity = _heading_identity(entry)
    if identity:
        span = _existing_section_span(existing, identity)
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
