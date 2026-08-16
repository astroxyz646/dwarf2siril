"""The optional-layers card: tick boxes for what to do after stacking.

Everything here is off by default and the card says so. Each layer states
what it does and what it costs, because several of them are taste calls
rather than improvements -- star reduction in particular changes real data,
and should read as an option rather than a recommendation.

A layer whose tool is missing is never a silently dead tick box: it says what
is missing, what it would enable, and where to get it, and offers a picker
for someone who already has it somewhere unusual.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..model import FRAMING_BLURB, FRAMING_CLEAN, FRAMING_LABELS, FRAMING_WHOLE
from ..postprocess import PostOptions, find_starnet, load_settings, save_setting
from ..quality import DEFAULT_STRENGTH, STRENGTHS, QualityFilter
from . import theme
from .cards import divider


def _label(text: str, name: str = "", wrap: bool = True) -> QLabel:
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


class LayerRow(QWidget):
    """One tick box. The explanation is a tooltip until something is wrong.

    The sentences explaining each layer used to sit permanently under every
    tick box, which is five paragraphs of text for five options. They are
    still there -- on hover -- and anything the user MUST see (a missing
    tool, a destructive step) still shows on the face, because compactness
    must not push a real warning off screen.
    """

    toggled = Signal()

    def __init__(self, title: str, detail: str, warning: str = "") -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(1)

        self.checkbox = QCheckBox(title)
        self.checkbox.setToolTip(detail)
        self.checkbox.stateChanged.connect(lambda _: self.toggled.emit())
        layout.addWidget(self.checkbox)

        self.detail = _label(detail, "Faint")
        self.detail.setContentsMargins(22, 0, 0, 0)
        self.detail.hide()
        layout.addWidget(self.detail)

        self.warning = _label("", "Faint")
        self.warning.setContentsMargins(22, 0, 0, 0)
        self.warning.setTextFormat(Qt.TextFormat.RichText)
        if warning:
            self.warning.setText(
                f'<span style="color:{theme.WARN};">{warning}</span>'
            )
        else:
            self.warning.hide()
        layout.addWidget(self.warning)

    @property
    def checked(self) -> bool:
        return self.checkbox.isChecked()

    def set_unavailable(self, message: str) -> None:
        self.checkbox.setChecked(False)
        self.checkbox.setEnabled(False)
        self.warning.setText(f'<span style="color:{theme.ERROR};">{message}</span>')
        self.warning.show()

    def set_available(self, message: str = "") -> None:
        self.checkbox.setEnabled(True)
        if message:
            self.warning.setText(f'<span style="color:{theme.OK};">{message}</span>')
            self.warning.show()


class LayersCard(QFrame):
    """Step 3b: what to do to the stack once it exists."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.starnet_path: Path | None = None
        self._framing_chosen = False

        # No saving until the card is built and the remembered state has been
        # put back. Building the card fires the same signals a user does, and
        # a card that saves while it is still empty writes ITS OWN blank
        # state over the settings it is about to read -- which is how the
        # first attempt at remembering managed to forget everything.
        self._restoring = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        layout.addWidget(_label("EXTRAS", "Faint"))
        layout.addWidget(
            _label(
                "Applied to a copy. Your plain stack is always kept.",
                "Muted",
            )
        )
        layout.addSpacing(2)

        self.background = LayerRow(
            "Remove background gradient",
            "Models the sky background and subtracts it. This is what takes "
            "out light pollution and the corner-to-corner brightness slope. "
            "Usually the single biggest improvement, and safe.",
        )
        self.plate_solve = LayerRow(
            "Plate solve",
            "Works out exactly where the image is pointing and writes real sky "
            "coordinates into the file. Seeded with the DWARF's known focal "
            "length and the coordinates it recorded, so it is fast and "
            "reliable. Works offline.",
        )
        self.colour = LayerRow(
            "Photometric colour calibration",
            "Sets colour balance from the measured brightness of known stars "
            "instead of by eye. Needs plate solving first, and needs the "
            "internet to look the stars up.",
        )
        self.denoise = LayerRow(
            "Denoise",
            "Siril's NL-Bayes denoiser. Helps most on short total integration. "
            "Overdone, it smooths away faint real detail.",
        )
        self.stars = LayerRow(
            "Reduce stars",
            "Separates stars from everything else and puts them back smaller, "
            "so the nebula or galaxy stands out.",
            warning="A taste call, and destructive: the stars in the result "
            "are no longer what the sensor recorded. The plain stack is kept, "
            "so nothing is lost.",
        )

        self.stretch = LayerRow(
            "Stretch it into a picture",
            "A stack straight out of Siril is linear: nearly all the signal "
            "is crammed into the bottom of the range, which is why it looks "
            "like a flat grey rectangle. This is the step that opens it out "
            "into something you would actually show someone. Runs last, "
            "after everything else, because every other layer needs the "
            "linear data.",
        )

        for row in (
            self.background,
            self.plate_solve,
            self.colour,
            self.denoise,
            self.stars,
        ):
            row.toggled.connect(self._on_change)
            layout.addWidget(row)

        # Star amount, only meaningful when star reduction is on.
        # Two stacked rows rather than one long one: this card now lives in a
        # ~330px sidebar, and a fixed 200px slider sharing a line with a
        # label and a button would have set the minimum width of the window.
        self.amount_box = QWidget()
        self.amount_box.setObjectName("Plain")
        amount_layout = QVBoxLayout(self.amount_box)
        amount_layout.setContentsMargins(28, 0, 0, 6)
        amount_layout.setSpacing(4)

        slider_row = QHBoxLayout()
        slider_row.setSpacing(10)
        slider_row.addWidget(_label("Keep", "Faint", wrap=False))
        self.amount = QSlider(Qt.Orientation.Horizontal)
        self.amount.setRange(0, 100)
        self.amount.setValue(50)
        self.amount.setMinimumWidth(90)
        self.amount.valueChanged.connect(self._on_amount)
        slider_row.addWidget(self.amount, 1)
        self.amount_label = _label("50% of the stars", "Faint", wrap=False)
        slider_row.addWidget(self.amount_label)
        amount_layout.addLayout(slider_row)

        self.locate_starnet = QPushButton("Locate StarNet...")
        self.locate_starnet.setObjectName("Ghost")
        self.locate_starnet.setCursor(Qt.CursorShape.PointingHandCursor)
        self.locate_starnet.clicked.connect(self._locate_starnet)
        amount_layout.addWidget(
            self.locate_starnet, 0, Qt.AlignmentFlag.AlignLeft
        )
        layout.addWidget(self.amount_box)
        self.amount_box.hide()

        # Added here rather than in the loop above so the star-amount slider
        # stays directly under the star tick box it belongs to.
        self.stretch.toggled.connect(self._on_change)
        layout.addWidget(self.stretch)

        # Edges, shown only when there is a real trade: an alt-az session,
        # or separate sessions being combined. Someone stacking one steady
        # EQ session is never asked -- their frames are trimmed to their
        # shared area anyway, which costs them nothing.
        self.framing_box = QWidget()
        self.framing_box.setObjectName("Plain")
        framing_layout = QVBoxLayout(self.framing_box)
        framing_layout.setContentsMargins(0, 6, 0, 0)
        framing_layout.setSpacing(3)
        framing_layout.addWidget(divider())
        framing_layout.addWidget(_label("EDGES", "Faint"))
        self.framing_reason = _label("", "Muted")
        framing_layout.addWidget(self.framing_reason)

        self.framing_group = QButtonGroup(self)
        for index, key in enumerate((FRAMING_WHOLE, FRAMING_CLEAN)):
            button = QRadioButton(FRAMING_LABELS[key])
            button.setProperty("framing_key", key)
            if key == FRAMING_WHOLE:
                button.setChecked(True)
            self.framing_group.addButton(button, index)
            framing_layout.addWidget(button)

            # The cost goes on screen, not in a tooltip. Losing 80% of the
            # picture is not something to discover after the fact.
            blurb = _label(FRAMING_BLURB[key], "Faint")
            blurb.setContentsMargins(22, 0, 8, 4)
            framing_layout.addWidget(blurb)

        # buttonClicked fires only on real user interaction, unlike
        # buttonToggled which also fires when we pre-select a default. That
        # distinction is what lets an untouched control mean "decide per
        # target" rather than "whatever radio happened to be selected".
        self.framing_group.buttonClicked.connect(self._on_framing_clicked)
        layout.addWidget(self.framing_box)
        self.framing_box.hide()

        layout.addWidget(divider())

        # Frame filtering is not an "extra" in the same sense -- it is on by
        # default and shapes the stack itself -- so it gets its own line and
        # its own words rather than sitting among the optional layers.
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_label = _label("Drop bad frames", wrap=False)
        filter_label.setToolTip(
            "Frames ruined by cloud, wind or poor seeing are left out of the "
            "stack. Siril measures every frame while aligning them; this "
            "decides how fussy to be about the result."
        )
        filter_row.addWidget(filter_label)
        self.frame_filter = QComboBox()
        for key in STRENGTHS:
            self.frame_filter.addItem(key.capitalize(), key)
        self.frame_filter.setCurrentText(DEFAULT_STRENGTH.capitalize())
        self.frame_filter.currentIndexChanged.connect(self._on_filter_change)
        filter_row.addWidget(self.frame_filter)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        self.filter_blurb = _label("", "Faint")
        layout.addWidget(self.filter_blurb)

        self.previews = QCheckBox("Save before/after previews")
        self.previews.setToolTip(
            "Small JPEGs showing what each step did, saved next to your .fit."
        )
        self.previews.setChecked(True)
        self.previews.stateChanged.connect(lambda _: (self._remember(), self.changed.emit()))
        layout.addWidget(self.previews)

        self._on_filter_change()
        self.refresh_tools()
        self._restore()

    # -- remembering -----------------------------------------------------

    # The tick boxes, by the name they are saved under. Order is not
    # significant; the names are, because they are on disk.
    def _saveable(self) -> dict:
        return {
            "background_removal": self.background,
            "plate_solve": self.plate_solve,
            "colour_calibration": self.colour,
            "denoise": self.denoise,
            "star_reduction": self.stars,
            "stretch": self.stretch,
        }

    def _restore(self) -> None:
        """Put the tick boxes back the way the user last left them.

        Every extra starts off, and until now it started off again on EVERY
        launch. That is a trap rather than a safe default: the user ticks
        five layers, restarts the app for some unrelated reason, stacks, and
        gets a plain stack with no hint that anything was dropped -- because
        from the app's point of view nothing was. Watched it happen three
        times in one morning.

        Restored AFTER refresh_tools, so a remembered star reduction cannot
        tick a box that has since been disabled for want of StarNet.
        """
        saved = load_settings().get("layers")
        try:
            if not isinstance(saved, dict):
                return

            for key, row in self._saveable().items():
                if row.checkbox.isEnabled() and isinstance(saved.get(key), bool):
                    row.checkbox.setChecked(saved[key])

            amount = saved.get("star_amount")
            if isinstance(amount, (int, float)) and 0 <= amount <= 1:
                self.amount.setValue(int(amount * 100))

            if isinstance(saved.get("previews"), bool):
                self.previews.setChecked(saved["previews"])

            strength = saved.get("frame_filter")
            if strength in STRENGTHS:
                self.frame_filter.setCurrentText(strength.capitalize())
        finally:
            self._restoring = False

        self._on_change()

    def _remember(self) -> None:
        if getattr(self, "_restoring", False):
            return
        state = {key: row.checked for key, row in self._saveable().items()}
        state["star_amount"] = self.amount.value() / 100.0
        state["previews"] = self.previews.isChecked()
        state["frame_filter"] = self.frame_filter.currentData() or DEFAULT_STRENGTH
        save_setting("layers", state)

    def _on_filter_change(self) -> None:
        self.filter_blurb.setText(self.quality().describe())
        self._remember()
        self.changed.emit()

    def quality(self) -> QualityFilter:
        key = self.frame_filter.currentData() or DEFAULT_STRENGTH
        return QualityFilter(enabled=key != "off", strength=key)

    def _on_framing_clicked(self, _button) -> None:
        self._framing_chosen = True
        self.changed.emit()

    def show_framing(self, groups) -> None:
        """Reveal the framing choice only when there is a real trade to make.

        Frames never cover identical sky, but the answer only matters when
        the field rotated or when separate sessions are being combined.
        Someone stacking one steady EQ session is not asked -- their frames
        are trimmed to their shared area anyway, which costs them nothing.
        """
        altaz = [g for g in groups if g.is_altaz]
        multi = [g for g in groups if len(g.sessions) > 1]
        needed = bool(altaz or multi)
        self.framing_box.setVisible(needed)
        self._framing_chosen = False
        if not needed:
            return

        # This control is one setting, but the right answer differs per
        # target: a drifted multi-session stack wants trimming and a rotated
        # alt-az one does not. So until the user actually picks, each target
        # gets its own default -- and the wording says so, rather than a
        # pre-selected radio quietly deciding for a target it does not suit.
        reasons = []
        if multi:
            reasons.append(
                "separate sessions never start pointing identically"
            )
        if altaz:
            reasons.append("the field rotates in alt-az")
        self.framing_reason.setText(
            f"Your frames do not all cover the same sky, because "
            f"{' and '.join(reasons)}. Handled per target unless you choose "
            f"here: trimmed when the mount drifted, whole frame when the "
            f"field rotated."
        )

        wanted = FRAMING_WHOLE if altaz else FRAMING_CLEAN
        for button in self.framing_group.buttons():
            if button.property("framing_key") == wanted:
                button.setChecked(True)
                break

    def framing(self) -> str | None:
        """The user's choice, or None to let each group pick its own default.

        None matters: when the choice is not on screen there is nothing to
        honour, and returning a value here would override the per-group
        default with whichever radio button happened to be pre-selected.
        """
        if not self.framing_box.isVisible() or not self._framing_chosen:
            return None
        button = self.framing_group.checkedButton()
        if button is None:
            return None
        return button.property("framing_key")

    # -- tools -----------------------------------------------------------

    def refresh_tools(self) -> None:
        status = find_starnet(self.starnet_path)
        if status.available:
            self.starnet_path = status.path
            self.stars.set_available(f"StarNet2 found in {status.found_in}.")
        else:
            self.stars.set_unavailable(
                "StarNet2 is not installed, so this is unavailable. It is a "
                "free download from starnetastro.com -- get the command-line "
                "ZIP, unpack it anywhere, then use Locate StarNet... below. "
                "Everything else on this card works without it."
            )
            self.locate_starnet.show()
            self.amount_box.show()

    def _locate_starnet(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Find starnet2.exe",
            "",
            "StarNet (starnet2.exe starnet++.exe starnet2 starnet++);;All files (*)",
        )
        if not chosen:
            return
        self.starnet_path = Path(chosen)
        # Remember it, so this is a once-only chore.
        save_setting("starnet_path", str(self.starnet_path))
        self.refresh_tools()
        self.changed.emit()

    # -- state -----------------------------------------------------------

    def _on_amount(self, value: int) -> None:
        self.amount_label.setText(f"{value}% of the stars")
        self._remember()
        self.changed.emit()

    def _on_change(self) -> None:
        self.amount_box.setVisible(self.stars.checked or not self.stars.checkbox.isEnabled())

        # Colour calibration needs a solve. Rather than refusing, tick the
        # prerequisite and show that it happened.
        if self.colour.checked and not self.plate_solve.checked:
            self.plate_solve.checkbox.setChecked(True)
        self._remember()
        self.changed.emit()

    def options(self) -> PostOptions:
        return PostOptions(
            background_removal=self.background.checked,
            denoise=self.denoise.checked,
            plate_solve=self.plate_solve.checked,
            colour_calibration=self.colour.checked,
            star_reduction=self.stars.checked,
            stretch=self.stretch.checked,
            star_amount=self.amount.value() / 100.0,
            starnet_path=self.starnet_path,
            previews=self.previews.isChecked(),
        )

