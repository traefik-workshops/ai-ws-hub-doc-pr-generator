import re
import tempfile
import unittest
from pathlib import Path
from scripts.assemble_section import assemble, check_fragment_links, render_compat_table

_UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")

EA_FRAGMENT = {
    "shape": "ea-subsection",
    "pr_number": 964,
    "body": (
        "#### Bedrock Mantle\n\n"
        ":::warning Early Access\n"
        "This feature is currently in early access. Available starting v3.21.0-ea.1.\n"
        ":::\n\n"
        "The **Bedrock Mantle** middleware promotes any route to an Anthropic Messages "
        "API endpoint.\n"
    ),
}

GA_BULLET_FRAGMENT = {
    "shape": "ga-bullet",
    "pr_number": 980,
    "body": "- **Hardened Image** is now generally available. See the [Hardened Image](../setup/installation/hardened-image.md) documentation.",
}

COMPAT_ROWS = [
    {"component": "Traefik Hub", "version": "v3.21.0-ea.1", "note": None},
    {"component": "Traefik Proxy", "version": "v3.7.8", "note": None},
    {"component": "Helm Chart", "version": None, "note": "no chart release covers this tag yet"},
]


class TestRenderCompatTable(unittest.TestCase):
    def test_renders_known_and_unknown_rows(self):
        table = render_compat_table(COMPAT_ROWS)
        self.assertIn("<Collapse title=\"Compatibility matrix\">", table)
        self.assertIn("| Traefik Hub | v3.21.0-ea.1 |", table)
        self.assertIn("| Helm Chart | TBD |", table)

    def test_escapes_pipe_in_version_value(self):
        """Regression test: an unescaped '|' in a free-text compat value
        (fragment front matter, not a fixed enum) previously split the row
        into an extra column instead of staying a 2-column row."""
        rows = [{"component": "Traefik Proxy", "version": "v3.7.10 (rc | preview)", "note": None}]
        table = render_compat_table(rows)
        row_line = next(line for line in table.splitlines() if "Traefik Proxy" in line)
        self.assertEqual(len(_UNESCAPED_PIPE_RE.findall(row_line)) - 1, 2)  # exactly 2 real columns
        self.assertIn("rc \\| preview", row_line)

    def test_escapes_pipe_in_component_name(self):
        rows = [{"component": "Weird | Component", "version": "v1.0.0", "note": None}]
        table = render_compat_table(rows)
        row_line = next(line for line in table.splitlines() if "Weird" in line)
        self.assertEqual(len(_UNESCAPED_PIPE_RE.findall(row_line)) - 1, 2)


class TestAssemble(unittest.TestCase):
    def test_ea_version_gets_badge_in_heading(self):
        section = assemble(
            version="v3.21.0-ea.1", date="2026-08-10",
            fragments=[EA_FRAGMENT], compat_rows=COMPAT_ROWS,
        )
        self.assertTrue(section.startswith("## Gateway v3.21.0-ea.1 <EarlyAccessBadge />"))

    def test_ga_version_has_no_badge(self):
        section = assemble(
            version="v3.21.0", date="2026-08-20",
            fragments=[EA_FRAGMENT], compat_rows=COMPAT_ROWS,
        )
        self.assertTrue(section.startswith("## Gateway v3.21.0\n"))

    def test_graduated_to_ga_comes_before_feature_subsections(self):
        section = assemble(
            version="v3.21.0-ea.1", date="2026-08-10",
            fragments=[EA_FRAGMENT, GA_BULLET_FRAGMENT], compat_rows=COMPAT_ROWS,
        )
        ga_idx = section.index("#### Graduated to GA")
        feature_idx = section.index("#### Bedrock Mantle")
        self.assertLess(ga_idx, feature_idx)

    def test_compat_matrix_is_last(self):
        section = assemble(
            version="v3.21.0-ea.1", date="2026-08-10",
            fragments=[EA_FRAGMENT, GA_BULLET_FRAGMENT], compat_rows=COMPAT_ROWS,
        )
        feature_idx = section.index("#### Bedrock Mantle")
        compat_idx = section.index("<Collapse title=\"Compatibility matrix\">")
        self.assertLess(feature_idx, compat_idx)

    def test_preserves_caller_supplied_order_for_feature_subsections(self):
        newer = {**EA_FRAGMENT, "pr_number": 990, "body": "#### Newer Feature\n\nBody.\n"}
        section = assemble(
            version="v3.21.0-ea.1", date="2026-08-10",
            fragments=[newer, EA_FRAGMENT], compat_rows=COMPAT_ROWS,
        )
        self.assertLess(section.index("Newer Feature"), section.index("Bedrock Mantle"))


class TestPlainBulletShape(unittest.TestCase):
    """Regression coverage for traefik-hub#1435 finding #2: no template shape
    existed for a small non-EA/non-GA enhancement (real precedent in
    release-notes.mdx for a plain bullet with no badge/callout)."""

    PLAIN_BULLET_FRAGMENT = {
        "shape": "plain-bullet",
        "pr_number": 1435,
        "body": "- **License expiration metric**: adds a Prometheus gauge for license expiry.",
    }

    def test_plain_bullet_is_not_grouped_under_graduated_to_ga(self):
        section = assemble(
            version="v3.21.0-ea.1", date="2026-08-10",
            fragments=[self.PLAIN_BULLET_FRAGMENT, GA_BULLET_FRAGMENT],
            compat_rows=COMPAT_ROWS,
        )
        ga_heading_idx = section.index("#### Graduated to GA")
        ga_bullet_idx = section.index("Hardened Image")
        plain_idx = section.index("License expiration metric")
        # The real GA bullet is grouped under the heading; the plain-bullet
        # entry appears in the section but is NOT swept into that group.
        self.assertGreater(ga_bullet_idx, ga_heading_idx)
        self.assertNotIn("License expiration metric", section[ga_heading_idx:ga_bullet_idx])


class TestShapeValidation(unittest.TestCase):
    """Regression coverage for cutmode audit finding B: `shape` matching was
    exact/case-sensitive and never validated -- a case-variant or typo'd
    shape (e.g. `GA-bullet`, `ga_bullet`) silently fell into the generic
    'subsections' bucket instead of being grouped correctly or raising, so a
    real GA graduation could silently render as an ungrouped orphan bullet
    with no error anywhere in the pipeline."""

    def test_unrecognized_shape_raises_instead_of_silently_misrendering(self):
        bad_fragment = {
            "shape": "GA-bullet",  # case-variant of the real "ga-bullet"
            "pr_number": 980,
            "body": "- **Hardened Image** is now generally available.",
        }
        with self.assertRaises(ValueError):
            assemble(
                version="v3.21.0-ea.1", date="2026-08-10",
                fragments=[bad_fragment], compat_rows=COMPAT_ROWS,
            )

    def test_every_known_shape_is_accepted(self):
        for shape in ("ea-subsection", "ga-subsection", "ga-bullet", "plain-bullet", "breaking-subsection"):
            fragment = {"shape": shape, "pr_number": 1, "body": "content"}
            assemble(  # must not raise
                version="v3.21.0-ea.1", date="2026-08-10",
                fragments=[fragment], compat_rows=COMPAT_ROWS,
            )


class TestCheckFragmentLinks(unittest.TestCase):
    """Defense-in-depth check for the traefik/hub-doc#988 class of bug: a
    fragment's relative link is written for its post-assembly location (the
    same directory release-notes.mdx lives in), not the fragment's own
    directory one level deeper. These tests resolve against a real temp
    directory tree rather than mocking Path so a genuine filesystem-existence
    check is exercised, matching how the underlying bug actually manifested."""

    def test_flags_link_that_does_not_resolve_post_assembly(self):
        with tempfile.TemporaryDirectory() as td:
            docs_dir = Path(td)
            fragment = {
                "filename": "_1234-broken-link.mdx",
                "body": "See the [Foo](../ai-gateway/guides/foo.md) documentation.",
            }
            findings = check_fragment_links([fragment], docs_dir)
        self.assertEqual(len(findings), 1)
        self.assertIn("_1234-broken-link.mdx", findings[0])
        self.assertIn("../ai-gateway/guides/foo.md", findings[0])

    def test_does_not_flag_link_that_resolves_post_assembly(self):
        with tempfile.TemporaryDirectory() as td:
            # docs_dir stands in for docs/api-gateway/ (where release-notes.mdx
            # lives); ai-gateway/ is its sibling under docs/, one level up --
            # matching a real cross-gateway link like the Bedrock Mantle one.
            docs_dir = Path(td) / "docs" / "api-gateway"
            docs_dir.mkdir(parents=True)
            target = Path(td) / "docs" / "ai-gateway" / "middlewares" / "bedrock-mantle.md"
            target.parent.mkdir(parents=True)
            target.write_text("# Bedrock Mantle\n")
            fragment = {
                "filename": "_964-bedrock-mantle.mdx",
                "body": "See the [Bedrock Mantle](../ai-gateway/middlewares/bedrock-mantle.md) documentation.",
            }
            findings = check_fragment_links([fragment], docs_dir)
        self.assertEqual(findings, [])

    def test_ignores_anchor_only_and_absolute_and_external_links(self):
        with tempfile.TemporaryDirectory() as td:
            docs_dir = Path(td)
            fragment = {
                "filename": "_970-messages-api.mdx",
                "body": (
                    "See [above](#above), the [site root](/traefik-hub/api-gateway/x.md), "
                    "and [external](https://example.com/docs) for more."
                ),
            }
            findings = check_fragment_links([fragment], docs_dir)
        self.assertEqual(findings, [])

    def test_flags_by_filename_across_multiple_fragments(self):
        with tempfile.TemporaryDirectory() as td:
            docs_dir = Path(td)
            good = {
                "filename": "_964-good.mdx",
                "body": "",
            }
            bad = {
                "filename": "_980-bad.mdx",
                "body": "[missing](../nowhere/missing.md)",
            }
            findings = check_fragment_links([good, bad], docs_dir)
        self.assertEqual(len(findings), 1)
        self.assertIn("_980-bad.mdx", findings[0])

    def test_checks_link_with_anchor_against_path_only(self):
        with tempfile.TemporaryDirectory() as td:
            docs_dir = Path(td)
            target = docs_dir / "reference" / "metrics.md"
            target.parent.mkdir(parents=True)
            target.write_text("# Metrics\n")
            fragment = {
                "filename": "_1435-metric.mdx",
                "body": "See the [Global Metrics](reference/metrics.md#global-metrics) table.",
            }
            findings = check_fragment_links([fragment], docs_dir)
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
