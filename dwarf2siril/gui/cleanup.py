"""Clean up the card: see where the space went, and choose what to remove.

This is the most dangerous screen in the app, so it is also the plainest.
Everything on the card is listed with its size, biggest first, because the
question being answered is "where has my space gone" and the answer is
almost always one or two folders.

The tool advises and never decides. Nothing is ever preselected, reusable
darks are marked Keep and warned about if picked, and the user's own photos
and videos are listed with sizes but no opinion at all.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..cardinfo import KEEP, STACKED, SYSTEM, YOURS, CardEntry, survey
from ..deletion import delete, describe_size
from . import theme
from .delete_dialog import DeleteRequest, confirm_delete
from .windows_theme import apply_dark_titlebar

ADVICE_COLOUR = {
    "Safe to remove": theme.OK,
    "Already stacked": theme.OK,
    "Keep": theme.WARN,
    "Yours": theme.TEXT_MUTED,
}


class CleanupPanel(QWidget):
    """A list of everything on the card, with sizes and advice.

    A panel rather than a window, so the same thing can be a whole mode in
    the main window or a dialog opened from a button, without two
    implementations of the most dangerous screen in the app.
    """

    changed = Signal()

    def __init__(self, card_root: Path, sessions: list, parent=None) -> None:
        super().__init__(parent)
        self._card_root = Path(card_root)
        self._sessions = sessions

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_3)

        title = QLabel("Clean up your DWARF card")
        title.setObjectName("CardTitle")
        layout.addWidget(title)

        self.space_label = QLabel("")
        self.space_label.setObjectName("Muted")
        layout.addWidget(self.space_label)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        # The first column is the one with the tick boxes in it, and it was
        # the only column with no name at all.
        self.tree.setHeaderLabels(["What goes", "Size", "Advice", "What it is"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        # Surface, border, row padding and header are all in theme.py: this
        # is the only tree in the app, but its colours are not its own.
        #
        # THE TREE TAKES WHAT IS LEFT, and never demands more. It asked for
        # 430px so a whole card's folders fit without scrolling, which is
        # right on a big window and impossible on a 900x640 one: 430 plus
        # everything above it is more than that window has, and a QVBoxLayout
        # that cannot fit its children draws them on top of each other. The
        # selected-count line, the note and the DELETE BUTTON were painted
        # across the middle of the list of things they were about to delete.
        #
        # A stretch of 1 with a small floor gets the same 430-and-more where
        # there is room, and lets the tree's own scrollbar absorb the
        # shortfall where there is not -- which is what a scrolling list is
        # for. The controls under it keep their space at every size.
        self.tree.setMinimumHeight(150)
        self.tree.itemChanged.connect(self._on_tick)
        layout.addWidget(self.tree, 1)

        self.selection_label = QLabel("Nothing selected.")
        self.selection_label.setWordWrap(True)
        layout.addWidget(self.selection_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(theme.SPACE_3)
        note = QLabel(
            "Nothing is selected for you. Tick only what you want gone."
        )
        note.setObjectName("Faint")
        note.setWordWrap(True)
        buttons.addWidget(note, 1)

        self.delete_button = QPushButton("Delete selected")
        self.delete_button.setObjectName("Danger")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._delete_selected)
        buttons.addWidget(self.delete_button)
        layout.addLayout(buttons)

        self.refresh()

    # -- contents --------------------------------------------------------

    def refresh(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()

        result = survey(self._card_root, self._sessions)
        self._entries: dict[int, CardEntry] = {}

        for entry in result.by_size():
            if entry.kind == SYSTEM:
                continue  # Windows' own folders are not ours to offer
            item = QTreeWidgetItem(
                ["", entry.readable_size, entry.advice, entry.reason]
            )
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked)  # never preselected
            item.setText(0, entry.name)
            item.setForeground(
                2, Qt.GlobalColor.white
            )
            colour = ADVICE_COLOUR.get(entry.advice, theme.TEXT_MUTED)
            item.setData(0, Qt.ItemDataRole.UserRole, id(entry))
            self._entries[id(entry)] = entry
            item.setToolTip(3, entry.reason)
            # The names are long and the column truncates them. Whoever is
            # about to delete something has to be able to read WHICH thing.
            item.setToolTip(0, f"{entry.name}\n{entry.path}")
            self.tree.addTopLevelItem(item)
            # Colour the advice column, which is the column being scanned.
            from PySide6.QtGui import QBrush, QColor

            item.setForeground(2, QBrush(QColor(colour)))
            if entry.size == 0:
                item.setForeground(1, QBrush(QColor(theme.TEXT_FAINT)))

        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        self.tree.blockSignals(False)

        self.space_label.setText(
            f"Card holds {describe_size(result.capacity_bytes)}, "
            f"{describe_size(result.free_bytes)} free. "
            f"Listed below: {describe_size(result.total_bytes)}."
        )
        self._result = result
        self._on_tick()

    def _selected_entries(self) -> list[CardEntry]:
        chosen = []
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.checkState(0) == Qt.CheckState.Checked:
                key = item.data(0, Qt.ItemDataRole.UserRole)
                entry = self._entries.get(key)
                if entry is not None:
                    chosen.append(entry)
        return chosen

    def _on_tick(self, *_args) -> None:
        chosen = self._selected_entries()
        self.delete_button.setEnabled(bool(chosen))
        if not chosen:
            # Disabled, and saying why. On the one screen in the app where a
            # mistake cannot be undone, a button that will not explain itself
            # is the last thing anybody needs.
            self.delete_button.setToolTip(
                "Nothing is ticked. Tick what you want gone first — nothing "
                "is ever ticked for you."
            )
            self.selection_label.setText("Nothing selected.")
            self.selection_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            return
        self.delete_button.setToolTip(
            f"You will be shown exactly what goes, and asked to confirm, "
            f"before anything is removed."
        )

        total = sum(entry.size for entry in chosen)
        after = self._result.free_bytes + total
        message = (
            f"{len(chosen)} selected, {describe_size(total)}. "
            f"That would leave {describe_size(after)} free."
        )
        keepers = [e for e in chosen if e.kind == KEEP]
        if keepers:
            message += (
                f"  ⚠ {len(keepers)} of these are reusable "
                f"({', '.join(e.name for e in keepers)}) — you would have to "
                f"shoot them again."
            )
            self.selection_label.setStyleSheet(f"color: {theme.WARN};")
        else:
            self.selection_label.setStyleSheet(f"color: {theme.TEXT};")
        self.selection_label.setText(message)

    # -- deleting --------------------------------------------------------

    def _delete_selected(self) -> None:
        chosen = self._selected_entries()
        if not chosen:
            return

        total = sum(entry.size for entry in chosen)
        warnings = []
        keepers = [e for e in chosen if e.kind == KEEP]
        if keepers:
            warnings.append(
                "These are REUSABLE and are not regenerated: "
                + ", ".join(e.name for e in keepers)
                + ". You would have to shoot them again."
            )
        sessions = [e for e in chosen if e.is_session]
        if sessions:
            warnings.append(
                "A whole session folder goes, not just its light frames — "
                "the DWARF's own album picture, its per-frame thumbnails and "
                "shotsInfo.json go with it."
            )

        unstacked = [e for e in sessions if e.kind != STACKED]
        if unstacked:
            warnings.append(
                "Nothing else on the card can replace these light frames: "
                + ", ".join(e.session_target or e.name for e in unstacked)
                + "."
            )

        # Losing the last session of a target is the one people regret, so it
        # gets its own sentence rather than being folded into the list above.
        per_target: dict[str, int] = {}
        for session in self._sessions:
            per_target[session.display_target] = (
                per_target.get(session.display_target, 0) + 1
            )
        going = [e for e in sessions if e.session_target]
        emptied = [
            e.session_target
            for e in going
            if per_target.get(e.session_target, 0)
            <= sum(1 for g in going if g.session_target == e.session_target)
        ]
        for target in sorted(set(emptied)):
            warnings.append(
                f"This is the ONLY session of {target} on the card. Deleting "
                f"it removes that target entirely."
            )

        request = DeleteRequest(
            paths=[entry.path for entry in chosen],
            total_bytes=total,
            what=f"{len(chosen)} item{'s' if len(chosen) != 1 else ''}",
            where_from="your DWARF card",
            grave=True,   # a bulk delete always deserves the extra gesture
            warnings=warnings,
            detail=[f"{e.readable_size:>10s}  {e.name}" for e in chosen],
        )
        if not confirm_delete(request, self):
            return

        outcome = delete([entry.path for entry in chosen], allow_recycle=True)
        self._report(outcome)
        self.refresh()
        self.changed.emit()

    def _report(self, outcome) -> None:
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox(self)
        box.setWindowTitle("Cleanup finished")
        box.setText(outcome.summary())
        if outcome.failed:
            box.setDetailedText(
                "\n".join(f"{path}: {why}" for path, why in outcome.failed)
            )
            box.setIcon(QMessageBox.Icon.Warning)
        box.exec()


class CleanupWindow(QDialog):
    """The cleanup panel as a standalone window, for the button that opens it."""

    changed = Signal()

    def __init__(self, card_root: Path, sessions: list, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Clean up your DWARF card")
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
        self.resize(920, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACE_5, theme.SPACE_4, theme.SPACE_5, theme.SPACE_4
        )
        layout.setSpacing(theme.SPACE_3)

        self.panel = CleanupPanel(card_root, sessions, self)
        self.panel.changed.connect(self.changed.emit)
        layout.addWidget(self.panel, 1)

        close = QPushButton("Close")
        close.setObjectName("Ghost")
        close.clicked.connect(self.accept)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)

    def refresh(self) -> None:
        self.panel.refresh()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        apply_dark_titlebar(self.winId(), theme.SURFACE, theme.TEXT, theme.BORDER)
