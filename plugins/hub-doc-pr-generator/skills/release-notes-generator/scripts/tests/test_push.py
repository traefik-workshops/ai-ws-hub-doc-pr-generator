import unittest
from unittest.mock import patch

from scripts.push import (
    _parent_full_name, detect_fork, _branch_has_commits_to_push,
    _fragments_with_staged_reassignment, commit_release_notes, open_release_notes_pr,
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


class TestFragmentsWithStagedReassignment(unittest.TestCase):
    """Unit-level coverage of the version-scoping guard (PR #32 review round
    5, finding 3) directly on the helper function, separate from
    TestCommitReleaseNotes' end-to-end coverage through commit_release_notes."""

    def test_expected_version_none_matches_any_real_reassignment(self):
        blobs = {
            "HEAD:frag.mdx": "---\ntarget_version: unassigned\n---\nbody\n",
            ":frag.mdx": "---\ntarget_version: v3.20.9\n---\nbody\n",
        }
        with patch("scripts.push._git.show_many", return_value=blobs):
            self.assertEqual(
                _fragments_with_staged_reassignment("/hub-doc", ["frag.mdx"]), ["frag.mdx"],
            )

    def test_expected_version_excludes_a_different_assigned_version(self):
        blobs = {
            "HEAD:frag.mdx": "---\ntarget_version: unassigned\n---\nbody\n",
            ":frag.mdx": "---\ntarget_version: v3.20.9\n---\nbody\n",
        }
        with patch("scripts.push._git.show_many", return_value=blobs):
            self.assertEqual(
                _fragments_with_staged_reassignment("/hub-doc", ["frag.mdx"], "v3.21.0-ea.2"), [],
            )

    def test_expected_version_includes_the_matching_assigned_version(self):
        blobs = {
            "HEAD:frag.mdx": "---\ntarget_version: unassigned\n---\nbody\n",
            ":frag.mdx": "---\ntarget_version: v3.21.0-ea.2\n---\nbody\n",
        }
        with patch("scripts.push._git.show_many", return_value=blobs):
            self.assertEqual(
                _fragments_with_staged_reassignment("/hub-doc", ["frag.mdx"], "v3.21.0-ea.2"), ["frag.mdx"],
            )


class TestCommitReleaseNotes(unittest.TestCase):
    def test_raises_if_not_on_expected_branch(self):
        with patch("scripts.push._git.head_branch", return_value="main"):
            with self.assertRaises(ValueError):
                commit_release_notes(doc_repo_root="/hub-doc", branch="docs/rn", title="docs: x")

    def test_commits_when_changes_are_staged(self):
        with patch("scripts.push._git.head_branch", return_value="docs/rn"), \
             patch("scripts.push._git.run") as mock_run:
            mock_run.side_effect = [
                "docs/api-gateway/release-notes.mdx\n",  # diff --cached --name-only (staged paths)
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

    def test_commit_uses_explicit_pathspec_not_bare_commit(self):
        """Regression test for cutmode audit finding E: a bare `git commit`
        with no pathspec commits whatever else happens to be staged in the
        repo -- in a shared clone another session might be using
        concurrently, that can sweep in a completely unrelated file. Must
        always pass an explicit `--` pathspec."""
        with patch("scripts.push._git.head_branch", return_value="docs/rn"), \
             patch("scripts.push._git.run") as mock_run:
            mock_run.side_effect = [
                "docs/api-gateway/release-notes.mdx\n",  # diff --cached --name-only (staged paths)
                "",  # commit
            ]
            commit_release_notes(doc_repo_root="/hub-doc", branch="docs/rn", title="docs: x")
        commit_call = [c for c in mock_run.call_args_list if c.args[1][0] == "commit"][0]
        self.assertIn("--", commit_call.args[1])
        self.assertIn("docs/api-gateway/release-notes.mdx", commit_call.args[1])

    def test_auto_discovers_staged_fragment_paths_without_explicit_list(self):
        """Regression test for PR #32 review finding 1: relying on the
        orchestrating agent to correctly maintain an external scratch file
        (SKILL.md's /tmp/reassigned_fragment_paths.txt) across steps has no
        way to catch a lost or incomplete list -- if it's wrong, finding F's
        fix silently doesn't apply, with no test able to catch it. The
        ground truth for "which fragments got reassigned this run" is
        already in git (assign_target_version.py's --doc-repo-root stages
        them) -- commit_release_notes must read that directly instead of
        trusting an external list, with no --path argument needed at all."""
        blobs = {
            "HEAD:docs/api-gateway/release-notes.d/_964-x.mdx": "---\ntarget_version: unassigned\n---\nbody\n",
            ":docs/api-gateway/release-notes.d/_964-x.mdx": "---\ntarget_version: v3.21.0-ea.1\n---\nbody\n",
            "HEAD:docs/api-gateway/release-notes.d/_970-y.mdx": "---\ntarget_version: unassigned\n---\nbody\n",
            ":docs/api-gateway/release-notes.d/_970-y.mdx": "---\ntarget_version: v3.21.0-ea.1\n---\nbody\n",
        }
        with patch("scripts.push._git.head_branch", return_value="docs/rn"), \
             patch("scripts.push._git.show_many", return_value=blobs), \
             patch("scripts.push._git.run") as mock_run:
            mock_run.side_effect = [
                # git diff --cached --name-only (staged paths, read once and
                # reused for both fragment auto-discovery and the staged check)
                "docs/api-gateway/release-notes.mdx\n"
                "docs/api-gateway/release-notes.d/_964-x.mdx\n"
                "docs/api-gateway/release-notes.d/_970-y.mdx\n",
                "",  # commit
            ]
            commit_release_notes(doc_repo_root="/hub-doc", branch="docs/rn", title="docs: x")
        commit_call = [c for c in mock_run.call_args_list if c.args[1][0] == "commit"][0]
        self.assertIn("docs/api-gateway/release-notes.d/_964-x.mdx", commit_call.args[1])
        self.assertIn("docs/api-gateway/release-notes.d/_970-y.mdx", commit_call.args[1])

    def test_does_not_auto_discover_unrelated_staged_files(self):
        """The auto-discovery must be scoped to the fragments directory glob
        -- an unrelated staged file in a shared clone (the CLAUDE.md
        "ec2.md nearly got committed" scenario) must never be swept in just
        because commit_release_notes looked at everything staged."""
        with patch("scripts.push._git.head_branch", return_value="docs/rn"), \
             patch("scripts.push._git.run") as mock_run:
            mock_run.side_effect = [
                "docs/api-gateway/release-notes.mdx\nsome/unrelated/ec2.md\n",
                "",  # commit
            ]
            commit_release_notes(doc_repo_root="/hub-doc", branch="docs/rn", title="docs: x")
        commit_call = [c for c in mock_run.call_args_list if c.args[1][0] == "commit"][0]
        self.assertNotIn("some/unrelated/ec2.md", commit_call.args[1])

    def test_does_not_auto_discover_a_staged_fragment_edit_without_a_reassignment(self):
        """Regression test (PR #32 review finding altitude-1): matching the
        FRAGMENT_GLOB alone isn't enough to tell "a fragment THIS run's
        assign_target_version.py --doc-repo-root staged" apart from "a
        fragment someone else in a concurrent session on the same shared
        clone happens to have staged for an unrelated reason" (e.g. a body
        typo fix, not a version reassignment) -- exactly the CLAUDE.md
        "shared clone" risk finding E's explicit-pathspec fix was meant to
        close, reopened via the auto-discovery glob. Auto-discovery must
        additionally confirm the staged fragment's content actually shows a
        target_version reassignment before including it."""
        blobs = {
            "HEAD:docs/api-gateway/release-notes.d/_970-y.mdx": "---\ntarget_version: v3.21.0-ea.1\n---\nOld body text\n",
            ":docs/api-gateway/release-notes.d/_970-y.mdx": "---\ntarget_version: v3.21.0-ea.1\n---\nFixed a typo in the body\n",
        }
        with patch("scripts.push._git.head_branch", return_value="docs/rn"), \
             patch("scripts.push._git.show_many", return_value=blobs), \
             patch("scripts.push._git.run") as mock_run:
            mock_run.side_effect = [
                "docs/api-gateway/release-notes.mdx\n"
                "docs/api-gateway/release-notes.d/_970-y.mdx\n",
                "",  # commit
            ]
            commit_release_notes(doc_repo_root="/hub-doc", branch="docs/rn", title="docs: x")
        commit_call = [c for c in mock_run.call_args_list if c.args[1][0] == "commit"][0]
        self.assertNotIn("docs/api-gateway/release-notes.d/_970-y.mdx", commit_call.args[1])

    def test_auto_discovers_a_staged_fragment_with_a_real_reassignment(self):
        """The positive case for the same guard: a fragment whose staged
        content DOES show a target_version reassignment (what
        assign_target_version.py --doc-repo-root actually produces) is still
        auto-discovered."""
        blobs = {
            "HEAD:docs/api-gateway/release-notes.d/_964-x.mdx": "---\ntarget_version: unassigned\n---\nbody\n",
            ":docs/api-gateway/release-notes.d/_964-x.mdx": "---\ntarget_version: v3.21.0-ea.1\n---\nbody\n",
        }
        with patch("scripts.push._git.head_branch", return_value="docs/rn"), \
             patch("scripts.push._git.show_many", return_value=blobs), \
             patch("scripts.push._git.run") as mock_run:
            mock_run.side_effect = [
                "docs/api-gateway/release-notes.mdx\n"
                "docs/api-gateway/release-notes.d/_964-x.mdx\n",
                "",  # commit
            ]
            commit_release_notes(doc_repo_root="/hub-doc", branch="docs/rn", title="docs: x")
        commit_call = [c for c in mock_run.call_args_list if c.args[1][0] == "commit"][0]
        self.assertIn("docs/api-gateway/release-notes.d/_964-x.mdx", commit_call.args[1])

    def test_a_reassigned_value_that_merely_contains_the_word_unassigned_still_counts(self):
        """Regression test: an earlier version of the auto-discovery check
        did `"unassigned" not in line` against the raw diff line, so a real
        assigned value that happens to CONTAIN the substring "unassigned"
        (e.g. a typo'd `v3.21.0-unassigned-rc1`) was wrongly treated as
        still-unassigned and silently excluded -- reopening finding F for
        that fragment. The check must match the exact sentinel
        (UNASSIGNED_TARGET_VERSION_RE), not do a substring search."""
        blobs = {
            "HEAD:docs/api-gateway/release-notes.d/_964-x.mdx": "---\ntarget_version: unassigned\n---\nbody\n",
            ":docs/api-gateway/release-notes.d/_964-x.mdx": "---\ntarget_version: v3.21.0-unassigned-rc1\n---\nbody\n",
        }
        with patch("scripts.push._git.head_branch", return_value="docs/rn"), \
             patch("scripts.push._git.show_many", return_value=blobs), \
             patch("scripts.push._git.run") as mock_run:
            mock_run.side_effect = [
                "docs/api-gateway/release-notes.mdx\n"
                "docs/api-gateway/release-notes.d/_964-x.mdx\n",
                "",  # commit
            ]
            commit_release_notes(doc_repo_root="/hub-doc", branch="docs/rn", title="docs: x")
        commit_call = [c for c in mock_run.call_args_list if c.args[1][0] == "commit"][0]
        self.assertIn("docs/api-gateway/release-notes.d/_964-x.mdx", commit_call.args[1])

    def test_brand_new_already_assigned_fragment_is_not_auto_discovered(self):
        """Regression test (PR #32 review round 4, finding 4): a fragment
        absent from HEAD (a brand-new file, not yet committed) that's staged
        with a real target_version already set doesn't necessarily mean THIS
        run's assign_target_version.py --doc-repo-root did that -- in the
        normal cut-mode workflow, a fragment assign_target_version.py
        reassigns already exists in HEAD as 'unassigned' (it was merged via
        its own doc PR before the cut ever ran); a fragment that's both
        brand-new AND already-assigned looks identical whether it came from
        this run or from an unrelated concurrent session on the same shared
        clone creating an off-convention fragment that skips the
        'unassigned' placeholder entirely -- the exact CLAUDE.md
        shared-clone risk this function's docstring says it exists to
        avoid. Treating 'absent from HEAD' as automatic proof of
        reassignment (the same as 'present in HEAD but still unassigned')
        reopens that risk; only the latter is unambiguous, so only the
        latter should auto-discover."""
        blobs = {
            "HEAD:docs/api-gateway/release-notes.d/_999-new.mdx": None,
            ":docs/api-gateway/release-notes.d/_999-new.mdx": "---\ntarget_version: v3.21.0-ea.1\n---\nbody\n",
        }
        with patch("scripts.push._git.head_branch", return_value="docs/rn"), \
             patch("scripts.push._git.show_many", return_value=blobs), \
             patch("scripts.push._git.run") as mock_run:
            mock_run.side_effect = [
                "docs/api-gateway/release-notes.mdx\n"
                "docs/api-gateway/release-notes.d/_999-new.mdx\n",
                "",  # commit
            ]
            commit_release_notes(doc_repo_root="/hub-doc", branch="docs/rn", title="docs: x")
        commit_call = [c for c in mock_run.call_args_list if c.args[1][0] == "commit"][0]
        self.assertNotIn("docs/api-gateway/release-notes.d/_999-new.mdx", commit_call.args[1])

    def test_rel_path_argument_controls_the_committed_pathspec(self):
        """Regression test: commit_release_notes used to hardcode
        DEFAULT_REL_PATH regardless of what preview.py's own overridable
        --rel-path actually wrote and staged. If they ever disagree, the
        pathspec this function builds doesn't match what's staged and the
        real edit is silently dropped (see rel_path's docstring). A caller
        that passes the same --rel-path preview.py was given must have that
        honored."""
        with patch("scripts.push._git.head_branch", return_value="docs/rn"), \
             patch("scripts.push._git.run") as mock_run:
            mock_run.side_effect = [
                "docs/api-gateway/some-other-file.mdx\n",
                "",  # commit
            ]
            commit_release_notes(
                doc_repo_root="/hub-doc", branch="docs/rn", title="docs: x",
                rel_path="docs/api-gateway/some-other-file.mdx",
            )
        commit_call = [c for c in mock_run.call_args_list if c.args[1][0] == "commit"][0]
        self.assertIn("docs/api-gateway/some-other-file.mdx", commit_call.args[1])

    def test_commit_includes_extra_paths_when_given(self):
        """A cut that reassigned fragments must commit those fragment paths
        in the same commit as the release-notes.mdx splice (see
        assign_target_version.py's --doc-repo-root), not leave them
        uncommitted."""
        with patch("scripts.push._git.head_branch", return_value="docs/rn"), \
             patch("scripts.push._git.run") as mock_run:
            mock_run.side_effect = [
                "docs/api-gateway/release-notes.mdx\ndocs/api-gateway/release-notes.d/_964-x.mdx\n",
                "",  # commit
            ]
            commit_release_notes(
                doc_repo_root="/hub-doc", branch="docs/rn", title="docs: x",
                paths=["docs/api-gateway/release-notes.d/_964-x.mdx"],
            )
        commit_call = [c for c in mock_run.call_args_list if c.args[1][0] == "commit"][0]
        self.assertIn("docs/api-gateway/release-notes.d/_964-x.mdx", commit_call.args[1])

    def test_path_argument_is_additive_not_a_replacement(self):
        """Regression test (PR #32 review finding 2): --path's own help text
        says it's an "extra repo-relative path to commit alongside
        {DEFAULT_REL_PATH}" -- i.e. additive. But `explicit_paths = list(paths)
        if paths else [DEFAULT_REL_PATH]` REPLACED the default whenever any
        --path was given, so a caller passing only the extra path (exactly
        what the help text says to do) silently dropped release-notes.mdx
        from the commit -- the actual release-note edit never got committed."""
        with patch("scripts.push._git.head_branch", return_value="docs/rn"), \
             patch("scripts.push._git.run") as mock_run:
            mock_run.side_effect = [
                "docs/api-gateway/release-notes.mdx\nsome/extra/file.md\n",
                "",  # commit
            ]
            commit_release_notes(
                doc_repo_root="/hub-doc", branch="docs/rn", title="docs: x",
                paths=["some/extra/file.md"],
            )
        commit_call = [c for c in mock_run.call_args_list if c.args[1][0] == "commit"][0]
        self.assertIn("docs/api-gateway/release-notes.mdx", commit_call.args[1])
        self.assertIn("some/extra/file.md", commit_call.args[1])


    def test_version_scoping_excludes_a_fragment_reassigned_to_a_different_version(self):
        """Regression test (PR #32 review round 5, finding 3): without
        --version, auto-discovery can't tell "this cut's own reassignment"
        apart from a DIFFERENT concurrent cut's reassignment sitting staged
        in the same shared clone -- two `cut` sessions running close
        together, each reassigning a different fragment to a different
        version, would each sweep up the OTHER's staged fragment into
        whichever session's push commits first. Passing the exact version
        this push is for must exclude a fragment staged for some other
        version."""
        blobs = {
            "HEAD:docs/api-gateway/release-notes.d/_964-x.mdx": "---\ntarget_version: unassigned\n---\nbody\n",
            ":docs/api-gateway/release-notes.d/_964-x.mdx": "---\ntarget_version: v3.20.9\n---\nbody\n",
        }
        with patch("scripts.push._git.head_branch", return_value="docs/rn"), \
             patch("scripts.push._git.show_many", return_value=blobs), \
             patch("scripts.push._git.run") as mock_run:
            mock_run.side_effect = [
                "docs/api-gateway/release-notes.mdx\n"
                "docs/api-gateway/release-notes.d/_964-x.mdx\n",
                "",  # commit
            ]
            commit_release_notes(
                doc_repo_root="/hub-doc", branch="docs/rn", title="docs: x",
                version="v3.21.0-ea.2",
            )
        commit_call = [c for c in mock_run.call_args_list if c.args[1][0] == "commit"][0]
        self.assertNotIn("docs/api-gateway/release-notes.d/_964-x.mdx", commit_call.args[1])

    def test_version_scoping_includes_a_fragment_reassigned_to_the_matching_version(self):
        """The positive case for the same guard: a fragment staged with
        EXACTLY the version this push is for is still auto-discovered."""
        blobs = {
            "HEAD:docs/api-gateway/release-notes.d/_964-x.mdx": "---\ntarget_version: unassigned\n---\nbody\n",
            ":docs/api-gateway/release-notes.d/_964-x.mdx": "---\ntarget_version: v3.21.0-ea.2\n---\nbody\n",
        }
        with patch("scripts.push._git.head_branch", return_value="docs/rn"), \
             patch("scripts.push._git.show_many", return_value=blobs), \
             patch("scripts.push._git.run") as mock_run:
            mock_run.side_effect = [
                "docs/api-gateway/release-notes.mdx\n"
                "docs/api-gateway/release-notes.d/_964-x.mdx\n",
                "",  # commit
            ]
            commit_release_notes(
                doc_repo_root="/hub-doc", branch="docs/rn", title="docs: x",
                version="v3.21.0-ea.2",
            )
        commit_call = [c for c in mock_run.call_args_list if c.args[1][0] == "commit"][0]
        self.assertIn("docs/api-gateway/release-notes.d/_964-x.mdx", commit_call.args[1])

    def test_no_version_given_keeps_old_any_reassignment_behavior(self):
        """Backward compatibility: tag mode never reassigns fragments and
        doesn't pass --version -- omitting it must behave exactly as before
        (any real reassignment is auto-discovered, regardless of value)."""
        blobs = {
            "HEAD:docs/api-gateway/release-notes.d/_964-x.mdx": "---\ntarget_version: unassigned\n---\nbody\n",
            ":docs/api-gateway/release-notes.d/_964-x.mdx": "---\ntarget_version: v3.20.9\n---\nbody\n",
        }
        with patch("scripts.push._git.head_branch", return_value="docs/rn"), \
             patch("scripts.push._git.show_many", return_value=blobs), \
             patch("scripts.push._git.run") as mock_run:
            mock_run.side_effect = [
                "docs/api-gateway/release-notes.mdx\n"
                "docs/api-gateway/release-notes.d/_964-x.mdx\n",
                "",  # commit
            ]
            commit_release_notes(doc_repo_root="/hub-doc", branch="docs/rn", title="docs: x")
        commit_call = [c for c in mock_run.call_args_list if c.args[1][0] == "commit"][0]
        self.assertIn("docs/api-gateway/release-notes.d/_964-x.mdx", commit_call.args[1])

    def test_unknown_explicit_path_raises_clean_error_instead_of_failing_the_whole_commit(self):
        """Regression test (PR #32 review round 5, finding 4): `git commit --
        <pathspec>` requires every path in the pathspec to be tracked or
        staged, or the ENTIRE commit fails -- confirmed live (`git commit --
        a.txt nonexistent.txt` -> "pathspec 'nonexistent.txt' did not match
        any file(s) known to git"). A typo'd or never-staged explicit --path
        must be caught with a clear, specific error before the git commit
        call, not surface as a cryptic low-level failure that also blocks
        the legitimate, validly-staged release-notes.mdx edit."""
        with patch("scripts.push._git.head_branch", return_value="docs/rn"), \
             patch("scripts.push._git.run") as mock_run:
            mock_run.side_effect = [
                "docs/api-gateway/release-notes.mdx\n",  # diff --cached --name-only
                "",  # ls-files -- typo/d-path.mdx (not tracked, empty output)
            ]
            with self.assertRaises(ValueError) as ctx:
                commit_release_notes(
                    doc_repo_root="/hub-doc", branch="docs/rn", title="docs: x",
                    paths=["typo/d-path.mdx"],
                )
        self.assertIn("typo/d-path.mdx", str(ctx.exception))
        # The commit itself must never have been attempted.
        commit_calls = [c for c in mock_run.call_args_list if c.args[1][0] == "commit"]
        self.assertEqual(commit_calls, [])

    def test_known_explicit_path_not_in_staged_now_but_tracked_is_accepted(self):
        """An explicit --path that's a real, already-tracked file (just not
        currently showing up in `git diff --cached` because it has no
        pending changes) must still be accepted -- the new validation only
        needs to rule out paths git has never heard of, not second-guess a
        caller who explicitly named a legitimate path."""
        with patch("scripts.push._git.head_branch", return_value="docs/rn"), \
             patch("scripts.push._git.run") as mock_run:
            mock_run.side_effect = [
                "docs/api-gateway/release-notes.mdx\n",  # diff --cached --name-only
                "already/tracked/unchanged.md\n",  # ls-files -- already/tracked/unchanged.md
                "",  # commit
            ]
            commit_release_notes(
                doc_repo_root="/hub-doc", branch="docs/rn", title="docs: x",
                paths=["already/tracked/unchanged.md"],
            )
        commit_call = [c for c in mock_run.call_args_list if c.args[1][0] == "commit"][0]
        self.assertIn("already/tracked/unchanged.md", commit_call.args[1])


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
