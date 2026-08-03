import unittest
from scripts.dedup_versions import dedup


def _tag(tag, date, commits):
    """commits: list of (sha, subject, verdict) tuples."""
    return {
        "tag": tag, "prev_tag": "irrelevant", "date": date,
        "commits": [
            {"sha": sha, "subject": subj, "verdict": verdict, "confidence": 1.0, "reason": None}
            for sha, subj, verdict in commits
        ],
    }


class TestDedupSingleTag(unittest.TestCase):
    def test_single_tag_never_combines(self):
        classified = {"repo": "traefik/traefik-hub", "tags": [
            _tag("v3.20.8", "2026-08-01T00:00:00Z", [("aaa", "fix: x", "include")]),
        ]}
        result = dedup(classified, max_date_gap_days=3)
        self.assertFalse(result["combine"])
        self.assertEqual(result["shared"], [])
        self.assertEqual(result["only"]["v3.20.8"], [{"sha": "aaa", "subject": "fix: x"}])


class TestDedupTwoTags(unittest.TestCase):
    def test_shared_commit_detected_by_identical_sha(self):
        classified = {"repo": "traefik/traefik-hub", "tags": [
            _tag("v3.20.8", "2026-08-01T00:00:00Z",
                 [("shared1", "fix: shared bug", "include"), ("only20", "fix: v3.20-only", "include")]),
            _tag("v3.19.13", "2026-08-01T00:00:00Z",
                 [("shared1", "fix: shared bug", "include"), ("only19", "fix: v3.19-only", "include")]),
        ]}
        result = dedup(classified, max_date_gap_days=3)
        self.assertEqual([s["sha"] for s in result["shared"]], ["shared1"])
        self.assertEqual([c["sha"] for c in result["only"]["v3.20.8"]], ["only20"])
        self.assertEqual([c["sha"] for c in result["only"]["v3.19.13"]], ["only19"])

    def test_excluded_commits_never_counted_as_shared_or_only(self):
        classified = {"repo": "traefik/traefik-hub", "tags": [
            _tag("v3.20.8", "2026-08-01T00:00:00Z",
                 [("merge1", "Merge v3.19 into v3.20", "exclude"), ("real1", "fix: real", "include")]),
            _tag("v3.19.13", "2026-08-01T00:00:00Z", [("real2", "fix: other real", "include")]),
        ]}
        result = dedup(classified, max_date_gap_days=3)
        all_shas = {s["sha"] for s in result["shared"]} | {
            c["sha"] for lst in result["only"].values() for c in lst
        }
        self.assertNotIn("merge1", all_shas)

    def test_combines_when_shared_and_close_dates(self):
        classified = {"repo": "traefik/traefik-hub", "tags": [
            _tag("v3.20.8", "2026-08-01T00:00:00Z", [("shared1", "fix: x", "include")]),
            _tag("v3.19.13", "2026-08-02T00:00:00Z", [("shared1", "fix: x", "include")]),
        ]}
        result = dedup(classified, max_date_gap_days=3)
        self.assertTrue(result["combine"])
        self.assertEqual(result["heading"], "v3.20.8 & v3.19.13")

    def test_does_not_combine_when_dates_too_far_apart(self):
        classified = {"repo": "traefik/traefik-hub", "tags": [
            _tag("v3.20.8", "2026-08-01T00:00:00Z", [("shared1", "fix: x", "include")]),
            _tag("v3.19.13", "2026-08-10T00:00:00Z", [("shared1", "fix: x", "include")]),
        ]}
        result = dedup(classified, max_date_gap_days=3)
        self.assertFalse(result["combine"])
        self.assertIn("9d apart", result["reason"])

    def test_does_not_combine_when_no_shared_commits(self):
        classified = {"repo": "traefik/traefik-hub", "tags": [
            _tag("v3.20.8", "2026-08-01T00:00:00Z", [("only20", "fix: x", "include")]),
            _tag("v3.19.13", "2026-08-01T00:00:00Z", [("only19", "fix: y", "include")]),
        ]}
        result = dedup(classified, max_date_gap_days=3)
        self.assertFalse(result["combine"])
        self.assertIn("unrelated", result["reason"])

    def test_heading_orders_newer_version_first(self):
        classified = {"repo": "traefik/traefik-hub", "tags": [
            _tag("v3.19.13", "2026-08-01T00:00:00Z", [("shared1", "fix: x", "include")]),
            _tag("v3.20.8", "2026-08-01T00:00:00Z", [("shared1", "fix: x", "include")]),
        ]}
        result = dedup(classified, max_date_gap_days=3)
        self.assertEqual(result["heading"], "v3.20.8 & v3.19.13")
        self.assertEqual(result["ordered_tags"], ["v3.20.8", "v3.19.13"])

    def test_custom_max_date_gap_days_widens_window(self):
        classified = {"repo": "traefik/traefik-hub", "tags": [
            _tag("v3.20.8", "2026-08-01T00:00:00Z", [("shared1", "fix: x", "include")]),
            _tag("v3.19.13", "2026-08-10T00:00:00Z", [("shared1", "fix: x", "include")]),
        ]}
        result = dedup(classified, max_date_gap_days=14)
        self.assertTrue(result["combine"])


if __name__ == "__main__":
    unittest.main()
