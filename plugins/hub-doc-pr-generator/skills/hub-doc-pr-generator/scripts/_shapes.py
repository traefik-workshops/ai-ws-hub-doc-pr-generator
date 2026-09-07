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

Named constants, not just the VALID_SHAPES set (PR #32 review finding 3):
extracting the set alone still left classify.py free to keep writing its own
`shape = "ea-subsection"` string literals rather than importing anything from
here, so the "structurally impossible" drift this module's docstring
originally promised was only actually enforced by a test that regex-scrapes
classify.py's source text for `shape = "..."` -- a refactor of how classify.py
assigns `shape` (an f-string, a dict lookup, different spacing) could make
that regex match nothing while classify.py silently keeps proposing shapes
never checked against VALID_SHAPES. Importing these constants instead of
retyping the strings means classify.py can't reference a shape that doesn't
exist here -- an actual `ImportError`/`AttributeError` at import time, not a
test that has to keep pace with classify.py's implementation details.
"""
from __future__ import annotations

# One literal per shape, written exactly once (PR #32 review round 4,
# finding 8): the constants below and VALID_SHAPES both derive from this
# single tuple instead of each hand-listing all five names -- the earlier
# version had VALID_SHAPES as its own frozenset literal repeating every
# constant a second time, in the very module whose docstring above says its
# purpose is eliminating exactly this kind of two-places-to-update drift.
# Adding a sixth shape now only means adding one entry here.
_SHAPE_NAMES = (
    "breaking-subsection",
    "ga-bullet",
    "ea-subsection",
    "ga-subsection",
    "plain-bullet",
)
BREAKING_SUBSECTION, GA_BULLET, EA_SUBSECTION, GA_SUBSECTION, PLAIN_BULLET = _SHAPE_NAMES
VALID_SHAPES = frozenset(_SHAPE_NAMES)
