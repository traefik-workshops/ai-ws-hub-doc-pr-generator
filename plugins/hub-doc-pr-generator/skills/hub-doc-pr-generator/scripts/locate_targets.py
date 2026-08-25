"""locate_targets.py — propose candidate doc file paths and neighbor pages
for the LLM to mirror in tone/structure.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

from scripts._frontmatter import split_front_matter, unquote

# A small static map of impl-repo Go-path prefixes → likely doc section.
_HUB_REF_MAP = {
    "hub/pkg/middleware/": ("docs/ai-gateway/middlewares/", "docs/api-gateway/reference/routing/http/middlewares/"),
    "hub/dashboard/":      ("docs/dashboard/",),
    "hub/portal/":         ("docs/portal/",),
}
_HUB_GUIDE_MAP = {
    "hub/dashboard/": ("docs/dashboard/guides/",),
    # "hub/pkg/" is broad enough to match almost any Hub Go package -- it is
    # NOT a specific-gateway signal despite counting as one matched prefix.
    # api-gateway listed first (not ai-gateway): confirmed live this generic
    # prefix confidently mis-picked AI Gateway for touched paths that were
    # actually API/MCP Gateway territory (AuthZEN, 2026-08-24) -- see
    # _section_dirs' fallback comment for the same reasoning applied there.
    "hub/pkg/":       ("docs/api-gateway/guides/", "docs/ai-gateway/guides/"),
}
_OSS_REF_MAP = {
    "pkg/middlewares/": ("docs/content/reference/routing/http/middlewares/",),
    "pkg/provider/":    ("docs/content/reference/install-configuration/providers/",),
}

_DOC_URL_RE = re.compile(r"https?://doc\.traefik\.io/(?:traefik-hub|traefik)/([a-zA-Z0-9\-/_]+)")
_REPO_PATH_RE = re.compile(r"\b(docs/[a-zA-Z0-9][a-zA-Z0-9\-_/]*\.mdx?)\b")
_FM_ID_RE = re.compile(r"^id:\s*(.+)$", re.MULTILINE)


def build_id_index(doc_repo_root: str) -> dict[str, str]:
    """Map a page's declared front-matter `id` -> its repo-relative path, built
    once per run over every `.md`/`.mdx` file under `docs/`.

    Exists because a `doc.traefik.io/.../<slug>` URL a human pastes into an
    issue is the rendered site's `id` slug, not the filename Docusaurus built
    it from -- those two only coincide by convention, not by rule. Confirmed
    live (traefik/hub-issues#3075): the URL named `ref-oidc`, but the real
    file is `oidc.md` with front matter `id: ref-oidc` — a filename-only scan
    (the pre-existing `existing_doc_refs` path check) can't resolve that and
    silently falls through to the much weaker path heuristic, which guessed
    the wrong product area entirely (AI Gateway instead of API Gateway).

    Malformed/unreadable pages are skipped rather than raising — a single bad
    front-matter block in an unrelated page shouldn't take down path
    resolution for everything else."""
    index: dict[str, str] = {}
    docs_dir = Path(doc_repo_root) / "docs"
    if not docs_dir.is_dir():
        return index
    for path in docs_dir.rglob("*"):
        if not (path.is_file() and path.suffix in {".md", ".mdx"}):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            fm_text, _ = split_front_matter(text)
        except ValueError:
            continue
        m = _FM_ID_RE.search(fm_text)
        if not m:
            continue
        doc_id = unquote(m.group(1).strip())
        if doc_id and doc_id not in index:
            index[doc_id] = str(path.relative_to(doc_repo_root))
    return index


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


def existing_doc_refs(issue_texts: list[str], *, doc_repo_root: str,
                       id_index: dict[str, str] | None = None) -> list[str]:
    """Doc pages a human already pointed to in linked-issue text — a doc.traefik.io
    URL or a literal repo-relative path — verified to actually exist in the doc
    repo, not guessed. This is the strongest possible placement signal: someone
    already named the target, so path-heuristic inference shouldn't override it
    (see the keyless-authentication mis-placement: the linked issue pointed
    straight at docs/api-management/api-auth, an existing page, while the path
    heuristic proposed a brand-new page in an unrelated directory).

    `id_index` (see build_id_index) resolves the common case where the URL's
    last segment is the page's declared front-matter `id`, not its filename —
    the two only coincide by convention. Filenames/paths are checked first
    (the cheaper, more literal signal); the id index is only consulted when
    that doesn't resolve, so a page that happens to share its `id` with
    another page's filename doesn't shadow a direct filename match."""
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
            resolved = None
            for ext in (".md", ".mdx"):
                path = f"docs/{slug}{ext}"
                if (root / path).is_file():
                    resolved = path
                    break
            if resolved is None and id_index:
                doc_id = slug.rsplit("/", 1)[-1]
                resolved = id_index.get(doc_id)
            if resolved and resolved not in seen:
                seen.add(resolved)
                found.append(resolved)
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
    # Generic fallback for Hub if nothing matched. Deliberately NOT an AI
    # Gateway directory: confirmed live (traefik-hub#1435, pure internal Go
    # paths like hub/pkg/hub/license with zero doc-adjacent mapping; and the
    # AuthZEN feature, which spans API+MCP gateways) that defaulting here to
    # AI Gateway produced a confidently wrong product-area guess both times,
    # in the same direction. API Gateway is the more general/foundational
    # layer in Hub's stack (Traefik Proxy -> Hub Gateway (API/AI/MCP) ->
    # optional Hub API Management) rather than one specific capability, so it
    # is the safer generic bucket when the touched paths give no real signal
    # -- still just a low-confidence guess (matched_prefixes stays 0, so this
    # never clears the auto-accept gates), not a confident pick.
    if not dirs and impl_repo == "traefik/traefik-hub":
        dirs = ["docs/api-gateway/reference/"] if doc_kind == "reference" else ["docs/api-gateway/guides/"]
    if not dirs and impl_repo == "traefik/traefik":
        dirs = ["docs/content/reference/"]
    return dirs, matched_prefixes


_MIDDLEWARE_PKG_PREFIXES = {
    "traefik/traefik-hub": "hub/pkg/middleware/",
    "traefik/traefik": "pkg/middlewares/",
}


def _normalize_name(s: str) -> str:
    """Lowercase and strip everything but alphanumerics, so 'content-guard'
    and 'contentguard' (the Go package name has no separators at all) compare
    equal without having to guess where hyphens belong."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _touched_middleware_pkgs(impl_repo: str, touched_paths: list[str]) -> dict[str, int]:
    """Middleware package name (the dir segment right after the middleware
    prefix) -> number of touched files under it. This is the touched
    component itself, not an LLM-invented feature slug -- the signal
    propose_paths() needs to find a page that already covers it."""
    prefix = _MIDDLEWARE_PKG_PREFIXES.get(impl_repo)
    if not prefix:
        return {}
    counts: dict[str, int] = {}
    for p in touched_paths:
        if p.startswith(prefix):
            pkg = p[len(prefix):].split("/", 1)[0]
            if pkg:
                counts[pkg] = counts.get(pkg, 0) + 1
    return counts


def find_existing_middleware_pages(*, doc_repo_root: str, section_dirs: list[str],
                                    pkg_counts: dict[str, int]) -> list[str]:
    """Existing doc pages in the candidate section dirs whose filename matches
    a touched middleware package (hyphen/underscore-insensitive), most-touched
    package first. Ties (or a PR spanning multiple middlewares) surface as
    multiple ranked entries rather than picking one arbitrarily."""
    if not pkg_counts:
        return []
    norm_pkgs = {pkg: _normalize_name(pkg) for pkg in pkg_counts}
    hits: list[tuple[str, int]] = []
    seen: set[str] = set()
    for d in section_dirs:
        dir_path = Path(doc_repo_root) / d
        if not dir_path.is_dir():
            continue
        for f in sorted(dir_path.iterdir()):
            if not (f.is_file() and f.suffix in {".md", ".mdx"}):
                continue
            norm_stem = _normalize_name(f.stem)
            for pkg, norm_pkg in norm_pkgs.items():
                if norm_stem == norm_pkg:
                    rel = str(f.relative_to(doc_repo_root))
                    if rel not in seen:
                        seen.add(rel)
                        hits.append((rel, pkg_counts[pkg]))
                    break
    hits.sort(key=lambda h: -h[1])
    return [h[0] for h in hits]


_PARTIAL_IMPORT_RE = re.compile(r"import\s+(\w+)\s+from\s+['\"]([^'\"]+)['\"]")


def find_transcluded_partials(*, doc_repo_root: str, candidate_paths: list[str]) -> list[dict]:
    """Shared `_*.mdx` partials transcluded into a candidate page via an
    import + component (e.g. `import DenyResponseFormats from
    '../_deny-response-formats.mdx'` then `<DenyResponseFormats />`).
    locate_targets can find the *page* that covers a touched middleware, but
    a page-level match hides content that actually lives in one of these
    partials — editing only the page's own prose would miss it entirely (see
    traefik-hub#1304: content-guard.md, llm-guard.md, and token-rate-limit.md
    all transclude docs/ai-gateway/_deny-response-formats.mdx).

    Scoped to `candidate_paths` — the existing pages already found by
    find_existing_middleware_pages() — not a repo-wide scan."""
    root = Path(doc_repo_root).resolve()
    seen: set[str] = set()
    hits: list[dict] = []
    for cand_path in candidate_paths:
        full = root / cand_path
        if not full.is_file():
            continue
        try:
            text = full.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in _PARTIAL_IMPORT_RE.finditer(text):
            component, rel_import = m.group(1), m.group(2)
            partial_name = rel_import.rsplit("/", 1)[-1]
            if not (partial_name.startswith("_") and partial_name.endswith((".md", ".mdx"))):
                continue
            partial_path = (full.parent / rel_import).resolve()
            if not partial_path.is_file():
                continue
            try:
                partial_rel = str(partial_path.relative_to(root))
            except ValueError:
                continue
            if partial_rel in seen:
                continue
            seen.add(partial_rel)
            hits.append({
                "path": partial_rel,
                "component": component,
                "transcluded_into": cand_path,
            })
    return hits


def propose_paths(*, impl_repo: str, doc_kind: str, feature_slug: str,
                  touched_paths: list[str], doc_repo_root: str | None = None) -> list[dict]:
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
        rationale = (
            "No touched-path prefix matched a specific gateway product area — "
            "generic fallback directory, not a confident guess; verify the "
            "product area by hand before accepting"
        )
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

    if doc_repo_root is not None:
        pkg_counts = _touched_middleware_pkgs(impl_repo, touched_paths)
        existing_pages = find_existing_middleware_pages(
            doc_repo_root=doc_repo_root, section_dirs=section_dirs, pkg_counts=pkg_counts,
        )
        if existing_pages:
            # A page for the touched middleware already exists -- propose it
            # (ranked by how much of the PR touches that middleware) ahead of
            # any fabricated new filename, which stays in the list, demoted,
            # in case this really is an additional new page.
            for c in out:
                c["confidence"] = round(min(c["confidence"], 0.7), 2)
            existing_candidates = [
                {
                    "path": p,
                    "confidence": round(max(0.93 - 0.08 * i, 0.75), 2),
                    "rationale": "Existing page's filename matches a touched middleware package",
                }
                for i, p in enumerate(existing_pages)
            ]
            out = existing_candidates + out

            # Surface, but never auto-select: a partial transcluded into one
            # of the pages above may be where the actual content to edit
            # lives, not the page's own prose. Confidence stays well under
            # the auto-accept gate — this is "go check," not a placement.
            for partial in find_transcluded_partials(
                doc_repo_root=doc_repo_root, candidate_paths=existing_pages,
            ):
                out.append({
                    "path": partial["path"],
                    "confidence": 0.5,
                    "kind": "shared_partial",
                    "rationale": (
                        f"Transcluded into {partial['transcluded_into']} via "
                        f"<{partial['component']} /> — verify whether this shared "
                        "partial (not just the page) needs the edit"
                    ),
                })

            # existing_candidates and the fabricated {feature_slug}.md entries
            # are built independently -- if the LLM-chosen feature_slug happens
            # to normalize to the same filename as an existing page, that path
            # would otherwise appear twice (once as the ~0.9-confidence
            # existing-page match, once as the capped fabricated entry).
            # First occurrence wins: existing_candidates were prepended first,
            # so they take priority.
            deduped: dict[str, dict] = {}
            for c in out:
                deduped.setdefault(c["path"], c)
            out = list(deduped.values())
        else:
            # The check ran and found no existing page -- this filename is
            # confirmed fabricated, not just directory-grounded. Don't let it
            # clear the 0.75 auto-accept gate on the strength of the (correct)
            # directory match alone.
            for c in out:
                c["confidence"] = round(min(c["confidence"], 0.7), 2)
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
        doc_repo_root=doc_repo_root,
    )
    # A page a human already named in the linked issue beats any path-heuristic
    # guess — but only when the scan turns up exactly ONE distinct page. Multiple
    # distinct references is itself ambiguous, so don't arbitrarily pick one;
    # fall through to the heuristic candidates instead.
    doc_refs = existing_doc_refs(
        list(issue_texts), doc_repo_root=doc_repo_root,
        id_index=build_id_index(doc_repo_root),
    )
    # Check membership across the WHOLE candidate list, not just index 0 --
    # find_existing_middleware_pages() can already surface the human-referenced
    # page at index 1+ (e.g. ranked behind another touched middleware's page),
    # in which case re-inserting it at index 0 would produce a harmless-looking
    # but confusing duplicate entry for the same path with two different
    # confidences/rationales.
    if len(doc_refs) == 1 and doc_refs[0] not in {c["path"] for c in candidates}:
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
    # nargs="*" (not "+"): an issue-only bundle (fetch_issue.py) has no touched
    # Go files at all. build_locate()/propose_paths() already tolerate an
    # empty list -- this just stops argparse itself from rejecting it first,
    # matching the convention fetch_grounding.py already uses for the same case.
    parser.add_argument("--touched-files", nargs="*", default=[])
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
