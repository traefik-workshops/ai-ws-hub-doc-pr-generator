"""assemble_section.py — render one `## Gateway <version>` release-notes.mdx
section from a confirmed release's fragments.

This is the piece that replaces per-PR full-file regeneration: fragments were
written and reviewed independently across possibly many concurrent doc PRs
(see the sibling hub-doc-pr-generator skill's references/release-note-heuristics.md,
"Where the entry goes"); this script is what finally decides their relative
order and renders the one real section, once, centrally — the ordering rule
itself (see "Insertion order — newest on top" in that same file) moved here
verbatim: `#### Graduated to GA` always first, feature subsections newest-first
next, compatibility matrix always last.

Usage:
  python -m scripts.assemble_section --version v3.21.0-ea.1 --date 2026-08-10 \
      --fragments /tmp/fragments_for_version.json --compat-rows /tmp/compat_rows.json
Prints {"section": "<## Gateway v3.21.0-ea.1 ...full section text...>"} —
feed straight into the sibling release-notes-generator skill's render_entry.py
(same splice-at-top mechanics as the patch flow, reused unchanged: the new
entry always goes immediately above the first existing `## Gateway v...`
heading).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

_EA_VERSION_RE = re.compile(r"-ea(\.|$)", re.IGNORECASE)

# ga-bullet fragments render as a single bullet line each (see
# hub-doc-pr-generator's templates/release-note-ga-bullet.mdx.tmpl); every
# other shape renders as a full `#### <Feature>` subsection body, verbatim.
_BULLET_SHAPE = "ga-bullet"


def render_compat_table(rows: list[dict]) -> str:
    lines = ["<Collapse title=\"Compatibility matrix\">", "", "| Component | Version |", "| --- | --- |"]
    for row in rows:
        version = row["version"] if row["version"] is not None else "TBD"
        lines.append(f"| {row['component']} | {version} |")
    lines.append("")
    lines.append("</Collapse>")
    return "\n".join(lines)


def assemble(*, version: str, date: str, fragments: list[dict], compat_rows: list[dict]) -> str:
    """`fragments` must already be filtered to this version and ordered
    newest-first (see collect_fragments.for_version) -- this function does not
    re-sort or re-filter; it only groups by shape and renders."""
    badge = " <EarlyAccessBadge />" if _EA_VERSION_RE.search(version) else ""
    heading = f"## Gateway {version}{badge}"
    date_line = f"**{date}**"

    ga_bullets = [f["body"].strip() for f in fragments if f.get("shape") == _BULLET_SHAPE]
    subsections = [f["body"].strip() for f in fragments if f.get("shape") != _BULLET_SHAPE]

    parts = [heading, "", date_line, "", "### What's New"]
    if ga_bullets:
        parts += ["", "#### Graduated to GA", "", *ga_bullets]
    for body in subsections:
        parts += ["", body]
    parts += ["", render_compat_table(compat_rows)]
    return "\n".join(parts).rstrip() + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--fragments", required=True, help="path to a JSON list of fragments for this version, newest-first")
    parser.add_argument("--compat-rows", required=True, help="path to a JSON list of {component, version, note} rows")
    args = parser.parse_args(argv)
    fragments = json.loads(Path(args.fragments).read_text(encoding="utf-8"))
    compat_rows = json.loads(Path(args.compat_rows).read_text(encoding="utf-8"))
    section = assemble(version=args.version, date=args.date, fragments=fragments, compat_rows=compat_rows)
    print(json.dumps({"section": section}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
