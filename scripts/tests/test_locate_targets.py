import unittest
from scripts.locate_targets import propose_paths


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


if __name__ == "__main__":
    unittest.main()
