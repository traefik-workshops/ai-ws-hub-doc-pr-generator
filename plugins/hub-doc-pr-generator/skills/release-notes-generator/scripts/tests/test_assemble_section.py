import unittest
from scripts.assemble_section import assemble, render_compat_table

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


if __name__ == "__main__":
    unittest.main()
