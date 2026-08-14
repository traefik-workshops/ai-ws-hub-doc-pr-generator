import unittest
from unittest.mock import patch
from scripts.compat_matrix import (
    go_mod_deps, traefik_proxy_version, helm_chart_for, static_analyzer_version, build_matrix,
    merge_fragment_deltas,
)

# Real snippets (trimmed) verified live against traefik/traefik-hub@main and
# traefik/traefik-helm-chart@v41.1.0 while reviewing this skill.
GO_MOD_SNIPPET = """
module github.com/traefik/traefik-hub/v3

go 1.26.0

require (
\tgithub.com/corazawaf/coraza-coreruleset/v4 v4.25.0
\tgithub.com/corazawaf/coraza/v3 v3.7.0
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


class TestStaticAnalyzerVersion(unittest.TestCase):
    def test_always_returns_null_with_explanatory_note(self):
        result = static_analyzer_version()
        self.assertIsNone(result["version"])
        self.assertIn("not yet identified", result["note"])


class TestBuildMatrix(unittest.TestCase):
    def test_assembles_all_rows(self):
        with patch("scripts.compat_matrix._file_at_ref",
                   side_effect=lambda repo, path, ref: (
                       GO_MOD_SNIPPET if "go.mod" in path else
                       "v3.7.10\n" if "traefik.version" in path else
                       CHART_YAML_SNIPPET
                   )), \
             patch("scripts.compat_matrix._chart_tag_names", return_value=["v41.1.0"]):
            matrix = build_matrix("v3.20.8", max_chart_tags=25)
        self.assertEqual(matrix["tag"], "v3.20.8")
        self.assertEqual(matrix["traefik_hub"], "v3.20.8")
        self.assertEqual(matrix["coraza_waf"], "v3.7.0")
        self.assertIsNone(matrix["static_analyzer"]["version"])


SAMPLE_MATRIX = {
    "tag": "v3.21.0-ea.1",
    "traefik_hub": "v3.21.0-ea.1",
    "helm_chart": {"version": None, "note": "no chart release covers this tag yet"},
    "traefik_proxy": {"version": "v3.7.9", "note": None},
    "coraza_waf": "v3.7.0",
    "owasp_crs": "v4.25.0",
    "kubernetes_gateway_api": "v1.6.1",
    "static_analyzer": {"version": None, "note": "pin location not yet identified"},
}


class TestMergeFragmentDeltas(unittest.TestCase):
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
             "OWASP CRS", "Static Analyzer", "Kubernetes Gateway API", "Envoy"],
        )


if __name__ == "__main__":
    unittest.main()
