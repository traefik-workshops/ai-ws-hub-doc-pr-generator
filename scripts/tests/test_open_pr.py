import unittest
from unittest.mock import patch
from scripts.open_pr import detect_fork, open_hub_pr, commit_oss_docs


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


class TestOpenHubPr(unittest.TestCase):
    def test_pushes_to_fork_and_calls_gh_pr_create(self):
        calls = []
        def fake_git_run(*a, **kw):
            calls.append(("git", a, kw))
            return ""
        def fake_gh_run_text(args):
            calls.append(("gh-text", args))
            return "https://github.com/traefik/hub-doc/pull/999"
        with patch("scripts.open_pr._git.run", side_effect=fake_git_run), \
             patch("scripts.open_pr._gh.run_text", side_effect=fake_gh_run_text):
            url = open_hub_pr(
                doc_repo_root="/hub-doc",
                fork="alice/hub-doc",
                branch="docs/x",
                title="docs: add X",
                body="...",
            )
        # The fork URL should flow through the remote-add call.
        remote_call = next(c for c in calls if c[0] == "git" and c[1][1][:2] == ["remote", "add"])
        self.assertIn("alice/hub-doc", " ".join(remote_call[1][1]))
        # And the gh pr create --head should reference the fork owner.
        gh_call = next(c for c in calls if c[0] == "gh-text")
        self.assertIn("alice:docs/x", gh_call[1])
        self.assertEqual(url, "https://github.com/traefik/hub-doc/pull/999")


class TestCommitOssDocs(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
