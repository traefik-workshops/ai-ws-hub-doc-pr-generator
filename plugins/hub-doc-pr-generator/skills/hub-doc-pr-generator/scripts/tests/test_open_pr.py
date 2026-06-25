import unittest
from unittest.mock import patch
from scripts.open_pr import (
    detect_fork, open_hub_pr, commit_hub_docs, commit_oss_docs, branch_slug_from_title
)


class TestDetectFork(unittest.TestCase):
    def test_returns_fork_when_match(self):
        forks = [{"name": "hub-doc", "parent": {"nameWithOwner": "traefik/hub-doc"}}]
        with patch("scripts.open_pr._gh.run_json", return_value=forks), \
             patch("scripts.open_pr._gh.current_user_login", return_value="alice"):
            fork = detect_fork(upstream="traefik/hub-doc")
        self.assertEqual(fork, "alice/hub-doc")

    def test_returns_none_when_no_match(self):
        with patch("scripts.open_pr._gh.run_json", return_value=[]), \
             patch("scripts.open_pr._gh.current_user_login", return_value="alice"):
            fork = detect_fork(upstream="traefik/hub-doc")
        self.assertIsNone(fork)


def _fake_git_on_branch(calls, branch, *, staged="docs/foo.md\n", ahead=0):
    """git stub: HEAD on *branch*, with *staged* files staged and *ahead* commits
    beyond base (for the push-retry path)."""
    def fake_git_run(*a, **kw):
        calls.append(("git", a, kw))
        args = a[1]
        if args[:2] == ["rev-parse", "--abbrev-ref"]:
            return f"{branch}\n"
        if args[:2] == ["diff", "--cached"]:
            return staged
        if args[:2] == ["rev-list", "--count"]:
            return f"{ahead}\n"
        return ""
    return fake_git_run


class TestOpenHubPr(unittest.TestCase):
    def test_pushes_to_fork_and_calls_gh_pr_create(self):
        calls = []
        def fake_gh_run_text(args):
            calls.append(("gh-text", args))
            return "https://github.com/traefik/hub-doc/pull/999"
        with patch("scripts.open_pr._git.run", side_effect=_fake_git_on_branch(calls, "docs/x")), \
             patch("scripts.open_pr._gh.run_text", side_effect=fake_gh_run_text):
            url = open_hub_pr(
                doc_repo_root="/hub-doc",
                fork="alice/hub-doc",
                branch="docs/x",
                title="docs: add X",
                body="...",
            )
        # A commit must happen before the push (otherwise the PR is empty)...
        commit_call = next(c for c in calls if c[0] == "git" and c[1][1][:1] == ["commit"])
        self.assertIn("docs: add X", " ".join(commit_call[1][1]))
        # ...and it must precede the push.
        kinds = [c[1][1][0] for c in calls if c[0] == "git"]
        self.assertLess(kinds.index("commit"), kinds.index("push"))
        # The fork URL should flow through the remote-add call.
        remote_call = next(c for c in calls if c[0] == "git" and c[1][1][:2] == ["remote", "add"])
        self.assertIn("alice/hub-doc", " ".join(remote_call[1][1]))
        # And the gh pr create --head should reference the fork owner.
        gh_call = next(c for c in calls if c[0] == "gh-text")
        self.assertIn("alice:docs/x", gh_call[1])
        self.assertEqual(url, "https://github.com/traefik/hub-doc/pull/999")


class TestCommitHubDocs(unittest.TestCase):
    def test_commits_staged_changes_with_title(self):
        calls = []
        with patch("scripts.open_pr._git.run", side_effect=_fake_git_on_branch(calls, "docs/x")):
            commit_hub_docs(doc_repo_root="/hub-doc", branch="docs/x", title="docs: add X")
        commit_call = next(c for c in calls if c[1][1][:1] == ["commit"])
        self.assertEqual(commit_call[1][1], ["commit", "-m", "docs: add X"])

    def test_wrong_branch_raises(self):
        calls = []
        with patch("scripts.open_pr._git.run", side_effect=_fake_git_on_branch(calls, "main")):
            with self.assertRaises(ValueError):
                commit_hub_docs(doc_repo_root="/hub-doc", branch="docs/x", title="docs: add X")
        # Must refuse before committing.
        self.assertNotIn("commit", [c[1][1][0] for c in calls])

    def test_no_staged_changes_raises(self):
        calls = []
        with patch("scripts.open_pr._git.run",
                   side_effect=_fake_git_on_branch(calls, "docs/x", staged="", ahead=0)):
            with self.assertRaises(ValueError):
                commit_hub_docs(doc_repo_root="/hub-doc", branch="docs/x", title="docs: add X")
        self.assertNotIn("commit", [c[1][1][0] for c in calls])

    def test_nothing_staged_but_already_committed_is_ok(self):
        # Push-retry path: a prior run committed (branch ahead of base) but the
        # push failed. Re-running must not raise and must not double-commit.
        calls = []
        with patch("scripts.open_pr._git.run",
                   side_effect=_fake_git_on_branch(calls, "docs/x", staged="", ahead=1)):
            commit_hub_docs(doc_repo_root="/hub-doc", branch="docs/x", title="docs: add X")
        self.assertNotIn("commit", [c[1][1][0] for c in calls])


class TestCommitOssDocs(unittest.TestCase):
    def test_empty_doc_files_raises(self):
        with self.assertRaises(ValueError, msg="should refuse to commit with no files"):
            commit_oss_docs(
                impl_repo_root="/traefik",
                title="add X",
                doc_files=[],
                refs_other_prs=[],
            )

    def test_single_pr_commit_no_refs(self):
        with patch("scripts.open_pr._git.run") as g:
            commit_oss_docs(
                impl_repo_root="/traefik",
                title="add encoded characters middleware",
                doc_files=["docs/content/reference/x.md"],
                refs_other_prs=[],
            )
        commit_call = next(c for c in g.call_args_list if c[0][1][0] == "commit")
        cmd = " ".join(commit_call[0][1])
        self.assertIn("docs: add encoded characters middleware", cmd)
        self.assertNotIn("Refs:", cmd)

    def test_multi_pr_commit_has_refs(self):
        with patch("scripts.open_pr._git.run") as g:
            commit_oss_docs(
                impl_repo_root="/traefik",
                title="add encoded characters middleware",
                doc_files=["docs/content/reference/x.md"],
                refs_other_prs=[5678, 5680],
            )
        commit_call = next(c for c in g.call_args_list if c[0][1][0] == "commit")
        cmd = " ".join(commit_call[0][1])
        self.assertIn("Refs: traefik#5678, traefik#5680", cmd)


class TestBranchSlug(unittest.TestCase):
    def test_strips_prefix_and_lowercases(self):
        self.assertEqual(
            branch_slug_from_title("feat: add onDenyResponse to ratelimit"),
            "docs/add-ondenyresponse-to-ratelimit",
        )

    def test_caps_length(self):
        title = "feat: " + "x" * 200
        slug = branch_slug_from_title(title)
        self.assertLessEqual(len(slug), 40 + len("docs/"))

    def test_prefix_only_title_falls_back_to_feature(self):
        self.assertEqual(branch_slug_from_title("feat:"), "docs/feature")

    def test_scoped_prefix_stripped(self):
        self.assertEqual(
            branch_slug_from_title("feat(ai-gateway): add rate limiting"),
            "docs/add-rate-limiting",
        )


if __name__ == "__main__":
    unittest.main()
