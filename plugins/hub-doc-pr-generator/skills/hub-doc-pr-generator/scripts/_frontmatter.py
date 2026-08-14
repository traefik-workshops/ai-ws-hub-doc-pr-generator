"""_frontmatter.py — shared front-matter parsing primitives.

Split out so a new front-matter consumer doesn't silently grow its own private
copy of `_unquote` (and its quoted-scalar handling, easy to forget) the way
extract_neighbor_structure.py and fetch_grounding.py each already did
independently before this module existed. Those two are left as-is here --
each has its own tests and slightly different surrounding parse logic (a
`tags` list vs. a `fields` list-of-dicts) that isn't worth touching just to
retrofit onto a shared module. This exists so the *next* consumer (starting
with release-notes-generator's collect_fragments.py) has one canonical place
to import from instead of adding a third or fourth private reimplementation.

Canonical location: hub-doc-pr-generator/scripts/ (like _gh.py/_git.py),
symlinked into release-notes-generator/scripts/ for cross-skill reuse — see
that skill's SKILL.md "Shared code" section for why symlinks over a shared
PYTHONPATH package.
"""
from __future__ import annotations
import re

_FRONT_MATTER_RE = re.compile(r"^---\n(?P<fm>.*?)\n---\n?(?P<body>.*)$", re.DOTALL)

# What counts as an unassigned release-note fragment's target_version (bare or
# quoted -- collect_fragments.parse_fragment unquotes scalars when reading a
# fragment back, so anything that checks for this sentinel at write time or in
# raw file content must recognize the same forms). Shared by
# hub-doc-pr-generator's preview.py (check_unassigned_fragment) and
# release-notes-generator's assign_target_version.py -- previously each kept
# its own private copy of this same pattern, in sync only by a comment.
UNASSIGNED_TARGET_VERSION_RE = re.compile(r"^target_version:\s*['\"]?unassigned['\"]?\s*$", re.MULTILINE)


def unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    return v


def split_front_matter(text: str) -> tuple[str, str]:
    """Split `text` into (front_matter_block, body), where front_matter_block is
    the raw text between the `---` delimiters (not yet parsed into fields).
    Raises ValueError if there's no such block — callers decide whether that's
    fatal for their use case."""
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        raise ValueError("no '---' front matter block found")
    return m["fm"], m["body"]
