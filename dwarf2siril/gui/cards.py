"""The cards the user actually reads: one per target group, one per drive.

Density first, depth on click. A group card shows target, settings, frame
count, integration and its calibration in a block small enough that several
sit side by side and can be compared at a glance. Everything else -- the
individual sessions, their tick boxes, the full text of any warning -- is one
click away rather than always on screen.

The compatibility checks are still surfaced rather than hidden: a group that
cannot be stacked says so on its face and in colour, and the reason is in the
detail rather than lost.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..model import LightSession, SessionGroup, format_exposure
from . import theme
from .album import show_album
from .thumbnails import THUMBNAIL_WIDTH, load_async

# Wide enough for the settings line without wrapping, narrow enough that a
# 1280px window fits three across and a small laptop window still fits two.
CARD_WIDTH = 330

# 16:9, matching the DWARF's sensor, so the preview is not letterboxed.
THUMBNAIL_HEIGHT = 58

# Every collapsed card is exactly this tall, so a row of them has one clean
# bottom edge and the Prepare buttons line up across the grid.
#
# The height comes from RESERVING the optional rows rather than from padding
# up to the tallest card: a group with no warning keeps an empty line where
# its warning would be, instead of shrinking and pulling its button up. That
# is what was making the grid look unresolved -- every card was a slightly
# different height depending on how much it happened to have to say.
#
# 204 rather than 196 because 196 was SEVEN PIXELS SHORTER than the card's
# own contents need. Nothing looked obviously wrong -- the frame count and
# the integration time were simply drawn tighter than Qt wanted, losing the
# space under their descenders -- which is exactly the sort of thing that is
# invisible until a check measures it. Found by the clipping check running
# inside the packaged app against a real card, where cards actually exist;
# the unit tests cannot see it because they have no card to scan.
CARD_HEIGHT = 204


def _label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


class _ClickableImage(QLabel):
    """A QLabel that reports clicks, for the thumbnail-opens-the-picture case."""

    clicked = Signal()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        # Release rather than press, so dragging off the image cancels the
        # click the way any other control behaves.
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFrameShape(QFrame.Shape.HLine)
    return line


class DriveTile(QPushButton):
    """One detected DWARF card, offered as a single click."""

    def __init__(self, label: str, path_text: str, detail: str) -> None:
        super().__init__()
        self.setObjectName("DriveTile")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setText("")
        # 84 rather than 66: the three lines need about 48px between them,
        # and the insets below add another 28. 66 was sized for the old
        # 2px inset and would now squash the tile's own contents.
        self.setMinimumSize(250, 84)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        # THE PADDING LIVES HERE, not in the stylesheet. This is a
        # QPushButton with a layout inside it, and a style sheet's `padding`
        # only insets what the BUTTON itself draws -- its own text and icon,
        # which are empty here. Child widgets are placed by the layout, and
        # the layout only knows about these margins. The stylesheet said
        # `padding: 16px 18px` and looked right on the page while the tile on
        # screen had 4px at the sides and 2px top and bottom, which is why
        # the title sat against the top edge and the amber line against the
        # bottom one.
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(2)

        title = _label(label)
        title.setStyleSheet("font-size: 11pt; font-weight: 600;")
        layout.addWidget(title)

        path_label = _label(path_text)
        path_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-family: {theme.MONO_STACK}; "
            f"font-size: 8.5pt;"
        )
        layout.addWidget(path_label)

        detail_label = _label(detail)
        detail_label.setStyleSheet(f"color: {theme.ACCENT}; font-size: 8.5pt;")
        layout.addWidget(detail_label)


class SessionRow(QWidget):
    """One session inside a group, with the tick that includes it."""

    toggled = Signal()

    def __init__(self, session: LightSession) -> None:
        super().__init__()
        self.session = session

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(7)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(True)
        self.checkbox.stateChanged.connect(lambda _: self.toggled.emit())
        layout.addWidget(self.checkbox)

        text = QVBoxLayout()
        text.setSpacing(0)
        when = session.started or session.path.name
        row = _label(f"{when}  ·  {session.frame_count} frames")
        row.setStyleSheet("font-size: 9pt;")
        text.addWidget(row)

        # The DWARF's own live stacker forms an opinion about frame quality;
        # how many it threw away is a fair summary of how the night went.
        if session.shots_taken and session.shots_stacked is not None:
            rejected = session.shots_taken - session.shots_stacked
            if rejected > 0:
                note = _label(
                    f"the DWARF rejected {rejected} of {session.shots_taken} "
                    f"while live-stacking",
                    "Faint",
                )
                text.addWidget(note)
        layout.addLayout(text, 1)
        return


class GroupCard(QFrame):
    """One stackable target, compact by default."""

    changed = Signal()
    build_requested = Signal(object)
    grid_requested = Signal(object)

    def __init__(self, group: SessionGroup) -> None:
        super().__init__()
        self.group = group
        self.setObjectName("Card")
        self.rows: list[SessionRow] = []
        self._expanded = False
        self._mode = "stack"
        self.setFixedWidth(CARD_WIDTH)
        self.setFixedHeight(CARD_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(7)

        # -- headline: target + status ----------------------------------
        head = QHBoxLayout()
        head.setSpacing(7)
        self.title = _label(group.display_target, "CardTitle")
        head.addWidget(self.title)
        self.status_pill = _label("")
        self.status_pill.setTextFormat(Qt.TextFormat.RichText)
        head.addWidget(self.status_pill)

        # Mount mode on the face of every card. EQ is the better way to
        # shoot, so alt-az is marked and EQ is left quiet rather than both
        # being badged as if they were equivalent.
        self.mode_pill = _label("")
        self.mode_pill.setTextFormat(Qt.TextFormat.RichText)
        head.addWidget(self.mode_pill)

        head.addStretch(1)
        outer.addLayout(head)

        # The settings line and the two big figures sit on the left; the
        # thumbnail fills the empty space to their right. Placing it there
        # rather than above or below is what keeps it free: the card is no
        # taller than it was before thumbnails existed.
        body = QHBoxLayout()
        body.setSpacing(10)
        left = QVBoxLayout()
        left.setSpacing(7)

        # -- one line of settings, not six labelled columns --------------
        first = group.sessions[0]
        settings = " · ".join(
            part
            for part in (
                format_exposure(first.exposure),
                f"gain {first.gain}",
                f"{first.binning}×{first.binning}",
                first.filter_name or None,
            )
            if part
        )
        self.settings_label = _label(settings, "Muted", wrap=True)
        left.addWidget(self.settings_label)

        # -- the two numbers that matter, given room ---------------------
        figures = QHBoxLayout()
        figures.setSpacing(16)
        self.frames_value = _label("")
        self.frames_value.setStyleSheet("font-size: 15pt; font-weight: 600;")
        frames_block = QVBoxLayout()
        frames_block.setSpacing(0)
        frames_block.addWidget(self.frames_value)
        frames_block.addWidget(_label("frames", "Faint"))
        figures.addLayout(frames_block)

        self.integration_value = _label("")
        self.integration_value.setStyleSheet("font-size: 15pt; font-weight: 600;")
        integration_block = QVBoxLayout()
        integration_block.setSpacing(0)
        integration_block.addWidget(self.integration_value)
        integration_block.addWidget(_label("integration", "Faint"))
        figures.addLayout(integration_block)
        figures.addStretch(1)
        left.addLayout(figures)

        body.addLayout(left, 1)
        body.addWidget(self._thumbnail_block(), 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(body)

        # -- calibration and session count on ONE reserved line ----------
        # Both used to be their own optional rows, which is where most of the
        # ragged height came from. One row, always present.
        self.status_line = _label("")
        self.status_line.setTextFormat(Qt.TextFormat.RichText)
        self.status_line.setFixedHeight(16)
        outer.addWidget(self.status_line)

        # -- one reserved line for anything blocking ---------------------
        # Always present even when empty, so a card with nothing wrong is
        # exactly as tall as one with a problem.
        self.issue_line = _label("")
        self.issue_line.setTextFormat(Qt.TextFormat.RichText)
        self.issue_line.setFixedHeight(15)
        outer.addWidget(self.issue_line)

        # -- detail, hidden until asked for ------------------------------
        self.detail = QWidget()
        self.detail.setObjectName("Plain")
        detail_layout = QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(0, 4, 0, 0)
        detail_layout.setSpacing(4)
        detail_layout.addWidget(divider())
        detail_layout.addWidget(_label("SESSIONS", "Faint"))
        for session in group.sessions:
            row = SessionRow(session)
            row.toggled.connect(self._on_toggle)
            self.rows.append(row)
            detail_layout.addWidget(row)

        self.issues_box = QVBoxLayout()
        self.issues_box.setSpacing(3)
        detail_layout.addLayout(self.issues_box)
        self.detail.hide()
        outer.addWidget(self.detail)

        # Pushes the actions to the bottom edge, so Prepare sits on the same
        # line on every card in the row whatever each has above it.
        outer.addStretch(1)

        # -- actions -----------------------------------------------------
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.detail_button = QPushButton("Details")
        self.detail_button.setObjectName("Link")
        self.detail_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.detail_button.clicked.connect(self._toggle_detail)
        actions.addWidget(self.detail_button)

        # The operator named this control and its tooltip; both are theirs.
        self.grid_button = QPushButton("View stack grid")
        self.grid_button.setObjectName("Link")
        self.grid_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.grid_button.setToolTip(
            "Manage your stack, remove any unwanted frames manually"
        )
        self.grid_button.clicked.connect(lambda: self.grid_requested.emit(self))
        actions.addWidget(self.grid_button)

        actions.addStretch(1)

        self.build_button = QPushButton("Prepare")
        self.build_button.setObjectName("Primary")
        self.build_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.build_button.clicked.connect(lambda: self.build_requested.emit(self))
        actions.addWidget(self.build_button)
        outer.addLayout(actions)

        self.refresh()

    def _thumbnail_block(self) -> QWidget:
        """The DWARF's own preview of this target, or nothing at all.

        Two things this must not do. It must not imply it is a preview of
        what this tool will produce -- it is the telescope's own live stack,
        so it is captioned as such and sits beside the session facts rather
        than near the before/after panel. And it must not leave a hole: if
        the file is missing or unreadable the whole block is removed, and
        the card looks exactly as it did before thumbnails existed.
        """
        holder = QWidget()
        holder.setObjectName("Plain")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.thumbnail_label = _ClickableImage()
        self.thumbnail_label.setFixedSize(THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)

        # Clickable only when there is something to open. A card whose
        # session never got a full-size picture simply does not respond,
        # rather than opening an empty window.
        if self.group.album_image is not None:
            self.thumbnail_label.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
            self.thumbnail_label.setStyleSheet(
                f"QLabel {{ background: {theme.BG}; "
                f"border: 1px solid {theme.BORDER}; border-radius: 4px; }}"
                f"QLabel:hover {{ border: 1px solid {theme.ACCENT}; }}"
            )
            self.thumbnail_label.setCursor(Qt.CursorShape.PointingHandCursor)
            self.thumbnail_label.setToolTip(
                "Click to see your DWARF's own picture full size"
            )
            self.thumbnail_label.clicked.connect(self._open_album)
        else:
            self.thumbnail_label.setStyleSheet(
                f"background: {theme.BG}; border: 1px solid {theme.BORDER}; "
                f"border-radius: 4px;"
            )
        layout.addWidget(self.thumbnail_label)

        # No caption under the picture. It read as a label stuck across the
        # bottom of every thumbnail, and because it was wider than the image
        # it made the thumbnails look different widths from card to card.
        # The attribution moves to the tooltip here and is stated outright in
        # the full-size viewer, which is where somebody might actually
        # mistake it for this tool's output.
        attribution = (
            "Your DWARF's own live-stacked preview of this session — not a "
            "preview of what this tool will produce."
        )
        self.thumbnail_label.setToolTip(
            attribution + " Click to see it full size."
            if self.group.album_image is not None
            else attribution
        )

        # Hidden until an image actually arrives, so a missing or corrupt
        # file costs the card nothing.
        holder.hide()
        self._thumbnail_holder = holder

        path = self.group.thumbnail
        if path is not None:
            load_async(path, self._on_thumbnail, THUMBNAIL_WIDTH)
        return holder

    def _open_album(self) -> None:
        """Show the DWARF's full-size picture. Never a dead end or a crash."""
        try:
            self._album_window = show_album(
                self.group.display_target, self.group.album_image, self
            )
        except Exception:  # noqa: BLE001 - a picture is not worth a crash
            self._album_window = None

    def _on_thumbnail(self, image) -> None:
        if image is None:
            return  # stays hidden; the card is the card it always was
        try:
            pixmap = QPixmap.fromImage(image)
        except Exception:  # noqa: BLE001
            return
        if pixmap.isNull():
            return
        self.thumbnail_label.setPixmap(
            pixmap.scaled(
                THUMBNAIL_WIDTH,
                THUMBNAIL_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.thumbnail_label.setScaledContents(False)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumbnail_holder.show()

    # -- state -----------------------------------------------------------

    @property
    def selected_sessions(self) -> list[LightSession]:
        return [row.session for row in self.rows if row.checkbox.isChecked()]

    def _toggle_detail(self) -> None:
        self._expanded = not self._expanded
        self.detail.setVisible(self._expanded)
        if self._expanded:
            # Only an opened card is allowed to be a different height; the
            # uniform grid is about the collapsed state.
            self.setMinimumHeight(CARD_HEIGHT)
            self.setMaximumHeight(16777215)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
            self.detail_button.setText("Hide")
        else:
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self.setFixedHeight(CARD_HEIGHT)
            self.refresh()   # puts the note count back on the button
        self.updateGeometry()
        # The flow layout sizes rows from the tallest card, so it has to be
        # told that this one changed height.
        if self.parentWidget() is not None and self.parentWidget().layout():
            self.parentWidget().layout().invalidate()
            self.parentWidget().adjustSize()

    def _on_toggle(self) -> None:
        if not self.selected_sessions and self.rows:
            self.rows[0].checkbox.setChecked(True)
        self.changed.emit()
        self.refresh()

    def set_group(self, group: SessionGroup) -> None:
        self.group = group
        self.refresh()

    def set_mode(self, mode: str) -> None:
        """Show the action this mode is actually about.

        The card itself does not change -- same target, same numbers, same
        place on screen. Only what it offers to do changes, which is the
        whole point of making a mode a lens rather than a separate screen.
        """
        self._mode = mode
        stacking = mode != "manage"
        self.build_button.setVisible(stacking)

        # In Frames mode the grid IS the job, so it stops being a quiet link
        # and becomes the button on the card.
        self.grid_button.setObjectName("Link" if stacking else "Primary")
        self.grid_button.setText(
            "View stack grid" if stacking else "Go through the frames"
        )
        self.grid_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.grid_button.style().unpolish(self.grid_button)
        self.grid_button.style().polish(self.grid_button)

    def set_busy(self, busy: bool) -> None:
        self.build_button.setEnabled(not busy and self.group.is_buildable)
        self.build_button.setText("Working..." if busy else "Prepare")

    def refresh(self) -> None:
        group = self.group

        self.frames_value.setText(str(group.total_frames))
        self.integration_value.setText(group.describe_integration())

        if group.mount_mode == "alt-az":
            self.mode_pill.setText(theme.pill("ALT-AZ", theme.TEXT_MUTED))
            self.mode_pill.setToolTip(
                "Shot without a wedge, so the field rotates between frames. "
                "This stacks fine, but the corners end up built from fewer "
                "frames and are slightly noisier. EQ mode keeps the whole "
                "frame equally good."
            )
            self.mode_pill.show()
        elif group.mount_mode == "unknown":
            self.mode_pill.setText(theme.pill("MODE UNKNOWN", theme.WARN))
            self.mode_pill.setToolTip(
                "This session does not record whether it was EQ or alt-az."
            )
            self.mode_pill.show()
        else:
            self.mode_pill.hide()

        if group.errors:
            self.status_pill.setText(theme.pill("CAN'T STACK", theme.ERROR))
            self.setObjectName("CardBad")
        elif group.warnings:
            self.status_pill.setText(theme.pill("READY", theme.WARN))
            self.setObjectName("CardSelected")
        else:
            self.status_pill.setText(theme.pill("READY", theme.OK))
            self.setObjectName("CardSelected")
        self.style().unpolish(self)
        self.style().polish(self)

        # Calibration as a mark and a number rather than a sentence. The
        # sentence moves to the tooltip, but the COLOUR stays on the face --
        # "no darks" has to be obvious without hovering, so it keeps a red
        # cross and the word, not just an icon.
        if group.darks:
            mark, colour = "✓", theme.OK
            calibration = f"{group.total_dark_frames} darks"
            explain = (
                f"{group.total_dark_frames} dark frames from "
                f"{len(group.darks)} of your own DWARF_DARK set"
                f"{'s' if len(group.darks) > 1 else ''}."
            )
        elif group.master_dark:
            mark, colour = "◆", theme.WARN
            calibration = f"{group.master_dark.stack_count} darks"
            explain = (
                f"No dark set of yours matched, so the DWARF's own master "
                f"dark is being used — built by the telescope from "
                f"{group.master_dark.stack_count} frames."
            )
        else:
            mark, colour = "✕", theme.ERROR
            calibration = "no darks"
            explain = (
                "No darks match these lights, so the stack will not be "
                "calibrated. Expect amp glow and hot pixels."
            )

        sessions = len(self.selected_sessions) or len(group.sessions)
        session_text = f"{sessions} sessions" if sessions > 1 else "1 session"
        self.status_line.setText(
            f'<span style="color:{colour};font-weight:600;">{mark} {calibration}</span>'
            f'<span style="color:{theme.TEXT_FAINT};">   ·   {session_text}</span>'
        )
        self.status_line.setToolTip(explain)

        # Only something BLOCKING earns the reserved line. Notes are folded
        # into the Details control rather than getting a row of their own,
        # since both were pointing at the same place.
        recipe = group.dark_recipe
        if group.errors:
            self.issue_line.setText(
                f'<span style="color:{theme.ERROR};">'
                f"{_shorten(group.errors[0].message, 46)}</span>"
            )
            self.issue_line.setToolTip(group.errors[0].message)
        elif recipe is not None:
            # THE ONE THING ON THIS CARD THAT IMPROVES THEIR PICTURES.
            # "no darks" states a fact; this says what to do about it, with
            # the exact two numbers the telescope needs, taken from these
            # very frames. It sits in the line already reserved for
            # something being wrong, so it costs no height, and it is
            # phrased as an offer rather than a telling-off.
            exposure, gain = recipe
            self.issue_line.setText(
                f'<span style="color:{theme.TEXT_MUTED};">Fix next time: '
                f'</span><span style="color:{theme.ACCENT};">'
                f"{group.SUGGESTED_DARKS} darks at {exposure} · gain {gain}"
                f"</span>"
            )
            self.issue_line.setToolTip(group.dark_advice)
        else:
            self.issue_line.setText("")
            self.issue_line.setToolTip("")

        warnings = len(group.warnings)
        self.detail_button.setText(
            f"Details ({warnings})" if warnings else "Details"
        )
        self.detail_button.setToolTip(
            f"{warnings} note{'s' if warnings != 1 else ''} about this group"
            if warnings
            else "The sessions in this group"
        )

        while self.issues_box.count():
            item = self.issues_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for issue in group.errors:
            self.issues_box.addWidget(
                _issue_label(issue.message, theme.ERROR, "Can't stack")
            )
        for issue in group.warnings:
            self.issues_box.addWidget(_issue_label(issue.message, theme.WARN, "Note"))

        self.build_button.setEnabled(group.is_buildable)


def _shorten(text: str, limit: int = 74) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _issue_label(message: str, colour: str, prefix: str) -> QLabel:
    label = _label("", wrap=True)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setText(
        f'<span style="color:{colour};font-weight:600;">{prefix}:</span> '
        f'<span style="color:{theme.TEXT_MUTED};">{message}</span>'
    )
    label.setStyleSheet("font-size: 8.5pt;")
    return label
