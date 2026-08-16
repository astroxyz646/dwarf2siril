"""Nothing in the window may be clipped, at any width we support.

This test exists because the same class of defect shipped twice: a caption
wider than its thumbnail, and then a whole sidebar column wider than the
sidebar, which took a BUTTON off screen. Both were reported as done after
being looked at. Measuring by eye is not a check, so this is the check.

It runs the real MainWindow offscreen at every width that matters and fails
on anything cut off -- a widget past the window edge, a label too narrow for
its own sentence, or a scroll area whose contents cannot fit its viewport.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))

# NOT the offscreen platform, tempting as it is. Offscreen Qt ships no fonts,
# so every text measurement comes back from a fallback with wildly different
# metrics -- it reported a 36-character tick box as 492px wide when the real
# one is 240px. A width test on invented widths is worse than no test.
# Instead the windows are laid out for real and simply never mapped to the
# screen, which keeps true font metrics and still shows nothing.

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - PySide6 is a hard requirement
    QApplication = None


# The operator's own window, the default, and the smallest we allow.
WIDTHS = [(1636, 1171), (1280, 880), (1000, 680), (900, 640)]

BUILT = SimpleNamespace(
    script_path=Path("/tmp/example/stack.ssf"),
    output_dir=Path("/tmp/example"),
    lights_copied=350,
    darks_copied=30,
    linked=True,
    warnings=[],
)


@unittest.skipIf(QApplication is None, "PySide6 not available")
class LayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # MainWindow starts a real drive scan 150ms after it is built. On a
        # developer machine that walks the actual card reader, and an empty
        # or awkward drive raises a MODAL Windows dialog that blocks the
        # entire test run until somebody clicks it. Layout has nothing to do
        # with what is plugged in, so the scan is switched off.
        os.environ["DWARF2SIRIL_NO_DRIVE_SCAN"] = "1"

        from dwarf2siril.gui import theme

        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(theme.stylesheet())

        # An empty folder standing in for a chosen card. Real path, nothing
        # in it, so nothing is scanned and nothing can be deleted.
        cls._tmp = tempfile.TemporaryDirectory()
        cls._tmp_root = cls._tmp.name

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _window(self):
        """A window in its most demanding state: everything on screen at once."""
        from PySide6.QtCore import Qt

        from dwarf2siril.gui.app import MainWindow

        window = MainWindow()
        # Clean-up mode REFUSES to open with no card chosen, and it refuses by
        # popping a modal warning box. Nothing dismisses that box in a test
        # run, so the whole suite sat there forever waiting for a click that
        # was never coming. Pretending a card is chosen is also the only way
        # this test ever reaches the clean-up layout it claims to check.
        window.source_root = Path(self._tmp_root)
        # Laid out exactly as if shown, but never actually put on screen.
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.show()

        # Step 4 filled in, because an empty placeholder is narrower than the
        # real panel and would let a too-wide run panel through.
        window.run_placeholder.hide()
        window.run_panel.show_result(BUILT, "C_27")
        window.run_panel.show()

        # The edges question is the tallest and wordiest thing in the sidebar
        # and is hidden by default, so force it on rather than test the easy
        # case. Two sessions of one target is exactly when it appears.
        window.layers_card.framing_box.show()
        window.layers_card.framing_reason.setText(
            "Your frames do not all cover the same sky, because separate "
            "sessions never start pointing identically and the field rotates "
            "in alt-az."
        )
        # Star reduction's slider row only exists while it is ticked.
        window.layers_card.stars.checkbox.setChecked(True)
        self.app.processEvents()
        return window

    def _settle(self, window, width: int, height: int) -> None:
        """Resize and let the layout finish arguing with itself.

        A Qt layout settles over several passes of the event loop, and a
        column of wrapping labels takes more of them than most: each pass
        the labels report a truer height and the panels above them widen
        their minimums to match. A real user gets those passes for free
        between one frame and the next; a test has to ask.
        """
        window.resize(width, height)
        for _ in range(24):
            self.app.processEvents()

    def test_nothing_is_clipped_at_any_supported_size(self) -> None:
        """Horizontal AND vertical, in every mode.

        Step 4 differs between modes and only exists in one of them, so a
        check that only ever looks at Stack is checking a third of the app.
        """
        from dwarf2siril.gui.app import MODES

        from launcher import find_clipping

        window = self._window()
        try:
            for mode, label, _hint in MODES:
                window._set_mode(mode)
                for width, height in WIDTHS:
                    with self.subTest(mode=label, size=f"{width}x{height}"):
                        self._settle(window, width, height)
                        problems = find_clipping(window)
                        self.assertEqual(
                            [],
                            problems,
                            f"{label} mode at {width}x{height}:\n  "
                            + "\n  ".join(problems),
                        )
        finally:
            window.close()

    def test_the_sidebar_scrolls_rather_than_squashing(self) -> None:
        """The defect itself, pinned.

        Content taller than the viewport must SCROLL. When it did not, Qt
        squeezed every widget below its minimum and drew them on top of each
        other -- a slider painted across a label, buttons sliced in half.
        """
        window = self._window()
        try:
            self._settle(window, 1000, 680)
            window._choose_sidebar(True)   # unfold it at this narrow size
            self._settle(window, 1000, 680)

            scroll = window.sidebar_scroll
            content = scroll.widget().height()
            viewport = scroll.viewport().height()
            self.assertGreater(
                content,
                viewport,
                "the sidebar content was squeezed to fit instead of scrolling",
            )
            self.assertGreater(
                scroll.verticalScrollBar().maximum(),
                0,
                "content is taller than the viewport but there is no way to scroll",
            )
        finally:
            window.close()

    def test_the_copy_status_fits_the_footer_at_every_size(self) -> None:
        """The Prepare messages are the longest text the footer ever holds.

        "Ready." fits anywhere, so a footer measured only in its resting state
        is not measured at all. These are the real sentences, from the code
        that builds them, at the real font -- a status line that reports the
        copy honestly and then gets cut off in the middle of doing so has
        reported nothing.
        """
        from dwarf2siril.builder import copy_headline, copy_progress

        from launcher import find_clipping

        # A real session on the operator's card: 350 lights and 30 darks,
        # about 7 GB, which is where the digits are widest.
        messages = [
            copy_headline(380, 7_000_000_000),
            copy_progress(213, 380, 4_200_000_000, 7_000_000_000),
        ]

        window = self._window()
        try:
            for message in messages:
                window.progress.show()
                window.cancel_button.show()
                window.status.setText(message)
                for width, height in WIDTHS:
                    with self.subTest(size=f"{width}x{height}", text=message[:24]):
                        self._settle(window, width, height)
                        problems = find_clipping(window)
                        self.assertEqual(
                            [],
                            problems,
                            f"at {width}x{height} while copying:\n  "
                            + "\n  ".join(problems),
                        )
        finally:
            window.close()

    def test_the_grid_never_collapses_to_one_column(self) -> None:
        """The sidebar folds before the card grid gives up its second column.

        A single column of cards is the layout the reflowing grid replaced,
        so it is a regression rather than a graceful degradation.
        """
        from dwarf2siril.gui.app import (
            CARD_WIDTH,
            GRID_MARGINS,
            RAIL_WIDTH,
            SCROLLBAR_ROOM,
            SIDEBAR_WIDTH,
        )

        window = self._window()
        try:
            for width, height in WIDTHS:
                window.resize(width, height)
                self.app.processEvents()
                taken = SIDEBAR_WIDTH if window.sidebar.isVisible() else RAIL_WIDTH
                room = width - taken - GRID_MARGINS - SCROLLBAR_ROOM
                with self.subTest(size=f"{width}x{height}"):
                    self.assertGreaterEqual(
                        room,
                        CARD_WIDTH * 2 + 12,
                        f"only room for one card column at {width}px",
                    )
        finally:
            window.close()

    def test_the_drive_tile_has_room_inside_its_border(self) -> None:
        """Padding INSIDE a bordered box, which nothing else here measures.

        The clipping check asks whether a widget fits. This tile always did:
        its three lines fitted its 66px perfectly, with two pixels above the
        title and two below the amber line, and touching the border is not
        clipping. It looked cramped and no check could say so.

        Not reachable through MainWindow, because the drive scan is off in
        these tests and a tile only exists once a card is found -- so the
        tile is built directly, the way the app builds it.
        """
        from PySide6.QtWidgets import QHBoxLayout, QWidget

        from dwarf2siril.gui.cards import DriveTile

        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        tile = DriveTile("U盘 (D:\\)", "D:\\Astronomy", "DWARF 3 data found here")
        row.addWidget(tile)
        row.addStretch(1)
        host.resize(700, 200)
        host.show()
        for _ in range(8):
            self.app.processEvents()

        try:
            children = [c for c in tile.findChildren(QWidget) if c.isVisible()]
            self.assertTrue(children, "the tile drew nothing at all")

            box = tile.rect()
            insets = {
                "left": min(c.geometry().left() for c in children),
                "top": min(c.geometry().top() for c in children),
                "right": box.right() - max(c.geometry().right() for c in children),
                "bottom": box.bottom() - max(c.geometry().bottom() for c in children),
            }
            for edge, gap in insets.items():
                with self.subTest(edge=edge):
                    self.assertGreaterEqual(
                        gap,
                        10,
                        f"only {gap}px between the tile's contents and its "
                        f"{edge} border: {insets}",
                    )
        finally:
            host.close()

if __name__ == "__main__":
    unittest.main()
