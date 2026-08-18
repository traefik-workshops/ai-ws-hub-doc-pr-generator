"""Integration tests for the full `cut` pipeline (collect_fragments ->
compat_matrix -> assemble_section -> render_entry), specifically covering the
straggler-fragment re-cut workflow end to end.

This exists because the individual unit tests for each script all passed while
a real data-loss bug slipped through: assemble_section/merge_fragment_deltas
only ever see fragments *currently on disk*, so a design that deleted a
fragment immediately after it was first cut meant a second cut of the same
still-open version silently lost the first cut's content -- no single
function's unit tests could catch that, since the bug was in the *interaction*
between "cut deletes what it consumes" (a SKILL.md-level workflow decision, not
a bug in any one script) and "assemble re-derives from disk" (correct in
isolation). These tests exercise the actual multi-cut workflow to make sure
that class of bug can't recur silently.
"""
import tempfile
import unittest
from pathlib import Path

from scripts.collect_fragments import collect, for_version
from scripts.assemble_section import assemble
from scripts.compat_matrix import merge_fragment_deltas
from scripts.render_entry import splice

FRAGMENT_BEDROCK = (
    "---\nshape: ea-subsection\nsource_prs: [964]\ntarget_version: v3.21.0-ea.1\n"
    "compat:\n  Traefik Proxy: v3.7.10\n---\n\n#### Bedrock Mantle\n\nBedrock body.\n"
)
FRAGMENT_MESSAGES_API = (
    "---\nshape: ea-subsection\nsource_prs: [970]\ntarget_version: v3.21.0-ea.1\n---\n\n"
    "#### Messages API\n\nMessages API body.\n"
)
FRAGMENT_HARDENED_IMAGE_STRAGGLER = (
    "---\nshape: ga-bullet\nsource_prs: [980]\ntarget_version: v3.21.0-ea.1\n---\n\n"
    "- **Hardened Image** is now generally available.\n"
)

BASE_MATRIX = {
    "traefik_hub": "v3.21.0-ea.1",
    "traefik_proxy": {"version": "v3.7.8", "note": "stale go.mod value"},
}


def _cut_once(fragments_dir: Path, existing_release_notes: str, *, version: str, date: str) -> str:
    """One full cut pass over whatever fragments currently exist on disk --
    mirrors SKILL.md's cut-mode steps 1, 3, 4, 5, 6 exactly (never step 7's old
    delete, which no longer exists)."""
    fragments = collect(fragments_dir)["fragments"]
    ordered = for_version(fragments, version)
    assert ordered, f"no fragments found for {version} -- nothing to cut"
    compat_rows = merge_fragment_deltas(BASE_MATRIX, ordered)
    section = assemble(version=version, date=date, fragments=ordered, compat_rows=compat_rows)
    return splice(existing_release_notes, section)


class TestReCutSameVersionPreservesContent(unittest.TestCase):
    def test_straggler_recut_keeps_prior_content_and_compat_override(self):
        """The exact regression this integration suite exists for: cut once,
        a straggler fragment lands, cut again -- both cuts' content and the
        first cut's compat override must all still be present. Regression
        test: this previously required deleting consumed fragments as part of
        `cut`, which silently dropped this exact content on the second cut."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "964-bedrock-mantle.mdx").write_text(FRAGMENT_BEDROCK)
            (d / "970-messages-api.mdx").write_text(FRAGMENT_MESSAGES_API)

            release_notes = "## Gateway v3.20.6\n\nold\n"
            release_notes = _cut_once(d, release_notes, version="v3.21.0-ea.1", date="2026-08-10")

            self.assertIn("Bedrock Mantle", release_notes)
            self.assertIn("Messages API", release_notes)
            self.assertIn("v3.7.10", release_notes)  # the compat override from Bedrock's fragment

            # No fragment deletion between cuts -- this is the whole point of
            # the fix. A straggler fragment lands.
            (d / "980-hardened-image.mdx").write_text(FRAGMENT_HARDENED_IMAGE_STRAGGLER)

            release_notes = _cut_once(d, release_notes, version="v3.21.0-ea.1", date="2026-08-11")

            self.assertIn("Bedrock Mantle", release_notes, "first cut's content must survive a re-cut")
            self.assertIn("Messages API", release_notes, "first cut's content must survive a re-cut")
            self.assertIn("Hardened Image", release_notes, "the new straggler must be included")
            self.assertIn("v3.7.10", release_notes, "the compat override must survive a re-cut")
            self.assertNotIn("v3.7.8", release_notes, "the stale go.mod value must not resurface")

            # Exactly one section for this version, not a duplicate heading.
            self.assertEqual(release_notes.count("## Gateway v3.21.0-ea.1"), 1)

            # The sibling version is untouched throughout.
            self.assertIn("## Gateway v3.20.6", release_notes)

    def test_fragments_are_never_deleted_from_disk(self):
        """Direct check on the workflow decision itself: nothing in the read
        (collect_fragments) or render (assemble_section/render_entry) path
        removes a fragment file. `cut` only ever reads them."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "964-bedrock-mantle.mdx").write_text(FRAGMENT_BEDROCK)
            (d / "970-messages-api.mdx").write_text(FRAGMENT_MESSAGES_API)

            _cut_once(d, "## Gateway v3.20.6\n\nold\n", version="v3.21.0-ea.1", date="2026-08-10")

            self.assertTrue((d / "964-bedrock-mantle.mdx").is_file())
            self.assertTrue((d / "970-messages-api.mdx").is_file())

    def test_third_cut_with_no_new_fragments_is_a_true_no_op(self):
        """Re-running cut again with nothing new must reproduce byte-identical
        content, not drift or duplicate anything."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "964-bedrock-mantle.mdx").write_text(FRAGMENT_BEDROCK)

            first = _cut_once(d, "## Gateway v3.20.6\n\nold\n", version="v3.21.0-ea.1", date="2026-08-10")
            second = _cut_once(d, first, version="v3.21.0-ea.1", date="2026-08-10")

            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
