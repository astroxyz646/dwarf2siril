"""The Dwarf2Siril window.

The flow the brief asks for, in two columns rather than one long scroll:

    LEFT   1. pick the DWARF 3 drive  ->  2. tick the targets to stack
    RIGHT  3. output and options      ->  4. stack it

Step 1 is the only thing the user has to find. Everything after it is
discovered for them: the sessions, their grouping by target, and the darks
that match. This file wires the widgets together and owns no logic of its
own -- the scanning, grouping and building all live in the core package so
the CLI runs the exact same code.

WHY THE SIDEBAR. Steps 3 and 4 used to sit below the grid, which meant
scrolling away from your targets to choose an output folder and scrolling
back. Both halves are now visible at once: what you are stacking on the
left, what happens to it on the right. The sidebar is also the only part
that persists across a rescan -- your output folder and your options survive
plugging in a different card.

It folds to a rail when the window is too narrow to hold it AND two cards.
Deciding which one folds matters: the alternative is a single column of
cards, which is exactly the chunky layout the grid replaced.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QDesktopServices, QFont, QIcon
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..cardinfo import remember_stacked
from ..grouping import auto_group, build_group
from ..scanner import ScanResult, find_astronomy_root
from . import theme
from .cards import CARD_WIDTH, DriveTile, GroupCard
from .cleanup import CleanupPanel
from .framegrid import StackGridWindow
from .flow import FlowLayout
from .layers import LayersCard
from .preview import PreviewPanel
from .run_panel import RunPanel
from .windows_theme import apply_dark_titlebar
from .workers import BuildWorker, DriveScanner, ScanWorker


def _label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


# The sidebar is one card wide, so the two columns share a rhythm rather
# than being two unrelated widths.
SIDEBAR_WIDTH = CARD_WIDTH + 22

# Below this, the sidebar and two cards cannot both fit, so the sidebar
# folds. Derived rather than guessed: two cards, the gap between them, the
# body margins and room for a scrollbar.
GRID_MARGINS = 40
SCROLLBAR_ROOM = 14
SIDEBAR_MIN_WINDOW = (
    SIDEBAR_WIDTH + (CARD_WIDTH * 2) + 12 + GRID_MARGINS + SCROLLBAR_ROOM
)

# The folded state: wide enough for a chevron and a word read downwards.
RAIL_WIDTH = 30

# THE THREE MODES, and the reasoning for the shape they take.
#
# The operator asked for a three-mode menu. The risk with modes, for somebody
# using this for the first time, is that they turn "everything is on screen
# in order" into "the thing you want is somewhere else, and you have to know
# where". That would be a real step backwards from a numbered flow.
#
# So a mode here is a LENS, not a place. The left column always shows the
# same thing -- your drive, and your targets -- and the mode changes what
# those targets offer and what the sidebar is for. Nothing moves. Stack is
# the default and is exactly the app as it was, so somebody who never
# touches the switcher never meets the feature at all.
#
# Clean up is the one mode that replaces the grid, because deleting is not
# something you do to a target you are stacking -- it is a different question
# ("where has my space gone") with a different answer shape, and it is the
# most dangerous screen in the app. Having to choose it deliberately is a
# safety feature, not a cost.
MODE_STACK = "stack"
MODE_MANAGE = "manage"
MODE_CLEAN = "clean"

MODES = [
    (MODE_STACK, "Stack", "Turn your sessions into one stacked image"),
    (MODE_MANAGE, "Frames", "Look through every frame and drop the bad ones"),
    (MODE_CLEAN, "Clean up", "See where the space went, and remove what you "
                             "no longer want"),
]


class _ScrollColumn(QWidget):
    """Content for a vertically scrolling column, with an HONEST minimum.

    *** WHY THIS CLASS EXISTS ***
    A word-wrapped QLabel reports a minimum height of a single line -- it is
    entitled to, since it can always rewrap. A column full of them therefore
    reports a tiny minimum, and QScrollArea, being told everything fits,
    resizes the content to the viewport instead of scrolling.

    Qt does not refuse to draw a layout it has under-sized. It squeezes every
    child below its minimum and then DRAWS THEM ON TOP OF EACH OTHER. That is
    what the operator photographed: the star slider painted across the label
    above it, "Locate Siril" and "Open folder" sliced to the top half of
    their glyphs, and Stop clipped to "top".

    Reporting the layout's real height at this width as the minimum makes the
    scroll area do the one thing it is there for.
    """

    def event(self, event) -> bool:
        # LayoutRequest is Qt telling us a child changed shape. Step 4 grows
        # a whole log and a progress bar the moment a stack starts, so a
        # height worked out only at resize time would be the OLD one at
        # exactly the moment it matters.
        handled = super().event(event)
        if event.type() == QEvent.Type.LayoutRequest:
            area = self.parentWidget()
            while area is not None and not isinstance(area, ScrollingColumn):
                area = area.parentWidget()
            if area is not None:
                area.fit_later()
        return handled


class ScrollingColumn(QScrollArea):
    """A column that SCROLLS when its contents do not fit, without argument.

    Qt's own answer to this is ``setWidgetResizable(True)``, which resizes
    the content to the viewport in BOTH directions and only scrolls when the
    content admits to needing more room. In a column of word-wrapped labels
    the content never does admit it -- see _give_room -- so the whole sidebar
    was squeezed into the viewport and drew its widgets on top of each other.

    Trying to make the content admit its height turned into a losing fight
    with Qt's layout caches: correct minimums, stale geometry, and a stable
    disagreement that no amount of invalidating would shift, because the
    corrections were being made from inside the very layout pass they needed
    to influence.

    So this does not negotiate. It sets the content's width to the viewport
    and its height to whatever the content needs, and lets the scrollbar do
    its job. There is nothing left for Qt to decide.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._pending = False

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self.fit()

    def fit_later(self) -> None:
        """Refit once the current layout pass is over.

        A request that arrives WHILE a fit is running is remembered rather
        than dropped. Fitting resizes widgets and resizing widgets asks for
        a fit, so answering those immediately spins forever -- but ignoring
        them outright loses the real ones.

        That distinction was a live defect, and a nasty one because it was a
        RACE: if the sidebar's contents changed during a fit -- which is
        exactly what happens when a scan finishes and the extras card grows
        an EDGES section -- the growth was discarded and never refitted. It
        showed in the packaged build and not from source purely because the
        timings differ, which made it look like the bundle's fault when the
        bundle had nothing to do with it.
        """
        if self._fitting:
            self._dirty = True
            return
        if self._pending:
            return
        self._pending = True
        QTimer.singleShot(0, self._fit_now)

    _fitting = False
    _dirty = False

    def _fit_now(self) -> None:
        self._pending = False
        self.fit()

    def fit(self) -> None:
        if self._fitting:
            return
        content = self.widget()
        if content is None:
            return
        self._fitting = True
        self._dirty = False
        try:
            self._fit(content)
        finally:
            self._fitting = False
        # Something changed shape while we were working. Answer it now that
        # we are out of the way, once.
        if self._dirty:
            self._dirty = False
            self.fit_later()

    def _fit(self, content) -> None:
        width = self.viewport().width()
        if width <= 0:
            return

        # UNTIL IT STOPS GROWING. One pass is not enough and cannot be: a
        # wrapping label cannot say how tall it is until it knows how wide
        # it is, its panel cannot say how tall IT is until its labels have,
        # and the column above cannot either. Each pass makes the layer
        # below it honest, so the height converges from the inside out --
        # in practice in two or three passes, and it stops when nothing
        # moves. The cap is only so a pathological case cannot spin.
        moved = False
        for _ in range(8):
            if content.width() != width:
                content.resize(width, content.height())
            grew = _give_room(content)
            moved = moved or grew
            if grew:
                _relayout(content)

            # Exactly as tall as its contents. Not "at least the
            # viewport": that reintroduces slack, and slack is what the
            # layout was mishandling.
            #
            # And NOT from sizeHint alone. sizeHint is a cached opinion, and
            # a stale one is how the column ended up 36px shorter than its
            # own children needed -- the extras card wanting 657px in a
            # 629px slot, drawn straight over the heading below it. It
            # showed in the packaged build and never from source, purely
            # because the timing of when the card grew differed; the cache
            # was the cause, not the bundle. Asking the children directly
            # cannot go stale.
            needed = max(
                content.sizeHint().height(),
                content.layout().minimumSize().height(),
                _tallest(content),
            )
            if content.height() == needed:
                break
            content.resize(width, needed)
            _relayout(content)

        if moved:
            # One last pass over the whole tree. The loop above re-lays the
            # column each time it grows, but the panels NESTED inside it can
            # claim their height on the final iteration, after the last
            # re-layout -- and a panel whose height changed without its
            # parent repositioning it is a panel drawn on top of its
            # neighbour. This is the difference between "the minimums are
            # right" and "the screen is right".
            _relayout(content)


def _relayout(root) -> None:
    """Re-run every layout in this column, outermost first.

    Outermost first because a parent decides where its children go:
    activating a child before its parent has repositioned it only arranges
    its contents inside the wrong rectangle. Safe to do here, and only here,
    because ScrollingColumn.fit runs outside Qt's own layout pass.
    """
    def depth(widget) -> int:
        steps, parent = 0, widget.parentWidget()
        while parent is not None and parent is not root:
            steps += 1
            parent = parent.parentWidget()
        return steps

    panels = sorted(
        [child for child in root.findChildren(QWidget)
         if child.layout() is not None and child.isVisible()],
        key=depth,
    )
    for widget in [root, *panels]:
        widget.layout().invalidate()
    for widget in [root, *panels]:
        widget.layout().activate()


def _tallest(content) -> int:
    """The height this column's children actually demand, laid end to end.

    Every visible child's own requirement, with the spacing and margins the
    layout uses. Three measures are taken because any one alone understates:
    sizeHint is a cached opinion, minimumHeight is whatever _give_room
    pinned, and minimumSizeHint is what the child recomputes from its own
    contents. The largest of the three is what the column must hold.

    *** WHAT MUST NEVER BE IN HERE IS widget.height(). ***

    It was, and it made this function a RATCHET: the column could be told to
    grow and never to shrink back. Switching to Frames or Clean up left the
    sidebar at the height Stack mode had needed -- 1078px of column holding
    270px of content -- and a box layout hands the slack to whatever will
    take it, so a heading, its hint and its card were each drawn 515px tall
    with enormous holes between them. Two of the three modes looked like a
    rendering fault.

    It is a ratchet because it is self-confirming: once the layout has
    stretched a child to fill an over-tall column, that child's height IS
    the over-tall column, so the next pass measures the mistake and agrees
    with it. Nothing could ever climb back down.

    The reason height() was reached for -- that sizeHint goes stale, and a
    card gets drawn on top of the heading below it -- is real, and it is
    what minimumSizeHint does above instead: a child recomputes that from
    its own contents rather than serving a cached number, so the guard
    survives without the ratchet.
    """
    layout = content.layout()
    if layout is None:
        return 0
    margins = layout.contentsMargins()
    total = margins.top() + margins.bottom()
    seen = 0
    for index in range(layout.count()):
        item = layout.itemAt(index)
        widget = item.widget()
        if widget is None:
            total += item.sizeHint().height()
            continue
        if not widget.isVisible():
            continue
        total += max(
            widget.sizeHint().height(),
            widget.minimumHeight(),
            widget.minimumSizeHint().height(),
        )
        seen += 1
    return total + max(0, seen - 1) * layout.spacing()


def _give_room(root) -> bool:
    """Make every wrapping label in this column admit how tall it really is.

    THE WHOLE PROBLEM IS THE WRAPPING LABELS, and pinning them fixes
    everything above them for free.

    A word-wrapped QLabel reports a height of ONE LINE. It is entitled to --
    it can always rewrap onto a wider line -- but in a fixed-width column it
    never will, so a four-line sentence claims it can live in the height of
    one. Every panel containing one inherits the understatement, and the
    column above them inherits it too, until QScrollArea concludes the whole
    sidebar fits its viewport and squeezes it to fit.

    Qt does not refuse to draw a layout it has under-sized. It squeezes
    every child below its minimum and then DRAWS THEM ON TOP OF EACH OTHER:
    the star slider painted across the label above it, "Locate Siril" and
    "Open folder" sliced to the top half of their glyphs, Stop clipped to
    "top".

    Returns whether anything actually changed, which matters: this runs from
    a layout notification, so reporting a change when there was none is a
    loop that never stops.
    """
    from PySide6.QtWidgets import QLabel

    changed = False
    for label in root.findChildren(QLabel):
        if not label.wordWrap() or not label.isVisible():
            continue
        width = label.width()
        if width <= 0:
            continue
        needed = label.heightForWidth(width)
        # THE TEST IS "IS IT PINNED", NOT "IS IT THE RIGHT HEIGHT".
        #
        # Those are not the same question and the difference was a live
        # defect. A label that the layout has ALREADY drawn at its correct
        # height passed the old `height() != needed` test and was skipped --
        # so it was never pinned, and it went on reporting a minimum of one
        # line while occupying four. Its card inherited the understatement,
        # ended up with a minimumSizeHint 19px short of what its own
        # contents need, and the column below the card was drawn on top of
        # it: the EDGES section over "Drop bad frames" and its dropdown.
        #
        # Measured on the operator's card at 1636x1171 and 1280x880 inside
        # the packaged exe. It appeared when a sixth extra was added to the
        # layers card, which is exactly the sort of unrelated change that
        # should not be able to break a layout.
        pinned = label.minimumHeight() == needed == label.maximumHeight()
        if needed > 0 and not pinned:
            # FIXED, not minimum. A minimum still leaves sizeHint reporting
            # one line, and a box layout hands out space by sizeHint -- so
            # the panel above still budgets one line for it and gives the
            # difference to something else. Every earlier attempt at this
            # foundered on exactly that: correct minimums, wrong shares, and
            # a card drawn on top of the heading above it that no amount of
            # invalidating or re-activating would shift.
            #
            # Pinned to its real height the label stops being squishy: its
            # sizeHint, its minimum and its actual height become the same
            # number, every panel above it computes correctly through Qt's
            # ordinary machinery, and there is nothing left to cache wrongly.
            label.setFixedHeight(needed)
            changed = True

    # Then every panel that is still shorter than it can be drawn. Pinning
    # the labels fixes most of it, but a panel can understate for other
    # reasons too -- a row whose warning line only appears once a box is
    # ticked, for instance -- and the checker is right to object to any of
    # them. Unlike the earlier attempts at this, it runs OUTSIDE Qt's layout
    # pass (see ScrollingColumn.fit), which is what makes it stick.
    for panel in root.findChildren(QWidget):
        if panel.layout() is None or not panel.isVisible():
            continue
        needed = panel.minimumSizeHint().height()
        if needed > panel.minimumHeight():
            panel.setMinimumHeight(needed)
            changed = True
    return changed


def _explainer(text: str) -> QLabel:
    """A wrapped note under a tick box, indented to line up with its label."""
    label = _label(text, "Faint", wrap=True)
    label.setContentsMargins(theme.SPACE_6, 0, 0, 2)
    return label


class _StatePanel(QFrame):
    """What step 2 says when it has no cards to show.

    Every state the target grid can be in that is NOT "here are your
    targets" gets a headline, a sentence saying what is going on, an
    optional detail line naming what the scanner actually objected to, and
    the buttons that get you out of it. One panel with four states rather
    than four one-line labels scattered through the flow, so an empty
    screen can never be silent again.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACE_5, theme.SPACE_4, theme.SPACE_5, theme.SPACE_4
        )
        layout.setSpacing(theme.SPACE_2)

        self.title = _label("", "CardTitle", wrap=True)
        layout.addWidget(self.title)

        self.body = _label("", "Muted", wrap=True)
        layout.addWidget(self.body)

        self.detail = _label("", "Faint", wrap=True)
        self.detail.hide()
        layout.addWidget(self.detail)

        self.actions_host = QWidget()
        self.actions_host.setObjectName("Plain")
        self.actions = QHBoxLayout(self.actions_host)
        self.actions.setContentsMargins(0, theme.SPACE_2, 0, 0)
        self.actions.setSpacing(theme.SPACE_2)
        self.actions_host.hide()
        layout.addWidget(self.actions_host)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """Pin the wrapping labels to the height they need AT THIS WIDTH.

        Same disease as the sidebar, same cure, kept local to this panel. A
        word-wrapped QLabel reports a sizeHint worked out at whatever width
        it was last asked about, and before the column has been laid out that
        is the wrong width -- so a one-line sentence claims two lines, the
        panel claims a height it does not need, the layout squeezes it back
        to what it will give, and the text floats in the middle of a box with
        holes above and below it.

        Measured at 1280x880 before this: a 21px heading claiming 42, a 34px
        sentence claiming 68, in a panel squeezed to 171 of the 205 it asked
        for.
        """
        super().resizeEvent(event)
        self._pin_labels()

    def _pin_labels(self) -> None:
        for label in (self.title, self.body, self.detail):
            if not label.isVisible():
                continue
            width = label.width()
            if width <= 0:
                continue
            needed = label.heightForWidth(width)
            if needed > 0 and label.height() != needed:
                label.setFixedHeight(needed)

    def set_body(self, text: str) -> None:
        """Replace the running line without letting the panel jump around."""
        self.body.setText(text)
        self._pin_labels()

    def show_state(self, title, body, detail="", actions=()) -> None:
        self.title.setText(title)
        self.body.setText(body)
        self.detail.setText(detail)
        self.detail.setVisible(bool(detail))

        while self.actions.count():
            item = self.actions.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for label, handler, primary in actions:
            button = QPushButton(label)
            button.setObjectName("Primary" if primary else "Ghost")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(handler)
            self.actions.addWidget(button)
        if actions:
            self.actions.addStretch(1)
        self.actions_host.setVisible(bool(actions))
        self.show()
        # New text, new heights, and the column above has to be told. Four
        # lines of "waiting for a card" and one line of "reading the card"
        # are very different heights, and without this the panel keeps the
        # taller of the two and spreads the difference between its own
        # children -- the state changes correctly and looks wrong.
        self._pin_labels()
        QTimer.singleShot(0, self._settle)

    def _settle(self) -> None:
        self._pin_labels()
        self.layout().invalidate()
        self.layout().activate()
        self.updateGeometry()
        parent = self.parentWidget()
        if parent is not None and parent.layout() is not None:
            parent.layout().invalidate()
            parent.layout().activate()
        self._pin_labels()


def _step_heading(number: int, title: str, hint: str) -> QWidget:
    holder = QWidget()
    holder.setObjectName("Plain")   # sits on the sidebar surface as well as the body
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(1)

    # Step number and title on one line rather than stacked: the number is a
    # small marker, not a heading in its own right.
    top = QHBoxLayout()
    top.setSpacing(theme.SPACE_2)
    if number:
        top.addWidget(_label(f"STEP {number}", "StepLabel"))
    heading = _label(title, "SectionHeading")
    top.addWidget(heading)
    top.addStretch(1)
    layout.addLayout(top)

    hint_label = _label(hint, "Muted", wrap=True)
    layout.addWidget(hint_label)
    hint_label.setVisible(bool(hint))

    # Handed back so a heading whose words depend on the mode can be
    # reworded rather than rebuilt.
    holder.title_label = heading
    holder.hint_label = hint_label
    return holder


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Dwarf2Siril")
        # Two card columns plus the sidebar, with room to spare.
        self.resize(1280, 880)
        self.setMinimumSize(900, 640)

        self.scan_result: ScanResult | None = None
        self.group_cards: list[GroupCard] = []
        self.scan_worker: ScanWorker | None = None
        self.build_worker: BuildWorker | None = None
        self.source_root: Path | None = None
        self.output_dir: Path | None = None
        # All four are built once, in _build_ui, and live for the life of the
        # window -- a rescan no longer throws them away.
        self.run_panel: RunPanel | None = None
        self.preview_panel: PreviewPanel | None = None
        self.layers_card: LayersCard | None = None
        self.sidebar: QFrame | None = None
        self._last_stack_name = ""
        self._last_output_dir: Path | None = None
        self._last_post = None
        self._last_group = None
        # None = follow the window width. True/False = the user said so, and
        # a deliberate choice outranks the rule.
        self._sidebar_choice: bool | None = None
        # Stack is the default, deliberately: somebody who never touches the
        # switcher gets exactly the app as it was before modes existed.
        self._mode = MODE_STACK
        # Per-frame quality verdicts from the last stack, keyed by file name.
        # Empty until a stack has run, which the grid says rather than
        # showing an unexplained blank column.
        self._frame_verdicts: dict[str, str] = {}

        self._build_ui()
        QTimer.singleShot(150, self._look_for_drives)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """Colour the native title bar once the window actually exists.

        winId() only returns a real handle after the window is shown, so
        this cannot be done in the constructor. Doing it here also survives
        the window being hidden and shown again.
        """
        super().showEvent(event)
        apply_dark_titlebar(
            self.winId(),
            caption=theme.SURFACE,
            text=theme.TEXT,
            border=theme.BORDER,
        )

    # -- layout ----------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._header())

        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)

        self.main_scroll = QScrollArea()
        self.main_scroll.setWidgetResizable(True)
        self.main_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(
            theme.SPACE_6, theme.SPACE_4, theme.SPACE_6, theme.SPACE_4
        )
        self.body_layout.setSpacing(theme.SPACE_4)
        self.main_scroll.setWidget(body)
        middle.addWidget(self.main_scroll, 1)

        middle.addWidget(self._sidebar(), 0)
        middle.addWidget(self._sidebar_rail(), 0)
        root.addLayout(middle, 1)

        self.body_layout.addWidget(
            _step_heading(
                1,
                "Pick your DWARF 3 drive",
                "Plug the card in, or point at the folder the DWARF writes to. "
                "Everything after this is found for you.",
            )
        )
        self.body_layout.addWidget(self._source_section())

        # STEP 2 EXISTS FROM THE FIRST FRAME, and so does something in it.
        #
        # It used to be built by _on_scanned, which meant that until a card
        # had been read the whole left column below step 1 was an unbroken
        # black rectangle: no step 2, no sign that there was going to be one,
        # nothing to read while the scan ran, and one grey sentence when a
        # card turned out to hold nothing. A blank half-screen is not a
        # neutral state -- it reads as a broken window, and it is exactly
        # where a first-time user is standing.
        #
        # The heading and the placeholder are built once and live for the
        # life of the window; only the grid of cards is rebuilt on a rescan.
        self.results_area = QWidget()
        self.results_area.setObjectName("Plain")
        self.results_layout = QVBoxLayout(self.results_area)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(theme.SPACE_3)

        self.step2_heading = _step_heading(2, "Choose what to stack", "")
        self.results_layout.addWidget(self.step2_heading)

        self.targets_state = _StatePanel()
        self.results_layout.addWidget(self.targets_state)

        self.grid_host = QWidget()
        self.grid_host.setObjectName("Plain")
        self.grid = FlowLayout(self.grid_host, margin=0, spacing=theme.SPACE_3)
        self.results_layout.addWidget(self.grid_host)

        # A trailing stretch HERE, unlike in the sidebar, and for the same
        # reason the sidebar must not have one. Wrapping labels understate
        # their height, so this column is handed more room than it needs;
        # with nothing to absorb it a box layout shares the surplus out
        # between the heading and the panel below it, which shows as holes
        # between two things that should be a few pixels apart. The sidebar
        # cannot do this because its column IS the scrolled content and a
        # stretch there swallows the height its panels need. Here the column
        # is inside a page that scrolls as a whole, so the leftover has
        # somewhere harmless to go.
        self.results_layout.addStretch(1)

        self.body_layout.addWidget(self.results_area)
        self._show_waiting_for_card()

        # Clean-up mode replaces the target grid rather than sharing it: it
        # answers a different question, in a different shape, and it is the
        # one screen where a mistake cannot be undone on a DWARF card.
        self.cleanup_host = QWidget()
        self.cleanup_host.setObjectName("Plain")
        self.cleanup_layout = QVBoxLayout(self.cleanup_host)
        self.cleanup_layout.setContentsMargins(0, 0, 0, 0)
        self.cleanup_panel: CleanupPanel | None = None
        self.cleanup_host.hide()
        self.body_layout.addWidget(self.cleanup_host, 1)

        # The before/after view stays in the wide column. It is the one thing
        # here that is genuinely about looking at a picture, and a 330px
        # column is the wrong place to judge whether a stack came out well.
        self.preview_panel = PreviewPanel()
        self.preview_panel.open_folder_requested.connect(self._open_output)
        self.preview_panel.hide()
        self.body_layout.addWidget(self.preview_panel)

        self.body_layout.addStretch(1)
        root.addWidget(self._footer())
        self._fit_sidebar()

    # -- the right-hand column -------------------------------------------

    def _sidebar(self) -> QWidget:
        """Steps 3 and 4, always on screen, surviving a rescan."""
        panel = QFrame()
        panel.setObjectName("Sidebar")
        panel.setFixedWidth(SIDEBAR_WIDTH)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(
            theme.SPACE_4, theme.SPACE_3, theme.SPACE_2, theme.SPACE_3
        )
        head.setSpacing(theme.SPACE_2)
        self.sidebar_title = _label("Output & stacking", "SidebarTitle")
        head.addWidget(self.sidebar_title)
        head.addStretch(1)
        fold = QPushButton("›")
        fold.setObjectName("SidebarToggle")
        fold.setCursor(Qt.CursorShape.PointingHandCursor)
        fold.setToolTip("Fold this panel away and give the targets the room")
        fold.clicked.connect(lambda: self._choose_sidebar(False))
        head.addWidget(fold)
        outer.addLayout(head)

        scroll = ScrollingColumn()
        content = _ScrollColumn()
        content.setObjectName("Plain")
        self.sidebar_layout = QVBoxLayout(content)
        self.sidebar_layout.setContentsMargins(
            theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_4
        )
        self.sidebar_layout.setSpacing(theme.SPACE_3)

        self.sidebar_layout.addWidget(
            _step_heading(
                3,
                "Output and options",
                "Where it goes, and anything extra to do to it. The extras "
                "are all off by default.",
            )
        )
        self.sidebar_layout.addWidget(self._output_section())
        self.layers_card = LayersCard()
        self.sidebar_layout.addWidget(self.layers_card)

        # A gap rather than a rule between steps 3 and 4. Each step already
        # announces itself with its own number and heading, so the line was
        # saying something that was already said.
        self.sidebar_layout.addSpacing(8)
        self.sidebar_layout.addWidget(
            _step_heading(
                4, "Stack it", "Run it here, or take the command and run it yourself."
            )
        )

        # Step 4 is visible from the start, saying plainly that it is waiting
        # rather than appearing out of nowhere later. Somewhere to look is
        # worth more than one less widget.
        self.run_placeholder = _label(
            "Press Prepare on a target and it appears here, with the command "
            "and a live log.",
            "Faint",
            wrap=True,
        )
        self.sidebar_layout.addWidget(self.run_placeholder)

        self.run_panel = RunPanel()
        self.run_panel.finished.connect(self._on_stack_finished)
        self.run_panel.running.connect(self._on_stack_running)
        self.run_panel.hide()
        self.sidebar_layout.addWidget(self.run_panel)

        # Everything added so far belongs to Stack mode; the other two modes
        # add their own below. NOT wrapped in a widget each.
        #
        # They were, and it was the direct cause of the operator's squashed
        # sidebar. A wrapper's layout is a second level for Qt to size, and
        # that level would not re-run: given a card 290px when it needed
        # 631px, it kept the arrangement it had computed while the column was
        # still the height of the viewport, and no combination of
        # invalidating, activating or resizing would shift it. Flat, there is
        # only one layout deciding anything, and it gets it right the first
        # time.
        self._mode_widgets = {
            MODE_STACK: [
                self.sidebar_layout.itemAt(index).widget()
                for index in range(self.sidebar_layout.count())
                if self.sidebar_layout.itemAt(index).widget() is not None
            ],
            MODE_MANAGE: self._manage_widgets(),
            MODE_CLEAN: self._clean_widgets(),
        }
        for mode in (MODE_MANAGE, MODE_CLEAN):
            for widget in self._mode_widgets[mode]:
                self.sidebar_layout.addWidget(widget)
                widget.hide()

        # NO TRAILING STRETCH. A stretch is given the space left over after
        # every widget has its minimum -- and the whole difficulty here is
        # that a column of wrapping labels understates its minimum. The
        # stretch happily swallowed 500px that the panels above it needed,
        # and they were squeezed into overlapping each other to pay for it.
        # The column is now exactly as tall as its contents, so there is no
        # leftover to misplace.
        scroll.setWidget(content)
        self.sidebar_scroll = scroll
        outer.addWidget(scroll, 1)

        self.sidebar = panel
        return panel

    def _manage_widgets(self) -> list:
        pieces = []
        pieces.append(
            _step_heading(
                0,
                "What this is for",
                "Open a target to see every frame it is made of.",
            )
        )
        card = QFrame()
        card.setObjectName("Card")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(
            theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3
        )
        inner.setSpacing(theme.SPACE_2)
        inner.addWidget(
            _label(
                "Pick out the frames a passing cloud, a knock or a satellite "
                "ruined, and take them out of the stack.",
                "Muted",
                wrap=True,
            )
        )
        inner.addWidget(
            _label(
                "You do not have to. Stacking already drops the worst frames "
                "for you — this is for when you want to look yourself.",
                "Faint",
                wrap=True,
            )
        )
        inner.addWidget(
            _label(
                "Frames you remove here go from the card itself, and a DWARF "
                "card has no Recycle Bin. You are asked to confirm first.",
                "Faint",
                wrap=True,
            )
        )
        pieces.append(card)
        return pieces

    def _clean_widgets(self) -> list:
        pieces = []
        pieces.append(
            _step_heading(
                0, "Before you delete anything", "Worth reading once."
            )
        )
        card = QFrame()
        card.setObjectName("Card")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(
            theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3
        )
        inner.setSpacing(theme.SPACE_2)
        for text, name in (
            ("Nothing is ever ticked for you. You choose what goes.", "Muted"),
            ("A DWARF card has no Recycle Bin, so what you remove from it is "
             "gone for good. You are shown exactly what and how much first.",
             "Muted"),
            ("Your darks are reusable and are marked Keep. Delete them and "
             "you have to shoot them again.", "Faint"),
            ("Nothing is deleted while a stack is running.", "Faint"),
        ):
            inner.addWidget(_label(text, name, wrap=True))
        pieces.append(card)
        return pieces

    def _sidebar_rail(self) -> QWidget:
        """What the sidebar folds down to: a way back, and nothing else."""
        rail = QFrame()
        rail.setObjectName("SidebarRail")
        rail.setFixedWidth(RAIL_WIDTH)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(0, theme.SPACE_3, 0, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)

        unfold = QPushButton("‹")
        unfold.setObjectName("SidebarToggle")
        unfold.setCursor(Qt.CursorShape.PointingHandCursor)
        unfold.setToolTip("Show output and stacking")
        unfold.clicked.connect(lambda: self._choose_sidebar(True))
        layout.addWidget(unfold, 0, Qt.AlignmentFlag.AlignHCenter)

        # One letter per line rather than a rotated label: rotation needs a
        # custom paint, and at this size the stack is just as readable.
        word = _label("\n".join("OUTPUT"), "Rail")
        word.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(word, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)

        rail.hide()
        self.sidebar_rail = rail
        return rail

    # -- modes -----------------------------------------------------------

    def _set_mode(self, mode: str) -> None:
        """Switch lens. Nothing moves; what the targets offer changes."""
        if mode == MODE_CLEAN and self._refuse_while_busy():
            self.mode_buttons[self._mode].setChecked(True)
            self.mode_buttons[mode].setChecked(False)
            return
        if mode == MODE_CLEAN and self.source_root is None:
            self._warn(
                "Pick your card first",
                "Choose your DWARF 3 drive, then this can show what is on it.",
            )
            self.mode_buttons[self._mode].setChecked(True)
            self.mode_buttons[mode].setChecked(False)
            return

        self._mode = mode
        for key, button in self.mode_buttons.items():
            button.setChecked(key == mode)

        cleaning = mode == MODE_CLEAN
        # Not "only when there are cards" any more: with no cards, step 2 is
        # a panel that says what is missing and offers the way out of it,
        # which is worth far more on screen than a black rectangle.
        self.results_area.setVisible(not cleaning)
        self.cleanup_host.setVisible(cleaning)
        if cleaning:
            self._show_cleanup()
        # The before/after view belongs to a finished stack, not to the two
        # modes that are about the card.
        if self.preview_panel is not None and mode != MODE_STACK:
            self.preview_panel.hide()

        for key, widgets in self._mode_widgets.items():
            for widget in widgets:
                widget.setVisible(key == mode)
        # The run panel is part of Stack mode but has its own idea of when
        # it should be seen: before a build there is nothing to show.
        if mode == MODE_STACK:
            has_run = bool(self.run_panel.script_path)
            self.run_panel.setVisible(has_run)
            self.run_placeholder.setVisible(not has_run)
        self.sidebar_title.setText(
            {
                MODE_STACK: "Output & stacking",
                MODE_MANAGE: "Going through frames",
                MODE_CLEAN: "Deleting safely",
            }[mode]
        )

        # The grid heading says what the grid is FOR in this mode. Leaving it
        # on "Choose what to stack" while the cards say "Go through the
        # frames" is the kind of small dishonesty that makes people distrust
        # the rest of the screen.
        heading = getattr(self, "step2_heading", None)
        if heading is not None:
            title, hint = {
                MODE_STACK: (
                    "Choose what to stack",
                    "Sessions of the same target with matching settings are "
                    "grouped for you. Open Details to pick individual sessions.",
                ),
                MODE_MANAGE: (
                    "Pick a target to go through",
                    "Open one to see every frame it is made of, and take out "
                    "the ones you do not want.",
                ),
                MODE_CLEAN: ("Choose what to stack", ""),
            }[mode]
            heading.title_label.setText(title)
            heading.hint_label.setText(hint)
            # The hint describes the cards. With no cards on screen the
            # state panel below is already saying more, and better.
            heading.hint_label.setVisible(bool(hint) and bool(self.group_cards))

        for card in self.group_cards:
            card.set_mode(mode)

        # Refit the sidebar NOW, in the same turn as the switch, rather than
        # leaving it to the layout notification that follows. A mode swaps
        # one set of panels for another of a completely different height, so
        # the frame between the swap and the refit is the frame where the
        # old height is holding the new contents -- either stretched apart
        # or, going the other way, drawn on top of each other. Nobody should
        # have to see that flash to get a correct sidebar a moment later.
        if getattr(self, "sidebar_scroll", None) is not None:
            self.sidebar_scroll.fit()

    def _show_cleanup(self) -> None:
        """Build the cleanup view on demand, and keep it up to date."""
        if self.source_root is None:
            return
        card_root = self.source_root
        if card_root.name.lower() == "astronomy":
            card_root = card_root.parent
        sessions = self.scan_result.sessions if self.scan_result else []

        if self.cleanup_panel is None:
            self.cleanup_panel = CleanupPanel(card_root, sessions, self.cleanup_host)
            self.cleanup_panel.changed.connect(self._rescan_after_delete)
            self.cleanup_layout.addWidget(self.cleanup_panel)
        else:
            self.cleanup_panel._card_root = card_root
            self.cleanup_panel._sessions = sessions
            self.cleanup_panel.refresh()

    def _choose_sidebar(self, want_open: bool) -> None:
        """The user folded or unfolded it, which then overrides the width rule."""
        self._sidebar_choice = want_open
        self._fit_sidebar()

    def _fit_sidebar(self) -> None:
        # resizeEvent can fire while the window is still being built.
        if getattr(self, "sidebar", None) is None:
            return
        if self._sidebar_choice is None:
            want = self.width() >= SIDEBAR_MIN_WINDOW
        else:
            want = self._sidebar_choice
        self.sidebar.setVisible(want)
        self.sidebar_rail.setVisible(not want)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._fit_sidebar()

    def _header(self) -> QWidget:
        holder = QWidget()
        # No rule under the header. The native title bar is painted this exact
        # colour, so a line here cut across what is otherwise one continuous
        # surface -- which is what the operator noticed. The change of
        # background against the body below is the separation.
        holder.setObjectName("Chrome")
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(
            theme.SPACE_6, theme.SPACE_4, theme.SPACE_6, theme.SPACE_4
        )
        layout.setSpacing(theme.SPACE_6)

        titles = QVBoxLayout()
        titles.setSpacing(theme.SPACE_1)
        titles.addWidget(_label("Dwarf2Siril", "Title"))
        titles.addWidget(
            _label(
                "Prepare DWARF 3 exposures for stacking in Siril  ·  EQ and alt-az",
                "Subtitle",
            )
        )
        layout.addLayout(titles)
        layout.addStretch(1)
        layout.addWidget(self._mode_bar(), 0, Qt.AlignmentFlag.AlignVCenter)
        return holder

    def _mode_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("ModeBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(theme.SPACE_1 // 2)

        self.mode_buttons: dict[str, QPushButton] = {}
        for key, label, hint in MODES:
            button = QPushButton(label)
            button.setObjectName("ModeDanger" if key == MODE_CLEAN else "Mode")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(hint)
            button.setChecked(key == MODE_STACK)
            button.clicked.connect(lambda _checked=False, k=key: self._set_mode(k))
            self.mode_buttons[key] = button
            row.addWidget(button)
        return bar

    def _source_section(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(
            theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3
        )
        layout.setSpacing(theme.SPACE_3)

        # WHAT IS OPEN, and only then what could be. These are two different
        # facts and they used to share one label, so once a folder had been
        # chosen by hand the card went on saying "No DWARF 3 drive spotted.
        # Plug the card in and hit Rescan" over six sessions it had just
        # read. Step 1 was lying about the thing step 1 is for.
        self.source_summary = _label("", "Muted", wrap=True)
        # Hidden rather than empty: an empty label still takes a line, and a
        # blank line at the top of the first card looks like a bug.
        self.source_summary.hide()
        layout.addWidget(self.source_summary)

        self.drive_status = _label("Looking for DWARF 3 drives...", "Muted")
        layout.addWidget(self.drive_status)

        self.drive_row = QHBoxLayout()
        self.drive_row.setSpacing(theme.SPACE_3)
        layout.addLayout(self.drive_row)

        picker = QHBoxLayout()
        picker.setSpacing(theme.SPACE_2)
        self.source_field = QLineEdit()
        self.source_field.setPlaceholderText("or choose the folder yourself...")
        self.source_field.setReadOnly(True)
        picker.addWidget(self.source_field, 1)

        browse = QPushButton("Choose folder...")
        browse.setObjectName("Ghost")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(self._choose_source)
        picker.addWidget(browse)

        self.rescan_button = QPushButton("Rescan")
        self.rescan_button.setObjectName("Ghost")
        self.rescan_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rescan_button.clicked.connect(self._look_for_drives)
        picker.addWidget(self.rescan_button)

        # Discoverable but out of the way: someone who never wants to delete
        # anything is not affected by its presence.
        self.cleanup_button = QPushButton("Clean up card...")
        self.cleanup_button.setObjectName("Ghost")
        self.cleanup_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cleanup_button.setToolTip(
            "See what is taking up space on the card and remove what you "
            "no longer want"
        )
        self.cleanup_button.clicked.connect(self._open_cleanup)
        picker.addWidget(self.cleanup_button)
        layout.addLayout(picker)

        return card

    def _footer(self) -> QWidget:
        holder = QWidget()
        # Same reasoning as the header: the raised surface is the separator.
        holder.setObjectName("Chrome")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(
            theme.SPACE_6, theme.SPACE_3, theme.SPACE_6, theme.SPACE_3
        )
        layout.setSpacing(theme.SPACE_2)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)

        row = QHBoxLayout()
        self.status = _label("Ready.", "Muted")
        row.addWidget(self.status, 1)

        self.cancel_button = QPushButton("Stop")
        self.cancel_button.setObjectName("Ghost")
        self.cancel_button.clicked.connect(self._cancel_build)
        self.cancel_button.hide()
        row.addWidget(self.cancel_button)

        self.open_button = QPushButton("Open output folder")
        self.open_button.setObjectName("Ghost")
        self.open_button.clicked.connect(self._open_output)
        self.open_button.hide()
        row.addWidget(self.open_button)

        layout.addLayout(row)
        return holder

    # -- step 1: source --------------------------------------------------

    def _card_name(self) -> str:
        """What to call the thing that is open, in one or two words.

        The scan root is usually the ``Astronomy`` folder inside the card, so
        its own name says nothing -- every DWARF card in the world is called
        Astronomy. The folder holding it is the one the user recognises: a
        drive letter, or whatever they named the copy on their disk.
        """
        root = self.source_root
        if root is None:
            return "Card"
        if root.name.lower() == "astronomy" and root.parent != root:
            return root.parent.name or str(root.parent)
        return root.name or str(root)

    def _set_source_summary(self, text: str, colour: str = "") -> None:
        """Say what is open right now, above everything about finding one."""
        if not text:
            self.source_summary.setText("")
            self.source_summary.hide()
            return
        if colour:
            self.source_summary.setTextFormat(Qt.TextFormat.RichText)
            self.source_summary.setText(f'<span style="color:{colour};">{text}</span>')
        else:
            self.source_summary.setTextFormat(Qt.TextFormat.PlainText)
            self.source_summary.setText(text)
        self.source_summary.show()

    def _look_for_drives(self) -> None:
        self.drive_status.setText("Looking for DWARF 3 drives...")
        self._clear_layout(self.drive_row)
        self._drive_scanner = DriveScanner(self)
        self._drive_scanner.found.connect(self._show_drives)
        self._drive_scanner.start()

    def _show_drives(self, candidates: list) -> None:
        self._clear_layout(self.drive_row)
        if not candidates:
            # Two different sentences, because a card being open changes what
            # the absence of a drive MEANS. With nothing open it is the thing
            # blocking you; with a folder already read it is a footnote.
            self.drive_status.setText(
                "No DWARF 3 drive spotted. Plug the card in and hit Rescan, "
                "or choose the folder below."
                if self.source_root is None
                else "No DWARF 3 drive spotted — plug one in and hit Rescan "
                "to switch to it."
            )
            return

        many = len(candidates) > 1
        self.drive_status.setText(
            f"Found {len(candidates)} drive{'s' if many else ''} that "
            f"look{'' if many else 's'} like a DWARF 3:"
        )
        for candidate in candidates:
            tile = DriveTile(
                candidate.display,
                str(candidate.path),
                "DWARF 3 data found here",
            )
            tile.clicked.connect(
                lambda _checked=False, path=candidate.path: self._start_scan(path)
            )
            self.drive_row.addWidget(tile)
        self.drive_row.addStretch(1)

    def _choose_source(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose your DWARF 3 drive or its Astronomy folder"
        )
        if not chosen:
            return
        root = find_astronomy_root(Path(chosen))
        if root is None:
            self._warn(
                "That does not look like a DWARF 3 card",
                f"{chosen}\n\nExpected DWARF_RAW_... session folders or a "
                f"DWARF_DARK folder, either directly inside it or inside an "
                f"'Astronomy' folder.",
            )
            return
        self._start_scan(root)

    # -- what step 2 says when it has no cards ----------------------------

    def _show_waiting_for_card(self) -> None:
        self.grid_host.hide()
        self.step2_heading.title_label.setText("Choose what to stack")
        self.step2_heading.hint_label.setText("")
        self.step2_heading.hint_label.hide()
        self.targets_state.show_state(
            "Your targets will appear here",
            "Pick your DWARF 3 drive above and this fills with one card per "
            "target — how many frames, how long you were on it, and which "
            "darks matched. That is the only thing you have to do; the "
            "sessions, the grouping and the darks are all found for you.",
            "Nothing on the card is ever written to, moved or renamed.",
            (("Choose folder...", self._choose_source, True),
             ("Look for drives again", self._look_for_drives, False)),
        )
        self.results_area.setVisible(self._mode != MODE_CLEAN)

    def _show_scanning(self, message: str = "") -> None:
        self.grid_host.hide()
        self.targets_state.show_state(
            "Reading the card...",
            message or "Opening one frame from each session to read what it "
            "was actually shot at.",
            "This reads the card only. It can be left to get on with it.",
        )
        self.results_area.setVisible(self._mode != MODE_CLEAN)

    def _on_scan_progress(self, message: str) -> None:
        """One progress line, in the two places somebody might be looking.

        The status bar is a strip at the very bottom of a 880px window; the
        panel is in the middle of the empty column the user is staring at.
        Putting it only in the former is how a scan came to look like a
        frozen window with a hint hidden at the foot of the screen.
        """
        self.status.setText(message)
        if self.targets_state.isVisible():
            self.targets_state.set_body(message)

    def _start_scan(self, root: Path) -> None:
        self.source_root = root
        self.source_field.setText(str(root))
        self.source_field.setToolTip(str(root))
        self._set_source_summary(f"Reading {self._card_name()}...")
        self.status.setText(f"Reading {root}...")
        self.progress.setRange(0, 0)   # indeterminate
        self.progress.show()
        self._show_scanning()

        self.scan_worker = ScanWorker(root)
        self.scan_worker.progressed.connect(self._on_scan_progress)
        self.scan_worker.finished_ok.connect(self._on_scanned)
        self.scan_worker.failed.connect(self._on_scan_failed)
        self.scan_worker.start()

    def _on_scan_failed(self, message: str) -> None:
        self.progress.hide()
        self.status.setText("Could not read that folder.")
        self._set_source_summary("That folder could not be read.", theme.ERROR)
        self.grid_host.hide()
        self.targets_state.show_state(
            "That folder could not be read",
            "Windows would not let this app read it. If the card is in a "
            "reader, try taking it out and putting it back; otherwise pick "
            "the folder again.",
            message,
            (("Choose folder...", self._choose_source, True),
             ("Try again", self._retry_scan, False)),
        )
        self.results_area.setVisible(self._mode != MODE_CLEAN)
        self._warn("Could not read that folder", message)

    def _retry_scan(self) -> None:
        if self.source_root is not None:
            self._start_scan(self.source_root)

    # -- step 2: groups --------------------------------------------------

    def _on_scanned(self, result: ScanResult) -> None:
        self.scan_result = result
        self.progress.hide()

        # A rescan rebuilds the target GRID and nothing else. Steps 3 and 4
        # live in the sidebar and are deliberately left alone: swapping cards
        # should not lose the output folder you picked, the extras you
        # ticked, or the log of the stack you just ran. The step heading and
        # the state panel are left alone too -- they outlive every scan.
        self._clear_layout(self.grid)
        self.group_cards.clear()

        groups = auto_group(
            result.stackable_sessions,
            result.darks,
            result.cali_masters,
            use_cali_fallback=True,
        )

        altaz = result.altaz_sessions
        total = len(result.sessions)
        summary = (
            f"{total} session{'s' if total != 1 else ''} in "
            f"{len(groups)} target group{'s' if len(groups) != 1 else ''}"
        )
        if altaz:
            summary += (
                f"  ·  {len(altaz)} shot in alt-az"
                f" (stacks fine, slightly noisier corners)"
            )
        self.status.setText(summary)

        if not groups:
            self._show_nothing_found(result)
            return

        # Step 1 states what it actually opened, rather than going on about
        # drives it did not find.
        darks = len(result.darks)
        self._set_source_summary(
            f"✓  {self._card_name()} — "
            f"{total} session{'s' if total != 1 else ''} in {len(groups)} "
            f"target group{'s' if len(groups) != 1 else ''}, "
            f"{darks} dark set{'s' if darks != 1 else ''}.",
            theme.OK,
        )

        self.targets_state.hide()
        self.grid_host.show()
        self.step2_heading.hint_label.setVisible(True)

        for group in groups:
            card = GroupCard(group)
            card.changed.connect(lambda c=card: self._regroup(c))
            card.build_requested.connect(self._start_build)
            card.grid_requested.connect(self._open_stack_grid)
            self.group_cards.append(card)
            self.grid.addWidget(card)

        # Only raise the framing question where there is a real trade.
        self.layers_card.show_framing(groups)

        # New cards start in whatever mode the user is actually in, so a
        # rescan while going through frames does not silently drop them back
        # into stacking.
        for card in self.group_cards:
            card.set_mode(self._mode)
        self._set_mode(self._mode)
        self.results_area.setVisible(self._mode != MODE_CLEAN)
        if self._mode == MODE_CLEAN:
            self._show_cleanup()

    def _show_nothing_found(self, result: ScanResult) -> None:
        """A card was read and held nothing stackable. SAY WHY.

        There are three quite different reasons and they want three
        different answers, so the panel works out which one it is looking at
        rather than printing one sentence that covers none of them. Where
        the scanner objected to something by name -- a session folder with
        no light frames in it, a dark folder it could not read -- those
        reasons are put on screen, because the README promises every refusal
        names what disagreed and an empty screen is a refusal.
        """
        darks = len(result.darks)
        skipped = result.skipped

        if darks and not result.sessions:
            title = "Darks, but nothing to use them on"
            body = (
                f"This card holds {darks} dark set"
                f"{'s' if darks != 1 else ''} and no imaging sessions. Darks "
                f"on their own cannot be stacked — point at the card that "
                f"has the sessions on it, or shoot a target first."
            )
        elif skipped and not result.sessions:
            title = "Nothing here could be read as a session"
            body = (
                "Folders were found, but none of them held light frames this "
                "app recognises. A DWARF 3 writes its subs as .fits files "
                "ending in the sensor temperature; its own live stack, its "
                "previews and anything you have processed in place are all "
                "skipped on purpose."
            )
        else:
            title = "Nothing to stack on this card"
            body = (
                "No DWARF 3 imaging sessions were found here. Point at the "
                "drive itself or at the Astronomy folder inside it — either "
                "works — or plug the card in and look again."
            )

        detail = ""
        if skipped:
            shown = skipped[:4]
            detail = "Skipped:  " + "   ·   ".join(shown)
            if len(skipped) > len(shown):
                detail += f"   ·   and {len(skipped) - len(shown)} more"

        self._set_source_summary(
            f"{self._card_name()} was read, and holds nothing to stack.",
            theme.WARN,
        )
        self.grid_host.hide()
        self.targets_state.show_state(
            title,
            body,
            detail,
            (("Choose folder...", self._choose_source, True),
             ("Look for drives again", self._look_for_drives, False)),
        )
        self.results_area.setVisible(self._mode != MODE_CLEAN)
        if self._mode == MODE_CLEAN:
            self._show_cleanup()

    def _busy(self) -> bool:
        """True while a build or a stack is running.

        Nothing may be deleted during either: the run is reading those very
        files, and removing one underneath it would fail confusingly at best.
        """
        if self.build_worker is not None and self.build_worker.isRunning():
            return True
        if self.run_panel is not None:
            worker = getattr(self.run_panel, "worker", None)
            if worker is not None and worker.isRunning():
                return True
        return False

    def _refuse_while_busy(self) -> bool:
        if not self._busy():
            return False
        self._warn(
            "Not while a stack is running",
            "A build or stack is using these files right now. Wait for it to "
            "finish, or stop it, and then try again.",
        )
        return True

    def _open_stack_grid(self, card: GroupCard) -> None:
        """Show every frame of a group, with whatever verdicts we have."""
        if self._refuse_while_busy():
            return
        sessions = card.selected_sessions or card.group.sessions
        if not sessions:
            return
        window = StackGridWindow(sessions[0], self._frame_verdicts, self)
        window.changed.connect(self._rescan_after_delete)
        window.exec()

    def _open_cleanup(self) -> None:
        """The button beside the drive picker. One door among two, one screen.

        It used to open a dialog. Now it switches to the Clean up mode, so
        there is a single implementation of the most dangerous screen in the
        app and only one place it can ever appear.
        """
        self._set_mode(MODE_CLEAN)

    def _rescan_after_delete(self) -> None:
        """Re-read the card so nothing on screen is claiming stale counts."""
        if self.source_root is not None:
            self._start_scan(self.source_root)

    def _regroup(self, card: GroupCard) -> None:
        """Re-run the checks after the user ticked or unticked a session."""
        if self.scan_result is None:
            return
        card.set_group(
            build_group(
                card.selected_sessions,
                self.scan_result.darks,
                self.scan_result.cali_masters,
                use_cali_fallback=self.use_dwarf_master.isChecked()
                if hasattr(self, "use_dwarf_master")
                else True,
            )
        )

    # -- step 3: output --------------------------------------------------

    def _output_section(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(
            theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3
        )
        layout.setSpacing(theme.SPACE_4)

        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_2)
        self.output_field = QLineEdit()
        self.output_field.setPlaceholderText("Where should the Siril project go?")
        self.output_field.setReadOnly(True)
        self.output_field.setMinimumWidth(80)   # may shrink with the column
        row.addWidget(self.output_field, 1)

        choose = QPushButton("Choose...")
        choose.setObjectName("Ghost")
        choose.setCursor(Qt.CursorShape.PointingHandCursor)
        choose.setToolTip("Pick an empty folder for the Siril project")
        choose.clicked.connect(self._choose_output)
        row.addWidget(choose)
        layout.addLayout(row)

        # There was a "Link instead of copying" tick box here. It asked the
        # user to choose between two mechanisms that produce identical output,
        # and its label recommended putting the project on the card -- the one
        # place it must never go. On this hardware it could never have taken
        # effect anyway: the card is exFAT, which has no hard links, and links
        # cannot cross volumes regardless. The build now links where that is
        # genuinely possible and copies where it is not, and says nothing
        # about which, because there is nothing there for anyone to decide.

        self.use_dwarf_master = QCheckBox("Fall back to the DWARF's master dark")
        self.use_dwarf_master.setChecked(True)
        self.use_dwarf_master.stateChanged.connect(self._recheck_all)
        layout.addWidget(self.use_dwarf_master)
        layout.addWidget(
            _explainer("Used only when no dark set of your own matches the "
                       "lights.")
        )

        note = _label(
            "Your DWARF folders are only ever read. Nothing is moved, renamed "
            "or deleted on the card.",
            "Faint",
            wrap=True,
        )
        layout.addWidget(note)
        return card

    def _recheck_all(self) -> None:
        for card in self.group_cards:
            self._regroup(card)

    def _choose_output(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose an output folder")
        if not chosen:
            return
        self.output_dir = Path(chosen)
        self.output_field.setText(chosen)

    # -- step 4: build ---------------------------------------------------

    def _start_build(self, card: GroupCard) -> None:
        if self.output_dir is None:
            self._choose_output()
            if self.output_dir is None:
                self._warn(
                    "Pick an output folder first",
                    "Choose somewhere for the Siril project to be built.",
                )
                return

        group = card.group
        if group.errors:
            return

        if not group.has_calibration:
            # The moment they are actually about to do it is the moment the
            # advice is worth something. Yes is the default here: stacking
            # without darks is a perfectly reasonable thing to do and they
            # have clearly been doing it. This is help, not a warning gate.
            box = QMessageBox(self)
            box.setWindowTitle("Stacking without darks")
            box.setIcon(QMessageBox.Icon.Information)
            box.setText("This will stack without darks — that is fine.")
            box.setInformativeText(group.dark_advice)
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            box.button(QMessageBox.StandardButton.Yes).setText("Stack it anyway")
            box.button(QMessageBox.StandardButton.No).setText("Not now")
            box.setDefaultButton(QMessageBox.StandardButton.Yes)
            if box.exec() != QMessageBox.StandardButton.Yes:
                return

        # Each target gets its own subfolder, so several stacks can share one
        # output folder without their process/ directories colliding.
        destination = self.output_dir / group.suggested_name()
        self._last_stack_name = group.suggested_name()
        self._last_group = group

        for other in self.group_cards:
            other.set_busy(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.show()
        self.cancel_button.show()
        self.open_button.hide()

        post = self.layers_card.options()
        for note in post.resolve():
            self.status.setText(note)
        self._last_post = post
        quality = self.layers_card.quality()
        framing = self.layers_card.framing()

        self.build_worker = BuildWorker(
            group,
            destination,
            stack_name=group.suggested_name(),
            post=post,
            quality=quality,

            framing=framing,
        )
        self.build_worker.progressed.connect(self._on_build_progress)
        self.build_worker.finished_ok.connect(self._on_built)
        self.build_worker.failed.connect(self._on_build_failed)
        self.build_worker.cancelled.connect(self._on_build_cancelled)
        self.build_worker.start()

    def _remember_stack(self) -> None:
        """Record which sessions have been stacked, and where to.

        Only recorded when a stack actually SUCCEEDS, because the cleanup
        view uses this to say "you already stacked this" -- and that claim
        has to be true or it will talk somebody into deleting their only
        copy.
        """
        if self._last_output_dir is None or self._last_group is None:
            return
        try:
            remember_stacked(
                [session.path for session in self._last_group.sessions],
                self._last_output_dir,
            )
        except Exception:  # noqa: BLE001 - bookkeeping is never worth a crash
            pass

    def _on_stack_finished(self, ok: bool) -> None:
        """Show the before/after view once Siril has finished.

        A missing or unreadable preview must never turn a successful stack
        into a failure, so this only ever adds a panel -- it cannot take the
        success away.
        """
        if ok:
            self._remember_stack()
        if not ok or self.preview_panel is None or self._last_output_dir is None:
            return
        try:
            # The options themselves, not a list of labels made from them.
            # The panel needs to know what was TICKED to explain what is
            # missing, and solvability is why the two layers that can go
            # missing without anything going wrong do so.
            shown = self.preview_panel.load_from(
                self._last_output_dir,
                self._last_stack_name,
                self._last_post,
                self._last_group.can_plate_solve
                if self._last_group is not None
                else True,
            )
        except Exception:  # noqa: BLE001 - a preview is never worth failing over
            shown = False

        self.preview_panel.setVisible(shown)
        if shown:
            QTimer.singleShot(
                80,
                lambda: self.main_scroll.ensureWidgetVisible(self.preview_panel),
            )

    def _on_build_progress(self, done: int, total: int, message: str) -> None:
        self.progress.setValue(int(done * 100 / total) if total else 100)
        self.status.setText(message)

    def _on_built(self, result) -> None:
        self._end_build()
        self.output_dir_last = result.output_dir
        self.open_button.show()
        self.status.setText(
            f"Built {result.lights_copied} lights and {result.darks_copied} darks "
            f"in {result.output_dir.name}"
        )

        self._last_output_dir = result.output_dir

        # Step 4 is in the sidebar rather than a dialog: the user is about to
        # watch a stack that can run a long time, and a modal box is the
        # wrong shape for something you sit and watch.
        self.run_placeholder.hide()
        self.run_panel.show_result(result, self._last_stack_name)
        self.run_panel.show()

        # If the window is narrow enough that the sidebar folded, unfold it:
        # the thing the user just asked for lives in there. Only when it is
        # actually folded, so an automatic sidebar stays automatic.
        if not self.sidebar.isVisible():
            self._choose_sidebar(True)

        if result.warnings:
            self._warn(
                "Built, with some problems",
                "\n".join(result.warnings),
            )

        QTimer.singleShot(
            60, lambda: self.sidebar_scroll.ensureWidgetVisible(self.run_panel)
        )

    def _on_build_failed(self, message: str) -> None:
        self._end_build()
        self.status.setText("Build failed.")
        self._warn("Could not build that stack", message)

    def _on_build_cancelled(self, message: str) -> None:
        self._end_build()
        self.status.setText(f"Stopped. {message}")

    def _on_stack_running(self, running: bool) -> None:
        """Put Stop in the status bar for as long as Siril is going.

        The run panel's own Stop lives inside the scrolling sidebar and can
        be scrolled out of sight. Stop is the one control somebody needs to
        reach in a hurry, so while a stack is running there is always one on
        screen, outside any scroll area, whatever mode you are in.
        """
        self._stack_running = running
        self.cancel_button.setText("Stop stacking" if running else "Stop")
        self.cancel_button.setVisible(running)
        self.cancel_button.setEnabled(True)

    def _cancel_build(self) -> None:
        # One button, two jobs, and it must stop the one that is actually
        # running rather than the one it was originally written for.
        if getattr(self, "_stack_running", False) and self.run_panel is not None:
            self.run_panel._stop()
            self.cancel_button.setEnabled(False)
            self.status.setText("Stopping Siril...")
            return
        if self.build_worker is not None:
            self.build_worker.request_stop()
            self.status.setText("Stopping after the current frame...")

    def _end_build(self) -> None:
        self.progress.hide()
        self.cancel_button.hide()
        for card in self.group_cards:
            card.set_busy(False)

    def _open_output(self) -> None:
        target = getattr(self, "output_dir_last", None) or self.output_dir
        if target is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    # -- helpers ---------------------------------------------------------

    def _warn(self, title: str, message: str) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(title)
        box.setInformativeText(message)
        box.setIcon(QMessageBox.Icon.Warning)
        box.exec()

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                MainWindow._clear_layout(item.layout())

    def closeEvent(self, event) -> None:
        if self.run_panel is not None:
            self.run_panel.shutdown()
        for worker in (self.scan_worker, self.build_worker):
            if worker is not None and worker.isRunning():
                if isinstance(worker, BuildWorker):
                    worker.request_stop()
                worker.wait(3000)
        super().closeEvent(event)


def application_icon() -> QIcon:
    """The app's own icon, from the bundle or from the source tree.

    PyInstaller unpacks data files to sys._MEIPASS, so the packaged app and a
    source checkout look for it in different places. A missing icon is not an
    error -- Qt falls back to its own, which is only cosmetic.
    """
    candidates = []
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        candidates.append(Path(bundled) / "icon.ico")
    candidates.append(Path(__file__).resolve().parents[2] / "packaging" / "icon.ico")

    for candidate in candidates:
        try:
            if candidate.is_file():
                icon = QIcon(str(candidate))
                if not icon.isNull():
                    return icon
        except OSError:
            continue
    return QIcon()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Dwarf2Siril")
    app.setStyle("Fusion")
    app.setStyleSheet(theme.stylesheet())

    icon = application_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    window = MainWindow()
    window.show()

    # Development only, and imported HERE rather than at module scope.
    # devreload is deliberately excluded from the packaged build, so a
    # top-level import would make the shipped exe fail to start at all --
    # which is exactly what it did until the bundle was actually run.
    try:
        from . import devreload

        devreload.install(app, window)
        devreload.restore(window)
    except ImportError:
        pass   # not present in a packaged build, which is the intent

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
