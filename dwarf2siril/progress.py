"""Turn Siril's log into an honest progress bar.

A 350-frame stack runs for a long time, and an indeterminate bar for all of
it says nothing -- worst of all, it cannot tell "working" from "hung". Siril
does report progress; it just reports it per stage, in among several thousand
other lines. This reads it.

WHAT SIRIL ACTUALLY EMITS (read off a real 350-frame run, not from docs):

    log: Running command: calibrate
    progress: Converting files, 43.00%
    progress: Preprocessing. Processing image 187 (light_00187.fit), 17.98%
    progress: 61.43%

So there are three shapes, all with a percentage, and a ``Running command``
line marking every stage boundary. That is enough for real progress, with
two things this module has to add:

* WHICH stage a percentage belongs to. ``convert`` and ``stack`` each appear
  twice in our scripts -- once for the darks, once for the lights -- so the
  command name alone is ambiguous. The plan is therefore built up front from
  what the builder already knows, and matching only ever moves FORWARD
  through it.

* WHAT EACH STAGE IS WORTH. They are nowhere near equal: a master dark from
  10 frames is under half a second, and stacking 350 is minutes. Weighting
  them equally would park the bar at 90% for most of the run, which is worse
  than not having one.

Three rules this module will not break:

1. It never goes backwards.
2. It never reaches 100% before the run has actually finished.
3. A stage with no progress signal at all -- StarNet, denoise, plate solving
   -- says so and goes indeterminate FOR THAT STAGE. A made-up number is
   worse than an honest spinner.

If Siril's output ever changes shape, the parser stops recognising lines and
the bar falls back to indeterminate. It degrades; it does not break.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ``progress:`` lines, most specific first. The image number is worth having
# separately -- "142 of 350" tells someone far more than "47%".
_IMAGE = re.compile(
    r"progress:\s*(?P<what>.*?)\.?\s*Processing image\s+(?P<n>\d+)\s*"
    r"\([^)]*\),\s*(?P<pct>[\d.]+)\s*%"
)
_LABELLED = re.compile(r"progress:\s*(?P<what>.+?),\s*(?P<pct>[\d.]+)\s*%")
_BARE = re.compile(r"progress:\s*(?P<pct>[\d.]+)\s*%")
_COMMAND = re.compile(r"Running command:\s*(?P<name>\w+)")

# Siril's own verdict. Until this shows up the run is not finished, whatever
# the arithmetic says.
_FINISHED = "Script execution finished successfully"


@dataclass
class Stage:
    """One step of the run, as the user should hear about it."""

    command: str            # the Siril command that starts it
    label: str              # plain English. No Siril command names, ever.
    weight: float           # share of a whole run, by measured time
    counts: bool = False    # does it report "image N of total"?
    determinate: bool = True


@dataclass
class Update:
    """What the window should show right now."""

    fraction: float         # 0.0 - 1.0 across the WHOLE run
    label: str              # stage name, with counts where we have them
    determinate: bool


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------
#
# WEIGHTS ARE MEASURED, NOT GUESSED. From a real 350-light / 10-dark C 27 run
# at 3840x2160 on 16 cores -- wall-clock seconds between the "Running
# command" lines in the log of that run:
#
#     darks: convert                0.05s     negligible
#     darks: stack                  0.42s     negligible
#     lights: convert               0.36s     negligible
#     calibrate                   167.4s      56%
#     register -2pass              35.6s      12%
#     seqapplyreg                  55.7s      19%
#     stack                        37.4s      13%
#     previews                      0.4s      negligible
#                                 ------
#                                 297.3s
#
# Worth stating plainly because it is not what you would guess: CALIBRATION
# is the long pole, not stacking and not registration. It reads, debayers and
# rewrites all 350 full-size frames; the two-pass register only measures them
# and writes nothing, which is why it is four times quicker.
#
# Those four stages are 99% of the run, which is why the trivial ones get a
# floor rather than a share: a stage worth 0.1% of the bar may as well not
# move it, but it should still be NAMED, because seeing "Building the master
# dark" flash past is how you know it happened.

_MEASURED = {
    "calibrate": 167.4,
    "register": 35.6,
    "seqapplyreg": 55.7,
    "stack": 37.4,
}
_TOTAL_MEASURED = sum(_MEASURED.values())

# What the quick stages are worth. Small, equal, and honest: they really are
# this cheap.
_TRIVIAL = 0.004

# Layers run once on one image rather than once per frame, so they scale with
# image size, not frame count. Measured on the same 3840x2160 stack.
_LAYER_WEIGHT = {
    "subsky": 0.02,
    "platesolve": 0.02,
    "pcc": 0.02,
    "denoise": 0.10,      # NL-Bayes on a 4K frame is not quick
    "starnet": 0.12,
    "pm": 0.01,
}

_LAYER_LABEL = {
    "subsky": "Removing the background gradient",
    "platesolve": "Working out where this is pointing",
    "pcc": "Setting the colour from known stars",
    "denoise": "Reducing the noise",
    "starnet": "Separating the stars from the rest",
    "pm": "Putting the stars back, smaller",
}


def plan_stages(
    light_count: int,
    dark_count: int = 0,
    has_calibration: bool | None = None,
    layers: tuple[str, ...] = (),
    previews: bool = True,
) -> list[Stage]:
    """The stages this run will go through, in order, already weighted.

    Built from what the builder knows before Siril starts, which is what
    makes the duplicated command names unambiguous: two ``convert``s and two
    ``stack``s, told apart by their position rather than by their text.

    ``dark_count`` is raw dark frames of the user's own, which have to be
    converted and stacked into a master first. ``has_calibration`` is the
    broader question of whether the lights get calibrated at all -- true as
    well when the DWARF's own ready-made master dark is being used, where
    there is no dark stage to wait for but there is still a calibrate.
    """
    if has_calibration is None:
        has_calibration = bool(dark_count)
    stages: list[Stage] = []

    if dark_count:
        stages.append(Stage("convert", "Preparing your dark frames", _TRIVIAL))
        stages.append(Stage("stack", "Building the master dark", _TRIVIAL))

    stages.append(Stage("convert", "Preparing your light frames", _TRIVIAL))

    if has_calibration:
        stages.append(
            Stage(
                "calibrate",
                "Subtracting the darks from every frame",
                _MEASURED["calibrate"] / _TOTAL_MEASURED,
                counts=True,
            )
        )
    stages.append(
        Stage(
            "register",
            "Measuring and aligning frames",
            _MEASURED["register"] / _TOTAL_MEASURED,
            counts=True,
        )
    )
    stages.append(
        Stage(
            "seqapplyreg",
            "Saving the aligned frames",
            _MEASURED["seqapplyreg"] / _TOTAL_MEASURED,
            counts=True,
        )
    )
    stages.append(
        Stage(
            "stack",
            "Combining every frame into one image",
            _MEASURED["stack"] / _TOTAL_MEASURED,
            counts=True,
        )
    )

    for layer in layers:
        stages.append(
            Stage(
                layer,
                _LAYER_LABEL.get(layer, "Working on the image"),
                _LAYER_WEIGHT.get(layer, 0.02),
                # None of these report progress at all. Saying so is the
                # honest answer; a fabricated number is not.
                determinate=False,
            )
        )

    if previews:
        stages.append(Stage("savejpg", "Saving the previews", _TRIVIAL))

    total = sum(stage.weight for stage in stages) or 1.0
    for stage in stages:
        stage.weight /= total
    return stages


class RunProgress:
    """Feed it Siril's log lines; it tells you what the bar should say."""

    def __init__(self, stages: list[Stage], total_frames: int = 0) -> None:
        self._stages = stages
        self._total_frames = total_frames
        self._index = -1
        self._within = 0.0
        self._image = 0
        self._done = 0
        self._fraction = 0.0
        # A freshly entered stage is not believed until it reports
        # something other than 'finished' -- see _advance.
        self._primed = False
        self._finished = False
        # Once nothing has been recognised for a long stretch we stop
        # claiming to know, rather than showing a bar frozen at some number.
        self._unmatched = 0

    # -- reading ---------------------------------------------------------

    def feed(self, line: str) -> Update | None:
        """Take one log line. Returns an Update only when something changed."""
        if _FINISHED in line:
            self._finished = True
            self._fraction = 1.0
            return Update(1.0, "Finished", True)

        command = _COMMAND.search(line)
        if command:
            return self._enter(command.group("name"))

        if "progress:" not in line:
            return None

        matched = _IMAGE.search(line)
        if matched:
            # COUNT the images, do not report Siril's image NUMBER. With 16
            # threads the frames finish out of order, so the number jumps
            # about -- a real run went "333 of 350" and then "22 of 350",
            # which reads as the thing having gone wrong. The count of lines
            # seen only ever goes up, and is the honest answer to "how many
            # are done".
            self._done += 1
            self._image = self._done
            return self._advance(float(matched.group("pct")))

        matched = _LABELLED.search(line) or _BARE.search(line)
        if matched:
            return self._advance(float(matched.group("pct")))
        return None

    # -- state -----------------------------------------------------------

    def _enter(self, command: str) -> Update | None:
        """Move to the next stage that expects this command. Forward only."""
        for offset in range(self._index + 1, len(self._stages)):
            if self._stages[offset].command == command:
                # Everything skipped over is finished, by definition: Siril
                # runs our script top to bottom.
                self._index = offset
                self._within = 0.0
                self._image = 0
                self._done = 0
                self._primed = False
                self._unmatched = 0
                return self._emit()
        return None

    def _advance(self, percent: float) -> Update | None:
        if self._index < 0:
            return None

        # *** THE ONE THAT ACTUALLY BIT ***
        # Siril emits the PREVIOUS operation's closing "progress: 100.00%"
        # AFTER printing the next "Running command" line:
        #
        #     progress: , 100.00%
        #     log: Running command: calibrate
        #     progress: 100.00%      <- still the convert talking
        #     progress: 100.00%
        #     progress: 0.00%        <- calibrate actually starting
        #
        # Taken at face value that slams the new stage to 100% on its first
        # line, and then every real reading looks like going backwards and is
        # refused. Replaying a genuine 350-frame run, the bar jumped to 57%
        # at one second in and then STOOD STILL FOR 168 SECONDS.
        #
        # So a stage is not believed until it has reported something that is
        # not "finished". Nothing else needs to change: the stray lines are
        # always 100%, and a stage that legitimately finishes reports 100%
        # after it has already reported something lower.
        if not self._primed:
            if percent >= 99.9:
                return None
            self._primed = True

        within = max(0.0, min(100.0, percent)) / 100.0
        if within < self._within:
            # Registration measures in one pass and transforms in another,
            # each counting 0-100. Never let the second pass pull the bar
            # backwards.
            return None
        self._within = within
        return self._emit()

    def _emit(self) -> Update:
        stage = self._stages[self._index]
        done = sum(s.weight for s in self._stages[: self._index])
        fraction = done + stage.weight * self._within

        # Rule 1: never backwards. Rule 2: never 100% before it is over.
        fraction = max(self._fraction, min(fraction, 0.99))
        self._fraction = fraction

        label = stage.label
        if stage.counts and self._total_frames and self._image:
            label = f"{label} — {min(self._image, self._total_frames)} "
            label += f"of {self._total_frames}"

        # A stage that has reported 100% is not finished -- Siril still has
        # to write the result, and on a 350-frame stack that write is half a
        # minute during which it says nothing at all. Freezing a determinate
        # bar there is exactly the "stuck at 99%" the bar exists to avoid, so
        # this hands back an honest sweep instead of a still number.
        determinate = stage.determinate and self._within < 1.0
        if stage.determinate and not determinate:
            label = f"{label} — writing the result"
        return Update(fraction, label, determinate)

    @property
    def fraction(self) -> float:
        return self._fraction

    @property
    def finished(self) -> bool:
        return self._finished
