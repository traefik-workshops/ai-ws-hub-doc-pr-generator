import unittest
from scripts.classify import feature_type, needs_release_note


class TestFeatureType(unittest.TestCase):
    def test_feat_prefix(self):
        self.assertEqual(feature_type("feat: add X"), "feat")

    def test_fix_prefix(self):
        self.assertEqual(feature_type("fix(deps): bump"), "fix")

    def test_chore(self):
        self.assertEqual(feature_type("chore: lint"), "chore")

    def test_unknown(self):
        self.assertEqual(feature_type("Random text"), "other")


class TestReleaseNote(unittest.TestCase):
    def _pr(self, title="", labels=None, body=""):
        return {"title": title, "labels": labels or [], "body": body}

    def test_oss_always_no(self):
        result = needs_release_note(self._pr(title="feat: add X"), impl_repo="traefik/traefik")
        self.assertEqual(result["verdict"], "no")
        self.assertIn("oss-short-circuit", result["signals"])

    def test_hub_feat_default_ea(self):
        result = needs_release_note(
            self._pr(title="feat: add X", labels=["feature"]),
            impl_repo="traefik/traefik-hub",
        )
        self.assertEqual(result["verdict"], "yes")
        self.assertEqual(result["proposed_shape"], "ea-subsection")

    def test_hub_ga_graduation_bullet(self):
        result = needs_release_note(
            self._pr(title="feat: X graduates to GA"),
            impl_repo="traefik/traefik-hub",
        )
        self.assertEqual(result["verdict"], "yes")
        self.assertEqual(result["proposed_shape"], "ga-bullet")

    def test_hub_breaking_label(self):
        result = needs_release_note(
            self._pr(title="feat: rename X", labels=["breaking-change"]),
            impl_repo="traefik/traefik-hub",
        )
        self.assertEqual(result["verdict"], "yes")
        self.assertEqual(result["proposed_shape"], "breaking-subsection")

    def test_hub_fix_no(self):
        result = needs_release_note(
            self._pr(title="fix: handle empty body"),
            impl_repo="traefik/traefik-hub",
        )
        self.assertEqual(result["verdict"], "no")

    def test_hub_chore_no(self):
        result = needs_release_note(
            self._pr(title="chore(deps): bump"),
            impl_repo="traefik/traefik-hub",
        )
        self.assertEqual(result["verdict"], "no")


if __name__ == "__main__":
    unittest.main()
