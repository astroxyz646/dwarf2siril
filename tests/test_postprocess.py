"""Tests for the optional layers and the script they generate.

The things worth pinning down: nothing happens unless asked, the step order
is the one Siril actually wants, and a missing tool downgrades the run
instead of breaking it.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dwarf2siril.postprocess import PostOptions, find_starnet
from dwarf2siril.script import generate_script

from test_core import make_darks, make_session


def _group(root: Path):
    from dwarf2siril.grouping import build_group
    from dwarf2siril.scanner import scan

    result = scan(root)
    return build_group(result.eq_sessions, result.darks)


class DefaultsTests(unittest.TestCase):
    def test_everything_is_off_by_default(self) -> None:
        options = PostOptions()
        self.assertFalse(options.any_enabled)
        self.assertFalse(options.background_removal)
        self.assertFalse(options.denoise)
        self.assertFalse(options.plate_solve)
        self.assertFalse(options.colour_calibration)
        self.assertFalse(options.star_reduction)

    def test_colour_calibration_pulls_in_plate_solving(self) -> None:
        # pcc cannot run on an unsolved image, so asking for one asks for both.
        options = PostOptions(colour_calibration=True)
        notes = options.resolve()
        self.assertTrue(options.plate_solve)
        self.assertTrue(any("plate solv" in note.lower() for note in notes))

    def test_missing_starnet_downgrades_rather_than_failing(self) -> None:
        options = PostOptions(
            star_reduction=True, starnet_path=Path("/nowhere/starnet2.exe")
        )
        status = find_starnet(Path("/nowhere/starnet2.exe"))
        if status.available:
            self.skipTest("StarNet is installed on this machine")
        notes = options.resolve()
        self.assertFalse(options.star_reduction)
        self.assertTrue(any("StarNet" in note for note in notes))


class ScriptLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Astronomy"
        self.root.mkdir(parents=True)
        make_session(self.root, "DWARF_RAW_TELE_C 5_EXP_60_GAIN_50_A", "C 5", 60, 50, 3)
        make_darks(self.root, 60, 50, 5)
        self.group = _group(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _script(self, post: PostOptions) -> str:
        return generate_script(self.group, Path("/out"), "STACK", post)

    def _commands(self, script: str) -> list[str]:
        return [
            line.strip()
            for line in script.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def test_no_layers_means_no_extra_commands(self) -> None:
        script = self._script(PostOptions(previews=False))
        for command in ("subsky", "denoise", "platesolve", "pcc", "starnet"):
            self.assertNotIn(f"\n{command}", script)

    def test_the_plain_stack_is_never_overwritten(self) -> None:
        script = self._script(PostOptions(background_removal=True, previews=False))
        # Everything after stacking saves to the _processed name.
        self.assertIn("save STACK_processed", script)
        self.assertNotIn("\nsave STACK\n", script)

    def test_background_removal_emits_subsky(self) -> None:
        script = self._script(PostOptions(background_removal=True, previews=False))
        self.assertIn("subsky -rbf", script)

    def test_denoise_skips_cosmetic_correction(self) -> None:
        # Cosmetic correction belongs on CFA frames at calibration time; on a
        # finished RGB stack it errors out.
        script = self._script(PostOptions(denoise=True, previews=False))
        self.assertIn("denoise -nocosmetic", script)

    def test_plate_solve_is_seeded_with_the_dwarfs_known_optics(self) -> None:
        script = self._script(PostOptions(plate_solve=True, previews=False))
        self.assertIn("platesolve -focal=150 -pixelsize=2 -noflip", script)

    def test_plate_solve_never_turns_the_image_upside_down(self) -> None:
        """Siril flips a "wrong way up" image by default. We do not want that.

        The solution is correct either way, but flipping leaves the finished
        picture mirrored relative to the plain stack kept beside it, which
        breaks the before/after view and surprises the user for no gain.
        Measured: with -noflip the pixels come out bit-identical.
        """
        script = self._script(PostOptions(plate_solve=True, previews=False))
        for line in script.splitlines():
            if line.strip().startswith("platesolve"):
                self.assertIn("-noflip", line)

    def test_plate_solve_also_solves_the_plain_stack(self) -> None:
        """The kept file is the one many people open, so it gets coordinates too."""
        script = self._script(PostOptions(plate_solve=True, previews=False))
        solves = [
            line for line in script.splitlines()
            if line.strip().startswith("platesolve")
        ]
        self.assertEqual(2, len(solves), "expected the processed file AND the plain stack")

    def test_star_reduction_alone_still_produces_an_output(self) -> None:
        """StarNet names its outputs after the LOADED image.

        With star reduction as the only layer nothing had saved and reloaded
        the working file, so starnet wrote starless_<name> while the pixel
        math asked for starless_<name>_processed. Siril failed the whole
        script and produced no output at all.
        """
        script = self._script(PostOptions(star_reduction=True, previews=False))
        commands = self._commands(script)
        working = f"{self.NAME}_processed" if hasattr(self, "NAME") else None
        starnet = next(i for i, c in enumerate(commands) if c.startswith("starnet"))
        loads_before = [
            c for c in commands[:starnet] if c.startswith("load ")
        ]
        self.assertTrue(
            loads_before and loads_before[-1].endswith("_processed"),
            f"starnet must run on the working file, not {loads_before}",
        )

    def test_the_solve_is_seeded_from_the_frames_not_from_a_constant(self) -> None:
        """The DWARF 3 has two cameras and they are nothing alike.

        This was hard-coded to the telephoto's 150mm / 2.0um. On a wide-angle
        session, which is 6.7mm at 2.9um, the solver hunted for a field
        twenty-two times too small, failed, and took every layer after it
        down with it -- which is the whole of the operator's "extras didn't
        work" report.
        """
        wide = Path(self._tmp.name) / "Wide"
        wide.mkdir()
        make_session(
            wide, "DWARF_RAW_WIDE_EXP_10_GAIN_0_B", "", 10, 0, 2,
            camera="WIDE", focal=6.7, pixel_size=2.9, ra=12.3, dec=45.6,
        )
        from dwarf2siril.grouping import build_group
        from dwarf2siril.scanner import scan

        group = build_group(scan(wide).eq_sessions, [])
        script = generate_script(group, Path("/out"), "WIDE", PostOptions(
            plate_solve=True, previews=False))
        self.assertIn("platesolve -focal=6.7 -pixelsize=2.9 -noflip", script)

    def test_a_session_with_no_pointing_skips_the_solve_instead_of_failing(self) -> None:
        """The wide camera writes RA/DEC of 0/0 -- an absence, not a position.

        Siril's near solver searches around a starting point. Given none, it
        fails, and because Siril aborts a script on the first failure it took
        background removal, denoise and star reduction with it. Skipping is
        the honest answer, and it leaves every other layer working.
        """
        blind = Path(self._tmp.name) / "Blind"
        blind.mkdir()
        make_session(
            blind, "DWARF_RAW_WIDE_EXP_10_GAIN_0_C", "", 10, 0, 2,
            camera="WIDE", focal=6.7, pixel_size=2.9, ra=None, dec=None,
        )
        from dwarf2siril.grouping import build_group
        from dwarf2siril.scanner import scan

        group = build_group(scan(blind).eq_sessions, [])
        self.assertFalse(group.can_plate_solve)

        options = PostOptions(
            plate_solve=True, colour_calibration=True,
            background_removal=True, denoise=True, previews=False,
        )
        script = generate_script(group, Path("/out"), "BLIND", options)
        commands = self._commands(script)
        self.assertNotIn("platesolve", " ".join(commands))
        self.assertNotIn("pcc", commands)
        # And the layers that CAN work still do.
        self.assertIn("subsky -rbf -samples=20 -tolerance=1.0 -smooth=0.5", commands)
        self.assertIn("denoise -nocosmetic", commands)

    def test_solve_comes_before_colour_calibration(self) -> None:
        options = PostOptions(colour_calibration=True, previews=False)
        options.resolve()
        commands = self._commands(self._script(options))
        self.assertLess(
            commands.index("platesolve -focal=150 -pixelsize=2 -noflip"),
            commands.index("pcc"),
        )

    def test_background_removal_comes_before_colour_calibration(self) -> None:
        # Siril itself warns to correct the gradient before running pcc.
        options = PostOptions(
            background_removal=True, colour_calibration=True, previews=False
        )
        options.resolve()
        commands = self._commands(self._script(options))
        self.assertLess(
            commands.index("subsky -rbf -samples=20 -tolerance=1.0 -smooth=0.5"),
            commands.index("pcc"),
        )

    def test_star_reduction_is_last_and_recombines_the_star_layer(self) -> None:
        options = PostOptions(
            background_removal=True,
            denoise=True,
            star_reduction=True,
            star_amount=0.4,
            starnet_path=Path("/fake/starnet2.exe"),
            previews=False,
        )
        # Bypass resolve() so the tool check does not drop the layer here.
        script = self._script(options)
        commands = self._commands(script)
        self.assertIn("starnet -stretch", commands)
        self.assertLess(
            commands.index("denoise -nocosmetic"), commands.index("starnet -stretch")
        )
        self.assertIn('pm "$starless_STACK_processed$ + 0.4*$starmask_STACK_processed$"', script)

    def test_previews_are_written_at_each_stage(self) -> None:
        script = self._script(
            PostOptions(background_removal=True, denoise=True, previews=True)
        )
        self.assertIn("savejpg previews/00_stacked", script)
        self.assertIn("savejpg previews/01_background", script)
        self.assertIn("savejpg previews/02_denoised", script)
        self.assertIn("savejpg previews/99_final", script)
        self.assertIn("resample -maxdim=1600", script)

    def test_previews_alone_do_not_alter_the_image(self) -> None:
        script = self._script(PostOptions(previews=True))
        for command in ("subsky", "denoise", "platesolve", "pcc", "starnet"):
            self.assertNotIn(f"\n{command}", script)
        self.assertIn("savejpg previews/00_stacked", script)


if __name__ == "__main__":
    unittest.main()
