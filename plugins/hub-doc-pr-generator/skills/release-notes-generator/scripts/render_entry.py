"""render_entry.py — splice a new release-note entry into release-notes.mdx.

Insertion order is a hard, mechanical rule (see the sibling hub-doc-pr-generator
skill's references/release-note-heuristics.md, "Insertion order — newest on
top"), not a judgment call: the new entry always goes immediately above the
first existing `## Gateway v...` heading, never appended at the end and never
inside `## Earlier releases` (which sits below all versioned sections). This
enforces that mechanically instead of leaving it to the generation step to
get right by hand every time.

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


def splice(existing: str, entry: str) -> str:
    entry_block = entry.strip("\n") + "\n\n"
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
