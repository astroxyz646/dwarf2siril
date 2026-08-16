"""Find drives that look like a DWARF 3 card, so the user need not hunt.

Best-effort by design. The GUI offers whatever this finds and always keeps a
plain folder picker beside it, because a detection miss must never be a dead
end.
"""

from __future__ import annotations

import string
import sys
from dataclasses import dataclass
from pathlib import Path

from .scanner import find_astronomy_root


@dataclass
class DriveCandidate:
    path: Path          # the folder to scan (the Astronomy root)
    mount: Path         # the drive or volume it sits on
    label: str
    is_dwarf: bool

    @property
    def display(self) -> str:
        return f"{self.label} ({self.mount})" if self.label else str(self.mount)


def _windows_mounts() -> list[Path]:
    mounts: list[Path] = []
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:\\")
        try:
            if root.exists():
                mounts.append(root)
        except OSError:
            continue
    return mounts


def _unix_mounts() -> list[Path]:
    mounts: list[Path] = []
    bases = [Path("/Volumes")] if sys.platform == "darwin" else [
        Path("/media"),
        Path("/run/media"),
        Path("/mnt"),
    ]
    for base in bases:
        if not base.is_dir():
            continue
        try:
            for child in base.iterdir():
                if child.is_dir():
                    mounts.append(child)
                    # /media/<user>/<volume> on most Linux desktops
                    try:
                        mounts.extend(g for g in child.iterdir() if g.is_dir())
                    except OSError:
                        pass
        except OSError:
            continue
    return mounts


def _volume_label(mount: Path) -> str:
    if sys.platform == "win32":
        try:
            import ctypes

            buffer = ctypes.create_unicode_buffer(261)
            ok = ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(str(mount)), buffer, 261, None, None, None, None, 0
            )
            if ok:
                return buffer.value
        except Exception:
            return ""
        return ""
    return mount.name


def find_dwarf_drives() -> list[DriveCandidate]:
    """Every mounted volume that holds a readable DWARF layout, best first."""
    mounts = _windows_mounts() if sys.platform == "win32" else _unix_mounts()

    candidates: list[DriveCandidate] = []
    for mount in mounts:
        try:
            root = find_astronomy_root(mount)
        except OSError:
            continue
        if root is None:
            continue
        candidates.append(
            DriveCandidate(
                path=root,
                mount=mount,
                label=_volume_label(mount),
                is_dwarf=True,
            )
        )
    return candidates
