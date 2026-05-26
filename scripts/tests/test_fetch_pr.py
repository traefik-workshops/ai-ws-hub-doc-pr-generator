import unittest
import json
from pathlib import Path
from unittest.mock import patch
from scripts.fetch_pr import parse_pr_inputs, PrRef, fetch_single, collect_issues, _BODY_LINK_RE

FIXTURES = Path(__file__).parent / "fixtures"


class TestParsePrInputs(unittest.TestCase):
    def test_url_form(self):
        refs = parse_pr_inputs(
            ["https://github.com/traefik/traefik-hub/pull/1234"], cwd_remote=None
        )
        self.assertEqual(refs, [PrRef("traefik/traefik-hub", 1234)])

    def test_multiple_urls(self):
        refs = parse_pr_inputs(
            [
                "https://github.com/traefik/traefik-hub/pull/1234",
                "https://github.com/traefik/traefik-hub/pull/1240",
            ],
            cwd_remote=None,
        )
        self.assertEqual(
            refs,
            [PrRef("traefik/traefik-hub", 1234), PrRef("traefik/traefik-hub", 1240)],
        )

    def test_number_uses_cwd_remote(self):
        refs = parse_pr_inputs(["1234"], cwd_remote="traefik/traefik-hub")
        self.assertEqual(refs, [PrRef("traefik/traefik-hub", 1234)])

    def test_number_without_cwd_raises(self):
        with self.assertRaises(ValueError):
            parse_pr_inputs(["1234"], cwd_remote=None)

    def test_mixed_repos_raises(self):
        with self.assertRaises(ValueError):
            parse_pr_inputs(
                [
                    "https://github.com/traefik/traefik-hub/pull/1234",
                    "https://github.com/traefik/traefik/pull/9999",
                ],
                cwd_remote=None,
            )


class TestFetchSingle(unittest.TestCase):
    def test_fetch_single_returns_normalized_shape(self):
        view = json.loads((FIXTURES / "gh_pr_view_hub_feat.json").read_text())
        diff = (FIXTURES / "gh_pr_diff_hub_feat.patch").read_text()
        with patch("scripts.fetch_pr._gh.run_json", return_value=view), \
             patch("scripts.fetch_pr._gh.run_text", return_value=diff):
            result = fetch_single(PrRef("traefik/traefik-hub", 1234))
        self.assertEqual(result["number"], 1234)
        self.assertEqual(result["title"], view["title"])
        self.assertIn("Closes #5678", result["body"])
        self.assertEqual(result["base"], "master")
        self.assertFalse(result["diff_truncated"])
        self.assertEqual(len(result["files_changed"]), 2)
        self.assertEqual(result["files_changed"][0]["path"],
                         "hub/pkg/middleware/tokenratelimit/config.go")


class TestCollectIssues(unittest.TestCase):
    def test_body_regex_finds_all_forms(self):
        body = "Closes #1\nfixes #2 and Resolves: #3"
        nums = sorted(int(m.group(1)) for m in _BODY_LINK_RE.finditer(body))
        self.assertEqual(nums, [1, 2, 3])

    def test_collect_issues_merges_closes_and_subissues(self):
        issue = json.loads((FIXTURES / "gh_issue_5678.json").read_text())
        subissues = json.loads((FIXTURES / "gh_sub_issues.json").read_text())

        def fake_json(args):
            if "sub_issues" in " ".join(args):
                return subissues
            return issue

        with patch("scripts.fetch_pr._gh.run_json", side_effect=fake_json):
            issues = collect_issues(
                repo="traefik/traefik-hub",
                pr_body="Closes #5678",
                closing_refs=[5678],
            )
        nums = {i["number"] for i in issues}
        self.assertEqual(nums, {5678, 5681})

    def test_comments_drop_bots_and_empty(self):
        issue = json.loads((FIXTURES / "gh_issue_5678.json").read_text())
        with patch("scripts.fetch_pr._gh.run_json", return_value=issue), \
             patch("scripts.fetch_pr._fetch_sub_issues", return_value=[]):
            issues = collect_issues(
                repo="traefik/traefik-hub", pr_body="", closing_refs=[5678]
            )
        authors = [c["author"] for c in issues[0]["comments"]]
        self.assertEqual(authors, ["alice"])


if __name__ == "__main__":
    unittest.main()
