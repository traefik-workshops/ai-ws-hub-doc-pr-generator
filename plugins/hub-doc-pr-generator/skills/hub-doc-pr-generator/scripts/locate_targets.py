"""locate_targets.py — propose candidate doc file paths and neighbor pages
for the LLM to mirror in tone/structure.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

# A small static map of impl-repo Go-path prefixes → likely doc section.
_HUB_REF_MAP = {
    "hub/pkg/middleware/": ("docs/ai-gateway/middlewares/", "docs/api-gateway/reference/routing/http/middlewares/"),
    "hub/dashboard/":      ("docs/dashboard/",),
    "hub/portal/":         ("docs/portal/",),
}
_HUB_GUIDE_MAP = {
    "hub/dashboard/": ("docs/dashboard/guides/",),
    "hub/pkg/":       ("docs/ai-gateway/guides/", "docs/api-gateway/guides/"),
}
_OSS_REF_MAP = {
    "pkg/middlewares/": ("docs/content/reference/routing/http/middlewares/",),
    "pkg/provider/":    ("docs/content/reference/install-configuration/providers/",),
}

_DOC_URL_RE = re.compile(r"https?://doc\.traefik\.io/(?:traefik-hub|traefik)/([a-zA-Z0-9\-/_]+)")
_REPO_PATH_RE = re.compile(r"\b(docs/[a-zA-Z0-9][a-zA-Z0-9\-_/]*\.mdx?)\b")


def issue_texts_from_bundle(bundle: dict) -> list[str]:
    """Every linked-issue body + comment body — text a human wrote that may
    directly name the doc page this PR belongs in."""
    texts: list[str] = []
    for iss in bundle.get("merged", {}).get("linked_issues", []):
        if iss.get("body"):
            texts.append(iss["body"])
        for c in iss.get("comments", []):
            if c.get("body"):
                texts.append(c["body"])
    return texts


def existing_doc_refs(issue_texts: list[str], *, doc_repo_root: str) -> list[str]:
    """Doc pages a human already pointed to in linked-issue text — a doc.traefik.io
    URL or a literal repo-relative path — verified to actually exist in the doc
    repo, not guessed. This is the strongest possible placement signal: someone
    already named the target, so path-heuristic inference shouldn't override it
    (see the keyless-authentication mis-placement: the linked issue pointed
    straight at docs/api-management/api-auth, an existing page, while the path
    heuristic proposed a brand-new page in an unrelated directory)."""
    root = Path(doc_repo_root)
    found: list[str] = []
    seen: set[str] = set()
    for text in issue_texts:
        for m in _REPO_PATH_RE.finditer(text):
            path = m.group(1)
            if path not in seen and (root / path).is_file():
                seen.add(path)
                found.append(path)
        for m in _DOC_URL_RE.finditer(text):
            slug = m.group(1).strip("/")
            for ext in (".md", ".mdx"):
                path = f"docs/{slug}{ext}"
                if path in seen:
                    break
                if (root / path).is_file():
                    seen.add(path)
                    found.append(path)
                    break
    return found


def _section_dirs(impl_repo: str, doc_kind: str, touched_paths: list[str]) -> tuple[list[str], int]:
    """Returns (dirs, matched_prefix_count). matched_prefix_count == 0 means no
    touched-path prefix matched and the generic single-dir fallback was used."""
    if impl_repo == "traefik/traefik-hub":
        m = _HUB_REF_MAP if doc_kind == "reference" else _HUB_GUIDE_MAP
    else:
        m = _OSS_REF_MAP
    dirs: list[str] = []
    matched_prefixes = 0
    for prefix, sections in m.items():
        if any(p.startswith(prefix) for p in touched_paths):
            dirs.extend(sections)
            matched_prefixes += 1
    # Generic fallback for Hub if nothing matched
    if not dirs and impl_repo == "traefik/traefik-hub":
        dirs = ["docs/ai-gateway/middlewares/"] if doc_kind == "reference" else ["docs/ai-gateway/guides/"]
    if not dirs and impl_repo == "traefik/traefik":
        dirs = ["docs/content/reference/"]
    return dirs, matched_prefixes


def propose_paths(*, impl_repo: str, doc_kind: str, feature_slug: str,
                  touched_paths: list[str]) -> list[dict]:
    section_dirs, matched_prefixes = _section_dirs(impl_repo, doc_kind, touched_paths)
    # Confidence reflects how GROUNDED the match is, not how many directories a
    # single matched prefix happens to map to. Directory count alone is the wrong
    # denominator: one matched prefix that fans out to two candidate dirs (e.g.
    # middleware reference pages living in two places) is still one solid signal,
    # not two competing guesses.
    #  - 0 prefixes matched -> generic single-dir fallback, the LEAST grounded
    #    guess -> low confidence (must clear the 0.75 auto-accept gate honestly).
    #  - 1 prefix matched -> specific, well-grounded match -> high confidence.
    #  - >1 distinct prefixes matched -> touched paths span unrelated sections,
    #    a genuinely ambiguous signal -> confidence split across them.
    if matched_prefixes == 0:
        base = 0.3
        rationale = "No touched-path prefix matched — generic fallback directory"
    elif matched_prefixes == 1:
        base = 0.9
        rationale = None
    else:
        base = round(0.9 / matched_prefixes, 2)
        rationale = None
    out = []
    for i, d in enumerate(section_dirs):
        out.append({
            "path": f"{d}{feature_slug}.md",
            "confidence": round(base if i == 0 else base * 0.8, 2),
            "rationale": rationale or f"Inferred section dir {d} from touched paths",
        })
    return out


def select_neighbors(*, doc_repo_root: str, target_path: str, limit: int = 5) -> list[str]:
    target_dir = Path(doc_repo_root) / Path(target_path).parent
    if not target_dir.is_dir():
        return []
    candidates = sorted(
        p for p in target_dir.iterdir()
        if p.is_file() and p.suffix in {".md", ".mdx"}
    )
    return [str(p.relative_to(doc_repo_root)) for p in candidates[:limit]]


_SIDEBAR_ID_RE = re.compile(r'"([\w\-]+(?:/[\w\-]+)+)"')


def sidebar_insertion_point(sidebars_js: str, *, target_path: str) -> dict | None:
    # Convert e.g. "docs/ai-gateway/middlewares/new-thing.md" to id prefix
    # "ai-gateway/middlewares/" and find the last id in that section.
    rel = target_path.removeprefix("docs/").removesuffix(".md").removesuffix(".mdx")
    section_prefix = rel.rsplit("/", 1)[0] + "/"
    ids_in_section = [
        m.group(1) for m in _SIDEBAR_ID_RE.finditer(sidebars_js)
        if m.group(1).startswith(section_prefix)
    ]
    if not ids_in_section:
        return None
    return {"file": "sidebars.js", "after_id": ids_in_section[-1]}


def build_locate(*, impl_repo: str, doc_repo_root: str, doc_kind: str,
                 feature_slug: str, touched_paths: list[str],
                 issue_texts: list[str] = ()) -> dict:
    candidates = propose_paths(
        impl_repo=impl_repo, doc_kind=doc_kind,
        feature_slug=feature_slug, touched_paths=touched_paths,
    )
    # A page a human already named in the linked issue beats any path-heuristic
    # guess — but only when the scan turns up exactly ONE distinct page. Multiple
    # distinct references is itself ambiguous, so don't arbitrarily pick one;
    # fall through to the heuristic candidates instead.
    doc_refs = existing_doc_refs(list(issue_texts), doc_repo_root=doc_repo_root)
    if len(doc_refs) == 1:
        candidates.insert(0, {
            "path": doc_refs[0],
            "confidence": 0.97,
            "rationale": "Directly referenced as an existing page in the linked issue's text",
        })
    target = candidates[0]["path"] if candidates else ""
    neighbors = select_neighbors(doc_repo_root=doc_repo_root, target_path=target)
    candidates[0]["neighbors"] = neighbors
    target_exists = bool(target) and (Path(doc_repo_root) / target).is_file()
    ins = None
    if impl_repo == "traefik/traefik-hub":
        sidebars = Path(doc_repo_root) / "sidebars.js"
        if sidebars.is_file():
            ins = sidebar_insertion_point(
                sidebars.read_text(), target_path=target
            )
    return {
        "candidates": candidates,
        "sidebar_insertion_point": ins,
        "target_exists": target_exists,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--impl-repo", required=True)
    parser.add_argument("--doc-repo-root", required=True)
    parser.add_argument("--doc-kind", required=True, choices=["reference", "user-guide"])
    parser.add_argument("--feature-slug", required=True)
    parser.add_argument("--touched-files", nargs="+", required=True)
    parser.add_argument("--bundle", default=None,
                        help="path to pr-bundle.json; scanned for an existing doc page "
                             "explicitly referenced in the linked issue's text")
    args = parser.parse_args(argv)
    issue_texts: list[str] = []
    if args.bundle:
        bundle = json.loads(Path(args.bundle).read_text())
        issue_texts = issue_texts_from_bundle(bundle)
    out = build_locate(
        impl_repo=args.impl_repo,
        doc_repo_root=args.doc_repo_root,
        doc_kind=args.doc_kind,
        feature_slug=args.feature_slug,
        touched_paths=args.touched_files,
        issue_texts=issue_texts,
    )
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
