"""Step 4: the panel that appears once a project has been built.

Two ways forward, both always available:

* **Stack now** runs Siril on the generated script and streams its log here.
* The command line is shown regardless, because plenty of people would
  rather run it themselves, and because it is the only thing left to fall
  back on if Siril cannot be found.

Siril not being installed is a normal state to be in, not an error: the panel
says so, offers a picker, and still shows the command.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QElapsedTimer, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..siril import expected_output, find_siril, run_command
from . import theme
from .cards import divider
from .flow import FlowLayout
from .workers import SirilWorker

# Siril is chatty. Keeping the whole log would grow without bound on a long
# stack, and nobody scrolls back past a few hundred lines anyway.
MAX_LOG_LINES = 2000


def _label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


class RunPanel(QFrame):
    """Everything the user needs after a project has been built."""

    finished = Signal(bool)
    # True while Siril is actually running. The window uses this to put a
    # Stop in the status bar: the panel's own Stop is inside a scrolling
    # column and can be scrolled off, and the one control you must be able
    # to reach in a hurry is the one that stops it.
    running = Signal(bool)
    # Stage text, percent (-1 where there is no honest number), and whether
    # that percent means anything. Emitted for the SAME reason as `running`:
    # everything this panel shows about a run in progress -- the bar, the
    # stage, the log -- lives inside a scrolling column, and on an 880px
    # window it is all below the fold. Pressing Stack now in Siril looked
    # like pressing a button that did nothing at all.
    staged = Signal(str, int, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")

        self.script_path: Path | None = None
        self.stack_name: str = ""
        self.output_dir: Path | None = None
        self.result_image: Path | None = None
        self.siril_path: Path | None = find_siril()
        self.worker: SirilWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3
        )
        layout.setSpacing(theme.SPACE_3)

        self.heading = _label("", "CardTitle")
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)

        self.summary = _label("", "Muted", wrap=True)
        layout.addWidget(self.summary)

        # -- the one button this panel exists for ------------------------
        # First, and across the full width. In a narrow column there is no
        # room for a row of equals, and this is not an equal: everything
        # else here is a fallback for when it does not work.
        run_row = QHBoxLayout()
        run_row.setSpacing(theme.SPACE_2)
        self.stack_button = QPushButton("Stack now in Siril")
        self.stack_button.setObjectName("Primary")
        self.stack_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stack_button.clicked.connect(self._start)
        run_row.addWidget(self.stack_button, 1)

        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("Ghost")
        self.stop_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_button.clicked.connect(self._stop)
        self.stop_button.hide()
        run_row.addWidget(self.stop_button)
        layout.addLayout(run_row)

        self.siril_note = _label("", "Faint", wrap=True)
        layout.addWidget(self.siril_note)

        # Secondary actions reflow instead of forcing the panel wide: this
        # panel now lives in a ~330px column, and a fixed row of four
        # buttons would have set the minimum width of the whole window.
        secondary_host = QWidget()
        secondary_host.setObjectName("Plain")
        secondary = FlowLayout(secondary_host, margin=0, spacing=theme.SPACE_2)

        self.locate_button = QPushButton("Locate Siril...")
        self.locate_button.setObjectName("Ghost")
        self.locate_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.locate_button.clicked.connect(self._locate_siril)
        secondary.addWidget(self.locate_button)

        self.open_folder_button = QPushButton("Open folder")
        self.open_folder_button.setObjectName("Ghost")
        self.open_folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_folder_button.clicked.connect(self._open_folder)
        secondary.addWidget(self.open_folder_button)
        layout.addWidget(secondary_host)

        layout.addWidget(divider())

        # -- the command, always here -----------------------------------
        layout.addWidget(_label("RUN IT YOURSELF", "Faint"))
        command_row = QHBoxLayout()
        command_row.setSpacing(theme.SPACE_2)
        self.command_field = QLineEdit()
        self.command_field.setReadOnly(True)
        self.command_field.setMinimumWidth(80)   # may shrink; must not force width
        self.command_field.setObjectName("Mono")
        command_row.addWidget(self.command_field, 1)

        self.copy_button = QPushButton("Copy")
        self.copy_button.setObjectName("Ghost")
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.clicked.connect(self._copy_command)
        command_row.addWidget(self.copy_button)
        layout.addLayout(command_row)

        # -- live log ----------------------------------------------------
        # Real progress where Siril gives us the numbers, indeterminate only
        # where it genuinely does not. Starts indeterminate because nothing
        # has been parsed yet.
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setTextVisible(False)
        self.busy.hide()
        layout.addWidget(self.busy)

        # Coloured RUNNING, matching the bar right above it, so "work is
        # happening" is one signal in one colour rather than a grey sentence
        # under a coloured bar.
        self.stage_line = _label("", "Running", wrap=True)
        self.stage_line.hide()
        layout.addWidget(self.stage_line)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(MAX_LOG_LINES)
        self.log.setMinimumHeight(170)
        self.log.setObjectName("Log")
        self.log.hide()
        layout.addWidget(self.log)

        self.verdict = _label("", wrap=True)
        self.verdict.setTextFormat(Qt.TextFormat.RichText)
        self.verdict.hide()
        layout.addWidget(self.verdict)

        self.open_image_button = QPushButton("Open the stacked image")
        self.open_image_button.setObjectName("Ghost")
        self.open_image_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_image_button.clicked.connect(self._open_image)
        self.open_image_button.hide()
        layout.addWidget(self.open_image_button, 0, Qt.AlignmentFlag.AlignLeft)

    # -- setup ----------------------------------------------------------

    def show_result(self, build_result, stack_name: str) -> None:
        """Point the panel at a project that has just been built."""
        self.script_path = build_result.script_path
        self.stack_name = stack_name
        self.output_dir = build_result.output_dir
        self.result_image = expected_output(self.script_path, stack_name)
        # The weighted stage plan, worked out at build time when the frame
        # counts and chosen layers were both known.
        self.stages = list(getattr(build_result, "stages", []) or [])
        self.total_frames = build_result.lights_copied

        self.heading.setText(f"{stack_name} is ready")
        placed = "linked" if build_result.linked else "copied"
        # THE FOLDER'S NAME, not its whole path. This panel lives in a 330px
        # column, and a real Windows path wrapped into five unbroken lines
        # that said nothing the last component does not. The full path is a
        # hover away, and Open folder is a few pixels below.
        self.summary.setText(
            f"{build_result.lights_copied} light frames and "
            f"{build_result.darks_copied} dark frames {placed} into "
            f"{build_result.output_dir.name}."
        )
        self.summary.setToolTip(str(build_result.output_dir))
        self.command_field.setText(run_command(self.script_path, self.siril_path))
        self.log.clear()
        self.log.hide()
        self.verdict.hide()
        self.open_image_button.hide()
        self._refresh_siril_state()

    def _refresh_siril_state(self) -> None:
        if self.siril_path is None:
            self.siril_note.setText(
                "Siril was not found on this computer. Install it from "
                "siril.org, or point at siril-cli yourself -- the command "
                "above works in any terminal once Siril is installed."
            )
            self.stack_button.setEnabled(False)
            self.stack_button.setToolTip("Siril could not be found.")
            self.locate_button.show()
        else:
            self.siril_note.setText(f"Using {self.siril_path}")
            self.stack_button.setEnabled(True)
            self.stack_button.setToolTip("")
            self.locate_button.show()
        if self.script_path is not None:
            self.command_field.setText(run_command(self.script_path, self.siril_path))
            # Show the start of the command, not its tail: a long output path
            # otherwise scrolls the executable name out of sight.
            self.command_field.setCursorPosition(0)

    def _locate_siril(self) -> None:
        pattern = (
            "Siril (siril-cli.exe siril-cli)" if _is_windows() else "Siril (siril-cli*)"
        )
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Find siril-cli", "", f"{pattern};;All files (*)"
        )
        if chosen:
            self.siril_path = Path(chosen)
            self._refresh_siril_state()

    # -- running ---------------------------------------------------------

    def _start(self) -> None:
        if self.script_path is None or self.siril_path is None:
            return
        self.log.clear()
        self.log.show()
        self.busy.show()
        self.verdict.hide()
        self.open_image_button.hide()
        self.stack_button.setEnabled(False)
        self.stack_button.setText("Stacking...")
        self.stop_button.show()

        self.busy.setRange(0, 0)
        self._stage_text = "Starting Siril..."
        self.stage_line.setText(self._stage_text)
        self.stage_line.show()

        # A CLOCK, because a stack is the one thing here that can run for
        # half an hour. A bar that is sweeping and a stage name that has not
        # changed for a while look exactly like a hung program; a number that
        # is still counting says otherwise, and it is the only honest thing
        # left to show while Siril is inside a step that reports nothing.
        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._show_stage)
        self._clock.start()
        self.staged.emit("Starting Siril", -1, False)

        self.worker = SirilWorker(
            self.script_path,
            self.result_image,
            self.siril_path,
            stages=getattr(self, "stages", []),
            total_frames=getattr(self, "total_frames", 0),
        )
        self.worker.line.connect(self._append)
        self.worker.progressed.connect(self._on_progress)
        self.running.emit(True)
        self.worker.finished_run.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _stop(self) -> None:
        if self.worker is not None:
            self.worker.request_stop()
            self.stop_button.setEnabled(False)
            self._append("Stopping Siril...")

    def _append(self, line: str) -> None:
        # Siril prefixes almost everything with "log: "; it adds nothing here.
        self.log.appendPlainText(line[5:] if line.startswith("log: ") else line)

    def _on_progress(self, fraction: float, stage: str, determinate: bool) -> None:
        """Show where the run has got to, and be honest when we cannot know.

        A stage with no progress signal of its own -- StarNet, denoise, plate
        solving -- switches the bar back to its indeterminate sweep rather
        than freezing at a number or inventing one. The stage name is shown
        either way, because "Separating the stars from the rest" is worth far
        more than a percentage that is not real.
        """
        if determinate:
            percent = int(fraction * 100)
            if self.busy.maximum() == 0:
                self.busy.setRange(0, 100)
            # Never backwards, even if a later stage reports a lower number.
            self.busy.setValue(max(self.busy.value(), percent))
            self._stage_text = f"{stage}  ·  {self.busy.value()}%"
        else:
            self.busy.setRange(0, 0)
            self._stage_text = f"{stage}  ·  no progress to report on this step"
        self._show_stage()
        self.stage_line.show()
        self.staged.emit(
            stage, self.busy.value() if determinate else -1, determinate
        )

    def _took(self) -> str:
        """How long the run took, for the line that says it finished.

        Worth keeping: it is the number somebody needs to decide whether to
        put the kettle on next time, and it is gone the moment the clock
        stops if nothing writes it down.
        """
        elapsed = getattr(self, "_elapsed", None)
        if elapsed is None:
            return ""
        seconds = elapsed.elapsed() // 1000
        if seconds < 60:
            return f" in {seconds}s"
        return f" in {seconds // 60}m {seconds % 60:02d}s"

    def _show_stage(self) -> None:
        """The stage, and how long this has been going."""
        text = getattr(self, "_stage_text", "")
        elapsed = getattr(self, "_elapsed", None)
        if elapsed is not None:
            seconds = elapsed.elapsed() // 1000
            clock = f"{seconds // 60}:{seconds % 60:02d}"
            text = f"{text}  ·  {clock}" if text else clock
        self.stage_line.setText(text)

    def _end_run(self) -> None:
        clock = getattr(self, "_clock", None)
        if clock is not None:
            clock.stop()
        self.running.emit(False)
        self.busy.hide()
        self.stage_line.hide()
        self.stop_button.hide()
        self.stop_button.setEnabled(True)
        self.stack_button.setEnabled(self.siril_path is not None)
        self.stack_button.setText("Stack now in Siril")

    def _on_finished(self, result) -> None:
        self._end_run()
        self.verdict.show()

        if result.cancelled:
            self.verdict.setText(
                f'<span style="color:{theme.WARN};font-weight:600;">Stopped.</span> '
                f'<span style="color:{theme.TEXT_MUTED};">Siril was stopped part '
                f'way through. The project folder is still there, so you can '
                f'run it again whenever you like.</span>'
            )
            self.finished.emit(False)
            return

        if result.ok:
            where = result.output_image or self.result_image
            took = self._took()
            # A preview that could not be written is worth a sentence, not a
            # failure: the stack is the deliverable and it is on disk.
            note = "".join(
                f'<br><span style="color:{theme.WARN};">{warning}</span>'
                for warning in getattr(result, "warnings", [])
            )
            self.verdict.setText(
                f'<span style="color:{theme.OK};font-weight:600;">Stacked.</span> '
                f'<span style="color:{theme.TEXT_MUTED};">Siril finished and '
                f'wrote {where.name if where else self.stack_name + ".fit"}'
                f'{took}.</span>'
                + note
            )
            if result.output_image is not None:
                self.open_image_button.show()
            self.finished.emit(True)
            return

        detail = result.error_lines[0] if result.error_lines else (
            f"Siril exited with code {result.exit_code}."
        )
        # The log pane strips Siril's "log: " prefix; the one line we promote
        # into the verdict has to be stripped too, or the sentence somebody
        # is meant to READ starts with a piece of another program's plumbing.
        if detail.startswith("log: "):
            detail = detail[5:]
        detail = detail[:1].upper() + detail[1:] if detail else detail
        self.verdict.setText(
            f'<span style="color:{theme.ERROR};font-weight:600;">Siril did not '
            f'finish.</span> '
            f'<span style="color:{theme.TEXT_MUTED};">{detail} The full log is '
            f'above. The project folder is untouched, so you can fix the '
            f'problem and run it again.</span>'
        )
        self.finished.emit(False)

    def _on_failed(self, message: str) -> None:
        self._end_run()
        self.verdict.show()
        self.verdict.setText(
            f'<span style="color:{theme.ERROR};font-weight:600;">Could not run '
            f'Siril.</span> '
            f'<span style="color:{theme.TEXT_MUTED};">{message}</span>'
        )
        self.finished.emit(False)

    # -- small actions ---------------------------------------------------

    def _copy_command(self) -> None:
        QGuiApplication.clipboard().setText(self.command_field.text())
        self.copy_button.setText("Copied")
        # And then back to Copy. It said "Copied" for the rest of the
        # session, which turns a confirmation into a label: come back ten
        # minutes later and the button claims something is on the clipboard
        # that may well have been replaced five times since.
        QTimer.singleShot(1600, lambda: self.copy_button.setText("Copy"))

    def _open_folder(self) -> None:
        if self.output_dir is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output_dir)))

    def _open_image(self) -> None:
        if self.result_image is not None and self.result_image.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result_image)))

    def shutdown(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.request_stop()
            self.worker.wait(5000)


def _is_windows() -> bool:
    import sys

    return sys.platform == "win32"
