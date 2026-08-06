import unittest
import tempfile
from pathlib import Path
from scripts.locate_targets import propose_paths
from scripts.locate_targets import select_neighbors
from scripts.locate_targets import sidebar_insertion_point, build_locate
from scripts.locate_targets import existing_doc_refs, issue_texts_from_bundle
from scripts.locate_targets import find_transcluded_partials


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

    def test_existing_middleware_page_preferred_over_fabricated_slug(self):
        # Regression for #2806: touched hub/pkg/middleware/contentguard/... with an
        # unrelated feature slug must not fabricate a new page when
        # docs/ai-gateway/middlewares/content-guard.md already exists -- the
        # package name "contentguard" and the filename "content-guard" match once
        # hyphens are stripped.
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/ai-gateway/middlewares"
            d.mkdir(parents=True)
            (d / "content-guard.md").write_text("existing page")
            cands = propose_paths(
                impl_repo="traefik/traefik-hub",
                doc_kind="reference",
                feature_slug="presidio-score-threshold",
                touched_paths=["hub/pkg/middleware/contentguard/engine/presidio.go"],
                doc_repo_root=td,
            )
        self.assertEqual(cands[0]["path"], "docs/ai-gateway/middlewares/content-guard.md")
        self.assertGreaterEqual(cands[0]["confidence"], 0.75)

    def test_multiple_touched_packages_ranked_by_touch_count(self):
        # Regression for #2927: touching both chatcompletion (1 file) and
        # responsesapi (2 files) must rank responses-api.md first, matching the
        # actually-correct target for that PR.
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/ai-gateway/middlewares"
            d.mkdir(parents=True)
            (d / "chat-completion.md").write_text("x")
            (d / "responses-api.md").write_text("y")
            cands = propose_paths(
                impl_repo="traefik/traefik-hub",
                doc_kind="reference",
                feature_slug="responses-api-field-preservation",
                touched_paths=[
                    "hub/pkg/middleware/chatcompletion/middleware.go",
                    "hub/pkg/middleware/responsesapi/config.go",
                    "hub/pkg/middleware/responsesapi/middleware.go",
                ],
                doc_repo_root=td,
            )
        self.assertEqual(cands[0]["path"], "docs/ai-gateway/middlewares/responses-api.md")
        self.assertEqual(cands[1]["path"], "docs/ai-gateway/middlewares/chat-completion.md")

    def test_no_existing_match_caps_fabricated_confidence_below_gate(self):
        # A genuinely new middleware with no existing page: the fabricated
        # {slug}.md is the right call, but its confidence must not clear the
        # 0.75 auto-accept gate on directory-match strength alone -- the
        # existing-page check ran and found nothing, which is weaker evidence
        # than an actual filename match.
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/ai-gateway/middlewares"
            d.mkdir(parents=True)
            (d / "llm-guard.md").write_text("unrelated")
            cands = propose_paths(
                impl_repo="traefik/traefik-hub",
                doc_kind="reference",
                feature_slug="brand-new-middleware",
                touched_paths=["hub/pkg/middleware/brandnewmw/config.go"],
                doc_repo_root=td,
            )
        self.assertTrue(cands[0]["path"].endswith("brand-new-middleware.md"))
        self.assertLess(cands[0]["confidence"], 0.75)

    def test_confidence_unaffected_when_doc_repo_root_omitted(self):
        # Legacy pure-heuristic callers (no filesystem access) must keep
        # getting the old high confidence -- the cap only applies once we've
        # actually had the chance to check for an existing page and found none.
        cands = propose_paths(
            impl_repo="traefik/traefik-hub",
            doc_kind="reference",
            feature_slug="token-ratelimit-deny-response",
            touched_paths=["hub/pkg/middleware/tokenratelimit/config.go"],
        )
        self.assertGreaterEqual(cands[0]["confidence"], 0.85)


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


class TestIssueTextsFromBundle(unittest.TestCase):
    def test_collects_issue_and_comment_bodies(self):
        bundle = {
            "merged": {
                "linked_issues": [
                    {"body": "See docs/api-management/api-auth for context",
                     "comments": [{"body": "also check https://doc.traefik.io/traefik-hub/api-management/api-auth"}]},
                ]
            }
        }
        texts = issue_texts_from_bundle(bundle)
        self.assertEqual(len(texts), 2)

    def test_no_linked_issues_returns_empty(self):
        self.assertEqual(issue_texts_from_bundle({"merged": {}}), [])


class TestExistingDocRefs(unittest.TestCase):
    def test_finds_literal_repo_path_if_file_exists(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/api-management"
            d.mkdir(parents=True)
            (d / "api-auth.md").write_text("existing page")
            refs = existing_doc_refs(
                ["The real place for this is docs/api-management/api-auth.md, please use it."],
                doc_repo_root=td,
            )
        self.assertEqual(refs, ["docs/api-management/api-auth.md"])

    def test_finds_doc_url_and_resolves_to_existing_file(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/api-management"
            d.mkdir(parents=True)
            (d / "api-auth.md").write_text("existing page")
            refs = existing_doc_refs(
                ["See https://doc.traefik.io/traefik-hub/api-management/api-auth for details."],
                doc_repo_root=td,
            )
        self.assertEqual(refs, ["docs/api-management/api-auth.md"])

    def test_ignores_path_or_url_that_does_not_exist(self):
        with tempfile.TemporaryDirectory() as td:
            refs = existing_doc_refs(
                ["Should live at docs/nope/does-not-exist.md",
                 "or maybe https://doc.traefik.io/traefik-hub/nope/does-not-exist"],
                doc_repo_root=td,
            )
        self.assertEqual(refs, [])

    def test_no_issue_text_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(existing_doc_refs([], doc_repo_root=td), [])

    def test_dedupes_same_path_mentioned_twice(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/api-management"
            d.mkdir(parents=True)
            (d / "api-auth.md").write_text("x")
            refs = existing_doc_refs(
                ["docs/api-management/api-auth.md",
                 "as mentioned, docs/api-management/api-auth.md is the place"],
                doc_repo_root=td,
            )
        self.assertEqual(refs, ["docs/api-management/api-auth.md"])


class TestBuildLocate(unittest.TestCase):
    def test_issue_referenced_existing_page_outranks_heuristic(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/api-management"
            d.mkdir(parents=True)
            (d / "api-auth.md").write_text("existing page")
            out = build_locate(
                impl_repo="traefik/traefik-hub",
                doc_repo_root=td,
                doc_kind="reference",
                feature_slug="keyless-authentication",
                touched_paths=["hub/pkg/middleware/keylessauth/config.go"],
                issue_texts=["The doc for this already exists: docs/api-management/api-auth.md"],
            )
        self.assertEqual(out["candidates"][0]["path"], "docs/api-management/api-auth.md")
        self.assertGreaterEqual(out["candidates"][0]["confidence"], 0.9)
        self.assertTrue(out["target_exists"])
        # Heuristic candidate is still present, just no longer first.
        self.assertGreater(len(out["candidates"]), 1)

    def test_ambiguous_multiple_issue_refs_falls_back_to_heuristic(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/api-management"
            d.mkdir(parents=True)
            (d / "api-auth.md").write_text("x")
            (d / "api-key.md").write_text("y")
            out = build_locate(
                impl_repo="traefik/traefik-hub",
                doc_repo_root=td,
                doc_kind="reference",
                feature_slug="keyless-authentication",
                touched_paths=["hub/pkg/middleware/keylessauth/config.go"],
                issue_texts=["Could go in docs/api-management/api-auth.md or docs/api-management/api-key.md"],
            )
        self.assertTrue(out["candidates"][0]["path"].endswith("keyless-authentication.md"))

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


class TestFindTranscludedPartials(unittest.TestCase):
    def test_surfaces_partial_imported_by_candidate_page(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/ai-gateway"
            d.mkdir(parents=True)
            (d / "_shared-partial.mdx").write_text("shared content\n")
            (d / "middlewares").mkdir()
            (d / "middlewares/content-guard.md").write_text(
                "import Shared from '../_shared-partial.mdx';\n\n<Shared />\n"
            )
            hits = find_transcluded_partials(
                doc_repo_root=td,
                candidate_paths=["docs/ai-gateway/middlewares/content-guard.md"],
            )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["path"], "docs/ai-gateway/_shared-partial.mdx")
        self.assertEqual(hits[0]["component"], "Shared")
        self.assertEqual(hits[0]["transcluded_into"], "docs/ai-gateway/middlewares/content-guard.md")

    def test_no_import_means_no_hits(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/ai-gateway/middlewares"
            d.mkdir(parents=True)
            (d / "content-guard.md").write_text("# Content Guard\n\nJust prose.\n")
            hits = find_transcluded_partials(
                doc_repo_root=td,
                candidate_paths=["docs/ai-gateway/middlewares/content-guard.md"],
            )
        self.assertEqual(hits, [])

    def test_same_partial_imported_by_two_pages_surfaces_once(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/ai-gateway"
            d.mkdir(parents=True)
            (d / "_deny-response-formats.mdx").write_text("shared table\n")
            (d / "middlewares").mkdir()
            for name in ("content-guard.md", "llm-guard.md"):
                (d / "middlewares" / name).write_text(
                    "import DenyResponseFormats from '../_deny-response-formats.mdx';\n"
                    "<DenyResponseFormats />\n"
                )
            hits = find_transcluded_partials(
                doc_repo_root=td,
                candidate_paths=[
                    "docs/ai-gateway/middlewares/content-guard.md",
                    "docs/ai-gateway/middlewares/llm-guard.md",
                ],
            )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["path"], "docs/ai-gateway/_deny-response-formats.mdx")

    def test_import_of_non_underscore_file_is_ignored(self):
        """Only the leading-underscore partial-file naming convention counts --
        an ordinary component import (e.g. a shared React component, not a doc
        partial) must not be mistaken for a transcluded partial."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/ai-gateway/middlewares"
            d.mkdir(parents=True)
            (Path(td) / "docs/ai-gateway/widget.mdx").write_text("not a partial\n")
            (d / "content-guard.md").write_text(
                "import Widget from '../widget.mdx';\n<Widget />\n"
            )
            hits = find_transcluded_partials(
                doc_repo_root=td,
                candidate_paths=["docs/ai-gateway/middlewares/content-guard.md"],
            )
        self.assertEqual(hits, [])


class TestPartialsWiredIntoBuildLocate(unittest.TestCase):
    def test_pr_1304_regression_surfaces_shared_partial(self):
        """Regression for traefik-hub#1304: a PR touching multiple middleware
        packages whose pages all transclude the same partial must surface that
        partial as an additional low-confidence candidate, not just the pages
        themselves."""
        with tempfile.TemporaryDirectory() as td:
            gw = Path(td) / "docs/ai-gateway"
            gw.mkdir(parents=True)
            (gw / "_deny-response-formats.mdx").write_text("old shape\n")
            mw = gw / "middlewares"
            mw.mkdir()
            for name in ("content-guard.md", "llm-guard.md", "token-rate-limit.md"):
                (mw / name).write_text(
                    "import DenyResponseFormats from '../_deny-response-formats.mdx';\n"
                    "<DenyResponseFormats />\n"
                )
            out = build_locate(
                impl_repo="traefik/traefik-hub",
                doc_repo_root=td,
                doc_kind="reference",
                feature_slug="responses-api-deny-response-failed-event",
                touched_paths=[
                    "hub/pkg/middleware/aiformat/denyresponse.go",
                    "hub/pkg/middleware/contentguard/middleware.go",
                    "hub/pkg/middleware/llmguard/client_formatter_res_api.go",
                    "hub/pkg/middleware/tokenratelimit/middleware.go",
                    "hub/pkg/middleware/tokenratelimit/responsewriter.go",
                ],
            )
        partial_candidates = [c for c in out["candidates"] if c.get("kind") == "shared_partial"]
        self.assertEqual(len(partial_candidates), 1)
        self.assertEqual(partial_candidates[0]["path"], "docs/ai-gateway/_deny-response-formats.mdx")
        self.assertLess(partial_candidates[0]["confidence"], 0.75)


if __name__ == "__main__":
    unittest.main()
