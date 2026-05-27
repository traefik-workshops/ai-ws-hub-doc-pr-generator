import unittest
from datetime import date
from scripts.classify import feature_type, needs_release_note
from scripts.classify import needs_screenshots
from scripts.classify import doc_kind_candidates
from scripts.classify import classify
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 5, 27)


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
    def _pr(self, title="", labels=None, body="", merged_at=None):
        return {"title": title, "labels": labels or [], "body": body,
                "merged_at": merged_at}

    def _note(self, **kw):
        return needs_release_note(self._pr(**kw), impl_repo="traefik/traefik-hub",
                                  today=TODAY)

    def test_oss_always_no(self):
        result = needs_release_note(self._pr(title="feat: add X"), impl_repo="traefik/traefik")
        self.assertEqual(result["verdict"], "no")
        self.assertIn("oss-short-circuit", result["signals"])

    def test_hub_feat_default_ea(self):
        result = self._note(title="feat: add X", labels=["kind/enhancement"])
        self.assertEqual(result["verdict"], "yes")
        self.assertEqual(result["proposed_shape"], "ea-subsection")
        self.assertIn("feat-default-ea", result["signals"])
        # kind/enhancement is matched by substring, not exact equality
        self.assertIn("enhancement-label", result["signals"])

    def test_hub_explicit_ea_marker(self):
        result = self._note(
            title="feat: add quota API",
            body="This feature ships as Early Access and may change.",
        )
        self.assertEqual(result["proposed_shape"], "ea-subsection")
        self.assertIn("ea-marker", result["signals"])

    def test_hub_new_ga_subsection(self):
        result = self._note(
            title="feat: add tracing export",
            body="Tracing export is generally available in this release.",
        )
        self.assertEqual(result["proposed_shape"], "ga-subsection")
        self.assertIn("ga-new-marker", result["signals"])

    def test_hub_ga_graduation_bullet(self):
        result = self._note(title="feat: X graduates to GA")
        self.assertEqual(result["verdict"], "yes")
        self.assertEqual(result["proposed_shape"], "ga-bullet")

    def test_hub_breaking_label(self):
        result = self._note(title="feat: rename X", labels=["kind/breaking-change"])
        self.assertEqual(result["verdict"], "yes")
        self.assertEqual(result["proposed_shape"], "breaking-subsection")

    def test_hub_fix_no(self):
        result = self._note(title="fix: handle empty body")
        self.assertEqual(result["verdict"], "no")

    def test_hub_chore_no(self):
        result = self._note(title="chore(deps): bump")
        self.assertEqual(result["verdict"], "no")

    def test_target_month_from_merge_date(self):
        result = self._note(title="feat: add X", merged_at="2026-05-27T15:05:06Z")
        self.assertEqual(result["target_month"], "May 2026")

    def test_target_month_falls_back_to_today_when_open(self):
        result = self._note(title="feat: add X", merged_at=None)
        self.assertEqual(result["target_month"], "May 2026")


class TestScreenshots(unittest.TestCase):
    def test_ui_neighbors_yes(self):
        result = needs_screenshots(
            neighbor_paths=[str(FIXTURES / "hub_doc_neighbor_ui.mdx")] * 3
            + [str(FIXTURES / "hub_doc_neighbor_middleware.md")],
            touched_paths=["hub/dashboard/src/App.tsx"],
        )
        self.assertEqual(result["verdict"], "yes")

    def test_pure_reference_no(self):
        result = needs_screenshots(
            neighbor_paths=[str(FIXTURES / "hub_doc_neighbor_middleware.md")] * 4,
            touched_paths=["hub/pkg/middleware/tokenratelimit/config.go"],
        )
        self.assertEqual(result["verdict"], "no")

    def test_dashboard_code_strong_yes(self):
        # Even with no neighbors, touching dashboard code is a strong signal.
        result = needs_screenshots(
            neighbor_paths=[],
            touched_paths=["hub/dashboard/src/App.tsx"],
        )
        self.assertEqual(result["verdict"], "yes")


class TestDocKindCandidates(unittest.TestCase):
    def test_middleware_code_leans_reference(self):
        cands = doc_kind_candidates(
            title="feat: add onDenyResponse to token ratelimit middleware",
            touched_paths=["hub/pkg/middleware/tokenratelimit/config.go"],
            neighbor_paths=[],
        )
        top = cands[0]
        self.assertEqual(top["kind"], "reference")
        self.assertGreater(top["confidence"], 0.5)

    def test_dashboard_code_leans_user_guide(self):
        cands = doc_kind_candidates(
            title="feat: add quota panel",
            touched_paths=["hub/dashboard/src/QuotaPanel.tsx"],
            neighbor_paths=[],
        )
        self.assertEqual(cands[0]["kind"], "user-guide")

    def test_title_hint_guide(self):
        cands = doc_kind_candidates(
            title="feat: guide for setting up X",
            touched_paths=[],
            neighbor_paths=[],
        )
        self.assertEqual(cands[0]["kind"], "user-guide")


class TestClassify(unittest.TestCase):
    def test_envelope_combines_all_three(self):
        bundle = {
            "impl_repo": "traefik/traefik-hub",
            "prs": [{
                "number": 1234,
                "title": "feat: add onDenyResponse to token ratelimit middleware",
                "labels": ["feature"],
                "body": "",
            }],
            "merged": {
                "files_changed": [
                    {"path": "hub/pkg/middleware/tokenratelimit/config.go"}
                ],
                "primary_pr": 1234,
            },
        }
        result = classify(bundle, grounding={"concepts": []}, neighbor_paths=[])
        self.assertEqual(result["feature_type"], "feat")
        self.assertEqual(result["needs_release_note"]["verdict"], "yes")
        self.assertEqual(result["needs_release_note"]["proposed_shape"], "ea-subsection")
        self.assertEqual(result["needs_screenshots"]["verdict"], "no")
        self.assertEqual(result["doc_kind_candidates"][0]["kind"], "reference")


if __name__ == "__main__":
    unittest.main()
