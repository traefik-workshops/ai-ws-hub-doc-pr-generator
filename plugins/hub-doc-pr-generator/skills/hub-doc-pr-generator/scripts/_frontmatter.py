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

# `\r?\n` rather than a literal `\n` around each delimiter -- cutmode audit
# finding G, and PR #32 review finding 5: an earlier version of this fix
# normalized the WHOLE input text (`text.replace("\r\n", "\n")`) before
# matching, which tolerated a CRLF-saved fragment (a plausible
# Windows-editor save) but also silently rewrote every line ending in the
# returned `fm`/`body` to LF -- producing a noisy full-file diff on
# write-back (assign_target_version.assign() reconstructs the file from this
# same split) for a change that should have touched only the
# target_version line. Tolerating `\r?\n` in the regex itself, instead of
# preprocessing the text, means only the two delimiter lines are
# affected -- the captured `fm`/`body` groups keep whatever line endings the
# original file actually used.
_FRONT_MATTER_RE = re.compile(r"^---\r?\n(?P<fm>.*?)\r?\n---\r?\n?(?P<body>.*)$", re.DOTALL)

# What counts as an unassigned release-note fragment's target_version (bare or
# quoted -- collect_fragments.parse_fragment unquotes scalars when reading a
# fragment back, so anything that checks for this sentinel at write time or in
# raw file content must recognize the same forms). Shared by
# hub-doc-pr-generator's preview.py (check_unassigned_fragment) and
# release-notes-generator's assign_target_version.py -- previously each kept
# its own private copy of this same pattern, in sync only by a comment.
UNASSIGNED_TARGET_VERSION_RE = re.compile(r"^target_version:\s*['\"]?unassigned['\"]?\s*$", re.MULTILINE)

# The release-version placeholder used in EA callouts/headings when the real
# version isn't known yet (see the sibling hub-doc-pr-generator skill's
# style-guide.md "Early Access features" and release-note-heuristics.md
# "Which version"). Shared by hub-doc-pr-generator's preview.py
# (check_placeholder_version) and release-notes-generator's preview.py
# (check_vnext_placeholder) -- both need to agree on the one token that counts
# as an unresolved placeholder, since assign_target_version.py only ever
# rewrites a fragment's front-matter target_version, never its body prose, so
# a fragment's body can still say vNEXT after its front matter is assigned a
# real version.
VNEXT_RE = re.compile(r"\bvNEXT\b")


def unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    return v


def split_front_matter(text: str) -> tuple[str, str]:
    """Split `text` into (front_matter_block, body), where front_matter_block is
    the raw text between the `---` delimiters (not yet parsed into fields).
    Raises ValueError if there's no such block — callers decide whether that's
    fatal for their use case. Tolerates CRLF around the delimiters without
    altering any other line endings in the returned `fm`/`body` (see
    _FRONT_MATTER_RE's comment) -- per-line parsers downstream of this
    (collect_fragments.parse_fragment's `fm_text.splitlines()`) already
    handle a `\\r\\n`-terminated line correctly on their own, so no further
    normalization is needed here."""
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        raise ValueError("no '---' front matter block found")
    return m["fm"], m["body"]
