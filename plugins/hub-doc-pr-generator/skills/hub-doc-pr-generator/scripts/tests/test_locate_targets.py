import unittest
import tempfile
from pathlib import Path
from scripts.locate_targets import propose_paths
from scripts.locate_targets import select_neighbors
from scripts.locate_targets import sidebar_insertion_point, build_locate
from scripts.locate_targets import existing_doc_refs, issue_texts_from_bundle
from scripts.locate_targets import build_id_index
from scripts.locate_targets import find_transcluded_partials
from scripts import locate_targets


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

    def test_unmapped_internal_go_paths_do_not_default_to_ai_gateway(self):
        """Regression test for traefik-hub#1435 finding #1: touched files with
        no doc-adjacent mapping at all (pure internal Go: license claims,
        profile resolution, OTel registration) previously defaulted to an AI
        Gateway path with 0.7 confidence -- a confidently wrong guess in a
        specific, unrelated product area. The real target was an existing
        API Gateway observability reference page."""
        cands = propose_paths(
            impl_repo="traefik/traefik-hub",
            doc_kind="reference",
            feature_slug="license-expiration-observability",
            touched_paths=[
                "hub/pkg/hub/license/claims.go",
                "hub/pkg/profile/profile.go",
                "hub/pkg/traefik/register.go",
            ],
        )
        self.assertFalse(any("ai-gateway" in c["path"] for c in cands))
        self.assertLess(cands[0]["confidence"], 0.75)

    def test_authzen_cross_gateway_paths_do_not_default_to_ai_gateway(self):
        """Regression test for the 2026-08-24 AuthZEN finding: AuthZEN spans
        API Gateway + MCP Gateway, neither of which is AI Gateway, but the
        heuristic's only fallback confidently guessed AI Gateway anyway."""
        cands = propose_paths(
            impl_repo="traefik/traefik-hub",
            doc_kind="user-guide",
            feature_slug="understanding-authzen",
            touched_paths=["hub/pkg/mcp/authzen/policy.go"],
        )
        # The generic "hub/pkg/" mapping still surfaces an ai-gateway/guides
        # candidate as a demoted secondary option (it isn't ruled out
        # entirely -- this really could be AI Gateway-relevant), but it must
        # not be the confident top pick the way it was before this fix.
        self.assertNotIn("ai-gateway", cands[0]["path"])

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

    def test_existing_and_fabricated_slug_dedupe_when_same_path(self):
        # If the LLM-chosen feature_slug happens to normalize to the same
        # filename as an existing middleware page (e.g. the slug IS the
        # existing page's name), the existing-page match and the fabricated
        # {slug}.md entry would otherwise both add "content-guard.md" to the
        # output -- once at existing-page confidence, once at the capped
        # fabricated confidence. Only one entry for that path should survive,
        # keeping the higher-priority (existing-page) confidence/rationale.
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/ai-gateway/middlewares"
            d.mkdir(parents=True)
            (d / "content-guard.md").write_text("existing page")
            cands = propose_paths(
                impl_repo="traefik/traefik-hub",
                doc_kind="reference",
                feature_slug="content-guard",
                touched_paths=["hub/pkg/middleware/contentguard/engine/presidio.go"],
                doc_repo_root=td,
            )
        paths = [c["path"] for c in cands]
        self.assertEqual(paths.count("docs/ai-gateway/middlewares/content-guard.md"), 1)
        match = next(c for c in cands if c["path"] == "docs/ai-gateway/middlewares/content-guard.md")
        self.assertEqual(match["rationale"], "Existing page's filename matches a touched middleware package")


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

    def test_resolves_doc_url_slug_via_frontmatter_id_when_filename_differs(self):
        """Regression test for traefik/hub-issues#3075: the URL a human pastes
        into an issue is the rendered site's front-matter `id`, not the
        filename Docusaurus built it from. Real repro: URL ends in
        'ref-oidc', but the file is oidc.md with `id: ref-oidc` -- a
        filename-only scan can't resolve that and falls through to the much
        weaker path heuristic."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/api-gateway/reference/routing/http/middlewares"
            d.mkdir(parents=True)
            (d / "oidc.md").write_text("---\nid: ref-oidc\ntitle: OIDC\n---\n\nContent.\n")
            id_index = build_id_index(td)
            refs = existing_doc_refs(
                ["See https://doc.traefik.io/traefik-hub/api-gateway/reference/routing/"
                 "http/middlewares/ref-oidc for details."],
                doc_repo_root=td,
                id_index=id_index,
            )
        self.assertEqual(refs, ["docs/api-gateway/reference/routing/http/middlewares/oidc.md"])

    def test_filename_match_takes_priority_over_id_index(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/api-management"
            d.mkdir(parents=True)
            (d / "api-auth.md").write_text("---\nid: something-else\n---\n\nx\n")
            id_index = {"api-auth": "docs/api-management/wrong-page.md"}
            refs = existing_doc_refs(
                ["docs/api-management/api-auth.md"],
                doc_repo_root=td,
                id_index=id_index,
            )
        self.assertEqual(refs, ["docs/api-management/api-auth.md"])

    def test_no_id_index_falls_back_to_previous_behavior(self):
        with tempfile.TemporaryDirectory() as td:
            refs = existing_doc_refs(
                ["https://doc.traefik.io/traefik-hub/api-gateway/reference/ref-oidc"],
                doc_repo_root=td,
            )
        self.assertEqual(refs, [])


class TestBuildIdIndex(unittest.TestCase):
    def test_indexes_declared_front_matter_id(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/api-gateway/reference/routing/http/middlewares"
            d.mkdir(parents=True)
            (d / "oidc.md").write_text("---\nid: ref-oidc\ntitle: OIDC\n---\n\nContent.\n")
            index = build_id_index(td)
        self.assertEqual(
            index.get("ref-oidc"),
            "docs/api-gateway/reference/routing/http/middlewares/oidc.md",
        )

    def test_skips_pages_without_id_field(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/api-gateway"
            d.mkdir(parents=True)
            (d / "no-id.md").write_text("---\ntitle: No Id\n---\n\nContent.\n")
            index = build_id_index(td)
        self.assertEqual(index, {})

    def test_skips_pages_with_no_front_matter(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/api-gateway"
            d.mkdir(parents=True)
            (d / "plain.md").write_text("# No front matter here\n")
            index = build_id_index(td)
        self.assertEqual(index, {})

    def test_missing_docs_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            index = build_id_index(td)
        self.assertEqual(index, {})

    def test_unquotes_quoted_id_value(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/api-gateway"
            d.mkdir(parents=True)
            (d / "quoted.md").write_text('---\nid: "ref-quoted"\n---\n\nx\n')
            index = build_id_index(td)
        self.assertEqual(index.get("ref-quoted"), "docs/api-gateway/quoted.md")


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

    def test_issue_referenced_page_already_surfaced_is_not_duplicated(self):
        # Regression: find_existing_middleware_pages() can already surface the
        # human-referenced page, just not necessarily at index 0 (e.g. ranked
        # behind another touched middleware's page). The old guard only
        # checked candidates[0]["path"] != doc_refs[0], so it would re-insert
        # the same path a second time with a different confidence/rationale.
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "docs/ai-gateway/middlewares"
            d.mkdir(parents=True)
            (d / "chat-completion.md").write_text("x")  # touched more -> ranked first
            (d / "responses-api.md").write_text("y")     # touched less, but issue-referenced
            out = build_locate(
                impl_repo="traefik/traefik-hub",
                doc_repo_root=td,
                doc_kind="reference",
                feature_slug="responses-api-field-preservation",
                touched_paths=[
                    "hub/pkg/middleware/chatcompletion/a.go",
                    "hub/pkg/middleware/chatcompletion/b.go",
                    "hub/pkg/middleware/responsesapi/config.go",
                ],
                issue_texts=["See docs/ai-gateway/middlewares/responses-api.md"],
            )
        paths = [c["path"] for c in out["candidates"]]
        self.assertEqual(paths.count("docs/ai-gateway/middlewares/responses-api.md"), 1)

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


class TestMainAcceptsNoTouchedFiles(unittest.TestCase):
    def test_cli_runs_with_zero_touched_files(self):
        """Regression: an issue-only bundle (fetch_issue.py) has no touched Go
        files at all. --touched-files was nargs='+' (required, at least one),
        which argparse itself rejects on zero values -- even though
        build_locate()/propose_paths() already tolerate an empty list fine."""
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "docs/ai-gateway/middlewares").mkdir(parents=True)
            rc = locate_targets.main([
                "--impl-repo", "traefik/traefik-hub",
                "--doc-repo-root", td,
                "--doc-kind", "reference",
                "--feature-slug", "regex-anchoring-tip",
                "--touched-files",
            ])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
