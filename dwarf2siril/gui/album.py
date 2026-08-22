"""The DWARF's own picture of a target, at a size worth looking at.

This is the image the DWARF's own app shows in its album: the full-size
version of the thumbnail already on the card, stretched and ready to view.
It is 3840x2160 and around 4 MB, so it is opened only when somebody actually
asks for it, and decoded off the UI thread.

It is emphatically NOT this tool's output. That distinction matters more at
this size, not less -- a big picture of your target looks like a result --
so the window says whose picture it is in its title, in a line under the
image, and in the caption on the card that opens it.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from . import theme
from .thumbnails import load_async


class AlbumWindow(QDialog):
    """A plain viewer for one DWARF album image."""

    def __init__(self, target: str, path: Path, parent=None) -> None:
        super().__init__(parent)
        self._path = path
        self._pixmap: QPixmap | None = None

        self.setWindowTitle(f"{target} — your DWARF's own picture")
        # Styled in theme.py rather than here: an inline sheet is set once at
        # construction and a palette switch cannot reach it.
        self.setObjectName("Sheet")
        self.setSizeGripEnabled(True)

        # Comfortably large, but never bigger than the screen it opens on.
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry().size() if screen else QSize(1280, 800)
        self.resize(
            min(1280, int(available.width() * 0.8)),
            min(800, int(available.height() * 0.85)),
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3
        )
        layout.setSpacing(theme.SPACE_3)

        self.view = QLabel("Opening the picture...")
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view.setObjectName("Muted")
        self.view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.view.setMinimumSize(320, 180)
        layout.addWidget(self.view, 1)

        footer = QHBoxLayout()
        footer.setSpacing(theme.SPACE_3)
        caption = QLabel(
            "This is your DWARF's own live-stacked picture, straight off the "
            "card — not the result of this tool."
        )
        caption.setObjectName("Muted")
        caption.setWordWrap(True)
        footer.addWidget(caption, 1)

        close = QPushButton("Close")
        close.setObjectName("Ghost")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        layout.addLayout(footer)

        # Decoded on a worker thread: 3840x2160 is not something to open on
        # the UI thread, however briefly.
        load_async(path, self._on_loaded, width=0)
        theme.follow(self)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        # Dialogs get their own native frame, so they need the same treatment
        # as the main window or this one window turns up in the platform's
        # default colours next to everything else.
        super().showEvent(event)
        theme.apply_titlebar(self)

    def restyle(self) -> None:
        """Only the title bar. Everything else here is object-named."""
        theme.apply_titlebar(self)

    def _on_loaded(self, image) -> None:
        if image is None:
            self.view.setText(
                "That picture could not be opened.\n"
                "The file may be damaged, or still being written."
            )
            return
        self._pixmap = QPixmap.fromImage(image)
        if self._pixmap.isNull():
            self._pixmap = None
            self.view.setText("That picture could not be opened.")
            return
        self._rescale()

    def _rescale(self) -> None:
        if self._pixmap is None:
            return
        self.view.setPixmap(
            self._pixmap.scaled(
                self.view.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._rescale()


def show_album(target: str, path: Path | None, parent=None) -> AlbumWindow | None:
    """Open the album image, or do nothing at all if there is not one.

    Returns None rather than opening an empty window, so a card whose
    session never got a picture simply does not respond to a click.
    """
    if path is None or not path.is_file():
        return None
    window = AlbumWindow(target, path, parent)
    window.show()
    return window
