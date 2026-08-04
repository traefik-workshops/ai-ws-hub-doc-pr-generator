import subprocess
import unittest
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
        with patch("scripts.setup.sys.version_info", (3, 9, 0, "final", 0)):
            self.assertFalse(setup.check_python_version())


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
