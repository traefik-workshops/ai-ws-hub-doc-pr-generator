import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import setup


def _cp(returncode=0, stdout=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _fake_run(*, gh_auth=0, git_clean=True):
    """Build a _run side-effect: gh present+authed, git tree clean by default."""
    def run(cmd, *, capture=True):
        if cmd[:2] == ["which", "gh"]:
            return _cp(0)
        if cmd[:3] == ["gh", "auth", "status"]:
            return _cp(gh_auth)
        if cmd[:1] == ["git"] and "status" in cmd:
            return _cp(0, "" if git_clean else " M file.go\n")
        if cmd[:3] == ["gh", "api", "user"]:
            return _cp(0, "octocat")
        return _cp(0)
    return run


def _fake_discover(*, hub_doc=None, oss=None):
    calls = {"hub_doc": 0, "oss": 0}

    def discover_hub_doc():
        calls["hub_doc"] += 1
        return hub_doc

    def discover_oss():
        calls["oss"] += 1
        return oss

    ns = SimpleNamespace(
        discover_hub_doc=discover_hub_doc,
        discover_oss=discover_oss,
        persist_hub_doc=lambda p: None,
        CONFIG_PATH="/tmp/cfg.json",
    )
    return ns, calls


def _fake_run_for_main_check(*, branch="main", fetch_ok=True, behind=0):
    def run(cmd, *, capture=True):
        if cmd[:3] == ["git", "-C", "/work/hub-doc"] and cmd[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return _cp(0, f"{branch}\n")
        if cmd[3:6] == ["fetch", "-q", "origin"]:
            return _cp(0 if fetch_ok else 1)
        if cmd[3:] == ["rev-list", "--count", "main..origin/main"]:
            return _cp(0, f"{behind}\n")
        return _cp(0)
    return run


class TestCheckMainBranchState(unittest.TestCase):
    def test_warns_when_not_on_main(self):
        with patch("scripts.setup._run", side_effect=_fake_run_for_main_check(branch="old-merged-feature")), \
             patch("scripts.setup._print_warn") as warn:
            setup.check_main_branch_state("/work/hub-doc", label="hub-doc clone")
        self.assertTrue(any("old-merged-feature" in c.args[0] for c in warn.call_args_list))

    def test_warns_when_behind_origin_main(self):
        with patch("scripts.setup._run", side_effect=_fake_run_for_main_check(behind=5)), \
             patch("scripts.setup._print_warn") as warn:
            setup.check_main_branch_state("/work/hub-doc", label="hub-doc clone")
        self.assertTrue(any("5 commit" in c.args[0] for c in warn.call_args_list))

    def test_ok_when_on_main_and_up_to_date(self):
        with patch("scripts.setup._run", side_effect=_fake_run_for_main_check()), \
             patch("scripts.setup._print_warn") as warn, \
             patch("scripts.setup._print_ok") as ok:
            setup.check_main_branch_state("/work/hub-doc", label="hub-doc clone")
        warn.assert_not_called()
        self.assertTrue(any("up to date" in c.args[0] for c in ok.call_args_list))

    def test_fetch_failure_warns_but_does_not_raise(self):
        with patch("scripts.setup._run", side_effect=_fake_run_for_main_check(fetch_ok=False)), \
             patch("scripts.setup._print_warn") as warn:
            setup.check_main_branch_state("/work/hub-doc", label="hub-doc clone")
        self.assertTrue(any("fetch" in c.args[0].lower() for c in warn.call_args_list))


class TestFindCompatiblePython(unittest.TestCase):
    def test_finds_first_qualifying_candidate_via_which(self):
        def fake_run(cmd, *, capture=True):
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

    def test_falls_back_to_absolute_path_candidates(self):
        def fake_run(cmd, *, capture=True):
            if cmd[:1] == ["which"]:
                return _cp(1)
            if cmd[0] == "/opt/homebrew/bin/python3.11":
                return _cp(0, "3.11\n")
            return _cp(1)

        def fake_is_file(self):
            return str(self) == "/opt/homebrew/bin/python3.11"

        with patch("scripts.setup._run", side_effect=fake_run), \
             patch("scripts.setup.Path.is_file", fake_is_file):
            found = setup.find_compatible_python()
        self.assertEqual(found, "/opt/homebrew/bin/python3.11")

    def test_rejects_candidate_below_3_11(self):
        def fake_run(cmd, *, capture=True):
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

        def fake_run(cmd, *, capture=True):
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

    def test_passes_when_already_new_enough(self):
        with patch("scripts.setup.sys.version_info", (3, 12, 0, "final", 0)):
            self.assertTrue(setup.check_python_version())


class TestUniversalGate(unittest.TestCase):
    def test_passes_with_no_impl_repo(self):
        with patch("scripts.setup._run", side_effect=_fake_run()):
            self.assertEqual(setup.main(["--check"]), 0)

    def test_gh_unauthenticated_fails(self):
        with patch("scripts.setup._run", side_effect=_fake_run(gh_auth=1)):
            self.assertEqual(setup.main(["--check"]), 1)


class TestFlowResources(unittest.TestCase):
    def test_oss_flow_does_not_require_hub_doc(self):
        # The regression guard: an OSS engineer with no hub-doc clone must NOT be
        # blocked, and hub-doc discovery must never even be consulted.
        ns, calls = _fake_discover(hub_doc=None, oss="/work/traefik")
        with patch("scripts.setup._run", side_effect=_fake_run()), \
             patch("scripts.setup._import_discover", return_value=ns):
            rc = setup.main(["--check", "--impl-repo", "traefik/traefik"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls["hub_doc"], 0)
        self.assertEqual(calls["oss"], 1)

    def test_oss_flow_fails_when_cwd_not_a_repo(self):
        ns, _ = _fake_discover(oss=None)
        with patch("scripts.setup._run", side_effect=_fake_run()), \
             patch("scripts.setup._import_discover", return_value=ns):
            rc = setup.main(["--check", "--impl-repo", "traefik/traefik"])
        self.assertEqual(rc, 1)

    def test_hub_flow_with_clone_passes(self):
        ns, calls = _fake_discover(hub_doc="/work/hub-doc")
        with patch("scripts.setup._run", side_effect=_fake_run()), \
             patch("scripts.setup._import_discover", return_value=ns):
            rc = setup.main(["--check", "--impl-repo", "traefik/traefik-hub"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls["hub_doc"], 1)

    def test_hub_flow_missing_clone_in_check_mode_fails(self):
        ns, _ = _fake_discover(hub_doc=None)
        with patch("scripts.setup._run", side_effect=_fake_run()), \
             patch("scripts.setup._import_discover", return_value=ns):
            rc = setup.main(["--check", "--impl-repo", "traefik/traefik-hub"])
        self.assertEqual(rc, 1)

    def test_unknown_repo_needs_no_resources(self):
        ns, calls = _fake_discover(hub_doc=None, oss=None)
        with patch("scripts.setup._run", side_effect=_fake_run()), \
             patch("scripts.setup._import_discover", return_value=ns):
            rc = setup.main(["--check", "--impl-repo", "acme/widgets"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls["hub_doc"], 0)
        self.assertEqual(calls["oss"], 0)


if __name__ == "__main__":
    unittest.main()
