"""Find drives that look like a DWARF 3 card, so the user need not hunt.

Best-effort by design. The GUI offers whatever this finds and always keeps a
plain folder picker beside it, because a detection miss must never be a dead
end.
"""

from __future__ import annotations

import contextlib
import os
import string
import sys
from dataclasses import dataclass
from pathlib import Path

from .scanner import find_astronomy_root

# Windows: fail a bad drive access instead of asking the user about it.
SEM_FAILCRITICALERRORS = 0x0001


@contextlib.contextmanager
def no_disk_dialogs():
    """Stop Windows popping "There is no disk in the drive" while we look.

    Looking for the card means touching every drive letter, and touching an
    empty card reader or a disconnected mapped drive raises a MODAL system
    dialog by default. The user gets an error box about a drive they never
    asked about, in the middle of a scan they did not know was running, and
    nothing continues until they click it -- including the tests.

    SEM_FAILCRITICALERRORS turns that dialog into an ordinary error return,
    which is what every caller in this module already handles. Set per
    thread, and put back afterwards, so this never changes the behaviour of
    anything outside the scan.
    """
    if sys.platform != "win32":
        yield
        return

    import ctypes

    previous = ctypes.c_uint()
    changed = False
    try:
        changed = bool(
            ctypes.windll.kernel32.SetThreadErrorMode(
                SEM_FAILCRITICALERRORS, ctypes.byref(previous)
            )
        )
    except Exception:  # noqa: BLE001 - an old Windows is not worth failing over
        changed = False

    try:
        yield
    finally:
        if changed:
            try:
                ctypes.windll.kernel32.SetThreadErrorMode(previous.value, None)
            except Exception:  # noqa: BLE001
                pass


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
    """Every mounted volume that holds a readable DWARF layout, best first.

    Set ``DWARF2SIRIL_NO_DRIVE_SCAN=1`` to make this return nothing without
    touching any hardware. The layout tests build a real MainWindow, which
    starts a real drive scan, which walks the developer's actual card reader
    -- slow at best, and at worst it blocks the whole test run behind a modal
    Windows dialog about a drive nobody asked about. A test must never depend
    on what is plugged into the machine running it.
    """
    if os.environ.get("DWARF2SIRIL_NO_DRIVE_SCAN"):
        return []

    candidates: list[DriveCandidate] = []
    with no_disk_dialogs():
        mounts = _windows_mounts() if sys.platform == "win32" else _unix_mounts()

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
