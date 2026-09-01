import tempfile
import unittest
from pathlib import Path

from scripts.rename_legacy_fragments import find_legacy_fragments, main, rename


class TestFindLegacyFragments(unittest.TestCase):
    def test_missing_dir_returns_empty(self):
        self.assertEqual(find_legacy_fragments(Path("/nonexistent/dir")), [])

    def test_underscore_prefixed_fragment_is_not_legacy(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "_964-bedrock-mantle.mdx").write_text("x")
            self.assertEqual(find_legacy_fragments(d), [])

    def test_unprefixed_fragment_is_legacy(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            legacy = d / "964-bedrock-mantle.mdx"
            legacy.write_text("x")
            self.assertEqual(find_legacy_fragments(d), [legacy])

    def test_non_fragment_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "README.md").write_text("x")
            (d / "not-a-pr-number.mdx").write_text("x")
            self.assertEqual(find_legacy_fragments(d), [])


class TestRename(unittest.TestCase):
    def test_renames_to_underscore_prefixed(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            legacy = d / "964-bedrock-mantle.mdx"
            legacy.write_text("content")
            new_path = rename(legacy)
            self.assertEqual(new_path.name, "_964-bedrock-mantle.mdx")
            self.assertTrue(new_path.exists())
            self.assertFalse(legacy.exists())
            self.assertEqual(new_path.read_text(), "content")

    def test_refuses_to_overwrite_existing_target(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            legacy = d / "964-bedrock-mantle.mdx"
            legacy.write_text("old")
            (d / "_964-bedrock-mantle.mdx").write_text("already here")
            with self.assertRaises(FileExistsError):
                rename(legacy)
            # Neither file was touched by the failed rename.
            self.assertTrue(legacy.exists())
            self.assertEqual(legacy.read_text(), "old")


class TestMainCli(unittest.TestCase):
    def test_dry_run_does_not_rename(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            legacy = d / "964-bedrock-mantle.mdx"
            legacy.write_text("x")
            rc = main(["--release-notes-dir", str(d)])
            self.assertEqual(rc, 0)
            self.assertTrue(legacy.exists())

    def test_apply_renames(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            legacy = d / "964-bedrock-mantle.mdx"
            legacy.write_text("x")
            rc = main(["--release-notes-dir", str(d), "--apply"])
            self.assertEqual(rc, 0)
            self.assertFalse(legacy.exists())
            self.assertTrue((d / "_964-bedrock-mantle.mdx").exists())

    def test_no_legacy_fragments_is_a_clean_noop(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "_964-bedrock-mantle.mdx").write_text("x")
            rc = main(["--release-notes-dir", str(d), "--apply"])
            self.assertEqual(rc, 0)
            self.assertTrue((d / "_964-bedrock-mantle.mdx").exists())


if __name__ == "__main__":
    unittest.main()
