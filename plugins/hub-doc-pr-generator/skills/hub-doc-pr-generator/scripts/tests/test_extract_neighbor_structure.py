import tempfile
import unittest
from pathlib import Path

from scripts.extract_neighbor_structure import (
    _first_sentence,
    _first_sentence_end,
    extract_structure,
)


class TestFirstSentenceBoundary(unittest.TestCase):
    def test_plain_sentence(self):
        self.assertEqual(
            _first_sentence(["This is the intro. And more."], 0),
            "This is the intro.",
        )

    def test_version_number_not_split(self):
        # The period in "v3.20" must not end the sentence.
        self.assertEqual(
            _first_sentence(["Supports Traefik Hub v3.20 and later."], 0),
            "Supports Traefik Hub v3.20 and later.",
        )

    def test_abbreviation_not_split(self):
        self.assertEqual(
            _first_sentence(["Pass a token, e.g. an API key, in the header. Then call."], 0),
            "Pass a token, e.g. an API key, in the header.",
        )

    def test_no_terminator_returns_text(self):
        self.assertEqual(_first_sentence(["A short clause"], 0), "A short clause")

    def test_end_helper_ignores_decimal(self):
        self.assertIsNone(_first_sentence_end("ratio is 0.5 exactly"))
        self.assertEqual(_first_sentence_end("done. next"), 5)


class TestExtractStructure(unittest.TestCase):
    def test_parses_front_matter_and_headings(self):
        doc = (
            "---\n"
            "title: Token Rate Limit\n"
            "description: Limit tokens per client.\n"
            "tags:\n"
            "  - ai-gateway\n"
            "---\n"
            "\n"
            "Intro paragraph about the feature. Second sentence.\n"
            "\n"
            "## Configuration\n"
            "The config block. More detail.\n"
            "\n"
            "### Fields\n"
            "Each field matters.\n"
        )
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "page.md"
            p.write_text(doc, encoding="utf-8")
            out = extract_structure([str(p)])
        self.assertEqual(len(out), 1)
        entry = out[0]
        self.assertEqual(entry["title"], "Token Rate Limit")
        self.assertEqual(entry["tags"], ["ai-gateway"])
        headings = [s["heading"] for s in entry["sections"]]
        self.assertEqual(headings, ["Configuration", "Fields"])
        self.assertEqual(entry["sections"][0]["first_sentence"], "The config block.")

    def test_skips_unreadable_and_tiny_files(self):
        self.assertEqual(extract_structure(["/no/such/file.md"]), [])


if __name__ == "__main__":
    unittest.main()
