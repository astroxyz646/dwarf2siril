"""Create the Siril working folder and put the frames in it.

The source card is READ-ONLY throughout. We copy or hard-link; we never move,
rename or delete anything under the source. Every write goes to the output
folder the user chose.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .deletion import describe_size
from .model import SessionGroup
from .postprocess import PostOptions
from .quality import QualityFilter
from .script import (
    DARKS_DIR,
    LIGHTS_DIR,
    MASTERS_DIR,
    PREVIEW_DIR,
    PROCESS_DIR,
    generate_script,
)

# (files done, files total, what we are doing)
ProgressFn = Callable[[int, int, str], None]
CancelFn = Callable[[], bool]


from .progress import plan_stages


class BuildCancelled(Exception):
    """Raised when the caller asked us to stop partway through."""


@dataclass
class BuildResult:
    output_dir: Path
    script_path: Path
    lights_copied: int = 0
    darks_copied: int = 0
    linked: bool = False
    # Total size of the frames this build had to place, whether they were
    # copied or linked. Held so the caller can state a fact about the size of
    # the job rather than counting files and calling that a measure of it.
    total_bytes: int = 0
    # Set when a DWARF-supplied CALI_FRAME master was used instead of raw darks.
    master_dark_source: Path | None = None
    warnings: list[str] = field(default_factory=list)
    # The stages this script will go through, weighted, so the run panel can
    # show real progress instead of an indeterminate bar. Worked out here
    # because this is where the frame counts and the chosen layers are both
    # known, before Siril has said a word.
    stages: list = field(default_factory=list)

    @property
    def total_copied(self) -> int:
        return self.lights_copied + self.darks_copied


def can_hardlink(source: Path, destination: Path) -> bool:
    """Hard links only work within one volume, and not on every filesystem.

    Worth testing rather than assuming: the whole point is to avoid copying
    several gigabytes when the user's output folder is on the same disk.
    """
    probe = destination / ".dwarf2siril_link_probe"
    try:
        source_file = next(
            (item for item in source.iterdir() if item.is_file()), None
        )
        if source_file is None:
            return False
        if probe.exists():
            probe.unlink()
        os.link(source_file, probe)
        probe.unlink()
        return True
    except (OSError, StopIteration, NotImplementedError, AttributeError):
        try:
            if probe.exists():
                probe.unlink()
        except OSError:
            pass
        return False


def _place(source: Path, destination: Path, use_links: bool) -> bool:
    """Put one frame in place. Returns True if a link was used.

    Falls back to copying whenever linking fails, so a link that turns out to
    be impossible mid-run costs speed and nothing else.
    """
    if destination.exists():
        return False
    if use_links:
        try:
            os.link(source, destination)
            return True
        except OSError:
            pass
    shutil.copy2(source, destination)
    return False


def copy_headline(frames: int, total_bytes: int) -> str:
    """What the user is about to wait for, said before the wait starts.

    Module level and not an f-string buried in the loop so that the layout
    check can measure the real sentence at the real font, rather than a
    stand-in that happens to be shorter.

    Facts only. No duration, no rate, no "about a minute": the honest units
    for a job whose speed we do not know in advance are frames and bytes.
    """
    return (
        f"Copying {frames} frames, {describe_size(total_bytes)}, from your "
        f"card. Your card is only ever read."
    )


def copy_progress(done: int, frames: int, moved: int, total_bytes: int) -> str:
    """How far through that copy we are, in both units.

    Bytes as well as frames, to the same standard as the stacking bar: frames
    vary in size, so a count alone does not tell you how much of the wait is
    left when the wait is measured in gigabytes.
    """
    return (
        f"Copying from your card — {done} of {frames} frames, "
        f"{describe_size(moved)} of {describe_size(total_bytes)}"
    )


def _unique_name(taken: set[str], preferred: str) -> str:
    """Session frames can collide by name across sessions; disambiguate.

    Real DWARF frame names carry a millisecond timestamp so collisions are
    unlikely, but two sessions of one target is exactly the case where an
    overwrite would silently lose frames.
    """
    if preferred not in taken:
        taken.add(preferred)
        return preferred
    stem, suffix = os.path.splitext(preferred)
    index = 2
    while f"{stem}_{index}{suffix}" in taken:
        index += 1
    name = f"{stem}_{index}{suffix}"
    taken.add(name)
    return name


def build(
    group: SessionGroup,
    output_dir: Path,
    stack_name: str | None = None,
    progress: ProgressFn | None = None,
    should_cancel: CancelFn | None = None,
    post: PostOptions | None = None,
    quality: QualityFilter | None = None,
    framing: str | None = None,
) -> BuildResult:
    """Build the whole working folder for one group.

    Raises ValueError if the group has blocking errors, so a mismatch caught
    in the UI cannot be built anyway by a different caller.
    """
    if group.errors:
        raise ValueError(
            "This group cannot be built:\n"
            + "\n".join(f"  - {issue.message}" for issue in group.errors)
        )
    if not group.sessions:
        raise ValueError("No sessions selected.")

    # Resolve to an absolute path before anything else. The generated script
    # embeds this in its `cd`, and Siril runs with its own current directory
    # (whatever it used last), so a relative path here fails at run time with
    # a "directory not found" that points at the script rather than at us.
    output_dir = Path(output_dir).expanduser().resolve()
    name = stack_name or group.suggested_name()

    folders = [LIGHTS_DIR, DARKS_DIR, MASTERS_DIR, PROCESS_DIR]
    if post is not None and (post.any_enabled or post.previews):
        # Siril's savejpg will not create a missing directory for itself.
        folders.append(PREVIEW_DIR)
    for folder in folders:
        (output_dir / folder).mkdir(parents=True, exist_ok=True)

    # Previews from a PREVIOUS run into this same folder must go, because a
    # run only writes the stages it actually performs. Rebuild the same target
    # with fewer layers and the old stage JPEGs survive, and the panel -- which
    # finds previews by looking for their filenames -- shows them alongside the
    # new ones as though they came from this stack. That is how "compare the
    # plain stack with the final image" came to show no difference while the
    # per-layer comparisons looked convincing: the per-layer images were real,
    # but they were a different, older stack. Deleting only the JPEGs we are
    # about to write keeps this to the previews and nothing else in the folder.
    preview_dir = output_dir / PREVIEW_DIR
    if preview_dir.is_dir():
        for stale in preview_dir.glob("*.jpg"):
            try:
                stale.unlink()
            except OSError:
                pass   # a leftover thumbnail is not worth failing the build

    lights_dir = output_dir / LIGHTS_DIR
    darks_dir = output_dir / DARKS_DIR

    # Not a preference any more, just a fact about these two paths. Linking
    # produces the same files as copying, faster and without a second copy of
    # the bytes, so it is taken whenever the volume and filesystem allow it.
    # On a DWARF card they never do: exFAT has no hard links, and a link
    # cannot cross volumes even where it did.
    use_links = can_hardlink(group.sessions[0].path, lights_dir)

    jobs: list[tuple[Path, Path, str]] = []
    light_names: set[str] = set()
    for session in group.sessions:
        for frame in session.frames:
            jobs.append((frame, lights_dir, "light"))
    dark_names: set[str] = set()
    for dark in group.darks:
        for frame in dark.frames:
            jobs.append((frame, darks_dir, "dark"))

    total = len(jobs)

    # HOW BIG IS THIS? Asked before the first byte moves, because "Prepare"
    # is followed by minutes of apparent silence and the honest answer to
    # "what have I just committed to" is a SIZE. Not a time -- a time would
    # be a guess about a card we have never measured -- but the number of
    # frames and the gigabytes are facts we already hold.
    #
    # Sized once and kept, not re-stat-ed inside the loop. Every stat is a
    # round trip to the card, and the loop already has all the card traffic
    # it needs.
    sizes: list[int] = []
    for source, _folder, _kind in jobs:
        try:
            sizes.append(source.stat().st_size)
        except OSError:
            sizes.append(0)
    total_bytes = sum(sizes)

    result = BuildResult(
        output_dir=output_dir,
        script_path=output_dir / f"{name}.ssf",
        linked=use_links,
        total_bytes=total_bytes,
    )

    # Linking is instant and needs no explanation; copying is minutes of
    # real work and does. Nobody needs to know WHICH mechanism moved their
    # files, only how much is moving and that the card is only read.
    if progress and not use_links:
        progress(0, total, copy_headline(total, total_bytes))

    moved = 0
    for index, (source, folder, kind) in enumerate(jobs, start=1):
        if should_cancel and should_cancel():
            raise BuildCancelled(f"Stopped after {index - 1} of {total} frames.")

        taken = light_names if kind == "light" else dark_names
        destination = folder / _unique_name(taken, source.name)
        try:
            _place(source, destination, use_links)
        except OSError as exc:
            result.warnings.append(f"Could not place {source.name}: {exc}")
            continue

        moved += sizes[index - 1]
        if kind == "light":
            result.lights_copied += 1
        else:
            result.darks_copied += 1

        if progress:
            if use_links:
                progress(index, total, f"Preparing frames ({index} of {total})")
            else:
                progress(
                    index, total,
                    copy_progress(index, total, moved, total_bytes),
                )

    # A DWARF-supplied master is already stacked, so it goes straight into
    # masters/ under the name the script expects. The source file on the card
    # is copied, never moved.
    if group.master_dark is not None:
        if progress:
            progress(total, total, "Copying the DWARF's master dark")
        destination = output_dir / MASTERS_DIR / "master_dark.fit"
        try:
            shutil.copy2(group.master_dark.path, destination)
            result.master_dark_source = group.master_dark.path
        except OSError as exc:
            result.warnings.append(
                f"Could not copy the DWARF master dark: {exc}. "
                f"The stack will be uncalibrated."
            )

    if progress:
        progress(total, total, "Writing Siril script")

    # Say when a layer the user ticked will not actually run. Silently
    # dropping it would be the same dishonesty as running it and failing.
    if post is not None and post.plate_solve and not group.can_plate_solve:
        skipped = ["plate solving"]
        if post.colour_calibration:
            skipped.append("colour calibration, which needs a solved image")
        result.warnings.append(
            "These frames record no pointing at all — the DWARF's wide camera "
            "writes no coordinates — so there is nothing for the solver to "
            "search around. Skipping "
            + " and ".join(skipped)
            + ". Everything else still runs."
        )

    script = generate_script(group, output_dir, name, post, quality, framing)
    result.script_path.write_text(script, encoding="utf-8")

    _write_summary(group, output_dir, result, name)

    # Only a master dark of our own gets a calibrate stage; a DWARF-supplied
    # master is already stacked, so there is no dark convert or dark stack to
    # wait for. Telling the progress bar the truth about that matters -- a
    # stage that never runs would leave a gap the bar jumps across.
    result.stages = plan_stages(
        light_count=result.lights_copied,
        dark_count=result.darks_copied,
        has_calibration=bool(result.darks_copied or result.master_dark_source),
        layers=tuple(post.siril_stages()) if post else (),
        previews=bool(post.previews) if post else True,
    )

    if progress:
        progress(total, total, "Done")
    return result


def _write_summary(
    group: SessionGroup, output_dir: Path, result: BuildResult, name: str
) -> None:
    """Drop a plain-text record beside the script.

    Six months later the user will want to know what went into a stack, and
    the source folders may be off the card by then.
    """
    lines = [
        f"Dwarf2Siril build summary: {group.display_target}",
        "=" * 60,
        "",
        f"Stack name     : {name}",
        f"Sessions       : {len(group.sessions)}",
        f"Light frames   : {result.lights_copied}",
        f"Dark frames    : {result.darks_copied}",
        f"Integration    : {group.describe_integration()}",
        f"Frames placed  : {'hard links' if result.linked else 'copies'}",
        "",
        "Sessions used",
        "-" * 60,
    ]
    for session in group.sessions:
        lines.append(f"  {session.path}")
        lines.append(
            f"    {session.frame_count} frames, {session.describe_settings()}"
            f", started {session.started or 'unknown'}"
        )
        lines.append(f"    metadata from: {session.metadata_source}")

    lines.extend(["", "Calibration", "-" * 60, f"  {group.dark_source}"])
    if group.darks:
        for dark in group.darks:
            lines.append(f"  {dark.path}")
            lines.append(f"    {dark.frame_count} frames, {dark.describe_settings()}")
    elif group.master_dark:
        lines.append(f"  {group.master_dark.path}")
        lines.append(
            f"    pre-stacked by the telescope from "
            f"{group.master_dark.stack_count} frames"
        )
    else:
        lines.append("  the stack is uncalibrated")

    if group.warnings:
        lines.extend(["", "Warnings", "-" * 60])
        for issue in group.warnings:
            lines.append(f"  - {issue.message}")

    if result.warnings:
        lines.extend(["", "Problems during build", "-" * 60])
        for warning in result.warnings:
            lines.append(f"  - {warning}")

    lines.extend(
        [
            "",
            "To run",
            "-" * 60,
            f'  siril-cli -s "{result.script_path}"',
            "",
            "The source DWARF folders were read only. Nothing was moved,",
            "renamed or deleted on the card.",
            "",
        ]
    )
    (output_dir / "build_summary.txt").write_text("\n".join(lines), encoding="utf-8")

