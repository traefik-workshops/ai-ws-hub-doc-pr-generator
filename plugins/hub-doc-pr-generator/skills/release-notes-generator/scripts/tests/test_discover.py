import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import _discover


def _init_hub_doc_clone(path: Path, *, remote: str = "https://github.com/traefik/hub-doc.git") -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", remote], cwd=path, check=True)


class TestIsHubDocClone(unittest.TestCase):
    def test_true_for_upstream_remote(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_hub_doc_clone(d)
            self.assertTrue(_discover._is_hub_doc_clone(d))

    def test_true_for_fork_remote(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_hub_doc_clone(d, remote="git@github.com:octocat/hub-doc.git")
            self.assertTrue(_discover._is_hub_doc_clone(d))

    def test_false_for_unrelated_repo(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_hub_doc_clone(d, remote="https://github.com/traefik/traefik.git")
            self.assertFalse(_discover._is_hub_doc_clone(d))

    def test_false_when_not_a_git_repo(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(_discover._is_hub_doc_clone(Path(td)))


class TestDiscoverHubDoc(unittest.TestCase):
    def test_env_var_takes_priority(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_hub_doc_clone(d)
            result = _discover.discover_hub_doc(cwd=td, env={"HUB_DOC_PATH": str(d)})
        self.assertEqual(result, str(d.resolve()))

    def test_persisted_config_used_when_no_env_var(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_hub_doc_clone(d)
            with patch("scripts._discover._load_config", return_value={"hub_doc_path": str(d)}):
                result = _discover.discover_hub_doc(cwd=td, env={})
        self.assertEqual(result, str(d.resolve()))

    def test_finds_sibling_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "myproject").mkdir()
            hub_doc = root / "hub-doc"
            hub_doc.mkdir()
            _init_hub_doc_clone(hub_doc)
            with patch("scripts._discover._load_config", return_value={}):
                result = _discover.discover_hub_doc(cwd=str(root / "myproject"), env={})
        self.assertEqual(result, str(hub_doc.resolve()))

    def test_returns_none_when_nothing_found(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("scripts._discover.COMMON_PARENTS", []), \
                 patch("scripts._discover._load_config", return_value={}):
                result = _discover.discover_hub_doc(cwd=td, env={})
        self.assertIsNone(result)


class TestPersistHubDoc(unittest.TestCase):
    def test_writes_config_file(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "config.json"
            with patch("scripts._discover.CONFIG_PATH", config_path):
                _discover.persist_hub_doc("/some/path")
            saved = json.loads(config_path.read_text())
        self.assertEqual(saved["hub_doc_path"], "/some/path")

    def test_preserves_other_keys(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "config.json"
            config_path.write_text(json.dumps({"other_key": "value"}))
            with patch("scripts._discover.CONFIG_PATH", config_path):
                _discover.persist_hub_doc("/some/path")
            saved = json.loads(config_path.read_text())
        self.assertEqual(saved["other_key"], "value")
        self.assertEqual(saved["hub_doc_path"], "/some/path")


if __name__ == "__main__":
    unittest.main()
