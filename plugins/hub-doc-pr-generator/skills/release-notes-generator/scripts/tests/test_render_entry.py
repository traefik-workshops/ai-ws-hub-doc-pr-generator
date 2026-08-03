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


if __name__ == "__main__":
    unittest.main()
