"""Read a DWARF 3 card and work out what is on it.

Everything in here treats the source as strictly read-only.

Layout, as observed on a real DWARF 3 (firmware 1.5.2.1) rather than assumed:

    <root>/
      DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_2026-08-12-00-05-34-558/
        shotsInfo.json
        C 27_15s100_Duo-Band_20260812-000629484_32C.fits   <- a light
        stacked-16_C 27_..._20260812-000615452.fits        <- NOT a light
        stacked.jpg, img_reference.png, Thumbnail/         <- NOT lights
      DWARF_RAW_WIDE_EXP_10_GAIN_0_.../                    <- other camera
      DWARF_DARK/
        tele_exp_15_gain_100_bin_1_2026-08-12-01-57-54-576/
          raw_15s_100_0000_20260812-015808617_33C.fits
      CALI_FRAME/, RESTACKED/, STARTRAILS/, Solving_Failed/  <- ignored

Note the target name contains a space ("C 27", "IC 1396"), the target may be
absent entirely, and dark folders carry no shotsInfo.json at all.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Iterable

from .fits_header import FitsHeaderError, read_header
from .model import DarkSet, LightSession, MasterDark

SESSION_PREFIX = "DWARF_RAW_"
DARK_FOLDER = "DWARF_DARK"
CALI_FOLDER = "CALI_FRAME"

# Folders on the card that are never inputs to a stack.
IGNORED_FOLDERS = {CALI_FOLDER, "RESTACKED", "STARTRAILS", "Solving_Failed", "Thumbnail"}

# A DWARF light frame always ends in its sensor temperature, e.g. "_32C.fits".
LIGHT_FRAME_RE = re.compile(r"_(-?\d+(?:\.\d+)?)C\.fits$", re.IGNORECASE)

# The DWARF's own stack, dropped in beside the subs. Not a light frame.
STACKED_PREFIX = "stacked"

# The DWARF's own live-stacked preview of the session, at gallery size. Around
# 25-50 KB, which is why this one is used rather than the full stacked.jpg
# sitting next to it at 4.6 MB -- both show the same picture, and only one of
# them is sensible to load for something an inch wide on a card.
SESSION_THUMBNAIL = "stacked_thumbnail.jpg"

# The same picture at full size: 3840x2160, ~4 MB, already stretched. This is
# what the DWARF's own app shows you in its album, and it is the one to open
# when somebody asks to see the picture properly.
#
# Checked against the alternatives rather than assumed. img_reference.png is
# a single unstretched frame and comes out nearly black; stacked-16_*.png is
# the 16-bit linear version; img_stacked_counter.png is an overlay. Only
# stacked.jpg is the processed picture a person would recognise.
SESSION_ALBUM = "stacked.jpg"

# DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_2026-08-12-00-05-34-558
# DWARF_RAW_WIDE_EXP_10_GAIN_0_2026-08-11-23-52-01-418        (no target)
SESSION_RE = re.compile(
    r"^DWARF_RAW_(?P<camera>[A-Z]+)_"
    r"(?:(?P<target>.+?)_)?"
    r"EXP_(?P<exposure>[\d.]+)_GAIN_(?P<gain>\d+)_"
    r"(?P<stamp>[\d-]+)$"
)

# tele_exp_15_gain_100_bin_1_2026-08-12-01-57-54-576
DARK_RE = re.compile(
    r"^(?P<camera>[a-z]+)_exp_(?P<exposure>[\d.]+)_gain_(?P<gain>\d+)_"
    r"bin_(?P<binning>\d+)_(?P<stamp>[\d-]+)$"
)

# 2026-08-12-00-05-34-558
STAMP_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})")

ProgressFn = Callable[[str], None]


def _pretty_stamp(stamp: str) -> str:
    match = STAMP_RE.match(stamp)
    if not match:
        return stamp
    year, month, day, hour, minute, second = match.groups()
    return f"{year}-{month}-{day} {hour}:{minute}:{second}"


def _as_float(value: object) -> float | None:
    """A header value as a number, or None when it is not one."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _binning_from_text(text: object) -> int:
    """shotsInfo.json writes binning as '1*1'; we want the integer 1."""
    if isinstance(text, int):
        return text
    if isinstance(text, str) and text:
        head = re.split(r"[*x×]", text)[0].strip()
        if head.isdigit():
            return int(head)
    return 1


def is_light_frame(path: Path) -> bool:
    """True only for a sub the DWARF wrote.

    Deliberately strict, because a session folder is not ours and does not
    stay tidy. The DWARF drops its own live stack and previews in there, and
    a user who has processed the session will have left Siril's output in it
    too -- .fit working files, Autosave.tif, per-frame .txt sidecars.

    A DWARF sub is always ``<name>_<sensor temperature>C.fits``: that exact
    shape, and the ``.fits`` extension rather than Siril's ``.fit``. Anything
    else in the folder is somebody else's file and is left alone.
    """
    if path.suffix.lower() != ".fits":
        return False
    if path.name.lower().startswith(STACKED_PREFIX):
        return False
    return bool(LIGHT_FRAME_RE.search(path.name))


def _frame_temperature(path: Path) -> float | None:
    match = LIGHT_FRAME_RE.search(path.name)
    return float(match.group(1)) if match else None


def _sorted_frames(folder: Path) -> list[Path]:
    """Light frames in capture order. The timestamp in the name sorts correctly."""
    return sorted(
        (child for child in folder.iterdir() if child.is_file() and is_light_frame(child)),
        key=lambda item: item.name,
    )


def _temp_range(frames: Iterable[Path]) -> tuple[float | None, float | None]:
    temps = [temp for temp in (_frame_temperature(f) for f in frames) if temp is not None]
    if not temps:
        return None, None
    return min(temps), max(temps)


def _read_shots_info(folder: Path) -> dict | None:
    info_path = folder / "shotsInfo.json"
    if not info_path.is_file():
        return None
    try:
        with open(info_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _sample_header(frames: list[Path]) -> dict:
    """The frames' own header beats every other source, so try a few.

    Only a few: opening one header is cheap, opening three hundred is not, and
    a session's frames are all shot with the same settings by construction.
    """
    for frame in frames[:3]:
        try:
            return read_header(frame)
        except FitsHeaderError:
            continue
    return {}


def read_light_session(folder: Path) -> LightSession | None:
    """Build a session from a ``DWARF_RAW_*`` folder, or None if it holds no subs.

    Metadata precedence is FITS header > shotsInfo.json > folder name. The
    header is the only one of the three written per-frame by the camera itself.
    """
    match = SESSION_RE.match(folder.name)
    frames = _sorted_frames(folder)
    if not frames:
        return None

    notes: list[str] = []
    header = _sample_header(frames)
    info = _read_shots_info(folder)

    sources: list[str] = []
    if header:
        sources.append("FITS header")
    if info:
        sources.append("shotsInfo.json")
    if match:
        sources.append("folder name")

    def pick(header_key: str, info_key: str, name_key: str, cast, default):
        if header_key and header_key in header and header[header_key] not in (None, ""):
            return cast(header[header_key])
        if info and info_key and info.get(info_key) not in (None, ""):
            return cast(info[info_key])
        if match and name_key:
            captured = match.group(name_key)
            if captured is not None:
                return cast(captured)
        return default

    exposure = pick("EXPTIME", "exp", "exposure", float, 0.0)
    gain = pick("GAIN", "gain", "gain", lambda v: int(float(v)), 0)
    binning = pick("XBINNING", "binning", "", _binning_from_text, 1)
    filter_name = pick("FILTER", "ir", "", lambda v: str(v).strip(), "")
    camera = pick("CAMERA", "", "camera", lambda v: str(v).strip().upper(), "TELE")
    target = pick("OBJECT", "target", "target", lambda v: str(v).strip(), "")

    # THE OPTICS, READ RATHER THAN ASSUMED.
    # The DWARF 3 has two cameras and they are nothing alike: the telephoto
    # is 150mm at 2.0um, the wide is 6.7mm at 2.9um -- a twenty-two-fold
    # difference in focal length and a field of a few degrees against most
    # of the sky. Plate solving was seeded with the telephoto's numbers
    # whatever took the frames, so on wide-angle sessions the solver hunted
    # for a 3.4 degree field in a 46 degree image and could not possibly
    # find it. Every frame states its own optics; there is no reason to guess.
    focal_length = pick("FOCALLEN", "", "", float, 0.0)
    pixel_size = pick("XPIXSZ", "", "", float, 0.0)

    # Where the telescope was pointing, if it recorded it. The wide camera
    # writes 0/0 -- not a coordinate, an absence -- and a solver given a
    # false starting point searches the wrong part of the sky.
    pointing_ra = _as_float(header.get("RA"))
    pointing_dec = _as_float(header.get("DEC"))
    if pointing_ra == 0.0 and pointing_dec == 0.0:
        pointing_ra = pointing_dec = None

    # EQ mode: EQMODE in the header, `eq` in shotsInfo.json. If neither exists
    # we say None -- unknown -- rather than guessing a value either way.
    eq_mode: bool | None = None
    if "EQMODE" in header:
        eq_mode = bool(header["EQMODE"])
    elif info is not None and "eq" in info:
        eq_mode = bool(info["eq"])

    if not header:
        notes.append("Could not read any FITS header; settings come from weaker sources.")

    temp_min, temp_max = _temp_range(frames)

    # Recorded, not read: whether the file opens as an image is the display
    # layer's problem, and a card must survive a corrupt one.
    thumbnail = folder / SESSION_THUMBNAIL
    if not thumbnail.is_file():
        thumbnail = None
    album = folder / SESSION_ALBUM
    if not album.is_file():
        album = None

    session = LightSession(
        path=folder,
        target=target,
        exposure=exposure,
        gain=gain,
        binning=binning,
        filter_name=filter_name,
        camera=camera or "TELE",
        focal_length=focal_length,
        pixel_size=pixel_size,
        pointing_ra=pointing_ra,
        pointing_dec=pointing_dec,
        eq_mode=eq_mode,
        frames=frames,
        started=_pretty_stamp(match.group("stamp")) if match else "",
        temp_min=temp_min,
        temp_max=temp_max,
        shots_taken=info.get("shotsTaken") if info else None,
        shots_stacked=info.get("shotsStacked") if info else None,
        metadata_source=" > ".join(sources) if sources else "unknown",
        notes=notes,
        thumbnail=thumbnail,

        album_image=album,
    )

    if info and info.get("shotsTaken") and info["shotsTaken"] != len(frames):
        session.notes.append(
            f"shotsInfo.json reports {info['shotsTaken']} frames but "
            f"{len(frames)} are on disk; using what is on disk."
        )
    return session


def read_dark_set(folder: Path) -> DarkSet | None:
    """Build a dark set from a ``DWARF_DARK/*`` folder.

    Dark folders carry no shotsInfo.json, so the folder name is the primary
    source here and the frames' own headers are the cross-check.
    """
    frames = _sorted_frames(folder)
    if not frames:
        return None

    match = DARK_RE.match(folder.name)
    header = _sample_header(frames)

    if "EXPTIME" in header:
        exposure = float(header["EXPTIME"])
    elif match:
        exposure = float(match.group("exposure"))
    else:
        return None

    if "GAIN" in header:
        gain = int(float(header["GAIN"]))
    elif match:
        gain = int(match.group("gain"))
    else:
        return None

    if "XBINNING" in header:
        binning = _binning_from_text(header["XBINNING"])
    elif match:
        binning = int(match.group("binning"))
    else:
        binning = 1

    camera = str(header.get("CAMERA", "") or (match.group("camera") if match else "TELE"))
    temp_min, temp_max = _temp_range(frames)

    return DarkSet(
        path=folder,
        exposure=exposure,
        gain=gain,
        binning=binning,
        camera=camera.strip().upper() or "TELE",
        frames=frames,
        started=_pretty_stamp(match.group("stamp")) if match else "",
        temp_min=temp_min,
        temp_max=temp_max,
        metadata_source="FITS header > folder name" if header else "folder name",
    )


# CALI_FRAME/dark/cam_0/dark_exp_15.000000_gain_100_bin_1_33C_stack_10.fits
CALI_DARK_RE = re.compile(
    r"^dark_exp_(?P<exposure>[\d.]+)_gain_(?P<gain>\d+)_bin_(?P<binning>\d+)_"
    r"(?P<temp>-?\d+(?:\.\d+)?)C_stack_(?P<count>\d+)\.fits$",
    re.IGNORECASE,
)

# CALI_FRAME splits by camera index, not by name. cam_0 is the 3840x2160 TELE
# sensor, cam_1 the smaller WIDE one -- confirmed by file size on real data
# (16.6 MB vs 4.2 MB) and by which exposures appear under each.
CALI_CAMERA_BY_DIR = {"cam_0": "TELE", "cam_1": "WIDE"}


def read_cali_masters(cali_root: Path) -> list[MasterDark]:
    """Read the DWARF's own pre-stacked master darks from ``CALI_FRAME/dark``.

    These are a fallback for when the user never shot a matching dark set.
    There is no index file, so the filename is the whole story.
    """
    masters: list[MasterDark] = []
    dark_root = cali_root / "dark"
    if not dark_root.is_dir():
        return masters

    try:
        cam_dirs = sorted(dark_root.iterdir(), key=lambda item: item.name)
    except OSError:
        return masters

    for cam_dir in cam_dirs:
        if not cam_dir.is_dir():
            continue
        camera = CALI_CAMERA_BY_DIR.get(cam_dir.name.lower())
        if camera is None:
            continue
        try:
            files = sorted(cam_dir.iterdir(), key=lambda item: item.name)
        except OSError:
            continue
        for item in files:
            match = CALI_DARK_RE.match(item.name)
            if not match or not item.is_file():
                continue
            masters.append(
                MasterDark(
                    path=item,
                    exposure=float(match.group("exposure")),
                    gain=int(match.group("gain")),
                    binning=int(match.group("binning")),
                    camera=camera,
                    stack_count=int(match.group("count")),
                    temperature=float(match.group("temp")),
                )
            )
    return masters


class ScanResult:
    """Everything found on one card."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.sessions: list[LightSession] = []
        self.darks: list[DarkSet] = []
        self.cali_masters: list[MasterDark] = []
        self.skipped: list[str] = []

    @property
    def stackable_sessions(self) -> list[LightSession]:
        """Every session found. Alt-az stacks too; it just costs the edges."""
        return list(self.sessions)

    @property
    def eq_sessions(self) -> list[LightSession]:
        """Kept for callers that specifically want EQ, e.g. reporting."""
        return [s for s in self.sessions if s.eq_mode is not False]

    @property
    def altaz_sessions(self) -> list[LightSession]:
        return [s for s in self.sessions if s.eq_mode is False]

    def targets(self) -> list[str]:
        seen: list[str] = []
        for session in self.sessions:
            if session.target not in seen:
                seen.append(session.target)
        return seen


def find_astronomy_root(start: Path) -> Path | None:
    """Accept either the card root or the ``Astronomy`` folder inside it.

    The user picks a drive; we work out which of those two they gave us so
    they never have to care about the distinction.
    """
    start = Path(start)
    if not start.is_dir():
        return None
    if looks_like_dwarf_root(start):
        return start
    for name in ("Astronomy", "DWARF_II", "DWARF"):
        candidate = start / name
        if candidate.is_dir() and looks_like_dwarf_root(candidate):
            return candidate
    return None


def looks_like_dwarf_root(folder: Path) -> bool:
    """Cheap test: does this folder hold DWARF session or dark folders?"""
    try:
        for child in folder.iterdir():
            if not child.is_dir():
                continue
            if child.name.startswith(SESSION_PREFIX):
                return True
            if child.name in (DARK_FOLDER, CALI_FOLDER):
                return True
    except OSError:
        return False
    return False


def scan(root: Path, progress: ProgressFn | None = None) -> ScanResult:
    """Walk a DWARF 3 card. Reads only -- never writes, moves or renames."""
    root = Path(root)
    result = ScanResult(root)

    def report(message: str) -> None:
        if progress:
            progress(message)

    try:
        children = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        result.skipped.append(f"Could not read {root}: {exc}")
        return result

    for child in children:
        if not child.is_dir():
            continue

        if child.name == DARK_FOLDER:
            report(f"Reading darks in {child.name}")
            for dark_folder in sorted(child.iterdir(), key=lambda item: item.name):
                if not dark_folder.is_dir():
                    continue
                dark = read_dark_set(dark_folder)
                if dark:
                    result.darks.append(dark)
                else:
                    result.skipped.append(f"{dark_folder.name}: no readable dark frames")
            continue

        if child.name == CALI_FOLDER:
            report("Reading DWARF master calibration frames")
            result.cali_masters.extend(read_cali_masters(child))
            continue

        if child.name in IGNORED_FOLDERS:
            continue

        if child.name.startswith(SESSION_PREFIX):
            report(f"Reading {child.name}")
            session = read_light_session(child)
            if session:
                result.sessions.append(session)
            else:
                result.skipped.append(f"{child.name}: no light frames")

    result.sessions.sort(key=lambda s: (s.target, s.started))
    result.darks.sort(key=lambda d: (d.exposure, d.gain))
    return result
