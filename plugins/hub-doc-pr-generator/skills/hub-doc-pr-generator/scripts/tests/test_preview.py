import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from scripts.preview import apply_edits, FileEdit
from unittest.mock import patch
from scripts import _git
from scripts.preview import (
    detect_pretty_tools,
    render_diff_to_stdout, render_pages_to_stdout,
    _fix_file_permissions, run_lint_fix, LintFixResult, render_manual_checks_section,
    apply_edits_with_lint_fix, check_table_completeness, check_placeholder_version,
    _dirty_paths, _stash_unrelated_changes, _filter_to_written_paths, _checkout_branch,
)


def _init_git(d: Path) -> None:
    """A repo with a self-referencing 'origin' remote and a fetched 'main', so
    _checkout_branch's `fetch origin main` + `checkout -b <branch> origin/main`
    has something real to branch from — matching what a real hub-doc clone
    looks like, instead of a bare local-only repo."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                    "commit", "--allow-empty", "-qm", "init"], cwd=d, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(d)], cwd=d, check=True)
    subprocess.run(["git", "fetch", "-q", "origin"], cwd=d, check=True)


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

    def test_new_branch_does_not_inherit_stale_checked_out_branch(self):
        """Regression for a broken PR (#965): a NEW doc branch must be cut from
        origin/main, never from whatever branch happened to be checked out.
        Simulates a clone left on an old, already-merged feature branch with
        commits that aren't on main."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            subprocess.run(["git", "checkout", "-q", "-b", "old-merged-feature"], cwd=d, check=True)
            (d / "unrelated.txt").write_text("leftover work\n")
            subprocess.run(["git", "add", "unrelated.txt"], cwd=d, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                            "commit", "-qm", "stale unrelated commit"], cwd=d, check=True)
            # Clone is left checked out on the stale branch, exactly like the bug report.

            edits = [FileEdit(path="docs/new.md", content="hello\n", mode="create")]
            apply_edits(repo_path=str(d), branch="docs/new-feature", edits=edits)

            log = subprocess.run(
                ["git", "log", "--format=%s", "origin/main..docs/new-feature"],
                cwd=d, capture_output=True, text=True, check=True,
            ).stdout
            self.assertNotIn("stale unrelated commit", log)
            self.assertFalse((d / "unrelated.txt").exists())

    def test_existing_local_branch_is_reused_not_recreated(self):
        """The update-existing-doc-PR flow: a branch that already exists locally
        (its own legitimate history diverging from main) must be checked out
        as-is, not recreated from origin/main."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            subprocess.run(["git", "checkout", "-q", "-b", "docs/existing-pr"], cwd=d, check=True)
            (d / "docs").mkdir()
            (d / "docs/prior.md").write_text("prior work\n")
            subprocess.run(["git", "add", "docs/prior.md"], cwd=d, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                            "commit", "-qm", "prior doc PR commit"], cwd=d, check=True)
            subprocess.run(["git", "checkout", "-q", "main"], cwd=d, check=True)

            edits = [FileEdit(path="docs/new.md", content="more\n", mode="create")]
            apply_edits(repo_path=str(d), branch="docs/existing-pr", edits=edits)

            self.assertTrue((d / "docs/prior.md").is_file())
            self.assertTrue((d / "docs/new.md").is_file())


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


class TestFilterToWrittenPaths(unittest.TestCase):
    def test_keeps_only_lines_mentioning_written_files(self):
        output = (
            "docs/unrelated-a.md:3:1 MD013 line too long\n"
            "docs/new.md:12:5 MD013 line too long\n"
            "docs/unrelated-b.mdx:1:1 MD041 first line heading\n"
        )
        filtered = _filter_to_written_paths(output, ["docs/new.md"])
        self.assertEqual(filtered, "docs/new.md:12:5 MD013 line too long")

    def test_no_written_files_mentioned_drops_everything(self):
        output = "docs/unrelated-a.md:3:1 MD013 line too long\n"
        self.assertEqual(_filter_to_written_paths(output, ["docs/new.md"]), "")

    def test_empty_written_list_returns_output_unchanged(self):
        output = "anything at all\n"
        self.assertEqual(_filter_to_written_paths(output, []), output)

    def test_does_not_false_positive_on_filename_substring(self):
        """A written path like `api.md` must not match an unrelated file whose
        name merely contains it, e.g. `old-api.md` — plain substring matching
        would wrongly keep this line."""
        output = "docs/old-api.md:1:1 MD041 first line heading\n"
        self.assertEqual(_filter_to_written_paths(output, ["docs/api.md"]), "")

    def test_still_matches_written_path_followed_by_punctuation(self):
        output = "docs/api.md:12:5 MD013 line too long\n"
        filtered = _filter_to_written_paths(output, ["docs/api.md"])
        self.assertEqual(filtered, "docs/api.md:12:5 MD013 line too long")


class TestCheckoutBranchFetchFailure(unittest.TestCase):
    def test_missing_origin_remote_raises_clear_error(self):
        """If a NEW branch needs to be cut but `origin` isn't configured (or
        is unreachable), the fetch failure must surface as an actionable
        GitError, not an opaque crash."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=d, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                            "commit", "--allow-empty", "-qm", "init"], cwd=d, check=True)
            with self.assertRaises(_git.GitError) as ctx:
                _checkout_branch(str(d), "docs/new-feature")
            self.assertIn("origin", str(ctx.exception))


class TestDirtyPathsAndStash(unittest.TestCase):
    def test_dirty_paths_lists_untracked_and_modified(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            (d / "tracked.md").write_text("x\n")
            subprocess.run(["git", "add", "tracked.md"], cwd=d, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                            "commit", "-qm", "add"], cwd=d, check=True)
            (d / "tracked.md").write_text("y\n")
            (d / "untracked.md").write_text("z\n")
            paths = _dirty_paths(str(d))
        self.assertIn("tracked.md", paths)
        self.assertIn("untracked.md", paths)

    def test_dirty_paths_returns_empty_if_git_status_fails(self):
        self.assertEqual(_dirty_paths("/definitely/not/a/repo"), [])

    def test_stash_protects_unrelated_dirty_files_from_lint_fixer(self):
        """The regression this guards: a hub-doc clone left dirty with unrelated
        in-progress work must not get reformatted (or left dirty a second time)
        by a repo-wide lint fixer run for our own edits."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            (d / "unrelated.md").write_text("someone else's in-progress edit\n")
            (d / "docs").mkdir()
            (d / "docs/ours.md").write_text("our new page\n")
            subprocess.run(["git", "add", "docs/ours.md"], cwd=d, check=True)

            with _stash_unrelated_changes(str(d), ["docs/ours.md"]):
                # Inside the context, only our own file should still be dirty.
                self.assertNotIn("unrelated.md", _dirty_paths(str(d)))
                self.assertIn("docs/ours.md", _dirty_paths(str(d)))

            # Restored afterward.
            self.assertEqual((d / "unrelated.md").read_text(), "someone else's in-progress edit\n")

    def test_stash_pop_conflict_raises_actionable_error(self):
        """Regression: if the stash pop conflicts (e.g. a prior crashed run left
        the tree in a state where re-applying the stash collides), the raised
        GitError must tell the caller how to recover, not surface a raw
        multi-file conflict dump."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            (d / "unrelated.md").write_text("someone else's in-progress edit\n")
            (d / "docs").mkdir()
            (d / "docs/ours.md").write_text("our new page\n")
            subprocess.run(["git", "add", "docs/ours.md"], cwd=d, check=True)

            real_run = _git.run

            def fake_git_run(repo_path, args):
                if args == ["stash", "pop"]:
                    raise _git.GitError("error: Your local changes ... Aborting")
                return real_run(repo_path, args)

            with patch("scripts.preview._git.run", side_effect=fake_git_run):
                with self.assertRaises(_git.GitError) as ctx:
                    with _stash_unrelated_changes(str(d), ["docs/ours.md"]):
                        pass
        message = str(ctx.exception)
        self.assertIn("git checkout -- .", message)
        self.assertIn("git stash drop", message)

    def test_nothing_to_stash_when_no_unrelated_changes(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            (d / "docs").mkdir()
            (d / "docs/ours.md").write_text("our new page\n")
            subprocess.run(["git", "add", "docs/ours.md"], cwd=d, check=True)
            with _stash_unrelated_changes(str(d), ["docs/ours.md"]):
                pass
            stash_list = subprocess.run(
                ["git", "stash", "list"], cwd=d, capture_output=True, text=True, check=True
            ).stdout
            self.assertEqual(stash_list.strip(), "")


class TestRunLintFix(unittest.TestCase):
    def test_hub_runs_autofix_then_checks(self):
        with patch("scripts.preview.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""
            result = run_lint_fix(
                repo_path="/hub-doc", impl_repo="traefik/traefik-hub", written=["docs/new.md"],
            )
        self.assertIsInstance(result, LintFixResult)
        self.assertEqual(result.unresolved, [])
        commands_joined = " ".join(result.commands)
        self.assertIn("node_modules/.bin/markdownlint", commands_joined)
        self.assertIn("--fix", commands_joined)
        self.assertIn("node_modules/.bin/alex", commands_joined)

    def test_hub_scopes_commands_to_written_markdown_files_only(self):
        """Regression: the lint-fix pass must never run repo-wide -- that's what
        left ~70 unrelated files dirty after every run and crashed the next
        run's stash-pop. Only the written .md/.mdx files should ever appear as
        args, and non-markdown written files (e.g. sidebars.js) are excluded."""
        with patch("scripts.preview.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""
            run_lint_fix(
                repo_path="/hub-doc", impl_repo="traefik/traefik-hub",
                written=["docs/a.md", "docs/b.mdx", "sidebars.js"],
            )
        all_args = [arg for call in mock_run.call_args_list for arg in call.args[0]]
        self.assertIn("docs/a.md", all_args)
        self.assertIn("docs/b.mdx", all_args)
        self.assertNotIn("sidebars.js", all_args)
        self.assertTrue(all("docs/**" not in a for a in all_args))

    def test_hub_skips_lint_commands_when_no_markdown_written(self):
        with patch("scripts.preview.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""
            result = run_lint_fix(
                repo_path="/hub-doc", impl_repo="traefik/traefik-hub", written=["sidebars.js"],
            )
        # No markdownlint/alex invocation at all -- only (if anything) the
        # unrelated-changes git-status check, never a lint command.
        self.assertEqual(result.commands, [])
        self.assertEqual(result.unresolved, [])
        for call in mock_run.call_args_list:
            self.assertNotIn("markdownlint", call.args[0][0])
            self.assertNotIn("alex", call.args[0][0])

    def test_hub_missing_binaries_surfaces_actionable_unresolved_note(self):
        """Regression: calling node_modules/.bin/markdownlint|alex directly
        (instead of the yarn wrapper) means a clone that hasn't had
        `yarn install` run yet would otherwise hit a bare FileNotFoundError
        and crash the whole preview step. Must degrade to an unresolved note
        pointing at the fix, not crash."""
        def fake_run(cmd, **kwargs):
            # subprocess.run is process-global (scripts.preview and scripts._git
            # both do a plain `import subprocess`), so this also intercepts the
            # `git status --porcelain` call _stash_unrelated_changes makes --
            # only the markdownlint/alex binaries should raise.
            if "markdownlint" in cmd[0] or "alex" in cmd[0]:
                raise FileNotFoundError(cmd[0])
            r = type("R", (), {"stdout": "", "stderr": "", "returncode": 0})()
            return r

        with patch("scripts.preview.subprocess.run", side_effect=fake_run):
            result = run_lint_fix(
                repo_path="/hub-doc", impl_repo="traefik/traefik-hub", written=["docs/new.md"],
            )
        self.assertTrue(any("yarn install" in u for u in result.unresolved))

    def test_hub_captures_unfixable_markdownlint_errors(self):
        def fake_run(cmd, **kwargs):
            r = type("R", (), {"stdout": "", "stderr": "", "returncode": 0})()
            if "markdownlint" in cmd[0] and "--fix" not in cmd:
                r.returncode, r.stderr = 1, "docs/new.md:5 MD013 line too long"
            return r
        with patch("scripts.preview.subprocess.run", side_effect=fake_run):
            result = run_lint_fix(
                repo_path="/hub-doc", impl_repo="traefik/traefik-hub", written=["docs/new.md"],
            )
        self.assertTrue(any("MD013" in u for u in result.unresolved))

    def test_hub_captures_alex_flags_as_unresolved_never_autofixed(self):
        def fake_run(cmd, **kwargs):
            r = type("R", (), {"stdout": "", "stderr": "", "returncode": 0})()
            if "alex" in cmd[0]:
                r.returncode, r.stdout = 1, "docs/new.md:3:1 warning: `guys` may be insensitive"
            return r
        with patch("scripts.preview.subprocess.run", side_effect=fake_run):
            result = run_lint_fix(
                repo_path="/hub-doc", impl_repo="traefik/traefik-hub", written=["docs/new.md"],
            )
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


class TestCheckPlaceholderVersion(unittest.TestCase):
    def test_flags_vnext_placeholder(self):
        edits = [FileEdit(
            path="docs/api-gateway/release-notes.mdx",
            content="## Gateway vNEXT\n\n**(version TBD)**\n\n### What's New\n",
            mode="overwrite",
        )]
        findings = check_placeholder_version(edits)
        self.assertTrue(any("vNEXT" in f for f in findings))

    def test_does_not_flag_real_version(self):
        edits = [FileEdit(
            path="docs/api-gateway/release-notes.mdx",
            content="## Gateway v3.20.7\n\n**2026-08-01**\n",
            mode="overwrite",
        )]
        self.assertEqual(check_placeholder_version(edits), [])

    def test_non_markdown_files_are_skipped(self):
        edits = [FileEdit(path="sidebars.js", content="// vNEXT\n", mode="overwrite")]
        self.assertEqual(check_placeholder_version(edits), [])

    def test_wired_into_manual_checks_via_apply_edits_with_lint_fix(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            edits = [FileEdit(
                path="docs/api-gateway/release-notes.mdx",
                content="## Gateway vNEXT\n\n**(version TBD)**\n",
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
        self.assertTrue(any("vNEXT" in u for u in lint.unresolved))


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
