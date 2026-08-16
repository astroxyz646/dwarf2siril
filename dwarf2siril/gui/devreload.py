"""Live reloading, for working on this app. Development only.

Two levels, because they are not equally safe:

*   THEME CHANGES ARE GENUINELY LIVE. Save theme.py and the running app
    restyles itself -- colours, spacing, padding, radii, fonts -- with the
    card grid exactly where it was. No restart, no state lost. That is the
    tight loop for design work.

*   CODE CHANGES RESTART THE PROCESS. Hot-swapping classes under live Qt
    widgets is a well-known source of phantom bugs, and an hour chasing a
    reload artefact costs more than every restart it would have saved. So
    this is honest about being a restart, and puts back what the user had.

The theme is a Python function rather than a .qss file, and it stays that
way: it interpolates the palette constants, so extracting it to plain QSS
would mean losing the single source of colour or duplicating it. Reloading
the module and re-applying its output gets the same live loop without that
trade.

OFF unless DWARF2SIRIL_DEV=1, and never present in a packaged build.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QTimer


def enabled() -> bool:
    """Only in a source checkout, and only when asked for.

    A shipped app that watches the filesystem is dead weight, and one that
    restarts itself when a file changes is a bug -- so the frozen check is
    first and is not negotiable by environment variable.
    """
    if getattr(sys, "frozen", False):
        return False
    return os.environ.get("DWARF2SIRIL_DEV", "") == "1"


class DevReloader:
    """Watches the package and reacts to saves."""

    def __init__(self, app, window=None) -> None:
        self._app = app
        self._window = window
        self._package = Path(__file__).resolve().parents[1]
        self._watcher = QFileSystemWatcher()
        self._pending = QTimer()
        self._pending.setSingleShot(True)
        self._pending.setInterval(150)   # editors write in bursts
        self._pending.timeout.connect(self._apply)
        self._dirty: set[str] = set()

        self._watch_everything()
        self._watcher.fileChanged.connect(self._on_changed)
        self._watcher.directoryChanged.connect(self._on_directory)
        print("[dev] live reload on — theme saves restyle, code saves restart")

    # -- watching --------------------------------------------------------

    def _files(self) -> list[str]:
        return [str(p) for p in self._package.rglob("*.py")]

    def _watch_everything(self) -> None:
        for path in self._files():
            if path not in self._watcher.files():
                self._watcher.addPath(path)
        for folder in {str(self._package)} | {
            str(p) for p in self._package.rglob("*") if p.is_dir()
        }:
            if folder not in self._watcher.directories():
                self._watcher.addPath(folder)

    def _on_changed(self, path: str) -> None:
        self._dirty.add(path)
        # THE CLASSIC TRAP: most editors save by writing a temp file and
        # renaming it over the original, which deletes the inode the watcher
        # held. Without re-adding, you get exactly one reload and then
        # silence -- which looks like the feature working once and then
        # quietly breaking.
        QTimer.singleShot(50, lambda: self._readd(path))
        self._pending.start()

    def _on_directory(self, _path: str) -> None:
        # New files appear as directory changes, not file changes.
        self._watch_everything()

    def _readd(self, path: str) -> None:
        if Path(path).exists() and path not in self._watcher.files():
            self._watcher.addPath(path)

    # -- reacting --------------------------------------------------------

    def _apply(self) -> None:
        changed = {Path(p).name for p in self._dirty}
        self._dirty.clear()
        if not changed:
            return

        # A theme-only change restyles in place. Anything else is code, and
        # code gets a restart.
        if changed <= {"theme.py"}:
            self._restyle()
        else:
            self._restart(changed)

    def _restyle(self) -> None:
        try:
            from . import theme

            importlib.reload(theme)
            self._app.setStyleSheet(theme.stylesheet())
            print("[dev] theme reloaded")
        except Exception as exc:  # noqa: BLE001 - a bad edit must not kill the app
            print(f"[dev] theme reload failed, app left as it was: {exc}")

    def _restart(self, changed: set[str]) -> None:
        # NEVER restart on top of a running stack. os.execv replaces this
        # process outright, so a save while Siril is working kills the build
        # mid-flight and leaves a half-written output folder behind. An edit
        # can wait; an hour of stacking cannot be got back.
        if self._busy():
            print(f"[dev] busy, holding restart for {', '.join(sorted(changed))}")
            self._dirty.update(changed)
            self._pending.start(2000)
            return

        print(f"[dev] restarting for {', '.join(sorted(changed))}")
        try:
            self._remember()
        except Exception:  # noqa: BLE001
            pass
        try:
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as exc:  # noqa: BLE001
            print(f"[dev] could not restart: {exc}")

    def _busy(self) -> bool:
        """Is a build or a stack running right now?

        Asked of the window rather than tracked here, so there is one answer
        to the question and it is the window's.
        """
        if self._window is None:
            return False
        try:
            return bool(self._window._busy())
        except Exception:  # noqa: BLE001 - if in doubt, do not restart
            return True

    def _remember(self) -> None:
        """Put back what the developer was looking at.

        A restart that loses the scanned card means re-picking the drive and
        waiting for the scan on every save, which would make the feature not
        worth having.
        """
        if self._window is None:
            return
        from ..postprocess import save_setting

        source = getattr(self._window, "source_root", None)
        if source is not None:
            save_setting("dev_last_card", str(source))
        output = getattr(self._window, "output_dir", None)
        if output is not None:
            save_setting("dev_last_output", str(output))


def install(app, window=None) -> DevReloader | None:
    """Turn on live reloading if this is a dev run. Otherwise do nothing."""
    if not enabled():
        return None
    try:
        return DevReloader(app, window)
    except Exception as exc:  # noqa: BLE001
        print(f"[dev] live reload unavailable: {exc}")
        return None


def restore(window) -> None:
    """Re-open whatever the last dev run had open."""
    if not enabled() or window is None:
        return
    try:
        from ..postprocess import load_settings

        settings = load_settings()
        card = settings.get("dev_last_card")
        output = settings.get("dev_last_output")
        if output:
            window.output_dir = Path(output)
            if hasattr(window, "output_field"):
                window.output_field.setText(output)
        if card and Path(card).exists():
            QTimer.singleShot(120, lambda: window._start_scan(Path(card)))
    except Exception as exc:  # noqa: BLE001
        print(f"[dev] could not restore the last session: {exc}")
