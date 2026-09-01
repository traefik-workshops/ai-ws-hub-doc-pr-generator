import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import _git


def _init_repo_with_files(files: dict[str, str]) -> str:
    td = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q"], cwd=td, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=td, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=td, check=True)
    for path, content in files.items():
        full = Path(td) / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
        subprocess.run(["git", "add", path], cwd=td, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=td, check=True)
    return td


class TestGit(unittest.TestCase):
    def test_run_in_dir_uses_minus_C(self):
        with patch("scripts._git.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "abc123\n"
            mock_run.return_value.stderr = ""
            _git.run("/repo", ["rev-parse", "HEAD"])
        called_args = mock_run.call_args[0][0]
        self.assertEqual(called_args[:3], ["git", "-C", "/repo"])

    def test_run_raises_on_nonzero(self):
        with patch("scripts._git.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "fatal: not a git repo"
            with self.assertRaises(_git.GitError):
                _git.run("/notrepo", ["status"])


class TestShowMany(unittest.TestCase):
    def test_empty_specs_returns_empty_dict(self):
        self.assertEqual(_git.show_many("/anywhere", []), {})

    def test_fetches_multiple_files_in_one_call(self):
        repo = _init_repo_with_files({
            "a.md": "content of a\n",
            "b.md": "content of b\n",
        })
        result = _git.show_many(repo, ["HEAD:a.md", "HEAD:b.md"])
        self.assertEqual(result["HEAD:a.md"], "content of a\n")
        self.assertEqual(result["HEAD:b.md"], "content of b\n")

    def test_missing_path_maps_to_none_not_an_error(self):
        repo = _init_repo_with_files({"a.md": "x\n"})
        result = _git.show_many(repo, ["HEAD:a.md", "HEAD:does-not-exist.md"])
        self.assertEqual(result["HEAD:a.md"], "x\n")
        self.assertIsNone(result["HEAD:does-not-exist.md"])

    def test_preserves_embedded_newlines_and_multiline_content(self):
        content = "line one\nline two\n\nline four\n"
        repo = _init_repo_with_files({"a.md": content})
        result = _git.show_many(repo, ["HEAD:a.md"])
        self.assertEqual(result["HEAD:a.md"], content)

    def test_result_matches_plain_show_for_same_spec(self):
        repo = _init_repo_with_files({"a.md": "some content\n"})
        via_show = _git.run(repo, ["show", "HEAD:a.md"])
        via_batch = _git.show_many(repo, ["HEAD:a.md"])["HEAD:a.md"]
        self.assertEqual(via_show, via_batch)

    def test_invalid_repo_path_raises_git_error(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(_git.GitError):
                _git.show_many(td, ["HEAD:a.md"])


if __name__ == "__main__":
    unittest.main()
