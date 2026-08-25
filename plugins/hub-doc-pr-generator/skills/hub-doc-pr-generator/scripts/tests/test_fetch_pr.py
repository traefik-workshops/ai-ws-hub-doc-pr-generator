import unittest
import json
from pathlib import Path
from unittest.mock import patch
from scripts.fetch_pr import parse_pr_inputs, PrRef, fetch_single, collect_issues, _BODY_LINK_RE, merge_prs, find_existing_doc_pr, build_bundle, fetch_issue_graph, _filter_diff
from scripts.fetch_pr import main as fetch_pr_main

FIXTURES = Path(__file__).parent / "fixtures"


class TestFilterDiff(unittest.TestCase):
    _PROD_HUNK = (
        "diff --git a/hub/pkg/middleware/cors/config.go b/hub/pkg/middleware/cors/config.go\n"
        "index abc..def 100644\n"
        "--- a/hub/pkg/middleware/cors/config.go\n"
        "+++ b/hub/pkg/middleware/cors/config.go\n"
        "@@ -1,3 +1,4 @@\n"
        " package cors\n"
        "+// AllowOrigins lists the permitted origins.\n"
    )
    _TEST_HUNK = (
        "diff --git a/hub/pkg/middleware/cors/config_test.go b/hub/pkg/middleware/cors/config_test.go\n"
        "index 111..222 100644\n"
        "--- a/hub/pkg/middleware/cors/config_test.go\n"
        "+++ b/hub/pkg/middleware/cors/config_test.go\n"
        "@@ -1,2 +1,3 @@\n"
        " package cors\n"
        "+// test\n"
    )
    _GENERATED_HUNK = (
        "diff --git a/zz_generated.deepcopy.go b/zz_generated.deepcopy.go\n"
        "index 333..444 100644\n"
        "--- a/zz_generated.deepcopy.go\n"
        "+++ b/zz_generated.deepcopy.go\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    def test_keeps_production_hunk(self):
        filtered, was_filtered = _filter_diff(self._PROD_HUNK)
        self.assertFalse(was_filtered)
        self.assertIn("cors/config.go", filtered)

    def test_drops_test_file_hunk(self):
        diff = self._PROD_HUNK + self._TEST_HUNK
        filtered, was_filtered = _filter_diff(diff)
        self.assertTrue(was_filtered)
        self.assertIn("cors/config.go", filtered)
        self.assertNotIn("config_test.go", filtered)

    def test_drops_generated_file_hunk(self):
        diff = self._PROD_HUNK + self._GENERATED_HUNK
        filtered, was_filtered = _filter_diff(diff)
        self.assertTrue(was_filtered)
        self.assertNotIn("zz_generated", filtered)

    def test_empty_diff_passthrough(self):
        filtered, was_filtered = _filter_diff("")
        self.assertEqual(filtered, "")
        self.assertFalse(was_filtered)

    def test_all_filtered_returns_empty(self):
        diff = self._TEST_HUNK + self._GENERATED_HUNK
        filtered, was_filtered = _filter_diff(diff)
        self.assertTrue(was_filtered)
        self.assertEqual(filtered.strip(), "")


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

    def test_number_without_cwd_error_points_at_working_alternatives(self):
        """Regression test for traefik-hub#1435 finding #3: the error
        previously gave no pointer to either working alternative (a full PR
        URL, or the already-existing --repo flag) when run from a directory
        that isn't a checkout of the impl repo."""
        with self.assertRaises(ValueError) as ctx:
            parse_pr_inputs(["1234"], cwd_remote=None)
        message = str(ctx.exception)
        self.assertIn("--repo", message)
        self.assertIn("URL", message)

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
        self.assertEqual(
            result["closingIssuesReferences"],
            [{"number": 5678, "repo": "traefik/traefik-hub"}],
        )

    def test_closing_issues_accepts_flat_list_and_nodes(self):
        from scripts.fetch_pr import _closing_issue_nodes
        # gh pr view --json returns a flat list
        self.assertEqual(_closing_issue_nodes([{"number": 1}]), [{"number": 1}])
        # raw GraphQL returns {"nodes": [...]}
        self.assertEqual(_closing_issue_nodes({"nodes": [{"number": 2}]}), [{"number": 2}])
        # None / empty degrade to []
        self.assertEqual(_closing_issue_nodes(None), [])
        self.assertEqual(_closing_issue_nodes({}), [])

    def test_node_repo_resolves_cross_repo_reference(self):
        from scripts.fetch_pr import _node_repo
        # repository object on the node wins
        self.assertEqual(
            _node_repo(
                {"number": 5, "repository": {"name": "hub-issues",
                                             "owner": {"login": "traefik"}}},
                "traefik/traefik-hub",
            ),
            "traefik/hub-issues",
        )
        # falls back to parsing the issue url
        self.assertEqual(
            _node_repo(
                {"number": 5, "url": "https://github.com/traefik/hub-issues/issues/5"},
                "traefik/traefik-hub",
            ),
            "traefik/hub-issues",
        )
        # no repo info → default to the PR's repo
        self.assertEqual(_node_repo({"number": 5}, "traefik/traefik-hub"),
                         "traefik/traefik-hub")


class TestCollectIssues(unittest.TestCase):
    def test_body_regex_finds_all_forms(self):
        body = "Closes #1\nfixes #2 and Resolves: #3"
        nums = sorted(int(m.group("num")) for m in _BODY_LINK_RE.finditer(body))
        self.assertEqual(nums, [1, 2, 3])

    def test_body_regex_captures_cross_repo_reference(self):
        body = "Closes traefik/hub-issues#42"
        m = _BODY_LINK_RE.search(body)
        self.assertEqual(m.group("repo"), "traefik/hub-issues")
        self.assertEqual(m.group("num"), "42")

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
                closing_refs=[{"number": 5678, "repo": "traefik/traefik-hub"}],
            )
        nums = {i["number"] for i in issues}
        self.assertEqual(nums, {5678, 5681})

    def test_collect_issues_fetches_from_issue_repo(self):
        issue = json.loads((FIXTURES / "gh_issue_5678.json").read_text())
        seen_repos = []

        def fake_json(args):
            if args[:2] == ["issue", "view"]:
                seen_repos.append(args[args.index("--repo") + 1])
                return issue
            return []  # sub_issues

        with patch("scripts.fetch_pr._gh.run_json", side_effect=fake_json):
            issues = collect_issues(
                repo="traefik/traefik-hub",
                pr_body="",
                closing_refs=[{"number": 5678, "repo": "traefik/hub-issues"}],
            )
        self.assertEqual(seen_repos, ["traefik/hub-issues"])
        self.assertEqual(issues[0]["repo"], "traefik/hub-issues")

    def test_comments_drop_bots_and_empty(self):
        issue = json.loads((FIXTURES / "gh_issue_5678.json").read_text())
        with patch("scripts.fetch_pr._gh.run_json", return_value=issue), \
             patch("scripts.fetch_pr._fetch_sub_issues", return_value=[]):
            issues = collect_issues(
                repo="traefik/traefik-hub", pr_body="",
                closing_refs=[{"number": 5678, "repo": "traefik/traefik-hub"}],
            )
        authors = [c["author"] for c in issues[0]["comments"]]
        self.assertEqual(authors, ["alice"])


def _graph_envelope(*, parent=None, issue_prs=None, sibling_specs=None, num=5678):
    """Build a closedByPullRequestsReferences/parent GraphQL response."""
    def pr_nodes(specs):
        return {"nodes": [
            {"number": n, "title": t, "url": f"https://x/{n}",
             "repository": {"nameWithOwner": "traefik/traefik-hub"}}
            for (n, t) in (specs or [])
        ]}
    parent_block = None
    if parent is not None:
        parent_block = {
            "number": parent[0], "title": parent[1], "body": parent[2],
            "subIssues": {"nodes": [
                {"number": s_num, "title": s_title,
                 "closedByPullRequestsReferences": pr_nodes(s_prs)}
                for (s_num, s_title, s_prs) in (sibling_specs or [])
            ]},
        }
    return {"data": {"repository": {"issue": {
        "number": num,
        "closedByPullRequestsReferences": pr_nodes(issue_prs),
        "parent": parent_block,
    }}}}


class TestFetchIssueGraph(unittest.TestCase):
    def test_parses_parent_siblings_and_related_prs(self):
        env = _graph_envelope(
            parent=(5000, "Epic: AI gateway rate limiting", "Decision context here."),
            issue_prs=[(1234, "feat: token rate limit")],
            sibling_specs=[
                (5681, "sub: store backend", [(1240, "feat: redis store")]),
                (5678, "this issue", [(1234, "feat: token rate limit")]),  # self, skipped
            ],
        )
        with patch("scripts.fetch_pr._gh.run_json", return_value=env):
            g = fetch_issue_graph("traefik/traefik-hub", 5678)
        self.assertEqual(g["parent"]["number"], 5000)
        self.assertIn("Decision context", g["parent"]["body"])
        # self is excluded from siblings
        self.assertEqual([s["number"] for s in g["siblings"]], [5681])
        related_nums = {p["number"] for p in g["related_prs"]}
        self.assertEqual(related_nums, {1234, 1240})

    def test_no_parent_returns_empty_siblings(self):
        env = _graph_envelope(parent=None, issue_prs=[(1234, "feat: x")])
        with patch("scripts.fetch_pr._gh.run_json", return_value=env):
            g = fetch_issue_graph("traefik/traefik-hub", 5678)
        self.assertIsNone(g["parent"])
        self.assertEqual(g["siblings"], [])

    def test_graphql_error_is_graceful(self):
        from scripts import _gh
        with patch("scripts.fetch_pr._gh.run_json", side_effect=_gh.GhError("boom")):
            g = fetch_issue_graph("traefik/traefik-hub", 5678)
        self.assertEqual(g, {"parent": None, "siblings": [], "related_prs": []})


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

        graph = _graph_envelope(
            parent=(5000, "Epic", "context"),
            issue_prs=[(1234, "feat: x"), (1240, "feat: sibling pr")],
            sibling_specs=[(5681, "sub", [(1240, "feat: sibling pr")])],
            num=5678,
        )

        with patch("scripts.fetch_pr._gh.run_json") as mock_json, \
             patch("scripts.fetch_pr._gh.run_text", return_value=diff):
            def route(args):
                joined = " ".join(args)
                if args[:2] == ["api", "graphql"]:
                    return graph
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
        # Parent/sibling context attached to the linked issue.
        linked = bundle["prs"][0]["linked_issues"][0]
        self.assertEqual(linked["parent"]["number"], 5000)
        self.assertEqual([s["number"] for s in linked["siblings"]], [5681])
        # related_prs excludes the source PR (1234) but keeps sibling PR 1240.
        related_nums = {p["number"] for p in bundle["prs"][0]["related_prs"]}
        self.assertEqual(related_nums, {1240})
        self.assertEqual({p["number"] for p in bundle["merged"]["related_prs"]}, {1240})


class TestMainAutoDetect(unittest.TestCase):
    def test_no_pr_and_detect_fails_returns_2(self):
        from scripts import _gh
        with patch("scripts.fetch_pr._gh.run_json", side_effect=_gh.GhError("no pr")), \
             patch("scripts.fetch_pr._cwd_remote", return_value="traefik/traefik-hub"):
            rc = fetch_pr_main([])
        self.assertEqual(rc, 2)

    def test_detect_without_number_returns_2(self):
        with patch("scripts.fetch_pr._gh.run_json", return_value={}), \
             patch("scripts.fetch_pr._cwd_remote", return_value="traefik/traefik-hub"):
            rc = fetch_pr_main([])
        self.assertEqual(rc, 2)

    def test_explicit_pr_skips_autodetection(self):
        # With an explicit --pr, `gh pr view` must not be consulted for detection,
        # even when --auto-detect is also passed.
        seen = {"pr_view": 0}

        def fake_json(args):
            if args[:2] == ["pr", "view"]:
                seen["pr_view"] += 1
            return {}

        with patch("scripts.fetch_pr._gh.run_json", side_effect=fake_json), \
             patch("scripts.fetch_pr._cwd_remote", return_value="traefik/traefik-hub"), \
             patch("scripts.fetch_pr.build_bundle", return_value={"ok": True}) as bb:
            rc = fetch_pr_main(["--pr", "1234", "--auto-detect"])
        self.assertEqual(rc, 0)
        self.assertEqual(seen["pr_view"], 0)
        refs = bb.call_args[0][0]
        self.assertEqual(refs[0], PrRef("traefik/traefik-hub", 1234))


if __name__ == "__main__":
    unittest.main()
