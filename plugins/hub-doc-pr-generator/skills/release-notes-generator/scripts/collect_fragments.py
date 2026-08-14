"""collect_fragments.py — find and parse release-note fragments for the `cut`
command.

Fragments live at <hub-doc-root>/docs/api-gateway/release-notes.d/*.mdx, written
by the sibling hub-doc-pr-generator skill's SKILL.md step 7 (one small file per
doc PR, never a shared-file overwrite — see that skill's
references/release-note-heuristics.md, "Where the entry goes"). This script is
the read side: glob the directory, parse each fragment's front matter, and
split into `assigned` (has a real `target_version`) vs. `unassigned` (writer
didn't know the release yet — see that same reference's "Which version").

No YAML dependency — this plugin deliberately stays stdlib-only (see
compat_matrix.py's note on the same choice). The front-matter schema is small
and fixed (scalars, one inline list, one nested mapping), so a hand-rolled
parser is simpler than pulling in a real YAML library for it. The delimiter
split and quoted-scalar handling come from the shared `_frontmatter` module
(see that module's docstring) rather than a third private reimplementation —
only the schema-specific field walk (the `source_prs` list and the `compat`
nested mapping, neither of which the two existing consumers need) lives here.

Usage:
  python -m scripts.collect_fragments --release-notes-dir <hub-doc-root>/docs/api-gateway/release-notes.d
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

from scripts._frontmatter import split_front_matter, unquote

_SCALAR_RE = re.compile(r"^(?P<k>[A-Za-z0-9_]+):\s*(?P<v>.*)$")
_NESTED_KV_RE = re.compile(r"^\s+(?P<k>[^:]+):\s*(?P<v>.+)$")
_PR_NUMBER_RE = re.compile(r"^(\d+)-")


def parse_fragment(text: str) -> dict:
    """Parse one fragment's front matter + body. Raises ValueError if the
    front-matter block is missing or malformed — a fragment this script can't
    parse should stop `cut` loudly, not be silently skipped."""
    try:
        fm_text, body = split_front_matter(text)
    except ValueError:
        raise ValueError("fragment has no '---' front matter block")

    fm: dict = {"compat": {}, "source_prs": []}
    section: str | None = None
    for line in fm_text.splitlines():
        if not line.strip():
            continue
        if line[0] in " \t":
            nested = _NESTED_KV_RE.match(line)
            if nested and section == "compat":
                fm["compat"][unquote(nested["k"].strip())] = unquote(nested["v"].strip())
            continue
        section = None
        scalar = _SCALAR_RE.match(line)
        if not scalar:
            continue
        key, val = scalar["k"], scalar["v"].strip()
        if key == "source_prs":
            fm["source_prs"] = [int(n) for n in re.findall(r"\d+", val)]
        elif val == "":
            section = key  # nested block header (currently only "compat")
        else:
            fm[key] = unquote(val)

    return {**fm, "body": body.strip("\n") + "\n"}


def _pr_number(filename: str) -> int:
    m = _PR_NUMBER_RE.match(filename)
    return int(m.group(1)) if m else 0


def collect(fragments_dir: Path) -> dict:
    fragments = []
    if fragments_dir.is_dir():
        for path in sorted(fragments_dir.glob("*.mdx")):
            parsed = parse_fragment(path.read_text(encoding="utf-8"))
            parsed["filename"] = path.name
            parsed["path"] = str(path)
            parsed["pr_number"] = _pr_number(path.name)
            fragments.append(parsed)

    def _is_unassigned(f: dict) -> bool:
        return not f.get("target_version") or f["target_version"] == "unassigned"

    return {
        "fragments": fragments,
        "assigned": [f for f in fragments if not _is_unassigned(f)],
        "unassigned": [f for f in fragments if _is_unassigned(f)],
    }


def for_version(fragments: list[dict], target_version: str) -> list[dict]:
    """Fragments assigned to exactly this release, newest-first (PR-number
    descending) — the same deterministic proxy for "newest" the design settled
    on instead of every branch guessing independently (see
    release-note-heuristics.md, "Insertion order")."""
    matching = [f for f in fragments if f.get("target_version") == target_version]
    return sorted(matching, key=lambda f: f["pr_number"], reverse=True)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release-notes-dir", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(collect(Path(args.release_notes_dir)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
