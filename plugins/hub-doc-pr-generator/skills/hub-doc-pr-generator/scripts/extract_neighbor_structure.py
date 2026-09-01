"""extract_neighbor_structure.py — compact structural summaries of neighbor doc pages.

Replaces reading full neighbor pages with a JSON summary of each file's:
- Front matter fields: title, description, tags, id (if present)
- H2 headings with the first sentence of the following paragraph
- H3 headings (under each H2) with first sentence only

Usage (CLI):
    python -m scripts.extract_neighbor_structure path/to/page.md [more.md ...]

Prints a JSON array to stdout.

Importable:
    from scripts.extract_neighbor_structure import extract_structure
    summaries = extract_structure(["docs/ai-gateway/middlewares/token-rate-limit.md"])
"""
from __future__ import annotations

import json
import re
import sys
from typing import Optional

from scripts import _discover


# ---------------------------------------------------------------------------
# Front-matter parsing (minimal YAML: scalars + tags list)
# ---------------------------------------------------------------------------

def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    return v


def _parse_front_matter(text: str) -> dict:
    """Parse YAML front matter between --- delimiters.

    Handles simple scalars and a 'tags' list (same pattern as fetch_grounding.py).
    Returns an empty dict when no front matter is found.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    fm: dict = {}
    section: Optional[str] = None

    for line in lines[1:]:
        if line.strip() == "---":
            break
        # Top-level key (no leading whitespace)
        top = re.match(r"^(?P<k>[A-Za-z0-9_]+):\s?(?P<v>.*)$", line)
        if top:
            k, v = top["k"], top["v"].strip()
            if v == "":
                section = k
                if k == "tags":
                    fm[k] = []
            else:
                fm[k] = _unquote(v)
                section = None
            continue
        # List items under a top-level block
        if section == "tags":
            mm = re.match(r"^\s*-\s+(?P<val>.+)$", line)
            if mm:
                fm["tags"].append(_unquote(mm["val"].strip()))
        # All other nested blocks are skipped

    return fm


# ---------------------------------------------------------------------------
# First-sentence extraction
# ---------------------------------------------------------------------------

_CODE_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
_HTML_TAG_RE = re.compile(r"^\s*<[a-zA-Z/!]")
_IMPORT_RE = re.compile(r"^\s*import\s+")
_HEADING_RE = re.compile(r"^#{1,6}\s")

# A sentence ends at . ! ? only when followed by whitespace or end-of-string.
# The lookahead alone avoids splitting "v3.20" or "1.2.3" (period followed by a
# digit, not a space). Common abbreviations are skipped separately.
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)")
_ABBREVIATIONS = {"e.g.", "i.e.", "etc.", "vs.", "cf.", "fig.", "no.", "approx."}


def _first_sentence_end(text: str) -> int | None:
    """Index just past the first real sentence terminator, or None if none."""
    for m in _SENTENCE_END_RE.finditer(text):
        end = m.start() + 1
        words = text[:end].split()
        if words and words[-1].lower() in _ABBREVIATIONS:
            continue  # period belongs to an abbreviation, not a sentence end
        return end
    return None


def _first_sentence(lines: list[str], start: int) -> str:
    """Return the first meaningful sentence starting at or after *start*.

    Skips blank lines, code fences, HTML tags, and import statements.
    Truncates at the first sentence-ending punctuation (. ! ?) or at 200 chars.
    """
    text_parts: list[str] = []
    in_code_fence = False

    for i in range(start, len(lines)):
        line = lines[i]

        # Stop at the next heading
        if _HEADING_RE.match(line):
            break

        # Track code fences — skip their contents
        if _CODE_FENCE_RE.match(line):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue

        stripped = line.strip()
        if not stripped:
            if text_parts:
                # A blank line after we've collected text ends the paragraph
                break
            continue

        # Skip import statements and HTML tags
        if _IMPORT_RE.match(stripped) or _HTML_TAG_RE.match(stripped):
            continue

        text_parts.append(stripped)

    if not text_parts:
        return ""

    combined = " ".join(text_parts)

    # Find the first real sentence end (ignores version numbers and abbreviations).
    end = _first_sentence_end(combined)
    if end is not None:
        return combined[:end].strip()

    # No sentence terminator found — truncate at 200 chars
    if len(combined) > 200:
        return combined[:200].rstrip() + "…"
    return combined


# ---------------------------------------------------------------------------
# Heading extraction
# ---------------------------------------------------------------------------

_H2_RE = re.compile(r"^##\s+(.+)$")
_H3_RE = re.compile(r"^###\s+(.+)$")


def _extract_sections(lines: list[str]) -> list[dict]:
    """Return a list of section dicts with keys: heading, level, first_sentence."""
    sections: list[dict] = []

    for i, line in enumerate(lines):
        h2 = _H2_RE.match(line)
        if h2:
            sections.append({
                "heading": h2.group(1).strip(),
                "level": 2,
                "first_sentence": _first_sentence(lines, i + 1),
            })
            continue

        h3 = _H3_RE.match(line)
        if h3:
            sections.append({
                "heading": h3.group(1).strip(),
                "level": 3,
                "first_sentence": _first_sentence(lines, i + 1),
            })

    return sections


# ---------------------------------------------------------------------------
# Front-matter boundary detection
# ---------------------------------------------------------------------------

def _body_start(lines: list[str]) -> int:
    """Return the index of the first line after the closing --- delimiter."""
    if not lines or lines[0].strip() != "---":
        return 0
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return i + 1
    return 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_structure(paths: list[str]) -> list[dict]:
    """Return compact structural summaries for each path.

    Skips files under 10 lines or that cannot be read (OSError).
    """
    results: list[dict] = []

    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue

        lines = text.splitlines()
        if len(lines) < 10:
            continue

        fm = _parse_front_matter(text)
        body_start = _body_start(lines)
        sections = _extract_sections(lines[body_start:])

        entry: dict = {"path": path}
        for field in ("title", "description", "id"):
            if field in fm:
                entry[field] = fm[field]
        if "tags" in fm:
            entry["tags"] = fm["tags"]
        entry["sections"] = sections

        results.append(entry)

    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract compact structural summaries from Markdown/MDX neighbor pages.",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        metavar="FILE",
        help="One or more .md / .mdx file paths to summarise.",
    )
    args = parser.parse_args(argv)

    summaries = extract_structure(args.paths)
    json.dump(summaries, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":  # pragma: no cover
    _discover.maybe_reexec()
    main()
