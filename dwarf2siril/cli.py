"""Command line front end.

Sits on the same core the GUI uses. Three verbs:

    scan    -- show what is on the card
    plan    -- show the groups and their checks, build nothing
    build   -- create the Siril working folder and script
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .builder import BuildCancelled, build
from .deletion import describe_size
from .grouping import auto_group, build_group
from .model import (
    FRAMING_BLURB,
    FRAMING_CLEAN,
    FRAMING_LABELS,
    FRAMING_WHOLE,
    LightSession,
    default_framing,
    SessionGroup,
    format_exposure,
)
from .postprocess import PostOptions
from .quality import DEFAULT_STRENGTH, STRENGTHS, QualityFilter, parse_log
from .scanner import ScanResult, find_astronomy_root, scan
from .siril import (
    SirilNotFound,
    expected_output,
    find_siril,
    interpret,
    run_command,
    stream_siril,
)


def _resolve_root(raw: str) -> Path:
    """Accept a drive, a card root, or the Astronomy folder itself."""
    given = Path(raw).expanduser()
    if not given.exists():
        raise SystemExit(f"error: no such folder: {given}")
    root = find_astronomy_root(given)
    if root is None:
        raise SystemExit(
            f"error: {given} does not look like a DWARF 3 card.\n"
            f"Expected DWARF_RAW_* session folders or a DWARF_DARK folder, "
            f"either directly inside it or inside an 'Astronomy' folder."
        )
    return root


def _print_scan(result: ScanResult) -> None:
    print(f"\nDWARF 3 card: {result.root}\n")

    eq = result.eq_sessions
    altaz = result.altaz_sessions

    print(f"Sessions: {len(result.sessions)} ({len(eq)} EQ, {len(altaz)} alt-az)")
    print(f"Dark sets: {len(result.darks)}\n")

    if result.sessions:
        print("Sessions")
        print("-" * 72)
        for session in result.sessions:
            print(f"  {session.path.name}")
            print(
                f"    target {session.display_target} | {session.describe_settings()} "
                f"| {session.frame_count} frames | {session.camera} | "
                f"{session.mount_mode}"
            )
        print()

    if altaz:
        print("Note on the alt-az sessions")
        print("-" * 72)
        print(
            "  These stack fine -- alignment corrects the field rotation.\n"
            "  The edges end up built from fewer frames than the middle, so\n"
            "  they are noisier. Trimming to the shared area would fix that\n"
            "  but costs about 80% of the frame on a rotated session, so the\n"
            "  whole frame is kept instead. Shooting in EQ on a wedge avoids\n"
            "  the trade entirely."
        )
        print()

    if result.darks:
        print("Dark sets")
        print("-" * 72)
        for dark in result.darks:
            print(
                f"  {dark.path.name}\n"
                f"    {dark.describe_settings()} | {dark.frame_count} frames"
            )
        print()

    if result.cali_masters:
        print("DWARF-supplied master darks (CALI_FRAME, used only as a fallback)")
        print("-" * 72)
        for master in result.cali_masters:
            usable = "usable" if master.is_usable else "too few frames - rejected"
            print(
                f"  {master.path.name}\n"
                f"    {master.describe_settings()} | {master.camera} | "
                f"{master.stack_count} frames | {usable}"
            )
        print()

    if result.skipped:
        print("Skipped")
        print("-" * 72)
        for note in result.skipped:
            print(f"  {note}")
        print()


def _print_group(group: SessionGroup, index: int) -> None:
    print(f"[{index}] {group.display_target}")
    print("-" * 72)
    first = group.sessions[0]
    print(f"  Settings    : {first.describe_settings()}")
    print(f"  Sessions    : {len(group.sessions)}")
    for session in group.sessions:
        print(f"                {session.path.name} ({session.frame_count} frames)")
    print(f"  Light frames: {group.total_frames}")
    print(f"  Integration : {group.describe_integration()}")
    print(f"  Calibration : {group.dark_source}")
    if group.darks:
        for dark in group.darks:
            print(f"                {dark.path.name} ({dark.frame_count} frames)")
    elif group.master_dark:
        print(f"                {group.master_dark.path.name}")
    print(f"  Stack name  : {group.suggested_name()}")

    for issue in group.errors:
        print(f"  ERROR       : {issue.message}")
    for issue in group.warnings:
        print(f"  warning     : {issue.message}")
    print()


def _select_sessions(result: ScanResult, wanted: list[str]) -> list[LightSession]:
    """Resolve --session arguments, which may be full paths or folder names."""
    chosen: list[LightSession] = []
    for item in wanted:
        needle = Path(item).name
        matches = [s for s in result.sessions if s.path.name == needle]
        if not matches:
            raise SystemExit(f"error: no session named {needle!r} on this card")
        chosen.extend(matches)
    return chosen


def cmd_scan(args: argparse.Namespace) -> int:
    result = scan(_resolve_root(args.source))
    _print_scan(result)
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    result = scan(_resolve_root(args.source))
    groups = auto_group(
        result.stackable_sessions,
        result.darks,
        result.cali_masters,
        use_cali_fallback=not args.no_dwarf_master,
    )
    if not groups:
        print("No sessions found on this card.")
        return 1
    print(f"\n{len(groups)} group(s) found on {result.root}\n")
    for index, group in enumerate(groups, start=1):
        _print_group(group, index)
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    result = scan(_resolve_root(args.source))

    if args.session:
        sessions = _select_sessions(result, args.session)
        group = build_group(
            sessions,
            result.darks,
            result.cali_masters,
            use_cali_fallback=not args.no_dwarf_master,
        )
    else:
        groups = auto_group(
            result.stackable_sessions,
            result.darks,
            result.cali_masters,
            use_cali_fallback=not args.no_dwarf_master,
        )
        if not groups:
            print("No sessions found on this card.")
            return 1
        if args.target:
            wanted = args.target.strip().lower()
            groups = [g for g in groups if g.display_target.lower() == wanted]
            if not groups:
                print(f"No group for target {args.target!r}. Run 'plan' to see targets.")
                return 1
        if len(groups) > 1:
            print(f"{len(groups)} groups found. Narrow it with --target:\n")
            for index, candidate in enumerate(groups, start=1):
                _print_group(candidate, index)
            return 1
        group = groups[0]

    _print_group(group, 1)

    if group.errors:
        print("Refusing to build: the sessions above are not compatible.")
        return 1

    if not group.has_calibration and not args.allow_no_darks:
        print(
            "Refusing to build: no matching darks. Pass --allow-no-darks to "
            "build an uncalibrated stack anyway."
        )
        return 1

    post = PostOptions(
        background_removal=args.background,
        denoise=args.denoise,
        plate_solve=args.platesolve,
        colour_calibration=args.colour,
        star_reduction=args.star_reduction,
        stretch=args.stretch,
        star_amount=max(0.0, min(1.0, args.star_amount)),
        starnet_path=Path(args.starnet) if args.starnet else None,
        previews=not args.no_previews,
    )
    for note in post.resolve():
        print(f"  note: {note}")
    if post.any_enabled:
        print(f"  Layers: {', '.join(post.enabled_labels())}")

    quality = QualityFilter(
        enabled=args.frame_filter != "off",
        strength=args.frame_filter,
    )
    print(f"  Frame filter: {args.frame_filter} - {quality.describe()}")

    # Framing applies to every group -- rotation and drift both cost edges --
    # but only say so when there is a real trade to explain.
    framing = args.framing or default_framing(group.is_altaz)
    if group.is_altaz:
        print("  Mount mode  : alt-az - the field rotates between frames")
    if group.is_altaz or len(group.sessions) > 1:
        print(f"  Framing     : {FRAMING_LABELS[framing]}")
        print(f"                {FRAMING_BLURB[framing]}")

    output = Path(args.output).expanduser()
    output.mkdir(parents=True, exist_ok=True)

    last = [-1]

    def progress(done: int, total: int, message: str) -> None:
        percent = int(done * 100 / total) if total else 100
        if percent != last[0]:
            last[0] = percent
            print(f"\r  {percent:3d}%  {message:<50}", end="", flush=True)

    try:
        built = build(
            group,
            output,
            stack_name=args.name,
            progress=progress,
            post=post,

            quality=quality,


            framing=framing,
        )
    except BuildCancelled as exc:
        print(f"\nCancelled: {exc}")
        return 1
    except (OSError, ValueError) as exc:
        print(f"\nerror: {exc}")
        return 1

    print("\n")
    print(f"Built in {built.output_dir}")
    print(f"  {built.lights_copied} lights, {built.darks_copied} darks, "
          f"{describe_size(built.total_bytes)}")
    print(f"  Script: {built.script_path}")
    for warning in built.warnings:
        print(f"  warning: {warning}")

    stack_name = args.name or group.suggested_name()
    siril = find_siril(args.siril)
    command = run_command(built.script_path, siril)

    if not args.stack:
        print(f"\nRun it with:\n  {command}")
        print("\nOr pass --stack next time to have this run it for you.\n")
        return 0

    if siril is None:
        print(
            "\nCould not find siril-cli, so there is nothing to run it with.\n"
            "Install Siril from siril.org, or pass --siril with the path to it.\n"
            f"The script is ready either way:\n  {command}\n"
        )
        return 1

    print(f"\nRunning Siril: {siril}\n")
    lines: list[str] = []
    exit_code = 1
    try:
        for item in stream_siril(built.script_path, siril):
            if item.startswith("__RESULT__:"):
                exit_code = int(item.split(":", 1)[1])
                continue
            lines.append(item)
            print(item[5:] if item.startswith("log: ") else item)
    except (SirilNotFound, OSError) as exc:
        print(f"\nerror: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\nStopped.")
        return 1

    outcome = interpret(lines, exit_code, expected_output(built.script_path, stack_name))
    if outcome.ok:
        where = outcome.output_image or expected_output(built.script_path, stack_name)

        # Report what was actually stacked, not what was shot.
        frames = parse_log(lines, group.total_frames)
        if frames.total:
            print(f"\n{frames.summary()}")
            for reason in frames.detail():
                print(f"  {reason}")
            used_seconds = group.integration_seconds * frames.kept_fraction
            minutes, seconds = divmod(int(used_seconds), 60)
            hours, minutes = divmod(minutes, 60)
            actual = (
                f"{hours}h {minutes:02d}m" if hours else f"{minutes}m {seconds:02d}s"
            )
            print(f"  Integration actually used: {actual}")
            if frames.looks_wrong:
                print(
                    f"\n  WARNING: that is most of the session gone. Either the "
                    f"filter is too strict or the data has a problem. Try "
                    f"--frame-filter=gentle or --frame-filter=off and look at "
                    f"the frames before trusting this result."
                )

        print(f"\nStacked: {where}\n")
        return 0

    print("\nSiril did not finish.")
    for line in outcome.error_lines[:5]:
        print(f"  {line}")
    print(f"\nThe project is still there. Try again with:\n  {command}\n")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dwarf2siril",
        description="Prepare DWARF 3 exposures for stacking in Siril.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="list what is on the card")
    scan_parser.add_argument("source", help="DWARF 3 drive, card root, or Astronomy folder")
    scan_parser.set_defaults(func=cmd_scan)

    plan_parser = subparsers.add_parser(
        "plan", help="show groups and compatibility checks without building"
    )
    plan_parser.add_argument("source", help="DWARF 3 drive, card root, or Astronomy folder")
    _add_master_flag(plan_parser)
    plan_parser.set_defaults(func=cmd_plan)

    build_parser_ = subparsers.add_parser("build", help="build the Siril working folder")
    build_parser_.add_argument("source", help="DWARF 3 drive, card root, or Astronomy folder")
    build_parser_.add_argument("-o", "--output", required=True, help="output folder")
    build_parser_.add_argument("-t", "--target", help="target name, e.g. 'C 27'")
    build_parser_.add_argument(
        "-s",
        "--session",
        action="append",
        default=[],
        help="session folder name; repeat to combine sessions explicitly",
    )
    build_parser_.add_argument("-n", "--name", help="name for the stacked result")
    # --copy was here. It forced copying where linking was possible, and a
    # hard link and a copy leave the same bytes in the same place under the
    # same name, so the flag could not change any outcome the caller could
    # observe -- only make it slower and use the space twice.
    build_parser_.add_argument(
        "--allow-no-darks",
        action="store_true",
        help="build even when no dark set matches",
    )
    build_parser_.add_argument(
        "--stack",
        action="store_true",
        help="run Siril on the generated script once it is built",
    )
    layers = build_parser_.add_argument_group(
        "optional layers (all off by default; the plain stack is unchanged)"
    )
    layers.add_argument(
        "--background", action="store_true", help="remove sky gradient (Siril subsky)"
    )
    layers.add_argument(
        "--denoise", action="store_true", help="denoise the result (Siril denoise)"
    )
    layers.add_argument(
        "--platesolve", action="store_true", help="plate solve the result"
    )
    layers.add_argument(
        "--colour",
        "--color",
        action="store_true",
        dest="colour",
        help="photometric colour calibration (implies --platesolve, needs internet)",
    )
    layers.add_argument(
        "--star-reduction",
        action="store_true",
        help="shrink stars using StarNet2 (destructive; StarNet2 must be installed)",
    )
    layers.add_argument(
        "--star-amount",
        type=float,
        default=0.5,
        metavar="N",
        help="how much of the star layer to keep, 0.0-1.0 (default 0.5)",
    )
    layers.add_argument(
        "--stretch",
        action="store_true",
        help="stretch the result into a finished picture (runs last)",
    )
    layers.add_argument(
        "--starnet", help="path to starnet2.exe, if it is somewhere unusual"
    )
    layers.add_argument(
        "--framing",
        choices=[FRAMING_WHOLE, FRAMING_CLEAN],
        default=None,
        help=(
            "alt-az sessions only: 'whole' keeps the full frame with slightly "
            "noisier corners (default); 'clean' crops to the area every frame "
            "covers, which can cost most of the picture"
        ),
    )
    layers.add_argument(
        "--frame-filter",
        choices=list(STRENGTHS.keys()),
        default=DEFAULT_STRENGTH,
        help=(
            "drop frames ruined by cloud, wind or bad seeing "
            f"(default: {DEFAULT_STRENGTH}; 'off' stacks everything)"
        ),
    )
    layers.add_argument(
        "--no-previews",
        action="store_true",
        help="do not save before/after preview JPEGs",
    )
    build_parser_.add_argument(
        "--siril",
        help="path to siril-cli, if it is not where we would look for it",
    )
    _add_master_flag(build_parser_)
    build_parser_.set_defaults(func=cmd_build)

    return parser


def _add_master_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--no-dwarf-master",
        action="store_true",
        help=(
            "do not fall back to the DWARF's own pre-stacked master dark from "
            "CALI_FRAME when no raw dark set matches"
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())



