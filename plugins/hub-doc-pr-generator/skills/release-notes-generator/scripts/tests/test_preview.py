import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.preview import (
    apply_edit, run_lint_fix, check_table_completeness, check_vnext_placeholder,
    render_manual_checks_section, detect_pretty_tools, git_diff, DEFAULT_REL_PATH,
)


def _init_git(d: Path) -> None:
    """A repo with a self-referencing 'origin' remote and a fetched 'main' —
    matches what a real hub-doc clone looks like, so _checkout_branch's
    `fetch origin main` + `checkout -b <branch> origin/main` has something
    real to branch from."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                    "commit", "--allow-empty", "-qm", "init"], cwd=d, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(d)], cwd=d, check=True)
    subprocess.run(["git", "fetch", "-q", "origin"], cwd=d, check=True)


class TestApplyEdit(unittest.TestCase):
    def test_writes_and_stages_content(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            apply_edit(repo_path=str(d), branch="docs/rn", rel_path=DEFAULT_REL_PATH, content="new content\n")
            self.assertEqual((d / DEFAULT_REL_PATH).read_text(), "new content\n")
            diff = git_diff(str(d))
        self.assertIn("new content", diff)

    def test_new_branch_does_not_inherit_stale_checked_out_branch(self):
        """Same class of bug as the sibling hub-doc-pr-generator skill's PR
        #965: a NEW branch must be cut from origin/main, never from whatever
        branch happens to be checked out."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            subprocess.run(["git", "checkout", "-q", "-b", "old-merged-feature"], cwd=d, check=True)
            (d / "unrelated.txt").write_text("leftover work\n")
            subprocess.run(["git", "add", "unrelated.txt"], cwd=d, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                            "commit", "-qm", "stale unrelated commit"], cwd=d, check=True)

            apply_edit(repo_path=str(d), branch="docs/rn-new", rel_path=DEFAULT_REL_PATH, content="x\n")

            log = subprocess.run(
                ["git", "log", "--format=%s", "origin/main..docs/rn-new"],
                cwd=d, capture_output=True, text=True, check=True,
            ).stdout
            self.assertNotIn("stale unrelated commit", log)
            self.assertFalse((d / "unrelated.txt").exists())

    def test_existing_local_branch_is_reused_not_recreated(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            subprocess.run(["git", "checkout", "-q", "-b", "docs/rn-existing"], cwd=d, check=True)
            (d / "docs/api-gateway").mkdir(parents=True)
            (d / "docs/api-gateway/other.mdx").write_text("prior work\n")
            subprocess.run(["git", "add", "docs/api-gateway/other.mdx"], cwd=d, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                            "commit", "-qm", "prior commit"], cwd=d, check=True)
            subprocess.run(["git", "checkout", "-q", "main"], cwd=d, check=True)

            apply_edit(repo_path=str(d), branch="docs/rn-existing", rel_path=DEFAULT_REL_PATH, content="x\n")

            self.assertTrue((d / "docs/api-gateway/other.mdx").is_file())

    def test_clears_stray_executable_bit(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            apply_edit(repo_path=str(d), branch="docs/rn", rel_path=DEFAULT_REL_PATH, content="x\n")
            (d / DEFAULT_REL_PATH).chmod(0o755)
            # Re-apply to exercise the chmod-clear path a second time.
            apply_edit(repo_path=str(d), branch="docs/rn", rel_path=DEFAULT_REL_PATH, content="y\n")
            self.assertEqual((d / DEFAULT_REL_PATH).stat().st_mode & 0o777, 0o644)


class TestRunLintFix(unittest.TestCase):
    def test_hub_autofix_then_check(self):
        with patch("scripts.preview.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""
            fixed, unresolved = run_lint_fix(repo_path="/hub-doc")
        self.assertTrue(any("docs:markdown --fix" in f for f in fixed))
        self.assertEqual(unresolved, [])

    def test_captures_alex_flags_as_unresolved(self):
        def fake_run(cmd, **kwargs):
            r = type("R", (), {"stdout": "", "stderr": "", "returncode": 0})()
            if cmd == ["yarn", "docs:alex"]:
                r.returncode, r.stdout = 1, "warning: `guys` may be insensitive"
            return r
        with patch("scripts.preview.subprocess.run", side_effect=fake_run):
            _, unresolved = run_lint_fix(repo_path="/hub-doc")
        self.assertTrue(any("guys" in u for u in unresolved))


class TestCheckTableCompleteness(unittest.TestCase):
    def test_flags_truncated_table_row(self):
        content = "| Component | Version |\n| --- | --- |\n| Traefik Hub, etc. | v3.20.8 |\n"
        findings = check_table_completeness(content, DEFAULT_REL_PATH)
        self.assertEqual(len(findings), 1)

    def test_complete_table_not_flagged(self):
        content = "| Component | Version |\n| --- | --- |\n| Traefik Hub | v3.20.8 |\n"
        self.assertEqual(check_table_completeness(content, DEFAULT_REL_PATH), [])

    def test_pre_existing_untouched_row_is_not_flagged_when_repo_path_given(self):
        """Fix D (PR #30 round 2 review): the sibling hub-doc-pr-generator
        skill's preview.py got a position-based scoping fix for this same
        false-positive (traefik-hub#1435 finding #5) but this skill's copy
        never did -- a pre-existing, untouched row containing an example
        value like "123..." must not be flagged just because this `cut` run
        also touches the same file elsewhere."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            existing = (
                "| Field | Type | Example |\n| --- | --- | --- |\n"
                "| serial | string | \"123...\" |\n"
            )
            (d / DEFAULT_REL_PATH).parent.mkdir(parents=True, exist_ok=True)
            (d / DEFAULT_REL_PATH).write_text(existing)
            subprocess.run(["git", "add", DEFAULT_REL_PATH], cwd=d, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                             "commit", "-qm", "existing"], cwd=d, check=True)

            new_content = existing + "| Gateway | v3.21.0-ea.1 |\n"
            findings = check_table_completeness(new_content, DEFAULT_REL_PATH, repo_path=str(d))
        self.assertEqual(findings, [])

    def test_genuinely_new_truncated_row_is_flagged_when_repo_path_given(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _init_git(d)
            existing = "| Component | Version |\n| --- | --- |\n| Traefik Hub | v3.20.8 |\n"
            (d / DEFAULT_REL_PATH).parent.mkdir(parents=True, exist_ok=True)
            (d / DEFAULT_REL_PATH).write_text(existing)
            subprocess.run(["git", "add", DEFAULT_REL_PATH], cwd=d, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                             "commit", "-qm", "existing"], cwd=d, check=True)

            new_content = existing + "| Traefik Proxy, etc. | v3.5.0 |\n"
            findings = check_table_completeness(new_content, DEFAULT_REL_PATH, repo_path=str(d))
        self.assertEqual(len(findings), 1)
        self.assertIn("Proxy", findings[0])

    def test_without_repo_path_falls_back_to_flagging_every_matching_line(self):
        """Backward-compatible default: omitting repo_path keeps the
        previous (unscoped) behavior."""
        content = "| Field | Example |\n| --- | --- |\n| serial | \"123...\" |\n"
        findings = check_table_completeness(content, DEFAULT_REL_PATH)
        self.assertEqual(len(findings), 1)


class TestCheckVnextPlaceholder(unittest.TestCase):
    def test_flags_vnext_left_in_fragment_body_prose(self):
        """Regression test: assign_target_version.py only rewrites a
        fragment's front-matter target_version, never its body -- a leftover
        `vNEXT` in the assembled section's callout text previously had nothing
        catching it before the cut PR shipped."""
        content = (
            "## Gateway v3.21.0-ea.1 <EarlyAccessBadge />\n\n**2026-08-10**\n\n"
            "#### Bedrock Mantle\n\n:::warning Early Access\n"
            "This feature is currently in early access. Available starting vNEXT.\n:::\n"
        )
        findings = check_vnext_placeholder(content, DEFAULT_REL_PATH)
        self.assertTrue(any("vNEXT" in f for f in findings))

    def test_real_version_not_flagged(self):
        content = (
            ":::warning Early Access\n"
            "This feature is currently in early access. Available starting v3.21.0-ea.1.\n:::\n"
        )
        self.assertEqual(check_vnext_placeholder(content, DEFAULT_REL_PATH), [])


class TestRenderManualChecksSection(unittest.TestCase):
    def test_empty_when_nothing_unresolved(self):
        self.assertEqual(render_manual_checks_section([]), "")

    def test_renders_checklist(self):
        md = render_manual_checks_section(["alex: flagged `guys`"])
        self.assertIn("## Manual checks required", md)
        self.assertIn("- [ ] alex: flagged `guys`", md)


class TestDetectPrettyTools(unittest.TestCase):
    def test_none_when_nothing_installed(self):
        with patch("scripts.preview.shutil.which", return_value=None):
            self.assertEqual(detect_pretty_tools(), {"diff": None, "page": None})

    def test_detects_delta_and_glow(self):
        with patch("scripts.preview.shutil.which", side_effect=lambda n: f"/x/{n}" if n in ("delta", "glow") else None):
            self.assertEqual(detect_pretty_tools(), {"diff": "delta", "page": "glow"})


if __name__ == "__main__":
    unittest.main()
