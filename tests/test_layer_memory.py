"""The extras must survive a restart of the app.

Every optional layer is off by default, and until now it went back to off on
EVERY launch. That is a trap rather than a safe default: tick five layers,
restart the app for some unrelated reason, press Stack, and you get a plain
stack with no hint that anything was dropped -- because from the app's point
of view nothing was. It happened three times in one morning and each time it
looked like the layers were broken.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - PySide6 is a hard requirement
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 not available")
class LayerMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["DWARF2SIRIL_NO_DRIVE_SCAN"] = "1"
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        # A settings file of our own, so the developer's real preferences are
        # neither read nor written by the tests.
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

        from dwarf2siril import postprocess

        self._real = postprocess.settings_path
        path = Path(self._tmp.name) / "settings.json"
        postprocess.settings_path = lambda: path
        self.addCleanup(lambda: setattr(postprocess, "settings_path", self._real))

    def _card(self):
        from dwarf2siril.gui.layers import LayersCard

        return LayersCard()

    def test_ticks_come_back_on_the_next_launch(self) -> None:
        first = self._card()
        first.background.checkbox.setChecked(True)
        first.denoise.checkbox.setChecked(True)
        first.stretch.checkbox.setChecked(True)

        second = self._card()
        self.assertTrue(second.background.checked)
        self.assertTrue(second.denoise.checked)
        self.assertTrue(second.stretch.checked)
        self.assertFalse(second.colour.checked, "untouched layers stay off")

    def test_what_comes_back_is_what_the_build_will_use(self) -> None:
        """Restoring the boxes is worthless if options() disagrees with them."""
        first = self._card()
        first.background.checkbox.setChecked(True)
        first.colour.checkbox.setChecked(True)   # drags plate solve in with it
        first.amount.setValue(30)

        options = self._card().options()
        self.assertTrue(options.background_removal)
        self.assertTrue(options.colour_calibration)
        self.assertTrue(options.plate_solve)
        self.assertAlmostEqual(0.30, options.star_amount, places=2)

    def test_unticking_is_remembered_too(self) -> None:
        """Otherwise the memory only ever accumulates and can never be undone."""
        first = self._card()
        first.denoise.checkbox.setChecked(True)
        self.assertTrue(self._card().denoise.checked)

        third = self._card()
        third.denoise.checkbox.setChecked(False)
        self.assertFalse(self._card().denoise.checked)

    def test_a_first_ever_launch_still_starts_with_everything_off(self) -> None:
        """No saved settings must mean the documented default, not a crash."""
        card = self._card()
        self.assertFalse(card.options().any_enabled)

    def test_the_frame_filter_is_remembered(self) -> None:
        first = self._card()
        first.frame_filter.setCurrentText("Off")
        self.assertFalse(self._card().quality().enabled)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
