import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts._discover import (
    HUB_DOC_URL_RE,
    _is_hub_doc_clone,
    discover_hub_doc,
    discover_oss,
)


def _init_repo(d: Path, origin_url: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "remote", "add", "origin", origin_url], cwd=d, check=True)


class TestUrlRegex(unittest.TestCase):
    def test_upstream_https(self):
        m = HUB_DOC_URL_RE.search("https://github.com/traefik/hub-doc.git")
        self.assertEqual(m["owner"], "traefik")

    def test_fork_ssh(self):
        m = HUB_DOC_URL_RE.search("git@github.com:alice/hub-doc.git")
        self.assertEqual(m["owner"], "alice")

    def test_unrelated_repo_does_not_match(self):
        self.assertIsNone(HUB_DOC_URL_RE.search("git@github.com:traefik/traefik.git"))


class TestIsHubDocClone(unittest.TestCase):
    def test_hub_doc_origin_matches(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_repo(d, "git@github.com:traefik/hub-doc.git")
            self.assertTrue(_is_hub_doc_clone(d))

    def test_non_git_dir_does_not_match(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(_is_hub_doc_clone(Path(td)))

    def test_other_repo_does_not_match(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_repo(d, "git@github.com:traefik/traefik.git")
            self.assertFalse(_is_hub_doc_clone(d))


class TestDiscoverHubDoc(unittest.TestCase):
    def test_env_var_wins(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_repo(d, "git@github.com:traefik/hub-doc.git")
            with patch("scripts._discover._load_config", return_value={}):
                result = discover_hub_doc(cwd="/", env={"HUB_DOC_PATH": str(d)})
            self.assertEqual(result, str(d.resolve()))

    def test_env_var_pointing_at_wrong_repo_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "wrong"
            d.mkdir()
            _init_repo(d, "git@github.com:traefik/traefik.git")
            with patch("scripts._discover._load_config", return_value={}), \
                 patch("scripts._discover._siblings_of", return_value=[]), \
                 patch("scripts._discover._scan_common_parents", return_value=[]):
                result = discover_hub_doc(cwd="/", env={"HUB_DOC_PATH": str(d)})
            self.assertIsNone(result)

    def test_cwd_sibling_discovery(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            hub_doc = workspace / "hub-doc"
            hub_doc.mkdir()
            _init_repo(hub_doc, "git@github.com:traefik/hub-doc.git")
            impl = workspace / "traefik-hub"
            impl.mkdir()
            with patch("scripts._discover._load_config", return_value={}), \
                 patch("scripts._discover._scan_common_parents", return_value=[]):
                result = discover_hub_doc(cwd=str(impl), env={})
            self.assertEqual(result, str(hub_doc.resolve()))

    def test_returns_none_when_nothing_found(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("scripts._discover._load_config", return_value={}), \
                 patch("scripts._discover._scan_common_parents", return_value=[]):
                result = discover_hub_doc(cwd=td, env={})
            self.assertIsNone(result)


class TestDiscoverOss(unittest.TestCase):
    def test_cwd_inside_git_repo_returns_root(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
            nested = d / "pkg" / "deep"
            nested.mkdir(parents=True)
            result = discover_oss(cwd=str(nested))
            # `git rev-parse --show-toplevel` may emit a `/private` prefix on macOS
            # for paths under /var; compare via realpath to normalize that.
            self.assertEqual(Path(result).resolve(), d.resolve())

    def test_non_git_dir_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(discover_oss(cwd=td))


if __name__ == "__main__":
    unittest.main()
