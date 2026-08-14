"""assign_target_version.py — rewrite one fragment's target_version in place.

Used by `cut` mode step 2 (see SKILL.md) after the writer confirms which
`unassigned` fragments belong to the release being cut. Pulled out of inline
SKILL.md prose (a `python3 -c` one-liner previously did a literal
`.replace('target_version: unassigned', ...)`) because that literal-string
match silently no-ops on any front-matter form it doesn't expect byte-for-byte
-- verified live: a fragment written as `target_version: "unassigned"` (quoted,
which collect_fragments.parse_fragment already tolerates when reading a
fragment back) left the string completely unchanged, no error, permanently
stranding that fragment as unassigned with zero visible failure. A real,
tested function can raise loudly instead of silently doing nothing.

Usage:
  python -m scripts.assign_target_version --fragment <path> --version <version>
Exits non-zero (with a clear message) if the fragment has no unassigned
target_version line to replace -- never silently no-ops.
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

# Same quote-tolerant match as the sibling hub-doc-pr-generator skill's
# preview.py check_unassigned_fragment (_UNASSIGNED_TARGET_VERSION_RE) -- keep
# these two in sync if either changes what counts as "unassigned".
_UNASSIGNED_LINE_RE = re.compile(r"^target_version:\s*['\"]?unassigned['\"]?\s*$", re.MULTILINE)


def assign(content: str, version: str) -> str:
    """Replace the fragment's `target_version: unassigned` line (bare or
    quoted) with `target_version: <version>` (always written unquoted, matching
    templates/release-note-fragment.mdx.tmpl's convention). Raises ValueError
    if no such line is found -- never returns `content` unchanged."""
    new_content, count = _UNASSIGNED_LINE_RE.subn(f"target_version: {version}", content, count=1)
    if count == 0:
        raise ValueError(
            "no 'target_version: unassigned' line found -- fragment may already be "
            "assigned, or its front matter doesn't match the expected shape"
        )
    return new_content


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fragment", required=True, help="path to the fragment file to rewrite")
    parser.add_argument("--version", required=True, help="the confirmed target_version to assign")
    args = parser.parse_args(argv)
    path = Path(args.fragment)
    try:
        path.write_text(assign(path.read_text(encoding="utf-8"), args.version), encoding="utf-8")
    except ValueError as e:
        print(f"{args.fragment}: {e}", file=sys.stderr)
        return 1
    print(f"{args.fragment}: target_version -> {args.version}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
