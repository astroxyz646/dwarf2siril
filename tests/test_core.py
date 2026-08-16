"""Tests for the parsing, grouping and script-generation core.

These build a fake DWARF card in a temp folder so they run anywhere. The
fixture mirrors the real layout observed on a DWARF 3 (firmware 1.5.2.1),
including the details that are easy to get wrong: spaces in target names, the
DWARF's own ``stacked-16_*.fits`` sitting beside the subs, and dark folders
having no shotsInfo.json at all.

Run with:  python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

from dwarf2siril.builder import build
from dwarf2siril.fits_header import FitsHeaderError, read_header
from dwarf2siril.grouping import auto_group, build_group, check_compatibility
from dwarf2siril.model import (
    FRAMING_CLEAN,
    FRAMING_WHOLE,
    MIN_CALI_STACK_COUNT,
    default_framing,
)
from dwarf2siril.scanner import find_astronomy_root, is_light_frame, scan
from dwarf2siril.script import generate_script


def write_fits(path: Path, **cards) -> None:
    """Write a FITS file with a real header and a 1x1 pixel of data."""
    header: list[str] = []

    def card(key: str, value) -> None:
        if isinstance(value, bool):
            rendered = "T" if value else "F"
        elif isinstance(value, str):
            rendered = f"'{value:<8}'"
        else:
            rendered = str(value)
        header.append(f"{key:<8}= {rendered:>20}".ljust(80)[:80])

    card("SIMPLE", True)
    card("BITPIX", 16)
    card("NAXIS", 2)
    card("NAXIS1", 1)
    card("NAXIS2", 1)
    for key, value in cards.items():
        card(key, value)
    header.append("END".ljust(80))

    block = "".join(header)
    block += " " * (2880 - (len(block) % 2880))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(block.encode("ascii"))
        handle.write(struct.pack(">h", 0))
        handle.write(b"\0" * (2880 - 2))


def make_session(
    root: Path,
    folder: str,
    target: str,
    exposure: float,
    gain: int,
    frames: int,
    eq: bool = True,
    filter_name: str = "Duo-Band",
    camera: str = "TELE",
    binning: int = 1,
    focal: float = 150.0,
    pixel_size: float = 2.0,
    ra: float | None = 10.68,
    dec: float | None = 41.27,
) -> Path:
    session = root / folder
    session.mkdir(parents=True, exist_ok=True)

    for index in range(frames):
        name = f"{target}_{exposure:g}s{gain}_{filter_name}_2026081200{index:04d}_32C.fits"
        write_fits(
            session / name,
            EXPTIME=float(exposure),
            GAIN=gain,
            XBINNING=binning,
            YBINNING=binning,
            FILTER=filter_name,
            CAMERA=camera,
            OBJECT=target,
            EQMODE=1 if eq else 0,
            BAYERPAT="RGGB",
            FOCALLEN=focal,
            XPIXSZ=pixel_size,
            YPIXSZ=pixel_size,
            # The wide camera writes 0/0, which is an absence rather than a
            # coordinate; pass ra=0, dec=0 to reproduce that case.
            RA=0.0 if ra is None else ra,
            DEC=0.0 if dec is None else dec,
        )

    # The DWARF's own stack and its previews live here too. None are lights.
    write_fits(session / f"stacked-16_{target}_x.fits", EXPTIME=float(exposure))
    (session / "stacked.jpg").write_bytes(b"not a frame")
    (session / "img_reference.png").write_bytes(b"not a frame")
    (session / "Thumbnail").mkdir(exist_ok=True)

    (session / "shotsInfo.json").write_text(
        json.dumps(
            {
                "target": target,
                "exp": str(exposure),
                "gain": gain,
                "binning": f"{binning}*{binning}",
                "ir": filter_name,
                "eq": eq,
                "format": "FITS",
                "shotsTaken": frames,
                "shotsStacked": frames,
                "maxTemp": 34,
                "minTemp": 32,
            }
        ),
        encoding="utf-8",
    )
    return session


def make_darks(
    root: Path, exposure: float, gain: int, frames: int, binning: int = 1
) -> Path:
    folder = (
        root
        / "DWARF_DARK"
        / f"tele_exp_{exposure:g}_gain_{gain}_bin_{binning}_2026-08-12-01-57-54-576"
    )
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(frames):
        write_fits(
            folder / f"raw_{exposure:g}s_{gain}_{index:04d}_2026081201_33C.fits",
            EXPTIME=float(exposure),
            GAIN=gain,
            XBINNING=binning,
            CAMERA="TELE",
        )
    return folder


def make_cali_master(
    root: Path, exposure: float, gain: int, stack_count: int, camera_dir: str = "cam_0"
) -> Path:
    folder = root / "CALI_FRAME" / "dark" / camera_dir
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (
        f"dark_exp_{exposure:.6f}_gain_{gain}_bin_1_33C_stack_{stack_count}.fits"
    )
    write_fits(path, EXPTIME=float(exposure), GAIN=gain)
    return path


class FitsHeaderTests(unittest.TestCase):
    def test_reads_typed_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.fits"
            write_fits(path, EXPTIME=15.0, GAIN=100, OBJECT="C 27", EQMODE=1)
            header = read_header(path)
        self.assertEqual(header["EXPTIME"], 15.0)
        self.assertEqual(header["GAIN"], 100)
        self.assertEqual(header["OBJECT"], "C 27")
        self.assertEqual(header["EQMODE"], 1)

    def test_rejects_non_fits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nope.fits"
            path.write_bytes(b"definitely not fits")
            with self.assertRaises(FitsHeaderError):
                read_header(path)


class FrameFilterTests(unittest.TestCase):
    def test_excludes_dwarf_stack_and_previews(self) -> None:
        self.assertTrue(is_light_frame(Path("C 27_15s100_Duo-Band_2026_32C.fits")))
        self.assertFalse(is_light_frame(Path("stacked-16_C 27_Duo-Band_2026.fits")))
        self.assertFalse(is_light_frame(Path("stacked.jpg")))
        self.assertFalse(is_light_frame(Path("img_reference.png")))


class OperatorLeftoversTests(unittest.TestCase):
    """A session folder is not ours and does not stay tidy.

    Once someone has processed a session in place, Siril's own output sits
    alongside the subs. None of it may be mistaken for a light frame. This
    mirrors a real folder on the operator's card.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Astronomy"
        self.root.mkdir(parents=True)
        self.session = make_session(
            self.root, "DWARF_RAW_TELE_M 31_EXP_30_GAIN_60_A", "M 31", 30, 60, 5, eq=False
        )
        # Exactly the kinds of file found in the operator's own session folder.
        write_fits(self.session / "M_31_166x30sec_2026-08-10_1842_og.fit", EXPTIME=30.0)
        write_fits(self.session / "pp_light_00001.fit", EXPTIME=30.0)
        write_fits(self.session / "result.fits", EXPTIME=30.0)
        (self.session / "Autosave.tif").write_bytes(b"not a frame")
        (self.session / "Autosave001.tif").write_bytes(b"not a frame")
        (self.session / "M 31_30s60_Astro_20260810-221630815_35C.Info.txt").write_text("x")
        (self.session / "M 31_30s60_Astro_20260810-221630815_35C.stackinfo.txt").write_text("x")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_only_the_dwarfs_own_subs_are_counted(self) -> None:
        result = scan(self.root)
        self.assertEqual(len(result.sessions), 1)
        self.assertEqual(result.sessions[0].frame_count, 5)

    def test_siril_output_is_never_a_light_frame(self) -> None:
        for name in (
            "M_31_166x30sec_2026-08-10_1842_og.fit",
            "pp_light_00001.fit",
            "result.fits",
            "Autosave.tif",
            "M 31_30s60_Astro_20260810-221630815_35C.Info.txt",
        ):
            with self.subTest(name=name):
                self.assertFalse(is_light_frame(self.session / name))

    def test_a_fit_named_exactly_like_a_sub_is_still_excluded(self) -> None:
        # Siril writes .fit; the DWARF writes .fits. Converted copies of the
        # subs would otherwise be counted twice.
        self.assertFalse(
            is_light_frame(self.session / "M 31_30s60_Astro_20260810-221630815_35C.fit")
        )
        self.assertTrue(
            is_light_frame(self.session / "M 31_30s60_Astro_20260810-221630815_35C.fits")
        )


class ThumbnailTests(unittest.TestCase):
    """The DWARF's own session preview, used for recognising a target.

    Recording it is the core's job; deciding whether it opens as an image is
    the display layer's, which is why a corrupt file is still recorded here
    and only rejected when something tries to draw it.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Astronomy"
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_found_when_the_dwarf_wrote_one(self) -> None:
        session = make_session(
            self.root, "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_A", "C 27", 15, 100, 2
        )
        (session / "stacked_thumbnail.jpg").write_bytes(b"pretend jpeg")
        result = scan(self.root)
        self.assertEqual(
            result.sessions[0].thumbnail, session / "stacked_thumbnail.jpg"
        )

    def test_absent_is_none_not_a_broken_path(self) -> None:
        make_session(
            self.root, "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_A", "C 27", 15, 100, 2
        )
        result = scan(self.root)
        self.assertIsNone(result.sessions[0].thumbnail)

    def test_the_big_preview_is_never_used(self) -> None:
        # stacked.jpg is the same picture at 4.6 MB. Nothing should reach for
        # it to fill something an inch wide.
        session = make_session(
            self.root, "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_A", "C 27", 15, 100, 2
        )
        (session / "stacked.jpg").write_bytes(b"big")
        result = scan(self.root)
        self.assertIsNone(result.sessions[0].thumbnail)

    def test_a_group_uses_the_first_session_that_has_one(self) -> None:
        make_session(self.root, "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_A", "C 27", 15, 100, 2)
        second = make_session(
            self.root, "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_B", "C 27", 15, 100, 2
        )
        (second / "stacked_thumbnail.jpg").write_bytes(b"pretend jpeg")
        result = scan(self.root)
        group = auto_group(result.stackable_sessions, result.darks)[0]
        self.assertEqual(len(group.sessions), 2)
        self.assertEqual(group.thumbnail, second / "stacked_thumbnail.jpg")

    def test_the_album_image_is_the_full_size_one(self) -> None:
        # stacked.jpg is what the DWARF's own app shows in its album: the
        # same picture as the thumbnail, at 3840x2160. It is recorded so it
        # can be opened on demand, and never used to draw a card.
        session = make_session(
            self.root, "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_A", "C 27", 15, 100, 2
        )
        (session / "stacked.jpg").write_bytes(b"pretend jpeg")
        (session / "stacked_thumbnail.jpg").write_bytes(b"pretend jpeg")
        result = scan(self.root)
        found = result.sessions[0]
        self.assertEqual(found.album_image, session / "stacked.jpg")
        self.assertEqual(found.thumbnail, session / "stacked_thumbnail.jpg")

    def test_no_album_image_is_none(self) -> None:
        session = make_session(
            self.root, "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_A", "C 27", 15, 100, 2
        )
        (session / "stacked.jpg").unlink()
        result = scan(self.root)
        self.assertIsNone(result.sessions[0].album_image)

    def test_the_unstretched_reference_frame_is_never_the_album(self) -> None:
        # img_reference.png is a single unstretched frame and comes out
        # nearly black. Showing it as "your picture" would be a bad joke, so
        # it is not a fallback when the real album image is absent.
        session = make_session(
            self.root, "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_A", "C 27", 15, 100, 2
        )
        (session / "stacked.jpg").unlink()
        (session / "img_reference.png").write_bytes(b"big and black")
        result = scan(self.root)
        self.assertIsNone(result.sessions[0].album_image)

    def test_a_group_with_none_has_none(self) -> None:
        make_session(self.root, "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_A", "C 27", 15, 100, 2)
        result = scan(self.root)
        group = auto_group(result.stackable_sessions, result.darks)[0]
        self.assertIsNone(group.thumbnail)


class ScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Astronomy"
        self.root.mkdir(parents=True)
        make_session(
            self.root,
            "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_2026-08-12-00-05-34-558",
            "C 27",
            15,
            100,
            4,
        )
        make_session(
            self.root,
            "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_2026-08-12-01-05-21-155",
            "C 27",
            15,
            100,
            3,
        )
        make_session(
            self.root,
            "DWARF_RAW_TELE_M 31_EXP_30_GAIN_60_2026-08-10-22-15-21-385",
            "M 31",
            30,
            60,
            2,
            eq=False,
        )
        make_darks(self.root, 15, 100, 6)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_finds_sessions_and_excludes_non_lights(self) -> None:
        result = scan(self.root)
        self.assertEqual(len(result.sessions), 3)
        c27 = [s for s in result.sessions if s.target == "C 27"]
        self.assertEqual(sorted(s.frame_count for s in c27), [3, 4])

    def test_separates_eq_from_altaz(self) -> None:
        result = scan(self.root)
        self.assertEqual(len(result.eq_sessions), 2)
        altaz = [s for s in result.sessions if s.eq_mode is False]
        self.assertEqual(len(altaz), 1)
        self.assertEqual(altaz[0].target, "M 31")

    def test_target_with_space_survives(self) -> None:
        result = scan(self.root)
        self.assertIn("C 27", [s.target for s in result.sessions])

    def test_accepts_drive_root_or_astronomy_folder(self) -> None:
        self.assertEqual(find_astronomy_root(self.root), self.root)
        self.assertEqual(find_astronomy_root(self.root.parent), self.root)

    def test_darks_parsed_without_shotsinfo(self) -> None:
        result = scan(self.root)
        self.assertEqual(len(result.darks), 1)
        self.assertEqual(result.darks[0].exposure, 15.0)
        self.assertEqual(result.darks[0].gain, 100)
        self.assertEqual(result.darks[0].frame_count, 6)


class GroupingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Astronomy"
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_two_sessions_of_one_target_group_together(self) -> None:
        make_session(self.root, "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_A", "C 27", 15, 100, 4)
        make_session(self.root, "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_B", "C 27", 15, 100, 3)
        make_darks(self.root, 15, 100, 6)
        result = scan(self.root)
        groups = auto_group(result.eq_sessions, result.darks, result.cali_masters)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0].sessions), 2)
        self.assertEqual(groups[0].total_frames, 7)
        self.assertTrue(groups[0].is_buildable)

    def test_gain_mismatch_is_refused_and_names_the_field(self) -> None:
        make_session(self.root, "DWARF_RAW_TELE_IC 1396_EXP_30_GAIN_70_A", "IC 1396", 30, 70, 2)
        make_session(self.root, "DWARF_RAW_TELE_IC 1396_EXP_30_GAIN_130_B", "IC 1396", 30, 130, 2)
        result = scan(self.root)
        issues = check_compatibility(result.sessions)
        errors = [issue for issue in issues if issue.is_error]
        self.assertEqual(len(errors), 1)
        self.assertIn("gain differs", errors[0].message)
        self.assertIn("70", errors[0].message)
        self.assertIn("130", errors[0].message)

    def test_each_mismatched_field_is_reported(self) -> None:
        for field_name, kwargs in [
            ("exposure", {"exposure": 30}),
            ("IR filter", {"filter_name": "Astro"}),
            ("binning", {"binning": 2}),
        ]:
            with self.subTest(field=field_name):
                base = dict(target="C 27", exposure=15, gain=100, frames=2)
                sessions = scan(self._card_with(base, kwargs)).sessions
                issues = check_compatibility(sessions)
                messages = " ".join(i.message for i in issues if i.is_error)
                self.assertIn(field_name, messages)

    def _card_with(self, base: dict, override: dict) -> Path:
        tmp = Path(tempfile.mkdtemp()) / "Astronomy"
        tmp.mkdir(parents=True)
        make_session(tmp, "DWARF_RAW_TELE_A", folder_target := base["target"], **{
            k: v for k, v in base.items() if k != "target"
        })
        merged = {**{k: v for k, v in base.items() if k != "target"}, **override}
        make_session(tmp, "DWARF_RAW_TELE_B", folder_target, **merged)
        return tmp

    def test_altaz_session_stacks_but_says_what_it_costs(self) -> None:
        # Alt-az used to be refused. It stacks fine -- registration solves
        # rotation -- so it is now built, with the cost stated rather than
        # the session rejected.
        make_session(self.root, "DWARF_RAW_TELE_M 31_EXP_30_GAIN_60_A", "M 31", 30, 60, 2, eq=False)
        result = scan(self.root)
        group = build_group(result.sessions, result.darks)
        self.assertTrue(group.is_buildable)
        self.assertEqual(group.errors, [])
        self.assertTrue(group.is_altaz)
        self.assertEqual(group.mount_mode, "alt-az")
        self.assertTrue(any("corners" in i.message for i in group.warnings))

    def test_eq_and_altaz_of_one_target_never_merge(self) -> None:
        # Alignment would cope, but the alt-az session's rotation would cost
        # the whole combined stack its edges -- including the EQ frames that
        # did not need to lose them. That is a mistake nobody would diagnose.
        make_session(self.root, "DWARF_RAW_TELE_M 31_EXP_30_GAIN_60_EQ", "M 31", 30, 60, 3)
        make_session(
            self.root, "DWARF_RAW_TELE_M 31_EXP_30_GAIN_60_AZ", "M 31", 30, 60, 2, eq=False
        )
        result = scan(self.root)
        groups = auto_group(result.stackable_sessions, result.darks)
        self.assertEqual(len(groups), 2)
        self.assertEqual({g.mount_mode for g in groups}, {"EQ", "alt-az"})
        for group in groups:
            self.assertEqual(len(group.sessions), 1)
        explained = " ".join(i.message for g in groups for i in g.warnings)
        self.assertIn("both in EQ and in alt-az", explained)
        self.assertIn("kept apart on purpose", explained)

    def test_darks_matched_on_exposure_and_gain(self) -> None:
        make_session(self.root, "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_A", "C 27", 15, 100, 3)
        make_darks(self.root, 15, 100, 6)
        make_darks(self.root, 60, 50, 6)
        result = scan(self.root)
        group = build_group(result.eq_sessions, result.darks)
        self.assertEqual(len(group.darks), 1)
        self.assertEqual(group.darks[0].exposure, 15.0)
        self.assertEqual(group.darks[0].gain, 100)

    def test_no_matching_dark_warns_but_does_not_block(self) -> None:
        make_session(self.root, "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_A", "C 27", 15, 100, 3)
        make_darks(self.root, 60, 50, 6)
        result = scan(self.root)
        group = build_group(result.eq_sessions, result.darks)
        self.assertEqual(group.darks, [])
        self.assertTrue(group.is_buildable)
        self.assertTrue(any("No dark set matches" in i.message for i in group.warnings))


class CaliFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Astronomy"
        self.root.mkdir(parents=True)
        make_session(self.root, "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_A", "C 27", 15, 100, 3)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_deep_enough_master_is_used_when_no_raw_darks(self) -> None:
        make_cali_master(self.root, 15, 100, MIN_CALI_STACK_COUNT + 5)
        result = scan(self.root)
        group = build_group(result.eq_sessions, result.darks, result.cali_masters)
        self.assertIsNotNone(group.master_dark)
        self.assertTrue(group.has_calibration)
        self.assertIn("DWARF-supplied", group.dark_source)

    def test_single_frame_master_is_rejected(self) -> None:
        make_cali_master(self.root, 15, 100, 1)
        result = scan(self.root)
        group = build_group(result.eq_sessions, result.darks, result.cali_masters)
        self.assertIsNone(group.master_dark)
        self.assertFalse(group.has_calibration)
        self.assertTrue(any("rejected" in i.message for i in group.warnings))

    def test_raw_darks_win_over_supplied_master(self) -> None:
        make_darks(self.root, 15, 100, 6)
        make_cali_master(self.root, 15, 100, 10)
        result = scan(self.root)
        group = build_group(result.eq_sessions, result.darks, result.cali_masters)
        self.assertIsNone(group.master_dark)
        self.assertEqual(len(group.darks), 1)
        self.assertIn("Your own darks", group.dark_source)

    def test_fallback_can_be_switched_off(self) -> None:
        make_cali_master(self.root, 15, 100, 10)
        result = scan(self.root)
        group = build_group(
            result.eq_sessions, result.darks, result.cali_masters, use_cali_fallback=False
        )
        self.assertIsNone(group.master_dark)
        self.assertFalse(group.has_calibration)

    def test_deepest_master_is_preferred(self) -> None:
        make_cali_master(self.root, 15, 100, 6)
        folder = self.root / "CALI_FRAME" / "dark" / "cam_0"
        write_fits(
            folder / "dark_exp_15.000000_gain_100_bin_1_30C_stack_9.fits",
            EXPTIME=15.0,
            GAIN=100,
        )
        result = scan(self.root)
        group = build_group(result.eq_sessions, result.darks, result.cali_masters)
        self.assertEqual(group.master_dark.stack_count, 9)


class ScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Astronomy"
        self.root.mkdir(parents=True)
        make_session(self.root, "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_A", "C 27", 15, 100, 3)
        make_darks(self.root, 15, 100, 6)
        self.result = scan(self.root)
        self.group = build_group(self.result.eq_sessions, self.result.darks)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_paths_with_spaces_are_quoted(self) -> None:
        script = generate_script(self.group, Path("C:/Astro Output/C 27 stack"))
        cd_lines = [line for line in script.splitlines() if line.startswith("cd ")]
        self.assertTrue(cd_lines[0].startswith('cd "'))
        self.assertTrue(cd_lines[0].endswith('"'))
        self.assertIn("C 27 stack", cd_lines[0])

    def test_only_the_first_cd_is_absolute(self) -> None:
        script = generate_script(self.group, Path("C:/Astro Output/C 27 stack"))
        cd_lines = [line for line in script.splitlines() if line.startswith("cd ")]
        for line in cd_lines[1:]:
            self.assertNotIn('"', line)
            self.assertNotIn(" ", line[3:])

    def test_includes_master_dark_and_stack_steps(self) -> None:
        script = generate_script(self.group, Path("/out"))
        self.assertIn("stack dark rej w 3 3 -nonorm -out=../masters/master_dark", script)
        self.assertIn("calibrate light -dark=../masters/master_dark", script)
        self.assertIn("register pp_light", script)
        self.assertIn("stack r_pp_light rej w 3 3", script)

    def test_eq_trims_to_the_shared_area_by_default(self) -> None:
        # Mounts drift, so even an EQ session's edges are covered by fewer
        # frames than its middle. Trimming is self-adjusting: it costs
        # nothing when the frames line up and removes the bad edge when they
        # do not, which is what makes it safe as the default.
        script = generate_script(self.group, Path("/out"), "STACK")
        self.assertIn("-framing=min", script)

    def test_eq_can_still_keep_the_whole_frame(self) -> None:
        script = generate_script(
            self.group, Path("/out"), "STACK", framing=FRAMING_WHOLE
        )
        self.assertIn("-framing=current", script)

    def test_altaz_defaults_to_keeping_the_whole_frame(self) -> None:
        script = generate_script(self._altaz_group(), Path("/out"), "STACK")
        self.assertIn("-framing=current", script)
        # One vocabulary for both causes: rotation and drift both cost edges.
        self.assertIn("edges are built from", script)

    def test_altaz_clean_crop_is_available(self) -> None:
        script = generate_script(
            self._altaz_group(), Path("/out"), "STACK", framing=FRAMING_CLEAN
        )
        self.assertIn("-framing=min", script)

    def test_the_two_causes_get_opposite_defaults(self) -> None:
        # Rotation and drift are the same problem -- uneven coverage at the
        # edges -- but they cost wildly different amounts to fix, so one
        # fixed default would be wrong half the time.
        self.assertEqual(default_framing(is_altaz=False), FRAMING_CLEAN)
        self.assertEqual(default_framing(is_altaz=True), FRAMING_WHOLE)

    def test_both_causes_are_explained_in_the_same_words(self) -> None:
        # The user should not need a second mental model because the cause
        # differs. Both say "edges", and both offer the same two choices.
        eq = generate_script(self.group, Path("/out"), "STACK", framing=FRAMING_WHOLE)
        altaz = generate_script(
            self._altaz_group(), Path("/out"), "STACK", framing=FRAMING_WHOLE
        )
        for script in (eq, altaz):
            self.assertIn("edges are built from", script)

    def test_multi_session_says_why_its_edges_are_uneven(self) -> None:
        tmp = Path(tempfile.mkdtemp()) / "Astronomy"
        tmp.mkdir(parents=True)
        make_session(tmp, "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_A", "C 27", 15, 100, 3)
        make_session(tmp, "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_B", "C 27", 15, 100, 2)
        make_darks(tmp, 15, 100, 5)
        result = scan(tmp)
        group = auto_group(result.stackable_sessions, result.darks)[0]
        script = generate_script(group, Path("/out"), "STACK")
        self.assertIn("Several sessions", script)
        self.assertIn("-framing=min", script)

    def test_framing_uses_two_pass_registration(self) -> None:
        # -framing belongs to seqapplyreg, so plain one-pass register would
        # silently drop the choice.
        script = generate_script(self._altaz_group(), Path("/out"), "STACK")
        self.assertIn("register pp_light -2pass", script)
        self.assertIn("seqapplyreg pp_light", script)

    def _altaz_group(self):
        tmp = Path(tempfile.mkdtemp()) / "Astronomy"
        tmp.mkdir(parents=True)
        make_session(tmp, "DWARF_RAW_TELE_M 31_EXP_60_GAIN_50_A", "M 31", 60, 50, 3, eq=False)
        make_darks(tmp, 60, 50, 5)
        result = scan(tmp)
        return build_group(result.stackable_sessions, result.darks)

    def test_uncalibrated_stacks_still_come_out_in_colour(self) -> None:
        # Debayering normally happens inside `calibrate`. With no darks there
        # is no calibrate step, so without -debayer on the convert the whole
        # stack comes back as a single grey layer.
        group = build_group(self.result.stackable_sessions, [], [])
        script = generate_script(group, Path("/out"), "STACK")
        self.assertIn("convert light -debayer", script)

    def test_calibrated_stacks_debayer_once_only(self) -> None:
        script = generate_script(self.group, Path("/out"), "STACK")
        self.assertIn("convert light -out=", script)
        self.assertNotIn("convert light -debayer", script)
        self.assertIn("-debayer", script)  # on calibrate, where it belongs

    def test_calibration_skipped_when_no_darks(self) -> None:
        group = build_group(self.result.eq_sessions, [], [])
        script = generate_script(group, Path("/out"))
        # Check for the command, not the word: the comments still explain that
        # calibration was skipped, and that explanation is the point.
        commands = [
            line for line in script.splitlines() if line and not line.startswith("#")
        ]
        self.assertFalse([line for line in commands if line.startswith("calibrate")])
        self.assertIn("register light", script)
        self.assertIn("No matching darks", script)


class BuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.root = self.base / "Astronomy"
        self.root.mkdir(parents=True)
        make_session(self.root, "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_A", "C 27", 15, 100, 4)
        make_session(self.root, "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_B", "C 27", 15, 100, 3)
        make_darks(self.root, 15, 100, 5)
        self.result = scan(self.root)
        self.group = auto_group(
            self.result.eq_sessions, self.result.darks, self.result.cali_masters
        )[0]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_builds_full_tree_from_two_sessions(self) -> None:
        out = self.base / "My Output" / "C 27"
        built = build(self.group, out, progress=None)
        self.assertEqual(built.lights_copied, 7)
        self.assertEqual(built.darks_copied, 5)
        for folder in ("lights", "darks", "masters", "process"):
            self.assertTrue((out / folder).is_dir())
        self.assertTrue(built.script_path.is_file())
        self.assertTrue((out / "build_summary.txt").is_file())

    def test_source_is_untouched(self) -> None:
        before = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*"))
        build(self.group, self.base / "out", progress=None)
        after = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*"))
        self.assertEqual(before, after)

    def test_script_path_is_absolute_even_from_a_relative_output(self) -> None:
        import os

        cwd = os.getcwd()
        os.chdir(self.base)
        try:
            built = build(self.group, Path("relative out"), progress=None)
            script = built.script_path.read_text(encoding="utf-8")
            cd_line = next(l for l in script.splitlines() if l.startswith("cd "))
            self.assertTrue(Path(cd_line[4:-1]).is_absolute())
        finally:
            os.chdir(cwd)

    def test_previews_from_an_earlier_run_are_cleared(self) -> None:
        """A rebuild must not leave the last run's stage previews behind.

        Found in the wild: a target was built with every layer on, then rebuilt
        with none. The second run wrote only the plain and final previews, so
        the first run's per-layer JPEGs survived and the before/after panel
        showed them as though they belonged to the new stack -- convincing
        per-layer differences sitting next to a plain-vs-final pair that were
        correctly identical.
        """
        from dwarf2siril.postprocess import PostOptions

        out = self.base / "rebuilt"
        build(self.group, out, post=PostOptions(previews=True), progress=None)

        previews = out / "previews"
        stale = previews / "01_background.jpg"
        stale.write_bytes(b"not really a jpeg")
        keep = previews / "notes.txt"
        keep.write_text("not a preview", encoding="utf-8")

        build(self.group, out, post=PostOptions(previews=True), progress=None)

        self.assertFalse(stale.exists(), "a previous run's preview survived")
        self.assertTrue(keep.is_file(), "non-preview files must be left alone")

    def test_refuses_to_build_an_incompatible_group(self) -> None:
        make_session(self.root, "DWARF_RAW_TELE_C 27_EXP_30_GAIN_100_C", "C 27", 30, 100, 2)
        result = scan(self.root)
        group = build_group(result.eq_sessions, result.darks)
        with self.assertRaises(ValueError):
            build(group, self.base / "nope", progress=None)


if __name__ == "__main__":
    unittest.main()
