"""Telling somebody what to shoot is worth more than telling them what is wrong.

Two of the three targets on the operator's own card have no matching darks.
The tool stated that fact and stopped there. A fact is not actionable; the
exposure and gain to shoot tonight is.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dwarf2siril.grouping import build_group
from dwarf2siril.scanner import scan

from test_core import make_darks, make_session


class AdviceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Astronomy"
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _group(self, with_darks: bool):
        make_session(
            self.root, "DWARF_RAW_TELE_M 31_EXP_30_GAIN_60_A", "M 31", 30, 60, 4
        )
        if with_darks:
            make_darks(self.root, 30, 60, 5)
        result = scan(self.root)
        return build_group(result.eq_sessions, result.darks)

    def test_it_names_the_exact_settings_to_shoot(self) -> None:
        """The two numbers the telescope needs, taken from these very frames."""
        group = self._group(with_darks=False)
        self.assertEqual(("30s", 60), group.dark_recipe)
        advice = group.dark_advice
        self.assertIn("30s", advice)
        self.assertIn("gain 60", advice)

    def test_it_says_what_to_do_not_only_what_is_wrong(self) -> None:
        advice = self._group(with_darks=False).dark_advice.lower()
        self.assertIn("lens cap", advice)
        self.assertIn("dwarf_dark", advice)
        # And that it is a one-off, which is the part that makes it worth doing.
        self.assertIn("automatically", advice)

    def test_it_says_what_it_costs_them(self) -> None:
        advice = self._group(with_darks=False).dark_advice.lower()
        self.assertIn("amp glow", advice)

    def test_it_is_help_rather_than_a_telling_off(self) -> None:
        """An uncalibrated stack is a real picture and they have been making them.

        Pinned because the difference between "here is how to make this
        better" and "you did it wrong" is the whole value of the feature,
        and it is the kind of thing an edit erodes without anyone noticing.
        """
        advice = self._group(with_darks=False).dark_advice.lower()
        self.assertIn("still makes a real picture", advice)
        for scolding in ("should have", "you failed", "error", "wrong", "warning"):
            self.assertNotIn(scolding, advice)

    def test_a_calibrated_group_is_offered_no_advice_at_all(self) -> None:
        """Nothing to fix, so nothing to say. Advice nobody needs is noise."""
        group = self._group(with_darks=True)
        self.assertTrue(group.has_calibration)
        self.assertIsNone(group.dark_recipe)
        self.assertEqual("", group.dark_advice)


if __name__ == "__main__":
    unittest.main()
