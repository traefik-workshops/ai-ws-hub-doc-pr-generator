import unittest
from unittest.mock import patch
from scripts import compat_matrix
from scripts.compat_matrix import (
    go_mod_deps, traefik_proxy_version, helm_chart_for, static_analyzer_version,
    mcp_specification_version, build_matrix, merge_fragment_deltas,
)

# Real snippets (trimmed) verified live against traefik/traefik-hub@main and
# traefik/traefik-helm-chart@v41.1.0 while reviewing this skill.
GO_MOD_SNIPPET = """
module github.com/traefik/traefik-hub/v3

go 1.26.0

require (
\tgithub.com/corazawaf/coraza-coreruleset/v4 v4.25.0
\tgithub.com/corazawaf/coraza/v3 v3.7.0
\tgithub.com/modelcontextprotocol/go-sdk v1.4.1
\tgithub.com/traefik/traefik/v3 v3.7.10-0.20260730153609-e80aaab074b4
\tsigs.k8s.io/gateway-api v1.6.1
)

replace github.com/corazawaf/coraza/v3 => github.com/traefik/coraza/v3 v3.0.0-20260603201638-0ab7cb557911
"""

CHART_YAML_SNIPPET = """
apiVersion: v2
name: traefik
version: 41.1.0
annotations:
  traefik.io/hub-min-version: v3.19.3
  traefik.io/hub-max-version: v3.20.7
"""

# Trimmed real snippet, verified live against modelcontextprotocol/go-sdk@v1.4.1's
# mcp/shared.go.
MCP_SDK_SHARED_GO_SNIPPET = """
const (
\t// latestProtocolVersion is the latest protocol version that this version of
\t// the SDK supports.
\tlatestProtocolVersion   = protocolVersion20250618
\tprotocolVersion20251125 = "2025-11-25" // not yet released
\tprotocolVersion20250618 = "2025-06-18"
\tprotocolVersion20250326 = "2025-03-26"
)
"""


class TestGoModDeps(unittest.TestCase):
    def test_extracts_real_dependency_lines(self):
        with patch("scripts.compat_matrix._file_at_ref", return_value=GO_MOD_SNIPPET):
            deps = go_mod_deps("v3.20.8")
        self.assertEqual(deps["coraza_waf"], "v3.7.0")
        self.assertEqual(deps["owasp_crs"], "v4.25.0")
        self.assertEqual(deps["kubernetes_gateway_api"], "v1.6.1")

    def test_replace_directive_does_not_shadow_require_line(self):
        # The replace directive also contains "github.com/corazawaf/coraza/v3"
        # followed by "=>", not a version — must not be mistaken for a match.
        with patch("scripts.compat_matrix._file_at_ref", return_value=GO_MOD_SNIPPET):
            deps = go_mod_deps("v3.20.8")
        self.assertEqual(deps["coraza_waf"], "v3.7.0")

    def test_missing_go_mod_returns_all_none(self):
        with patch("scripts.compat_matrix._file_at_ref", return_value=None):
            deps = go_mod_deps("v3.20.8")
        self.assertEqual(deps, {"coraza_waf": None, "owasp_crs": None, "kubernetes_gateway_api": None})


class TestTraefikProxyVersion(unittest.TestCase):
    def test_extracts_pseudo_version_prefix(self):
        with patch("scripts.compat_matrix._file_at_ref",
                   side_effect=lambda repo, path, ref: GO_MOD_SNIPPET if "go.mod" in path else "v3.7.9\n"):
            result = traefik_proxy_version("v3.20.8")
        self.assertEqual(result["version"], "v3.7.10")

    def test_notes_disagreement_between_go_mod_and_version_file(self):
        with patch("scripts.compat_matrix._file_at_ref",
                   side_effect=lambda repo, path, ref: GO_MOD_SNIPPET if "go.mod" in path else "v3.7.9\n"):
            result = traefik_proxy_version("v3.20.8")
        self.assertIsNotNone(result["note"])
        self.assertIn("disagree", result["note"])

    def test_no_note_when_sources_agree(self):
        with patch("scripts.compat_matrix._file_at_ref",
                   side_effect=lambda repo, path, ref: GO_MOD_SNIPPET if "go.mod" in path else "v3.7.10\n"):
            result = traefik_proxy_version("v3.20.8")
        self.assertIsNone(result["note"])

    def test_falls_back_to_version_file_when_go_mod_has_no_traefik_pin(self):
        no_traefik = "module x\n\nrequire (\n\tsigs.k8s.io/gateway-api v1.6.1\n)\n"
        with patch("scripts.compat_matrix._file_at_ref",
                   side_effect=lambda repo, path, ref: no_traefik if "go.mod" in path else "v3.7.9\n"):
            result = traefik_proxy_version("v3.20.8")
        self.assertEqual(result["version"], "v3.7.9")
        self.assertIn("fell back", result["note"])

    def test_returns_none_with_note_when_neither_source_available(self):
        with patch("scripts.compat_matrix._file_at_ref", return_value=None):
            result = traefik_proxy_version("v3.20.8")
        self.assertIsNone(result["version"])
        self.assertIsNotNone(result["note"])


class TestHelmChartFor(unittest.TestCase):
    def test_finds_chart_bracketing_target_tag(self):
        with patch("scripts.compat_matrix._chart_tag_names", return_value=["v41.1.0"]), \
             patch("scripts.compat_matrix._file_at_ref", return_value=CHART_YAML_SNIPPET):
            result = helm_chart_for("v3.20.7", max_chart_tags=25)
        self.assertEqual(result["version"], "41.1.0")
        self.assertIn("v41.1.0", result["note"])

    def test_target_outside_bracket_range_is_skipped(self):
        with patch("scripts.compat_matrix._chart_tag_names", return_value=["v41.1.0"]), \
             patch("scripts.compat_matrix._file_at_ref", return_value=CHART_YAML_SNIPPET):
            result = helm_chart_for("v3.21.0", max_chart_tags=25)
        self.assertIsNone(result["version"])
        self.assertIn("no chart release", result["note"])

    def test_unparseable_target_tag_returns_none(self):
        result = helm_chart_for("not-a-tag", max_chart_tags=25)
        self.assertIsNone(result["version"])

    def test_chart_missing_annotations_is_skipped(self):
        no_annotations = "apiVersion: v2\nname: traefik\nversion: 40.0.0\n"
        with patch("scripts.compat_matrix._chart_tag_names", return_value=["v40.0.0"]), \
             patch("scripts.compat_matrix._file_at_ref", return_value=no_annotations):
            result = helm_chart_for("v3.20.7", max_chart_tags=25)
        self.assertIsNone(result["version"])


class TestAnalyzerReleases(unittest.TestCase):
    """`_analyzer_releases` itself, independent of the tag-date filtering
    `static_analyzer_version` layers on top."""

    def test_sorts_explicitly_rather_than_trusting_api_order(self):
        # Deliberately out of chronological order -- the API's ordering
        # (creation time) isn't guaranteed to match published_at.
        raw = "v1.9.3\t2026-08-12T08:31:30Z\nv1.9.4\t2026-08-19T08:00:48Z\n"
        with patch("scripts.compat_matrix._gh.run_text", return_value=raw):
            releases = compat_matrix._analyzer_releases(max_releases=25)
        self.assertEqual([r[0] for r in releases], ["v1.9.4", "v1.9.3"])

    def test_draft_release_with_no_published_at_is_dropped(self):
        # A draft release reports published_at as null -- empty string over
        # this TSV encoding. Left in, it would sort as "before everything"
        # and could be picked as if it predated every real tag date.
        raw = "v1.9.5\t\nv1.9.4\t2026-08-19T08:00:48Z\n"
        with patch("scripts.compat_matrix._gh.run_text", return_value=raw):
            releases = compat_matrix._analyzer_releases(max_releases=25)
        self.assertEqual([r[0] for r in releases], ["v1.9.4"])


class TestStaticAnalyzerVersion(unittest.TestCase):
    def test_picks_newest_release_at_or_before_hub_tag_date(self):
        releases = [
            ("v1.9.4", "2026-08-19T08:00:48Z"),  # newest, predates the tag date -- should win
            ("v1.9.3", "2026-08-12T08:31:30Z"),
        ]
        with patch("scripts.compat_matrix._hub_tag_date", return_value="2026-08-26T09:04:13Z"), \
             patch("scripts.compat_matrix._analyzer_releases", return_value=releases):
            result = static_analyzer_version("v3.20.12")
        self.assertEqual(result["version"], "v1.9.4")
        self.assertIn("v3.20.12", result["note"])

    def test_release_published_after_hub_tag_date_is_skipped(self):
        releases = [
            ("v1.9.5", "2026-09-01T00:00:00Z"),  # published after the tag -- must not be picked
            ("v1.9.4", "2026-08-19T08:00:48Z"),
        ]
        with patch("scripts.compat_matrix._hub_tag_date", return_value="2026-08-26T09:04:13Z"), \
             patch("scripts.compat_matrix._analyzer_releases", return_value=releases):
            result = static_analyzer_version("v3.20.12")
        self.assertEqual(result["version"], "v1.9.4")

    def test_no_release_predating_tag_returns_null_with_note(self):
        releases = [("v1.9.5", "2026-09-01T00:00:00Z")]
        with patch("scripts.compat_matrix._hub_tag_date", return_value="2026-08-26T09:04:13Z"), \
             patch("scripts.compat_matrix._analyzer_releases", return_value=releases):
            result = static_analyzer_version("v3.20.12")
        self.assertIsNone(result["version"])
        self.assertIn("no traefik/hub-static-analyzer release", result["note"])

    def test_unresolvable_hub_tag_date_returns_null_with_note(self):
        with patch("scripts.compat_matrix._hub_tag_date", return_value=None):
            result = static_analyzer_version("v3.20.12")
        self.assertIsNone(result["version"])
        self.assertIn("commit date", result["note"])


class TestMcpSpecificationVersion(unittest.TestCase):
    def test_resolves_latest_protocol_version_from_pinned_sdk(self):
        with patch("scripts.compat_matrix._file_at_ref",
                   side_effect=lambda repo, path, ref: (
                       GO_MOD_SNIPPET if "go.mod" in path else MCP_SDK_SHARED_GO_SNIPPET
                   )):
            result = mcp_specification_version("v3.20.13")
        self.assertEqual(result["version"], "2025-06-18")
        self.assertIn("v1.4.1", result["note"])

    def test_does_not_pick_the_unreleased_sibling_constant(self):
        """Regression guard for the exact hub-doc#1000 mistake: the SDK's
        mcp/shared.go defines a second protocolVersion constant right next to
        the aliased one, explicitly marked 'not yet released'. Only the one
        latestProtocolVersion actually aliases may be returned."""
        with patch("scripts.compat_matrix._file_at_ref",
                   side_effect=lambda repo, path, ref: (
                       GO_MOD_SNIPPET if "go.mod" in path else MCP_SDK_SHARED_GO_SNIPPET
                   )):
            result = mcp_specification_version("v3.20.13")
        self.assertNotEqual(result["version"], "2025-11-25")

    def test_missing_go_sdk_pin_returns_null_with_note(self):
        no_sdk = "module x\n\nrequire (\n\tsigs.k8s.io/gateway-api v1.6.1\n)\n"
        with patch("scripts.compat_matrix._file_at_ref", return_value=no_sdk):
            result = mcp_specification_version("v3.20.13")
        self.assertIsNone(result["version"])
        self.assertIn("not found in go.mod", result["note"])

    def test_unreachable_sdk_source_returns_null_with_note(self):
        with patch("scripts.compat_matrix._file_at_ref",
                   side_effect=lambda repo, path, ref: GO_MOD_SNIPPET if "go.mod" in path else None):
            result = mcp_specification_version("v3.20.13")
        self.assertIsNone(result["version"])
        self.assertIn("could not read", result["note"])

    def test_sdk_source_missing_the_constant_returns_null_with_note(self):
        with patch("scripts.compat_matrix._file_at_ref",
                   side_effect=lambda repo, path, ref: GO_MOD_SNIPPET if "go.mod" in path else "package mcp\n"):
            result = mcp_specification_version("v3.20.13")
        self.assertIsNone(result["version"])
        self.assertIn("no latestProtocolVersion constant", result["note"])

    def test_alias_with_unresolvable_string_value_returns_null_with_note(self):
        """latestProtocolVersion aliases a name, but that alias's own string
        constant is nowhere in the file -- e.g. the SDK moved to computing it
        instead of a literal, or the alias is misspelled. Distinct from the
        'no latestProtocolVersion constant at all' case above: here the alias
        itself resolves, only the second lookup fails."""
        orphan_alias_snippet = """
const (
\tlatestProtocolVersion = protocolVersionUnresolved
\tprotocolVersion20250618 = "2025-06-18"
)
"""
        with patch("scripts.compat_matrix._file_at_ref",
                   side_effect=lambda repo, path, ref: GO_MOD_SNIPPET if "go.mod" in path else orphan_alias_snippet):
            result = mcp_specification_version("v3.20.13")
        self.assertIsNone(result["version"])
        self.assertIn("couldn't be resolved", result["note"])

    def test_alias_name_is_not_matched_as_a_substring_of_a_longer_identifier(self):
        """Regression guard for suggestion #3 in the PR #34 review: the alias
        lookup must not match a longer identifier that merely contains the
        alias name as a substring (e.g. a differently-scoped constant that
        happens to share a suffix). Word-boundary anchoring must win here."""
        shadowed_snippet = """
const (
\tlatestProtocolVersion = protocolVersion20250618
\txprotocolVersion20250618 = "1999-01-01" // decoy: alias name is a literal substring of this identifier, appears first
\tprotocolVersion20250618 = "2025-06-18"
)
"""
        with patch("scripts.compat_matrix._file_at_ref",
                   side_effect=lambda repo, path, ref: GO_MOD_SNIPPET if "go.mod" in path else shadowed_snippet):
            result = mcp_specification_version("v3.20.13")
        self.assertEqual(result["version"], "2025-06-18")


class TestBuildMatrix(unittest.TestCase):
    def test_assembles_all_rows(self):
        with patch("scripts.compat_matrix._file_at_ref",
                   side_effect=lambda repo, path, ref: (
                       GO_MOD_SNIPPET if "go.mod" in path else
                       "v3.7.10\n" if "traefik.version" in path else
                       MCP_SDK_SHARED_GO_SNIPPET if "shared.go" in path else
                       CHART_YAML_SNIPPET
                   )), \
             patch("scripts.compat_matrix._chart_tag_names", return_value=["v41.1.0"]), \
             patch("scripts.compat_matrix._hub_tag_date", return_value="2026-08-26T09:04:13Z"), \
             patch("scripts.compat_matrix._analyzer_releases",
                   return_value=[("v1.9.4", "2026-08-19T08:00:48Z")]):
            matrix = build_matrix("v3.20.8", max_chart_tags=25)
        self.assertEqual(matrix["tag"], "v3.20.8")
        self.assertEqual(matrix["traefik_hub"], "v3.20.8")
        self.assertEqual(matrix["coraza_waf"], "v3.7.0")
        self.assertEqual(matrix["static_analyzer"]["version"], "v1.9.4")
        self.assertEqual(matrix["mcp_specification"]["version"], "2025-06-18")


SAMPLE_MATRIX = {
    "tag": "v3.21.0-ea.1",
    "traefik_hub": "v3.21.0-ea.1",
    "helm_chart": {"version": None, "note": "no chart release covers this tag yet"},
    "traefik_proxy": {"version": "v3.7.9", "note": None},
    "coraza_waf": "v3.7.0",
    "owasp_crs": "v4.25.0",
    "kubernetes_gateway_api": "v1.6.1",
    "static_analyzer": {"version": None, "note": "pin location not yet identified"},
    "mcp_specification": {"version": None, "note": "no supported revision is declared"},
}


SAMPLE_MATRIX_WITH_UNMATCHED_DEP = {**SAMPLE_MATRIX, "kubernetes_gateway_api": None}


class TestMergeFragmentDeltas(unittest.TestCase):
    def test_go_mod_dep_with_no_regex_match_renders_as_tbd_not_dropped(self):
        """Regression test: a go.mod-derived component (coraza_waf/owasp_crs/
        kubernetes_gateway_api) whose regex doesn't match at a given tag comes
        back as a bare `None` (not a dict), unlike helm_chart/traefik_proxy/
        static_analyzer which are always dict-shaped even when unknown.
        Checking `value is None` to decide whether to skip the row -- instead
        of checking whether the matrix even has the key -- silently dropped
        that component from the published compat table entirely instead of
        rendering it as `TBD` like every other unknown value."""
        rows = merge_fragment_deltas(SAMPLE_MATRIX_WITH_UNMATCHED_DEP, [])
        components = [r["component"] for r in rows]
        self.assertIn("Kubernetes Gateway API", components)
        by_component = {r["component"]: r["version"] for r in rows}
        self.assertIsNone(by_component["Kubernetes Gateway API"])

    def test_case_variant_component_name_overrides_instead_of_duplicating(self):
        """Regression test: previously an uncanonicalized 'traefik proxy'
        delta produced BOTH 'Traefik Proxy' and 'traefik proxy' as separate
        rows instead of overriding the canonical one."""
        deltas = [{"compat": {"traefik proxy": "v3.7.10"}}]
        rows = merge_fragment_deltas(SAMPLE_MATRIX, deltas)
        components = [r["component"] for r in rows]
        self.assertEqual(components.count("Traefik Proxy"), 1)
        self.assertNotIn("traefik proxy", components)
        by_component = {r["component"]: r["version"] for r in rows}
        self.assertEqual(by_component["Traefik Proxy"], "v3.7.10")

    def test_whitespace_variant_component_name_is_canonicalized(self):
        deltas = [{"compat": {"  Traefik Proxy  ": "v3.7.10"}}]
        rows = merge_fragment_deltas(SAMPLE_MATRIX, deltas)
        components = [r["component"] for r in rows]
        self.assertEqual(components.count("Traefik Proxy"), 1)

    def test_unknown_component_keeps_original_spelling(self):
        """No canonical form exists for a component the matrix doesn't track,
        so its spelling is preserved as-is rather than forced to some form."""
        deltas = [{"compat": {"Envoy Gateway": "v1.30.0"}}]
        rows = merge_fragment_deltas(SAMPLE_MATRIX, deltas)
        self.assertEqual(rows[-1]["component"], "Envoy Gateway")

    def test_case_variant_of_unknown_component_is_canonicalized_too(self):
        """Regression test: canonicalization previously only covered the
        static _DISPLAY_NAMES set -- two fragments naming a brand-new
        component with different casing (newest-first: 'Envoy Gateway' then
        older 'envoy gateway') previously produced two separate rows instead
        of the newest fragment's spelling winning, same bug class as the
        known-component case fixed earlier."""
        deltas_newest_first = [
            {"compat": {"Envoy Gateway": "v1.31.0"}},   # newer fragment, sets the canonical spelling
            {"compat": {"envoy gateway": "v1.30.0"}},   # older fragment, case variant
        ]
        rows = merge_fragment_deltas(SAMPLE_MATRIX, deltas_newest_first)
        components = [r["component"] for r in rows]
        self.assertEqual(components.count("Envoy Gateway"), 1)
        self.assertNotIn("envoy gateway", components)
        by_component = {r["component"]: r["version"] for r in rows}
        self.assertEqual(by_component["Envoy Gateway"], "v1.31.0")

    def test_no_deltas_returns_matrix_as_is(self):
        rows = merge_fragment_deltas(SAMPLE_MATRIX, [])
        by_component = {r["component"]: r["version"] for r in rows}
        self.assertEqual(by_component["Traefik Proxy"], "v3.7.9")
        self.assertEqual(by_component["Helm Chart"], None)

    def test_fragment_delta_overrides_matrix_value(self):
        deltas = [{"compat": {"Traefik Proxy": "v3.7.10"}}]
        rows = merge_fragment_deltas(SAMPLE_MATRIX, deltas)
        by_component = {r["component"]: r["version"] for r in rows}
        self.assertEqual(by_component["Traefik Proxy"], "v3.7.10")

    def test_fragment_delta_override_preserves_matrix_row_note(self):
        """Regression test for cutmode audit finding D: overriding a matrix
        row's version with a fragment delta previously always set that row's
        note to None, silently dropping a real matrix-derived caveat -- e.g.
        traefik_proxy_version()'s note flagging a go.mod/traefik.version
        mismatch, which is exactly the case this note exists to surface.
        A fragment delta has no way to carry its own note (the compat:
        front-matter block is just component: version pairs), so overriding
        a row's version must carry the existing note forward, not blank it."""
        matrix_with_note = {
            **SAMPLE_MATRIX,
            "traefik_proxy": {
                "version": "v3.7.9",
                "note": "go.mod pins v3.7.9; hub/pkg/version/traefik.version reads v3.7.8 -- these disagree",
            },
        }
        deltas = [{"compat": {"Traefik Proxy": "v3.7.10"}}]
        rows = merge_fragment_deltas(matrix_with_note, deltas)
        by_component = {r["component"]: r for r in rows}
        self.assertEqual(by_component["Traefik Proxy"]["version"], "v3.7.10")
        self.assertIn("disagree", by_component["Traefik Proxy"]["note"])

    def test_fragment_delta_for_unknown_component_is_appended(self):
        deltas = [{"compat": {"Envoy": "v1.30.0"}}]
        rows = merge_fragment_deltas(SAMPLE_MATRIX, deltas)
        self.assertEqual(rows[-1], {"component": "Envoy", "version": "v1.30.0", "note": None})

    def test_newest_first_delta_wins_over_older_duplicate(self):
        """Regression test: fragment_deltas must be fed newest-first (the real
        caller is collect_fragments.for_version, which orders that way), and the
        FIRST delta seen per component must win -- an older duplicate must never
        override a newer one. Previously this silently let whichever delta was
        processed *last* win regardless of recency: fed exactly this newest-first
        order, it returned the older v3.7.8 instead of the newer v3.7.10."""
        deltas_newest_first = [
            {"compat": {"Traefik Proxy": "v3.7.10"}},  # newer PR, correct bump
            {"compat": {"Traefik Proxy": "v3.7.8"}},   # older PR, stale duplicate
        ]
        rows = merge_fragment_deltas(SAMPLE_MATRIX, deltas_newest_first)
        by_component = {r["component"]: r["version"] for r in rows}
        self.assertEqual(by_component["Traefik Proxy"], "v3.7.10")

    def test_row_order_is_matrix_order_then_new_components(self):
        deltas = [{"compat": {"Envoy": "v1.30.0"}}]
        rows = merge_fragment_deltas(SAMPLE_MATRIX, deltas)
        components = [r["component"] for r in rows]
        self.assertEqual(
            components,
            ["Traefik Hub", "Helm Chart", "Traefik Proxy", "Coraza WAF",
             "OWASP CRS", "Static Analyzer", "Kubernetes Gateway API",
             "MCP specification", "Envoy"],
        )


if __name__ == "__main__":
    unittest.main()
