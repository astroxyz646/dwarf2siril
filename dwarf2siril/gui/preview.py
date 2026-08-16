"""Before/after view of what the optional layers did.

These are ordinary JPEGs that Siril wrote while running the script -- Qt
displays them natively, so nothing here needs an imaging library. They are
downscaled snapshots for looking at; the real output is the .fit, and the
panel says so rather than letting a preview imply the file was resized.

The comparison is a swipe divider: both images are drawn in the same place
and a draggable line decides how much of each you see. Comparing an
astro image before and after a subtle change is exactly the case where
flicking between two tabs loses the difference, and side-by-side halves the
size of both.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme

# The stages the script writes, in order, with the caption each gets.
STAGE_LABELS = [
    ("00_stacked", "Plain stack"),
    ("01_background", "Background removed"),
    ("02_solved", "Plate solved"),
    ("03_colour", "Colour calibrated"),
    ("04_denoised", "Denoised"),
    ("05_stars_reduced", "Stars reduced"),
    ("99_final", "Final"),
]

# Below this mean difference per channel (out of 255) two previews are the
# same picture as far as anybody's eyes are concerned. Chosen so that JPEG
# rounding between two saves of identical pixels counts as identical, while a
# real change -- even a subtle denoise -- does not.
IDENTICAL = 0.35

HANDLE_WIDTH = 3
HANDLE_GRAB = 14


def _mean_difference(before: QPixmap, after: QPixmap) -> float | None:
    """Average per-channel difference between two previews, 0-255.

    Measured on a small scaled copy of each: the question is "would a person
    see a difference", not "are these byte-identical", and a 96px thumbnail
    answers that at a fraction of the cost. Returns None when the two cannot
    be compared at all.
    """
    if before.isNull() or after.isNull():
        return None
    size = QSize(96, 96)
    mode = Qt.AspectRatioMode.IgnoreAspectRatio
    smooth = Qt.TransformationMode.SmoothTransformation
    left = before.toImage().scaled(size, mode, smooth).convertToFormat(
        QImage.Format.Format_RGB888
    )
    right = after.toImage().scaled(size, mode, smooth).convertToFormat(
        QImage.Format.Format_RGB888
    )
    if left.size() != right.size():
        return None

    total = 0
    count = 0
    for y in range(left.height()):
        # constScanLine hands back a memoryview of the row's bytes. RGB888 is
        # three bytes per pixel and all three are compared: stepping over two
        # of them measured the red channel alone, which misses a change that
        # lands mostly in blue -- colour calibration, of all things.
        a = left.constScanLine(y)
        b = right.constScanLine(y)
        for index in range(min(len(a), len(b))):
            total += abs(a[index] - b[index])
            count += 1
    return total / count if count else None


class SwipeView(QWidget):
    """Two images, one on top of the other, split by a draggable line."""

    def __init__(self) -> None:
        super().__init__()
        self.before = QPixmap()
        self.after = QPixmap()
        self.before_label = "Before"
        self.after_label = "After"
        self.split = 0.5
        self._dragging = False
        self.setMinimumHeight(360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.SplitHCursor)

    def set_images(
        self, before: QPixmap, after: QPixmap, before_label: str, after_label: str
    ) -> None:
        self.before = before
        self.after = after
        self.before_label = before_label
        self.after_label = after_label
        self.update()

    def _target_rect(self) -> QRect:
        """Where the image sits, letterboxed to keep its aspect ratio."""
        source = self.before if not self.before.isNull() else self.after
        if source.isNull():
            return QRect()
        scaled = source.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        return QRect(QPoint(x, y), scaled)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.BG))

        rect = self._target_rect()
        if rect.isEmpty():
            painter.setPen(QColor(theme.TEXT_FAINT))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "No preview available"
            )
            return

        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        if not self.after.isNull():
            painter.drawPixmap(rect, self.after)

        # The "before" half is clipped to the left of the divider.
        if not self.before.isNull():
            cut = int(rect.width() * self.split)
            painter.save()
            painter.setClipRect(QRect(rect.left(), rect.top(), cut, rect.height()))
            painter.drawPixmap(rect, self.before)
            painter.restore()

        x = rect.left() + int(rect.width() * self.split)
        painter.setPen(QPen(QColor(theme.ACCENT), HANDLE_WIDTH))
        painter.drawLine(x, rect.top(), x, rect.bottom())

        # Grab handle, so the line reads as draggable rather than decorative.
        painter.setBrush(QColor(theme.ACCENT))
        painter.setPen(Qt.PenStyle.NoPen)
        centre = rect.top() + rect.height() // 2
        painter.drawEllipse(QPoint(x, centre), 13, 13)
        painter.setPen(QPen(QColor(theme.ACCENT_FG), 2))
        painter.drawLine(x - 5, centre, x - 2, centre)
        painter.drawLine(x + 2, centre, x + 5, centre)

        self._draw_tag(painter, rect, self.before_label, left=True)
        self._draw_tag(painter, rect, self.after_label, left=False)

    def _draw_tag(self, painter: QPainter, rect: QRect, text: str, left: bool) -> None:
        font = QFont()
        font.setPointSizeF(9.5)
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 24
        height = 26
        y = rect.bottom() - height - 12
        x = rect.left() + 12 if left else rect.right() - width - 12

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 190))
        painter.drawRoundedRect(QRect(x, y, width, height), 13, 13)
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(
            QRect(x, y, width, height), Qt.AlignmentFlag.AlignCenter, text
        )

    # -- dragging --------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._dragging = True
        self._move_split(event.position().x())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._dragging:
            self._move_split(event.position().x())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._dragging = False

    def _move_split(self, x: float) -> None:
        rect = self._target_rect()
        if rect.isEmpty() or rect.width() == 0:
            return
        self.split = min(1.0, max(0.0, (x - rect.left()) / rect.width()))
        self.update()


class PreviewPanel(QFrame):
    """Step 5: look at what happened."""

    open_folder_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.previews: list[tuple[str, str, Path]] = []
        self.result_fit: Path | None = None
        self.solved_note = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("Before and after")
        title.setObjectName("CardTitle")
        header.addWidget(title)
        header.addStretch(1)

        header.addWidget(self._muted("Compare"))
        self.before_pick = QComboBox()
        self.before_pick.currentIndexChanged.connect(self._refresh)
        header.addWidget(self.before_pick)
        header.addWidget(self._muted("with"))
        self.after_pick = QComboBox()
        self.after_pick.currentIndexChanged.connect(self._refresh)
        header.addWidget(self.after_pick)
        layout.addLayout(header)

        self.applied = QLabel("")
        self.applied.setObjectName("Muted")
        self.applied.setWordWrap(True)
        layout.addWidget(self.applied)

        # Ticked, and not in the list below. Its own line rather than part of
        # the finding, because it is about the RUN and is true whatever two
        # stages happen to be selected, whereas the finding is about the pair
        # currently being compared and changes with the dropdowns.
        self.missing = QLabel("")
        self.missing.setWordWrap(True)
        self.missing.setTextFormat(Qt.TextFormat.RichText)
        self.missing.hide()
        layout.addWidget(self.missing)

        # Where a step that changes no pixels gets to say so, and where the
        # plate solve reports its actual result. A comparison that shows
        # nothing MUST say it shows nothing -- otherwise the honest
        # conclusion for the user is that the feature is broken.
        self.finding = QLabel("")
        self.finding.setWordWrap(True)
        self.finding.setTextFormat(Qt.TextFormat.RichText)
        self.finding.hide()
        layout.addWidget(self.finding)

        self.swipe = SwipeView()
        layout.addWidget(self.swipe, 1)

        layout.addWidget(
            self._muted(
                "Drag the line to compare. These are downscaled JPEGs for "
                "looking at -- your real output is the full-resolution .fit, "
                "which is untouched by this view."
            )
        )

        footer = QHBoxLayout()
        self.file_note = QLabel("")
        self.file_note.setObjectName("Faint")
        self.file_note.setWordWrap(True)
        footer.addWidget(self.file_note, 1)

        open_folder = QPushButton("Open output folder")
        open_folder.setObjectName("Ghost")
        open_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        open_folder.clicked.connect(self.open_folder_requested.emit)
        footer.addWidget(open_folder)
        layout.addLayout(footer)

    @staticmethod
    def _muted(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Muted")
        label.setWordWrap(True)
        return label

    def load_from(
        self,
        output_dir: Path,
        stack_name: str,
        post=None,
        solvable: bool = True,
    ) -> bool:
        """Point the panel at a finished run. False if there is nothing to show.

        A missing preview is a missing preview, never a failed stack, so this
        returns quietly rather than raising.

        Takes the PostOptions rather than a list of labels, so the "Applied:"
        line and the list of stages come from ONE source. They used to be
        computed separately -- the line from the ticked boxes, the stages
        from the JPEGs on disk -- and nothing reconciled them, which is how a
        ticked layer could be named as applied and silently absent from the
        comparison at the same time.
        """
        preview_dir = output_dir / "previews"
        self.previews = []
        for key, caption in STAGE_LABELS:
            path = preview_dir / f"{key}.jpg"
            if path.is_file():
                self.previews.append((key, caption, path))

        if len(self.previews) < 2:
            return False

        processed = output_dir / f"{stack_name}_processed.fit"
        self.result_fit = processed if processed.is_file() else output_dir / f"{stack_name}.fit"

        applied = post.enabled_labels() if post is not None else []
        if applied:
            self.applied.setText("Applied: " + ", ".join(applied) + ".")
        else:
            self.applied.setText("No optional layers were applied.")

        self._explain_missing(post, solvable)

        self.file_note.setText(
            f"Full-resolution result: {self.result_fit.name}"
            + (
                f"   ·   plain stack kept as {stack_name}.fit"
                if self.result_fit.name.endswith("_processed.fit")
                else ""
            )
        )

        for box in (self.before_pick, self.after_pick):
            box.blockSignals(True)
            box.clear()
            for _key, caption, _path in self.previews:
                box.addItem(caption)
            box.blockSignals(False)

        self.solved_note = self._describe_solve(self.result_fit)

        self.before_pick.setCurrentIndex(0)
        self.after_pick.setCurrentIndex(len(self.previews) - 1)
        self._refresh()
        return True

    def _explain_missing(self, post, solvable: bool) -> None:
        """Name every ticked layer that is not in the list, and say why.

        THE DEFECT THIS FIXES: a layer the user ticked could be named in
        "Applied:" and absent from the Compare dropdowns at the same time,
        with nothing said about it. There is no reading of that which is not
        alarming -- either the layer did nothing, or the app is hiding
        something -- and both are worse than the truth, which is usually
        mundane: the frames could not be solved, or the layer has no step of
        its own by design.

        Silence is the one answer that is never right here. A layer with no
        known reason still gets a line saying that Siril wrote no preview for
        it, because "we do not know why" is information and an empty panel is
        not.
        """
        self.missing.hide()
        if post is None:
            return

        have = {key for key, _caption, _path in self.previews}
        notes: list[str] = []
        for key, label, reason in post.expected_previews(solvable):
            if key and key in have:
                continue
            if not reason:
                reason = (
                    "Siril wrote no preview for it, so there is nothing to "
                    "compare -- the layer itself may still have run"
                )
            notes.append(f"<b>{label}</b> is not in the list: {reason}.")

        if not notes:
            return

        self.missing.setText(
            f'<span style="color:{theme.TEXT_MUTED};">' + "<br>".join(notes) + "</span>"
        )
        self.missing.show()

    @staticmethod
    def _describe_solve(path: Path | None) -> str:
        """What the plate solve actually resolved this field to, if anything.

        The solve's result is text, not a picture -- it writes sky
        coordinates and touches no pixels -- so this is where the evidence
        for it belongs. Reading the header is also the only honest way to
        answer it: the log saying "solve succeeded" is not the same as the
        file the user opens carrying the solution.
        """
        if path is None or not path.is_file():
            return ""
        try:
            from ..fits_header import read_header

            header = read_header(path)
        except Exception:  # noqa: BLE001 - a note is never worth a crash
            return ""

        if not header.get("PLTSOLVD"):
            return ""
        centre_ra = str(header.get("OBJCTRA", "")).strip()
        centre_dec = str(header.get("OBJCTDEC", "")).strip()
        scale = header.get("CDELT2")
        parts = []
        if centre_ra and centre_dec:
            parts.append(f"centred on {centre_ra} {centre_dec}")
        if isinstance(scale, (int, float)) and scale:
            parts.append(f"{abs(scale) * 3600:.2f} arcsec per pixel")
        detail = ", ".join(parts)
        return (
            "Plate solved: your image now carries real sky coordinates"
            + (f" — {detail}." if detail else ".")
        )

    def _refresh(self) -> None:
        if not self.previews:
            return
        before_index = max(0, min(self.before_pick.currentIndex(), len(self.previews) - 1))
        after_index = max(0, min(self.after_pick.currentIndex(), len(self.previews) - 1))

        before = QPixmap(str(self.previews[before_index][2]))
        after = QPixmap(str(self.previews[after_index][2]))
        self.swipe.set_images(
            before,
            after,
            self.previews[before_index][1],
            self.previews[after_index][1],
        )
        self._explain(before_index, after_index, before, after)

    def _explain(self, before_index, after_index, before, after) -> None:
        """Say plainly when there is nothing to see, and why.

        This is the bug the operator found: they compared the plain stack
        with the final image on a run where the only layer was plate solving,
        saw an identical picture, and concluded it had not worked. It HAD
        worked. Plate solving writes coordinates into the header and does not
        alter a single pixel, so an identical picture is the correct result
        -- and showing it without a word of explanation invites exactly that
        conclusion.
        """
        notes: list[str] = []

        if before_index == after_index:
            notes.append("You are comparing a stage with itself.")
        else:
            difference = _mean_difference(before, after)
            if difference is not None and difference <= IDENTICAL:
                notes.append(
                    "<b>These two are the same picture.</b> Nothing between "
                    "them changed a single pixel."
                )
                if self.solved_note:
                    notes.append(
                        "That is expected here: plate solving adds sky "
                        "coordinates to the file, it does not retouch the "
                        "image."
                    )

        if self.solved_note:
            notes.append(self.solved_note)

        if notes:
            self.finding.setText(
                f'<span style="color:{theme.TEXT_MUTED};">'
                + " ".join(notes)
                + "</span>"
            )
            self.finding.show()
        else:
            self.finding.hide()
