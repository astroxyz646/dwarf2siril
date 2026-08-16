"""Background threads for the two slow jobs: scanning and building.

Scanning opens a FITS header per session and a build copies gigabytes, so
neither may run on the UI thread. Both report progress by signal and both
report failure as a message rather than letting a traceback reach the user.
"""

from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from ..builder import BuildCancelled, BuildResult, build
from ..model import SessionGroup
from ..scanner import ScanResult, scan
from ..siril import SirilNotFound, interpret, stream_plan


class ScanWorker(QThread):
    """Walk a card and report what is on it."""

    progressed = Signal(str)
    finished_ok = Signal(object)   # ScanResult
    failed = Signal(str)

    def __init__(self, root: Path) -> None:
        super().__init__()
        self._root = root

    def run(self) -> None:
        try:
            result: ScanResult = scan(self._root, progress=self.progressed.emit)
            self.finished_ok.emit(result)
        except Exception as exc:  # noqa: BLE001 - the UI must never see a traceback
            traceback.print_exc()
            self.failed.emit(f"Could not read that folder.\n\n{exc}")


class BuildWorker(QThread):
    """Copy the frames and write the script."""

    progressed = Signal(int, int, str)
    finished_ok = Signal(object)   # BuildResult
    failed = Signal(str)
    cancelled = Signal(str)

    def __init__(
        self,
        group: SessionGroup,
        output_dir: Path,
        stack_name: str | None,
        post=None,
        quality=None,

        framing=None,
    ) -> None:
        super().__init__()
        self._group = group
        self._output_dir = output_dir
        self._stack_name = stack_name
        self._post = post
        self._quality = quality

        self._framing = framing
        self._stop = False

    def request_stop(self) -> None:
        """Ask the build to stop at the next frame boundary.

        Stopping between frames rather than mid-file means a cancelled build
        leaves whole files behind, never a half-written one.
        """
        self._stop = True

    def run(self) -> None:
        try:
            result: BuildResult = build(
                self._group,
                self._output_dir,
                stack_name=self._stack_name,
                progress=lambda done, total, msg: self.progressed.emit(done, total, msg),
                should_cancel=lambda: self._stop,
                post=self._post,
                quality=self._quality,

                framing=self._framing,
            )
            self.finished_ok.emit(result)
        except BuildCancelled as exc:
            self.cancelled.emit(str(exc))
        except (OSError, ValueError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.failed.emit(f"Something went wrong while building.\n\n{exc}")


class SirilWorker(QThread):
    """Run Siril on a generated script and stream its log back.

    A stack can run for a long time, so the log is emitted line by line
    rather than collected and handed over at the end.
    """

    line = Signal(str)
    # fraction 0-1, plain-English stage, whether that fraction means anything
    progressed = Signal(float, str, bool)
    finished_run = Signal(object)   # SirilRunResult
    failed = Signal(str)

    def __init__(
        self,
        script_path: Path,
        expected_image: Path | None,
        siril_path: Path | None = None,
        stages: list | None = None,
        total_frames: int = 0,
    ) -> None:
        super().__init__()
        self._script = script_path
        self._expected = expected_image
        self._siril = siril_path
        self._stop = False
        self._stages = stages or []
        self._total_frames = total_frames

    def request_stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        from ..progress import RunProgress

        collected: list[str] = []
        exit_code = 1
        # No plan means no claim: an old build result, or a script we did not
        # write, falls back to the indeterminate bar rather than guessing.
        tracker = RunProgress(self._stages, self._total_frames) if self._stages else None
        try:
            # stream_PLAN, not stream_siril: it runs the optional steps in
            # their own Siril each, so one failing cannot take the stack or
            # the other extras with it. See pipeline.py.
            for item in stream_plan(
                self._script, self._siril, should_cancel=lambda: self._stop
            ):
                if item.startswith("__RESULT__:"):
                    exit_code = int(item.split(":", 1)[1])
                    continue
                collected.append(item)
                if item.startswith("__SKIPPED__:"):
                    _, label, reason = item.split(":", 2)
                    self.line.emit(f"*** {label} was skipped: {reason.strip()} ***")
                    continue
                self.line.emit(item)
                if tracker is not None:
                    try:
                        update = tracker.feed(item)
                    except Exception:  # noqa: BLE001 - a bar is never worth a crash
                        tracker = None
                        continue
                    if update is not None:
                        self.progressed.emit(
                            update.fraction, update.label, update.determinate
                        )
            self.finished_run.emit(interpret(collected, exit_code, self._expected))
        except SirilNotFound as exc:
            self.failed.emit(str(exc))
        except OSError as exc:
            self.failed.emit(f"Could not start Siril.\n\n{exc}")
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.failed.emit(f"Something went wrong while running Siril.\n\n{exc}")


class DriveScanner(QObject):
    """Look for DWARF-shaped drives without blocking the window.

    Kept separate from ScanWorker because it runs on a timer at startup and
    must stay cheap: it only checks whether each volume has the right shape.
    """

    found = Signal(list)

    class _Thread(QThread):
        done = Signal(list)

        def run(self) -> None:
            from ..drives import find_dwarf_drives

            try:
                self.done.emit(find_dwarf_drives())
            except Exception:  # noqa: BLE001
                self.done.emit([])

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: DriveScanner._Thread | None = None

    def start(self) -> None:
        self._thread = DriveScanner._Thread()
        self._thread.done.connect(self.found.emit)
        self._thread.start()
