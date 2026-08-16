"""What is on the card, how big it is, and how safe it is to remove.

The value of a cleanup view is not the deleting -- a file manager deletes.
It is knowing which of these folders you will regret losing, which the
telescope will simply make again, and which are none of the tool's business.

Four classes, and the tool is deliberately conservative about the middle two:

    SAFE      the DWARF regenerates it, or it is a failed attempt
    STACKED   a session this tool has already stacked somewhere else
    KEEP      reusable across future sessions -- darks and calibration
    YOURS     photos and videos: shown with sizes, judged not at all

Nothing is ever preselected. The user selects; this module only advises.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .deletion import describe_size, folder_size
from .postprocess import load_settings, save_setting

SAFE = "safe"
STACKED = "stacked"
KEEP = "keep"
YOURS = "yours"
SYSTEM = "system"

# Folders Windows owns. Never offered, never counted as the user's.
SYSTEM_NAMES = {"$RECYCLE.BIN", "System Volume Information"}

# What each well-known folder is, and why.
KNOWN = {
    "DWARF_DARK": (
        KEEP,
        "Your dark frames. These are REUSABLE on future sessions at the same "
        "exposure and gain -- deleting them means shooting them again.",
    ),
    "CALI_FRAME": (
        KEEP,
        "The telescope's own calibration masters, reused across sessions.",
    ),
    "Solving_Failed": (
        SAFE,
        "Attempts where the telescope could not work out where it was "
        "pointing. Nothing here was ever used.",
    ),
    "RESTACKED": (
        SAFE,
        "Stacks the DWARF made itself from sessions you still have. It can "
        "make them again.",
    ),
    "STARTRAILS": (
        SAFE,
        "Star-trail images the DWARF generated.",
    ),
    ".log": (
        SAFE,
        "The telescope's own log files.",
    ),
    "Normal_Photos": (YOURS, "Your ordinary photos."),
    "Videos": (YOURS, "Your videos."),
    "Panoramas": (YOURS, "Your panoramas."),
    "Burst": (YOURS, "Your burst shots."),
}


@dataclass
class CardEntry:
    """One thing on the card, with its size and how safe it is to lose."""

    path: Path
    name: str
    size: int
    files: int
    kind: str            # SAFE / STACKED / KEEP / YOURS / SYSTEM
    reason: str
    is_session: bool = False
    session_target: str = ""
    stacked_to: str = ""

    @property
    def readable_size(self) -> str:
        return describe_size(self.size)

    @property
    def advice(self) -> str:
        if self.kind == KEEP:
            return "Keep"
        if self.kind == STACKED:
            return "Already stacked"
        if self.kind == SAFE:
            return "Safe to remove"
        return "Yours"


@dataclass
class CardSurvey:
    root: Path
    entries: list[CardEntry] = field(default_factory=list)
    total_bytes: int = 0
    free_bytes: int = 0
    capacity_bytes: int = 0

    @property
    def used_bytes(self) -> int:
        return max(0, self.capacity_bytes - self.free_bytes)

    def by_size(self) -> list[CardEntry]:
        """Biggest first -- the whole point is finding where space went."""
        return sorted(self.entries, key=lambda e: e.size, reverse=True)


# -- remembering what we have stacked ---------------------------------------
#
# A session whose stack already exists elsewhere is the safest thing on the
# card to remove, and nobody tracks that by hand. But it can only be claimed
# if it is KNOWN, so it is recorded when a build finishes rather than guessed
# at afterwards. No record, no claim.

def remember_stacked(session_paths: list[Path], output_dir: Path) -> None:
    """Record that these sessions were stacked into this folder."""
    stacked = load_settings().get("stacked_sessions", {})
    if not isinstance(stacked, dict):
        stacked = {}
    when = datetime.now().strftime("%Y-%m-%d %H:%M")
    for session in session_paths:
        stacked[str(session)] = {"output": str(output_dir), "when": when}
    save_setting("stacked_sessions", stacked)


def stacked_record(session_path: Path) -> dict | None:
    """What we know about this session having been stacked, if anything."""
    stacked = load_settings().get("stacked_sessions", {})
    if not isinstance(stacked, dict):
        return None
    record = stacked.get(str(session_path))
    if not isinstance(record, dict):
        return None
    # Only claim it if the output is actually still there. A stack the user
    # has since deleted is not a reason to delete the source.
    output = record.get("output", "")
    if output and not Path(output).exists():
        return None
    return record


def _classify(path: Path, sessions_by_path: dict[str, str]) -> tuple[str, str]:
    name = path.name
    if name in SYSTEM_NAMES:
        return SYSTEM, "Windows' own folder."

    if str(path) in sessions_by_path:
        record = stacked_record(path)
        if record:
            return (
                STACKED,
                f"You already stacked this with Dwarf2Siril on "
                f"{record.get('when', 'a previous run')}. The stack is in "
                f"{record.get('output', 'your output folder')}.",
            )
        return (
            YOURS,
            "A session of light frames. Nothing else on the card can "
            "replace these.",
        )

    known = KNOWN.get(name)
    if known:
        return known
    return YOURS, "Not something this tool recognises, so it offers no opinion."


def survey(card_root: Path, sessions: list | None = None) -> CardSurvey:
    """Walk the card and size everything at the top two levels.

    ``sessions`` is the scanner's session list, so a session folder can be
    labelled with its target rather than its very long folder name.
    """
    card_root = Path(card_root)
    result = CardSurvey(root=card_root)

    sessions_by_path = {
        str(session.path): session.display_target for session in (sessions or [])
    }

    try:
        total, free = _disk_space(card_root)
        result.capacity_bytes, result.free_bytes = total, free
    except OSError:
        pass

    # The card root, plus inside Astronomy, because that is where the
    # interesting split between sessions, darks and leftovers lives.
    places: list[Path] = []
    try:
        places.extend(sorted(card_root.iterdir()))
    except OSError:
        return result

    astronomy = card_root / "Astronomy"
    if astronomy.is_dir():
        places = [p for p in places if p != astronomy]
        try:
            places.extend(sorted(astronomy.iterdir()))
        except OSError:
            pass

    for path in places:
        try:
            size, files = folder_size(path)
        except OSError:
            continue
        kind, reason = _classify(path, sessions_by_path)
        target = sessions_by_path.get(str(path), "")
        record = stacked_record(path) if target else None
        result.entries.append(
            CardEntry(
                path=path,
                name=(f"{target} — {path.name}" if target else path.name),
                size=size,
                files=files,
                kind=kind,
                reason=reason,
                is_session=bool(target),
                session_target=target,
                stacked_to=record.get("output", "") if record else "",
            )
        )
        result.total_bytes += size

    return result


def _disk_space(path: Path) -> tuple[int, int]:
    """Capacity and free bytes for the volume holding ``path``."""
    usage = os.statvfs(path) if hasattr(os, "statvfs") else None
    if usage is not None:
        return usage.f_blocks * usage.f_frsize, usage.f_bavail * usage.f_frsize

    import ctypes
    from ctypes import wintypes

    free = ctypes.c_ulonglong(0)
    total = ctypes.c_ulonglong(0)
    ctypes.windll.kernel32.GetDiskFreeSpaceExW(
        ctypes.c_wchar_p(str(path)),
        ctypes.byref(free),
        ctypes.byref(total),
        None,
    )
    return total.value, free.value
