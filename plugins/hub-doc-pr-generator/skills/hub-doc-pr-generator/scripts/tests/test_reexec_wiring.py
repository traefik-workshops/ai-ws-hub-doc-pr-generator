"""Confirms maybe_reexec() is actually wired into each script's CLI entrypoint.

maybe_reexec() (in _discover.py) is a self-correcting-interpreter guard: it's
useless unless it actually runs before main() on every real `python script.py`
invocation. This was previously defined + unit-tested but never called from
any script's `if __name__ == "__main__":` guard, so the feature did nothing
at runtime (see PR review round). These tests lock in the wiring.
"""
from __future__ import annotations

import re
import runpy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# this_file -> tests -> scripts -> hub-doc-pr-generator (skill dir) -> skills
_PLUGIN_ROOT = Path(__file__).resolve().parents[3]

# Every script with a `def main(argv...` CLI entrypoint, across both skills,
# that is expected to call _discover.maybe_reexec() as the first statement
# inside its `if __name__ == "__main__":` guard.
_WIRED_SCRIPTS = [
    "hub-doc-pr-generator/scripts/_discover.py",
    "hub-doc-pr-generator/scripts/fetch_issue.py",
    "hub-doc-pr-generator/scripts/classify.py",
    "hub-doc-pr-generator/scripts/extract_neighbor_structure.py",
    "hub-doc-pr-generator/scripts/fetch_pr.py",
    "hub-doc-pr-generator/scripts/preview.py",
    "hub-doc-pr-generator/scripts/locate_targets.py",
    "hub-doc-pr-generator/scripts/setup.py",
    "hub-doc-pr-generator/scripts/fetch_grounding.py",
    "hub-doc-pr-generator/scripts/write_flags.py",
    "hub-doc-pr-generator/scripts/open_pr.py",
    "release-notes-generator/scripts/_discover.py",
    "release-notes-generator/scripts/assemble_section.py",
    "release-notes-generator/scripts/compat_matrix.py",
    "release-notes-generator/scripts/collect_fragments.py",
    "release-notes-generator/scripts/assign_target_version.py",
    "release-notes-generator/scripts/push.py",
    "release-notes-generator/scripts/preview.py",
    "release-notes-generator/scripts/classify_commits.py",
    "release-notes-generator/scripts/fetch_release_range.py",
    "release-notes-generator/scripts/dedup_versions.py",
    "release-notes-generator/scripts/setup.py",
    "release-notes-generator/scripts/render_entry.py",
]

# Matches the `if __name__ == "__main__":` guard block up to end of file (these
# scripts all put that guard last), so we can look for maybe_reexec() only
# within the guard, before any sys.exit(main(...)) call.
_GUARD_RE = re.compile(r'if __name__ == "__main__":.*\n(?P<body>(?:.*\n)*)')
_REEXEC_CALL_RE = re.compile(r"\bmaybe_reexec\(\)")
_MAIN_CALL_RE = re.compile(r"\bmain\(")


class TestReexecWiring(unittest.TestCase):
    def test_every_listed_script_exists(self):
        for rel in _WIRED_SCRIPTS:
            self.assertTrue((_PLUGIN_ROOT / rel).is_file(), f"missing {rel}")

    def test_every_listed_script_calls_maybe_reexec_before_main_in_guard(self):
        failures = []
        for rel in _WIRED_SCRIPTS:
            text = (_PLUGIN_ROOT / rel).read_text()
            guard_match = _GUARD_RE.search(text)
            if not guard_match:
                failures.append(f"{rel}: no `if __name__ == '__main__':` guard found")
                continue
            body = guard_match.group("body")
            reexec_match = _REEXEC_CALL_RE.search(body)
            main_match = _MAIN_CALL_RE.search(body)
            if not reexec_match:
                failures.append(f"{rel}: maybe_reexec() not called in __main__ guard")
                continue
            if main_match and reexec_match.start() > main_match.start():
                failures.append(f"{rel}: maybe_reexec() called after main(), not before")
        self.assertEqual(failures, [], "\n".join(failures))


class TestReexecActuallyInvoked(unittest.TestCase):
    """Representative, real-invocation checks: run a couple of scripts with
    run_name="__main__" (as if `python -m scripts.X` were executed for real)
    and confirm maybe_reexec() fires before main() does its work, rather than
    just checking source text. `scripts._discover.maybe_reexec` is a single
    shared function object regardless of which script re-imports `_discover`,
    so patching it here also patches what the freshly executed __main__ code
    calls."""

    def test_classify_invokes_maybe_reexec_before_main(self):
        with patch("scripts._discover.maybe_reexec") as mock_reexec, \
             patch.object(sys, "argv", ["classify.py"]):
            with self.assertRaises(SystemExit):
                # No required args given -> argparse exits(2) inside main().
                # If maybe_reexec() had not already run by then, the mock
                # would never be called at all.
                runpy.run_module("scripts.classify", run_name="__main__")
            mock_reexec.assert_called_once()

    def test_locate_targets_invokes_maybe_reexec_before_main(self):
        with patch("scripts._discover.maybe_reexec") as mock_reexec, \
             patch.object(sys, "argv", ["locate_targets.py"]):
            with self.assertRaises(SystemExit):
                runpy.run_module("scripts.locate_targets", run_name="__main__")
            mock_reexec.assert_called_once()

    def test_fetch_pr_invokes_maybe_reexec_before_main(self):
        with patch("scripts._discover.maybe_reexec") as mock_reexec, \
             patch.object(sys, "argv", ["fetch_pr.py"]):
            with self.assertRaises(SystemExit):
                runpy.run_module("scripts.fetch_pr", run_name="__main__")
            mock_reexec.assert_called_once()


if __name__ == "__main__":
    unittest.main()
