import unittest
import json
from pathlib import Path
from unittest.mock import patch
from scripts.fetch_pr import parse_pr_inputs, PrRef, fetch_single, collect_issues, _BODY_LINK_RE, merge_prs, find_existing_doc_pr, build_bundle

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


class TestMergePrs(unittest.TestCase):
    def test_single_pr_primary_is_only_pr(self):
        prs = [{"number": 7, "files_changed": [{"path": "a.go", "additions": 3, "deletions": 0}],
                "title": "feat: A", "linked_issues": [], "sub_issues": []}]
        merged = merge_prs(prs)
        self.assertEqual(merged["primary_pr"], 7)
        self.assertEqual(merged["files_changed"][0]["path"], "a.go")

    def test_multi_pr_picks_largest_as_primary(self):
        prs = [
            {"number": 7, "files_changed": [{"path": "a.go", "additions": 3, "deletions": 0}],
             "title": "feat: A", "linked_issues": [], "sub_issues": []},
            {"number": 8, "files_changed": [{"path": "b.go", "additions": 50, "deletions": 0}],
             "title": "feat: B", "linked_issues": [], "sub_issues": []},
        ]
        merged = merge_prs(prs)
        self.assertEqual(merged["primary_pr"], 8)

    def test_files_changed_dedupes_by_path(self):
        prs = [
            {"number": 7, "files_changed": [{"path": "a.go", "additions": 3, "deletions": 0}],
             "title": "", "linked_issues": [], "sub_issues": []},
            {"number": 8, "files_changed": [{"path": "a.go", "additions": 5, "deletions": 1}],
             "title": "", "linked_issues": [], "sub_issues": []},
        ]
        merged = merge_prs(prs)
        paths = [f["path"] for f in merged["files_changed"]]
        self.assertEqual(paths, ["a.go"])
        # Sum additions when deduping
        self.assertEqual(merged["files_changed"][0]["additions"], 8)


class TestFindExistingDocPr(unittest.TestCase):
    def test_hub_returns_match(self):
        with patch("scripts.fetch_pr._gh.run_json",
                   return_value=[{"number": 999, "title": "docs: ...", "url": "..."}]):
            match = find_existing_doc_pr("traefik/traefik-hub", 1234)
        self.assertEqual(match["number"], 999)

    def test_hub_returns_none_when_empty(self):
        with patch("scripts.fetch_pr._gh.run_json", return_value=[]):
            match = find_existing_doc_pr("traefik/traefik-hub", 1234)
        self.assertIsNone(match)

    def test_oss_returns_none(self):
        # OSS does not file separate doc PRs — duplicate detection is the impl PR diff.
        match = find_existing_doc_pr("traefik/traefik", 1234)
        self.assertIsNone(match)


class TestBuildBundle(unittest.TestCase):
    def test_envelope_shape(self):
        view = json.loads((FIXTURES / "gh_pr_view_hub_feat.json").read_text())
        diff = (FIXTURES / "gh_pr_diff_hub_feat.patch").read_text()
        issue = json.loads((FIXTURES / "gh_issue_5678.json").read_text())

        with patch("scripts.fetch_pr._gh.run_json") as mock_json, \
             patch("scripts.fetch_pr._gh.run_text", return_value=diff):
            def route(args):
                joined = " ".join(args)
                if "issues/" in joined and "sub_issues" in joined:
                    return []
                if "pr list" in joined or args[:2] == ["pr", "list"]:
                    return []
                if "issue view" in joined or args[:2] == ["issue", "view"]:
                    return issue
                return view
            mock_json.side_effect = route
            bundle = build_bundle([PrRef("traefik/traefik-hub", 1234)])
        self.assertEqual(bundle["impl_repo"], "traefik/traefik-hub")
        self.assertEqual(len(bundle["prs"]), 1)
        self.assertEqual(bundle["merged"]["primary_pr"], 1234)
        self.assertIsNone(bundle["existing_doc_pr"])


if __name__ == "__main__":
    unittest.main()
