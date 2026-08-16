r"""Deleting things from the card, as safely as Windows will allow.

ONE delete path for the whole application. Frames, whole sessions and the
cleanup view all come through here, so there is a single place where the
rules live and a single thing to get right.

The rule that matters most: prefer the Recycle Bin. That single choice turns
an irreversible mistake into a recoverable one.

*** AND THE THING THAT MAKES IT DANGEROUS ***
A DWARF card is a REMOVABLE volume, and removable volumes generally have NO
Recycle Bin. Measured on the operator's own card: D:\ is DRIVE_REMOVABLE and
SHQueryRecycleBin returns E_FAIL (0x80004005), meaning there is no bin to
recycle into. Windows does not refuse in that case -- given FOF_ALLOWUNDO it
simply deletes permanently and reports success. That is a silent,
unrecoverable surprise, so this module never assumes: it asks the volume
first, and the answer is passed up so the confirmation dialog can say
"permanently" in plain words rather than "delete".

Everything here is ctypes against the Windows shell, so no dependency.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

# SHFileOperation
FO_DELETE = 0x0003
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040          # this is the one that means "recycle"
FOF_NOERRORUI = 0x0400
FOF_NOCONFIRMMKDIR = 0x0200
FOF_WANTNUKEWARNING = 0x4000


def describe_size(size: int) -> str:
    """Bytes in units a person reads. 4 GB, 512 MB, 40 KB."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit in ("B", "KB"):
                return f"{value:.0f} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def folder_size(path: Path) -> tuple[int, int]:
    """Total bytes and file count under a folder. Never raises."""
    total = files = 0
    try:
        if path.is_file():
            return path.stat().st_size, 1
    except OSError:
        return 0, 0
    for dirpath, _dirs, names in os.walk(path):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
                files += 1
            except OSError:
                continue
    return total, files


def recycle_bin_available(path: Path | str) -> bool:
    """Does the volume holding ``path`` actually have a working Recycle Bin?

    Asked with SHQueryRecycleBin, which only QUERIES -- it deletes nothing,
    so it is safe to run against the user's card. A removable volume
    generally answers no, and that answer has to reach the user before they
    press the button, not afterwards.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class SHQUERYRBINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("i64Size", ctypes.c_longlong),
                ("i64NumItems", ctypes.c_longlong),
            ]

        drive = os.path.splitdrive(str(Path(path).resolve()))[0]
        if not drive:
            return False
        info = SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(info)
        result = ctypes.windll.shell32.SHQueryRecycleBinW(
            ctypes.c_wchar_p(drive + "\\"), ctypes.byref(info)
        )
        return result == 0
    except Exception:  # noqa: BLE001 - treat any doubt as "no bin"
        return False


@dataclass
class DeleteResult:
    """What actually happened. Never optimistic."""

    deleted: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
    bytes_freed: int = 0
    recycled: bool = False
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return not self.failed and not self.cancelled

    def summary(self) -> str:
        where = "to the Recycle Bin" if self.recycled else "permanently"
        parts = []
        if self.deleted:
            parts.append(
                f"{len(self.deleted)} item{'s' if len(self.deleted) != 1 else ''} "
                f"deleted {where}, {describe_size(self.bytes_freed)} freed"
            )
        if self.failed:
            parts.append(
                f"{len(self.failed)} could NOT be deleted"
            )
        if self.cancelled:
            parts.append("cancelled")
        return "; ".join(parts) if parts else "nothing to delete"


def _shell_delete(paths: list[Path], recycle: bool) -> tuple[bool, bool, str]:
    """Hand the paths to the Windows shell. Returns (ok, aborted, message)."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_uint16),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    # pFrom is a list of paths separated by NULs and terminated by a double
    # NUL. Getting that wrong silently truncates the list, so it is built
    # explicitly rather than by joining.
    joined = "\0".join(str(p) for p in paths) + "\0\0"

    flags = FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT | FOF_NOCONFIRMMKDIR
    if recycle:
        flags |= FOF_ALLOWUNDO

    operation = SHFILEOPSTRUCTW()
    operation.hwnd = None
    operation.wFunc = FO_DELETE
    operation.pFrom = joined
    operation.pTo = None
    operation.fFlags = flags
    operation.fAnyOperationsAborted = False

    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    return code == 0, bool(operation.fAnyOperationsAborted), f"shell error {code}"


def delete(paths: list[Path], allow_recycle: bool = True) -> DeleteResult:
    """Delete files and folders, preferring the Recycle Bin.

    ``allow_recycle`` only ASKS. Whether it actually recycles depends on the
    volume, which is why the result records what really happened rather than
    what was requested.
    """
    result = DeleteResult()
    wanted = [Path(p) for p in paths]
    existing = [p for p in wanted if p.exists()]
    for missing in [p for p in wanted if not p.exists()]:
        result.failed.append((missing, "already gone"))
    if not existing:
        return result

    # Measure before deleting: afterwards there is nothing left to measure.
    for path in existing:
        size, _count = folder_size(path)
        result.bytes_freed += size

    recycle = bool(allow_recycle) and recycle_bin_available(existing[0])
    result.recycled = recycle

    if sys.platform == "win32":
        try:
            ok, aborted, message = _shell_delete(existing, recycle)
        except Exception as exc:  # noqa: BLE001
            ok, aborted, message = False, False, str(exc)
        result.cancelled = aborted
        if not ok and not aborted:
            # Fall through to per-item deletion so we can say WHICH failed
            # rather than reporting a single opaque shell error.
            _delete_individually(existing, result)
            return result
    else:
        _delete_individually(existing, result)
        return result

    # Trust nothing: check each path really went.
    for path in existing:
        if path.exists():
            result.failed.append((path, "still there after the delete"))
            result.bytes_freed -= folder_size(path)[0]
        else:
            result.deleted.append(path)
    return result


def _delete_individually(paths: list[Path], result: DeleteResult) -> None:
    """Fallback: delete one at a time so failures can be named.

    Used when the shell operation fails as a whole, and on platforms that do
    not have it. Always a permanent delete -- there is no recycle bin to
    reach from here -- so the result says so.
    """
    result.recycled = False
    for path in paths:
        size = folder_size(path)[0]
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            result.deleted.append(path)
        except OSError as exc:
            result.failed.append((path, exc.strerror or str(exc)))
            result.bytes_freed -= size
