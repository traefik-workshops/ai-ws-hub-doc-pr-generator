import json
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.fetch_grounding import (
    parse_index, concepts_for_paths, build_grounding,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestParseIndex(unittest.TestCase):
    def test_parse_index_extracts_entries(self):
        text = (FIXTURES / "reference_INDEX.md").read_text()
        entries = parse_index(text)
        ids = [e["id"] for e in entries]
        self.assertIn("http.routers", ids)
        self.assertIn("hub.middleware.tokenratelimit", ids)
        tr = next(e for e in entries if e["id"] == "hub.middleware.tokenratelimit")
        self.assertEqual(tr["source"], "hub")
        self.assertIn("hub/pkg/middleware/tokenratelimit/config.go", tr["extracted_from"])


class TestConceptsForPaths(unittest.TestCase):
    def test_matches_extracted_from_path(self):
        entries = parse_index((FIXTURES / "reference_INDEX.md").read_text())
        matches = concepts_for_paths(
            entries, ["hub/pkg/middleware/tokenratelimit/middleware.go",
                      "hub/pkg/middleware/tokenratelimit/config.go"]
        )
        self.assertEqual([m["id"] for m in matches], ["hub.middleware.tokenratelimit"])

    def test_no_matches_returns_empty(self):
        entries = parse_index((FIXTURES / "reference_INDEX.md").read_text())
        self.assertEqual(concepts_for_paths(entries, ["unrelated.go"]), [])


class TestBuildGrounding(unittest.TestCase):
    def test_envelope(self):
        index = (FIXTURES / "reference_INDEX.md").read_text()
        doc_index = json.loads((FIXTURES / "reference_DOC_INDEX.json").read_text())
        with patch("scripts.fetch_grounding._gh.run_text", return_value=index), \
             patch("scripts.fetch_grounding._gh.run_json", return_value=doc_index):
            g = build_grounding(["hub/pkg/middleware/tokenratelimit/config.go"])
        self.assertEqual(len(g["concepts"]), 1)
        self.assertEqual(g["concepts"][0]["narrative_doc"],
                         "ai-gateway/middlewares/token-rate-limit.md")
        self.assertEqual(g["llms_txt_url"], "https://doc.traefik.io/traefik-hub/llms.txt")


if __name__ == "__main__":
    unittest.main()
