import unittest
import tempfile
from pathlib import Path
from scripts.locate_targets import propose_paths
from scripts.locate_targets import select_neighbors
from scripts.locate_targets import sidebar_insertion_point, build_locate


class TestProposePaths(unittest.TestCase):
    def test_hub_middleware_reference(self):
        cands = propose_paths(
            impl_repo="traefik/traefik-hub",
            doc_kind="reference",
            feature_slug="token-ratelimit-deny-response",
            touched_paths=["hub/pkg/middleware/tokenratelimit/config.go"],
        )
        paths = [c["path"] for c in cands]
        self.assertIn("docs/ai-gateway/middlewares/token-ratelimit-deny-response.md", paths)

    def test_specific_prefix_match_is_high_confidence(self):
        # Regression: one matched prefix fanning out to two candidate dirs must NOT
        # be read as "two competing guesses" and score low. It's one solid signal.
        cands = propose_paths(
            impl_repo="traefik/traefik-hub",
            doc_kind="reference",
            feature_slug="token-ratelimit-deny-response",
            touched_paths=["hub/pkg/middleware/tokenratelimit/config.go"],
        )
        self.assertGreaterEqual(cands[0]["confidence"], 0.85)

    def test_fallback_with_no_matched_prefix_is_low_confidence(self):
        # Regression for the confidence-formula bug: previously the generic
        # single-dir fallback (len(section_dirs) == 1) scored 1.0 -- the highest
        # possible score for the LEAST grounded guess. Must now score low enough
        # to fail both the 0.85 (kind) and 0.75 (path) auto-accept gates.
        cands = propose_paths(
            impl_repo="traefik/traefik-hub",
            doc_kind="reference",
            feature_slug="mystery-feature",
            touched_paths=["hub/something/totally/unmapped.go"],
        )
        self.assertEqual(len(cands), 1)
        self.assertLess(cands[0]["confidence"], 0.75)

    def test_conflicting_prefixes_lower_confidence(self):
        # Touched paths spanning two unrelated mapped prefixes is a genuinely
        # ambiguous signal and must score below the auto-accept gates too.
        cands = propose_paths(
            impl_repo="traefik/traefik-hub",
            doc_kind="reference",
            feature_slug="cross-cutting-feature",
            touched_paths=[
                "hub/pkg/middleware/tokenratelimit/config.go",
                "hub/dashboard/src/App.tsx",
            ],
        )
        self.assertLess(cands[0]["confidence"], 0.75)

    def test_hub_user_guide(self):
        cands = propose_paths(
            impl_repo="traefik/traefik-hub",
            doc_kind="user-guide",
            feature_slug="quota-panel",
            touched_paths=["hub/dashboard/src/QuotaPanel.tsx"],
        )
        self.assertTrue(any("guides" in c["path"] for c in cands))

    def test_oss_reference(self):
        cands = propose_paths(
            impl_repo="traefik/traefik",
            doc_kind="reference",
            feature_slug="encoded-characters-middleware",
            touched_paths=["pkg/middlewares/encodedcharacters/middleware.go"],
        )
        self.assertTrue(
            any(c["path"].startswith("docs/content/reference/") for c in cands)
        )


class TestSelectNeighbors(unittest.TestCase):
    def test_picks_up_to_five_md_files(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/ai-gateway/middlewares"
            d.mkdir(parents=True)
            for name in ("llm-guard.md", "token-rate-limit.md", "content-guard.md",
                         "parallel-llm-guard.md", "mcp.md", "extra.md"):
                (d / name).write_text("placeholder")
            picked = select_neighbors(
                doc_repo_root=td,
                target_path="docs/ai-gateway/middlewares/new-thing.md",
            )
        self.assertLessEqual(len(picked), 5)
        self.assertTrue(all(p.endswith(".md") for p in picked))

    def test_returns_empty_if_dir_missing(self):
        with tempfile.TemporaryDirectory() as td:
            picked = select_neighbors(
                doc_repo_root=td,
                target_path="docs/nope/x.md",
            )
        self.assertEqual(picked, [])


class TestSidebarInsertionPoint(unittest.TestCase):
    def test_finds_section_by_dir_prefix(self):
        sidebars_js = '''
const sidebars = {
  apiSidebar: [
    { type: "category", label: "AI Gateway", items: [
      "ai-gateway/middlewares/llm-guard",
      "ai-gateway/middlewares/content-guard",
    ]},
  ],
};
'''
        ins = sidebar_insertion_point(
            sidebars_js, target_path="docs/ai-gateway/middlewares/new-thing.md",
        )
        self.assertEqual(ins["after_id"], "ai-gateway/middlewares/content-guard")


class TestBuildLocate(unittest.TestCase):
    def test_envelope(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "docs/ai-gateway/middlewares").mkdir(parents=True)
            (Path(td) / "docs/ai-gateway/middlewares/llm-guard.md").write_text("x")
            (Path(td) / "sidebars.js").write_text(
                'const sidebars = { apiSidebar: ["ai-gateway/middlewares/llm-guard"] };'
            )
            out = build_locate(
                impl_repo="traefik/traefik-hub",
                doc_repo_root=td,
                doc_kind="reference",
                feature_slug="new-thing",
                touched_paths=["hub/pkg/middleware/newthing/config.go"],
            )
        self.assertTrue(out["candidates"][0]["path"].endswith("new-thing.md"))
        self.assertEqual(out["sidebar_insertion_point"]["file"], "sidebars.js")

    def test_target_exists_false_for_new_page(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "docs/ai-gateway/middlewares").mkdir(parents=True)
            out = build_locate(
                impl_repo="traefik/traefik-hub",
                doc_repo_root=td,
                doc_kind="reference",
                feature_slug="new-thing",
                touched_paths=["hub/pkg/middleware/newthing/config.go"],
            )
        self.assertFalse(out["target_exists"])

    def test_target_exists_true_when_page_already_present(self):
        # The in-place-edit case (extending an existing page): the LLM step needs
        # this flag to know it must Read the full current file, not just summaries.
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/ai-gateway/middlewares"
            d.mkdir(parents=True)
            (d / "new-thing.md").write_text("existing content\n")
            out = build_locate(
                impl_repo="traefik/traefik-hub",
                doc_repo_root=td,
                doc_kind="reference",
                feature_slug="new-thing",
                touched_paths=["hub/pkg/middleware/newthing/config.go"],
            )
        self.assertTrue(out["target_exists"])


if __name__ == "__main__":
    unittest.main()
