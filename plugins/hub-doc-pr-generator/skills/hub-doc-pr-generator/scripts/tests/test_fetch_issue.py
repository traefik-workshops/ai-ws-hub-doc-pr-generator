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


_EMPTY_GRAPH = {"parent": None, "siblings": [], "related_prs": []}


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
             patch("scripts.fetch_issue._fetch_sub_issues", return_value=[]), \
             patch("scripts.fetch_issue.fetch_issue_graph", return_value=_EMPTY_GRAPH):
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
             patch("scripts.fetch_issue._fetch_sub_issues", return_value=[]), \
             patch("scripts.fetch_issue.fetch_issue_graph", return_value=_EMPTY_GRAPH):
            bundle = build_bundle(
                IssueRef("traefik/hub-issues", 2930), impl_repo="traefik/traefik-hub",
            )
        authors = [c["author"] for c in bundle["issue"]["comments"]]
        self.assertNotIn("dependabot[bot]", authors)
        self.assertIn("alice", authors)

    def test_sub_issues_included(self):
        sub = [{"number": 2931, "title": "Follow-up", "body": "detail"}]
        with patch("scripts.fetch_issue._fetch_issue", return_value=self._RAW_ISSUE), \
             patch("scripts.fetch_issue._fetch_sub_issues", return_value=sub), \
             patch("scripts.fetch_issue.fetch_issue_graph", return_value=_EMPTY_GRAPH):
            bundle = build_bundle(
                IssueRef("traefik/hub-issues", 2930), impl_repo="traefik/traefik-hub",
            )
        self.assertEqual(len(bundle["merged"]["sub_issues"]), 1)
        self.assertEqual(bundle["merged"]["sub_issues"][0]["number"], 2931)
        self.assertTrue(bundle["merged"]["sub_issues"][0]["is_sub_issue"])

    def test_parent_and_siblings_populated_from_issue_graph(self):
        """Regression test for the 2026-08-24 finding: fetch_issue.py never
        queried GitHub's native parent/sub-issue relationship at all, so
        `parent`/`siblings` always came back null/empty even when GitHub's
        graph had them populated (confirmed live against issue #3025, whose
        parent is #2971)."""
        graph = {
            "parent": {"number": 2971, "title": "AuthZEN MVP", "body": "epic body"},
            "siblings": [{"number": 3024, "title": "Sibling A"}],
            "related_prs": [],
        }
        with patch("scripts.fetch_issue._fetch_issue", return_value=self._RAW_ISSUE), \
             patch("scripts.fetch_issue._fetch_sub_issues", return_value=[]), \
             patch("scripts.fetch_issue.fetch_issue_graph", return_value=graph) as mock_graph:
            bundle = build_bundle(
                IssueRef("traefik/hub-issues", 3025), impl_repo="traefik/traefik-hub",
            )
        mock_graph.assert_called_once_with("traefik/hub-issues", 3025)
        issue = bundle["merged"]["linked_issues"][0]
        self.assertEqual(issue["parent"]["number"], 2971)
        self.assertEqual(issue["siblings"], [{"number": 3024, "title": "Sibling A"}])
        self.assertEqual(bundle["issue"]["parent"]["number"], 2971)

    def test_related_prs_populated_including_cross_repo(self):
        """Regression test: a PR closing the issue from a DIFFERENT repo than
        the issue itself (e.g. issue in traefik/hub-issues, closing PR in
        traefik/traefik-hub via a cross-repo Fixes:/Closes: reference)
        previously never surfaced -- `merged.related_prs` was hardcoded to
        `[]` regardless of what GitHub's closedByPullRequestsReferences
        graph actually had."""
        graph = {
            "parent": None,
            "siblings": [],
            "related_prs": [
                {"number": 1448, "title": "AuthZEN implementation", "url": "...",
                 "repo": "traefik/traefik-hub"},
            ],
        }
        with patch("scripts.fetch_issue._fetch_issue", return_value=self._RAW_ISSUE), \
             patch("scripts.fetch_issue._fetch_sub_issues", return_value=[]), \
             patch("scripts.fetch_issue.fetch_issue_graph", return_value=graph):
            bundle = build_bundle(
                IssueRef("traefik/hub-issues", 3025), impl_repo="traefik/traefik-hub",
            )
        self.assertEqual(len(bundle["merged"]["related_prs"]), 1)
        self.assertEqual(bundle["merged"]["related_prs"][0]["repo"], "traefik/traefik-hub")
        self.assertEqual(bundle["merged"]["related_prs"][0]["number"], 1448)


class TestMain(unittest.TestCase):
    def test_end_to_end_prints_valid_bundle(self):
        with patch("scripts.fetch_issue._fetch_issue", return_value=TestBuildBundle._RAW_ISSUE), \
             patch("scripts.fetch_issue._fetch_sub_issues", return_value=[]), \
             patch("scripts.fetch_issue.fetch_issue_graph", return_value=_EMPTY_GRAPH):
            rc = fetch_issue_main([
                "--issue", "https://github.com/traefik/hub-issues/issues/2930",
                "--impl-repo", "traefik/traefik-hub",
            ])
        self.assertEqual(rc, 0)

    def test_defaults_impl_repo_to_issue_repo_when_not_given(self):
        with patch("scripts.fetch_issue._fetch_issue", return_value=TestBuildBundle._RAW_ISSUE), \
             patch("scripts.fetch_issue._fetch_sub_issues", return_value=[]), \
             patch("scripts.fetch_issue.fetch_issue_graph", return_value=_EMPTY_GRAPH), \
             patch("scripts.fetch_issue.build_bundle") as mock_build:
            mock_build.return_value = {"impl_repo": "x", "prs": [], "merged": {}, "issue": {}}
            fetch_issue_main(["--issue", "https://github.com/traefik/hub-issues/issues/2930"])
        _, kwargs = mock_build.call_args
        self.assertEqual(kwargs["impl_repo"], "traefik/hub-issues")


if __name__ == "__main__":
    unittest.main()
