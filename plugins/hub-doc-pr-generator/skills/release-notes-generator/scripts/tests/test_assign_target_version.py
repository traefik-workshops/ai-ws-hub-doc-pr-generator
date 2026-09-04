import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.assign_target_version import assign, main
from scripts import _git

FRAGMENT_BARE = "---\nshape: ea-subsection\nsource_prs: [964]\ntarget_version: unassigned\n---\n\n#### Bedrock Mantle\n"
FRAGMENT_DOUBLE_QUOTED = FRAGMENT_BARE.replace("target_version: unassigned", 'target_version: "unassigned"')
FRAGMENT_SINGLE_QUOTED = FRAGMENT_BARE.replace("target_version: unassigned", "target_version: 'unassigned'")
FRAGMENT_ALREADY_ASSIGNED = FRAGMENT_BARE.replace("target_version: unassigned", "target_version: v3.20.0-ea.8")
FRAGMENT_DUPLICATE_KEY = FRAGMENT_BARE.replace(
    "target_version: unassigned\n", "target_version: unassigned\ntarget_version: unassigned\n",
)
FRAGMENT_BODY_TEXT_FALSE_POSITIVE = (
    "---\nshape: ea-subsection\nsource_prs: [964]\ntarget_version: unassigned\n---\n\n"
    "#### Bedrock Mantle\n\n"
    "This fragment demonstrates the format:\n"
    "target_version: unassigned\n"
)


class TestAssign(unittest.TestCase):
    def test_replaces_bare_unassigned(self):
        result = assign(FRAGMENT_BARE, "v3.21.0-ea.1")
        self.assertIn("target_version: v3.21.0-ea.1", result)
        self.assertNotIn("unassigned", result)

    def test_replaces_double_quoted_unassigned(self):
        """Regression test: the bug this script was extracted to fix -- a
        literal .replace('target_version: unassigned', ...) silently no-ops on
        this exact input."""
        result = assign(FRAGMENT_DOUBLE_QUOTED, "v3.21.0-ea.1")
        self.assertIn("target_version: v3.21.0-ea.1", result)
        self.assertNotIn("unassigned", result)

    def test_replaces_single_quoted_unassigned(self):
        result = assign(FRAGMENT_SINGLE_QUOTED, "v3.21.0-ea.1")
        self.assertIn("target_version: v3.21.0-ea.1", result)
        self.assertNotIn("unassigned", result)

    def test_raises_when_already_assigned(self):
        with self.assertRaises(ValueError):
            assign(FRAGMENT_ALREADY_ASSIGNED, "v3.21.0-ea.1")

    def test_raises_rather_than_silently_no_op(self):
        """The literal bug being fixed: never return content unchanged."""
        with self.assertRaises(ValueError):
            assign("no target_version line at all\n", "v3.21.0-ea.1")

    def test_raises_on_duplicate_unassigned_lines_instead_of_fixing_only_first(self):
        """Regression test: previously silently replaced only the first of two
        duplicate `target_version: unassigned` lines and reported success, while
        parse_fragment's dict-assignment walk (which takes the LAST occurrence)
        would still read the fragment back as unassigned. A duplicate key is
        malformed front matter -- raise so a human fixes it, don't guess."""
        with self.assertRaises(ValueError):
            assign(FRAGMENT_DUPLICATE_KEY, "v3.21.0-ea.1")

    def test_body_text_false_positive_does_not_block_assignment(self):
        """Regression test: a coincidental match of the sentinel pattern in
        the fragment's own BODY prose (not its front matter) previously
        counted as a second "duplicate key", permanently blocking assignment
        with a false "malformed front matter" error even though the actual
        front matter was perfectly well-formed. The search must be scoped to
        the front-matter block only."""
        result = assign(FRAGMENT_BODY_TEXT_FALSE_POSITIVE, "v3.21.0-ea.1")
        self.assertIn("target_version: v3.21.0-ea.1", result)
        # The body-text occurrence is untouched -- assign() only ever rewrites
        # the front-matter field, never body prose.
        self.assertIn("This fragment demonstrates the format:\ntarget_version: unassigned", result)

    def test_written_version_is_never_quoted(self):
        result = assign(FRAGMENT_DOUBLE_QUOTED, "v3.21.0-ea.1")
        self.assertIn('target_version: v3.21.0-ea.1', result)
        self.assertNotIn('target_version: "v3.21.0-ea.1"', result)

    def test_version_containing_backslash_digit_does_not_crash(self):
        """Regression test: the version was interpolated into re.sub's `repl`
        STRING argument, where a backslash-digit sequence (\\1, \\g<name>, ...)
        is interpreted as a backreference rather than literal text -- a
        plausible fat-fingered version string containing one previously
        raised a raw `re.error: invalid group reference` instead of this
        module's documented clean behavior. Must substitute it literally."""
        result = assign(FRAGMENT_BARE, r"v3.20\1")
        self.assertIn("target_version: v3.20\\1", result)

    def test_preserves_crlf_line_endings_throughout(self):
        """Regression test (PR #32 review finding 1): a CRLF-saved fragment
        previously came back with MIXED line endings -- split_front_matter
        preserves the original \\r\\n inside fm/body, but assign()'s final
        `f"---\\n{new_fm}\\n---\\n{body}"` hardcoded LF for both delimiter
        lines, and the substitution itself dropped the \\r on the one line it
        rewrote (`\\s*$` in UNASSIGNED_TARGET_VERSION_RE swallows a trailing
        \\r). Confirmed live: assigning a version to a CRLF fragment produced
        a file with both \\n and \\r\\n line endings in the same front-matter
        block -- exactly the noisy write-back diff this CRLF-tolerance work
        was supposed to eliminate."""
        crlf_fragment = FRAGMENT_BARE.replace("\n", "\r\n")
        result = assign(crlf_fragment, "v3.21.0-ea.1")
        self.assertNotIn("\n", result.replace("\r\n", ""), "result has a bare LF not part of a CRLF pair")
        self.assertIn("target_version: v3.21.0-ea.1\r\n", result)


class TestMain(unittest.TestCase):
    def test_writes_file_and_returns_zero(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "964-bedrock-mantle.mdx"
            path.write_text(FRAGMENT_BARE)
            rc = main(["--fragment", str(path), "--version", "v3.21.0-ea.1"])
            self.assertEqual(rc, 0)
            self.assertIn("target_version: v3.21.0-ea.1", path.read_text())

    def test_preserves_crlf_through_the_actual_file_round_trip(self):
        """Regression test (PR #32 review round 4, finding 2):
        test_preserves_crlf_line_endings_throughout above only calls
        assign() directly with an in-memory string, so it never exercised
        main()'s actual read/write path. Path.read_text()/write_text() at
        their default `newline=None` apply Python's universal-newline
        translation -- confirmed live: reading a file written as
        `b'---\\r\\ntarget_version: unassigned\\r\\n---\\r\\n'` back with
        `read_text(encoding='utf-8')` returns `'---\\ntarget_version:
        unassigned\\n---\\n'`, every \\r already gone before assign() ever
        runs -- silently defeating the whole CRLF-preservation fix in the
        one code path that matters, since the CLI is what actually rewrites
        fragments on disk."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "964-bedrock-mantle.mdx"
            path.write_bytes(FRAGMENT_BARE.replace("\n", "\r\n").encode("utf-8"))
            rc = main(["--fragment", str(path), "--version", "v3.21.0-ea.1"])
            self.assertEqual(rc, 0)
            raw = path.read_bytes()
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""),
                              "result has a bare LF not part of a CRLF pair")
            self.assertIn(b"target_version: v3.21.0-ea.1\r\n", raw)

    def test_returns_nonzero_and_leaves_file_untouched_on_no_match(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "964-bedrock-mantle.mdx"
            path.write_text(FRAGMENT_ALREADY_ASSIGNED)
            rc = main(["--fragment", str(path), "--version", "v3.21.0-ea.1"])
            self.assertEqual(rc, 1)
            self.assertEqual(path.read_text(), FRAGMENT_ALREADY_ASSIGNED)


class TestMainGitStaging(unittest.TestCase):
    def _init_repo(self, repo: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)

    def test_stages_reassigned_fragment_in_doc_repo_when_root_given(self):
        """Regression test for cutmode audit finding F: assign_target_version.py
        rewrites a fragment's front matter directly on disk but never staged
        that change in the hub-doc git repo -- if the branch doing the cut
        was never otherwise committed with this exact file, a later re-cut of
        the same still-open version from a different or fresh clone sees the
        fragment as `unassigned` again and silently drops it. Passing
        --doc-repo-root must stage (git add) the rewritten fragment so it
        rides along with whatever commits the rest of the cut pipeline."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._init_repo(repo)
            frag_dir = repo / "docs" / "api-gateway" / "release-notes.d"
            frag_dir.mkdir(parents=True)
            frag_path = frag_dir / "_964-bedrock-mantle.mdx"
            frag_path.write_text(FRAGMENT_BARE)
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

            rc = main([
                "--fragment", str(frag_path), "--version", "v3.21.0-ea.1",
                "--doc-repo-root", str(repo),
            ])
            self.assertEqual(rc, 0)
            staged = subprocess.run(
                ["git", "diff", "--cached", "--name-only"], cwd=repo,
                capture_output=True, text=True, check=True,
            ).stdout
            self.assertIn("docs/api-gateway/release-notes.d/_964-bedrock-mantle.mdx", staged)

    def test_branch_argument_checks_out_the_release_branch_before_staging(self):
        """Regression test (PR #32 review round 4, finding 6): cut mode's
        step 2 (this command) previously staged a fragment reassignment on
        whatever branch --doc-repo-root happened to be checked out to, and
        only step 6 (preview.py, several steps later) ever created/checked
        out the real release branch. If that later checkout failed (a
        diverged branch refusing an overwrite -- the exact concurrent-
        session risk CLAUDE.md documents), the reassignment was left staged
        somewhere that was never going to be committed anywhere real.
        Passing --branch makes this command check out (creating from
        origin/main if needed) the SAME branch preview.py uses, before
        staging, using the exact same checkout_branch() preview.py itself
        calls -- so the fragment always lands staged on the branch that's
        actually going somewhere."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._init_repo(repo)
            frag_dir = repo / "docs" / "api-gateway" / "release-notes.d"
            frag_dir.mkdir(parents=True)
            frag_path = frag_dir / "_964-bedrock-mantle.mdx"
            frag_path.write_text(FRAGMENT_BARE)
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
            # No local "origin" remote in this bare test repo -- checkout_branch()
            # only fetches from origin when the branch doesn't exist locally yet,
            # so create the release branch locally (via `git branch`, which
            # doesn't switch to it) first to exercise the "already exists,
            # just switch to it" path without needing a real remote.
            subprocess.run(["git", "branch", "docs/release-notes"], cwd=repo, check=True)

            rc = main([
                "--fragment", str(frag_path), "--version", "v3.21.0-ea.1",
                "--doc-repo-root", str(repo), "--branch", "docs/release-notes",
            ])
            self.assertEqual(rc, 0)
            current_branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo,
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            self.assertEqual(current_branch, "docs/release-notes")
            staged = subprocess.run(
                ["git", "diff", "--cached", "--name-only"], cwd=repo,
                capture_output=True, text=True, check=True,
            ).stdout
            self.assertIn("docs/api-gateway/release-notes.d/_964-bedrock-mantle.mdx", staged)

    def test_omitting_branch_keeps_staging_on_whatever_branch_is_checked_out(self):
        """--branch is optional -- omitting it must not attempt any checkout,
        preserving the exact behavior every other test in this class relies
        on (staging on the repo's current branch, whatever it is)."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._init_repo(repo)
            frag_dir = repo / "docs" / "api-gateway" / "release-notes.d"
            frag_dir.mkdir(parents=True)
            frag_path = frag_dir / "_964-bedrock-mantle.mdx"
            frag_path.write_text(FRAGMENT_BARE)
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

            rc = main([
                "--fragment", str(frag_path), "--version", "v3.21.0-ea.1",
                "--doc-repo-root", str(repo),
            ])
            self.assertEqual(rc, 0)

    def test_omitting_doc_repo_root_keeps_write_only_behavior(self):
        """--doc-repo-root is optional -- omitting it must not attempt any
        git operation (e.g. for a fragment path outside any repo, as most
        existing tests in this file use)."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "964-bedrock-mantle.mdx"
            path.write_text(FRAGMENT_BARE)
            rc = main(["--fragment", str(path), "--version", "v3.21.0-ea.1"])
            self.assertEqual(rc, 0)
            self.assertIn("target_version: v3.21.0-ea.1", path.read_text())

    def test_non_repo_doc_root_is_rejected_before_writing_the_fragment(self):
        """Regression test for PR #32 review finding 8: the original fix
        wrote the fragment's new target_version to disk BEFORE attempting to
        stage it, so a bad --doc-repo-root (not a real git repo) left the
        fragment rewritten-but-unstaged -- a broken, re-run-unsafe state
        (the unassigned sentinel is gone, so re-running just fails). A
        --doc-repo-root that isn't a git repo must be caught before any
        write happens, so the fragment is left completely untouched."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "_964-bedrock-mantle.mdx"
            path.write_text(FRAGMENT_BARE)
            not_a_repo = Path(td) / "not-a-repo"
            not_a_repo.mkdir()
            rc = main([
                "--fragment", str(path), "--version", "v3.21.0-ea.1",
                "--doc-repo-root", str(not_a_repo),
            ])
            self.assertEqual(rc, 1)
            self.assertEqual(path.read_text(), FRAGMENT_BARE)

    def test_fragment_outside_doc_repo_root_is_rejected_before_writing(self):
        """A fragment that isn't actually inside --doc-repo-root (a nonsensical
        pairing, likely a wrong argument) must be caught before any write,
        same rationale as the non-repo case above."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            self._init_repo(repo)
            elsewhere = Path(td) / "elsewhere"
            elsewhere.mkdir()
            path = elsewhere / "_964-bedrock-mantle.mdx"
            path.write_text(FRAGMENT_BARE)
            rc = main([
                "--fragment", str(path), "--version", "v3.21.0-ea.1",
                "--doc-repo-root", str(repo),
            ])
            self.assertEqual(rc, 1)
            self.assertEqual(path.read_text(), FRAGMENT_BARE)

    def test_git_add_failure_message_is_actionable(self):
        """If staging still fails for some other reason after a valid,
        pre-checked repo and path (e.g. a permissions issue), the error must
        tell the operator the fragment WAS already rewritten on disk and give
        the exact command to finish staging it manually, rather than a bare
        "failed to stage" message that leaves the recovery path a mystery."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._init_repo(repo)
            frag_path = repo / "_964-bedrock-mantle.mdx"
            frag_path.write_text(FRAGMENT_BARE)
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

            with patch("scripts.assign_target_version._git.run", side_effect=_git.GitError("simulated failure")):
                rc, err = self._run_capturing_stderr([
                    "--fragment", str(frag_path), "--version", "v3.21.0-ea.1",
                    "--doc-repo-root", str(repo),
                ])
            self.assertEqual(rc, 1)
            self.assertIn("target_version: v3.21.0-ea.1", frag_path.read_text())  # write DID happen
            self.assertIn("git -C", err)
            self.assertIn("add -- _964-bedrock-mantle.mdx", err)

    def test_warns_loudly_when_doc_repo_root_omitted(self):
        """Regression test (PR #32 review round 5, finding 1): SKILL.md's
        cut-mode step 2 tells the operator/agent to "always pass both
        --doc-repo-root and --branch", but the flags themselves are optional
        and nothing enforced or even flagged that instruction -- omitting
        --doc-repo-root left the rewrite silently uncommitted, with the
        exact same success message as the staged case. An operator/agent
        that skips the flag (e.g. copy-pasting an older command) must see an
        unmistakable warning, not just the same "success" line finding F's
        fix relies on staging actually happening."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "964-bedrock-mantle.mdx"
            path.write_text(FRAGMENT_BARE)
            rc, err = self._run_capturing_stderr(["--fragment", str(path), "--version", "v3.21.0-ea.1"])
        self.assertEqual(rc, 0)
        self.assertIn("WARNING", err)
        self.assertIn("--doc-repo-root", err)

    def test_warns_loudly_when_branch_omitted_but_doc_repo_root_given(self):
        """Same gap, the --branch half: omitting it stages the reassignment
        on whatever branch the doc repo already happens to be on (main, or a
        stale branch), not the release branch -- SKILL.md says to always
        pass both, so silently proceeding without --branch must warn too."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._init_repo(repo)
            frag_dir = repo / "docs" / "api-gateway" / "release-notes.d"
            frag_dir.mkdir(parents=True)
            frag_path = frag_dir / "_964-bedrock-mantle.mdx"
            frag_path.write_text(FRAGMENT_BARE)
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

            rc, err = self._run_capturing_stderr([
                "--fragment", str(frag_path), "--version", "v3.21.0-ea.1",
                "--doc-repo-root", str(repo),
            ])
        self.assertEqual(rc, 0)
        self.assertIn("WARNING", err)
        self.assertIn("--branch", err)

    def test_no_warning_when_both_safety_flags_are_given(self):
        """The happy path (both flags passed, as SKILL.md instructs) must
        stay quiet -- no WARNING noise on every normal cut-mode run."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._init_repo(repo)
            frag_dir = repo / "docs" / "api-gateway" / "release-notes.d"
            frag_dir.mkdir(parents=True)
            frag_path = frag_dir / "_964-bedrock-mantle.mdx"
            frag_path.write_text(FRAGMENT_BARE)
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
            subprocess.run(["git", "branch", "docs/release-notes"], cwd=repo, check=True)

            rc, err = self._run_capturing_stderr([
                "--fragment", str(frag_path), "--version", "v3.21.0-ea.1",
                "--doc-repo-root", str(repo), "--branch", "docs/release-notes",
            ])
        self.assertEqual(rc, 0)
        self.assertNotIn("WARNING", err)

    def test_success_message_states_whether_staging_happened(self):
        """The final confirmation line must say whether the reassignment was
        actually staged, not print identical text regardless -- an operator
        skimming output for confirmation shouldn't have to infer staging
        status from the presence or absence of a WARNING line above it."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "staged"
            repo.mkdir()
            self._init_repo(repo)
            frag_dir = repo / "docs" / "api-gateway" / "release-notes.d"
            frag_dir.mkdir(parents=True)
            frag_path = frag_dir / "_964-bedrock-mantle.mdx"
            frag_path.write_text(FRAGMENT_BARE)
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

            import io
            import contextlib
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                main([
                    "--fragment", str(frag_path), "--version", "v3.21.0-ea.1",
                    "--doc-repo-root", str(repo),
                ])
            self.assertIn("staged", out.getvalue().lower())

            unstaged_path = Path(td) / "unstaged.mdx"
            unstaged_path.write_text(FRAGMENT_BARE)
            out2 = io.StringIO()
            with contextlib.redirect_stdout(out2):
                main(["--fragment", str(unstaged_path), "--version", "v3.21.0-ea.1"])
            self.assertIn("not staged", out2.getvalue().lower())

    def test_stale_local_branch_missing_fragment_gives_clean_error_not_a_crash(self):
        """Regression test (PR #32 review round 5, finding 2): checkout_branch()
        leaves an EXISTING local branch as-is (no fetch/merge from origin/main
        -- only a branch that doesn't exist locally yet gets created fresh
        from there). If that existing branch is stale and predates this
        fragment's merge to main (a real risk on the shared clones this
        repo's own CLAUDE.md documents), checking it out removes the
        fragment from the working tree before this command's open() call
        ever runs -- previously an uncaught FileNotFoundError traceback
        instead of a clean, non-zero, "the fragment is gone" message."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._init_repo(repo)
            (repo / "README.md").write_text("x")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
            # A stale branch left over from earlier work, branched BEFORE
            # the fragment ever existed.
            subprocess.run(["git", "branch", "stale-branch"], cwd=repo, check=True)

            frag_dir = repo / "docs" / "api-gateway" / "release-notes.d"
            frag_dir.mkdir(parents=True)
            frag_path = frag_dir / "_964-bedrock-mantle.mdx"
            frag_path.write_text(FRAGMENT_BARE)
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "add fragment"], cwd=repo, check=True)

            rc, err = self._run_capturing_stderr([
                "--fragment", str(frag_path), "--version", "v3.21.0-ea.1",
                "--doc-repo-root", str(repo), "--branch", "stale-branch",
            ])
            self.assertEqual(rc, 1)
            self.assertIn("could not read/write the fragment file", err)
            self.assertIn("stale-branch", err)
            self.assertNotIn("Traceback", err)

    @staticmethod
    def _run_capturing_stderr(argv):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = main(argv)
        return rc, buf.getvalue()


if __name__ == "__main__":
    unittest.main()
