import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from scripts.preview import apply_edits, FileEdit
from unittest.mock import patch
from scripts.preview import (
    run_linter, LintResult, detect_pretty_tools,
    render_diff_to_stdout, render_pages_to_stdout,
)


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


class TestPrettyRendering(unittest.TestCase):
    def test_detect_pretty_tools(self):
        def which(name):
            return f"/usr/bin/{name}" if name in ("delta", "glow") else None
        with patch("scripts.preview.shutil.which", side_effect=which):
            tools = detect_pretty_tools()
        self.assertEqual(tools, {"diff": "delta", "page": "glow"})

    def test_detect_prefers_glow_over_bat(self):
        with patch("scripts.preview.shutil.which",
                   side_effect=lambda n: "/x" if n in ("bat", "glow") else None):
            self.assertEqual(detect_pretty_tools()["page"], "glow")

    def test_detect_none_when_absent(self):
        with patch("scripts.preview.shutil.which", return_value=None):
            self.assertEqual(detect_pretty_tools(), {"diff": None, "page": None})

    def test_render_diff_falls_back_to_plain(self):
        # No delta on PATH → emit the raw diff, no subprocess.
        with patch("scripts.preview.shutil.which", return_value=None), \
             patch("scripts.preview.git_diff", return_value="diff --git a/x b/x\n+hi\n"), \
             patch("scripts.preview.subprocess.run") as run:
            buf = io.StringIO()
            with redirect_stdout(buf):
                render_diff_to_stdout("/repo")
        run.assert_not_called()
        self.assertIn("+hi", buf.getvalue())

    def test_render_diff_uses_delta_when_present(self):
        with patch("scripts.preview.shutil.which", side_effect=lambda n: "/x" if n == "delta" else None), \
             patch("scripts.preview.git_diff", return_value="diff --git a/x b/x\n+hi\n"), \
             patch("scripts.preview.subprocess.run") as run:
            render_diff_to_stdout("/repo")
        self.assertEqual(run.call_args[0][0][0], "delta")

    def test_render_pages_plain_skips_non_markdown(self):
        edits = [
            FileEdit(path="docs/page.md", content="# Title\n", mode="create"),
            FileEdit(path="sidebars.js", content="module.exports={}\n", mode="overwrite"),
        ]
        with patch("scripts.preview.shutil.which", return_value=None), \
             patch("scripts.preview.subprocess.run") as run:
            buf = io.StringIO()
            with redirect_stdout(buf):
                render_pages_to_stdout(edits)
        run.assert_not_called()
        out = buf.getvalue()
        self.assertIn("docs/page.md", out)
        self.assertIn("# Title", out)
        self.assertNotIn("sidebars.js", out)  # non-markdown skipped


if __name__ == "__main__":
    unittest.main()
