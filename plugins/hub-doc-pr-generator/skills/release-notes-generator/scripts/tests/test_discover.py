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


class TestReexecTarget(unittest.TestCase):
    """See the identical test class in the sibling hub-doc-pr-generator
    skill's test_discover.py for the full regression context
    (traefik-hub#1435 finding #6) -- duplicated here since this skill keeps
    its own independent, trimmed _discover.py copy, not a symlink."""

    def test_already_compatible_version_needs_no_reexec(self):
        self.assertIsNone(
            _discover.reexec_target(current_version=(3, 11), persisted_path="/opt/homebrew/bin/python3.11")
        )

    def test_too_old_with_no_persisted_path_does_nothing(self):
        self.assertIsNone(_discover.reexec_target(current_version=(3, 9), persisted_path=None))

    def test_too_old_with_persisted_path_re_execs(self):
        self.assertEqual(
            _discover.reexec_target(current_version=(3, 9), persisted_path="/opt/homebrew/bin/python3.11"),
            "/opt/homebrew/bin/python3.11",
        )

    def test_persisted_path_same_as_current_executable_does_not_loop(self):
        self.assertIsNone(
            _discover.reexec_target(
                current_version=(3, 9),
                persisted_path="/usr/bin/python3",
                current_executable="/usr/bin/python3",
            )
        )


class TestMaybeReexec(unittest.TestCase):
    def test_calls_execv_when_reexec_target_found(self):
        with patch("scripts._discover.sys") as mock_sys, \
             patch("scripts._discover.discover_python_path", return_value="/opt/homebrew/bin/python3.11"), \
             patch("scripts._discover.os.execv") as mock_execv:
            mock_sys.version_info = (3, 9, 0)
            mock_sys.executable = "/usr/bin/python3"
            mock_sys.argv = ["-m", "scripts.foo"]
            _discover.maybe_reexec()
        mock_execv.assert_called_once_with(
            "/opt/homebrew/bin/python3.11",
            ["/opt/homebrew/bin/python3.11", "-m", "scripts.foo"],
        )

    def test_does_not_call_execv_when_already_compatible(self):
        with patch("scripts._discover.sys") as mock_sys, \
             patch("scripts._discover.discover_python_path", return_value="/opt/homebrew/bin/python3.11"), \
             patch("scripts._discover.os.execv") as mock_execv:
            mock_sys.version_info = (3, 11, 0)
            _discover.maybe_reexec()
        mock_execv.assert_not_called()


if __name__ == "__main__":
    unittest.main()
