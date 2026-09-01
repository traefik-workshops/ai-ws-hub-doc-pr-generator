import json
import os
import subprocess
import sys
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
    (traefik-hub#1435 finding #6; traefik/hub-doc PR #988 round-3 finding #4)
    -- duplicated here since this skill keeps its own independent, trimmed
    _discover.py copy, not a symlink.

    All tests pass an explicit `probe_version` fake -- production's default
    (scripts.setup.python_version_at) really shells out to the given path,
    which none of these fixture paths point at a real interpreter."""

    @staticmethod
    def _always_compatible(path: str) -> tuple[int, int]:
        return (3, 11)

    def test_already_compatible_version_needs_no_reexec(self):
        self.assertIsNone(
            _discover.reexec_target(
                current_version=(3, 11), persisted_path="/opt/homebrew/bin/python3.11",
                probe_version=self._always_compatible,
            )
        )

    def test_too_old_with_no_persisted_path_does_nothing(self):
        self.assertIsNone(
            _discover.reexec_target(
                current_version=(3, 9), persisted_path=None,
                probe_version=self._always_compatible,
            )
        )

    def test_too_old_with_persisted_path_re_execs(self):
        self.assertEqual(
            _discover.reexec_target(
                current_version=(3, 9), persisted_path="/opt/homebrew/bin/python3.11",
                probe_version=self._always_compatible,
            ),
            "/opt/homebrew/bin/python3.11",
        )

    def test_persisted_path_same_as_current_executable_does_not_loop(self):
        self.assertIsNone(
            _discover.reexec_target(
                current_version=(3, 9),
                persisted_path="/usr/bin/python3",
                current_executable="/usr/bin/python3",
                probe_version=self._always_compatible,
            )
        )

    def test_symlink_to_same_interpreter_does_not_loop(self):
        # Fix B, layer 1: a symlink pointing at the same physical binary as
        # current_executable must be recognized as "same interpreter" even
        # though the two path strings differ.
        with tempfile.TemporaryDirectory() as td:
            real_bin = Path(td) / "python3.9"
            real_bin.write_text("")
            alias = Path(td) / "python3-alias"
            alias.symlink_to(real_bin)
            self.assertIsNone(
                _discover.reexec_target(
                    current_version=(3, 9),
                    persisted_path=str(alias),
                    current_executable=str(real_bin),
                    probe_version=self._always_compatible,
                )
            )

    def test_stale_persisted_path_below_min_python_is_not_used(self):
        """Regression for traefik/hub-doc PR #988 round-3 finding #4: a
        persisted path that no longer actually reports a MIN_PYTHON-or-newer
        version must not be handed back as the re-exec target."""
        self.assertIsNone(
            _discover.reexec_target(
                current_version=(3, 9),
                persisted_path="/opt/homebrew/bin/python3.11",
                probe_version=lambda path: (3, 9),
            )
        )

    def test_persisted_path_that_no_longer_exists_is_not_used(self):
        self.assertIsNone(
            _discover.reexec_target(
                current_version=(3, 9),
                persisted_path="/opt/homebrew/bin/python3.11",
                probe_version=lambda path: None,
            )
        )


class TestReexecArgv(unittest.TestCase):
    """Regression coverage for traefik/hub-doc PR #988 round-3 finding #3.
    See the identical test class in the sibling hub-doc-pr-generator skill's
    test_discover.py for the full rationale."""

    def test_preserves_dash_m_invocation_when_main_module_name_known(self):
        argv = ["/abs/path/.../scripts/collect_fragments.py", "--flag"]
        result = _discover._reexec_argv(
            "/opt/homebrew/bin/python3.11",
            orig_argv=argv,
            main_module_name="scripts.collect_fragments",
        )
        self.assertEqual(
            result,
            ["/opt/homebrew/bin/python3.11", "-m", "scripts.collect_fragments", "--flag"],
        )

    def test_falls_back_to_bare_argv_when_main_module_name_unknown(self):
        argv = ["scripts/foo.py", "--flag"]
        result = _discover._reexec_argv(
            "/opt/homebrew/bin/python3.11", orig_argv=argv, main_module_name=None,
        )
        self.assertEqual(result, ["/opt/homebrew/bin/python3.11", "scripts/foo.py", "--flag"])


class TestMaybeReexec(unittest.TestCase):
    def setUp(self):
        # maybe_reexec() sets a real env var as its one-shot re-exec guard;
        # keep that from leaking into other tests in this process.
        self._env_patch = patch.dict(os.environ, {}, clear=False)
        self._env_patch.start()
        os.environ.pop(_discover._REEXEC_ENV_SENTINEL, None)
        self.addCleanup(self._env_patch.stop)
        # reexec_target()'s default probe_version really shells out via
        # scripts.setup.python_version_at -- patch it to a compatible version
        # everywhere in this class so tests don't spawn a real subprocess
        # against a fixture path. Individual tests override as needed.
        self._probe_patch = patch("scripts.setup.python_version_at", return_value=(3, 11))
        self._probe_patch.start()
        self.addCleanup(self._probe_patch.stop)

    def test_calls_execv_when_reexec_target_found(self):
        # main_module_name forced to None: this test's argv fixture is a
        # simplified stand-in, not real sys.argv under an actual -m
        # invocation -- see test_preserves_dash_m_style_when_invoked_via_module.
        with patch("scripts._discover.sys") as mock_sys, \
             patch("scripts._discover.discover_python_path", return_value="/opt/homebrew/bin/python3.11"), \
             patch("scripts._discover._current_main_module_name", return_value=None), \
             patch("scripts._discover.os.execv") as mock_execv:
            mock_sys.version_info = (3, 9, 0)
            mock_sys.executable = "/usr/bin/python3"
            mock_sys.argv = ["-m", "scripts.foo"]
            _discover.maybe_reexec()
        mock_execv.assert_called_once_with(
            "/opt/homebrew/bin/python3.11",
            ["/opt/homebrew/bin/python3.11", "-m", "scripts.foo"],
        )
        self.assertEqual(os.environ.get(_discover._REEXEC_ENV_SENTINEL), "1")

    def test_preserves_dash_m_style_when_invoked_via_module(self):
        """Regression for traefik/hub-doc PR #988 round-3 finding #3."""
        with patch("scripts._discover.sys") as mock_sys, \
             patch("scripts._discover.discover_python_path", return_value="/opt/homebrew/bin/python3.11"), \
             patch("scripts._discover._current_main_module_name", return_value="scripts.foo"), \
             patch("scripts._discover.os.execv") as mock_execv:
            mock_sys.version_info = (3, 9, 0)
            mock_sys.executable = "/usr/bin/python3"
            mock_sys.argv = ["/abs/path/scripts/foo.py", "--flag"]
            _discover.maybe_reexec()
        mock_execv.assert_called_once_with(
            "/opt/homebrew/bin/python3.11",
            ["/opt/homebrew/bin/python3.11", "-m", "scripts.foo", "--flag"],
        )

    def test_does_not_call_execv_when_already_compatible(self):
        with patch("scripts._discover.sys") as mock_sys, \
             patch("scripts._discover.discover_python_path", return_value="/opt/homebrew/bin/python3.11"), \
             patch("scripts._discover.os.execv") as mock_execv:
            mock_sys.version_info = (3, 11, 0)
            _discover.maybe_reexec()
        mock_execv.assert_not_called()

    def test_does_not_call_discover_python_path_when_already_compatible(self):
        # Fix C: discover_python_path() must not run once the version check
        # alone already short-circuits.
        with patch("scripts._discover.sys") as mock_sys, \
             patch("scripts._discover.discover_python_path") as mock_discover, \
             patch("scripts._discover.os.execv") as mock_execv:
            mock_sys.version_info = (3, 11, 0)
            _discover.maybe_reexec()
        mock_discover.assert_not_called()
        mock_execv.assert_not_called()

    def test_execv_failure_is_caught_and_does_not_propagate(self):
        # Fix A: a stale persisted interpreter path must not surface as a
        # raw, confusing traceback.
        with patch("scripts._discover.sys") as mock_sys, \
             patch("scripts._discover.discover_python_path", return_value="/opt/homebrew/bin/python3.11"), \
             patch("scripts._discover._current_main_module_name", return_value=None), \
             patch("scripts._discover.os.execv", side_effect=OSError("no such file or directory")):
            mock_sys.version_info = (3, 9, 0)
            mock_sys.executable = "/usr/bin/python3"
            mock_sys.argv = ["-m", "scripts.foo"]
            mock_sys.stderr = sys.stderr
            try:
                _discover.maybe_reexec()
            except OSError:
                self.fail("maybe_reexec() must not let OSError from os.execv propagate")

    def test_execv_failure_prints_diagnostic_to_stderr(self):
        import io
        buf = io.StringIO()
        with patch("scripts._discover.sys") as mock_sys, \
             patch("scripts._discover.discover_python_path", return_value="/opt/homebrew/bin/python3.11"), \
             patch("scripts._discover._current_main_module_name", return_value=None), \
             patch("scripts._discover.os.execv", side_effect=OSError("no such file or directory")):
            mock_sys.version_info = (3, 9, 0)
            mock_sys.executable = "/usr/bin/python3"
            mock_sys.argv = ["-m", "scripts.foo"]
            mock_sys.stderr = buf
            _discover.maybe_reexec()
        output = buf.getvalue()
        self.assertIn("/opt/homebrew/bin/python3.11", output)
        self.assertIn("setup.py", output)

    def test_env_sentinel_prevents_second_reexec(self):
        # Fix B, layer 2: hard one-shot guard independent of reexec_target's
        # own comparison.
        os.environ[_discover._REEXEC_ENV_SENTINEL] = "1"
        with patch("scripts._discover.sys") as mock_sys, \
             patch("scripts._discover.discover_python_path", return_value="/opt/homebrew/bin/python3.11"), \
             patch("scripts._discover._current_main_module_name", return_value=None), \
             patch("scripts._discover.os.execv") as mock_execv:
            mock_sys.version_info = (3, 9, 0)
            mock_sys.executable = "/usr/bin/python3"
            mock_sys.argv = ["-m", "scripts.foo"]
            mock_sys.stderr = sys.stderr
            _discover.maybe_reexec()
        mock_execv.assert_not_called()

    def test_stale_persisted_path_skips_execv_entirely(self):
        """Regression for traefik/hub-doc PR #988 round-3 finding #4."""
        with patch("scripts._discover.sys") as mock_sys, \
             patch("scripts._discover.discover_python_path", return_value="/opt/homebrew/bin/python3.11"), \
             patch("scripts._discover._current_main_module_name", return_value=None), \
             patch("scripts.setup.python_version_at", return_value=(3, 9)), \
             patch("scripts._discover.os.execv") as mock_execv:
            mock_sys.version_info = (3, 9, 0)
            mock_sys.executable = "/usr/bin/python3"
            mock_sys.argv = ["-m", "scripts.foo"]
            mock_sys.stderr = sys.stderr
            _discover.maybe_reexec()
        mock_execv.assert_not_called()


if __name__ == "__main__":
    unittest.main()
