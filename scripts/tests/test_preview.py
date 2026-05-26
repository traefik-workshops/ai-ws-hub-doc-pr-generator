import subprocess
import tempfile
import unittest
from pathlib import Path
from scripts.preview import apply_edits, FileEdit


def _init_git(d: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                    "commit", "--allow-empty", "-qm", "init"], cwd=d, check=True)


class TestApplyEdits(unittest.TestCase):
    def test_writes_new_file_and_returns_paths(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            edits = [FileEdit(path="docs/new.md", content="hello\n", mode="create")]
            written = apply_edits(repo_path=str(d), branch="docs/test", edits=edits)
            self.assertEqual(written, ["docs/new.md"])
            self.assertTrue((d / "docs/new.md").is_file())

    def test_updates_existing_file(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            (d / "existing.md").write_text("old\n")
            subprocess.run(["git", "add", "existing.md"], cwd=d, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                            "commit", "-qm", "add"], cwd=d, check=True)
            edits = [FileEdit(path="existing.md", content="new\n", mode="overwrite")]
            apply_edits(repo_path=str(d), branch="docs/test", edits=edits)
            self.assertEqual((d / "existing.md").read_text(), "new\n")


if __name__ == "__main__":
    unittest.main()
