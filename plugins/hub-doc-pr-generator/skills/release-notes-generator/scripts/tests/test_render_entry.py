import unittest
from scripts.render_entry import splice


class TestSplice(unittest.TestCase):
    def test_inserts_above_first_gateway_heading(self):
        existing = (
            "---\nid: release-notes\n---\n\n"
            "## Gateway v3.20.6 & v3.19.11\n\n**2026-07-01**\n\n### Bug fixes\n\n- old fix\n"
        )
        entry = "## Gateway v3.20.7\n\n**2026-08-01**\n\n### Bug fixes\n\n- new fix\n"
        result = splice(existing, entry)
        # New entry appears before the old heading.
        self.assertLess(result.index("v3.20.7"), result.index("v3.20.6 & v3.19.11"))

    def test_preserves_preamble_before_first_heading(self):
        existing = (
            "---\nid: release-notes\n---\n\nimport Collapse from '@site/src/components/Collapse';\n\n"
            "## Gateway v3.20.6\n\nold content\n"
        )
        entry = "## Gateway v3.20.7\n\nnew content\n"
        result = splice(existing, entry)
        self.assertIn("import Collapse", result)
        self.assertLess(result.index("import Collapse"), result.index("v3.20.7"))

    def test_never_inserts_inside_earlier_releases_archive(self):
        # The archive collapses old months behind literal <h2> tags, not "##
        # Gateway v..." headings, so the regex must not match inside it.
        existing = (
            "## Gateway v3.20.6\n\nrecent\n\n"
            "## Earlier releases\n\n<Collapse title=\"2025 and earlier\">\n\n"
            "<h2 id=\"november-2025\">November 2025</h2>\n\ncontent\n\n</Collapse>\n"
        )
        entry = "## Gateway v3.20.7\n\nnewest\n"
        result = splice(existing, entry)
        self.assertLess(result.index("v3.20.7"), result.index("v3.20.6"))
        self.assertLess(result.index("v3.20.6"), result.index("Earlier releases"))

    def test_raises_when_no_gateway_heading_found(self):
        existing = "---\nid: release-notes\n---\n\nsomehow empty or malformed\n"
        with self.assertRaises(ValueError):
            splice(existing, "## Gateway v3.20.7\n\nnew\n")

    def test_entry_gets_exactly_one_blank_line_separator(self):
        existing = "preamble\n\n## Gateway v3.20.6\n\nold\n"
        entry = "## Gateway v3.20.7\n\nnew\n\n\n"  # trailing blank lines in the entry itself
        result = splice(existing, entry)
        self.assertIn("new\n\n## Gateway v3.20.6", result)

    def test_resplicing_the_same_version_replaces_instead_of_duplicating(self):
        """Regression test: re-running `cut` against a version that's still
        open (a straggler fragment lands after an earlier cut) must replace
        that version's section, not add a second heading for it."""
        existing = "preamble\n\n## Gateway v3.20.6\n\nold\n"
        entry_v1 = "## Gateway v3.21.0-ea.1\n\n**2026-08-10**\n\n#### Bedrock Mantle\n"
        entry_v2 = "## Gateway v3.21.0-ea.1\n\n**2026-08-11**\n\n#### Bedrock Mantle\n\n#### Messages API\n"
        once = splice(existing, entry_v1)
        twice = splice(once, entry_v2)
        self.assertEqual(twice.count("## Gateway v3.21.0-ea.1"), 1)
        self.assertIn("Messages API", twice)
        self.assertIn("## Gateway v3.20.6", twice)  # untouched sibling section

    def test_resplice_tolerates_badge_spacing_drift(self):
        """Regression test: a byte-exact single-space match previously missed
        a heading with different spacing before the badge (hand edit, or a
        legacy formatting variant) and silently fell through to the default
        insert-above-first path, duplicating the heading -- the same bug this
        function exists to prevent, just reopened via a narrower trigger."""
        existing = "## Gateway v3.21.0-ea.1  <EarlyAccessBadge />\n\n**2026-08-10**\n\nold\n"  # two spaces
        entry = "## Gateway v3.21.0-ea.1 <EarlyAccessBadge />\n\n**2026-08-11**\n\nnew\n"  # one space
        result = splice(existing, entry)
        self.assertEqual(result.count("## Gateway v3.21.0-ea.1"), 1)
        self.assertIn("new", result)
        self.assertNotIn("old", result)

    def test_resplice_preserves_ea_badge_in_heading(self):
        existing = "preamble\n\n## Gateway v3.21.0-ea.1 <EarlyAccessBadge />\n\n**2026-08-10**\n\nold\n"
        entry = "## Gateway v3.21.0-ea.1 <EarlyAccessBadge />\n\n**2026-08-11**\n\nnew\n"
        result = splice(existing, entry)
        self.assertEqual(result.count("## Gateway v3.21.0-ea.1"), 1)
        self.assertIn("new", result)
        self.assertNotIn("old", result)

    def test_resplice_stops_at_earlier_releases_boundary(self):
        """The replaced section's end must never swallow the archive below it."""
        existing = (
            "## Gateway v3.21.0-ea.1\n\nold\n\n"
            "## Earlier releases\n\n<Collapse title=\"2025 and earlier\">\n\ncontent\n\n</Collapse>\n"
        )
        entry = "## Gateway v3.21.0-ea.1\n\nnew\n"
        result = splice(existing, entry)
        self.assertEqual(result.count("## Gateway v3.21.0-ea.1"), 1)
        self.assertIn("Earlier releases", result)
        self.assertIn("2025 and earlier", result)

    def test_resplice_stops_at_next_sibling_version_heading(self):
        existing = "## Gateway v3.21.0-ea.1\n\nold\n\n## Gateway v3.20.6\n\nsibling\n"
        entry = "## Gateway v3.21.0-ea.1\n\nnew\n"
        result = splice(existing, entry)
        self.assertEqual(result.count("## Gateway v3.21.0-ea.1"), 1)
        self.assertIn("## Gateway v3.20.6", result)
        self.assertIn("sibling", result)

    def test_different_version_still_inserts_above_first_heading(self):
        """Sanity check: the new idempotency logic must not change behavior
        for the ordinary brand-new-version case."""
        existing = "## Gateway v3.20.6\n\nold\n"
        entry = "## Gateway v3.20.7\n\nnew\n"
        result = splice(existing, entry)
        self.assertLess(result.index("v3.20.7"), result.index("v3.20.6"))
        self.assertIn("old", result)

    def test_combined_heading_falls_back_to_default_insert(self):
        """A hub-doc-team-curated combined heading (e.g. two patch tags sharing
        one section) is never generated by this pipeline itself, so it's
        correct for the exact-version match to miss and fall back to
        inserting above the first heading, not an idempotency gap."""
        existing = "## Gateway v3.20.6 & v3.19.11\n\n**2026-07-01**\n\nold\n"
        entry = "## Gateway v3.20.6\n\nnew\n"
        result = splice(existing, entry)
        self.assertLess(result.index("v3.20.6\n"), result.index("v3.20.6 & v3.19.11"))
        self.assertIn("old", result)


if __name__ == "__main__":
    unittest.main()
