"""A ticked layer that is not in the comparison must say why it is not.

THE DEFECT: the panel worked out what to SHOW by listing the JPEGs on disk,
and what to CLAIM by listing the ticked boxes, and nothing compared the two.
So a layer could be named in "Applied: ..." and be absent from the Compare
dropdowns at the same time, with not a word about it. Every reading of that
is worse than the truth -- the frames could not be solved, or the layer has
no step of its own by design.

These tests are on the panel's own state rather than on pixels: what matters
is that the sentence exists, names the layer, and gives a reason.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dwarf2siril.postprocess import PostOptions

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - PySide6 is a hard requirement
    QApplication = None


class ExpectedPreviewTests(unittest.TestCase):
    """The mapping itself, with no Qt involved."""

    def test_a_solvable_run_expects_a_picture_from_every_pixel_layer(self) -> None:
        post = PostOptions(
            background_removal=True,
            plate_solve=True,
            colour_calibration=True,
            denoise=True,
            star_reduction=True,
        )
        expected = post.expected_previews(solvable=True)
        self.assertEqual(
            ["01_background", "02_solved", "03_colour", "04_denoised", "05_stars_reduced"],
            [key for key, _label, _reason in expected],
        )
        for key, label, reason in expected:
            with self.subTest(layer=label):
                self.assertEqual("", reason, f"{label} should expect a preview")

    def test_an_unsolvable_run_explains_the_two_that_cannot_run(self) -> None:
        """Not a failure. The wide camera writes no pointing to solve from."""
        post = PostOptions(
            plate_solve=True, colour_calibration=True, denoise=True
        )
        reasons = {
            label: reason
            for _key, label, reason in post.expected_previews(solvable=False)
        }
        self.assertIn("no pointing", reasons["Plate solve"])
        self.assertIn("solved first", reasons["Photometric colour calibration"])
        self.assertEqual("", reasons["Denoise"], "denoise does not need a solve")

    def test_stretch_is_always_explained_because_it_never_gets_a_stage(self) -> None:
        """It runs last, so what it produced IS the final image.

        The one layer that is guaranteed to be ticked and missing on every
        single run, which makes it the likeliest to be read as broken.
        """
        expected = PostOptions(stretch=True).expected_previews()
        self.assertEqual(1, len(expected))
        key, label, reason = expected[0]
        self.assertEqual("", key, "stretch has no stage of its own")
        self.assertIn("Stretch", label)
        self.assertIn("Final image", reason)

    def test_nothing_ticked_expects_nothing(self) -> None:
        self.assertEqual([], PostOptions().expected_previews())


@unittest.skipIf(QApplication is None, "PySide6 not available")
class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.output = Path(self._temp.name)
        (self.output / "previews").mkdir()
        (self.output / "stack.fit").write_bytes(b"stands in for the real one")

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _preview(self, key: str) -> None:
        """A real, readable JPEG, so the panel is exercised and not stubbed."""
        from PySide6.QtGui import QImage

        image = QImage(64, 48, QImage.Format.Format_RGB888)
        # Not all one colour: two previews that are identical trigger the
        # panel's "these are the same picture" note, which is a different
        # feature and would muddy what these tests are measuring.
        image.fill(0x203040 + len(key) * 0x050505)
        self.assertTrue(image.save(str(self.output / "previews" / f"{key}.jpg")))

    def _panel(self, post: PostOptions, solvable: bool = True):
        from dwarf2siril.gui.preview import PreviewPanel

        panel = PreviewPanel()
        shown = panel.load_from(self.output, "stack", post, solvable)
        self.assertTrue(shown, "the panel refused to load at all")
        return panel

    def test_a_ticked_layer_with_no_preview_is_named_and_explained(self) -> None:
        """The defect itself, pinned.

        Denoise ticked, denoise absent from the previews folder. Before this,
        the panel listed denoise as applied and simply did not offer it.
        """
        self._preview("00_stacked")
        self._preview("01_background")
        self._preview("99_final")

        panel = self._panel(PostOptions(background_removal=True, denoise=True))
        try:
            self.assertTrue(
                panel.missing.isVisible() or not panel.missing.isHidden(),
                "a ticked layer went missing without a word",
            )
            text = panel.missing.text()
            self.assertIn("Denoise", text)
            self.assertNotIn(
                "Remove background gradient",
                text,
                "a layer that IS in the list was reported missing",
            )
        finally:
            panel.deleteLater()

    def test_nothing_is_said_when_every_ticked_layer_is_there(self) -> None:
        """The line must not become wallpaper. Silence is right here."""
        for key in ("00_stacked", "01_background", "04_denoised", "99_final"):
            self._preview(key)

        panel = self._panel(PostOptions(background_removal=True, denoise=True))
        try:
            self.assertTrue(panel.missing.isHidden())
            self.assertEqual("", panel.missing.text())
        finally:
            panel.deleteLater()

    def test_an_unsolvable_run_says_why_rather_than_looking_broken(self) -> None:
        self._preview("00_stacked")
        self._preview("99_final")

        panel = self._panel(
            PostOptions(plate_solve=True, colour_calibration=True), solvable=False
        )
        try:
            text = panel.missing.text()
            self.assertIn("Plate solve", text)
            self.assertIn("Photometric colour calibration", text)
            self.assertIn("no pointing", text)
        finally:
            panel.deleteLater()

    def test_a_layer_missing_for_no_known_reason_still_gets_a_sentence(self) -> None:
        """"We do not know why" is information; an empty panel is not."""
        self._preview("00_stacked")
        self._preview("99_final")

        panel = self._panel(PostOptions(star_reduction=True))
        try:
            text = panel.missing.text()
            self.assertIn("Reduce stars", text)
            self.assertIn("no preview", text)
        finally:
            panel.deleteLater()

    def test_the_applied_line_comes_from_the_same_options(self) -> None:
        """One source of truth, which is the whole point of the change.

        The claim and the list used to be computed independently, which is
        what let them disagree.
        """
        self._preview("00_stacked")
        self._preview("04_denoised")
        self._preview("99_final")

        post = PostOptions(denoise=True, stretch=True)
        panel = self._panel(post)
        try:
            for label in post.enabled_labels():
                self.assertIn(label, panel.applied.text())
            # Stretch is applied AND has no stage, so it must appear in both.
            self.assertIn("Stretch", panel.missing.text())
        finally:
            panel.deleteLater()


if __name__ == "__main__":
    unittest.main()
