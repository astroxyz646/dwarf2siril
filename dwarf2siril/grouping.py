"""Decide what may be stacked with what, and which darks calibrate it.

The rule the brief asks for: refuse to merge sessions that disagree, and say
which field disagrees. So every rejection here names the field and both values
-- "won't stack" on its own is not an answer the user can act on.
"""

from __future__ import annotations

from .model import (
    MIN_CALI_STACK_COUNT,
    TEMP_WARN_DELTA_C,
    DarkSet,
    Issue,
    LightSession,
    MasterDark,
    SessionGroup,
    exposure_key,
    format_exposure,
)

# The fields that must agree, in the order we report them. Each entry is
# (label, how to read it off a session, how to render it for the user).
COMPATIBILITY_FIELDS: list[tuple[str, callable, callable]] = [
    ("target", lambda s: s.target, lambda v: v or "(untargeted)"),
    ("exposure", lambda s: exposure_key(s.exposure), format_exposure),
    ("gain", lambda s: s.gain, lambda v: str(v)),
    ("binning", lambda s: s.binning, lambda v: f"{v}x{v}"),
    ("IR filter", lambda s: s.filter_name, lambda v: v or "(none)"),
    ("camera", lambda s: s.camera, lambda v: v or "(unknown)"),
    ("mount mode", lambda s: s.mount_mode, lambda v: v),
]


def check_compatibility(sessions: list[LightSession]) -> list[Issue]:
    """Every reason this set of sessions cannot become one stack."""
    issues: list[Issue] = []
    if not sessions:
        return [Issue("error", "No sessions selected.")]

    first = sessions[0]
    for label, get, render in COMPATIBILITY_FIELDS:
        baseline = get(first)
        for other in sessions[1:]:
            value = get(other)
            if value != baseline:
                issues.append(
                    Issue(
                        "error",
                        f"{label} differs: {first.path.name} has "
                        f"{render(baseline)}, {other.path.name} has {render(value)}. "
                        f"These cannot be stacked together.",
                    )
                )
                break  # one report per field is enough to act on

    # Alt-az stacks perfectly well -- Siril's registration solves rotation as
    # well as shift -- so this is a note about the trade, not a refusal. What
    # rotation costs is the frame edges, which is a framing choice made
    # further down. Mixing EQ and alt-az is prevented by the compatibility
    # key rather than here, so the two never reach this function together.
    if sessions and sessions[0].mount_mode == "alt-az":
        issues.append(
            Issue(
                "warning",
                "Shot in alt-az, so the field rotates between frames. This "
                "stacks fine -- alignment corrects the rotation -- but the "
                "corners end up built from fewer frames than the middle, and "
                "are slightly noisier. On a wedge, in EQ mode, the whole "
                "frame would be equally good.",
            )
        )

    for session in sessions:
        if session.eq_mode is None:
            issues.append(
                Issue(
                    "warning",
                    f"{session.path.name} does not record whether it was EQ "
                    f"or alt-az, so it is treated as its own group rather "
                    f"than being merged with either.",
                )
            )

    if not first.target:
        issues.append(
            Issue(
                "warning",
                "These sessions have no target name recorded. Grouping is by "
                "settings alone -- confirm they really are the same object.",
            )
        )

    for session in sessions:
        for note in session.notes:
            issues.append(Issue("warning", f"{session.path.name}: {note}"))

    return issues


def match_darks(sessions: list[LightSession], darks: list[DarkSet]) -> tuple[list[DarkSet], list[Issue]]:
    """Find the dark sets that calibrate these lights.

    Matched on exposure, gain and binning -- the three things that determine
    dark current and its offset. Sensor temperature deliberately is NOT part
    of the key: the DWARF 3 is uncooled and drifts several degrees inside one
    session, so an exact-temperature rule would reject everything. A large gap
    is worth telling the user about, so it becomes a warning.
    """
    issues: list[Issue] = []
    if not sessions:
        return [], issues

    reference = sessions[0]
    wanted = (exposure_key(reference.exposure), reference.gain, reference.binning)

    matched = [
        dark
        for dark in darks
        if (exposure_key(dark.exposure), dark.gain, dark.binning) == wanted
        and dark.camera == reference.camera
    ]

    if not matched:
        return [], issues

    total_frames = sum(dark.frame_count for dark in matched)
    if total_frames < 5:
        issues.append(
            Issue(
                "warning",
                f"Only {total_frames} dark frames matched. A master dark from "
                f"so few frames adds noise of its own; 15-20 is a better set.",
            )
        )

    light_temps = [t for s in sessions for t in (s.temp_min, s.temp_max) if t is not None]
    dark_temps = [t for d in matched for t in (d.temp_min, d.temp_max) if t is not None]
    if light_temps and dark_temps:
        light_mean = sum(light_temps) / len(light_temps)
        dark_mean = sum(dark_temps) / len(dark_temps)
        delta = abs(light_mean - dark_mean)
        if delta >= TEMP_WARN_DELTA_C:
            issues.append(
                Issue(
                    "warning",
                    f"Darks average {dark_mean:.0f}C but the lights average "
                    f"{light_mean:.0f}C, a {delta:.0f}C gap. Dark current "
                    f"roughly doubles every 6-7C, so calibration will be "
                    f"imperfect. Usable, but darks shot near the lights are better.",
                )
            )

    return matched, issues


def match_cali_master(
    sessions: list[LightSession], masters: list[MasterDark]
) -> tuple[MasterDark | None, list[Issue]]:
    """Find a usable DWARF-supplied master dark for these lights.

    Only ever consulted when no raw dark set matched. A master built from too
    few frames is rejected outright and explained, rather than being used
    quietly: subtracting a one-frame "master" adds noise instead of removing it.
    """
    issues: list[Issue] = []
    if not sessions or not masters:
        return None, issues

    reference = sessions[0]
    wanted = (exposure_key(reference.exposure), reference.gain, reference.binning)
    candidates = [
        master
        for master in masters
        if (exposure_key(master.exposure), master.gain, master.binning) == wanted
        and master.camera == reference.camera
    ]
    if not candidates:
        return None, issues

    # Deepest stack wins; it is the one with the least noise of its own.
    candidates.sort(key=lambda master: master.stack_count, reverse=True)
    best = candidates[0]

    if not best.is_usable:
        issues.append(
            Issue(
                "warning",
                f"The DWARF's own master dark for these settings was built "
                f"from only {best.stack_count} frame"
                f"{'s' if best.stack_count != 1 else ''} "
                f"({best.path.name}), below the {MIN_CALI_STACK_COUNT}-frame "
                f"minimum. Using it would add more noise than it removes, so "
                f"it has been rejected.",
            )
        )
        return None, issues

    issues.append(
        Issue(
            "warning",
            f"No raw dark set matched, so the DWARF's own master dark is being "
            f"used instead: {best.path.name}, built by the telescope from "
            f"{best.stack_count} frames at {best.temperature:.0f}C. Your own "
            f"darks, shot on the same night, would calibrate better.",
        )
    )
    return best, issues


def build_group(
    sessions: list[LightSession],
    darks: list[DarkSet],
    cali_masters: list[MasterDark] | None = None,
    use_cali_fallback: bool = True,
) -> SessionGroup:
    """Assemble one group and run every check against it.

    Calibration preference, in order: the user's own matching DWARF_DARK set,
    then a DWARF-supplied CALI_FRAME master if the fallback is enabled, then
    nothing.
    """
    target = sessions[0].target if sessions else ""
    group = SessionGroup(target=target, sessions=list(sessions))
    group.issues.extend(check_compatibility(sessions))

    if not group.errors:
        matched, dark_issues = match_darks(sessions, darks)
        group.darks = matched
        group.issues.extend(dark_issues)

        if not matched and use_cali_fallback:
            master, cali_issues = match_cali_master(sessions, cali_masters or [])
            group.master_dark = master
            group.issues.extend(cali_issues)

        if not group.has_calibration:
            reference = sessions[0]
            near = [
                dark
                for dark in darks
                if exposure_key(dark.exposure) == exposure_key(reference.exposure)
                and dark.gain == reference.gain
            ]
            detail = ""
            if near:
                detail = (
                    f" The closest is {near[0].path.name} "
                    f"({near[0].describe_settings()}), which differs on "
                    f"binning or camera."
                )
            group.issues.append(
                Issue(
                    "warning",
                    f"No dark set matches "
                    f"{format_exposure(reference.exposure)} at gain "
                    f"{reference.gain}, bin {reference.binning}.{detail} "
                    f"The stack will be built WITHOUT dark calibration -- "
                    f"expect amp glow and hot pixels. Shoot darks at these "
                    f"settings on the DWARF and scan again.",
                )
            )

    return group


def auto_group(
    sessions: list[LightSession],
    darks: list[DarkSet],
    cali_masters: list[MasterDark] | None = None,
    use_cali_fallback: bool = True,
) -> list[SessionGroup]:
    """Bucket sessions by everything that must agree, then check each bucket.

    This is what makes the two C 27 sessions arrive as one obvious group
    without the user pairing them by hand.
    """
    buckets: dict[tuple, list[LightSession]] = {}
    for session in sessions:
        buckets.setdefault(session.compatibility_key, []).append(session)

    groups = [
        build_group(bucket, darks, cali_masters, use_cali_fallback)
        for bucket in buckets.values()
    ]
    groups.sort(key=lambda g: (g.target == "", g.target, -g.total_frames))
    explain_splits(groups)
    return groups


def explain_splits(groups: list[SessionGroup]) -> None:
    """Say why one target ended up as more than one stack.

    Without this the user sees two cards both labelled "IC 1396" and no
    reason for it. The sessions were never offered together, so nothing ever
    raises the mismatch as an error -- but "why are these separate?" is
    exactly the question the split provokes, so each card answers it.
    """
    by_target: dict[str, list[SessionGroup]] = {}
    for group in groups:
        if group.target:
            by_target.setdefault(group.target, []).append(group)

    for target, siblings in by_target.items():
        if len(siblings) < 2:
            continue
        for group in siblings:
            mine = group.sessions[0]
            differences: list[str] = []
            for other in siblings:
                if other is group:
                    continue
                theirs = other.sessions[0]
                for label, get, render in COMPATIBILITY_FIELDS:
                    if label == "target":
                        continue
                    if get(mine) != get(theirs):
                        differences.append(f"{label} {render(get(theirs))}")
                        break
            modes = {other.sessions[0].mount_mode for other in siblings}
            if len(modes) > 1:
                # Worth its own sentence. This is the one split where the
                # obvious question -- "why can't I just tick both?" -- has an
                # answer the user would never work out for themselves.
                others = sorted(modes - {mine.mount_mode})
                group.issues.append(
                    Issue(
                        "warning",
                        f"{target} was shot both in EQ and in alt-az. This "
                        f"group is {mine.mount_mode}; there "
                        f"{'is' if len(others) == 1 else 'are'} also "
                        f"{' and '.join(others)}. They are kept apart on "
                        f"purpose: the frames would align, but the alt-az "
                        f"session's field rotation would cost the whole "
                        f"combined stack its frame edges, including the EQ "
                        f"frames that did not need to lose them.",
                    )
                )

            if differences:
                unique = list(dict.fromkeys(differences))
                group.issues.append(
                    Issue(
                        "warning",
                        f"{target} was shot at more than one setting, so it "
                        f"cannot all go in one stack. This group is "
                        f"{mine.describe_settings()}; the other "
                        f"{'groups are' if len(unique) > 1 else 'group is'} "
                        f"{', '.join(unique)}. Stack them separately.",
                    )
                )
