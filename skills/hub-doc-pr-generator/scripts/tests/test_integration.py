import json
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.fetch_pr import build_bundle, PrRef

FIXTURES = Path(__file__).parent / "fixtures"


class TestEndToEnd(unittest.TestCase):
    """Replay a real PR through fetch_pr without touching the network."""

    def test_real_pr_normalizes_cleanly(self):
        view = json.loads((FIXTURES / "integration_pr_view.json").read_text())
        diff = (FIXTURES / "integration_pr_diff.patch").read_text()

        def fake_json(args):
            joined = " ".join(args)
            if "issue view" in joined or "issues/" in joined and "sub_issues" in joined:
                return []  # no sub-issues / issue-view in this minimal fixture
            if args[:2] == ["pr", "list"]:
                return []
            if args[:2] == ["pr", "view"]:
                return view
            if args[:2] == ["issue", "view"]:
                return {"number": 0, "title": "", "body": "", "comments": []}
            return view

        with patch("scripts.fetch_pr._gh.run_json", side_effect=fake_json), \
             patch("scripts.fetch_pr._gh.run_text", return_value=diff):
            bundle = build_bundle([PrRef("traefik/traefik-hub", view["number"])])

        self.assertEqual(bundle["impl_repo"], "traefik/traefik-hub")
        self.assertEqual(bundle["prs"][0]["number"], view["number"])
        self.assertIsInstance(bundle["prs"][0]["title"], str)
        self.assertTrue(bundle["merged"]["files_changed"])


if __name__ == "__main__":
    unittest.main()
