import unittest

from scripts.check_implementation_signal import has_implementation_signal


def _bundle(*, prs=None, related_prs=None, sub_issues=None, issue_siblings=None):
    return {
        "prs": prs or [],
        "merged": {
            "related_prs": related_prs or [],
            "sub_issues": sub_issues or [],
        },
        "issue": {"siblings": issue_siblings or []},
    }


class TestPrBackedBundle(unittest.TestCase):
    def test_pr_backed_bundle_always_has_signal(self):
        bundle = _bundle(prs=[{"number": 1}])
        result = has_implementation_signal(bundle)
        self.assertTrue(result["has_signal"])
        self.assertIn("bundle is PR-backed", result["reasons"][0])


class TestIssueOnlyNoSignal(unittest.TestCase):
    def test_no_related_prs_no_siblings_has_no_signal(self):
        bundle = _bundle()
        result = has_implementation_signal(bundle)
        self.assertFalse(result["has_signal"])
        self.assertEqual(result["reasons"], [])

    def test_closed_unmerged_related_pr_is_not_a_signal(self):
        # An abandoned/superseded PR (closed, never merged) is not evidence
        # of a real implementation landing.
        bundle = _bundle(related_prs=[{"number": 42, "state": "CLOSED"}])
        result = has_implementation_signal(bundle)
        self.assertFalse(result["has_signal"])

    def test_investigation_sibling_is_not_a_signal(self):
        # This is the Transparency Logs case this check exists for: a
        # sibling ticket that reads as investigation/QA, not implementation.
        bundle = _bundle(sub_issues=[{"number": 7, "title": "QA Findings — X is broken"}])
        result = has_implementation_signal(bundle)
        self.assertFalse(result["has_signal"])

    def test_investigation_marker_wins_even_with_add_keyword(self):
        # "Investigate adding X" should not be misread as "Add X" just
        # because it also contains an implementation-shaped word.
        bundle = _bundle(sub_issues=[{"number": 8, "title": "Investigate add X support"}])
        result = has_implementation_signal(bundle)
        self.assertFalse(result["has_signal"])


class TestIssueOnlyWithSignal(unittest.TestCase):
    def test_merged_related_pr_is_a_signal(self):
        bundle = _bundle(related_prs=[{"number": 100, "state": "MERGED"}])
        result = has_implementation_signal(bundle)
        self.assertTrue(result["has_signal"])
        self.assertIn("#100", result["reasons"][0])
        self.assertIn("merged", result["reasons"][0])

    def test_open_related_pr_is_a_signal(self):
        # SKILL.md explicitly allows drafting in parallel with an open,
        # close-to-landing PR -- don't require merge.
        bundle = _bundle(related_prs=[{"number": 101, "state": "OPEN"}])
        result = has_implementation_signal(bundle)
        self.assertTrue(result["has_signal"])

    def test_implementation_shaped_sub_issue_is_a_signal(self):
        bundle = _bundle(sub_issues=[{"number": 9, "title": "Implement transparency log verification"}])
        result = has_implementation_signal(bundle)
        self.assertTrue(result["has_signal"])
        self.assertIn("#9", result["reasons"][0])

    def test_implementation_shaped_native_sibling_is_a_signal(self):
        # native GitHub sub-issue siblings live under issue.siblings, a
        # separate list from merged.sub_issues (the fetch_issue.py-specific
        # sub-issue list) -- both are checked.
        bundle = _bundle(issue_siblings=[{"number": 10, "title": "Add support for witness verification"}])
        result = has_implementation_signal(bundle)
        self.assertTrue(result["has_signal"])

    def test_reasons_accumulate_across_multiple_signals(self):
        bundle = _bundle(
            related_prs=[{"number": 100, "state": "MERGED"}],
            sub_issues=[{"number": 9, "title": "Implement X"}],
        )
        result = has_implementation_signal(bundle)
        self.assertTrue(result["has_signal"])
        self.assertEqual(len(result["reasons"]), 2)


if __name__ == "__main__":
    unittest.main()
