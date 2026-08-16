"""Optional layers applied to the final stacked image, and the tools they need.

Everything here is OFF by default. With nothing ticked the output is exactly
the plain stack it has always been.

What Siril 1.4.4 can do on its own, checked against the real binary rather
than the documentation:

======================  ========  ==================================
Layer                   Native?   How
======================  ========  ==================================
Background removal      yes       ``subsky -rbf``
Denoise                 yes       ``denoise``
Plate solve             yes       ``platesolve``, local Gaia catalogue
Colour calibration      yes       ``pcc``, needs the internet
Star reduction          NO        ``starnet``, needs StarNet2 installed
======================  ========  ==================================

Only star reduction needs anything fetched. The rest ship with Siril.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Where we look for helper tools, in order. G:\Astronomy\bin is where this
# operator keeps them; it is one candidate among several, never the only one,
# and a machine without that drive just falls through to the next.
EXTRA_TOOL_DIRS = [
    Path(r"G:\Astronomy\bin"),
    Path(r"C:\Program Files\StarNet2\bin"),
    Path(r"C:\Program Files\StarNet"),
]

STARNET_NAMES = ["starnet2.exe", "starnet++.exe", "starnet2", "starnet++"]

STARNET_URL = "https://www.starnetastro.com/download/"

# Remembered manual picks. Kept beside the user's other app settings rather
# than in the repo, so it survives a rebuild of the exe.
def settings_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "Dwarf2Siril" / "settings.json"


def load_settings() -> dict:
    try:
        with open(settings_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_setting(key: str, value) -> None:
    data = load_settings()
    data[key] = value
    try:
        settings_path().parent.mkdir(parents=True, exist_ok=True)
        with open(settings_path(), "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
    except OSError:
        pass  # a preference we could not save is not worth failing over


@dataclass
class ToolStatus:
    """Whether a helper tool is available, and where it came from."""

    name: str
    path: Path | None
    found_in: str = ""
    download_url: str = ""
    enables: str = ""

    @property
    def available(self) -> bool:
        return self.path is not None

    def describe(self) -> str:
        if self.available:
            return f"{self.name} found in {self.found_in}"
        return f"{self.name} is not installed"


def _siril_configured_starnet() -> Path | None:
    """Ask Siril where its StarNet is, since it has a setting for exactly this."""
    from .siril import find_siril

    siril = find_siril()
    if siril is None:
        return None
    try:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "get.ssf"
            script.write_text(
                "requires 1.4.0\nget core.starnet_exe\n", encoding="utf-8"
            )
            result = subprocess.run(
                [str(siril), "-s", str(script)],
                capture_output=True,
                text=True,
                timeout=60,
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if sys.platform == "win32"
                    else 0
                ),
            )
        for line in result.stdout.splitlines():
            if "core.starnet_exe" in line and "=" in line:
                value = line.split("=", 1)[1].strip()
                # Siril prints "(not set)" when it has no value.
                if value and "not set" not in value:
                    candidate = Path(value.split(" (")[0].strip())
                    if candidate.is_file():
                        return candidate
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return None


def find_starnet(remembered: Path | str | None = None) -> ToolStatus:
    """Find StarNet2, wherever it happens to live.

    Order: a path the user picked before, Siril's own setting, the folders we
    know about, then PATH. Never raises -- "not installed" is a normal state
    that the UI explains rather than an error.
    """
    status = ToolStatus(
        name="StarNet2",
        path=None,
        download_url=STARNET_URL,
        enables="star reduction",
    )

    if remembered:
        candidate = Path(remembered)
        if candidate.is_file():
            status.path = candidate
            status.found_in = "the location you chose"
            return status

    stored = load_settings().get("starnet_path")
    if stored and Path(stored).is_file():
        status.path = Path(stored)
        status.found_in = "the location you chose"
        return status

    configured = _siril_configured_starnet()
    if configured is not None:
        status.path = configured
        status.found_in = "Siril's own settings"
        return status

    for folder in EXTRA_TOOL_DIRS:
        for name in STARNET_NAMES:
            for candidate in (folder / name, folder / "starnet2" / name):
                try:
                    if candidate.is_file():
                        status.path = candidate
                        status.found_in = str(candidate.parent)
                        return status
                except OSError:
                    continue

    for name in STARNET_NAMES:
        found = shutil.which(name)
        if found:
            status.path = Path(found)
            status.found_in = "PATH"
            return status

    return status


@dataclass
class PostOptions:
    """Which optional layers to apply. Everything defaults to off."""

    background_removal: bool = False
    denoise: bool = False
    plate_solve: bool = False
    colour_calibration: bool = False
    star_reduction: bool = False
    stretch: bool = False

    # How much of the star layer to put back. 1.0 would be no reduction at
    # all; 0.0 would remove the stars entirely. Half is the usual starting
    # point for "smaller stars, still a star field".
    star_amount: float = 0.5

    # Where StarNet is, if star reduction is on.
    starnet_path: Path | None = None

    # Before/after snapshots for the preview. Cheap, and they make the whole
    # thing inspectable without the app.
    previews: bool = True

    @property
    def any_enabled(self) -> bool:
        return any(
            (
                self.background_removal,
                self.denoise,
                self.plate_solve,
                self.colour_calibration,
                self.star_reduction,
                self.stretch,
            )
        )

    def enabled_labels(self) -> list[str]:
        labels = []
        if self.background_removal:
            labels.append("background removal")
        if self.plate_solve:
            labels.append("plate solve")
        if self.colour_calibration:
            labels.append("colour calibration")
        if self.denoise:
            labels.append("denoise")
        if self.star_reduction:
            labels.append(f"star reduction ({int(self.star_amount * 100)}% stars kept)")
        if self.stretch:
            labels.append("stretch")
        return labels

    def expected_previews(self, solvable: bool = True) -> list[tuple[str, str, str]]:
        """Every ticked layer, the preview it should produce, and why not.

        Returns ``(stage key, what the user ticked, why there is no preview)``
        for each enabled layer, with an empty reason when the layer really is
        expected to leave a picture behind.

        THIS EXISTS SO THE BEFORE/AFTER PANEL CAN STOP GUESSING. The panel
        used to work out what to show by listing the JPEGs on disk, and work
        out what to claim by listing the ticked boxes, and nothing compared
        the two. A layer that produced no preview was therefore named in
        "Applied:" and absent from the dropdowns, with no word about why --
        which reads as the layer having quietly done nothing.

        The reasons are the same ones the script itself writes into its
        comments, said in the user's words rather than Siril's. Kept here,
        beside the options that cause them, so the panel and the script
        cannot drift into disagreeing about what a run was supposed to do.
        """
        no_pointing = (
            "these frames record no pointing at all -- the wide camera "
            "writes zero for the coordinates, which is an absence rather "
            "than a position -- so there was nothing to seed a solve with"
        )
        expected: list[tuple[str, str, str]] = []
        if self.background_removal:
            expected.append(("01_background", "Remove background gradient", ""))
        if self.plate_solve:
            expected.append(
                ("02_solved", "Plate solve", "" if solvable else no_pointing)
            )
        if self.colour_calibration:
            expected.append(
                (
                    "03_colour",
                    "Photometric colour calibration",
                    ""
                    if solvable
                    else "it sets the colour from the measured brightness of "
                    "known stars, so it needs the image solved first, and "
                    "this one could not be",
                )
            )
        if self.denoise:
            expected.append(("04_denoised", "Denoise", ""))
        if self.star_reduction:
            expected.append(("05_stars_reduced", "Reduce stars", ""))
        if self.stretch:
            # No stage of its own, by design rather than by failure: it runs
            # last and what it produces IS the final image. Listed anyway,
            # because "ticked and not in the list" is the exact thing that
            # needs explaining, and silence is what caused the confusion.
            expected.append(
                (
                    "",
                    "Stretch it into a picture",
                    "it runs last, so what it produced is the Final image "
                    "itself rather than a step before it",
                )
            )
        return expected

    def siril_stages(self) -> list[str]:
        """The Siril commands these layers will produce, in script order.

        For the progress bar, which needs to know what is coming before the
        run starts. The order mirrors script.py and is not arbitrary --
        colour calibration has to follow plate solving, and the stars can
        only be put back after they have been taken out.
        """
        stages = []
        if self.background_removal:
            stages.append("subsky")
        if self.plate_solve:
            stages.append("platesolve")
        if self.colour_calibration:
            stages.append("pcc")
        if self.denoise:
            stages.append("denoise")
        if self.star_reduction:
            stages.append("starnet")
            stages.append("pm")
        if self.stretch:
            stages.append("autostretch")
        return stages

    def resolve(self) -> list[str]:
        """Drop any layer whose tool is missing. Returns what was dropped.

        A missing tool must never fail the stack -- the layer is skipped and
        the user is told why.
        """
        skipped: list[str] = []
        if self.star_reduction:
            status = find_starnet(self.starnet_path)
            if not status.available:
                self.star_reduction = False
                skipped.append(
                    "Star reduction was skipped: StarNet2 is not installed. "
                    f"Get it from {STARNET_URL} and point the app at it."
                )
            else:
                self.starnet_path = status.path

        if self.colour_calibration and not self.plate_solve:
            # pcc needs the image solved first. Turning solving on quietly is
            # friendlier than refusing, and it is what the user meant.
            self.plate_solve = True
            skipped.append(
                "Colour calibration needs the image plate solved, so plate "
                "solving was switched on too."
            )
        return skipped
