import tempfile
import unittest
from pathlib import Path
from scripts.collect_fragments import parse_fragment, collect, for_version, _pr_number, main

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

FRAGMENT_BLANK_TARGET_VERSION = """---
shape: ea-subsection
source_prs: [990]
target_version:
---

#### Blank Version Feature
"""

FRAGMENT_MISMATCHED_QUOTES = """---
shape: ea-subsection
source_prs: [990]
target_version: 'unassigned"
---

#### Mismatched Quotes Feature
"""

FRAGMENT_GARBLED_VERSION = """---
shape: ea-subsection
source_prs: [990]
target_version: not-a-real-version
---

#### Garbled Version Feature
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

    def test_blank_target_version_raises(self):
        """Regression test: a blank `target_version:` line previously hit the
        same "empty value = nested block header" branch that lets `compat:`
        work, so it never became a dict key at all -- collect()'s old
        falsy-value check then silently treated that identically to the
        deliberate 'unassigned' sentinel, while the shared
        UNASSIGNED_TARGET_VERSION_RE regex (used by preview.py and
        assign_target_version.assign()) only recognizes the literal token.
        That meant a blank fragment wasn't flagged at PR-preview time but was
        later refused by assign() -- a confusing dead end. Blank/missing is
        malformed input, not a legitimate third state, so this must raise."""
        with self.assertRaises(ValueError):
            parse_fragment(FRAGMENT_BLANK_TARGET_VERSION)

    def test_mismatched_quotes_raise_instead_of_orphaning_the_fragment(self):
        """Regression test: UNASSIGNED_TARGET_VERSION_RE's independent ['\"]?
        on each side matched a MISMATCHED quote pair ('unassigned" -- single
        open, double close), but unquote() requires the SAME character on
        both ends and left the stray quotes in place. That produced a value
        that was neither the clean 'unassigned' sentinel nor a real version --
        collect() silently miscategorized it as "assigned" (since it wasn't
        exactly "unassigned") with a garbage value for_version() could never
        match against any real cut, permanently orphaning the fragment:
        invisible to both the interactive assignment prompt and every future
        cut. This must raise at parse time instead."""
        with self.assertRaises(ValueError):
            parse_fragment(FRAGMENT_MISMATCHED_QUOTES)

    def test_garbled_non_version_value_raises(self):
        """Any target_version that's neither the literal sentinel nor a
        parseable version is malformed input, regardless of how it got that
        way -- not just the mismatched-quote case above."""
        with self.assertRaises(ValueError):
            parse_fragment(FRAGMENT_GARBLED_VERSION)

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
            (d / "_964-bedrock-mantle.mdx").write_text(FRAGMENT_EA)
            (d / "_970-messages-api.mdx").write_text(FRAGMENT_UNASSIGNED)
            result = collect(d)
        self.assertEqual(len(result["fragments"]), 2)
        self.assertEqual(len(result["assigned"]), 1)
        self.assertEqual(len(result["unassigned"]), 1)
        self.assertEqual(result["assigned"][0]["target_version"], "v3.21.0-ea.1")
        self.assertEqual(result["unassigned"][0]["filename"], "_970-messages-api.mdx")

    def test_missing_directory_returns_empty(self):
        result = collect(Path("/nonexistent/release-notes.d"))
        self.assertEqual(result, {"fragments": [], "assigned": [], "unassigned": []})

    def test_pr_number_extracted_from_filename(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "_964-bedrock-mantle.mdx").write_text(FRAGMENT_EA)
            result = collect(d)
        self.assertEqual(result["fragments"][0]["pr_number"], 964)

    def test_malformed_filename_raises_instead_of_collecting_silently(self):
        """Regression test: a fragment filename with no PR-number prefix
        previously silently defaulted to pr_number=0 (sorting as if it were
        the oldest possible PR) instead of surfacing that its ordering can't
        be trusted -- inconsistent with parse_fragment's and assign()'s
        loud-failure behavior elsewhere in this pipeline."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "bedrock-mantle-no-pr-prefix.mdx").write_text(FRAGMENT_EA)
            with self.assertRaises(ValueError):
                collect(d)

    def test_orders_by_pr_number_not_filename_string(self):
        """Regression test: sorted(glob(...)) with no key sorts filenames as
        plain strings, so '10-x.mdx' comes before '9-x.mdx' ('1' < '9'
        lexicographically). SKILL.md's cut-mode step 2 lists collect()'s
        `unassigned` slice in this exact order for the interactive "which of
        these belong to this release" prompt -- a writer with fragments from
        PR #9 and PR #10 would see #10 offered first, which reads as though
        it's the older one."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "_10-second.mdx").write_text(FRAGMENT_UNASSIGNED.replace("970", "10"))
            (d / "_9-first.mdx").write_text(FRAGMENT_UNASSIGNED.replace("970", "9"))
            result = collect(d)
        self.assertEqual([f["pr_number"] for f in result["fragments"]], [9, 10])

    def test_malformed_front_matter_error_names_the_file(self):
        """Regression test: parse_fragment's own ValueError message never
        names the file it was parsing -- previously a writer saw e.g.
        "fragment's front matter has no target_version value" with no way to
        tell which of possibly many accumulated fragments (never deleted, by
        the round-7 no-delete design) that referred to."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "_990-blank-version.mdx").write_text(FRAGMENT_BLANK_TARGET_VERSION)
            with self.assertRaises(ValueError) as ctx:
                collect(d)
        self.assertIn("_990-blank-version.mdx", str(ctx.exception))


class TestPrNumber(unittest.TestCase):
    def test_raises_on_missing_prefix(self):
        with self.assertRaises(ValueError):
            _pr_number("bedrock-mantle-no-pr-prefix.mdx")

    def test_extracts_leading_number(self):
        self.assertEqual(_pr_number("_964-bedrock-mantle.mdx"), 964)

    def test_accepts_legacy_filename_without_underscore(self):
        """Regression/transition test: fragments written before the
        underscore-prefix filename convention (see release-note-heuristics.md
        -- the prefix keeps Docusaurus's default exclude glob from trying to
        build fragments as real pages) must still be collectible so an
        in-flight fragment from before the fix isn't silently dropped from a
        cut."""
        self.assertEqual(_pr_number("964-bedrock-mantle.mdx"), 964)


class TestForVersion(unittest.TestCase):
    def test_filters_and_orders_newest_first_by_pr_number(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "_964-bedrock-mantle.mdx").write_text(FRAGMENT_EA)
            (d / "_980-hardened-image.mdx").write_text(FRAGMENT_GA_BULLET)
            (d / "_970-messages-api.mdx").write_text(FRAGMENT_UNASSIGNED)
            fragments = collect(d)["fragments"]
        ordered = for_version(fragments, "v3.21.0-ea.1")
        self.assertEqual([f["pr_number"] for f in ordered], [980, 964])

    def test_excludes_other_versions(self):
        fragments = [
            {"target_version": "v3.21.0-ea.1", "pr_number": 1},
            {"target_version": "v3.20.0-ea.8", "pr_number": 2},
        ]
        self.assertEqual(len(for_version(fragments, "v3.21.0-ea.1")), 1)

    def test_matches_case_insensitively(self):
        """Regression test: a fragment stamped with different casing than the
        --version argument previously silently vanished from the assembled
        section instead of matching -- same bug class already fixed twice for
        compat component names, left open here for version strings."""
        fragments = [{"target_version": "v3.21.0-EA.1", "pr_number": 1}]
        self.assertEqual(len(for_version(fragments, "v3.21.0-ea.1")), 1)

    def test_matches_with_incidental_whitespace(self):
        fragments = [{"target_version": " v3.21.0-ea.1 ", "pr_number": 1}]
        self.assertEqual(len(for_version(fragments, "v3.21.0-ea.1")), 1)

    def test_matches_missing_v_prefix(self):
        """Regression test: a fragment stamped without the leading `v`
        previously silently didn't match -- not flagged as unassigned (it has
        a non-empty value), not included in the assembled section either,
        just silently absent with zero error."""
        fragments = [{"target_version": "3.20.7", "pr_number": 1}]
        self.assertEqual(len(for_version(fragments, "v3.20.7")), 1)

    def test_matches_v_prefix_and_case_drift_together(self):
        fragments = [{"target_version": "3.21.0-EA.1", "pr_number": 1}]
        self.assertEqual(len(for_version(fragments, "v3.21.0-ea.1")), 1)

    def test_non_semver_value_falls_back_to_exact_string_match(self):
        """A value that doesn't parse as semver at all (e.g. hand-typo'd) still
        gets an exact-match chance via the fallback, rather than being treated
        as unmatchable against everything."""
        fragments = [{"target_version": "not-a-version", "pr_number": 1}]
        self.assertEqual(len(for_version(fragments, "not-a-version")), 1)
        self.assertEqual(len(for_version(fragments, "v3.20.7")), 0)


class TestMain(unittest.TestCase):
    def test_returns_zero_and_prints_json_on_success(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "_964-bedrock-mantle.mdx").write_text(FRAGMENT_EA)
            rc = main(["--release-notes-dir", str(d)])
        self.assertEqual(rc, 0)

    def test_malformed_fragment_returns_nonzero_instead_of_raising(self):
        """Regression test: previously a ValueError from a malformed fragment
        (bad front matter, or a misnamed file per _pr_number) propagated all
        the way out of main() as a raw traceback instead of a clean error --
        inconsistent with assign_target_version.py's main(), which already
        catches ValueError and returns 1."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "no-pr-prefix.mdx").write_text(FRAGMENT_EA)
            rc = main(["--release-notes-dir", str(d)])  # must not raise
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
