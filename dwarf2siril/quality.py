"""Dropping frames that clouds, wind or bad seeing ruined.

Siril already measures every frame while registering it, and its stacking and
registration commands can filter on those measurements. So this needs no
extra tool: it is a matter of asking Siril for the right filters and then
translating what it did back into English.

Which measurement means what, which is the part worth getting right:

    background level up + star count down   a cloud went through
    weighted FWHM up                        soft frame, poor seeing
    roundness down                          trailing: wind, a knock, a satellite
    will not register at all                unusable; Siril drops it itself

Note the first one: a cloud is NOT an FWHM problem. Cloud scatters light into
the background and hides stars, and a frame can be badly clouded while its
few surviving stars still look perfectly sharp. Filtering on FWHM alone would
sail straight past it.

Everything is expressed in k-sigma rather than absolute numbers. "Drop frames
more than 3 sigma from the median of this session" adapts to the night it is
given; "drop frames with FWHM over 4 arcsec" is a number that is wrong on
every night except the one it was tuned for. It is also inherently
conservative: by construction only outliers go, so a normal session loses
nothing much.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# One control, four settings, rather than four numeric fields nobody wants to
# tune. The number is the k in k-sigma: bigger keeps more.
STRENGTHS = {
    "off": None,
    "gentle": 4.0,
    "balanced": 3.0,
    "strict": 2.0,
}

DEFAULT_STRENGTH = "balanced"

STRENGTH_BLURB = {
    "gentle": "Only throws away frames that are obviously ruined.",
    "balanced": "Drops clouded, trailed and soft frames. A good default.",
    "strict": "Keeps only the better frames. Use when you have plenty.",
}

# If a filter would take out more than this share of a session, something is
# wrong with the data or the setting, and quietly handing back a stack of
# four frames would be worse than saying so.
ALARM_KEPT_FRACTION = 0.6


@dataclass
class QualityFilter:
    """How aggressively to drop bad frames. On by default, and gentle."""

    enabled: bool = True
    strength: str = DEFAULT_STRENGTH

    @property
    def k(self) -> float | None:
        return STRENGTHS.get(self.strength)

    @property
    def active(self) -> bool:
        return self.enabled and self.k is not None

    def describe(self) -> str:
        if not self.active:
            return "Off - every frame is stacked."
        return STRENGTH_BLURB.get(self.strength, "")

    def filter_arguments(self) -> list[str]:
        """The -filter-* arguments for seqapplyreg.

        Each maps to a fault the user would recognise:
          wfwhm    soft frames (weighted, so it accounts for star count too)
          round    trailed frames
          bkg      frames with a raised background: cloud, moon, headlights
          nbstars  frames that lost their stars: cloud
        """
        if not self.active:
            return []
        k = self.k
        return [
            f"-filter-wfwhm={k:g}k",
            f"-filter-round={k:g}k",
            f"-filter-bkg={k:g}k",
            f"-filter-nbstars={k:g}k",
        ]


# All of these are matched against wording taken from a real Siril 1.4.4 run,
# not from documentation. Siril summarises the whole filter in one sentence:
#
#   "Processing images of the sequence with a weighted FWHM lower or equal
#    than 11.447 (286), processing images ... roundness higher or equal than
#    0.726814 (285), ... background lower or equal than 0.000870093 (299),
#    ... number of stars higher or equal than 198 (292), for a total of
#    images processed of 280)"
#
# so each criterion's surviving count is in brackets after its threshold.
CRITERION_PATTERNS = [
    ("soft", re.compile(r"weighted FWHM lower or equal than [\d.eE+-]+ \((\d+)\)")),
    ("trailed", re.compile(r"roundness higher or equal than [\d.eE+-]+ \((\d+)\)")),
    ("skyglow", re.compile(r"background lower or equal than [\d.eE+-]+ \((\d+)\)")),
    ("cloud", re.compile(r"number of stars higher or equal than [\d.eE+-]+ \((\d+)\)")),
]

# "for a total of images processed of 280)"
TOTAL_KEPT = re.compile(r"for a total of images processed of (\d+)")

# "Using selected images filter (303/350 of the sequence)" -- how many frames
# Siril could register at all, out of how many it was given.
REGISTERED_LINE = re.compile(r"selected images filter \((\d+)/(\d+) of the sequence\)")

# "Integration of 280 images on 280 of the sequence:" -- what actually got
# stacked. Note the second number is the size of the FILTERED sequence, not
# the original, which is why the true total is passed in by the caller.
INTEGRATION_LINE = re.compile(r"Integration of (?P<used>\d+) images? on \d+ of the sequence")

# How each criterion reads to a person. Deliberately not "wFWHM 11.4".
FAULT_WORDS = {
    "soft": "soft or out of focus",
    "trailed": "trailed - wind, a knock, or a satellite",
    "skyglow": "washed out by sky glow or moonlight",
    "cloud": "clouded - the stars went missing",
}


@dataclass
class FrameReport:
    """What actually got stacked, and what did not."""

    used: int = 0
    total: int = 0
    reasons: list[str] = field(default_factory=list)
    unregistered: int = 0

    @property
    def dropped(self) -> int:
        return max(0, self.total - self.used)

    @property
    def filtered(self) -> int:
        """Dropped on quality, as opposed to never registering at all."""
        return max(0, self.dropped - self.unregistered)

    @property
    def kept_fraction(self) -> float:
        return self.used / self.total if self.total else 1.0

    @property
    def looks_wrong(self) -> bool:
        """True when so much was dropped that a human should look at it."""
        return self.total > 0 and self.kept_fraction < ALARM_KEPT_FRACTION

    def summary(self) -> str:
        if not self.total:
            return ""
        if not self.dropped:
            return f"All {self.total} frames were good enough to stack."
        return f"{self.used} of {self.total} frames stacked - {self.dropped} dropped."

    def detail(self) -> list[str]:
        """Why, in plain English, with the overlap stated rather than hidden."""
        lines: list[str] = []
        if self.unregistered:
            lines.append(
                f"{self.unregistered} could not be aligned at all - usually "
                f"thick cloud or bad trailing."
            )
        if self.reasons:
            faults = ", ".join(self.reasons)
            lines.append(f"{self.filtered} failed quality checks: {faults}.")
            if len(self.reasons) > 1:
                lines.append("A frame often fails more than one check, so those overlap.")
        return lines


def parse_log(lines: list[str], total_frames: int = 0) -> FrameReport:
    """Work out from Siril's log what it stacked, and why the rest went.

    ``total_frames`` is the true number of light frames, which the caller
    knows for certain. It is passed in rather than parsed because the counts
    Siril prints after filtering refer to the already-filtered sequence, so
    reading the total from there would report "280 of 280" on a run that
    started with 350.

    Best effort by design: if a future Siril rewords its log the counts come
    back empty and the stack is still reported as the success it was. An
    unexplained drop is a missing explanation, never a failed run.
    """
    report = FrameReport(total=total_frames)
    text = "\n".join(lines)

    registered: int | None = None
    match = REGISTERED_LINE.search(text)
    if match:
        registered = int(match.group(1))
        if not report.total:
            report.total = int(match.group(2))
        report.unregistered = max(0, report.total - registered)

    # The last integration line is the lights; an earlier one is the master
    # dark, which is not what we are reporting on.
    used = [int(m.group("used")) for m in INTEGRATION_LINE.finditer(text)]
    if used:
        report.used = used[-1]

    kept = TOTAL_KEPT.search(text)
    if kept:
        report.used = int(kept.group(1))

    # Per-criterion survivors, measured against the frames that were
    # measurable at all.
    baseline = registered if registered is not None else report.total
    if baseline:
        counts: list[tuple[str, int]] = []
        for key, pattern in CRITERION_PATTERNS:
            found = pattern.search(text)
            if found:
                removed = baseline - int(found.group(1))
                if removed > 0:
                    counts.append((key, removed))
        counts.sort(key=lambda item: item[1], reverse=True)
        report.reasons = [f"{n} {FAULT_WORDS[key]}" for key, n in counts]

    return report
