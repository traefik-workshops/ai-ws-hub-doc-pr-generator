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

    def test_resplice_tolerates_version_casing_drift(self):
        """Regression test: a re-cut of the same release invoked with
        different casing in the `<version>` argument (`v3.21.0-EA.1` vs
        `v3.21.0-ea.1`) previously failed the exact-case heading match,
        fell through to the default insert-above-first path, and produced
        two headings for what's logically one release -- same failure class
        as the badge-spacing-drift bug above, just a different trigger.
        collect_fragments.for_version() already matches version strings
        case-insensitively; this brings the heading match in line with it."""
        existing = "## Gateway v3.21.0-EA.1 <EarlyAccessBadge />\n\n**2026-08-10**\n\nold\n"
        entry = "## Gateway v3.21.0-ea.1 <EarlyAccessBadge />\n\n**2026-08-12**\n\nnew\n"
        result = splice(existing, entry)
        self.assertEqual(result.lower().count("## gateway v3.21.0-ea.1"), 1)
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

    def test_bare_version_entry_never_replaces_a_combined_heading(self):
        """Safety-critical, not just a fallback nicety: a bare single-version
        entry ("## Gateway v3.20.6") must never match a DIFFERENT identity
        like a hub-doc-team-curated combined heading ("## Gateway v3.20.6 &
        v3.19.11") just because it shares a leading version -- regression
        test for a bug introduced and caught in the same review round: an
        earlier fix that matched on a bare version PREFIX (rather than the
        full heading identity) let this exact case match and replace the
        combined section, silently destroying v3.19.11's content. Falling
        back to insert-above-first is correct here, not an idempotency gap."""
        existing = "## Gateway v3.20.6 & v3.19.11\n\n**2026-07-01**\n\nold\n"
        entry = "## Gateway v3.20.6\n\nnew\n"
        result = splice(existing, entry)
        self.assertLess(result.index("v3.20.6\n"), result.index("v3.20.6 & v3.19.11"))
        self.assertIn("old", result)
        self.assertIn("v3.20.6 & v3.19.11", result)

    def test_resplicing_the_same_combined_heading_replaces_instead_of_duplicating(self):
        """The actual fix: tag mode's edit-loop re-prompt path regenerates a
        combined entry and re-splices it against a file that already has that
        SAME combined heading from an earlier splice attempt -- this must
        replace, not duplicate. Previously this fell through to the default
        insert-above-first path because the old matching only recognized a
        bare version, never a combined heading, as a possible match at all."""
        existing = "## Gateway v3.20.6 & v3.19.11\n\n**2026-07-01 & 2026-06-30**\n\n### Bug fixes\n\n- old fix\n"
        entry = "## Gateway v3.20.6 & v3.19.11\n\n**2026-07-02 & 2026-07-01**\n\n### Bug fixes\n\n- new fix\n"
        result = splice(existing, entry)
        self.assertEqual(result.count("## Gateway v3.20.6 & v3.19.11"), 1)
        self.assertIn("new fix", result)
        self.assertNotIn("old fix", result)

    def test_inserts_above_first_heading_even_with_case_drifted_gateway_word(self):
        """Regression test for cutmode audit finding H: _HEADING_RE (used
        both as splice()'s own insertion-point search and as one of
        _existing_section_span's stop boundaries) was case-sensitive while
        _existing_section_span's own heading match is case-insensitive --
        an inconsistency that meant a differently-cased '## gateway v...'
        heading was a legitimate boundary for one and invisible to the
        other. Must recognize both consistently."""
        existing = "## gateway v3.20.6\n\nold content\n"  # lowercase "gateway"
        entry = "## Gateway v3.20.7\n\nnew content\n"
        result = splice(existing, entry)
        self.assertLess(result.index("v3.20.7"), result.index("v3.20.6"))

    def test_resplicing_replaces_even_when_new_entrys_heading_case_drifts(self):
        """Regression test for PR #32 review finding 3: _HEADING_IDENTITY_RE
        (used to read the NEW entry's own heading identity) lacked the
        IGNORECASE fix applied to _existing_section_span's match -- a
        differently-cased new-entry heading (e.g. from a re-prompt/regenerate
        cycle) failed _heading_identity(), fell through to the default
        insert-above-first-heading path, and duplicated the heading instead
        of replacing it -- the same duplicate-heading bug finding H exists to
        prevent, just reopened from the other side of the comparison."""
        existing = "## Gateway v3.20.6\n\nold content\n"
        entry = "## gateway v3.20.6\n\nnew content\n"  # lowercase "gateway"
        result = splice(existing, entry)
        self.assertEqual(result.count("v3.20.6"), 1)
        self.assertIn("new content", result)
        self.assertNotIn("old content", result)

    def test_resplice_ignores_h2_lookalike_inside_a_fenced_code_block(self):
        """Regression test for PR #32 review finding 4: _ANY_H2_RE (added for
        finding A's fix) is a naive '^## ' regex with no fenced-code-block
        awareness. A release note can legitimately contain a fenced example
        (e.g. demonstrating a config file's own comment syntax) whose content
        happens to start with '## ' -- treating that as the section's real
        end boundary means the OLD section's trailing content (after the
        fake heading) is wrongly left in the file as orphaned top-level
        content instead of being cleanly superseded by the new entry, the
        same 'replace, don't duplicate/leak' guarantee finding H protects on
        the heading side."""
        existing = (
            "## Gateway v3.21.0-ea.1\n\n**2026-08-10**\n\n#### Bedrock Mantle\n\n"
            "Example config:\n\n"
            "```yaml\n"
            "## This comment looks like a heading but is inside a code fence\n"
            "key: value\n"
            "```\n\n"
            "Stale content that must be fully replaced, not orphaned.\n"
        )
        entry = (
            "## Gateway v3.21.0-ea.1\n\n**2026-08-11**\n\n#### Bedrock Mantle\n\n"
            "#### Messages API\n"
        )
        result = splice(existing, entry)
        self.assertEqual(result.count("## Gateway v3.21.0-ea.1"), 1)
        self.assertIn("Messages API", result)
        self.assertNotIn("Stale content that must be fully replaced, not orphaned.", result)
        self.assertNotIn("inside a code fence", result)

    def test_resplicing_last_section_preserves_trailing_non_heading_footer(self):
        """Regression test for cutmode audit finding A: re-cutting the LAST
        Gateway section must not delete trailing content that isn't itself a
        '## Gateway v...' or '## Earlier releases' heading (e.g. a footer
        section like '## Support policy'). Confirmed live that
        _existing_section_span fell back to end-of-file when neither stop
        pattern matched, so splice() silently dropped everything after the
        re-cut section."""
        existing = (
            "## Gateway v3.21.0-ea.1\n\n**2026-08-10**\n\n#### Bedrock Mantle\n\n"
            "## Support policy\n\nThis section describes our support policy.\n"
        )
        entry = (
            "## Gateway v3.21.0-ea.1\n\n**2026-08-11**\n\n#### Bedrock Mantle\n\n"
            "#### Messages API\n"
        )
        result = splice(existing, entry)
        self.assertIn("Support policy", result)
        self.assertIn("This section describes our support policy.", result)
        self.assertIn("Messages API", result)


if __name__ == "__main__":
    unittest.main()
