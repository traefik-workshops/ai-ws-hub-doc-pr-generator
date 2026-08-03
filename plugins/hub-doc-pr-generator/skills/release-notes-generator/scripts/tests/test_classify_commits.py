import unittest
from unittest.mock import patch
from scripts.classify_commits import (
    classify_commit, classify_range, flagged_for_review, render_needs_verification_section,
)


class TestClassifyCommit(unittest.TestCase):
    def test_branch_merge_excluded_full_confidence(self):
        c = classify_commit({"sha": "abc1234", "subject": "Merge v3.19 into v3.20"})
        self.assertEqual(c["verdict"], "exclude")
        self.assertEqual(c["confidence"], 1.0)

    def test_lint_fix_excluded_full_confidence(self):
        c = classify_commit({"sha": "abc1234", "subject": "fix lint error in handler.go"})
        self.assertEqual(c["verdict"], "exclude")
        self.assertEqual(c["confidence"], 1.0)

    def test_ordinary_fix_included_full_confidence(self):
        c = classify_commit({"sha": "abc1234", "subject": "fix: no policy matchers breaks mcp spans"})
        self.assertEqual(c["verdict"], "include")
        self.assertEqual(c["confidence"], 1.0)

    def test_test_hint_excluded_when_touches_only_test_files(self):
        with patch("scripts.classify_commits._gh.run_json", return_value=["hub/pkg/foo/foo_test.go"]):
            c = classify_commit({"sha": "abc1234", "subject": "fix: flaky e2e test for LDAP"})
        self.assertEqual(c["verdict"], "exclude")
        self.assertEqual(c["confidence"], 0.9)

    def test_test_hint_included_at_reduced_confidence_when_touches_prod_files(self):
        with patch("scripts.classify_commits._gh.run_json",
                   return_value=["hub/pkg/ldap/dial.go", "hub/pkg/ldap/dial_test.go"]):
            c = classify_commit({"sha": "abc1234", "subject": "fix: dns issues in e2e tests on linux"})
        self.assertEqual(c["verdict"], "include")
        self.assertEqual(c["confidence"], 0.6)

    def test_preserves_original_commit_fields(self):
        c = classify_commit({"sha": "abc1234", "subject": "fix: something"})
        self.assertEqual(c["sha"], "abc1234")
        self.assertEqual(c["subject"], "fix: something")


class TestClassifyRange(unittest.TestCase):
    def test_classifies_every_commit_per_tag(self):
        range_data = {
            "repo": "traefik/traefik-hub",
            "tags": [{
                "tag": "v3.20.8", "prev_tag": "v3.20.7", "date": "2026-08-01T00:00:00Z",
                "commits": [
                    {"sha": "aaa1111", "subject": "fix: real bug"},
                    {"sha": "bbb2222", "subject": "Merge v3.19 into v3.20"},
                ],
            }],
        }
        out = classify_range(range_data)
        self.assertEqual(len(out["tags"][0]["commits"]), 2)
        verdicts = {c["sha"]: c["verdict"] for c in out["tags"][0]["commits"]}
        self.assertEqual(verdicts["aaa1111"], "include")
        self.assertEqual(verdicts["bbb2222"], "exclude")

    def test_adds_needs_verification_md_field(self):
        range_data = {
            "repo": "traefik/traefik-hub",
            "tags": [{
                "tag": "v3.20.8", "prev_tag": "v3.20.7", "date": "2026-08-01T00:00:00Z",
                "commits": [{"sha": "aaa1111", "subject": "fix: real bug"}],
            }],
        }
        out = classify_range(range_data)
        self.assertIn("needs_verification_md", out)


class TestFlaggedForReview(unittest.TestCase):
    def _classified(self, commits):
        return {"repo": "traefik/traefik-hub", "tags": [
            {"tag": "v3.20.8", "prev_tag": "v3.20.7", "date": "2026-08-01T00:00:00Z", "commits": commits}
        ]}

    def test_full_confidence_included_commits_not_flagged(self):
        classified = self._classified([
            {"sha": "aaa1111", "subject": "fix: real bug", "verdict": "include", "confidence": 1.0, "reason": None},
        ])
        self.assertEqual(flagged_for_review(classified), [])

    def test_low_confidence_included_commit_is_flagged(self):
        classified = self._classified([
            {"sha": "aaa1111", "subject": "fix: dns issues in e2e tests on linux",
             "verdict": "include", "confidence": 0.6, "reason": "mentions test/e2e wording but touches non-test files"},
        ])
        flagged = flagged_for_review(classified)
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]["sha"], "aaa1111")

    def test_excluded_commits_are_not_flagged_even_below_full_confidence(self):
        # An exclusion is a different kind of judgment call than an inclusion;
        # this function only surfaces included-but-uncertain commits.
        classified = self._classified([
            {"sha": "aaa1111", "subject": "fix: flaky e2e test", "verdict": "exclude",
             "confidence": 0.9, "reason": "touches only test files"},
        ])
        self.assertEqual(flagged_for_review(classified), [])


class TestRenderNeedsVerificationSection(unittest.TestCase):
    def test_empty_when_nothing_flagged(self):
        classified = {"tags": [{"tag": "v3.20.8", "commits": [
            {"sha": "aaa1111", "subject": "fix: x", "verdict": "include", "confidence": 1.0, "reason": None},
        ]}]}
        self.assertEqual(render_needs_verification_section(classified), "")

    def test_renders_section_with_flagged_commit(self):
        classified = {"tags": [{"tag": "v3.20.8", "commits": [
            {"sha": "aaa1111234", "subject": "fix: dns issues in e2e tests on linux",
             "verdict": "include", "confidence": 0.6, "reason": "verify before excluding"},
        ]}]}
        md = render_needs_verification_section(classified)
        self.assertIn("## Needs verification", md)
        self.assertIn("aaa1111", md)  # short sha (first 7 chars)
        self.assertIn("v3.20.8", md)
        self.assertIn("0.6", md)
        self.assertIn("verify before excluding", md)


if __name__ == "__main__":
    unittest.main()
