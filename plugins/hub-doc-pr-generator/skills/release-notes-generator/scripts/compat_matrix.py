"""compat_matrix.py — compatibility-matrix values for a Hub release tag.

None of this is derivable from a commit changelog. Confirmed the hard way:
manually cross-checking a hand-drafted v3.20.8 entry against `go.mod` at that
tag turned up a stale Kubernetes Gateway API version (v1.5.1) the draft had
silently carried forward from the previous release, when the tag actually
pinned v1.6.1. This pulls the authoritative values instead of trusting
whatever the last published entry said:

  - Coraza WAF / OWASP CRS / Kubernetes Gateway API: pinned versions read
    directly from `go.mod` at the release tag (traefik/traefik-hub).
  - Traefik Proxy: read from `go.mod`'s `github.com/traefik/traefik/v3`
    pin, not from a "chore: bump traefik to vX.Y.Z" commit message and,
    somewhat surprisingly, not from `hub/pkg/version/traefik.version`
    either. That file looks like the obvious authoritative source (commit
    e9bb444, "fix: align traefik.version with the pinned Traefik version",
    exists specifically to keep it in sync) but verified live against both
    v3.19.13 and v3.20.8: the file reads one patch behind what go.mod
    actually pins (v3.6.24 vs. go.mod's v3.6.25, v3.7.9 vs. go.mod's
    v3.7.10) at both tags. go.mod often pins a pre-release pseudo-version
    (`vX.Y.Z-0.<timestamp>-<hash>`) rather than a clean tag — confirmed by
    checking that the embedded commit hash matches the real upstream
    `traefik/traefik` tag exactly, so the `vX.Y.Z` prefix is trustworthy
    even when it's a pseudo-version. See traefik_proxy_version() below: it
    reads both sources and surfaces a note when they disagree, rather than
    silently trusting either one.
  - Helm Chart: traefik-helm-chart doesn't tag a chart release per Hub
    release. This scans its recent tags for whichever `Chart.yaml` has
    `traefik.io/hub-min-version` / `hub-max-version` annotations bracketing
    the target tag. No YAML dependency — these are flat `key: value` lines,
    parsed with a regex, matching the stdlib-only rule the rest of this
    plugin follows. As of writing this can genuinely come back empty (the
    latest chart tag can lag a day or more behind a Hub patch release) —
    that's reported as `version: null`, never guessed.
  - Static Analyzer: no pin location has been identified yet. The Makefile
    invokes `hub-static-analyzer` but doesn't pin a version anywhere found
    so far. Always reported as unknown; see references/compat-matrix-sources.md
    before wiring this up for real.

Usage:
  python -m scripts.compat_matrix --tag v3.19.13 --tag v3.20.8 [--max-chart-tags 25]
"""
from __future__ import annotations
import argparse
import base64
import json
import re
import sys
from typing import Optional

from scripts import _gh, _semver

HUB_REPO = "traefik/traefik-hub"
CHART_REPO = "traefik/traefik-helm-chart"
TRAEFIK_VERSION_FILE = "hub/pkg/version/traefik.version"

_GO_MOD_DEPS = {
    "coraza_waf": re.compile(r"github\.com/corazawaf/coraza/v3\s+(v\S+)"),
    "owasp_crs": re.compile(r"github\.com/corazawaf/coraza-coreruleset/v4\s+(v\S+)"),
    "kubernetes_gateway_api": re.compile(r"sigs\.k8s\.io/gateway-api\s+(v\S+)"),
}

_TRAEFIK_MOD_RE = re.compile(r"github\.com/traefik/traefik/v3\s+(\S+)")
_PSEUDOVERSION_RE = re.compile(r"^(v\d+\.\d+\.\d+)-0\.\d+-[0-9a-f]+$")

_CHART_VERSION_RE = re.compile(r"^version:\s*(\S+)", re.MULTILINE)
_HUB_MIN_RE = re.compile(r"traefik\.io/hub-min-version:\s*(\S+)")
_HUB_MAX_RE = re.compile(r"traefik\.io/hub-max-version:\s*(\S+)")


def _file_at_ref(repo: str, path: str, ref: str) -> Optional[str]:
    try:
        b64 = _gh.run_text(["api", f"repos/{repo}/contents/{path}?ref={ref}", "--jq", ".content"])
    except _gh.GhError:
        return None
    return base64.b64decode(b64).decode("utf-8", errors="replace")


def go_mod_deps(tag: str) -> dict[str, Optional[str]]:
    content = _file_at_ref(HUB_REPO, "go.mod", tag)
    if content is None:
        return {name: None for name in _GO_MOD_DEPS}
    out: dict[str, Optional[str]] = {}
    for name, pattern in _GO_MOD_DEPS.items():
        m = pattern.search(content)
        out[name] = m.group(1) if m else None
    return out


def _traefik_version_from_go_mod(content: str) -> Optional[str]:
    m = _TRAEFIK_MOD_RE.search(content)
    if not m:
        return None
    raw = m.group(1)
    pseudo = _PSEUDOVERSION_RE.match(raw)
    # A pseudo-version's vX.Y.Z prefix is the version it's pinned past, not
    # necessarily a tagged release — but in the two cases checked live, the
    # embedded commit hash matched the real upstream tag of that same
    # vX.Y.Z exactly, so treat the prefix as the release version.
    return pseudo.group(1) if pseudo else raw


def traefik_proxy_version(tag: str) -> dict:
    """Prefer go.mod's pin; cross-check against the traefik.version file and
    surface a note (never silently pick one) when they disagree — verified
    live that they can, at both v3.19.13 and v3.20.8, with the file one patch
    behind go.mod both times."""
    go_mod_content = _file_at_ref(HUB_REPO, "go.mod", tag)
    from_go_mod = _traefik_version_from_go_mod(go_mod_content) if go_mod_content else None

    pinned_file_content = _file_at_ref(HUB_REPO, TRAEFIK_VERSION_FILE, tag)
    from_file = pinned_file_content.strip() if pinned_file_content else None

    if from_go_mod is None:
        return {
            "version": from_file,
            "note": "github.com/traefik/traefik/v3 not found in go.mod; fell back to "
                    "hub/pkg/version/traefik.version" if from_file else
                    "could not determine Traefik Proxy version from go.mod or traefik.version",
        }
    if from_file and from_file != from_go_mod:
        return {
            "version": from_go_mod,
            "note": (
                f"go.mod pins {from_go_mod}; hub/pkg/version/traefik.version reads {from_file} — "
                "these disagree at this tag. Using go.mod (verified: its pinned commit hash matches "
                "the real upstream traefik/traefik tag). Worth flagging the mismatch to the team, "
                "since traefik.version exists specifically to avoid this (see commit e9bb444)."
            ),
        }
    return {"version": from_go_mod, "note": None}


def _chart_tag_names(max_tags: int) -> list[str]:
    raw = _gh.run_text(["api", f"repos/{CHART_REPO}/tags", "--paginate", "--jq", ".[].name"])
    return [line for line in raw.splitlines() if line.strip()][:max_tags]


def helm_chart_for(tag: str, *, max_chart_tags: int) -> dict:
    target = _semver.parse(tag)
    if target is None:
        return {"version": None, "note": f"could not parse semver from {tag!r}"}

    for chart_tag in _chart_tag_names(max_chart_tags):
        content = _file_at_ref(CHART_REPO, "traefik/Chart.yaml", chart_tag)
        if content is None:
            continue
        min_m, max_m = _HUB_MIN_RE.search(content), _HUB_MAX_RE.search(content)
        if not (min_m and max_m):
            continue
        lo, hi = _semver.parse(min_m.group(1)), _semver.parse(max_m.group(1))
        if lo is None or hi is None:
            continue
        if lo.key() <= target.key() <= hi.key():
            ver_m = _CHART_VERSION_RE.search(content)
            return {
                "version": ver_m.group(1) if ver_m else chart_tag.lstrip("v"),
                "note": f"from chart {chart_tag} (hub-min {min_m.group(1)}, hub-max {max_m.group(1)})",
            }

    return {
        "version": None,
        "note": (
            f"no chart release among the last {max_chart_tags} tags covers {tag} yet — "
            "check traefik-helm-chart for a newer release before publishing, or leave as TBD"
        ),
    }


def static_analyzer_version() -> dict:
    return {
        "version": None,
        "note": (
            "pin location not yet identified (Makefile invokes hub-static-analyzer without "
            "a version pin) — carry forward the previous release's value and verify manually; "
            "see references/compat-matrix-sources.md"
        ),
    }


_DISPLAY_NAMES = {
    "traefik_hub": "Traefik Hub",
    "helm_chart": "Helm Chart",
    "traefik_proxy": "Traefik Proxy",
    "coraza_waf": "Coraza WAF",
    "owasp_crs": "OWASP CRS",
    "static_analyzer": "Static Analyzer",
    "kubernetes_gateway_api": "Kubernetes Gateway API",
}


def merge_fragment_deltas(matrix: dict, fragment_deltas: list[dict]) -> list[dict]:
    """Merge per-fragment `compat:` front-matter deltas (release-note fragments'
    optional component: version bumps -- see the sibling hub-doc-pr-generator
    skill's SKILL.md step 7) into one row list for the `cut` command's rendered
    table.

    Fragment deltas win over `matrix`'s go.mod-derived value for the same
    component: a fragment was written closer to when the bump actually
    happened, whereas `matrix` reflects go.mod *at the release tag*, which can
    legitimately be stale for a component whose real version isn't tracked in
    go.mod at all (a fragment is often the only source for that). Never drops
    a `matrix` row for a component with no matching delta -- this only adds
    or overrides, it doesn't shrink the table.

    `fragment_deltas` MUST be ordered newest-first (see
    `collect_fragments.for_version`, which is what actually feeds this in
    practice) -- the first delta seen for a given component wins; an older
    fragment's delta for a component a newer fragment already set is ignored.
    Without this, two PRs bumping the same component in one release window
    would let whichever one happens to be processed last silently win
    regardless of recency -- exactly the class of silent cross-PR corruption
    fragments exist to prevent, just relocated into the compat matrix instead
    of the release-note prose (confirmed live: feeding a newest-first list of
    an older v3.7.8 delta after a newer v3.7.10 one previously produced
    v3.7.8 in the output).

    Returns an ordered list of {"component": ..., "version": ..., "note": ...}
    rows: known components first (matrix's fixed order), any delta naming a
    component the matrix doesn't track appended after, in the order first seen.
    """
    rows: dict[str, dict] = {}
    order: list[str] = []

    for key, display in _DISPLAY_NAMES.items():
        value = matrix.get(key)
        if value is None:
            continue
        version, note = (value["version"], value.get("note")) if isinstance(value, dict) else (value, None)
        rows[display] = {"component": display, "version": version, "note": note}
        order.append(display)

    delta_assigned: set[str] = set()
    for delta in fragment_deltas:
        for component, version in delta.get("compat", {}).items():
            if component in delta_assigned:
                continue  # a newer fragment already claimed this component -- ignore the older one
            delta_assigned.add(component)
            if component not in rows:
                order.append(component)
            rows[component] = {"component": component, "version": version, "note": None}

    return [rows[name] for name in order]


def build_matrix(tag: str, *, max_chart_tags: int) -> dict:
    deps = go_mod_deps(tag)
    return {
        "tag": tag,
        "traefik_hub": tag,
        "helm_chart": helm_chart_for(tag, max_chart_tags=max_chart_tags),
        "traefik_proxy": traefik_proxy_version(tag),  # {"version": ..., "note": ... | None}
        "coraza_waf": deps["coraza_waf"],
        "owasp_crs": deps["owasp_crs"],
        "kubernetes_gateway_api": deps["kubernetes_gateway_api"],
        "static_analyzer": static_analyzer_version(),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag", action="append", required=True, dest="tags")
    parser.add_argument("--max-chart-tags", type=int, default=25)
    args = parser.parse_args(argv)
    result = {"tags": [build_matrix(t, max_chart_tags=args.max_chart_tags) for t in args.tags]}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
