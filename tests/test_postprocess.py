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
        self.assertIn("platesolve -focal=150 -pixelsize=2", script)

    def test_plate_solve_is_allowed_to_turn_the_image_the_right_way_up(self) -> None:
        """Siril flips a "wrong way up" image, and that is what we want.

        North up is the orientation every star chart and every other image of
        the same object uses. This used to pass -noflip purely to keep the
        before/after pair lined up; that is now handled by solving the plain
        stack BEFORE its snapshot is taken, so both sides end up the same way
        up without leaving the finished picture upside down.
        """
        script = self._script(PostOptions(plate_solve=True, previews=False))
        solves = [
            line for line in script.splitlines()
            if line.strip().startswith("platesolve")
        ]
        self.assertTrue(solves)
        for line in solves:
            self.assertNotIn("-noflip", line)

    def test_the_plain_stack_is_solved_before_its_preview_is_taken(self) -> None:
        """Both sides of the before/after pair must end up the same way up.

        The solve can flip. Snapshotting the plain stack first and solving it
        afterwards would leave the kept .fit flipped relative to the JPEG the
        panel shows beside the final image, which is exactly the confusion
        -noflip used to avoid.
        """
        script = self._script(PostOptions(plate_solve=True, previews=True))
        lines = [line.strip() for line in script.splitlines()]
        solve = max(i for i, l in enumerate(lines) if l.startswith("platesolve"))
        snapshot = next(
            i for i, l in enumerate(lines) if l.startswith("savejpg previews/00_stacked")
        )
        self.assertLess(solve, snapshot)

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
        self.assertIn("platesolve -focal=6.7 -pixelsize=2.9", script)

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
            commands.index("platesolve -focal=150 -pixelsize=2"),
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

    def test_a_stages_preview_number_does_not_depend_on_the_other_stages(self) -> None:
        """The bug that made the whole thing look like it had done nothing.

        The numbers used to be handed out by a counter as the script was
        written, so with background removal switched OFF colour calibration
        took number 01 and was saved as 01_colour.jpg. The panel only knows
        03_colour, so it dropped that preview -- and every one after it --
        and showed the plain stack beside the final image with nothing in
        between. Two similar-looking pictures and no explanation.
        """
        from dwarf2siril.gui.preview import STAGE_LABELS

        known = {key for key, _caption in STAGE_LABELS}
        combinations = [
            PostOptions(background_removal=True, colour_calibration=True,
                        denoise=True, star_reduction=False, previews=True),
            PostOptions(colour_calibration=True, denoise=True, previews=True),
            PostOptions(denoise=True, previews=True),
            PostOptions(plate_solve=True, previews=True),
            PostOptions(background_removal=True, previews=True),
        ]
        for options in combinations:
            options.resolve()
            written = [
                line.strip().split()[1].split("/")[-1]
                for line in self._script(options).splitlines()
                if line.strip().startswith("savejpg ")
            ]
            self.assertTrue(written)
            for key in written:
                self.assertIn(
                    key, known,
                    f"{key} is a preview the panel cannot show, from {options}",
                )

    def test_the_solve_gets_its_own_preview_now_that_it_can_flip(self) -> None:
        """A step that turns the picture over must appear in the comparison."""
        script = self._script(PostOptions(plate_solve=True, previews=True))
        self.assertIn("savejpg previews/02_solved 90", script)

    def test_stretch_runs_after_every_other_layer(self) -> None:
        """subsky, pcc and starnet all expect LINEAR data.

        Stretching before any of them hands them the wrong kind of numbers,
        so the stretch has to be the last thing that touches the pixels.
        """
        options = PostOptions(
            background_removal=True, colour_calibration=True, denoise=True,
            stretch=True, previews=False,
        )
        options.resolve()
        commands = self._commands(self._script(options))
        stretch = commands.index("autostretch -linked")
        for earlier in ("subsky", "platesolve", "pcc", "denoise"):
            position = next(
                i for i, c in enumerate(commands) if c.startswith(earlier)
            )
            self.assertLess(position, stretch, f"{earlier} must precede the stretch")

    def test_stretch_is_linked_so_it_keeps_the_calibrated_colour(self) -> None:
        """Unlinked re-balances the channels and throws pcc's answer away."""
        script = self._script(PostOptions(stretch=True, previews=False))
        self.assertIn("autostretch -linked", script)

    def test_the_final_preview_is_not_stretched_twice(self) -> None:
        """The preview autostretches linear data. Stretched data is already done.

        Autostretching an already-stretched image blows the highlights out and
        makes the finished picture look WORSE than the intermediate previews,
        which is exactly backwards.
        """
        lines = [
            line.strip()
            for line in self._script(
                PostOptions(stretch=True, previews=True)
            ).splitlines()
        ]
        final = next(
            i for i, l in enumerate(lines) if l.startswith("savejpg previews/99_final")
        )
        # Walk back to the load that starts this preview block.
        start = max(i for i, l in enumerate(lines[:final]) if l.startswith("load "))
        self.assertNotIn("autostretch", lines[start:final])

    def test_the_plain_stack_preview_is_still_stretched(self) -> None:
        """It is linear whatever the layers did, so it needs the stretch."""
        lines = [
            line.strip()
            for line in self._script(
                PostOptions(stretch=True, previews=True)
            ).splitlines()
        ]
        stacked = next(
            i for i, l in enumerate(lines) if l.startswith("savejpg previews/00_stacked")
        )
        start = max(i for i, l in enumerate(lines[:stacked]) if l.startswith("load "))
        self.assertIn("autostretch", lines[start:stacked])

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
        # 04, not 02: denoise's number is its own and does not shuffle down
        # when the stages before it are switched off.
        self.assertIn("savejpg previews/04_denoised", script)
        self.assertIn("savejpg previews/99_final", script)
        self.assertIn("resample -maxdim=1600", script)

    def test_previews_alone_do_not_alter_the_image(self) -> None:
        script = self._script(PostOptions(previews=True))
        for command in ("subsky", "denoise", "platesolve", "pcc", "starnet"):
            self.assertNotIn(f"\n{command}", script)
        self.assertIn("savejpg previews/00_stacked", script)


if __name__ == "__main__":
    unittest.main()
