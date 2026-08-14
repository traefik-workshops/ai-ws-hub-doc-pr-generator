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

    if not fm.get("target_version"):
        # A blank `target_version:` line hits the "elif val == '': section = key"
        # branch above (the same one that lets `compat:` work) and never becomes
        # a dict key at all -- collect()'s old falsy-value check then silently
        # treated that identically to the deliberate "unassigned" sentinel,
        # while the shared UNASSIGNED_TARGET_VERSION_RE regex (used by
        # preview.py and assign_target_version.assign()) only recognizes the
        # literal token, not a blank. That mismatch meant a blank fragment
        # wasn't flagged at PR-preview time but was later refused by assign()
        # -- a confusing dead end. This template always writes either
        # `unassigned` or a real version; blank/missing is malformed input,
        # not a legitimate third state, so raise here rather than silently
        # letting the two "what counts as unassigned" definitions disagree.
        raise ValueError(
            "fragment's front matter has no target_version value (missing or blank) -- "
            "must be either 'unassigned' or a real version string"
        )

    return {**fm, "body": body.strip("\n") + "\n"}


def _pr_number(filename: str) -> int:
    """Raises ValueError on a filename that doesn't start with a PR number,
    consistent with parse_fragment's and assign_target_version.assign's loud-
    failure behavior elsewhere in this pipeline -- silently defaulting to 0
    would let a misnamed fragment sort as if it were the oldest possible PR
    instead of surfacing that its ordering can't actually be trusted."""
    m = _PR_NUMBER_RE.match(filename)
    if not m:
        raise ValueError(
            f"{filename}: fragment filename doesn't start with a PR number "
            "(expected '<pr-number>-<slug>.mdx') -- can't determine its position "
            "in newest-first ordering"
        )
    return int(m.group(1))


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
        # parse_fragment now guarantees target_version is always present and
        # non-blank (raises otherwise), so this only needs to check the literal
        # sentinel -- the same definition _frontmatter.UNASSIGNED_TARGET_VERSION_RE
        # (used by preview.py and assign_target_version.assign()) already uses.
        # Previously this also treated any falsy value as unassigned, which
        # disagreed with that regex for a blank value and produced a fragment
        # that preview.py wouldn't flag but assign() would then refuse to fix.
        return f["target_version"] == "unassigned"

    return {
        "fragments": fragments,
        "assigned": [f for f in fragments if not _is_unassigned(f)],
        "unassigned": [f for f in fragments if _is_unassigned(f)],
    }


def for_version(fragments: list[dict], target_version: str) -> list[dict]:
    """Fragments assigned to exactly this release, newest-first (PR-number
    descending) — the same deterministic proxy for "newest" the design settled
    on instead of every branch guessing independently (see
    release-note-heuristics.md, "Insertion order").

    Matches case/whitespace-insensitively -- the same class of bug already
    fixed twice in compat_matrix.merge_fragment_deltas for component names,
    left open here for version strings. Confirmed live: a fragment stamped
    `v3.21.0-EA.1` (human-typed casing, from SKILL.md step 6c's free-text
    AskUserQuestion answer or `cut`'s own CLI argument) silently doesn't match
    cutting `v3.21.0-ea.1` -- not flagged as unassigned, not included in the
    assembled section, just silently absent with no error."""
    key = target_version.strip().lower()
    matching = [f for f in fragments if (f.get("target_version") or "").strip().lower() == key]
    return sorted(matching, key=lambda f: f["pr_number"], reverse=True)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release-notes-dir", required=True)
    args = parser.parse_args(argv)
    try:
        result = collect(Path(args.release_notes_dir))
    except ValueError as e:
        # One malformed fragment (bad front matter from parse_fragment, or a
        # misnamed file from _pr_number) shouldn't take down the whole `cut`
        # run with a raw traceback -- same clean-error convention
        # assign_target_version.py's main() already uses.
        print(f"error collecting fragments: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
