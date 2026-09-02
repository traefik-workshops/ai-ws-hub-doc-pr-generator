"""_shapes.py — the canonical set of release-note fragment shapes.

Single source of truth for what `shape` a fragment's front matter can
legitimately declare. Shared by classify.py (which proposes a shape for a
new fragment) and the sibling release-notes-generator skill's
assemble_section.py (which validates one before rendering).

Pulled out into its own module rather than left as two independent hardcoded
sets -- PR #32 review finding 6: assemble_section.py's original
`_VALID_SHAPES` was a separate literal copy of the shapes classify.py can
actually produce, with nothing keeping them in sync. If classify.py started
proposing a new shape without this set also being updated, B's typo-guard
(assemble_section.py raising on an "unrecognized" shape) would then reject a
perfectly legitimate one. A single definition makes that class of drift
structurally impossible instead of relying on both files being remembered
together.

Each shape name corresponds to a release-note-<name-without-"-subsection">
.mdx.tmpl template in this skill's templates/ directory (see
release-note-heuristics.md's shape table) -- the historical "ea"/"breaking"
template filenames predate the "-subsection" suffix on the shape identifiers
themselves.
"""
from __future__ import annotations

VALID_SHAPES = frozenset({
    "breaking-subsection",
    "ga-bullet",
    "ea-subsection",
    "ga-subsection",
    "plain-bullet",
})
