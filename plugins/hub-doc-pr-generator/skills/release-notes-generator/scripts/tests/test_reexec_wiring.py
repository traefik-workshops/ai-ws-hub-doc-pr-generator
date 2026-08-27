"""Representative real-invocation check that maybe_reexec() fires before
main() for release-notes-generator scripts too. The exhaustive, both-skills
source-text check for every wired script lives in the sibling
hub-doc-pr-generator skill's test_reexec_wiring.py (grep-based meta-test);
this just confirms it also actually happens at real invocation time here,
not only via source inspection.
"""
from __future__ import annotations

import runpy
import sys
import unittest
from unittest.mock import patch


class TestReexecActuallyInvoked(unittest.TestCase):
    def test_render_entry_invokes_maybe_reexec_before_main(self):
        with patch("scripts._discover.maybe_reexec") as mock_reexec, \
             patch.object(sys, "argv", ["render_entry.py"]):
            with self.assertRaises(SystemExit):
                # No required args given -> argparse exits(2) inside main().
                runpy.run_module("scripts.render_entry", run_name="__main__")
            mock_reexec.assert_called_once()

    def test_push_invokes_maybe_reexec_before_main(self):
        with patch("scripts._discover.maybe_reexec") as mock_reexec, \
             patch.object(sys, "argv", ["push.py"]):
            with self.assertRaises(SystemExit):
                runpy.run_module("scripts.push", run_name="__main__")
            mock_reexec.assert_called_once()


if __name__ == "__main__":
    unittest.main()
