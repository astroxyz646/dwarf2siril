"""Every palette has to be readable, not just look plausible in a screenshot.

This exists because "it looks fine" is how a light theme ships with near-black
button text on a near-black fill. The numbers below are measured, so a palette
added or tweaked later cannot quietly fall under them.

Two measures, and they answer different questions:

* CONTRAST RATIO (WCAG 2.1) -- can you read it. Used for every text-on-ground
  and text-on-fill pairing.
* CIE76 DELTA-E -- can you tell two colours APART when they are never seen
  side by side, which is what a status pill actually is. Contrast against a
  shared background says nothing about this: two colours can both sit at 8:1
  on the same card and still be the same colour as each other.

Delta-E rather than a plain RGB distance, and the difference matters here.
On a LIGHT palette every status has to be dark to be readable, which packs
them all into one small corner of the RGB cube -- so raw RGB distance scores
a light palette worse than a dark one for colours that are, to the eye,
equally far apart. Lab is roughly perceptually uniform and does not have that
bias.

The floor is set from Deep Space, which shipped and was accepted: its own
tightest pair (RUNNING against ACCENT, teal against blue) is the worst
separation the app has ever asked anyone to make, so no new palette may be
tighter than that.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dwarf2siril.gui import theme
except ImportError:  # pragma: no cover - PySide6 is a hard requirement
    theme = None


def _rgb(colour: str) -> tuple[int, int, int]:
    value = colour.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def _relative_luminance(colour: str) -> float:
    def channel(raw: int) -> float:
        v = raw / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    red, green, blue = _rgb(colour)
    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def contrast(a: str, b: str) -> float:
    """WCAG 2.1 contrast ratio between two opaque colours, 1.0 to 21.0."""
    first, second = _relative_luminance(a), _relative_luminance(b)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _lab(colour: str) -> tuple[float, float, float]:
    """sRGB to CIE L*a*b*, through XYZ, under the D65 white point."""

    def linear(raw: int) -> float:
        v = raw / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in _rgb(colour))
    x = (0.4124 * red + 0.3576 * green + 0.1805 * blue) / 0.95047
    y = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    z = (0.0193 * red + 0.1192 * green + 0.9505 * blue) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t) + (16 / 116)

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy) - 16, 500 * (fx - fy), 200 * (fy - fz)


def separation(a: str, b: str) -> float:
    """How far apart two colours look, as a CIE76 delta-E."""
    first, second = _lab(a), _lab(b)
    return sum((first[i] - second[i]) ** 2 for i in range(3)) ** 0.5


STATUS_TOKENS = ("OK", "WARN", "ERROR", "RUNNING", "ACCENT")


@unittest.skipIf(theme is None, "PySide6 not available")
class PaletteTest(unittest.TestCase):
    def palettes(self):
        return theme.PALETTES.values()

    def test_body_text_is_comfortably_readable(self) -> None:
        """TEXT on every ground it is actually drawn on, at 7:1 or better.

        7 rather than 4.5: this is body copy at 9.5pt, on a window somebody
        reads at 2am, and every palette already clears it with room to spare.
        """
        for palette in self.palettes():
            for ground in ("BG", "SURFACE", "SURFACE_RAISED", "SURFACE_HOVER"):
                with self.subTest(palette=palette.name, ground=ground):
                    ratio = contrast(palette.TEXT, getattr(palette, ground))
                    self.assertGreaterEqual(ratio, 7.0, f"{ratio:.2f}:1")

    def test_secondary_text_clears_the_small_text_bar(self) -> None:
        """TEXT_MUTED carries whole sentences, so it gets the full 4.5."""
        for palette in self.palettes():
            for ground in ("BG", "SURFACE", "SURFACE_RAISED"):
                with self.subTest(palette=palette.name, ground=ground):
                    ratio = contrast(palette.TEXT_MUTED, getattr(palette, ground))
                    self.assertGreaterEqual(ratio, 4.5, f"{ratio:.2f}:1")

    def test_faint_text_is_faint_but_still_present(self) -> None:
        """TEXT_FAINT is deliberately quiet, and still has to be legible.

        2.8 is Deep Space's own floor on its lightest surface. It is below
        the WCAG bar on purpose -- this is the token for asides nobody has to
        read -- so the test's job is only to stop a new palette going further
        than the one that shipped.
        """
        for palette in self.palettes():
            for ground in ("BG", "SURFACE", "SURFACE_RAISED"):
                with self.subTest(palette=palette.name, ground=ground):
                    ratio = contrast(palette.TEXT_FAINT, getattr(palette, ground))
                    self.assertGreaterEqual(ratio, 2.8, f"{ratio:.2f}:1")

    def test_text_on_filled_buttons(self) -> None:
        """The trap: ACCENT_FG and DANGER_FG sit ON their button, not near it.

        A near-black foreground is right on a light accent and catastrophic
        on a dark one, which is exactly the mistake a light palette invites.
        Hover is held to the same bar as rest -- a pointer can sit on a
        button indefinitely.
        """
        for palette in self.palettes():
            pairs = (
                ("ACCENT_FG", "ACCENT"),
                ("ACCENT_FG", "ACCENT_HOVER"),
                ("DANGER_FG", "ERROR"),
                ("DANGER_FG", "ERROR_HOVER"),
            )
            for fg, bg in pairs:
                with self.subTest(palette=palette.name, pair=f"{fg} on {bg}"):
                    ratio = contrast(getattr(palette, fg), getattr(palette, bg))
                    self.assertGreaterEqual(ratio, 4.5, f"{ratio:.2f}:1")

    def test_text_on_a_button_being_pressed(self) -> None:
        """The pressed fill is darker, and gets a lower bar on purpose.

        4.2, not 4.5, and the number is not a convenience: a pressed fill is
        on screen only while a mouse button is held, by which point the label
        has already been read -- it is feedback that the click landed, not
        something anyone reads FROM. Deep Space, which shipped and was
        accepted, sits at 4.26 here; this says no palette may be worse than
        the one already in front of users.
        """
        for palette in self.palettes():
            pairs = (
                ("ACCENT_FG", "ACCENT_PRESSED"),
                ("DANGER_FG", "ERROR_PRESSED"),
            )
            for fg, bg in pairs:
                with self.subTest(palette=palette.name, pair=f"{fg} on {bg}"):
                    ratio = contrast(getattr(palette, fg), getattr(palette, bg))
                    self.assertGreaterEqual(ratio, 4.2, f"{ratio:.2f}:1")

    def test_the_focus_ring_is_visible_on_every_surface(self) -> None:
        """Where the keyboard is has to be findable on all five palettes.

        The ring is a 1px border and never text, so the bar is WCAG's 3:1 for
        a non-text indicator rather than 4.5. It arrived as a single
        hard-coded light blue, which is fine on the four dark palettes and
        invisible on Daylight, so every palette states its own -- and this
        checks each against the surfaces its controls actually sit on,
        including the hover state, where the gap is always narrowest.
        """
        for palette in self.palettes():
            for ground in ("BG", "SURFACE", "SURFACE_RAISED", "SURFACE_HOVER"):
                with self.subTest(palette=palette.name, ground=ground):
                    ratio = contrast(palette.FOCUS, getattr(palette, ground))
                    self.assertGreaterEqual(ratio, 3.0, f"{ratio:.2f}:1")

    def test_the_focus_ring_is_not_mistakable_for_the_accent(self) -> None:
        """Focus says where the keyboard is; the accent says what is chosen.

        Both are on screen at once, on controls that sit next to each other,
        so a focused button and a selected one must not look like the same
        state. The floor is Deep Space's own gap, which shipped: this asserts
        no palette is tighter than the one users already have.
        """
        floor = contrast(theme.DEEP_SPACE.FOCUS, theme.DEEP_SPACE.ACCENT)
        for palette in self.palettes():
            with self.subTest(palette=palette.name):
                gap = contrast(palette.FOCUS, palette.ACCENT)
                self.assertGreaterEqual(gap, floor * 0.95, f"{gap:.2f}:1")

    def test_status_colours_are_readable_as_text(self) -> None:
        """Every status is written as words somewhere, not only as a swatch."""
        for palette in self.palettes():
            for token in STATUS_TOKENS:
                for ground in ("BG", "SURFACE", "SURFACE_RAISED"):
                    with self.subTest(palette=palette.name, token=token, ground=ground):
                        ratio = contrast(
                            getattr(palette, token), getattr(palette, ground)
                        )
                        self.assertGreaterEqual(ratio, 4.5, f"{ratio:.2f}:1")

    def test_status_colours_are_readable_inside_their_own_pill(self) -> None:
        """A pill draws the status on a 15% wash of itself. See theme.pill."""
        for palette in self.palettes():
            for token in STATUS_TOKENS:
                colour = getattr(palette, token)
                ground = _blend(colour, palette.SURFACE, 0x26)
                with self.subTest(palette=palette.name, token=token):
                    ratio = contrast(colour, ground)
                    self.assertGreaterEqual(ratio, 3.5, f"{ratio:.2f}:1")

    def test_statuses_stay_tellable_apart_from_each_other(self) -> None:
        """And from the accent, which is the pair that keeps going wrong.

        35 delta-E is comfortably past "obviously a different colour", and
        it is set from what shipped rather than from a standard: Deep Space's
        own tightest pair is OK against RUNNING -- green against teal -- at
        40, so this says a new palette may be a little tighter than the one
        users already have but not a lot.

        Red Night is exempt and tested separately. It cannot meet this by
        construction, and that is the point of it: see the test below.
        """
        for palette in self.palettes():
            if palette is theme.RED_NIGHT:
                continue
            for index, a in enumerate(STATUS_TOKENS):
                for b in STATUS_TOKENS[index + 1 :]:
                    with self.subTest(palette=palette.name, pair=f"{a}/{b}"):
                        gap = separation(getattr(palette, a), getattr(palette, b))
                        self.assertGreaterEqual(gap, 35.0, f"{gap:.1f}")

    def test_red_night_separates_its_statuses_by_lightness_instead(self) -> None:
        """The whole point of Red Night, and the one thing that makes it work.

        It has about forty degrees of hue to play with, so it CANNOT put its
        statuses as far apart as a full-gamut palette can, and pretending
        otherwise would mean putting blue back into a palette that exists to
        keep blue out. What it does instead is spread them in LIGHTNESS: OK
        is the dimmest and least saturated, RUNNING is the brightest thing on
        screen, and the rest sit between them.

        So this checks the property the palette was actually designed around
        -- that no two of them are close in L* AND close in colour -- rather
        than a number it was never going to reach.
        """
        palette = theme.RED_NIGHT
        for index, a in enumerate(STATUS_TOKENS):
            for b in STATUS_TOKENS[index + 1 :]:
                first, second = getattr(palette, a), getattr(palette, b)
                gap = separation(first, second)
                lightness = abs(_lab(first)[0] - _lab(second)[0])
                with self.subTest(pair=f"{a}/{b}"):
                    # 20 delta-E is still several times the threshold at
                    # which two colours stop looking like the same one.
                    self.assertGreaterEqual(gap, 20.0, f"delta-E {gap:.1f}")
                    self.assertGreater(
                        max(gap / 35.0, lightness / 12.0),
                        1.0,
                        f"delta-E {gap:.1f}, L* apart {lightness:.1f} -- "
                        f"{a} and {b} are close in both",
                    )

    def test_red_night_keeps_the_blue_out(self) -> None:
        """It is a dark-adaptation palette, not a red-tinted one.

        Every colour it draws has to be warm: red at least as strong as
        blue, everywhere. One cool token would undo what the palette is for.
        """
        for field in theme._COLOUR_FIELDS:
            value = getattr(theme.RED_NIGHT, field)
            if not isinstance(value, str):
                continue
            red, _green, blue = _rgb(value)
            with self.subTest(token=field, colour=value):
                self.assertGreaterEqual(red, blue, f"{value} is cooler than it is warm")

    def test_the_photograph_mount_carries_its_own_text(self) -> None:
        """BG_SUNKEN does not follow the palette, so nor may the text on it."""
        for palette in self.palettes():
            with self.subTest(palette=palette.name):
                self.assertGreaterEqual(
                    contrast(palette.SUNKEN_TEXT, palette.BG_SUNKEN), 4.5
                )
                self.assertGreaterEqual(
                    contrast(palette.SUNKEN_TEXT_BRIGHT, palette.BG_SUNKEN), 7.0
                )

    def test_the_mount_stays_dark_on_every_palette(self) -> None:
        """Including Daylight. An astrophoto needs a dark surround, not a
        white one -- see the BG_SUNKEN comment in theme.py."""
        for palette in self.palettes():
            with self.subTest(palette=palette.name):
                self.assertLess(_relative_luminance(palette.BG_SUNKEN), 0.05)

    def test_surfaces_step_in_one_direction(self) -> None:
        """Further forward is further from the ground, whichever way that is.

        On a dark palette a card is lighter than the window; on a light one
        it is whiter. What must never happen is a step that goes backwards,
        which is how elevation stops reading as elevation.
        """
        for palette in self.palettes():
            order = ["BG", "SURFACE", "SURFACE_RAISED"]
            levels = [_relative_luminance(getattr(palette, name)) for name in order]
            with self.subTest(palette=palette.name):
                self.assertEqual(
                    levels, sorted(levels), f"{dict(zip(order, levels))}"
                )

    def test_borders_are_visible_against_the_surfaces_they_divide(self) -> None:
        for palette in self.palettes():
            with self.subTest(palette=palette.name):
                self.assertGreater(
                    contrast(palette.BORDER_STRONG, palette.SURFACE),
                    contrast(palette.BORDER, palette.SURFACE),
                )
                self.assertGreater(
                    contrast(palette.BORDER_BRIGHT, palette.SURFACE),
                    contrast(palette.BORDER_STRONG, palette.SURFACE),
                )


def _blend(fg: str, bg: str, alpha: int) -> str:
    """``fg`` at ``alpha``/255 over ``bg``, as an opaque colour."""
    weight = alpha / 255
    front, back = _rgb(fg), _rgb(bg)
    return "#%02X%02X%02X" % tuple(
        round(front[i] * weight + back[i] * (1 - weight)) for i in range(3)
    )


@unittest.skipIf(theme is None, "PySide6 not available")
class EngineTest(unittest.TestCase):
    def tearDown(self) -> None:
        theme.set_palette(theme.DEFAULT_PALETTE)

    def test_the_module_tokens_follow_the_active_palette(self) -> None:
        """theme.BG is read at ninety-odd sites and must never go stale."""
        theme.set_palette("Daylight")
        self.assertEqual(theme.BG, theme.DAYLIGHT.BG)
        self.assertEqual(theme.ACCENT_FG, theme.DAYLIGHT.ACCENT_FG)
        self.assertFalse(theme.IS_DARK)
        theme.set_palette("Deep Space")
        self.assertEqual(theme.BG, theme.DEEP_SPACE.BG)
        self.assertTrue(theme.IS_DARK)

    def test_an_unknown_name_falls_back_rather_than_failing(self) -> None:
        """A settings file from a newer build must still open the app."""
        for name in ("Chartreuse", "", None):
            with self.subTest(name=name):
                self.assertIs(theme.resolve(name), theme.DEEP_SPACE)

    def test_the_stylesheet_is_built_from_the_active_palette(self) -> None:
        theme.set_palette("Mars")
        sheet = theme.stylesheet()
        self.assertIn(theme.MARS.ACCENT, sheet)
        self.assertNotIn(theme.DEEP_SPACE.ACCENT, sheet)

    def test_every_palette_produces_a_sheet(self) -> None:
        """A missing token would be a NameError in an f-string, at runtime,
        on whichever palette somebody happened to pick."""
        for name in theme.names():
            with self.subTest(palette=name):
                theme.set_palette(name)
                self.assertGreater(len(theme.stylesheet()), 1000)

    def test_tint_puts_the_alpha_where_qt_looks_for_it(self) -> None:
        """Qt reads #AARRGGBB. Getting this backwards gives an olive."""
        self.assertEqual(theme.tint("#E5675E", 0x22), "#22E5675E")

    def test_the_default_is_the_colours_the_app_already_shipped(self) -> None:
        self.assertEqual(theme.DEFAULT_PALETTE, "Deep Space")
        self.assertEqual(theme.DEEP_SPACE.BG, "#0A0C10")
        self.assertEqual(theme.DEEP_SPACE.ACCENT, "#4C8FD9")
        self.assertEqual(theme.DEEP_SPACE.RUNNING, "#38BEC9")


if __name__ == "__main__":
    unittest.main()
