"""fetch_grounding.py — load the traefik/reference catalog and match concepts
to the Go files a PR touched.

traefik/reference layout (as of generator 0.4.x):
- reference/INDEX.md       flat catalog: `## Section` headers, then bullets
                           `` `concept.id` , TypeName , description``
- reference/<source>/<path>.md   per-concept page; YAML front matter carries
                           id, kind, source, extracted_from, fields, summary
- reference/DOC_INDEX.json {"entries": [{concept_id, source, doc_path}]}

There is no central Go-file -> concept index, so matching is token based:
tokens from the touched file paths are matched against each concept's last id
segment or its TypeName. Matched concepts are then enriched by fetching their
own page for `kind`, `fields`, and `summary`, and cross-linked via DOC_INDEX.
(The page's `extracted_from` list is parsed but not surfaced in the output.)
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from scripts import _gh

REFERENCE_REPO = "traefik/reference"
INDEX_PATH = "reference/INDEX.md"
DOC_INDEX_PATH = "reference/DOC_INDEX.json"

# `## Section` headers, e.g. "## HTTP middlewares"
_SECTION_RE = re.compile(r"^##\s+(?P<section>.+?)\s*$")
# `- `concept.id` , TypeName , description`
_ENTRY_RE = re.compile(r"^-\s+`(?P<id>[^`]+)`\s*,\s*(?P<type_name>[^,]+?)\s*,\s*(?P<desc>.*)$")

# Generic path segments that carry no concept signal.
_STOPWORDS = {
    "pkg", "internal", "cmd", "config", "middleware", "middlewares", "go",
    "http", "tcp", "udp", "tls", "api", "hub", "oss", "dynamic", "types",
    "options", "option", "server", "handler", "handlers", "service", "services",
    "common", "util", "utils", "main", "test", "tests", "doc", "docs", "v1",
    "v1alpha1", "apis", "crd", "crds",
}


def parse_index(text: str) -> list[dict]:
    entries: list[dict] = []
    section = ""
    for line in text.splitlines():
        m = _SECTION_RE.match(line)
        if m:
            section = m["section"]
            continue
        m = _ENTRY_RE.match(line)
        if m:
            entries.append({
                "id": m["id"].strip(),
                "type_name": m["type_name"].strip(),
                "description": m["desc"].strip(),
                "section": section,
            })
    return entries


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    return v


def parse_front_matter(text: str) -> dict:
    """Minimal YAML front-matter parser for the fields this skill needs:
    top-level scalars, the `extracted_from` string list, and the `fields`
    list of {name, type}. Each field item may carry extra keys (go_name,
    go_type, description) between name and type. Other nested blocks
    (e.g. representations) are skipped."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm: dict = {}
    section = None       # active top-level block: 'extracted_from' | 'fields' | other
    cur_field = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        top = re.match(r"^(?P<k>[A-Za-z0-9_]+):\s?(?P<v>.*)$", line)  # no indentation
        if top:
            k, v = top["k"], top["v"].strip()
            cur_field = None
            if v == "":
                section = k
                if k in ("extracted_from", "fields"):
                    fm[k] = []
            else:
                fm[k] = _unquote(v)
                section = None
            continue
        if section == "extracted_from":
            mm = re.match(r"^\s+-\s+(?P<val>.+)$", line)
            if mm:
                fm["extracted_from"].append(mm["val"].split("#", 1)[0].strip())
            continue
        if section == "fields":
            nm = re.match(r"^\s+-\s+name:\s*(?P<n>.+)$", line)
            if nm:
                cur_field = {"name": _unquote(nm["n"])}
                fm["fields"].append(cur_field)
                continue
            tm = re.match(r"^\s+type:\s*(?P<t>.+)$", line)
            if tm and cur_field is not None:
                cur_field["type"] = _unquote(tm["t"])
            continue
        # Inside an unrelated nested block — skip.
    return fm


def _tokens_for_paths(touched_paths: list[str]) -> set[str]:
    tokens: set[str] = set()
    for p in touched_paths:
        for seg in p.replace("\\", "/").split("/"):
            seg = seg.rsplit(".", 1)[0]  # drop file extension
            seg = re.sub(r"[^a-z0-9]", "", seg.lower())
            if seg and seg not in _STOPWORDS and len(seg) > 2:
                tokens.add(seg)
    return tokens


def concepts_for_paths(entries: list[dict], touched_paths: list[str]) -> list[dict]:
    tokens = _tokens_for_paths(touched_paths)
    if not tokens:
        return []
    matched = []
    for e in entries:
        last_seg = e["id"].rsplit(".", 1)[-1].lower()
        type_norm = re.sub(r"[^a-z0-9]", "", e["type_name"].lower())
        if last_seg in tokens or type_norm in tokens:
            matched.append(e)
    return matched


def concept_page_path(concept_id: str, source: str) -> str:
    segs = concept_id.split(".")
    if segs and segs[0] == source:
        segs = segs[1:]
    return f"reference/{source}/{'/'.join(segs)}.md"


def _fetch_raw(path: str) -> str:
    return _gh.run_text([
        "api", f"repos/{REFERENCE_REPO}/contents/{path}",
        "-H", "Accept: application/vnd.github.raw",
    ])


def _llms_txt_url_for(impl_repo: str | None, sources: set[str]) -> str:
    hub = "https://doc.traefik.io/traefik-hub/llms.txt"
    oss = "https://doc.traefik.io/traefik/llms.txt"
    if impl_repo == "traefik/traefik-hub":
        return hub
    if impl_repo == "traefik/traefik":
        return oss
    if "hub" in sources:
        return hub
    if "oss" in sources:
        return oss
    return hub


_SOURCE_FOR_IMPL_REPO = {
    "traefik/traefik-hub": "hub",
    "traefik/traefik": "oss",
}


def build_grounding(touched_paths: list[str], *, impl_repo: str | None = None) -> dict:
    entries = parse_index(_fetch_raw(INDEX_PATH))
    matches = concepts_for_paths(entries, touched_paths)
    total_matched = len(matches)

    doc_map: dict[str, dict] = {}
    if matches:
        doc_index = json.loads(_fetch_raw(DOC_INDEX_PATH))
        for entry in doc_index.get("entries", []):
            doc_map[entry["concept_id"]] = entry

    # Filter by source family BEFORE truncating to top 3. Token matching alone
    # is repo-agnostic (see the module docstring — there's no Go-file -> concept
    # index), so an impl_repo=traefik/traefik-hub PR can token-match unrelated
    # OSS provider concepts (Docker, ECS, etcd) that happen to sort earlier in
    # INDEX.md, crowding the real Hub concepts out of the top-3 slice entirely.
    # A concept with no DOC_INDEX entry (source unknown) is kept — we can't
    # confidently call it irrelevant just because we don't know its family yet.
    expected_source = _SOURCE_FOR_IMPL_REPO.get(impl_repo)
    if expected_source:
        matches = [
            m for m in matches
            if doc_map.get(m["id"], {}).get("source", expected_source) == expected_source
        ]
    matches = matches[:3]

    enriched = []
    for m in matches:
        cid = m["id"]
        di = doc_map.get(cid)
        source = di.get("source") if di else None
        concept = {
            "id": cid,
            "type_name": m["type_name"],
            "kind": "",
            "source": source,
            "summary": m["description"],
            "fields": [],
            "narrative_doc": di.get("doc_path") if di else None,
        }
        if source:
            try:
                fm = parse_front_matter(_fetch_raw(concept_page_path(cid, source)))
                concept["kind"] = fm.get("kind", "")
                concept["fields"] = fm.get("fields", [])
                if fm.get("summary"):
                    concept["summary"] = fm["summary"]
            except _gh.GhError:
                pass
        enriched.append(concept)

    sources = {c["source"] for c in enriched if c["source"]}
    return {
        "concepts": enriched,
        "concepts_total_matched": total_matched,
        "llms_txt_url": _llms_txt_url_for(impl_repo, sources),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    # nargs="*" (not "+"): the caller expands this from a `jq` of the PR's
    # changed files, which can legitimately be empty (e.g. a PR touching only
    # test/generated files, which fetch_pr filters out). Empty → no concepts,
    # and the skill falls back to neighbor-only grounding.
    parser.add_argument("--touched-files", nargs="*", default=[])
    parser.add_argument("--impl-repo", default=None)
    args = parser.parse_args(argv)
    print(json.dumps(build_grounding(args.touched_files, impl_repo=args.impl_repo), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
