import unittest
from scripts import _semver


class TestParse(unittest.TestCase):
    def test_parses_plain_release(self):
        v = _semver.parse("v3.20.7")
        self.assertEqual((v.major, v.minor, v.patch, v.prerelease), (3, 20, 7, None))

    def test_parses_prerelease_suffix(self):
        v = _semver.parse("v3.20.0-ea.8")
        self.assertEqual((v.major, v.minor, v.patch, v.prerelease), (3, 20, 0, "ea.8"))

    def test_accepts_no_leading_v(self):
        v = _semver.parse("3.20.7")
        self.assertEqual((v.major, v.minor, v.patch), (3, 20, 7))

    def test_returns_none_for_unparseable(self):
        self.assertIsNone(_semver.parse("not-a-version"))
        self.assertIsNone(_semver.parse("v3.20"))

    def test_raw_preserves_original_string(self):
        v = _semver.parse("v3.20.7")
        self.assertEqual(v.raw, "v3.20.7")


class TestKeyOrdering(unittest.TestCase):
    def test_final_release_sorts_after_prerelease_of_same_version(self):
        final = _semver.parse("v3.20.0")
        ea = _semver.parse("v3.20.0-ea.8")
        self.assertGreater(final.key(), ea.key())

    def test_higher_patch_sorts_after_lower(self):
        self.assertGreater(_semver.parse("v3.20.7").key(), _semver.parse("v3.20.6").key())

    def test_higher_minor_sorts_after_lower_regardless_of_patch(self):
        self.assertGreater(_semver.parse("v3.20.0").key(), _semver.parse("v3.19.99").key())


class TestSortedTags(unittest.TestCase):
    def test_sorts_ascending_and_drops_unparseable(self):
        tags = ["v3.20.7", "v3.19.13", "not-a-tag", "v3.20.1"]
        result = [s.raw for s in _semver.sorted_tags(tags)]
        self.assertEqual(result, ["v3.19.13", "v3.20.1", "v3.20.7"])


class TestSameLine(unittest.TestCase):
    def test_same_major_minor_is_same_line(self):
        a, b = _semver.parse("v3.20.1"), _semver.parse("v3.20.7")
        self.assertTrue(_semver.same_line(a, b))

    def test_different_minor_is_not_same_line(self):
        a, b = _semver.parse("v3.19.13"), _semver.parse("v3.20.7")
        self.assertFalse(_semver.same_line(a, b))

    def test_different_major_is_not_same_line(self):
        a, b = _semver.parse("v2.20.1"), _semver.parse("v3.20.1")
        self.assertFalse(_semver.same_line(a, b))


if __name__ == "__main__":
    unittest.main()
