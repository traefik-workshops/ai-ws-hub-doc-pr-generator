import subprocess
import tempfile
import unittest
from pathlib import Path
from scripts.preview import apply_edits, FileEdit
from unittest.mock import patch
from scripts.preview import run_linter, LintResult


def _init_git(d: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                    "commit", "--allow-empty", "-qm", "init"], cwd=d, check=True)


class TestApplyEdits(unittest.TestCase):
    def test_writes_new_file_and_returns_paths(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            edits = [FileEdit(path="docs/new.md", content="hello\n", mode="create")]
            written = apply_edits(repo_path=str(d), branch="docs/test", edits=edits)
            self.assertEqual(written, ["docs/new.md"])
            self.assertTrue((d / "docs/new.md").is_file())

    def test_new_file_appears_in_diff(self):
        """New (previously untracked) files must be visible in git_diff output."""
        from scripts.preview import git_diff
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            edits = [FileEdit(path="docs/new.md", content="# Hello\n", mode="create")]
            apply_edits(repo_path=str(d), branch="docs/test", edits=edits)
            diff = git_diff(str(d))
            self.assertIn("docs/new.md", diff)
            self.assertIn("Hello", diff)

    def test_updates_existing_file(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            (d / "existing.md").write_text("old\n")
            subprocess.run(["git", "add", "existing.md"], cwd=d, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                            "commit", "-qm", "add"], cwd=d, check=True)
            edits = [FileEdit(path="existing.md", content="new\n", mode="overwrite")]
            apply_edits(repo_path=str(d), branch="docs/test", edits=edits)
            self.assertEqual((d / "existing.md").read_text(), "new\n")


class TestApplyEditsValidation(unittest.TestCase):
    def test_patch_mode_raises(self):
        """Mode 'patch' is not implemented and must raise, not silently overwrite."""
        with self.assertRaises((ValueError, NotImplementedError)):
            apply_edits(
                repo_path="/irrelevant",
                branch="docs/x",
                edits=[FileEdit(path="docs/x.md", content="hi", mode="patch")],  # type: ignore[arg-type]
            )


class TestRunLinter(unittest.TestCase):
    def test_hub_invokes_yarn(self):
        with patch("scripts.preview.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""
            result = run_linter(repo_path="/hub-doc", impl_repo="traefik/traefik-hub")
        self.assertIsInstance(result, LintResult)
        self.assertTrue(result.ok)
        first_call_args = mock_run.call_args_list[0][0][0]
        self.assertIn("yarn", first_call_args[0])

    def test_oss_invokes_mkdocs(self):
        with patch("scripts.preview.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""
            run_linter(repo_path="/traefik", impl_repo="traefik/traefik")
        call_args = mock_run.call_args_list[0][0][0]
        self.assertIn("mkdocs", " ".join(call_args))

    def test_failure_captures_stderr(self):
        with patch("scripts.preview.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "MD013 line too long"
            result = run_linter(repo_path="/hub-doc", impl_repo="traefik/traefik-hub")
        self.assertFalse(result.ok)
        self.assertIn("MD013", result.errors)


if __name__ == "__main__":
    unittest.main()
