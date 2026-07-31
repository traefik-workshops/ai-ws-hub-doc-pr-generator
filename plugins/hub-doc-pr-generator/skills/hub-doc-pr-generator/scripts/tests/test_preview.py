import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from scripts.preview import apply_edits, FileEdit
from unittest.mock import patch
from scripts.preview import (
    detect_pretty_tools,
    render_diff_to_stdout, render_pages_to_stdout,
    _fix_file_permissions, run_lint_fix, LintFixResult, render_manual_checks_section,
    apply_edits_with_lint_fix, check_table_completeness,
)


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

    def test_new_file_appears_in_diff(self):
        """New (previously untracked) files must be visible in git_diff output."""
        from scripts.preview import git_diff
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            edits = [FileEdit(path="docs/new.md", content="# Hello\n", mode="create")]
            apply_edits(repo_path=str(d), branch="docs/test", edits=edits)
            diff = git_diff(str(d))
            self.assertIn("docs/new.md", diff)
            self.assertIn("Hello", diff)

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


class TestApplyEditsValidation(unittest.TestCase):
    def test_patch_mode_raises(self):
        """Mode 'patch' is not implemented and must raise, not silently overwrite."""
        with self.assertRaises((ValueError, NotImplementedError)):
            apply_edits(
                repo_path="/irrelevant",
                branch="docs/x",
                edits=[FileEdit(path="docs/x.md", content="hi", mode="patch")],  # type: ignore[arg-type]
            )


class TestFixFilePermissions(unittest.TestCase):
    def test_fixes_executable_doc_file(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            f = d / "docs" / "new.md"
            f.parent.mkdir(parents=True)
            f.write_text("hello\n")
            f.chmod(0o755)
            fixed = _fix_file_permissions(str(d), ["docs/new.md"])
            self.assertEqual(f.stat().st_mode & 0o777, 0o644)
        self.assertEqual(len(fixed), 1)

    def test_leaves_non_executable_file_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            f = d / "docs" / "new.md"
            f.parent.mkdir(parents=True)
            f.write_text("hello\n")
            f.chmod(0o644)
            fixed = _fix_file_permissions(str(d), ["docs/new.md"])
        self.assertEqual(fixed, [])


class TestRunLintFix(unittest.TestCase):
    def test_hub_runs_autofix_then_checks(self):
        with patch("scripts.preview.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""
            result = run_lint_fix(repo_path="/hub-doc", impl_repo="traefik/traefik-hub", written=[])
        self.assertIsInstance(result, LintFixResult)
        self.assertEqual(result.unresolved, [])
        commands_joined = " ".join(result.commands)
        self.assertIn("docs:markdown --fix", commands_joined)
        self.assertIn("docs:alex", commands_joined)

    def test_hub_captures_unfixable_markdownlint_errors(self):
        def fake_run(cmd, **kwargs):
            r = type("R", (), {"stdout": "", "stderr": "", "returncode": 0})()
            if cmd[:2] == ["yarn", "docs:markdown"] and "--fix" not in cmd:
                r.returncode, r.stderr = 1, "MD013 line too long"
            return r
        with patch("scripts.preview.subprocess.run", side_effect=fake_run):
            result = run_lint_fix(repo_path="/hub-doc", impl_repo="traefik/traefik-hub", written=[])
        self.assertTrue(any("MD013" in u for u in result.unresolved))

    def test_hub_captures_alex_flags_as_unresolved_never_autofixed(self):
        def fake_run(cmd, **kwargs):
            r = type("R", (), {"stdout": "", "stderr": "", "returncode": 0})()
            if cmd == ["yarn", "docs:alex"]:
                r.returncode, r.stdout = 1, "warning: `guys` may be insensitive"
            return r
        with patch("scripts.preview.subprocess.run", side_effect=fake_run):
            result = run_lint_fix(repo_path="/hub-doc", impl_repo="traefik/traefik-hub", written=[])
        self.assertTrue(any("guys" in u for u in result.unresolved))
        # alex has no --fix flag anywhere in the commands we run
        self.assertTrue(all("alex --fix" not in c for c in result.commands))

    def test_oss_runs_mkdocs_build_strict(self):
        with patch("scripts.preview.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""
            result = run_lint_fix(repo_path="/traefik", impl_repo="traefik/traefik", written=[])
        self.assertEqual(result.unresolved, [])
        self.assertIn("mkdocs", " ".join(result.commands))

    def test_oss_failure_is_unresolved_not_raised(self):
        with patch("scripts.preview.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "broken link"
            result = run_lint_fix(repo_path="/traefik", impl_repo="traefik/traefik", written=[])
        self.assertTrue(any("broken link" in u for u in result.unresolved))


class TestApplyEditsWithLintFix(unittest.TestCase):
    def test_permission_fix_is_visible_in_staged_diff(self):
        """apply_edits stages the pre-fix mode; the permission fix must be re-staged
        or the diff engineers see would silently omit it."""
        from scripts.preview import git_diff
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            existing = d / "docs" / "existing.md"
            existing.parent.mkdir(parents=True)
            existing.write_text("old\n")
            existing.chmod(0o755)
            subprocess.run(["git", "add", "docs/existing.md"], cwd=d, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                            "commit", "-qm", "add"], cwd=d, check=True)

            edits = [FileEdit(path="docs/existing.md", content="new\n", mode="overwrite")]
            # Patching subprocess.run patches the module globally, which would also
            # silently no-op _git.run's real `git` calls (same subprocess module
            # object) — fake only the yarn/mkdocs commands, let git through for real.
            real_run = subprocess.run

            def fake_run(cmd, **kwargs):
                if cmd[0] == "git":
                    return real_run(cmd, **kwargs)
                return type("R", (), {"stdout": "", "stderr": "", "returncode": 0})()

            with patch("scripts.preview.subprocess.run", side_effect=fake_run):
                written, lint = apply_edits_with_lint_fix(
                    repo_path=str(d), branch="docs/test",
                    impl_repo="traefik/traefik-hub", edits=edits,
                )
            diff = git_diff(str(d))
            self.assertEqual(existing.stat().st_mode & 0o777, 0o644)
            self.assertIn("old mode 100755", diff)
            self.assertIn("new mode 100644", diff)
            self.assertEqual(written, ["docs/existing.md"])
            self.assertIsInstance(lint, LintFixResult)


class TestCheckTableCompleteness(unittest.TestCase):
    def test_flags_ellipsis_placeholder_in_table_row(self):
        edits = [FileEdit(
            path="docs/reference.md",
            content="| Format | Description |\n| --- | --- |\n| json, xml, … | formats |\n",
            mode="overwrite",
        )]
        findings = check_table_completeness(edits)
        self.assertTrue(any("docs/reference.md" in f for f in findings))

    def test_flags_etc_placeholder_in_table_row(self):
        edits = [FileEdit(
            path="docs/reference.md",
            content="| Format | Description |\n| --- | --- |\n| json, xml, etc. | formats |\n",
            mode="overwrite",
        )]
        findings = check_table_completeness(edits)
        self.assertEqual(len(findings), 1)

    def test_complete_table_is_not_flagged(self):
        edits = [FileEdit(
            path="docs/reference.md",
            content="| Format | Description |\n| --- | --- |\n| json | JSON format |\n| xml | XML format |\n",
            mode="overwrite",
        )]
        self.assertEqual(check_table_completeness(edits), [])

    def test_non_table_prose_with_ellipsis_is_not_flagged(self):
        edits = [FileEdit(
            path="docs/reference.md",
            content="This is prose that trails off…\n",
            mode="create",
        )]
        self.assertEqual(check_table_completeness(edits), [])

    def test_non_markdown_files_are_skipped(self):
        edits = [FileEdit(
            path="sidebars.js",
            content="| json, xml, … |\n",
            mode="overwrite",
        )]
        self.assertEqual(check_table_completeness(edits), [])

    def test_wired_into_manual_checks_via_apply_edits_with_lint_fix(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            edits = [FileEdit(
                path="docs/new.md",
                content="| Format | Description |\n| --- | --- |\n| json, xml, … | formats |\n",
                mode="create",
            )]
            with patch("scripts.preview.subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = ""
                mock_run.return_value.stderr = ""
                _, lint = apply_edits_with_lint_fix(
                    repo_path=str(d), branch="docs/test",
                    impl_repo="traefik/traefik-hub", edits=edits,
                )
        self.assertTrue(any("docs/new.md" in u for u in lint.unresolved))
        md = render_manual_checks_section(lint.unresolved)
        self.assertIn("## Manual checks required", md)


class TestRenderManualChecksSection(unittest.TestCase):
    def test_empty_when_nothing_unresolved(self):
        self.assertEqual(render_manual_checks_section([]), "")

    def test_renders_checklist_for_unresolved_items(self):
        md = render_manual_checks_section(["alex: flagged `guys`"])
        self.assertIn("## Manual checks required", md)
        self.assertIn("- [ ] alex: flagged `guys`", md)


class TestPrettyRendering(unittest.TestCase):
    def test_detect_pretty_tools(self):
        def which(name):
            return f"/usr/bin/{name}" if name in ("delta", "glow") else None
        with patch("scripts.preview.shutil.which", side_effect=which):
            tools = detect_pretty_tools()
        self.assertEqual(tools, {"diff": "delta", "page": "glow"})

    def test_detect_prefers_glow_over_bat(self):
        with patch("scripts.preview.shutil.which",
                   side_effect=lambda n: "/x" if n in ("bat", "glow") else None):
            self.assertEqual(detect_pretty_tools()["page"], "glow")

    def test_detect_none_when_absent(self):
        with patch("scripts.preview.shutil.which", return_value=None):
            self.assertEqual(detect_pretty_tools(), {"diff": None, "page": None})

    def test_render_diff_falls_back_to_plain(self):
        # No delta on PATH → emit the raw diff, no subprocess.
        with patch("scripts.preview.shutil.which", return_value=None), \
             patch("scripts.preview.git_diff", return_value="diff --git a/x b/x\n+hi\n"), \
             patch("scripts.preview.subprocess.run") as run:
            buf = io.StringIO()
            with redirect_stdout(buf):
                render_diff_to_stdout("/repo")
        run.assert_not_called()
        self.assertIn("+hi", buf.getvalue())

    def test_render_diff_uses_delta_when_present(self):
        with patch("scripts.preview.shutil.which", side_effect=lambda n: "/x" if n == "delta" else None), \
             patch("scripts.preview.git_diff", return_value="diff --git a/x b/x\n+hi\n"), \
             patch("scripts.preview.subprocess.run") as run:
            render_diff_to_stdout("/repo")
        self.assertEqual(run.call_args[0][0][0], "delta")

    def test_render_pages_plain_skips_non_markdown(self):
        edits = [
            FileEdit(path="docs/page.md", content="# Title\n", mode="create"),
            FileEdit(path="sidebars.js", content="module.exports={}\n", mode="overwrite"),
        ]
        with patch("scripts.preview.shutil.which", return_value=None), \
             patch("scripts.preview.subprocess.run") as run:
            buf = io.StringIO()
            with redirect_stdout(buf):
                render_pages_to_stdout(edits)
        run.assert_not_called()
        out = buf.getvalue()
        self.assertIn("docs/page.md", out)
        self.assertIn("# Title", out)
        self.assertNotIn("sidebars.js", out)  # non-markdown skipped


if __name__ == "__main__":
    unittest.main()
