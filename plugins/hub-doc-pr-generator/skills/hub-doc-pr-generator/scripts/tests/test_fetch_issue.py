import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.fetch_issue import parse_issue_input, IssueRef, build_bundle
from scripts.fetch_issue import main as fetch_issue_main

FIXTURES = Path(__file__).parent / "fixtures"


class TestParseIssueInput(unittest.TestCase):
    def test_url_form(self):
        ref = parse_issue_input(
            "https://github.com/traefik/hub-issues/issues/2930", cwd_remote=None,
        )
        self.assertEqual(ref, IssueRef("traefik/hub-issues", 2930))

    def test_number_uses_cwd_remote(self):
        ref = parse_issue_input("2930", cwd_remote="traefik/hub-issues")
        self.assertEqual(ref, IssueRef("traefik/hub-issues", 2930))

    def test_number_without_cwd_raises(self):
        with self.assertRaises(ValueError):
            parse_issue_input("2930", cwd_remote=None)

    def test_pr_url_is_rejected_not_misparsed(self):
        """A PR URL passed by mistake must not silently be treated as an
        issue -- fail loudly instead of fetching the wrong thing."""
        with self.assertRaises(ValueError):
            parse_issue_input("https://github.com/traefik/traefik-hub/pull/1234", cwd_remote=None)


class TestBuildBundle(unittest.TestCase):
    _RAW_ISSUE = {
        "number": 2930,
        "title": "Regex anchoring usage tip",
        "body": "Anchors matter for perf; document the gotcha.",
        "labels": [{"name": "area/ai-gateway"}],
        "state": "CLOSED",
        "stateReason": "COMPLETED",
        "comments": [
            {"author": {"login": "alice"}, "body": "Confirmed as working-as-intended."},
            {"author": {"login": "dependabot[bot]"}, "body": "noise"},
        ],
    }

    def test_bundle_shape_is_pipeline_compatible(self):
        with patch("scripts.fetch_issue._fetch_issue", return_value=self._RAW_ISSUE), \
             patch("scripts.fetch_issue._fetch_sub_issues", return_value=[]):
            bundle = build_bundle(
                IssueRef("traefik/hub-issues", 2930), impl_repo="traefik/traefik-hub",
            )
        self.assertEqual(bundle["impl_repo"], "traefik/traefik-hub")
        self.assertEqual(bundle["prs"], [])
        self.assertEqual(bundle["merged"]["files_changed"], [])
        self.assertIsNone(bundle["merged"]["primary_pr"])
        self.assertEqual(len(bundle["merged"]["linked_issues"]), 1)
        self.assertEqual(bundle["merged"]["linked_issues"][0]["number"], 2930)
        self.assertIsNone(bundle["existing_doc_pr"])
        self.assertEqual(bundle["issue"]["title"], "Regex anchoring usage tip")
        self.assertEqual(bundle["issue"]["labels"], ["area/ai-gateway"])

    def test_bot_comments_filtered(self):
        with patch("scripts.fetch_issue._fetch_issue", return_value=self._RAW_ISSUE), \
             patch("scripts.fetch_issue._fetch_sub_issues", return_value=[]):
            bundle = build_bundle(
                IssueRef("traefik/hub-issues", 2930), impl_repo="traefik/traefik-hub",
            )
        authors = [c["author"] for c in bundle["issue"]["comments"]]
        self.assertNotIn("dependabot[bot]", authors)
        self.assertIn("alice", authors)

    def test_sub_issues_included(self):
        sub = [{"number": 2931, "title": "Follow-up", "body": "detail"}]
        with patch("scripts.fetch_issue._fetch_issue", return_value=self._RAW_ISSUE), \
             patch("scripts.fetch_issue._fetch_sub_issues", return_value=sub):
            bundle = build_bundle(
                IssueRef("traefik/hub-issues", 2930), impl_repo="traefik/traefik-hub",
            )
        self.assertEqual(len(bundle["merged"]["sub_issues"]), 1)
        self.assertEqual(bundle["merged"]["sub_issues"][0]["number"], 2931)
        self.assertTrue(bundle["merged"]["sub_issues"][0]["is_sub_issue"])


class TestMain(unittest.TestCase):
    def test_end_to_end_prints_valid_bundle(self):
        with patch("scripts.fetch_issue._fetch_issue", return_value=TestBuildBundle._RAW_ISSUE), \
             patch("scripts.fetch_issue._fetch_sub_issues", return_value=[]):
            rc = fetch_issue_main([
                "--issue", "https://github.com/traefik/hub-issues/issues/2930",
                "--impl-repo", "traefik/traefik-hub",
            ])
        self.assertEqual(rc, 0)

    def test_defaults_impl_repo_to_issue_repo_when_not_given(self):
        with patch("scripts.fetch_issue._fetch_issue", return_value=TestBuildBundle._RAW_ISSUE), \
             patch("scripts.fetch_issue._fetch_sub_issues", return_value=[]), \
             patch("scripts.fetch_issue.build_bundle") as mock_build:
            mock_build.return_value = {"impl_repo": "x", "prs": [], "merged": {}, "issue": {}}
            fetch_issue_main(["--issue", "https://github.com/traefik/hub-issues/issues/2930"])
        _, kwargs = mock_build.call_args
        self.assertEqual(kwargs["impl_repo"], "traefik/hub-issues")


if __name__ == "__main__":
    unittest.main()
