import unittest
from unittest.mock import patch
from scripts import _gh


class TestGh(unittest.TestCase):
    def test_run_json_parses_stdout(self):
        with patch("scripts._gh._run") as mock_run:
            mock_run.return_value = '{"number": 42}'
            result = _gh.run_json(["pr", "view", "42"])
        self.assertEqual(result, {"number": 42})

    def test_run_text_returns_raw_stdout(self):
        with patch("scripts._gh._run") as mock_run:
            mock_run.return_value = "raw patch text\n"
            result = _gh.run_text(["pr", "diff", "42"])
        self.assertEqual(result, "raw patch text\n")

    def test_assert_auth_raises_on_missing(self):
        with patch("scripts._gh._run") as mock_run:
            mock_run.side_effect = _gh.GhError("not logged in")
            with self.assertRaises(_gh.GhError):
                _gh.assert_auth()

    def test_current_user_login_extracts_login(self):
        with patch("scripts._gh._run") as mock_run:
            mock_run.return_value = '{"login": "octocat"}'
            self.assertEqual(_gh.current_user_login(), "octocat")

    def test_raises_when_gh_not_on_path(self):
        with patch("scripts._gh.shutil.which", return_value=None):
            with self.assertRaises(_gh.GhError):
                _gh.run_text(["pr", "view", "42"])

    def test_run_raises_with_stderr_on_nonzero(self):
        with patch("scripts._gh.shutil.which", return_value="/usr/bin/gh"), \
             patch("scripts._gh.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "HTTP 404"
            with self.assertRaises(_gh.GhError):
                _gh.run_text(["api", "repos/traefik/traefik-hub/tags"])


if __name__ == "__main__":
    unittest.main()
