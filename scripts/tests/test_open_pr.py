import unittest
from unittest.mock import patch
from scripts.open_pr import detect_fork


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


if __name__ == "__main__":
    unittest.main()
