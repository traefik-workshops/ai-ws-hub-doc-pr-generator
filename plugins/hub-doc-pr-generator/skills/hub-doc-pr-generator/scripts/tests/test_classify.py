import unittest
from scripts.classify import feature_type, needs_release_note, _title_to_heading
from scripts.classify import needs_screenshots
from scripts.classify import doc_kind_candidates
from scripts.classify import classify
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


class TestFeatureType(unittest.TestCase):
    def test_feat_prefix(self):
        self.assertEqual(feature_type("feat: add X"), "feat")

    def test_fix_prefix(self):
        self.assertEqual(feature_type("fix(deps): bump"), "fix")

    def test_chore(self):
        self.assertEqual(feature_type("chore: lint"), "chore")

    def test_unknown(self):
        self.assertEqual(feature_type("Random text"), "other")


class TestTitleToHeading(unittest.TestCase):
    def test_simple_prefix_stripped(self):
        self.assertEqual(_title_to_heading("feat: add rate limiting"), "Add rate limiting")

    def test_scoped_prefix_stripped(self):
        self.assertEqual(_title_to_heading("feat(ai-gateway): Rate limiting"), "Rate limiting")

    def test_fix_scoped(self):
        self.assertEqual(_title_to_heading("fix(middleware): handle empty body"), "Handle empty body")

    def test_no_prefix(self):
        self.assertEqual(_title_to_heading("Some feature"), "Some feature")

    def test_empty_title(self):
        self.assertEqual(_title_to_heading("feat:"), "")


class TestReleaseNote(unittest.TestCase):
    def _pr(self, title="", labels=None, body="", merged_at=None):
        return {"title": title, "labels": labels or [], "body": body,
                "merged_at": merged_at}

    def _note(self, **kw):
        return needs_release_note(self._pr(**kw), impl_repo="traefik/traefik-hub")

    def test_not_breaking_label_does_not_match(self):
        # "not-breaking-change" must NOT trigger breaking-subsection.
        result = self._note(title="feat: rename X", labels=["kind/not-breaking-change"])
        self.assertNotEqual(result["proposed_shape"], "breaking-subsection")

    def test_breaking_wins_over_ea_marker(self):
        # A PR with both a breaking label and an EA marker in the body should
        # produce breaking-subsection, not ea-subsection.
        result = self._note(
            title="feat: rename token API",
            labels=["kind/breaking-change"],
            body="This early access API is being renamed.",
        )
        self.assertEqual(result["proposed_shape"], "breaking-subsection")

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

    def test_no_target_month_field(self):
        # Removed: release-notes.mdx moved to per-version (semver) sections
        # (traefik/hub-doc#953), so a merge-date-derived month no longer maps to
        # anything in the file. SKILL.md asks for the target version explicitly.
        result = self._note(title="feat: add X", merged_at="2026-05-27T15:05:06Z")
        self.assertNotIn("target_month", result)


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

    def test_pure_type_def_file_does_not_force_yes(self):
        # Regression: hub/portal/types/api.d.ts is a type-definition file with
        # no rendered UI — it must NOT trigger rule 1's strong "yes" the way an
        # actual .tsx component touch would.
        result = needs_screenshots(
            neighbor_paths=[str(FIXTURES / "hub_doc_neighbor_middleware.md")] * 4,
            touched_paths=["hub/portal/types/api.d.ts"],
        )
        self.assertEqual(result["verdict"], "no")
        self.assertNotIn("ui-code-touched", result["signals"])

    def test_type_def_alongside_real_component_still_yes(self):
        # A type-def file touched alongside actual component code should still
        # trigger "yes" from the component file, not be masked by the type file.
        result = needs_screenshots(
            neighbor_paths=[],
            touched_paths=["hub/portal/types/api.d.ts", "hub/portal/src/ApiKeyPanel.tsx"],
        )
        self.assertEqual(result["verdict"], "yes")
        self.assertIn("ui-code-touched", result["signals"])


class TestDocKindCandidatesNoSignal(unittest.TestCase):
    def test_no_signal_returns_reference_default(self):
        """Regression test for traefik-hub#1435 finding #4: a diff with zero
        doc-adjacent signal at all (no markdown/UI/config-schema files) used
        to tie-break toward user-guide at 0.5/0.5 confidence, but the real
        case this represents -- pure internal Go with nothing guide-shaped to
        write about (license claims, profile resolution, OTel registration) --
        was actually a reference-table extension. We should still get a clear
        default (reference at 0.5) rather than two 0.0 candidates, but
        reference now wins the tie."""
        cands = doc_kind_candidates(title="", touched_paths=[])
        self.assertEqual(cands[0]["kind"], "reference")
        self.assertEqual(cands[0]["confidence"], 0.5)

    def test_single_signal_stays_absolute_below_gate(self):
        # A lone signal (score_ref=0.6, score_guide=0) must NOT be inflated to 1.0.
        # Confidence stays at the absolute 0.6 — below the 0.85 auto-accept gate —
        # so the skill still asks the engineer instead of silently picking.
        cands = doc_kind_candidates(
            title="",
            touched_paths=["hub/pkg/middleware/cors/config.go"]
        )
        self.assertEqual(cands[0]["kind"], "reference")
        self.assertAlmostEqual(cands[0]["confidence"], 0.6)

    def test_lone_weak_title_keyword_does_not_auto_accept(self):
        # The regression case: a single weak 0.4 title keyword must stay at 0.4,
        # not normalise to 1.0.
        cands = doc_kind_candidates(title="feat: setup guide", touched_paths=[])
        self.assertEqual(cands[0]["kind"], "user-guide")
        self.assertAlmostEqual(cands[0]["confidence"], 0.4)
        self.assertLess(cands[0]["confidence"], 0.85)


class TestDocKindCandidates(unittest.TestCase):
    def test_middleware_code_leans_reference(self):
        cands = doc_kind_candidates(
            title="feat: add onDenyResponse to token ratelimit middleware",
            touched_paths=["hub/pkg/middleware/tokenratelimit/config.go"]
        )
        top = cands[0]
        self.assertEqual(top["kind"], "reference")
        self.assertGreater(top["confidence"], 0.5)

    def test_dashboard_code_leans_user_guide(self):
        cands = doc_kind_candidates(
            title="feat: add quota panel",
            touched_paths=["hub/dashboard/src/QuotaPanel.tsx"]
        )
        self.assertEqual(cands[0]["kind"], "user-guide")

    def test_title_hint_guide(self):
        cands = doc_kind_candidates(
            title="feat: guide for setting up X",
            touched_paths=[]
        )
        self.assertEqual(cands[0]["kind"], "user-guide")


class TestClassifyConfidenceBoundary(unittest.TestCase):
    """Confidence drives the SKILL.md 0.85 auto-accept gate. Verify a lone signal
    stays below it (asks) while corroborating signals cross it (auto-accept)."""

    def _bundle(self, title, paths):
        return {
            "impl_repo": "traefik/traefik-hub",
            "prs": [{"number": 1, "title": title, "labels": [], "body": ""}],
            "merged": {
                "files_changed": [{"path": p} for p in paths],
                "primary_pr": 1,
            },
        }

    def test_single_signal_below_gate_asks(self):
        # One reference signal (0.6) is below 0.85 → the skill must still confirm.
        result = classify(
            self._bundle("feat: add X", ["hub/pkg/middleware/cors/config.go"]),
            grounding={"concepts": []},
            neighbor_paths=[],
        )
        self.assertEqual(result["doc_kind_candidates"][0]["kind"], "reference")
        self.assertLess(result["confidence"], 0.85)

    def test_corroborating_signals_cross_gate(self):
        # Path signal (0.6) + title keyword (0.4) = 1.0 → above 0.85 → auto-accept.
        result = classify(
            self._bundle("feat: CRD reference", ["hub/pkg/middleware/cors/config.go"]),
            grounding={"concepts": []},
            neighbor_paths=[],
        )
        self.assertEqual(result["doc_kind_candidates"][0]["kind"], "reference")
        self.assertGreaterEqual(result["confidence"], 0.85)

    def test_no_signal_confidence_is_0_5(self):
        # No signals → default 0.5 confidence, which is below 0.85, forcing confirmation.
        result = classify(
            self._bundle("", []),
            grounding={"concepts": []},
            neighbor_paths=[],
        )
        self.assertEqual(result["confidence"], 0.5)
        self.assertLess(result["confidence"], 0.85)


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


class TestClassifyWithNoPR(unittest.TestCase):
    """A fetch_issue.py bundle: no implementation PR at all, so classify()
    can't derive `primary` from bundle["prs"] (empty) -- it must fall back to
    the issue itself as the title/body signal instead of crashing."""

    def _issue_bundle(self, title, body="", labels=None):
        issue = {"number": 2930, "repo": "traefik/hub-issues", "title": title,
                  "body": body, "labels": labels or [], "state": "CLOSED", "comments": []}
        return {
            "impl_repo": "traefik/traefik-hub",
            "prs": [],
            "merged": {
                "files_changed": [],
                "primary_pr": None,
                "linked_issues": [issue],
                "sub_issues": [],
                "related_prs": [],
            },
            "existing_doc_pr": None,
            "issue": issue,
        }

    def test_does_not_crash_with_empty_prs(self):
        result = classify(
            self._issue_bundle("regex anchoring usage tip"),
            grounding={"concepts": []},
            neighbor_paths=[],
        )
        self.assertIn("doc_kind_candidates", result)

    def test_uses_issue_title_as_signal(self):
        result = classify(
            self._issue_bundle("docs: CRD reference for regex anchoring"),
            grounding={"concepts": []},
            neighbor_paths=[],
        )
        self.assertEqual(result["feature_type"], "docs")

    def test_needs_release_note_false_with_no_pr(self):
        # No PR means nothing shipped in a release -- never a release note.
        result = classify(
            self._issue_bundle("clarify harmless debug log"),
            grounding={"concepts": []},
            neighbor_paths=[],
        )
        self.assertEqual(result["needs_release_note"]["verdict"], "no")


if __name__ == "__main__":
    unittest.main()
