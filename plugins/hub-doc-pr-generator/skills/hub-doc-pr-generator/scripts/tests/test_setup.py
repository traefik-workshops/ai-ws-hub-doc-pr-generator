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
