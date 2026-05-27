import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.fetch_grounding import (
    parse_index, parse_front_matter, concepts_for_paths,
    concept_page_path, build_grounding,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestParseIndex(unittest.TestCase):
    def test_parses_flat_bullets(self):
        entries = parse_index((FIXTURES / "reference_INDEX.md").read_text())
        ids = [e["id"] for e in entries]
        self.assertIn("http.middlewares.ratelimit", ids)
        self.assertIn("hub.middlewares.tokenratelimit", ids)
        self.assertIn("crd.api", ids)
        tr = next(e for e in entries if e["id"] == "hub.middlewares.tokenratelimit")
        self.assertEqual(tr["type_name"], "TokenRateLimit")
        self.assertEqual(tr["section"], "Hub middlewares")
        self.assertTrue(tr["description"])


class TestParseFrontMatter(unittest.TestCase):
    def test_extracts_scalars_and_lists(self):
        fm = parse_front_matter((FIXTURES / "reference_concept_tokenratelimit.md").read_text())
        self.assertEqual(fm["kind"], "middleware-http")
        self.assertEqual(fm["source"], "hub")
        self.assertEqual(fm["id"], "hub.middlewares.tokenratelimit")
        self.assertIn("hub/pkg/middleware/tokenratelimit/config.go", fm["extracted_from"])
        self.assertEqual(len(fm["extracted_from"]), 2)
        self.assertIn({"name": "limit", "type": "integer"}, fm["fields"])
        self.assertEqual(len(fm["fields"]), 3)


class TestConceptPagePath(unittest.TestCase):
    def test_drops_leading_source_segment(self):
        self.assertEqual(
            concept_page_path("hub.middlewares.tokenratelimit", "hub"),
            "reference/hub/middlewares/tokenratelimit.md",
        )

    def test_keeps_full_id_when_no_source_prefix(self):
        self.assertEqual(
            concept_page_path("crd.api", "hub"),
            "reference/hub/crd/api.md",
        )
        self.assertEqual(
            concept_page_path("http.middlewares.ratelimit", "oss"),
            "reference/oss/http/middlewares/ratelimit.md",
        )


class TestConceptsForPaths(unittest.TestCase):
    def setUp(self):
        self.entries = parse_index((FIXTURES / "reference_INDEX.md").read_text())

    def test_token_matches_last_id_segment(self):
        matches = concepts_for_paths(
            self.entries,
            ["hub/pkg/middleware/tokenratelimit/config.go",
             "hub/pkg/middleware/tokenratelimit/middleware.go"],
        )
        self.assertEqual([m["id"] for m in matches], ["hub.middlewares.tokenratelimit"])

    def test_does_not_substring_match(self):
        # 'tokenratelimit' must not match the 'ratelimit' concept
        matches = concepts_for_paths(
            self.entries, ["hub/pkg/middleware/tokenratelimit/config.go"]
        )
        self.assertNotIn("http.middlewares.ratelimit", [m["id"] for m in matches])

    def test_matches_via_type_name(self):
        matches = concepts_for_paths(self.entries, ["pkg/middlewares/stripprefix/stripprefix.go"])
        self.assertIn("http.middlewares.stripprefix", [m["id"] for m in matches])

    def test_no_match_returns_empty(self):
        self.assertEqual(concepts_for_paths(self.entries, ["pkg/server/router.go"]), [])


class TestBuildGrounding(unittest.TestCase):
    def _raw(self, path):
        mapping = {
            "reference/INDEX.md": (FIXTURES / "reference_INDEX.md").read_text(),
            "reference/DOC_INDEX.json": (FIXTURES / "reference_DOC_INDEX.json").read_text(),
            "reference/hub/middlewares/tokenratelimit.md":
                (FIXTURES / "reference_concept_tokenratelimit.md").read_text(),
        }
        return mapping[path]

    def test_enriches_matched_concept(self):
        with patch("scripts.fetch_grounding._fetch_raw", side_effect=self._raw):
            g = build_grounding(
                ["hub/pkg/middleware/tokenratelimit/config.go"],
                impl_repo="traefik/traefik-hub",
            )
        self.assertEqual(len(g["concepts"]), 1)
        c = g["concepts"][0]
        self.assertEqual(c["id"], "hub.middlewares.tokenratelimit")
        self.assertEqual(c["source"], "hub")
        self.assertEqual(c["narrative_doc"], "ai-gateway/middlewares/token-rate-limit.md")
        self.assertIn({"name": "limit", "type": "integer"}, c["fields"])
        self.assertEqual(g["llms_txt_url"], "https://doc.traefik.io/traefik-hub/llms.txt")

    def test_llms_url_from_impl_repo_when_no_concepts(self):
        with patch("scripts.fetch_grounding._fetch_raw", side_effect=self._raw):
            g = build_grounding(["pkg/server/router.go"], impl_repo="traefik/traefik")
        self.assertEqual(g["concepts"], [])
        self.assertEqual(g["llms_txt_url"], "https://doc.traefik.io/traefik/llms.txt")

    def test_never_emits_nonexistent_cross_product_url(self):
        with patch("scripts.fetch_grounding._fetch_raw", side_effect=self._raw):
            g = build_grounding(["pkg/server/router.go"], impl_repo=None)
        self.assertNotEqual(g["llms_txt_url"], "https://doc.traefik.io/llms.txt")


if __name__ == "__main__":
    unittest.main()
