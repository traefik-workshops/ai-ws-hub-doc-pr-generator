import unittest
from scripts._frontmatter import split_front_matter, unquote


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


if __name__ == "__main__":
    unittest.main()
