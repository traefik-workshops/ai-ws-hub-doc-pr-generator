"""_product_areas.py — the single source of truth for Hub/OSS product-area
Go-path prefixes, shared between locate_targets.py (page PLACEMENT: given an
already-decided doc kind, where should a page live) and classify.py (doc kind
SCORING: which kind does a touched path suggest in the first place).

These are two different questions about the same prefixes, and they don't
always agree per-prefix -- e.g. "hub/dashboard/" has both a reference page
location (docs/dashboard/) in _HUB_REF_MAP below AND a guide page location
(docs/dashboard/guides/) in _HUB_GUIDE_MAP, because a dashboard change really
could go either way depending on what doc_kind is separately decided.
classify.py's doc-kind scoring collapses that placement ambiguity into one
scoring direction (a dashboard touch is treated as a guide SIGNAL only) --
that collapse is classify's own judgment call, so REFERENCE_SIGNAL_PREFIXES /
GUIDE_SIGNAL_PREFIXES below are kept as their own explicit constants rather
than derived automatically from _HUB_REF_MAP/_HUB_GUIDE_MAP's membership.

What IS enforced automatically (see scripts/tests/test_product_areas_sync.py)
is that every non-generic prefix in _HUB_REF_MAP/_HUB_GUIDE_MAP has SOME entry
in REFERENCE_SIGNAL_PREFIXES or GUIDE_SIGNAL_PREFIXES -- so a new product-area
prefix added for placement purposes can't silently go unrecognized by doc-kind
scoring. That's the actual drift this module's existence guards against: two
independently-maintained prefix lists were previously each missing whatever
the other one didn't happen to have.
"""
from __future__ import annotations


class _Section:
    """One impl-repo Go-path prefix -> likely doc section(s), plus whether
    that prefix is a real product-area signal or just a broad catch-all.

    `generic=True` is declared right here, next to the prefix it describes,
    rather than in a separately-maintained set elsewhere in the file --
    adding a new broad/catch-all prefix to one of the maps below and marking
    it generic is a single edit instead of two that have to be kept in sync
    by hand (a forgotten second edit previously let an overly-broad prefix
    silently inflate its confidence score to that of a real signal; see
    locate_targets.py's _section_dirs/propose_paths for how `generic` is
    used)."""

    __slots__ = ("dirs", "generic")

    def __init__(self, *dirs: str, generic: bool = False) -> None:
        self.dirs = dirs
        self.generic = generic


# A small static map of impl-repo Go-path prefixes → likely doc section.
# Consumed by locate_targets.py's _section_dirs() to pick candidate
# directories once doc_kind is already known.
HUB_REF_MAP = {
    "hub/pkg/middleware/": _Section("docs/ai-gateway/middlewares/", "docs/api-gateway/reference/routing/http/middlewares/"),
    "hub/dashboard/":      _Section("docs/dashboard/"),
    "hub/portal/":         _Section("docs/portal/"),
}
HUB_GUIDE_MAP = {
    "hub/dashboard/": _Section("docs/dashboard/guides/"),
    # "hub/pkg/" is broad enough to match almost any Hub Go package -- it is
    # NOT a specific-gateway signal despite counting as one matched prefix,
    # hence generic=True. api-gateway listed first (not ai-gateway):
    # confirmed live this generic prefix confidently mis-picked AI Gateway
    # for touched paths that were actually API/MCP Gateway territory
    # (AuthZEN, 2026-08-24) -- see locate_targets.py's _section_dirs fallback
    # comment for the same reasoning applied there.
    "hub/pkg/": _Section("docs/api-gateway/guides/", "docs/ai-gateway/guides/", generic=True),
}
OSS_REF_MAP = {
    "pkg/middlewares/": _Section("docs/content/reference/routing/http/middlewares/"),
    "pkg/provider/":    _Section("docs/content/reference/install-configuration/providers/"),
}

# Consumed by classify.py's doc_kind_candidates() to score which doc kind a
# touched path suggests. See this module's docstring for why these are their
# own constants rather than derived from HUB_REF_MAP/HUB_GUIDE_MAP directly.
REFERENCE_SIGNAL_PREFIXES = ("hub/pkg/middleware/",)
GUIDE_SIGNAL_PREFIXES = ("hub/dashboard/", "hub/portal/")
