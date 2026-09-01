import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import setup


def _cp(returncode=0, stdout=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _fake_run(*, gh_auth=0, git_clean=True):
    def run(cmd):
        if cmd[:2] == ["which", "gh"]:
            return _cp(0)
        if cmd[:3] == ["gh", "auth", "status"]:
            return _cp(gh_auth)
        if cmd[:1] == ["git"] and "status" in cmd:
            return _cp(0, "" if git_clean else " M file.mdx\n")
        return _cp(0)
    return run


class TestCheckPythonVersion(unittest.TestCase):
    def test_passes_on_3_11_plus(self):
        with patch("scripts.setup.sys.version_info", (3, 12, 0, "final", 0)):
            self.assertTrue(setup.check_python_version())

    def test_fails_below_3_11(self):
        with patch("scripts.setup.sys.version_info", (3, 9, 0, "final", 0)), \
             patch("scripts.setup.find_compatible_python", return_value=None):
            self.assertFalse(setup.check_python_version())


class TestFindCompatiblePython(unittest.TestCase):
    """Fix E (PR #30 round 2 review): this skill's setup.py had no
    find_compatible_python()-equivalent at all -- ported from the sibling
    hub-doc-pr-generator skill's setup.py, same approach and candidate list."""

    def test_finds_first_qualifying_candidate_via_which(self):
        def fake_run(cmd):
            if cmd[:1] == ["which"]:
                if cmd[1] == "python3.11":
                    return _cp(0, "/opt/homebrew/bin/python3.11\n")
                return _cp(1)
            if cmd[0] == "/opt/homebrew/bin/python3.11":
                return _cp(0, "3.11\n")
            return _cp(1)
        with patch("scripts.setup._run", side_effect=fake_run), \
             patch("scripts.setup.Path.is_file", return_value=False):
            found = setup.find_compatible_python()
        self.assertEqual(found, "/opt/homebrew/bin/python3.11")

    def test_rejects_candidate_below_3_11(self):
        def fake_run(cmd):
            if cmd[:1] == ["which"] and cmd[1] == "python3.11":
                return _cp(0, "/usr/bin/python3.11\n")
            if cmd[:1] == ["which"]:
                return _cp(1)
            if cmd[0] == "/usr/bin/python3.11":
                return _cp(0, "3.9\n")
            return _cp(1)
        with patch("scripts.setup._run", side_effect=fake_run), \
             patch("scripts.setup.Path.is_file", return_value=False):
            found = setup.find_compatible_python()
        self.assertIsNone(found)

    def test_returns_none_when_nothing_found(self):
        with patch("scripts.setup._run", return_value=_cp(1)), \
             patch("scripts.setup.Path.is_file", return_value=False):
            self.assertIsNone(setup.find_compatible_python())


class TestCheckPythonVersionDiscovery(unittest.TestCase):
    def test_persists_and_reports_found_interpreter_when_too_old(self):
        persisted = {}
        ns = SimpleNamespace(
            persist_python_path=lambda p: persisted.setdefault("path", p),
            CONFIG_PATH="/tmp/cfg.json",
        )

        def fake_run(cmd):
            if cmd[:1] == ["which"] and cmd[1] == "python3.11":
                return _cp(0, "/opt/homebrew/bin/python3.11\n")
            if cmd[:1] == ["which"]:
                return _cp(1)
            if cmd[0] == "/opt/homebrew/bin/python3.11":
                return _cp(0, "3.11\n")
            return _cp(1)

        with patch("scripts.setup.sys.version_info", (3, 9, 0, "final", 0)), \
             patch("scripts.setup._run", side_effect=fake_run), \
             patch("scripts.setup.Path.is_file", return_value=False), \
             patch("scripts.setup._import_discover", return_value=ns):
            ok = setup.check_python_version()
        self.assertFalse(ok)
        self.assertEqual(persisted.get("path"), "/opt/homebrew/bin/python3.11")

    def test_reports_when_nothing_found(self):
        with patch("scripts.setup.sys.version_info", (3, 9, 0, "final", 0)), \
             patch("scripts.setup._run", return_value=_cp(1)), \
             patch("scripts.setup.Path.is_file", return_value=False), \
             patch("scripts.setup._print_error") as err:
            ok = setup.check_python_version()
        self.assertFalse(ok)
        self.assertTrue(any("No Python 3.11+" in c.args[0] for c in err.call_args_list))


class TestCheckGhCli(unittest.TestCase):
    def test_fails_when_gh_not_on_path(self):
        with patch("scripts.setup._run", side_effect=lambda cmd: _cp(1)):
            self.assertFalse(setup.check_gh_cli())

    def test_fails_when_not_authenticated(self):
        with patch("scripts.setup._run", side_effect=_fake_run(gh_auth=1)):
            self.assertFalse(setup.check_gh_cli())

    def test_passes_when_present_and_authed(self):
        with patch("scripts.setup._run", side_effect=_fake_run()):
            self.assertTrue(setup.check_gh_cli())


class TestEnsureHubDoc(unittest.TestCase):
    def test_found_automatically(self):
        with patch("scripts.setup._run", side_effect=_fake_run()), \
             patch("scripts._discover.discover_hub_doc", return_value="/work/hub-doc") as disc:
            ok, path = setup.ensure_hub_doc(check_mode=True)
        self.assertTrue(ok)
        self.assertEqual(path, "/work/hub-doc")
        self.assertEqual(disc.call_count, 1)

    def test_check_mode_fails_when_not_found(self):
        with patch("scripts.setup._run", side_effect=_fake_run()), \
             patch("scripts._discover.discover_hub_doc", return_value=None):
            ok, path = setup.ensure_hub_doc(check_mode=True)
        self.assertFalse(ok)
        self.assertIsNone(path)


class TestMain(unittest.TestCase):
    def test_universal_gate_failure_short_circuits(self):
        with patch("scripts.setup.check_python_version", return_value=False):
            self.assertEqual(setup.main(["--check"]), 1)

    def test_full_success_path(self):
        with patch("scripts.setup.check_python_version", return_value=True), \
             patch("scripts.setup.check_gh_cli", return_value=True), \
             patch("scripts.setup.ensure_hub_doc", return_value=(True, "/work/hub-doc")):
            self.assertEqual(setup.main(["--check"]), 0)

    def test_missing_hub_doc_fails(self):
        with patch("scripts.setup.check_python_version", return_value=True), \
             patch("scripts.setup.check_gh_cli", return_value=True), \
             patch("scripts.setup.ensure_hub_doc", return_value=(False, None)):
            self.assertEqual(setup.main(["--check"]), 1)


if __name__ == "__main__":
    unittest.main()
