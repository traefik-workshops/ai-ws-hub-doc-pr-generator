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


def _section_dirs(impl_repo: str, doc_kind: str, touched_paths: list[str]) -> list[str]:
    if impl_repo == "traefik/traefik-hub":
        m = _HUB_REF_MAP if doc_kind == "reference" else _HUB_GUIDE_MAP
    else:
        m = _OSS_REF_MAP
    dirs: list[str] = []
    for prefix, sections in m.items():
        if any(p.startswith(prefix) for p in touched_paths):
            dirs.extend(sections)
    # Generic fallback for Hub if nothing matched
    if not dirs and impl_repo == "traefik/traefik-hub":
        dirs = ["docs/ai-gateway/middlewares/"] if doc_kind == "reference" else ["docs/ai-gateway/guides/"]
    if not dirs and impl_repo == "traefik/traefik":
        dirs = ["docs/content/reference/"]
    return dirs


def propose_paths(*, impl_repo: str, doc_kind: str, feature_slug: str,
                  touched_paths: list[str]) -> list[dict]:
    section_dirs = _section_dirs(impl_repo, doc_kind, touched_paths)
    base = max(0.4, 1.0 / max(len(section_dirs), 1))
    out = []
    for i, d in enumerate(section_dirs):
        out.append({
            "path": f"{d}{feature_slug}.md",
            "confidence": round(base if i == 0 else base * 0.8, 2),
            "rationale": f"Inferred section dir {d} from touched paths",
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
                 feature_slug: str, touched_paths: list[str]) -> dict:
    candidates = propose_paths(
        impl_repo=impl_repo, doc_kind=doc_kind,
        feature_slug=feature_slug, touched_paths=touched_paths,
    )
    target = candidates[0]["path"] if candidates else ""
    neighbors = select_neighbors(doc_repo_root=doc_repo_root, target_path=target)
    candidates[0]["neighbors"] = neighbors
    ins = None
    if impl_repo == "traefik/traefik-hub":
        sidebars = Path(doc_repo_root) / "sidebars.js"
        if sidebars.is_file():
            ins = sidebar_insertion_point(
                sidebars.read_text(), target_path=target
            )
    return {"candidates": candidates, "sidebar_insertion_point": ins}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--impl-repo", required=True)
    parser.add_argument("--doc-repo-root", required=True)
    parser.add_argument("--doc-kind", required=True, choices=["reference", "user-guide"])
    parser.add_argument("--feature-slug", required=True)
    parser.add_argument("--touched-files", nargs="+", required=True)
    args = parser.parse_args(argv)
    out = build_locate(
        impl_repo=args.impl_repo,
        doc_repo_root=args.doc_repo_root,
        doc_kind=args.doc_kind,
        feature_slug=args.feature_slug,
        touched_paths=args.touched_files,
    )
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
