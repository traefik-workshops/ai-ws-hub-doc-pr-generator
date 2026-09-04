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

from scripts import _discover
from scripts._shapes import GA_BULLET, VALID_SHAPES

_EA_VERSION_RE = re.compile(r"-ea(\.|$)", re.IGNORECASE)

# ga-bullet fragments render as a single bullet line each, grouped under
# "#### Graduated to GA" below (see hub-doc-pr-generator's
# templates/release-note-ga-bullet.mdx.tmpl); every other shape -- including
# plain-bullet -- renders as its own body block, verbatim, under "### What's
# New". plain-bullet's body also happens to be a single bullet line (see
# templates/release-note-plain-bullet.mdx.tmpl), but it's deliberately NOT
# grouped under "Graduated to GA" -- that heading is reserved for actual GA
# graduations, and a plain-bullet entry (a small enhancement the
# engineer/reviewer explicitly declined EA/GA framing for) isn't one.
#
# Imported from _shapes.py, not retyped as a literal (PR #32 review-round-5
# finding): this constant WAS a hardcoded "ga-bullet" string even after
# _shapes.py was introduced as the single source of truth specifically to
# rule out this exact drift -- if GA_BULLET's value ever changed there, this
# copy would silently stop matching real fragments' shape field.
_BULLET_SHAPE = GA_BULLET

# Matches markdown link targets, e.g. `[text](../foo/bar.md#anchor)`. Only the
# target (group 1) is used -- link text can contain nested brackets/parens we
# don't need to parse correctly here.
_MD_LINK_RE = re.compile(r"\]\(([^)]+)\)")


def _is_checkable_relative_link(target: str) -> bool:
    """Skip anything that isn't a plain relative filesystem path: absolute
    URLs (http/https/mailto), site-absolute paths (leading '/', which
    Docusaurus resolves against the doc root, not the fragment's directory),
    and pure in-page anchors (`#foo`, no path component)."""
    target = target.strip()
    if not target or target.startswith("#"):
        return False
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):  # any URI scheme
        return False
    if target.startswith("/"):
        return False
    return True


def check_fragment_links(fragments: list[dict], docs_dir: Path) -> list[str]:
    """Defense-in-depth check for the exact class of bug behind
    traefik/hub-doc#988's first real CI failure: a fragment's relative
    markdown links are deliberately written for where the fragment's content
    will live *after* `cut` splices it into release-notes.mdx (one directory
    up from release-notes.d/, i.e. `docs_dir` -- the same directory
    release-notes.mdx itself lives in), not for the fragment's own location.
    That mismatch isn't visible from the fragment file alone; it only shows up
    once something tries to resolve the link from the wrong base directory.

    This resolves each fragment body's relative links against `docs_dir` (the
    post-assembly location) and flags any that don't point to an existing
    file, the same non-blocking "surface it, don't fail the run" pattern
    check_table_completeness/check_vnext_placeholder already use in
    preview.py. It does NOT catch the underscore-filename build-exclusion bug
    itself (that's fixed structurally by the filename convention, see
    hub-doc-pr-generator's release-note-heuristics.md) -- this is a second,
    independent safety net for a fragment whose link target is simply wrong
    or was written assuming the wrong base directory."""
    findings: list[str] = []
    for fragment in fragments:
        body = fragment.get("body", "")
        filename = fragment.get("filename", "<unknown fragment>")
        for match in _MD_LINK_RE.finditer(body):
            target = match.group(1).split(" ", 1)[0]  # drop an optional "title" suffix
            if not _is_checkable_relative_link(target):
                continue
            path_part = target.split("#", 1)[0]
            if not path_part:
                continue
            resolved = (docs_dir / path_part).resolve()
            if not resolved.is_file():
                findings.append(
                    f"{filename}: relative link '{target}' does not resolve to an existing "
                    f"file at its post-assembly location ({docs_dir}) -- double-check the "
                    "path before this fragment is cut into release-notes.mdx"
                )
    return findings


def _escape_table_cell(value: object) -> str:
    """Escape `|` (the markdown table cell delimiter) so a value containing one
    -- component names and versions both come from free-text fragment front
    matter, not a fixed enum -- can't split a row into extra columns. Confirmed
    live: an unescaped 'v3.7.10 (rc | preview)' value produced a 3-column row
    instead of 2."""
    return str(value).replace("|", "\\|")


def render_compat_table(rows: list[dict]) -> str:
    lines = ["<Collapse title=\"Compatibility matrix\">", "", "| Component | Version |", "| --- | --- |"]
    for row in rows:
        version = row["version"] if row["version"] is not None else "TBD"
        lines.append(f"| {_escape_table_cell(row['component'])} | {_escape_table_cell(version)} |")
    lines.append("")
    lines.append("</Collapse>")
    return "\n".join(lines)


def assemble(*, version: str, date: str, fragments: list[dict], compat_rows: list[dict]) -> str:
    """`fragments` must already be filtered to this version and ordered
    newest-first (see collect_fragments.for_version) -- this function does not
    re-sort or re-filter; it only groups by shape and renders."""
    for f in fragments:
        shape = f.get("shape")
        if shape not in VALID_SHAPES:
            # Loud failure, not a silent fall-through to the subsections
            # bucket -- see _shapes.py's docstring (cutmode audit finding B).
            # A typo'd or case-variant shape needs a human to fix the
            # fragment's front matter, not to be quietly misrendered.
            raise ValueError(
                f"{f.get('filename', '<unknown fragment>')}: unrecognized shape {shape!r} -- "
                f"expected one of {sorted(VALID_SHAPES)}"
            )
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
    parser.add_argument(
        "--docs-dir",
        help="the directory release-notes.mdx lives in (fragments' post-assembly location), "
             "e.g. <hub-doc-root>/docs/api-gateway -- if given, fragment relative links are "
             "checked against it and any unresolvable ones are surfaced as link_warnings "
             "(non-blocking; omit to skip the check)",
    )
    args = parser.parse_args(argv)
    fragments = json.loads(Path(args.fragments).read_text(encoding="utf-8"))
    compat_rows = json.loads(Path(args.compat_rows).read_text(encoding="utf-8"))
    try:
        section = assemble(version=args.version, date=args.date, fragments=fragments, compat_rows=compat_rows)
    except ValueError as e:
        # An unrecognized shape needs a human to fix the fragment's front
        # matter -- clean stderr message and non-zero exit, same convention
        # collect_fragments.py's and assign_target_version.py's main()
        # already use, not a raw traceback.
        print(f"error assembling section: {e}", file=sys.stderr)
        return 1
    link_warnings = check_fragment_links(fragments, Path(args.docs_dir)) if args.docs_dir else []
    print(json.dumps({"section": section, "link_warnings": link_warnings}, indent=2))
    return 0


if __name__ == "__main__":
    _discover.maybe_reexec()
    sys.exit(main(sys.argv[1:]))
