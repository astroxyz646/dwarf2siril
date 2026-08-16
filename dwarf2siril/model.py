"""The things we find on a DWARF 3 card, and the rules for combining them.

Everything here is plain data plus pure functions. The CLI and the GUI both
sit on top of this and neither owns any of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Exposures are floats on the card ("0.0333333" for solar) but we compare them
# as keys, so round hard enough that 15.0 and 15.000001 are the same exposure
# and short solar exposures still separate cleanly.
EXPOSURE_DP = 4

# Sensor temperature is NOT part of the dark match key. The DWARF 3 is
# uncooled: a single C 27 session in the sample data drifts 32C -> 34C, so any
# exact-temperature rule would reject every dark set the telescope ever wrote.
# We match on exposure/gain/binning and report the temperature gap instead.
TEMP_WARN_DELTA_C = 8.0

# Floor for accepting a DWARF-supplied master dark from CALI_FRAME. Those
# files carry their frame count in the name (`..._stack_10.fits`) and on real
# hardware range from stack_1 to stack_10. A stack_1 "master" is one single
# frame: subtracting it would inject that frame's own read noise into every
# light instead of removing noise. 5 frames halves the dark's noise
# contribution (it falls as sqrt(N)), which is the point at which the trade
# starts paying. Below this we refuse and say why rather than quietly using it.
MIN_CALI_STACK_COUNT = 5


def exposure_key(seconds: float) -> float:
    return round(float(seconds), EXPOSURE_DP)


def format_exposure(seconds: float) -> str:
    """Human exposure: '15s', '0.0333s' -- never '15.0000s'."""
    value = exposure_key(seconds)
    if value == int(value):
        return f"{int(value)}s"
    return f"{value:g}s"


# How to frame a stack whose frames do not cover exactly the same sky. Named
# for what the user gets, not for the Siril argument underneath: nobody
# choosing between their own photos is thinking in terms of "-framing=current"
# versus "-framing=min".
#
# Two different causes, one problem and one set of words:
#
#   alt-az        the field ROTATES between frames
#   any session   the mount DRIFTS, and two nights never start identically
#
# Both leave the edges covered by fewer frames than the middle, which shows up
# as a band or corner of visibly worse noise. Measured on the operator's own
# C 27 stack, green-channel background noise was 4.9 in the centre and 17.4
# along the bottom edge -- before any processing ran. It is missing coverage,
# not a processing artefact.
#
# The cost of cropping to the shared area depends entirely on the cause:
# rotation is expensive, drift is cheap. So the DEFAULT is chosen per group
# rather than fixed, and the measured numbers are in FRAMING_BLURB below.
#
# Note that cropping is SELF-ADJUSTING: if the frames really do line up, the
# shared area is the whole frame and the crop costs nothing at all. That is
# what makes it safe as the default for drift.
FRAMING_WHOLE = "whole"
FRAMING_CLEAN = "clean"

FRAMING_LABELS = {
    FRAMING_WHOLE: "Keep the whole picture",
    FRAMING_CLEAN: "Every pixel equally good",
}

FRAMING_BLURB = {
    FRAMING_WHOLE: (
        "You get every pixel the camera saw. The edges are built from fewer "
        "frames than the middle, so they are noisier -- measured at nearly "
        "3 times the background noise along the worst edge of a two-night "
        "stack."
    ),
    FRAMING_CLEAN: (
        "Trims to the part of the sky every frame covers, so the whole image "
        "is equally good. Costs nothing when your frames line up. On a "
        "two-night stack where the nights were offset it cost 17% of the "
        "frame and made the noise even edge to edge. On a session that "
        "rotated 20 degrees it would cost about 80%."
    ),
}

# The Siril argument each choice becomes.
FRAMING_ARGUMENT = {
    FRAMING_WHOLE: "current",
    FRAMING_CLEAN: "min",
}


def default_framing(is_altaz: bool) -> str:
    """Pick the framing that is right for someone who never touches it.

    Rotation and drift need opposite answers, and the difference is large
    enough that one fixed default would be wrong half the time:

      drift (any EQ session, and every multi-session stack)
          Trimming is nearly free -- the frames are only offset by the
          mount's own wander -- and it removes an edge that is genuinely
          worse than the rest of the picture. Trim.

      rotation (alt-az)
          Trimming to the shared area cost 81% of a real session. Nothing is
          worth that, so keep the whole frame and say what the corners cost.

    The mount mode is read from the frames themselves, so this needs no
    guesswork. Per-frame pointing would have been a better signal but the
    DWARF does not record it -- every frame carries the same commanded
    coordinates, so the spread across 350 frames is exactly zero.
    """
    return FRAMING_WHOLE if is_altaz else FRAMING_CLEAN


@dataclass(frozen=True)
class FrameMeta:
    """What one FITS frame says about itself."""

    path: Path
    exposure: float
    gain: int
    binning: int
    filter_name: str
    camera: str
    target: str
    eq_mode: bool | None
    temperature: float | None
    date_obs: str | None


@dataclass
class LightSession:
    """One ``DWARF_RAW_...`` folder: a single run of the telescope."""

    path: Path
    target: str
    exposure: float
    gain: int
    binning: int
    filter_name: str
    camera: str
    eq_mode: bool | None

    # THE OPTICS THIS SESSION WAS ACTUALLY SHOT WITH, from its own frames.
    # The DWARF 3's two cameras are nothing alike -- 150mm at 2.0um for the
    # telephoto, 6.7mm at 2.9um for the wide -- and plate solving has to be
    # seeded with the right ones or it searches a field twenty-two times too
    # small and fails outright.
    focal_length: float = 0.0
    pixel_size: float = 0.0

    # Where the telescope said it was pointing. None when it recorded
    # nothing usable: the wide camera writes 0/0, which is an absence
    # dressed up as a coordinate and would send a solver to the wrong sky.
    pointing_ra: float | None = None
    pointing_dec: float | None = None

    frames: list[Path] = field(default_factory=list)
    started: str = ""
    temp_min: float | None = None
    temp_max: float | None = None
    shots_taken: int | None = None
    shots_stacked: int | None = None
    metadata_source: str = "folder name"
    notes: list[str] = field(default_factory=list)

    # The DWARF's own live-stacked preview of this session, if it wrote one.
    # It is the telescope's picture, not ours, and nothing downstream may
    # present it as a preview of what this tool produces.
    thumbnail: Path | None = None

    # The same picture at full size, as the DWARF's own app shows it.
    album_image: Path | None = None

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def display_target(self) -> str:
        return self.target or "(untargeted)"

    @property
    def mount_mode(self) -> str:
        """'EQ', 'alt-az', or 'unknown' -- read, never guessed."""
        if self.eq_mode is True:
            return "EQ"
        if self.eq_mode is False:
            return "alt-az"
        return "unknown"

    @property
    def compatibility_key(self) -> tuple:
        """Two sessions may be stacked together only if these all agree.

        Mount mode is in here deliberately. Alignment would actually cope
        with mixing EQ and alt-az frames -- registration solves rotation
        either way -- but an alt-az session drags its field rotation onto the
        whole stack, so adding one to a night of good EQ data quietly costs
        the entire stack its frame edges. That is a mistake someone would
        never diagnose, so the two are kept apart and the reason is shown.
        """
        return (
            self.target,
            exposure_key(self.exposure),
            self.gain,
            self.binning,
            self.filter_name,
            self.camera,
            self.mount_mode,
        )

    @property
    def label(self) -> str:
        return f"{self.started or self.path.name} - {self.frame_count} frames"

    def describe_settings(self) -> str:
        parts = [format_exposure(self.exposure), f"gain {self.gain}", f"bin {self.binning}"]
        if self.filter_name:
            parts.append(self.filter_name)
        return " / ".join(parts)


@dataclass
class DarkSet:
    """One ``DWARF_DARK/...`` folder."""

    path: Path
    exposure: float
    gain: int
    binning: int
    camera: str
    frames: list[Path] = field(default_factory=list)
    started: str = ""
    temp_min: float | None = None
    temp_max: float | None = None
    metadata_source: str = "folder name"

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def match_key(self) -> tuple:
        return (exposure_key(self.exposure), self.gain, self.binning, self.camera)

    @property
    def mean_temp(self) -> float | None:
        temps = [t for t in (self.temp_min, self.temp_max) if t is not None]
        return sum(temps) / len(temps) if temps else None

    def describe_settings(self) -> str:
        return f"{format_exposure(self.exposure)} / gain {self.gain} / bin {self.binning}"


@dataclass
class MasterDark:
    """A pre-stacked master dark the DWARF itself wrote, from CALI_FRAME.

    The filename is the only metadata: ``dark_exp_15.000000_gain_100_bin_1_
    33C_stack_10.fits``. The ``stack_N`` suffix is how many frames went into
    it, which is what decides whether it is worth using at all.
    """

    path: Path
    exposure: float
    gain: int
    binning: int
    camera: str
    stack_count: int
    temperature: float | None = None

    @property
    def match_key(self) -> tuple:
        return (exposure_key(self.exposure), self.gain, self.binning, self.camera)

    @property
    def is_usable(self) -> bool:
        return self.stack_count >= MIN_CALI_STACK_COUNT

    def describe_settings(self) -> str:
        return f"{format_exposure(self.exposure)} / gain {self.gain} / bin {self.binning}"


@dataclass
class Issue:
    """Something the user needs to know, at one of two weights."""

    level: str  # "error" blocks the build; "warning" does not
    message: str

    @property
    def is_error(self) -> bool:
        return self.level == "error"


@dataclass
class SessionGroup:
    """Sessions of one target that the user wants stacked as one image."""

    target: str
    sessions: list[LightSession] = field(default_factory=list)
    darks: list[DarkSet] = field(default_factory=list)
    # Set only when no raw dark set matched and the CALI_FRAME fallback is on.
    master_dark: MasterDark | None = None
    issues: list[Issue] = field(default_factory=list)

    @property
    def thumbnail(self) -> Path | None:
        """The DWARF's own preview for this target, from the first session
        that has one. Sessions of one target show the same sky, so any of
        them recognises it."""
        for session in self.sessions:
            if session.thumbnail is not None:
                return session.thumbnail
        return None

    @property
    def album_image(self) -> Path | None:
        """The DWARF's full-size picture of this target, if it wrote one."""
        for session in self.sessions:
            if session.album_image is not None:
                return session.album_image
        return None

    @property
    def mount_mode(self) -> str:
        return self.sessions[0].mount_mode if self.sessions else "unknown"

    @property
    def focal_length(self) -> float:
        """The focal length these frames were actually shot at, in mm.

        Sessions are only grouped together when their camera matches, so the
        first one speaks for all of them. Falls back to the telephoto, which
        is the camera almost everyone uses for a target.
        """
        for session in self.sessions:
            if session.focal_length:
                return session.focal_length
        return 150.0

    @property
    def pixel_size(self) -> float:
        """Sensor pixel pitch in microns, from the frames themselves."""
        for session in self.sessions:
            if session.pixel_size:
                return session.pixel_size
        return 2.0

    @property
    def can_plate_solve(self) -> bool:
        """Whether a solver has anywhere to start.

        Siril's near solver searches around a given position. The wide
        camera records RA/DEC of 0/0 -- an absence, not a coordinate -- so
        there is nothing to search around, and asking it to try anyway makes
        it fail and take every later step down with it.
        """
        return any(
            session.pointing_ra is not None and session.pointing_dec is not None
            for session in self.sessions
        )

    @property
    def is_altaz(self) -> bool:
        """True when the field rotates between frames.

        Only alt-az needs a framing decision: in EQ the field does not
        rotate, so there is nothing to trade away and the question should
        never be put to the user.
        """
        return self.mount_mode == "alt-az"

    @property
    def has_calibration(self) -> bool:
        return bool(self.darks) or self.master_dark is not None

    @property
    def dark_source(self) -> str:
        """One line the user can read at a glance to know what calibrated this."""
        if self.darks:
            return (
                f"Your own darks - {self.total_dark_frames} frames from "
                f"{len(self.darks)} DWARF_DARK set"
                f"{'s' if len(self.darks) > 1 else ''}"
            )
        if self.master_dark:
            return (
                f"DWARF-supplied master (CALI_FRAME) - built by the telescope "
                f"from {self.master_dark.stack_count} frames"
            )
        return "None - this stack will be uncalibrated"

    # How many darks to suggest shooting. Dark noise falls as the square
    # root of the count, so ten already removes most of it and twenty is
    # meaningfully better; beyond that the returns are small and it is
    # sky time they could have spent on the target. Ten is also what the
    # DWARF shoots by default, so it is a number they have already met.
    SUGGESTED_DARKS = 10

    @property
    def dark_recipe(self) -> tuple[str, int] | None:
        """The exact dark frames that would calibrate THIS group.

        Returned as (exposure, gain) because that is all the DWARF needs to
        be told, and because those two numbers are already on the card face
        -- which turns "you have no darks" into something they can act on
        tonight rather than a fact about their data.
        """
        if not self.sessions or self.has_calibration:
            return None
        first = self.sessions[0]
        return format_exposure(first.exposure), first.gain

    @property
    def dark_advice(self) -> str:
        """What an uncalibrated stack costs, and how to fix it. Plain English.

        Deliberately not alarming. An uncalibrated stack is a real picture
        and they have clearly been making them; this is "here is how to make
        this better", never "you did it wrong".
        """
        recipe = self.dark_recipe
        if recipe is None:
            return ""
        exposure, gain = recipe
        return (
            f"This will stack without darks. It still makes a real picture — "
            f"you just keep the sensor's own marks in it: amp glow, usually a "
            f"coloured haze in one corner, and scattered bright dots that "
            f"never move between frames.\n\n"
            f"To fix it for next time: with the lens cap ON, shoot about "
            f"{self.SUGGESTED_DARKS} darks at {exposure} and gain {gain} — the "
            f"same settings as these lights. The DWARF saves them into "
            f"DWARF_DARK, and this tool will match them to this target "
            f"automatically the next time you plug the card in. They keep "
            f"working for every future session at those settings, so it is "
            f"a few minutes once."
        )

    @property
    def display_target(self) -> str:
        """A name a person can tell apart from the others on the card.

        The DWARF records no target for some sessions -- a test run, a
        pointing check -- and calling them all "(untargeted)" produces two or
        three identical titles in the grid, which is useless. When there is
        no name, one is built from what does distinguish them: which camera
        shot it and when.
        """
        if self.target:
            return self.target
        if not self.sessions:
            return "Untitled"
        first = self.sessions[0]
        bits = ["Untitled"]
        if first.camera:
            bits.append(first.camera)
        when = first.started[:10] if first.started else ""
        if when:
            try:
                year, month, day = when.split("-")
                months = (
                    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
                )
                bits.append(f"{int(day)} {months[int(month) - 1]}")
            except (ValueError, IndexError):
                bits.append(when)
        return " · ".join(bits)

    @property
    def total_frames(self) -> int:
        return sum(session.frame_count for session in self.sessions)

    @property
    def total_dark_frames(self) -> int:
        return sum(dark.frame_count for dark in self.darks)

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.is_error]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if not issue.is_error]

    @property
    def is_buildable(self) -> bool:
        return not self.errors and bool(self.sessions)

    @property
    def integration_seconds(self) -> float:
        return sum(session.exposure * session.frame_count for session in self.sessions)

    def describe_integration(self) -> str:
        total = int(round(self.integration_seconds))
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}h {minutes:02d}m"
        if minutes:
            return f"{minutes}m {seconds:02d}s"
        return f"{seconds}s"

    def suggested_name(self) -> str:
        """A filesystem-safe stack name, e.g. ``C_27_350x15s_gain100``."""
        base = (self.target or "untargeted").replace(" ", "_")
        safe = "".join(char for char in base if char.isalnum() or char in "_-+.")
        if not self.sessions:
            return safe or "stack"
        first = self.sessions[0]
        return f"{safe}_{self.total_frames}x{format_exposure(first.exposure)}_gain{first.gain}"
