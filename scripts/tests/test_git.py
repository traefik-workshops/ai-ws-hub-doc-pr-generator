import unittest
from unittest.mock import patch
from scripts import _git


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


if __name__ == "__main__":
    unittest.main()
