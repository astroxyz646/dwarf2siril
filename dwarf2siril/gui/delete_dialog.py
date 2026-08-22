"""The one confirmation dialog every delete in this app goes through.

There is exactly one of these on purpose. Frames, whole sessions and the
cleanup view all end up here, so the safeguards cannot be forgotten in one
corner of the app.

What it guarantees:

* It says WHERE things go. "Recycle Bin" and "permanently" are different
  words for different outcomes, and a DWARF card usually has no Recycle Bin,
  so "permanently" is the normal case rather than the exception.
* It says what will be LEFT, not only what goes. "42 go, 308 remain" is the
  sentence someone can actually check against their intention.
* Cancel has focus. The destructive button never does.
* A bigger loss costs a bigger gesture: deleting whole sessions needs an
  explicit tick before the button will work at all.
* There is no "don't ask again". This is not a dialog anyone should be able
  to switch off.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from ..deletion import describe_size, recycle_bin_available
from . import theme
from .windows_theme import apply_dark_titlebar


@dataclass
class DeleteRequest:
    """Everything the dialog needs to describe what is about to happen."""

    paths: list[Path]
    total_bytes: int
    # What the user sees, e.g. "42 frames" or "1 session folder".
    what: str
    # Where they are going from, e.g. "C 27, 12 August".
    where_from: str = ""
    # How many of this kind will still be there afterwards.
    remaining: int | None = None
    remaining_label: str = "frames"
    # Set for losses big enough to deserve a deliberate second gesture.
    grave: bool = False
    # Anything the user must not miss: this is the only session of a target,
    # it is selected for stacking, these are reusable darks.
    warnings: list[str] | None = None
    # Extra lines listing exactly what goes, shown in a scrollable box.
    detail: list[str] | None = None


class DeleteDialog(QDialog):
    def __init__(self, request: DeleteRequest, parent=None) -> None:
        super().__init__(parent)
        self._request = request
        self.recycles = recycle_bin_available(request.paths[0]) if request.paths else False

        self.setWindowTitle("Delete from your DWARF card")
        self.setMinimumWidth(520)
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_4
        )
        layout.setSpacing(theme.SPACE_3)

        headline = QLabel(
            f"Delete {request.what}"
            + (f" from {request.where_from}?" if request.where_from else "?")
        )
        headline.setObjectName("DialogTitle")
        headline.setWordWrap(True)
        layout.addWidget(headline)

        # Size and what remains, which is the pair of numbers that lets
        # someone check this against what they meant to do.
        facts = [f"This frees {describe_size(request.total_bytes)}."]
        if request.remaining is not None:
            facts.append(
                f"{request.remaining} {request.remaining_label} will remain."
            )
        summary = QLabel(" ".join(facts))
        summary.setObjectName("Muted")
        summary.setWordWrap(True)
        layout.addWidget(summary)

        # Where they go. This is the sentence that stops the feature being a
        # trap on a card with no Recycle Bin.
        if self.recycles:
            destination = QLabel(
                "They go to the Windows Recycle Bin, so you can get them "
                "back if you change your mind."
            )
            destination.setStyleSheet(f"color: {theme.OK};")
        else:
            destination = QLabel(
                "This card has no Recycle Bin, so they will be deleted "
                "PERMANENTLY and cannot be recovered."
            )
            destination.setStyleSheet(f"color: {theme.ERROR}; font-weight: 600;")
        destination.setWordWrap(True)
        layout.addWidget(destination)

        for warning in request.warnings or []:
            label = QLabel(warning)
            label.setStyleSheet(f"color: {theme.WARN};")
            label.setWordWrap(True)
            layout.addWidget(label)

        if request.detail:
            listing = QPlainTextEdit()
            listing.setReadOnly(True)
            listing.setPlainText("\n".join(request.detail))
            listing.setMaximumHeight(150)
            # ONE LINE PER THING, scrolling sideways if it has to. A DWARF
            # session folder name is 50-odd characters, and wrapped in a
            # monospace box it broke across two lines mid-word -- so the list
            # of what is about to be deleted permanently read as twice as
            # many items as it contained, each of them mangled. Counting the
            # rows is the first thing anyone does with this box.
            listing.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            # Styled in theme.py alongside the run panel's log, which is the
            # same thing: a padded, bordered box of monospace lines.
            listing.setObjectName("Listing")
            layout.addWidget(listing)

        # A larger loss costs a larger gesture. A frame is one click; a whole
        # session is a tick and then a click.
        self.confirm_tick: QCheckBox | None = None
        if request.grave:
            self.confirm_tick = QCheckBox(
                f"Yes, delete {request.what}"
                + (" permanently" if not self.recycles else "")
            )
            self.confirm_tick.setStyleSheet(f"color: {theme.TEXT};")
            self.confirm_tick.stateChanged.connect(self._sync_button)
            layout.addWidget(self.confirm_tick)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Yes
        )
        self.delete_button = buttons.button(QDialogButtonBox.StandardButton.Yes)
        self.delete_button.setText(
            "Delete permanently" if not self.recycles else "Move to Recycle Bin"
        )
        self.delete_button.setObjectName("Danger")
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setObjectName("Ghost")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._sync_button()
        # Cancel is what Enter and the initial focus land on. The destructive
        # button is never the default.
        cancel.setDefault(True)
        cancel.setFocus()

    def _sync_button(self) -> None:
        if self.confirm_tick is not None:
            ready = self.confirm_tick.isChecked()
            self.delete_button.setEnabled(ready)
            # The extra gesture is deliberate, so the greyed button has to
            # read as a step still to take rather than as one that has
            # stopped working.
            self.delete_button.setToolTip(
                "" if ready else "Tick the box above first."
            )
        else:
            self.delete_button.setEnabled(True)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        apply_dark_titlebar(
            self.winId(), theme.SURFACE, theme.TEXT, theme.BORDER
        )


def confirm_delete(request: DeleteRequest, parent=None) -> bool:
    """Ask. True only if the user actively said yes."""
    if not request.paths:
        return False
    dialog = DeleteDialog(request, parent)
    return dialog.exec() == QDialog.DialogCode.Accepted
