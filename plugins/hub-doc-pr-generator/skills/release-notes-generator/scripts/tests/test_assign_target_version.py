import tempfile
import unittest
from pathlib import Path
from scripts.assign_target_version import assign, main

FRAGMENT_BARE = "---\nshape: ea-subsection\nsource_prs: [964]\ntarget_version: unassigned\n---\n\n#### Bedrock Mantle\n"
FRAGMENT_DOUBLE_QUOTED = FRAGMENT_BARE.replace("target_version: unassigned", 'target_version: "unassigned"')
FRAGMENT_SINGLE_QUOTED = FRAGMENT_BARE.replace("target_version: unassigned", "target_version: 'unassigned'")
FRAGMENT_ALREADY_ASSIGNED = FRAGMENT_BARE.replace("target_version: unassigned", "target_version: v3.20.0-ea.8")


class TestAssign(unittest.TestCase):
    def test_replaces_bare_unassigned(self):
        result = assign(FRAGMENT_BARE, "v3.21.0-ea.1")
        self.assertIn("target_version: v3.21.0-ea.1", result)
        self.assertNotIn("unassigned", result)

    def test_replaces_double_quoted_unassigned(self):
        """Regression test: the bug this script was extracted to fix -- a
        literal .replace('target_version: unassigned', ...) silently no-ops on
        this exact input."""
        result = assign(FRAGMENT_DOUBLE_QUOTED, "v3.21.0-ea.1")
        self.assertIn("target_version: v3.21.0-ea.1", result)
        self.assertNotIn("unassigned", result)

    def test_replaces_single_quoted_unassigned(self):
        result = assign(FRAGMENT_SINGLE_QUOTED, "v3.21.0-ea.1")
        self.assertIn("target_version: v3.21.0-ea.1", result)
        self.assertNotIn("unassigned", result)

    def test_raises_when_already_assigned(self):
        with self.assertRaises(ValueError):
            assign(FRAGMENT_ALREADY_ASSIGNED, "v3.21.0-ea.1")

    def test_raises_rather_than_silently_no_op(self):
        """The literal bug being fixed: never return content unchanged."""
        with self.assertRaises(ValueError):
            assign("no target_version line at all\n", "v3.21.0-ea.1")

    def test_written_version_is_never_quoted(self):
        result = assign(FRAGMENT_DOUBLE_QUOTED, "v3.21.0-ea.1")
        self.assertIn('target_version: v3.21.0-ea.1', result)
        self.assertNotIn('target_version: "v3.21.0-ea.1"', result)


class TestMain(unittest.TestCase):
    def test_writes_file_and_returns_zero(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "964-bedrock-mantle.mdx"
            path.write_text(FRAGMENT_BARE)
            rc = main(["--fragment", str(path), "--version", "v3.21.0-ea.1"])
            self.assertEqual(rc, 0)
            self.assertIn("target_version: v3.21.0-ea.1", path.read_text())

    def test_returns_nonzero_and_leaves_file_untouched_on_no_match(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "964-bedrock-mantle.mdx"
            path.write_text(FRAGMENT_ALREADY_ASSIGNED)
            rc = main(["--fragment", str(path), "--version", "v3.21.0-ea.1"])
            self.assertEqual(rc, 1)
            self.assertEqual(path.read_text(), FRAGMENT_ALREADY_ASSIGNED)


if __name__ == "__main__":
    unittest.main()
