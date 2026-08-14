import tempfile
import unittest
from pathlib import Path
from scripts.collect_fragments import parse_fragment, collect, for_version

FRAGMENT_EA = """---
shape: ea-subsection
source_prs: [964]
target_version: v3.21.0-ea.1
compat:
  Traefik Proxy: v3.7.8
---

#### Bedrock Mantle

:::warning Early Access
This feature is currently in early access.
:::

The **Bedrock Mantle** middleware promotes any route to an Anthropic Messages API endpoint.
"""

FRAGMENT_UNASSIGNED = """---
shape: ea-subsection
source_prs: [970]
target_version: unassigned
---

#### Messages API
"""

FRAGMENT_GA_BULLET = """---
shape: ga-bullet
source_prs: [980]
target_version: v3.21.0-ea.1
---

- **Hardened Image** is now generally available. See the [Hardened Image](../setup/installation/hardened-image.md) documentation.
"""

FRAGMENT_QUOTED_SCALARS = """---
shape: ea-subsection
source_prs: [990]
target_version: "v3.21.0-ea.1"
compat:
  "Traefik Proxy": 'v3.7.10'
---

#### Quoted Feature
"""


class TestParseFragment(unittest.TestCase):
    def test_parses_scalars_list_and_nested_compat(self):
        fm = parse_fragment(FRAGMENT_EA)
        self.assertEqual(fm["shape"], "ea-subsection")
        self.assertEqual(fm["source_prs"], [964])
        self.assertEqual(fm["target_version"], "v3.21.0-ea.1")
        self.assertEqual(fm["compat"], {"Traefik Proxy": "v3.7.8"})
        self.assertIn("Bedrock Mantle", fm["body"])

    def test_defaults_compat_to_empty_dict_when_absent(self):
        fm = parse_fragment(FRAGMENT_UNASSIGNED)
        self.assertEqual(fm["compat"], {})
        self.assertEqual(fm["target_version"], "unassigned")

    def test_missing_front_matter_raises(self):
        with self.assertRaises(ValueError):
            parse_fragment("#### No front matter here\n")

    def test_unquotes_scalar_and_nested_compat_values(self):
        """Regression test: quoted scalars (which an LLM generation step can
        plausibly emit even when not required) must be unquoted the same way
        the two other front-matter consumers (extract_neighbor_structure.py,
        fetch_grounding.py) already do via the shared _frontmatter.unquote --
        previously this parser kept the literal quote characters, which would
        have silently broken the `target_version == "unassigned"` sentinel
        check and version-matching in for_version()."""
        fm = parse_fragment(FRAGMENT_QUOTED_SCALARS)
        self.assertEqual(fm["target_version"], "v3.21.0-ea.1")
        self.assertEqual(fm["compat"], {"Traefik Proxy": "v3.7.10"})


class TestCollect(unittest.TestCase):
    def test_splits_assigned_and_unassigned(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "964-bedrock-mantle.mdx").write_text(FRAGMENT_EA)
            (d / "970-messages-api.mdx").write_text(FRAGMENT_UNASSIGNED)
            result = collect(d)
        self.assertEqual(len(result["fragments"]), 2)
        self.assertEqual(len(result["assigned"]), 1)
        self.assertEqual(len(result["unassigned"]), 1)
        self.assertEqual(result["assigned"][0]["target_version"], "v3.21.0-ea.1")
        self.assertEqual(result["unassigned"][0]["filename"], "970-messages-api.mdx")

    def test_missing_directory_returns_empty(self):
        result = collect(Path("/nonexistent/release-notes.d"))
        self.assertEqual(result, {"fragments": [], "assigned": [], "unassigned": []})

    def test_pr_number_extracted_from_filename(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "964-bedrock-mantle.mdx").write_text(FRAGMENT_EA)
            result = collect(d)
        self.assertEqual(result["fragments"][0]["pr_number"], 964)


class TestForVersion(unittest.TestCase):
    def test_filters_and_orders_newest_first_by_pr_number(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "964-bedrock-mantle.mdx").write_text(FRAGMENT_EA)
            (d / "980-hardened-image.mdx").write_text(FRAGMENT_GA_BULLET)
            (d / "970-messages-api.mdx").write_text(FRAGMENT_UNASSIGNED)
            fragments = collect(d)["fragments"]
        ordered = for_version(fragments, "v3.21.0-ea.1")
        self.assertEqual([f["pr_number"] for f in ordered], [980, 964])

    def test_excludes_other_versions(self):
        fragments = [
            {"target_version": "v3.21.0-ea.1", "pr_number": 1},
            {"target_version": "v3.20.0-ea.8", "pr_number": 2},
        ]
        self.assertEqual(len(for_version(fragments, "v3.21.0-ea.1")), 1)


if __name__ == "__main__":
    unittest.main()
