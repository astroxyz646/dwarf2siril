"""One rule, in one place: NO OPTIONAL STEP MAY COST THE DELIVERABLE.

*** WHY THIS MODULE EXISTS ***

Siril aborts a script the instant any command fails. That is a property of
Siril, not of any particular command, so EVERY optional step inherits it.
The consequence has now been found three separate times on real data:

  * a preview JPEG failing because its folder was missing stopped every
    layer from running and produced no processed image at all;
  * a plate solve that could not succeed on wide-angle frames took
    background removal, colour calibration, denoising and star reduction
    down with it, again leaving nothing;
  * and in both cases the run was reported to the user as a failure, when
    the thing they actually asked for -- the stack -- was already on disk.

Fixing those one at a time was treating the symptom. An extra is BY
DEFINITION something the user can live without. So the pipeline, not each
step, is responsible for this:

  1. A failing optional step does not stop the run.
  2. It does not stop the OTHER optional steps either.
  3. The user is told which step did not run, in the result, in plain words.
  4. A failing REQUIRED step is still a failure. This is not "make
     everything forgiving" -- if the stack itself cannot be built, saying so
     is the only honest answer.

The mechanism is deliberately dull. The generated script carries marker
comments, and the runner splits it on them and runs each piece as its own
Siril invocation. A crashed invocation cannot take the next one with it.
The markers are ordinary comments, so the one script the user is handed to
run themselves is completely unaffected -- there is exactly one script,
which is what stops the two representations ever drifting apart.

Anything added later inherits all of this by being emitted between markers.
Nobody has to remember the rule again.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Emitted by script.py. A comment, so a human running the script by hand
# never knows it is there.
MARKER = re.compile(r"^#\s*@@SEGMENT\s+(?P<kind>required|optional)(?:\s+(?P<label>.*))?$")

REQUIRED = "required"
OPTIONAL = "optional"


@dataclass
class Segment:
    """One independently-runnable piece of the pipeline."""

    kind: str                 # REQUIRED or OPTIONAL
    label: str                # plain English, for the user
    lines: list[str] = field(default_factory=list)

    @property
    def optional(self) -> bool:
        return self.kind == OPTIONAL

    def script(self, preamble: list[str]) -> str:
        """This segment as a standalone script.

        The preamble goes in front of every one of them: each invocation is
        a fresh Siril that knows nothing, so it has to be told the working
        directory and the bit depth again. That is the entire cost of the
        arrangement.
        """
        return "\n".join([*preamble, "", *self.lines]) + "\n"

    def is_empty(self) -> bool:
        return not any(
            line.strip() and not line.strip().startswith("#") for line in self.lines
        )


def split(script_text: str) -> tuple[list[str], list[Segment]]:
    """Cut a generated script into its preamble and its segments.

    A script with no markers at all comes back as a single required
    segment, which is exactly right: an older script, or one the user wrote
    themselves, should run as one piece and be judged as one piece.
    """
    preamble: list[str] = []
    segments: list[Segment] = []
    current: Segment | None = None

    for line in script_text.splitlines():
        matched = MARKER.match(line.strip())
        if matched:
            current = Segment(
                kind=matched.group("kind"),
                label=(matched.group("label") or "").strip(),
            )
            segments.append(current)
            continue
        if current is None:
            preamble.append(line)
        else:
            current.lines.append(line)

    if not segments:
        return [], [Segment(kind=REQUIRED, label="", lines=script_text.splitlines())]

    # The preamble is the header comments plus the setup commands. Comments
    # are harmless to repeat and carry the provenance into every piece.
    return preamble, [s for s in segments if not s.is_empty()]
