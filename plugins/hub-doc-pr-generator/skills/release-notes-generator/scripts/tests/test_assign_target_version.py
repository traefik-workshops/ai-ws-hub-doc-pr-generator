import subprocess
import tempfile
import unittest
from pathlib import Path
from scripts.assign_target_version import assign, main

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


class TestMain(unittest.TestCase):
    def test_writes_file_and_returns_zero(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "964-bedrock-mantle.mdx"
            path.write_text(FRAGMENT_BARE)
            rc = main(["--fragment", str(path), "--version", "v3.21.0-ea.1"])
            self.assertEqual(rc, 0)
            self.assertIn("target_version: v3.21.0-ea.1", path.read_text())

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


if __name__ == "__main__":
    unittest.main()
