"""Look at every frame in a session, and remove the ones you do not want.

An expert tool inside a beginner-friendly app: someone who never opens it is
unaffected, and someone who does should not need a manual.

It draws the DWARF's OWN per-frame JPEGs from the session's Thumbnail folder
-- one per sub, same name, ~40 KB. So there is no FITS decoding, no
debayering and no stretching to do, and nothing large is read to fill a grid.
A frame whose JPEG is missing is still listed and still deletable, just
without a picture.

The thing that makes this better than a file manager is the verdicts. The
quality filter already measures every frame during registration and already
turns that into plain English, so those faults are shown here and can be
sorted worst-first. That is also where somebody learns to trust the filter:
they see the frames it would drop, and agree.

Those measurements only exist AFTER a registration run, so before one the
grid says so rather than showing an empty column.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..deletion import delete, describe_size, folder_size
from ..model import LightSession
from . import theme
from .delete_dialog import DeleteRequest, confirm_delete
from .flow import FlowLayout
from .thumbnails import load_async
from .windows_theme import apply_dark_titlebar

TILE_WIDTH = 168
TILE_HEIGHT = 95      # 16:9, matching the sensor


@dataclass
class FrameItem:
    """One sub, its picture, and whatever is known about its quality."""

    path: Path
    thumbnail: Path | None
    index: int
    fault: str = ""          # "trailed", "clouded", "soft", "" if fine
    excluded: bool = False   # already left out of the stack

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def when(self) -> str:
        """The capture time out of the DWARF's own filename."""
        parts = self.path.stem.split("_")
        for part in parts:
            if len(part) >= 15 and part[:8].isdigit() and "-" in part:
                date, _, time = part.partition("-")
                return (
                    f"{date[0:4]}-{date[4:6]}-{date[6:8]} "
                    f"{time[0:2]}:{time[2:4]}:{time[4:6]}"
                )
        return ""


def frames_for(session: LightSession) -> list[FrameItem]:
    """Every sub in a session, paired with its thumbnail where there is one."""
    thumbs = session.path / "Thumbnail"
    items: list[FrameItem] = []
    for index, frame in enumerate(session.frames):
        candidate = thumbs / (frame.stem + ".jpg")
        items.append(
            FrameItem(
                path=frame,
                thumbnail=candidate if candidate.is_file() else None,
                index=index,
            )
        )
    return items


class FrameTile(QWidget):
    """One frame in the grid: picture, tick, and its fault if it has one."""

    clicked = Signal(object)
    toggled = Signal()

    def __init__(self, item: FrameItem) -> None:
        super().__init__()
        self.item = item
        self.selected = False
        self.setFixedSize(TILE_WIDTH, TILE_HEIGHT + 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.image = QLabel()
        self.image.setFixedSize(TILE_WIDTH, TILE_HEIGHT)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setText("no preview" if item.thumbnail is None else "")
        # No initial sheet here: _restyle() below paints it, and one place
        # deciding how a tile looks is one place to change it.
        layout.addWidget(self.image)

        self.caption = QLabel(f"#{item.index + 1}")
        self.caption.setObjectName("Caption")
        layout.addWidget(self.caption)

        if item.thumbnail is not None:
            load_async(item.thumbnail, self._on_image, TILE_WIDTH)
        self._restyle()

    def _on_image(self, image) -> None:
        if image is None:
            self.image.setText("no preview")
            return
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            self.image.setText("no preview")
            return
        self.image.setPixmap(
            pixmap.scaled(
                TILE_WIDTH,
                TILE_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self._restyle()

    def _restyle(self) -> None:
        # Chosen is a 2px accent edge; merely hovered is a 1px pale one. The
        # difference in weight, not just colour, is what keeps a pointer
        # passing over a tile from looking like a tile you picked.
        border = theme.ACCENT if self.selected else theme.BORDER
        width = 2 if self.selected else 1
        hover = theme.ACCENT if self.selected else theme.BORDER_STRONG
        self.image.setStyleSheet(
            f"QLabel {{ background: {theme.BG}; "
            f"border: {width}px solid {border}; "
            f"border-radius: {theme.RADIUS_XS + 2}px; "
            f"color: {theme.TEXT_FAINT}; font-size: 8pt; }}"
            f"QLabel:hover {{ border-color: {hover}; }}"
        )
        bits = [f"#{self.item.index + 1}"]
        colour = theme.TEXT_FAINT
        if self.item.fault:
            bits.append(self.item.fault)
            colour = theme.WARN
        if self.item.excluded:
            bits.append("not in stack")
            colour = theme.TEXT_FAINT
        self.caption.setText("  ·  ".join(bits))
        self.caption.setStyleSheet(f"color: {colour}; font-size: 8pt;")

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.set_selected(not self.selected)
                self.toggled.emit()
            else:
                self.clicked.emit(self.item)
        super().mouseReleaseEvent(event)


class StackGridWindow(QDialog):
    """Every frame in a session, with its verdict where one exists."""

    changed = Signal()

    def __init__(self, session: LightSession, verdicts=None, parent=None) -> None:
        super().__init__(parent)
        self._session = session
        self._verdicts = verdicts or {}

        self.setWindowTitle(f"{session.display_target} — stack grid")
        # SCOPED TO THIS DIALOG, not to everything inside it.
        #
        # A stylesheet set on a widget applies to that widget AND all its
        # descendants, and it OUTRANKS the application stylesheet for them.
        # A bare `background: ...` therefore repainted every button, box and
        # label in the dialog too -- which meant the filled Danger button in
        # here lost its red and drew its near-black label straight onto the
        # near-black ground. The most dangerous button in the app was
        # invisible in exactly the two windows that own it, while the
        # identical button in the main window looked right, because the main
        # window never set a stylesheet of its own.
        #
        # A type selector still applies only where it matches, so the dialog
        # gets its ground and its children go on being styled by theme.py.
        self.setStyleSheet(f"QDialog {{ background: {theme.BG}; }}")
        self.resize(1120, 760)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_3
        )
        layout.setSpacing(theme.SPACE_3)

        header = QHBoxLayout()
        header.setSpacing(theme.SPACE_3)
        title = QLabel(f"{session.display_target} — every frame")
        title.setObjectName("CardTitle")
        header.addWidget(title)
        header.addStretch(1)

        # SELECTING AT SCALE. A session is 40 to 400 frames, and the only way
        # to pick any of them was one Ctrl-click at a time -- fine for the
        # three you spotted, hopeless for "sort worst first and take the top
        # twenty", which is the whole reason the sort exists. Two buttons and
        # Ctrl+A, sitting beside the sort they get used with.
        self.select_all_button = QPushButton("Select all")
        self.select_all_button.setObjectName("Ghost")
        self.select_all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.select_all_button.setToolTip("Select every frame shown  (Ctrl+A)")
        self.select_all_button.clicked.connect(lambda: self._select_all(True))
        header.addWidget(self.select_all_button)

        self.select_none_button = QPushButton("Select none")
        self.select_none_button.setObjectName("Ghost")
        self.select_none_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.select_none_button.setToolTip("Clear the selection")
        self.select_none_button.clicked.connect(lambda: self._select_all(False))
        header.addWidget(self.select_none_button)

        header.addWidget(QLabel("Sort"))
        self.sort_box = QComboBox()
        self.sort_box.addItem("In the order they were taken", "order")
        self.sort_box.addItem("Worst quality first", "quality")
        self.sort_box.currentIndexChanged.connect(self._rebuild)
        header.addWidget(self.sort_box)
        layout.addLayout(header)

        self.note = QLabel("")
        self.note.setObjectName("Muted")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setStyleSheet("border: none;")
        self._host = QWidget()
        self._grid = FlowLayout(self._host, margin=0, spacing=theme.SPACE_3)
        area.setWidget(self._host)
        layout.addWidget(area, 1)

        footer = QHBoxLayout()
        footer.setSpacing(theme.SPACE_3)
        self.selection_label = QLabel("")
        self.selection_label.setWordWrap(True)
        footer.addWidget(self.selection_label, 1)

        hint = QLabel("Click a frame to see it full screen · Ctrl-click to select")
        hint.setObjectName("Faint")
        footer.addWidget(hint)

        self.delete_button = QPushButton("Delete selected")
        self.delete_button.setObjectName("Danger")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._delete_selected)
        footer.addWidget(self.delete_button)

        close = QPushButton("Close")
        close.setObjectName("Ghost")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        layout.addLayout(footer)

        self._items = frames_for(session)
        for item in self._items:
            verdict = self._verdicts.get(item.path.name)
            if verdict:
                item.fault = verdict
        self._rebuild()

    # -- contents --------------------------------------------------------

    def _rebuild(self) -> None:
        while self._grid.count():
            entry = self._grid.takeAt(0)
            if entry and entry.widget():
                entry.widget().deleteLater()

        order = self.sort_box.currentData()
        items = list(self._items)
        if order == "quality":
            # Faulty first, then the rest in capture order.
            items.sort(key=lambda i: (i.fault == "", i.index))

        self.tiles: list[FrameTile] = []
        for item in items:
            tile = FrameTile(item)
            tile.clicked.connect(self._open_viewer)
            tile.toggled.connect(self._on_selection)
            self.tiles.append(tile)
            self._grid.addWidget(tile)

        judged = sum(1 for i in self._items if i.fault)
        if self._verdicts:
            self.note.setText(
                f"{len(self._items)} frames. {judged} were judged poor by the "
                f"last stack — shown with the reason. Sort by quality to bring "
                f"them to the top."
            )
        else:
            self.note.setText(
                f"{len(self._items)} frames. No quality verdicts yet — those "
                f"are measured while stacking, so run a stack and reopen this "
                f"to see which frames were judged poor."
            )
            self.sort_box.setEnabled(False)
        self._on_selection()

    def _selected(self) -> list[FrameItem]:
        return [tile.item for tile in self.tiles if tile.selected]

    def _select_all(self, everything: bool) -> None:
        for tile in self.tiles:
            tile.set_selected(everything)
        self._on_selection()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """Ctrl+A selects the lot; Escape clears before it closes.

        Escape closing a dialog is the Qt default and stays that way -- but
        with a selection made it means "never mind that", which is the same
        word for a smaller undo. Only once there is nothing selected does it
        close the window.
        """
        if event.matches(QKeySequence.StandardKey.SelectAll):
            self._select_all(True)
            return
        if event.key() == Qt.Key.Key_Escape and self._selected():
            self._select_all(False)
            return
        super().keyPressEvent(event)

    def _on_selection(self) -> None:
        chosen = self._selected()
        self.delete_button.setEnabled(bool(chosen))
        if not chosen:
            # Disabled and saying so, on a button that deletes from a card
            # with no Recycle Bin.
            self.delete_button.setToolTip(
                "No frames are selected. Ctrl-click frames, or use Select "
                "all, and you will still be asked to confirm."
            )
            self.selection_label.setText("Nothing selected.")
            self.selection_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            return
        self.delete_button.setToolTip(
            "You will be shown exactly which frames go, and asked to "
            "confirm, before anything is removed."
        )
        total = sum(folder_size(item.path)[0] for item in chosen)
        remaining = len(self._items) - len(chosen)
        self.selection_label.setText(
            f"{len(chosen)} selected, {describe_size(total)}. "
            f"{remaining} frames would remain."
            + ("  ⚠ That is every frame in this session." if not remaining else "")
        )
        # Selecting the lot is the one selection worth colouring. With
        # Select all a click away it is easy to reach by accident, and
        # "0 frames would remain" in the same grey as every other count is
        # the sort of thing that gets read after the fact.
        self.selection_label.setStyleSheet(
            f"color: {theme.WARN};" if not remaining else f"color: {theme.TEXT};"
        )

    # -- actions ---------------------------------------------------------

    def _open_viewer(self, item: FrameItem) -> None:
        order = [tile.item for tile in self.tiles]
        try:
            start = order.index(item)
        except ValueError:
            start = 0
        viewer = FrameViewer(order, start, self)
        viewer.deleted.connect(self._on_viewer_deleted)
        viewer.exec()
        self._rebuild()

    def _on_viewer_deleted(self, item: FrameItem) -> None:
        if item in self._items:
            self._items.remove(item)
        self.changed.emit()

    def _delete_selected(self) -> None:
        chosen = self._selected()
        if not chosen:
            return
        total = sum(folder_size(item.path)[0] for item in chosen)
        remaining = len(self._items) - len(chosen)

        # Emptying a session is a different act from thinning one, and Select
        # all makes it one click. It says so, and it costs the extra gesture
        # whatever the frame count is.
        warnings = []
        if remaining == 0:
            warnings.append(
                f"This is EVERY frame in this session of "
                f"{self._session.display_target}. Nothing of it is left to "
                f"stack afterwards."
            )

        request = DeleteRequest(
            paths=[item.path for item in chosen],
            total_bytes=total,
            what=f"{len(chosen)} frame{'s' if len(chosen) != 1 else ''}",
            where_from=self._session.display_target,
            remaining=remaining,
            remaining_label="frames in this session",
            grave=len(chosen) > 10 or remaining == 0,
            warnings=warnings,
            detail=[item.name for item in chosen],
        )
        if not confirm_delete(request, self):
            return

        outcome = delete([item.path for item in chosen], allow_recycle=True)
        for item in chosen:
            if item.path not in [p for p, _ in outcome.failed] and item in self._items:
                self._items.remove(item)

        if outcome.failed:
            from PySide6.QtWidgets import QMessageBox

            box = QMessageBox(self)
            box.setWindowTitle("Some frames were not deleted")
            box.setText(outcome.summary())
            box.setDetailedText(
                "\n".join(f"{path.name}: {why}" for path, why in outcome.failed)
            )
            box.setIcon(QMessageBox.Icon.Warning)
            box.exec()

        self._rebuild()
        self.changed.emit()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        apply_dark_titlebar(self.winId(), theme.SURFACE, theme.TEXT, theme.BORDER)


class FrameViewer(QDialog):
    """Full-screen gallery: step through frames, judge them, delete them."""

    deleted = Signal(object)   # FrameItem that went

    def __init__(self, items: list[FrameItem], start: int, parent=None) -> None:
        super().__init__(parent)
        self._items = items
        self._index = max(0, min(start, len(items) - 1))
        self._cache: dict[int, QPixmap] = {}

        self.setWindowTitle("Frame viewer")
        # SCOPED TO THIS DIALOG, not to everything inside it.
        #
        # A stylesheet set on a widget applies to that widget AND all its
        # descendants, and it OUTRANKS the application stylesheet for them.
        # A bare `background: ...` therefore repainted every button, box and
        # label in the dialog too -- which meant the filled Danger button in
        # here lost its red and drew its near-black label straight onto the
        # near-black ground. The most dangerous button in the app was
        # invisible in exactly the two windows that own it, while the
        # identical button in the main window looked right, because the main
        # window never set a stylesheet of its own.
        #
        # A type selector still applies only where it matches, so the dialog
        # gets its ground and its children go on being styled by theme.py.
        self.setStyleSheet(f"QDialog {{ background: {theme.BG}; }}")
        self.setWindowState(Qt.WindowState.WindowFullScreen)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.view = QLabel()
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view.setStyleSheet(
            f"background: {theme.BG_SUNKEN}; color: {theme.TEXT_MUTED};"
        )
        layout.addWidget(self.view, 1)

        bar = QWidget()
        # No rule above the bar: this one sits against a near-black viewer,
        # so the surface change is already the strongest edge in the window.
        bar.setObjectName("Chrome")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(
            theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3
        )
        bar_layout.setSpacing(theme.SPACE_3)

        previous = QPushButton("‹  Previous")
        previous.setObjectName("Ghost")
        previous.clicked.connect(lambda: self.step(-1))
        bar_layout.addWidget(previous)

        self.caption = QLabel("")
        self.caption.setWordWrap(True)
        bar_layout.addWidget(self.caption, 1)

        nxt = QPushButton("Next  ›")
        nxt.setObjectName("Ghost")
        nxt.clicked.connect(lambda: self.step(1))
        bar_layout.addWidget(nxt)

        self.delete_button = QPushButton("Delete this frame")
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self._delete_current)
        bar_layout.addWidget(self.delete_button)

        close = QPushButton("Close  (Esc)")
        close.setObjectName("Ghost")
        close.clicked.connect(self.accept)
        bar_layout.addWidget(close)
        layout.addWidget(bar)

        self._show_current()

    # -- navigation ------------------------------------------------------

    def step(self, delta: int) -> None:
        if not self._items:
            return
        self._index = (self._index + delta) % len(self._items)
        self._show_current()

    def _show_current(self) -> None:
        if not self._items:
            self.accept()
            return
        item = self._items[self._index]

        pixmap = self._cache.get(self._index)
        if pixmap is not None:
            self._paint(pixmap)
        elif item.thumbnail is None:
            self.view.setPixmap(QPixmap())
            self.view.setText(
                "This frame has no picture from the DWARF.\n"
                "It is still a real frame and can still be deleted."
            )
        else:
            self.view.setPixmap(QPixmap())
            self.view.setText("Loading...")
            index = self._index
            load_async(
                item.thumbnail,
                lambda image, i=index: self._on_loaded(i, image),
                width=0,
            )

        # Preload the neighbours so stepping feels instant.
        for offset in (1, -1):
            neighbour = (self._index + offset) % len(self._items)
            if neighbour in self._cache:
                continue
            other = self._items[neighbour]
            if other.thumbnail is not None:
                load_async(
                    other.thumbnail,
                    lambda image, i=neighbour: self._cache_only(i, image),
                    width=0,
                )

        bits = [
            f"Frame {self._index + 1} of {len(self._items)}",
            item.name,
        ]
        if item.when:
            bits.append(item.when)
        if item.fault:
            bits.append(f"⚠ {item.fault}")
        elif item.excluded:
            bits.append("not in the stack")
        self.caption.setText(
            "   ·   ".join(bits)
            + "\nThe DWARF's own preview of this frame, not this tool's output."
        )

    def _on_loaded(self, index: int, image) -> None:
        if image is None:
            if index == self._index:
                self.view.setText("That preview could not be opened.")
            return
        pixmap = QPixmap.fromImage(image)
        self._cache[index] = pixmap
        if index == self._index:
            self._paint(pixmap)

    def _cache_only(self, index: int, image) -> None:
        if image is not None:
            pixmap = QPixmap.fromImage(image)
            if not pixmap.isNull():
                self._cache[index] = pixmap

    def _paint(self, pixmap: QPixmap) -> None:
        self.view.setText("")
        self.view.setPixmap(
            pixmap.scaled(
                self.view.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    # -- input -----------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        key = event.key()
        if key in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Space):
            self.step(1)
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_Backspace):
            self.step(-1)
        elif key == Qt.Key.Key_Escape:
            self.accept()
        else:
            super().keyPressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        # Clicking away from the picture closes, which is what people expect
        # of a full-screen image. Clicking the picture itself does not, so a
        # careless click does not lose your place.
        if event.button() == Qt.MouseButton.LeftButton:
            pixmap = self.view.pixmap()
            if pixmap is None or pixmap.isNull():
                self.accept()
                return
            centre = self.view.geometry().center()
            image_rect = pixmap.rect()
            image_rect.moveCenter(centre)
            if not image_rect.contains(event.position().toPoint()):
                self.accept()
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        pixmap = self._cache.get(self._index)
        if pixmap is not None:
            self._paint(pixmap)

    # -- deleting --------------------------------------------------------

    def _delete_current(self) -> None:
        item = self._items[self._index]
        size = folder_size(item.path)[0]
        request = DeleteRequest(
            paths=[item.path],
            total_bytes=size,
            what="1 frame",
            where_from=item.name,
            remaining=len(self._items) - 1,
            remaining_label="frames in this session",
        )
        if not confirm_delete(request, self):
            return
        outcome = delete([item.path], allow_recycle=True)
        if not outcome.ok:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "Not deleted", outcome.summary())
            return

        self.deleted.emit(item)
        self._items.pop(self._index)
        self._cache.clear()
        if not self._items:
            self.accept()
            return
        self._index = min(self._index, len(self._items) - 1)
        self._show_current()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        apply_dark_titlebar(self.winId(), theme.SURFACE, theme.TEXT, theme.BORDER)
