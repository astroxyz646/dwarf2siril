"""Find Siril and run a generated script through it.

Kept in the core rather than the GUI so the CLI can stack too, and so the
awkward parts -- locating the binary, quoting a path with spaces, deciding
whether a run actually succeeded -- are written once and tested once.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

# Where Siril installs itself when nobody intervenes. Checked before PATH,
# because Siril's Windows installer does not add itself to PATH and the
# overwhelmingly common case is a default install the user never thinks about.
WINDOWS_CANDIDATES = [
    Path(r"C:\Program Files\Siril\bin\siril-cli.exe"),
    Path(r"C:\Program Files\Siril\siril-cli.exe"),
    Path(r"C:\Program Files (x86)\Siril\bin\siril-cli.exe"),
]

MACOS_CANDIDATES = [
    Path("/Applications/Siril.app/Contents/MacOS/siril-cli"),
    Path("/opt/homebrew/bin/siril-cli"),
    Path("/usr/local/bin/siril-cli"),
]

LINUX_CANDIDATES = [
    Path("/usr/bin/siril-cli"),
    Path("/usr/local/bin/siril-cli"),
    Path("/snap/bin/siril-cli"),
]

# Siril reports a failed script in its log but still exits 0 in some builds,
# so the exit code alone is not enough to call a run successful.
FAILURE_MARKERS = (
    "Script execution failed",
    "Error in line",
)
SUCCESS_MARKER = "Script execution finished successfully"


class SirilNotFound(Exception):
    """Raised when no siril-cli could be located."""


@dataclass
class SirilRunResult:
    ok: bool
    exit_code: int
    output_image: Path | None = None
    error_lines: list[str] = field(default_factory=list)
    cancelled: bool = False
    # Things that went wrong but did not cost the user their stack.
    warnings: list[str] = field(default_factory=list)


def find_siril(extra: Path | str | None = None) -> Path | None:
    """Locate ``siril-cli``. Returns None rather than raising.

    Order: an explicit path the user picked, then the standard install
    location for the platform, then PATH.
    """
    if extra:
        candidate = Path(extra)
        if candidate.is_file():
            return candidate

    if sys.platform == "win32":
        candidates = WINDOWS_CANDIDATES
    elif sys.platform == "darwin":
        candidates = MACOS_CANDIDATES
    else:
        candidates = LINUX_CANDIDATES

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    for name in ("siril-cli", "siril-cli.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def run_command(script_path: Path, siril: Path | str | None = None) -> str:
    """The command line to run this script, ready to paste into a terminal.

    Always quoted: the script lives under a user-chosen output folder and
    DWARF targets are named "C 27", so a space in the path is normal here.
    """
    exe = str(siril) if siril else "siril-cli"
    return f'"{exe}" -s "{script_path}"'


def _creation_flags() -> int:
    """Keep a console window from flashing up on Windows.

    The packaged app is windowed, so a child process that opens its own
    console is a black rectangle appearing and vanishing on every run.
    """
    if sys.platform == "win32":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def stream_siril(
    script_path: Path,
    siril: Path | str | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> Iterator[str]:
    """Run Siril and yield its log a line at a time.

    Yields as it goes so a caller can show progress during a stack that runs
    for a long time. The final line yielded is a sentinel of the form
    ``__RESULT__:<exit code>`` so the caller knows how it ended without
    having to guess from the log.
    """
    exe = find_siril(siril)
    if exe is None:
        raise SirilNotFound(
            "Could not find siril-cli. Install Siril from siril.org, or point "
            "at the siril-cli executable yourself."
        )

    # Passed as a list, so the space in the path is handled by the OS rather
    # than by shell quoting we would have to get right ourselves.
    command = [str(exe), "-s", str(script_path)]

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        cwd=str(script_path.parent),
        creationflags=_creation_flags(),
    )

    cancelled = False
    try:
        assert process.stdout is not None
        for line in process.stdout:
            if should_cancel and should_cancel() and not cancelled:
                cancelled = True
                process.terminate()
                yield "\n*** Stopped at your request. ***"
                break
            line = line.rstrip("\n")
            if line:
                yield line
    finally:
        if cancelled:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        code = process.wait()
        # Closed explicitly: a run is now several Siril processes rather than
        # one, so a pipe leaked per segment adds up.
        if process.stdout is not None:
            process.stdout.close()

    yield f"__RESULT__:{-1 if cancelled else code}"


def stream_plan(
    script_path: Path,
    siril: Path | str | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> Iterator[str]:
    """Run a generated script segment by segment, and yield its log.

    THE RULE, ENFORCED HERE RATHER THAN PER-STEP: no optional step may cost
    the deliverable. Siril aborts a script on the first failed command, so
    each segment is run as its own Siril. A required segment that fails ends
    the run, because the stack is the thing being asked for. An optional
    segment that fails is reported and the next one is tried, because an
    extra is by definition something the user can live without.

    Yields the same shape as ``stream_siril``: log lines, then a final
    ``__RESULT__:<code>``. Segments that were skipped are announced in the
    log as ``__SKIPPED__:<label>:<reason>`` so the caller can tell the user
    which one, in the result rather than buried in three thousand lines.
    """
    from .pipeline import split

    exe = find_siril(siril)
    if exe is None:
        raise SirilNotFound(
            "Could not find siril-cli. Install Siril from siril.org, or point "
            "at the siril-cli executable yourself."
        )

    text = script_path.read_text(encoding="utf-8")
    preamble, segments = split(text)

    # One script per segment, written beside the original so a failure can
    # be reproduced by hand exactly as it ran.
    pieces_dir = script_path.parent / "process"
    try:
        pieces_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pieces_dir = script_path.parent

    worst = 0
    for index, segment in enumerate(segments):
        if should_cancel and should_cancel():
            yield "\n*** Stopped at your request. ***"
            yield "__RESULT__:-1"
            return

        piece = pieces_dir / f"_step_{index:02d}.ssf"
        try:
            piece.write_text(segment.script(preamble), encoding="utf-8")
        except OSError as exc:
            yield f"__SKIPPED__:{segment.label}:could not be prepared ({exc})"
            continue

        collected: list[str] = []
        code = 0
        for item in stream_siril(piece, exe, should_cancel=should_cancel):
            if item.startswith("__RESULT__:"):
                code = int(item.split(":", 1)[1])
                continue
            collected.append(item)
            yield item

        if code == -1:
            yield "__RESULT__:-1"
            return

        failed = code != 0 or any(
            marker in line for line in collected for marker in FAILURE_MARKERS
        )
        if not failed:
            continue

        if segment.optional:
            # The whole point. Say which one, and carry on with the rest.
            reason = _why(collected) or "Siril reported an error"
            yield f"__SKIPPED__:{segment.label or 'An optional step'}:{reason}"
            continue

        worst = code or 1
        yield "__RESULT__:" + str(worst)
        return

    yield "__RESULT__:" + str(worst)


def _why(lines: list[str]) -> str:
    """The most specific thing Siril said about why a step failed."""
    for line in reversed(lines):
        stripped = line.strip()
        for marker in ("failed:", "Error in line", "error:"):
            if marker in stripped:
                return stripped.split("log: ")[-1][:160]
    return ""


def interpret(lines: list[str], exit_code: int, expected_image: Path | None) -> SirilRunResult:
    """Decide whether a finished run actually worked.

    Siril's exit code is not sufficient on its own: a script that fails part
    way through still logs the failure and can exit 0. So the log is checked
    for Siril's own verdict, and where we know what file should have appeared,
    for the file.
    """
    if exit_code == -1:
        return SirilRunResult(ok=False, exit_code=exit_code, cancelled=True)

    image = expected_image if expected_image and expected_image.is_file() else None

    # A THUMBNAIL MUST NEVER COST SOMEBODY THEIR STACK.
    # Siril aborts a script on the first failed command, and savejpg fails
    # for reasons that have nothing to do with the stack -- no room on the
    # disk, a folder that is not there. The script is ordered so every .fit
    # is written before any JPEG is attempted, so if the only thing that
    # failed was a preview AND the image we were promised is on disk, the
    # run worked. The user is told the preview is missing rather than told
    # their stack failed. Same rule the display side already holds.
    # Steps the runner skipped, in the words the user should hear. These are
    # not errors: the run continued and the file was produced.
    warnings: list[str] = []
    skipped = False
    for line in lines:
        if line.startswith("__SKIPPED__:"):
            skipped = True
            _, label, reason = line.split(":", 2)
            warnings.append(
                f"{label} did not run on this image ({reason.strip()}). "
                f"Everything else did, and your stack is unaffected."
            )
    lines = [line for line in lines if not line.startswith("__SKIPPED__:")]

    # When the plan runner has already judged each segment, its verdict is
    # the authoritative one: a required failure came back non-zero, and a
    # zero means every failure in the log belonged to an optional step that
    # was skipped on purpose. Re-reading those lines and calling the run a
    # failure would undo the entire point of running the segments apart.
    if skipped and exit_code == 0 and image is not None:
        return SirilRunResult(
            ok=True, exit_code=0, output_image=image, warnings=warnings
        )

    errors = [
        line for line in lines if any(m in line for m in FAILURE_MARKERS)
    ]
    said_ok = any(SUCCESS_MARKER in line for line in lines)

    forgiven = False
    if errors and image is not None:
        if _only_preview_failed(errors):
            forgiven = True
            warnings.append(
                "The stack finished, but a preview image could not be written, "
                "so the before/after view may be missing a step. Your "
                "full-resolution result is fine."
            )
        else:
            layer = _failed_extra(errors)
            if layer:
                forgiven = True
                warnings.append(
                    f"Your stack is fine and saved. One of the optional "
                    f"extras — {layer} — could not run on this image, and "
                    f"anything after it was skipped. The plain stack is "
                    f"untouched either way."
                )
    if forgiven:
        errors = []

    # A forgiven run also exits non-zero, because Siril did abort the script.
    # The file it promised is on disk, which is the thing that matters.
    ok = (exit_code == 0 or forgiven) and not errors and (said_ok or image is not None)

    return SirilRunResult(
        ok=ok,
        exit_code=exit_code,
        output_image=image,
        error_lines=errors,
        warnings=warnings,
    )


def _failed_extra(errors: list[str]) -> str:
    """The name of the optional layer that failed, if that is all that did.

    Siril aborts a script on the first failed command, so one optional layer
    failing costs every layer after it. It must not also cost the user their
    stack: the plain .fit is written long before any of this runs, and each
    layer saves the processed file as it goes, so the work up to the failure
    is on disk and real. This is what turns "the whole thing failed" into
    "the stack is fine, this one step did not work".

    Found by an EQ wide-angle session on the operator's card, where plate
    solving could not succeed and took background removal, colour
    calibration, denoise and star reduction down with it.
    """
    layers = {
        "subsky": "background removal",
        "platesolve": "plate solving",
        "pcc": "colour calibration",
        "denoise": "denoising",
        "starnet": "star reduction",
        "pm": "star reduction",
    }
    blamed = ""
    for line in errors:
        if "Script execution failed" in line:
            continue
        for command, friendly in layers.items():
            if f"('{command}')" in line:
                blamed = friendly
                break
        else:
            return ""     # something that is not an optional layer failed
    return blamed


def _only_preview_failed(errors: list[str]) -> bool:
    """True when every reported failure is a preview being written.

    Deliberately narrow: it looks for the failing COMMAND being savejpg, not
    merely for the word appearing somewhere in the line, so a real failure
    that happens to mention a JPEG is still a failure.
    """
    blamed = False
    for line in errors:
        if "Script execution failed" in line:
            continue           # the generic follow-up to whatever failed
        if "('savejpg')" in line or "'savejpg'" in line:
            blamed = True
            continue
        return False           # something else failed too
    return blamed


def expected_output(script_path: Path, stack_name: str) -> Path:
    """Where the script's `stack ... -out=` will land the finished image."""
    return script_path.parent / f"{stack_name}.fit"
