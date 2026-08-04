import unittest
from unittest.mock import patch
from scripts.fetch_release_range import resolve_prev_tag, compare_commits, tag_commit_date, fetch_range


ALL_TAGS = ["v3.20.8", "v3.20.7", "v3.20.6", "v3.19.13", "v3.19.12", "v3.19.11", "v3.18.9"]


class TestResolvePrevTag(unittest.TestCase):
    def test_finds_previous_patch_on_same_line(self):
        prev = resolve_prev_tag("v3.20.8", override=None, all_tags=ALL_TAGS)
        self.assertEqual(prev, "v3.20.7")

    def test_override_is_used_verbatim_without_lookup(self):
        prev = resolve_prev_tag("v3.20.8", override="v3.20.1", all_tags=[])
        self.assertEqual(prev, "v3.20.1")

    def test_raises_when_no_earlier_tag_on_line(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_prev_tag("v3.21.0", override=None, all_tags=ALL_TAGS)
        self.assertIn("--prev-tag", str(ctx.exception))

    def test_raises_on_unparseable_tag(self):
        with self.assertRaises(ValueError):
            resolve_prev_tag("not-a-tag", override=None, all_tags=ALL_TAGS)

    def test_ignores_tags_from_other_lines(self):
        prev = resolve_prev_tag("v3.19.13", override=None, all_tags=ALL_TAGS)
        self.assertEqual(prev, "v3.19.12")
        self.assertNotEqual(prev, "v3.20.8")


class TestCompareCommits(unittest.TestCase):
    def test_extracts_sha_and_first_subject_line(self):
        api_response = {"commits": [
            {"sha": "aaa1111", "commit": {"message": "fix: real bug\n\nlonger body here"}},
            {"sha": "bbb2222", "commit": {"message": "docs: update readme"}},
        ]}
        with patch("scripts.fetch_release_range._gh.run_json", return_value=api_response):
            commits = compare_commits("v3.20.7", "v3.20.8")
        self.assertEqual(commits, [
            {"sha": "aaa1111", "subject": "fix: real bug"},
            {"sha": "bbb2222", "subject": "docs: update readme"},
        ])

    def test_empty_compare_range_returns_empty_list(self):
        with patch("scripts.fetch_release_range._gh.run_json", return_value={"commits": []}):
            self.assertEqual(compare_commits("v3.20.7", "v3.20.7"), [])


class TestTagCommitDate(unittest.TestCase):
    def test_resolves_sha_then_fetches_commit_date(self):
        with patch("scripts.fetch_release_range._gh.run_text",
                   side_effect=["deadbeef\n", "2026-08-01T12:00:00Z\n"]):
            date = tag_commit_date("v3.20.8")
        self.assertEqual(date, "2026-08-01T12:00:00Z")


class TestFetchRange(unittest.TestCase):
    def test_assembles_full_tag_entry(self):
        with patch("scripts.fetch_release_range.resolve_prev_tag", return_value="v3.20.7"), \
             patch("scripts.fetch_release_range.tag_commit_date", return_value="2026-08-01T00:00:00Z"), \
             patch("scripts.fetch_release_range.compare_commits",
                   return_value=[{"sha": "aaa1111", "subject": "fix: x"}]):
            result = fetch_range("v3.20.8", prev_override=None, all_tags=ALL_TAGS)
        self.assertEqual(result["tag"], "v3.20.8")
        self.assertEqual(result["prev_tag"], "v3.20.7")
        self.assertEqual(result["date"], "2026-08-01T00:00:00Z")
        self.assertEqual(len(result["commits"]), 1)


if __name__ == "__main__":
    unittest.main()
