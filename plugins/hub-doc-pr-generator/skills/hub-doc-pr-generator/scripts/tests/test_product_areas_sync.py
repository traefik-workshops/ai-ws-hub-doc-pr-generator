"""Guards against the exact drift Part 2 of the classify/locate confidence
work was meant to close: a product-area prefix added to locate_targets.py's
placement maps (HUB_REF_MAP/HUB_GUIDE_MAP) without also teaching classify.py's
doc-kind scoring about it, or vice versa.

See scripts/_product_areas.py's module docstring for why placement and
doc-kind-scoring prefixes are kept as separate constants rather than one
literally-shared data structure -- this test is what makes that split safe:
every non-generic placement prefix must have SOME doc-kind-scoring opinion.
"""
from __future__ import annotations

import unittest

from scripts._product_areas import (
    HUB_REF_MAP, HUB_GUIDE_MAP, REFERENCE_SIGNAL_PREFIXES, GUIDE_SIGNAL_PREFIXES,
)


def _non_generic_prefixes(*maps: dict) -> set[str]:
    return {prefix for m in maps for prefix, section in m.items() if not section.generic}


class TestPlacementAndScoringPrefixesStaySynced(unittest.TestCase):
    def test_every_non_generic_placement_prefix_has_a_scoring_opinion(self):
        known_signal_prefixes = set(REFERENCE_SIGNAL_PREFIXES) | set(GUIDE_SIGNAL_PREFIXES)
        placement_prefixes = _non_generic_prefixes(HUB_REF_MAP, HUB_GUIDE_MAP)
        missing = placement_prefixes - known_signal_prefixes
        self.assertEqual(
            missing, set(),
            msg=f"{missing} is a real (non-generic) product-area prefix in "
                "HUB_REF_MAP/HUB_GUIDE_MAP with no corresponding entry in "
                "REFERENCE_SIGNAL_PREFIXES or GUIDE_SIGNAL_PREFIXES -- "
                "classify.py's doc-kind scoring doesn't know this prefix "
                "exists. Add it to one of the two signal-prefix tuples in "
                "scripts/_product_areas.py.",
        )

    def test_every_signal_prefix_is_a_real_placement_prefix(self):
        # The reverse direction: a signal prefix that names something not
        # actually in either placement map is very likely a typo, not a
        # deliberate choice -- REFERENCE_SIGNAL_PREFIXES/GUIDE_SIGNAL_PREFIXES
        # exist to score touches that locate_targets.py also recognizes for
        # placement, not to invent new prefixes locate_targets never sees.
        placement_prefixes = set(HUB_REF_MAP) | set(HUB_GUIDE_MAP)
        for prefix in (*REFERENCE_SIGNAL_PREFIXES, *GUIDE_SIGNAL_PREFIXES):
            self.assertIn(
                prefix, placement_prefixes,
                msg=f"{prefix!r} is a doc-kind signal prefix with no matching "
                    "entry in HUB_REF_MAP/HUB_GUIDE_MAP -- likely a typo.",
            )

    def test_reference_and_guide_signal_prefixes_are_disjoint(self):
        # A prefix scored as both a reference AND a guide signal would double
        # the intent -- each prefix should represent one classify.py judgment
        # call, not two agreeing or conflicting ones.
        overlap = set(REFERENCE_SIGNAL_PREFIXES) & set(GUIDE_SIGNAL_PREFIXES)
        self.assertEqual(overlap, set())


if __name__ == "__main__":
    unittest.main()
