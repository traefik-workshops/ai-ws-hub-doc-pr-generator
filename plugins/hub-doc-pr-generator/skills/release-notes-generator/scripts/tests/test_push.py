import unittest
from unittest.mock import patch

from scripts.push import (
    _parent_full_name, detect_fork, _branch_has_commits_to_push,
    commit_release_notes, open_release_notes_pr,
)
from scripts import _git


class TestParentFullName(unittest.TestCase):
    def test_uses_name_with_owner_if_present(self):
        self.assertEqual(_parent_full_name({"nameWithOwner": "traefik/hub-doc"}), "traefik/hub-doc")

    def test_builds_from_owner_and_name(self):
        parent = {"owner": {"login": "traefik"}, "name": "hub-doc"}
        self.assertEqual(_parent_full_name(parent), "traefik/hub-doc")

    def test_empty_parent_returns_empty_string(self):
        self.assertEqual(_parent_full_name({}), "")
        self.assertEqual(_parent_full_name(None), "")


class TestDetectFork(unittest.TestCase):
    def test_finds_fork_of_upstream(self):
        with patch("scripts.push._gh.current_user_login", return_value="octocat"), \
             patch("scripts.push._gh.run_json", return_value=[
                 {"name": "hub-doc", "parent": {"owner": {"login": "traefik"}, "name": "hub-doc"}},
             ]):
            fork = detect_fork()
        self.assertEqual(fork, "octocat/hub-doc")

    def test_returns_none_when_no_matching_fork(self):
        with patch("scripts.push._gh.current_user_login", return_value="octocat"), \
             patch("scripts.push._gh.run_json", return_value=[
                 {"name": "something-else", "parent": {"owner": {"login": "other"}, "name": "repo"}},
             ]):
            self.assertIsNone(detect_fork())


class TestBranchHasCommitsToPush(unittest.TestCase):
    def test_true_when_ahead_of_origin_main(self):
        with patch("scripts.push._git.run", return_value="3\n"):
            self.assertTrue(_branch_has_commits_to_push("/hub-doc", "docs/rn"))

    def test_false_when_no_commits_ahead(self):
        with patch("scripts.push._git.run", return_value="0\n"):
            self.assertFalse(_branch_has_commits_to_push("/hub-doc", "docs/rn"))

    def test_tries_next_base_when_one_fails(self):
        calls = {"n": 0}

        def fake_run(repo, args):
            calls["n"] += 1
            if "origin/main" in args[-1]:
                raise _git.GitError("unknown revision")
            return "1\n"
        with patch("scripts.push._git.run", side_effect=fake_run):
            self.assertTrue(_branch_has_commits_to_push("/hub-doc", "docs/rn"))
        self.assertGreater(calls["n"], 1)

    def test_false_when_all_bases_fail(self):
        with patch("scripts.push._git.run", side_effect=_git.GitError("no such ref")):
            self.assertFalse(_branch_has_commits_to_push("/hub-doc", "docs/rn"))


class TestCommitReleaseNotes(unittest.TestCase):
    def test_raises_if_not_on_expected_branch(self):
        with patch("scripts.push._git.head_branch", return_value="main"):
            with self.assertRaises(ValueError):
                commit_release_notes(doc_repo_root="/hub-doc", branch="docs/rn", title="docs: x")

    def test_commits_when_changes_are_staged(self):
        with patch("scripts.push._git.head_branch", return_value="docs/rn"), \
             patch("scripts.push._git.run") as mock_run:
            mock_run.side_effect = [
                "docs/api-gateway/release-notes.mdx\n",  # diff --cached --name-only
                "",  # commit
            ]
            commit_release_notes(doc_repo_root="/hub-doc", branch="docs/rn", title="docs: x")
        commit_call = [c for c in mock_run.call_args_list if c.args[1][0] == "commit"]
        self.assertEqual(len(commit_call), 1)

    def test_noop_when_already_committed_by_prior_run(self):
        with patch("scripts.push._git.head_branch", return_value="docs/rn"), \
             patch("scripts.push._git.run", return_value=""), \
             patch("scripts.push._branch_has_commits_to_push", return_value=True):
            commit_release_notes(doc_repo_root="/hub-doc", branch="docs/rn", title="docs: x")  # no raise

    def test_raises_when_nothing_staged_and_nothing_to_push(self):
        with patch("scripts.push._git.head_branch", return_value="docs/rn"), \
             patch("scripts.push._git.run", return_value=""), \
             patch("scripts.push._branch_has_commits_to_push", return_value=False):
            with self.assertRaises(ValueError):
                commit_release_notes(doc_repo_root="/hub-doc", branch="docs/rn", title="docs: x")


class TestOpenReleaseNotesPr(unittest.TestCase):
    def test_raises_when_no_fork_detected(self):
        with patch("scripts.push.detect_fork", return_value=None):
            with self.assertRaises(RuntimeError):
                open_release_notes_pr(doc_repo_root="/hub-doc", branch="docs/rn", title="t", body="b")

    def test_pushes_to_fork_and_creates_pr(self):
        def fake_git_run(repo, args):
            if args[:2] == ["remote", "add"]:
                raise _git.GitError("remote fork already exists")
            return ""

        with patch("scripts.push.detect_fork", return_value="octocat/hub-doc"), \
             patch("scripts.push.commit_release_notes"), \
             patch("scripts.push._git.run", side_effect=fake_git_run) as git_run, \
             patch("scripts.push._gh.run_text", return_value="https://github.com/traefik/hub-doc/pull/999\n") as gh_run:
            url = open_release_notes_pr(doc_repo_root="/hub-doc", branch="docs/rn", title="t", body="b")
        self.assertEqual(url, "https://github.com/traefik/hub-doc/pull/999")
        set_url_calls = [c for c in git_run.call_args_list if c.args[1][:2] == ["remote", "set-url"]]
        self.assertEqual(len(set_url_calls), 1)
        pr_create_call = gh_run.call_args[0][0]
        self.assertIn("--draft", pr_create_call)
        self.assertIn("--base", pr_create_call)


if __name__ == "__main__":
    unittest.main()
