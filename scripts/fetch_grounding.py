"""fetch_grounding.py — load INDEX.md + DOC_INDEX.json from traefik/reference
and match concepts by Go source paths.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from scripts import _gh

REFERENCE_REPO = "traefik/reference"
INDEX_PATH = "INDEX.md"
DOC_INDEX_PATH = "DOC_INDEX.json"

_HEADER_RE = re.compile(r"^###\s+(?P<id>\S+)\s*$")
_FIELD_RE = re.compile(r"^-\s+(?P<key>\w+):\s*(?P<val>.*)$")
_BULLET_RE = re.compile(r"^\s+-\s+(?P<val>.+)$")


def parse_index(text: str) -> list[dict]:
    entries: list[dict] = []
    current: dict | None = None
    in_extracted = False
    for line in text.splitlines():
        m = _HEADER_RE.match(line)
        if m:
            if current:
                entries.append(current)
            current = {"id": m["id"], "extracted_from": []}
            in_extracted = False
            continue
        if current is None:
            continue
        m = _FIELD_RE.match(line)
        if m:
            key, val = m["key"], m["val"].strip()
            if key == "extracted_from":
                in_extracted = True
            else:
                current[key] = val
                in_extracted = False
            continue
        if in_extracted:
            m = _BULLET_RE.match(line)
            if m:
                # Strip line anchors like '#L85'
                p = m["val"].split("#", 1)[0].strip()
                current["extracted_from"].append(p)
    if current:
        entries.append(current)
    return entries


def concepts_for_paths(entries: list[dict], touched_paths: list[str]) -> list[dict]:
    touched = set(touched_paths)
    return [e for e in entries if any(p in touched for p in e.get("extracted_from", []))]


def _llms_txt_url_for(sources: set[str]) -> str:
    if "hub" in sources:
        return "https://doc.traefik.io/traefik-hub/llms.txt"
    if "oss" in sources:
        return "https://doc.traefik.io/traefik/llms.txt"
    return "https://doc.traefik.io/llms.txt"


def build_grounding(touched_paths: list[str]) -> dict:
    index_text = _gh.run_text([
        "api", f"repos/{REFERENCE_REPO}/contents/{INDEX_PATH}", "-H", "Accept: application/vnd.github.raw",
    ])
    entries = parse_index(index_text)
    matches = concepts_for_paths(entries, touched_paths)

    doc_index: dict = {}
    if matches:
        doc_index = _gh.run_json([
            "api", f"repos/{REFERENCE_REPO}/contents/{DOC_INDEX_PATH}",
            "--jq", ".content | @base64d | fromjson",
        ])

    enriched = []
    for m in matches:
        doc_entry = doc_index.get(m["id"], {})
        enriched.append({
            "id": m["id"],
            "kind": m.get("kind", ""),
            "source": m.get("source", ""),
            "extracted_from": m.get("extracted_from", []),
            "narrative_doc": doc_entry.get("narrative_doc"),
        })

    return {
        "concepts": enriched,
        "llms_txt_url": _llms_txt_url_for({c["source"] for c in enriched}),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--touched-files", nargs="+", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(build_grounding(args.touched_files), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
