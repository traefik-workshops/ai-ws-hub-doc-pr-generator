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
