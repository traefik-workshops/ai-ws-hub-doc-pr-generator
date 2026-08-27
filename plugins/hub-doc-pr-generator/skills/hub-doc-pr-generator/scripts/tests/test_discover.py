import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts._discover import (
    HUB_DOC_URL_RE,
    _is_hub_doc_clone,
    _REEXEC_ENV_SENTINEL,
    discover_hub_doc,
    discover_oss,
    reexec_target,
    maybe_reexec,
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


class TestReexecTarget(unittest.TestCase):
    """Regression coverage for traefik-hub#1435 finding #6: nothing shortcut
    re-invoking a script under the correct interpreter after setup.py had
    already discovered and persisted it -- every command still needed the
    full interpreter path typed out by hand each session. The decision logic
    is split out from the os.execv side effect (see maybe_reexec) precisely
    so it's testable without actually replacing the test process."""

    def test_already_compatible_version_needs_no_reexec(self):
        self.assertIsNone(
            reexec_target(current_version=(3, 11), persisted_path="/opt/homebrew/bin/python3.11")
        )

    def test_newer_than_minimum_needs_no_reexec(self):
        self.assertIsNone(
            reexec_target(current_version=(3, 12), persisted_path="/opt/homebrew/bin/python3.11")
        )

    def test_too_old_with_no_persisted_path_does_nothing(self):
        # Nothing to re-exec to -- setup.py's own "Python 3.11+ required"
        # error still fires normally in this case.
        self.assertIsNone(reexec_target(current_version=(3, 9), persisted_path=None))

    def test_too_old_with_persisted_path_re_execs(self):
        self.assertEqual(
            reexec_target(current_version=(3, 9), persisted_path="/opt/homebrew/bin/python3.11"),
            "/opt/homebrew/bin/python3.11",
        )

    def test_persisted_path_same_as_current_executable_does_not_loop(self):
        # Defensive: never re-exec into the exact same (still-too-old)
        # interpreter that's already running -- that would just loop forever.
        self.assertIsNone(
            reexec_target(
                current_version=(3, 9),
                persisted_path="/usr/bin/python3",
                current_executable="/usr/bin/python3",
            )
        )

    def test_symlink_to_same_interpreter_does_not_loop(self):
        # Fix B, layer 1: a symlink pointing at the same physical binary as
        # current_executable must be recognized as "same interpreter" even
        # though the two path strings differ -- plain string equality would
        # miss this and re-exec into an identical, still-too-old process.
        with tempfile.TemporaryDirectory() as td:
            real_bin = Path(td) / "python3.9"
            real_bin.write_text("")
            alias = Path(td) / "python3-alias"
            alias.symlink_to(real_bin)
            self.assertIsNone(
                reexec_target(
                    current_version=(3, 9),
                    persisted_path=str(alias),
                    current_executable=str(real_bin),
                )
            )


class TestMaybeReexec(unittest.TestCase):
    def setUp(self):
        # maybe_reexec() sets a real env var as its one-shot re-exec guard;
        # keep that from leaking into other tests in this process.
        self._env_patch = patch.dict(os.environ, {}, clear=False)
        self._env_patch.start()
        os.environ.pop(_REEXEC_ENV_SENTINEL, None)
        self.addCleanup(self._env_patch.stop)

    def test_calls_execv_when_reexec_target_found(self):
        with patch("scripts._discover.sys") as mock_sys, \
             patch("scripts._discover.discover_python_path", return_value="/opt/homebrew/bin/python3.11"), \
             patch("scripts._discover.os.execv") as mock_execv:
            mock_sys.version_info = (3, 9, 0)
            mock_sys.executable = "/usr/bin/python3"
            mock_sys.argv = ["-m", "scripts.foo"]
            maybe_reexec()
        mock_execv.assert_called_once_with(
            "/opt/homebrew/bin/python3.11",
            ["/opt/homebrew/bin/python3.11", "-m", "scripts.foo"],
        )
        # Fix B, layer 2: the sentinel must be set before the (mocked) execv
        # attempt, since a real os.execv would inherit it into the child.
        self.assertEqual(os.environ.get(_REEXEC_ENV_SENTINEL), "1")

    def test_does_not_call_execv_when_already_compatible(self):
        with patch("scripts._discover.sys") as mock_sys, \
             patch("scripts._discover.discover_python_path", return_value="/opt/homebrew/bin/python3.11"), \
             patch("scripts._discover.os.execv") as mock_execv:
            mock_sys.version_info = (3, 11, 0)
            maybe_reexec()
        mock_execv.assert_not_called()

    def test_does_not_call_discover_python_path_when_already_compatible(self):
        # Fix C: discover_python_path() (file read + JSON parse) must not run
        # at all once the version check alone is enough to short-circuit --
        # wasted I/O on the (common) case of an already-compatible interpreter.
        with patch("scripts._discover.sys") as mock_sys, \
             patch("scripts._discover.discover_python_path") as mock_discover, \
             patch("scripts._discover.os.execv") as mock_execv:
            mock_sys.version_info = (3, 11, 0)
            maybe_reexec()
        mock_discover.assert_not_called()
        mock_execv.assert_not_called()

    def test_execv_failure_is_caught_and_does_not_propagate(self):
        # Fix A: a stale persisted interpreter path (e.g. moved/removed by a
        # Homebrew upgrade) must not surface as a raw, confusing traceback.
        with patch("scripts._discover.sys") as mock_sys, \
             patch("scripts._discover.discover_python_path", return_value="/opt/homebrew/bin/python3.11"), \
             patch("scripts._discover.os.execv", side_effect=OSError("no such file or directory")):
            mock_sys.version_info = (3, 9, 0)
            mock_sys.executable = "/usr/bin/python3"
            mock_sys.argv = ["-m", "scripts.foo"]
            mock_sys.stderr = sys.stderr
            try:
                maybe_reexec()
            except OSError:
                self.fail("maybe_reexec() must not let OSError from os.execv propagate")

    def test_execv_failure_prints_diagnostic_to_stderr(self):
        import io
        buf = io.StringIO()
        with patch("scripts._discover.sys") as mock_sys, \
             patch("scripts._discover.discover_python_path", return_value="/opt/homebrew/bin/python3.11"), \
             patch("scripts._discover.os.execv", side_effect=OSError("no such file or directory")):
            mock_sys.version_info = (3, 9, 0)
            mock_sys.executable = "/usr/bin/python3"
            mock_sys.argv = ["-m", "scripts.foo"]
            mock_sys.stderr = buf
            maybe_reexec()
        output = buf.getvalue()
        self.assertIn("/opt/homebrew/bin/python3.11", output)
        self.assertIn("setup.py", output)

    def test_env_sentinel_prevents_second_reexec(self):
        # Fix B, layer 2: a hard one-shot guard independent of reexec_target's
        # own path comparison -- if this process is itself the result of a
        # prior re-exec this invocation chain, never attempt another one, no
        # matter what reexec_target() would otherwise say.
        os.environ[_REEXEC_ENV_SENTINEL] = "1"
        with patch("scripts._discover.sys") as mock_sys, \
             patch("scripts._discover.discover_python_path", return_value="/opt/homebrew/bin/python3.11"), \
             patch("scripts._discover.os.execv") as mock_execv:
            mock_sys.version_info = (3, 9, 0)
            mock_sys.executable = "/usr/bin/python3"
            mock_sys.argv = ["-m", "scripts.foo"]
            mock_sys.stderr = sys.stderr
            maybe_reexec()
        mock_execv.assert_not_called()


if __name__ == "__main__":
    unittest.main()
