import unittest
from scripts._frontmatter import detect_newline, join_front_matter, split_front_matter, unquote


class TestUnquote(unittest.TestCase):
    def test_strips_double_quotes(self):
        self.assertEqual(unquote('"v3.21.0-ea.1"'), "v3.21.0-ea.1")

    def test_strips_single_quotes(self):
        self.assertEqual(unquote("'v3.21.0-ea.1'"), "v3.21.0-ea.1")

    def test_leaves_unquoted_value_alone(self):
        self.assertEqual(unquote("v3.21.0-ea.1"), "v3.21.0-ea.1")

    def test_mismatched_quotes_are_left_alone(self):
        self.assertEqual(unquote("'v3.21.0-ea.1\""), "'v3.21.0-ea.1\"")

    def test_strips_surrounding_whitespace_first(self):
        self.assertEqual(unquote('  "v3.21.0-ea.1"  '), "v3.21.0-ea.1")


class TestSplitFrontMatter(unittest.TestCase):
    def test_splits_front_matter_and_body(self):
        fm, body = split_front_matter("---\nkey: value\n---\nBody text\n")
        self.assertEqual(fm, "key: value")
        self.assertEqual(body, "Body text\n")

    def test_raises_when_no_front_matter_present(self):
        with self.assertRaises(ValueError):
            split_front_matter("# Just a heading\n")

    def test_tolerates_crlf_line_endings(self):
        """Regression test for cutmode audit finding G: _FRONT_MATTER_RE
        matches a literal '\\n', so a CRLF-saved fragment (a plausible
        Windows-editor save) previously failed the whole regex and raised the
        generic, misleading "no '---' front matter block found" error even
        though the front matter itself was perfectly well-formed."""
        fm, body = split_front_matter("---\r\nkey: value\r\n---\r\nBody text\r\n")
        self.assertEqual(fm, "key: value")

    def test_crlf_tolerance_does_not_flatten_the_body(self):
        """Regression test for PR #32 review finding 5: the original CRLF fix
        normalized the WHOLE input text (`text.replace("\\r\\n", "\\n")`)
        before matching, not just the bytes needed to make the delimiter
        regex match -- so a CRLF-saved fragment's body came back with every
        line ending silently rewritten to LF, producing a noisy full-file
        diff on write-back (assign_target_version.assign() reconstructs the
        file from this same fm/body split) for a change that should have
        touched only the target_version line. Only the fragment's own
        original line endings should survive in `body`."""
        fm, body = split_front_matter("---\r\nkey: value\r\n---\r\nBody text\r\nSecond line\r\n")
        self.assertEqual(body, "Body text\r\nSecond line\r\n")


class TestDetectNewline(unittest.TestCase):
    def test_detects_lf(self):
        self.assertEqual(detect_newline("---\nkey: value\n---\n"), "\n")

    def test_detects_crlf(self):
        self.assertEqual(detect_newline("---\r\nkey: value\r\n---\r\n"), "\r\n")

    def test_defaults_to_lf_with_no_newline_at_all(self):
        self.assertEqual(detect_newline("no newline here"), "\n")


class TestJoinFrontMatter(unittest.TestCase):
    def test_round_trips_with_split_front_matter(self):
        original = "---\nkey: value\n---\nBody text\n"
        fm, body = split_front_matter(original)
        self.assertEqual(join_front_matter(fm, body, detect_newline(original)), original)

    def test_round_trips_crlf(self):
        """Regression coverage for the shared counterpart of PR #32's
        CRLF-preservation fix (originally private to
        assign_target_version.assign()): rebuilding a CRLF fragment's
        delimiters must reproduce the original bytes exactly, not just LF."""
        original = "---\r\nkey: value\r\n---\r\nBody text\r\n"
        fm, body = split_front_matter(original)
        self.assertEqual(join_front_matter(fm, body, detect_newline(original)), original)

    def test_defaults_newline_to_lf(self):
        self.assertEqual(join_front_matter("key: value", "Body\n"), "---\nkey: value\n---\nBody\n")


if __name__ == "__main__":
    unittest.main()
