import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from scripts.write_flags import render_needs_verification_section, main


def _classify(confidence, kind="reference", rationale="touches config/middleware Go package",
              runner_up_kind="user-guide", runner_up_confidence=0.4, runner_up_rationale="no signal"):
    return {
        "doc_kind_candidates": [
            {"kind": kind, "confidence": confidence, "rationale": rationale},
            {"kind": runner_up_kind, "confidence": runner_up_confidence, "rationale": runner_up_rationale},
        ],
    }


def _locate(confidence, path="docs/ai-gateway/middlewares/new-thing.md",
            rationale="Inferred section dir from touched paths"):
    return {
        "candidates": [
            {"path": path, "confidence": confidence, "rationale": rationale, "neighbors": []},
        ],
    }


class TestRenderNeedsVerificationSection(unittest.TestCase):
    def test_empty_when_both_confident(self):
        md = render_needs_verification_section(
            classify_result=_classify(0.9), locate_result=_locate(0.9),
        )
        self.assertEqual(md, "")

    def test_flags_low_confidence_kind_with_runner_up(self):
        md = render_needs_verification_section(
            classify_result=_classify(0.6), locate_result=_locate(0.9),
        )
        self.assertIn("## Needs verification", md)
        self.assertIn("Doc kind", md)
        self.assertIn("reference", md)
        self.assertIn("user-guide", md)  # runner-up named
        self.assertNotIn("Target path", md)

    def test_flags_low_confidence_path_with_runner_up(self):
        md = render_needs_verification_section(
            classify_result=_classify(0.9), locate_result=_locate(0.5),
        )
        self.assertIn("Target path", md)
        self.assertIn("docs/ai-gateway/middlewares/new-thing.md", md)
        self.assertNotIn("Doc kind", md)

    def test_flags_both_when_both_low(self):
        md = render_needs_verification_section(
            classify_result=_classify(0.6), locate_result=_locate(0.5),
        )
        self.assertIn("Doc kind", md)
        self.assertIn("Target path", md)

    def test_no_runner_up_still_renders(self):
        classify_result = {"doc_kind_candidates": [{"kind": "reference", "confidence": 0.5, "rationale": "no signal"}]}
        locate_result = {"candidates": []}
        md = render_needs_verification_section(classify_result=classify_result, locate_result=locate_result)
        self.assertIn("Doc kind", md)
        self.assertNotIn("runner-up", md)

    def test_custom_thresholds(self):
        md = render_needs_verification_section(
            classify_result=_classify(0.8), locate_result=_locate(0.9),
            kind_threshold=0.7,
        )
        self.assertEqual(md, "")

    def test_override_renders_even_when_both_confident(self):
        md = render_needs_verification_section(
            classify_result=_classify(0.9), locate_result=_locate(0.9),
            overrides=[("docs/api-management/api-auth.md",
                        "linked issue points to this existing page")],
        )
        self.assertIn("## Needs verification", md)
        self.assertIn("Override", md)
        self.assertIn("docs/api-management/api-auth.md", md)
        self.assertIn("linked issue points to this existing page", md)

    def test_override_and_low_confidence_both_render(self):
        md = render_needs_verification_section(
            classify_result=_classify(0.6), locate_result=_locate(0.9),
            overrides=[("docs/x.md", "reason")],
        )
        self.assertIn("Doc kind", md)
        self.assertIn("Override", md)

    def test_no_overrides_and_no_low_confidence_is_empty(self):
        md = render_needs_verification_section(
            classify_result=_classify(0.9), locate_result=_locate(0.9), overrides=[],
        )
        self.assertEqual(md, "")


class TestMainOverrideParsing(unittest.TestCase):
    def test_cli_override_flag_parses_path_and_reason(self):
        with tempfile.TemporaryDirectory() as td:
            classify_path = Path(td) / "classify.json"
            locate_path = Path(td) / "locate.json"
            classify_path.write_text(json.dumps(_classify(0.9)))
            locate_path.write_text(json.dumps(_locate(0.9)))
            buf = StringIO()
            with redirect_stdout(buf):
                main([
                    "--classify", str(classify_path), "--locate", str(locate_path),
                    "--override", "docs/api-management/api-auth.md:linked issue points here",
                ])
            out = json.loads(buf.getvalue())
        self.assertIn("Override", out["needs_verification_md"])
        self.assertIn("docs/api-management/api-auth.md", out["needs_verification_md"])


if __name__ == "__main__":
    unittest.main()
