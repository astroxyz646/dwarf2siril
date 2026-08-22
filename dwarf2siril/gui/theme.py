"""The window's colours, and the palettes it can wear.

Tuned for the situation the tool is used in: a dark room, at night, often
straight after a session. The default background is near-black rather than
mid-grey, because a bright panel at 2am is genuinely unpleasant and washes
out dark-adapted vision.

The default accent is a deep, slightly desaturated blue. A pure #0080FF on
near-black glares; this one is pulled down in both lightness and saturation
so it reads as a calm, deliberate highlight rather than a light source. Note
that blue is the WORST colour for dark adaptation -- short-wavelength light
costs the most of it, which is why red torches are standard at a telescope --
so this is a considered aesthetic choice, not a physiological one. Anyone at
the eyepiece should be dimming their screen anyway.

Everything is one flat token set so the whole window stays consistent.
Nothing outside this module should name a colour: if a widget needs one, it
either takes an object name that is styled here, or it imports a token.

*** HOW SWITCHING WORKS ***
Every colour lives on a frozen ``Palette``. ``set_palette`` copies the chosen
one's fields onto THIS MODULE'S globals, so ``theme.BG`` keeps meaning "the
active background" at the ninety-odd places across the gui package that read
it. Rebinding module attributes is unusual, and it is chosen deliberately:
the alternative is threading a palette object through every widget
constructor in the package, and a switch that costs a ninety-site rewrite is
a switch nobody adds.

Repainting is two things, and BOTH are needed:

1. ``app.setStyleSheet(theme.stylesheet())`` -- the global sheet. Qt
   repolishes every widget that takes its colours from an object name, which
   is most of them, and which is why rules live here rather than inline.
2. ``changed`` -- a signal, for the rest. A widget that bakes a colour into
   an inline sheet, a QBrush, a rich-text span or a paintEvent cannot be
   reached by a style sheet. Those widgets pass themselves to ``follow`` and
   grow a ``restyle`` method; the signal calls it.

Three scales carry the rhythm, and every margin, gap and corner in the window
is one of their values. NONE of them are per-palette -- a theme changes the
colours, never the layout, or a switch would reflow the window:

* ``SPACE_*``   -- 4px steps, for layout margins and spacing.
* ``RADIUS_*``  -- corner radii, small for controls, larger for surfaces.
* the surfaces  -- BG through SURFACE_HOVER, which do the work borders used
  to. Elevation separates panels; a hairline is only added where two
  same-coloured surfaces meet.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from PySide6.QtCore import QObject, Signal


@dataclass(frozen=True)
class Palette:
    """One complete set of colours. Frozen: a palette is a fact, not a state.

    The field comments below are the reasoning behind the DEFAULT values, in
    Deep Space. Every other palette answers the same questions its own way,
    and where one deviates it says so at its own definition.
    """

    # The name shown in the picker, and the string written to settings.
    name: str
    # Whether this palette reads as dark. Drives Windows' immersive dark
    # title bar, which is a boolean the OS owns rather than a colour we
    # choose -- get it wrong and the caption text ends up the same tone as
    # the caption behind it.
    dark: bool

    # ---- surfaces, darkest first (on a dark palette) --------------------
    # BG_SUNKEN is only for the ground behind a photograph, where anything
    # lighter would sit in the picture's tonal range and compete with it.
    # This is a ROLE, not a lightness: on Daylight it stays DARK, because an
    # astrophoto is almost entirely near-black and a white mount around it
    # glares and flattens everything in the frame.
    BG_SUNKEN: str
    # Because BG_SUNKEN does not follow the rest of the palette, anything
    # drawn ON it needs its own two tokens rather than TEXT_MUTED and TEXT.
    SUNKEN_TEXT: str
    SUNKEN_TEXT_BRIGHT: str

    BG: str
    SURFACE: str
    SURFACE_RAISED: str
    SURFACE_HOVER: str
    SURFACE_PRESSED: str

    # Borders are deliberately quiet. Most separation in this window comes
    # from the surface steps above; a line is a last resort, not the default.
    # STRONG and BRIGHT mean "more contrast against the surface", which on a
    # dark palette is lighter and on a light one is darker.
    BORDER: str
    BORDER_STRONG: str
    BORDER_BRIGHT: str

    # ---- text -----------------------------------------------------------
    TEXT_BRIGHT: str
    TEXT: str
    TEXT_MUTED: str
    TEXT_FAINT: str

    # ---- accent ---------------------------------------------------------
    # HOVER means "more prominent", not "lighter": on a light palette the
    # accent gets darker when you point at it, because lighter would fade.
    ACCENT: str
    ACCENT_HOVER: str
    ACCENT_PRESSED: str
    # Focus rings and selection washes. Always a low-contrast relative of the
    # accent, so a ring never shouts louder than the thing it marks.
    ACCENT_DIM: str
    # Text drawn ON TOP of a filled accent button. Near-black on the dark
    # palettes, whose accents are light enough to carry it; white on
    # Daylight, whose accent is a deep blue. Getting this one backwards is
    # the single most likely way to ship an unreadable primary button.
    ACCENT_FG: str

    # ---- status ---------------------------------------------------------
    # Each of these has to survive being seen next to the accent, so all
    # four sit well away from it. RUNNING is the odd one out and the reason
    # it exists: work in progress used to be drawn in the accent, which on a
    # blue theme is indistinguishable from "this one is selected". A
    # cyan-teal reads as motion instead, at a glance, without joining the
    # warn/error vocabulary.
    OK: str
    WARN: str
    ERROR: str
    ERROR_HOVER: str
    ERROR_PRESSED: str
    RUNNING: str

    # Text drawn on top of a filled ERROR button. Near-black rather than
    # white on the dark palettes: white on those reds is the weaker pairing,
    # and a destructive button should not also be the hardest thing to read.
    # Daylight's error is dark enough that the reasoning flips.
    DANGER_FG: str

    # ---- washes ---------------------------------------------------------
    # The alpha used when TEXT is laid over a surface to make a hover state
    # (see ``tint``). On a dark palette that is a pale wash lightening the
    # surface; on a light one it is near-black darkening it, and the same
    # alpha would be far too weak to see -- so the AMOUNT is per-palette
    # rather than a literal in the sheet.
    WASH_SOFT: int
    WASH_HARD: int


_COLOUR_FIELDS = tuple(
    field.name for field in fields(Palette) if field.name not in ("name", "dark")
)


# ---- the palettes --------------------------------------------------------

DEEP_SPACE = Palette(
    name="Deep Space",
    dark=True,
    BG_SUNKEN="#05070A",
    SUNKEN_TEXT="#8E99AC",
    SUNKEN_TEXT_BRIGHT="#E8ECF4",
    BG="#0A0C10",
    SURFACE="#141924",
    SURFACE_RAISED="#1C2231",
    SURFACE_HOVER="#242C3E",
    SURFACE_PRESSED="#161B27",
    BORDER="#1F2634",
    BORDER_STRONG="#2E3849",
    BORDER_BRIGHT="#3F4B60",
    TEXT_BRIGHT="#FFFFFF",
    TEXT="#E8ECF4",
    TEXT_MUTED="#8E99AC",
    TEXT_FAINT="#5E6879",
    ACCENT="#4C8FD9",
    ACCENT_HOVER="#6BA6E8",
    ACCENT_PRESSED="#3B79BE",
    ACCENT_DIM="#2E567F",
    ACCENT_FG="#04101C",
    OK="#4FC98C",
    WARN="#E3A93F",
    ERROR="#E5675E",
    ERROR_HOVER="#EE7C73",
    ERROR_PRESSED="#CF574F",
    RUNNING="#38BEC9",
    DANGER_FG="#1A0806",
    WASH_SOFT=0x0A,
    WASH_HARD=0x1A,
)

PALETTES: dict[str, Palette] = {
    palette.name: palette for palette in (DEEP_SPACE,)
}

DEFAULT_PALETTE = DEEP_SPACE.name

#: The settings key the chosen palette is remembered under.
SETTING_KEY = "theme"


# ---- spacing and radii, which no palette touches -------------------------
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 20
SPACE_6 = 24

RADIUS_XS = 4
RADIUS_SM = 8
RADIUS_MD = 12
RADIUS_LG = 16

FONT_STACK = '"Segoe UI Variable Text", "Segoe UI", "Inter", system-ui, sans-serif'
MONO_STACK = '"Cascadia Code", "Consolas", "SF Mono", monospace'


# ---- the active palette --------------------------------------------------


class _Bus(QObject):
    """Carries the one signal. A module cannot own a Signal; a QObject can."""

    changed = Signal()


_bus = _Bus()

#: Emitted after the active palette changes. Connect through ``follow``.
changed = _bus.changed

_active: Palette = DEEP_SPACE


def active() -> Palette:
    """The palette currently in force."""
    return _active


def names() -> list[str]:
    """Every palette name, in the order the picker should offer them."""
    return list(PALETTES)


def resolve(name: str | None) -> Palette:
    """The palette called ``name``, or the default if there is no such thing.

    An unknown name is not an error. A settings file written by a newer
    build, or edited by hand, should open the app in Deep Space rather than
    refuse to start.
    """
    return PALETTES.get(name or "", PALETTES[DEFAULT_PALETTE])


def _publish(palette: Palette) -> None:
    """Copy ``palette`` onto this module's globals. See the module docstring."""
    global _active
    _active = palette
    namespace = globals()
    for token in _COLOUR_FIELDS:
        namespace[token] = getattr(palette, token)
    namespace["IS_DARK"] = palette.dark
    namespace["PALETTE_NAME"] = palette.name


def set_palette(name: str) -> Palette:
    """Make the palette called ``name`` active. Does NOT repaint anything.

    Use ``apply`` for that. This one is for before the window exists, where
    there is nothing to repaint yet.
    """
    palette = resolve(name)
    _publish(palette)
    return palette


def apply(app, name: str) -> Palette:
    """Switch palette and repaint the whole window.

    Both halves of the repaint, in the order that matters: the global sheet
    first, so every object-named widget is already correct by the time the
    widgets that restyle themselves go looking at their neighbours.
    """
    palette = set_palette(name)
    if app is not None:
        app.setStyleSheet(stylesheet())
    _bus.changed.emit()
    return palette


def follow(widget) -> None:
    """Call ``widget.restyle()`` whenever the palette changes.

    For the widgets the global sheet cannot reach: inline sheets, QBrushes,
    rich-text spans and paintEvents. Qt drops the connection when the widget
    is destroyed, so there is nothing to undo.
    """
    _bus.changed.connect(widget.restyle)


def repolish(widget, name: str | None = None) -> None:
    """Make Qt re-read the sheet for one widget, optionally under a new name.

    Qt matches a ``#Name`` rule when a widget is polished and not again, so a
    widget whose object name is part of its STATE has to ask. Passing
    ``name`` renames it first, which is how a label whose COLOUR is its
    meaning changes what it means: "" puts it back on the default rules.
    """
    if name is not None:
        widget.setObjectName(name)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


_publish(DEEP_SPACE)


def tint(colour: str, alpha: int) -> str:
    """``colour`` at ``alpha``/255, in the form Qt actually parses.

    Qt reads an eight-digit hex colour as **#AARRGGBB**, not the web's
    #RRGGBBAA. Appending the alpha -- "#E5675E" + "22" -- therefore does not
    give a faint red, it gives an olive (#675E22) at 90% opacity. Every
    translucent colour in the window goes through here so that cannot happen
    again.
    """
    return f"#{alpha:02X}{colour.lstrip('#')}"


def apply_titlebar(window) -> bool:
    """Colour one window's native title bar in the active palette.

    Every window in the app calls exactly this, from its showEvent and again
    from its restyle, so a switch cannot leave one caption in the old
    colours -- which is what makes the title bar part of the theme rather
    than something set once at startup.
    """
    from .windows_theme import apply_titlebar as _apply

    return _apply(
        window.winId(),
        caption=SURFACE,
        text=TEXT,
        border=BORDER,
        dark=IS_DARK,
    )


def stylesheet() -> str:
    """The whole window's sheet, built from whichever palette is active.

    The tokens below are read as module globals rather than off ``active()``
    on purpose: ``_publish`` has already rebound them, and naming them bare
    keeps this sheet readable as a sheet.
    """
    return f"""
    QWidget {{
        background: {BG};
        color: {TEXT};
        font-family: {FONT_STACK};
        font-size: 9.5pt;
    }}

    QScrollArea, QScrollArea > QWidget > QWidget {{
        background: transparent;
        border: none;
    }}

    /* Labels and checkboxes must not paint their own ground, or every one of
       them shows as a slightly-wrong rectangle against the card it sits on. */
    QLabel, QCheckBox, QRadioButton {{
        background: transparent;
    }}

    /* A plain QWidget used purely to hold a layout has the same problem: it
       inherits the window background and shows as a dark band across
       whatever raised surface it was placed on. Anything that is only a
       container is marked Plain and paints nothing. */
    QWidget#Plain {{
        background: transparent;
    }}

    /* Every dialog in the app sits on the window ground rather than the
       platform's. This used to be an inline sheet on each one, which is
       precisely the kind of thing a palette switch cannot reach. */
    QDialog#Sheet {{ background: {BG}; }}

    /* ---- typography ------------------------------------------------ */
    /* Five sizes, and each one is a step in the hierarchy rather than a
       nudge: 17 / 12 / 9.5 / 9 / 8.5. Weight and colour carry as much of
       the ranking as size does, so nothing has to shout. */
    QLabel#Title {{
        font-size: 17pt;
        font-weight: 650;
        color: {TEXT};
        letter-spacing: -0.4px;
    }}
    QLabel#Subtitle {{
        font-size: 9pt;
        color: {TEXT_MUTED};
    }}
    QLabel#StepLabel {{
        font-size: 7.5pt;
        font-weight: 700;
        color: {ACCENT};
        letter-spacing: 1.4px;
    }}
    QLabel#DialogTitle {{
        font-size: 14pt;
        font-weight: 620;
        color: {TEXT};
        letter-spacing: -0.2px;
    }}
    QLabel#SectionHeading {{
        font-size: 12pt;
        font-weight: 600;
        color: {TEXT};
        letter-spacing: -0.1px;
    }}
    QLabel#CardTitle {{
        font-size: 12pt;
        font-weight: 600;
        color: {TEXT};
        letter-spacing: -0.1px;
    }}
    QLabel#RowTitle {{
        font-size: 11pt;
        font-weight: 600;
        color: {TEXT};
    }}
    /* The two big numbers on a target card. Tabular figures so the frame
       count does not jitter sideways as it counts up. */
    QLabel#Figure {{
        font-size: 16pt;
        font-weight: 620;
        color: {TEXT};
        letter-spacing: -0.5px;
    }}
    QLabel#Muted {{ color: {TEXT_MUTED}; }}
    QLabel#Faint {{ color: {TEXT_FAINT}; font-size: 8.5pt; }}
    QLabel#Small {{ font-size: 8.5pt; }}
    QLabel#Body {{ font-size: 9pt; }}
    QLabel#Mono {{ font-family: {MONO_STACK}; font-size: 8.5pt; color: {TEXT_MUTED}; }}
    QLabel#Path {{
        font-family: {MONO_STACK};
        font-size: 8.5pt;
        color: {TEXT_MUTED};
    }}
    QLabel#Detail {{ color: {ACCENT}; font-size: 8.5pt; }}
    QLabel#Running {{ color: {RUNNING}; font-size: 9pt; }}
    QLabel#Caption {{ color: {TEXT_FAINT}; font-size: 8pt; }}
    /* The folded sidebar's one-letter-per-line spine. */
    QLabel#Rail {{ color: {TEXT_FAINT}; font-size: 7.5pt; letter-spacing: 0.5px; }}

    /* A line whose COLOUR is its meaning -- "this is fine", "mind this",
       "this is wrong". Object names rather than inline sheets, so a palette
       switch repaints them along with everything else. */
    QLabel#Ok {{ color: {OK}; }}
    QLabel#Warn {{ color: {WARN}; }}
    QLabel#Error {{ color: {ERROR}; font-weight: 600; }}
    /* The frame grid's caption line, which says how many are picked. Plain
       TEXT once something is, muted while nothing is. */
    QLabel#TileCaption {{ color: {TEXT_FAINT}; font-size: 8pt; }}
    QLabel#TileCaptionWarn {{ color: {WARN}; font-size: 8pt; }}

    /* ---- cards ----------------------------------------------------- */
    /* A card is a surface, not a box. The step up from the window
       background is what separates it; the hairline only stops two cards
       stacked in a column from melting into one another. */
    QFrame#Card {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_MD}px;
    }}
    QFrame#CardSelected {{
        background: {SURFACE_RAISED};
        border: 1px solid {ACCENT_DIM};
        border-radius: {RADIUS_MD}px;
    }}
    QFrame#CardBad {{
        background: {SURFACE};
        border: 1px solid {tint(ERROR, 0x59)};
        border-radius: {RADIUS_MD}px;
    }}
    QFrame#Divider {{
        background: {BORDER};
        border: none;
        max-height: 1px;
        min-height: 1px;
    }}

    /* ---- the mode switcher ------------------------------------------ */
    /* One control, three states, and the current one is unmistakable. A
       beginner who never touches it sees the app exactly as it was. */
    QFrame#ModeBar {{
        background: {BG};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM + 2}px;
    }}
    QPushButton#Mode {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: {RADIUS_SM - 1}px;
        padding: 5px 14px;
        color: {TEXT_MUTED};
        font-size: 9pt;
        font-weight: 600;
    }}
    QPushButton#Mode:hover {{ color: {TEXT}; background: {tint(TEXT, WASH_HARD)}; }}
    QPushButton#Mode:checked {{
        background: {SURFACE_RAISED};
        color: {TEXT};
    }}
    QPushButton#Mode:focus {{ border: 1px solid {ACCENT_DIM}; }}
    /* The dangerous mode is the only one that colours itself, and only once
       you are actually in it. */
    QPushButton#ModeDanger:checked {{
        background: {tint(ERROR, 0x24)};
        color: {ERROR};
    }}

    /* ---- the palette picker ----------------------------------------- */
    /* Quiet on purpose. It shares the header row with the mode switcher,
       which is the control that actually changes what the app does, so this
       one carries no border and no fill until you point at it. */
    QComboBox#ThemePicker {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: {RADIUS_SM}px;
        padding: 5px 9px;
        color: {TEXT_MUTED};
        font-size: 9pt;
    }}
    QComboBox#ThemePicker:hover {{
        color: {TEXT};
        background: {tint(TEXT, WASH_SOFT)};
        border-color: {BORDER};
    }}
    QComboBox#ThemePicker:focus {{ border-color: {ACCENT_DIM}; }}

    /* ---- the right-hand sidebar ------------------------------------- */
    /* Raised rather than sunken: it holds the controls and the button you
       actually press, so it should read as the panel in front, not a gutter
       behind the grid. The change of surface IS the separation -- no rule
       down the seam, the same reasoning as the header and the status bar. */
    QFrame#Sidebar {{
        background: {SURFACE};
        border: none;
    }}
    QFrame#SidebarRail {{
        background: {SURFACE};
        border: none;
    }}
    QLabel#SidebarTitle {{
        font-size: 10pt;
        font-weight: 650;
        color: {TEXT};
        letter-spacing: 0.2px;
    }}
    /* Muted rather than faint: folded away, this chevron is the ONLY way
       back to the output folder, so it has to read as a control. */
    QPushButton#SidebarToggle {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: {RADIUS_XS + 2}px;
        color: {TEXT_MUTED};
        padding: 2px 6px;
        font-size: 12pt;
        font-weight: 600;
    }}
    QPushButton#SidebarToggle:hover {{
        color: {TEXT};
        background: {tint(TEXT, WASH_HARD)};
    }}
    QPushButton#SidebarToggle:pressed {{ background: {tint(TEXT, WASH_HARD + 0x0D)}; }}
    QPushButton#SidebarToggle:focus {{ border: 1px solid {ACCENT_DIM}; }}

    /* ---- surfaces the header and footer sit on ---------------------- */
    QWidget#Chrome {{ background: {SURFACE}; }}

    /* ---- drive tiles ----------------------------------------------- */
    QPushButton#DriveTile {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_LG - 2}px;
        /* No padding here on purpose. The tile's contents are child widgets
           laid out by a QVBoxLayout, and a style sheet's padding does not
           inset those -- it only insets the button's own text, which is
           empty. The real insets are the layout's contents margins in
           cards.py; a value here would just be a comforting lie. */
        text-align: left;
        font-size: 11pt;
        color: {TEXT};
    }}
    QPushButton#DriveTile:hover {{
        background: {SURFACE_HOVER};
        border: 1px solid {BORDER_STRONG};
    }}
    QPushButton#DriveTile:pressed {{ background: {SURFACE_PRESSED}; }}
    /* Chosen: lifted AND outlined. Either alone was readable, but this is
       the one piece of state the whole first step turns on. */
    QPushButton#DriveTile:checked {{
        background: {SURFACE_RAISED};
        border: 1px solid {ACCENT};
    }}
    QPushButton#DriveTile:focus {{ border: 1px solid {ACCENT_DIM}; }}

    /* ---- buttons --------------------------------------------------- */
    /* Every button keeps a 1px border at all times, transparent when it is
       not wanted. A focus ring that appears from nothing would resize the
       button and shove its neighbours along the row. */
    QPushButton {{
        background: {SURFACE_RAISED};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM}px;
        padding: 6px 13px;
        color: {TEXT};
    }}
    QPushButton:hover {{ background: {SURFACE_HOVER}; border-color: {BORDER_STRONG}; }}
    QPushButton:pressed {{ background: {SURFACE_PRESSED}; }}
    QPushButton:focus {{ border: 1px solid {ACCENT_DIM}; }}
    QPushButton:disabled {{
        color: {TEXT_FAINT};
        background: {SURFACE};
        border-color: {BORDER};
    }}

    QPushButton#Primary {{
        background: {ACCENT};
        color: {ACCENT_FG};
        border: 1px solid {ACCENT};
        border-radius: {RADIUS_SM}px;
        padding: 8px 17px;
        font-size: 9.5pt;
        font-weight: 650;
    }}
    QPushButton#Primary:hover {{
        background: {ACCENT_HOVER};
        border-color: {ACCENT_HOVER};
    }}
    QPushButton#Primary:pressed {{
        background: {ACCENT_PRESSED};
        border-color: {ACCENT_PRESSED};
    }}
    /* On a filled button the ring cannot be the border -- it would vanish
       into the fill -- so focus pales the edge instead. TEXT is the right
       colour for that on every palette: on the dark ones it is the lightest
       thing available against a mid accent, and on Daylight it is the
       darkest thing available against a deep one. */
    QPushButton#Primary:focus {{ border-color: {TEXT}; }}
    QPushButton#Primary:disabled {{
        background: {SURFACE_RAISED};
        border-color: {BORDER};
        color: {TEXT_FAINT};
    }}

    /* The one button that destroys something. Filled, so it is never
       mistaken for the row of quiet Ghosts it sits in. */
    QPushButton#Danger {{
        background: {ERROR};
        color: {DANGER_FG};
        border: 1px solid {ERROR};
        border-radius: {RADIUS_SM}px;
        padding: 8px 16px;
        font-weight: 650;
    }}
    QPushButton#Danger:hover {{
        background: {ERROR_HOVER};
        border-color: {ERROR_HOVER};
    }}
    QPushButton#Danger:pressed {{
        background: {ERROR_PRESSED};
        border-color: {ERROR_PRESSED};
    }}
    QPushButton#Danger:focus {{ border-color: {TEXT}; }}
    QPushButton#Danger:disabled {{
        background: {SURFACE_RAISED};
        border-color: {BORDER};
        color: {TEXT_FAINT};
    }}

    QPushButton#Ghost {{
        background: transparent;
        border: 1px solid {BORDER};
        color: {TEXT_MUTED};
        border-radius: {RADIUS_SM}px;
    }}
    QPushButton#Ghost:hover {{
        color: {TEXT};
        background: {tint(TEXT, WASH_SOFT)};
        border-color: {BORDER_STRONG};
    }}
    QPushButton#Ghost:pressed {{ background: {SURFACE_PRESSED}; }}
    QPushButton#Ghost:focus {{ border-color: {ACCENT_DIM}; }}

    QPushButton#Link {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: {RADIUS_XS}px;
        color: {TEXT_MUTED};
        padding: 2px 4px;
        font-size: 8.5pt;
        text-align: left;
    }}
    QPushButton#Link:hover {{ color: {ACCENT}; }}
    QPushButton#Link:pressed {{ color: {ACCENT_PRESSED}; }}
    QPushButton#Link:focus {{ border-color: {ACCENT_DIM}; }}

    /* ---- inputs ---------------------------------------------------- */
    QLineEdit {{
        background: {BG};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM}px;
        padding: 6px 10px;
        color: {TEXT};
        selection-background-color: {ACCENT_DIM};
        selection-color: {TEXT};
    }}
    QLineEdit:hover {{ border-color: {BORDER_STRONG}; }}
    QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
    QLineEdit:read-only {{ color: {TEXT_MUTED}; }}
    QLineEdit#Mono {{ font-family: {MONO_STACK}; font-size: 9pt; }}

    QComboBox {{
        background: {SURFACE_RAISED};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM}px;
        padding: 5px 9px;
        color: {TEXT};
    }}
    QComboBox:hover {{ border-color: {BORDER_STRONG}; }}
    QComboBox:focus {{ border: 1px solid {ACCENT}; }}
    QComboBox QAbstractItemView {{
        background: {SURFACE_RAISED};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM}px;
        selection-background-color: {ACCENT_DIM};
        selection-color: {TEXT};
        color: {TEXT};
        padding: 4px;
    }}

    QCheckBox {{ spacing: 8px; color: {TEXT}; }}
    QCheckBox::indicator {{
        width: 15px; height: 15px;
        border-radius: {RADIUS_XS}px;
        border: 1px solid {BORDER_STRONG};
        background: {BG};
    }}
    QCheckBox::indicator:hover {{ border: 1px solid {ACCENT_DIM}; }}
    QCheckBox::indicator:checked {{
        background: {ACCENT};
        border: 1px solid {ACCENT};
        image: none;
    }}
    QCheckBox::indicator:checked:hover {{
        background: {ACCENT_HOVER};
        border: 1px solid {ACCENT_HOVER};
    }}
    QCheckBox::indicator:disabled {{ border-color: {BORDER}; background: {SURFACE}; }}
    QCheckBox:disabled {{ color: {TEXT_FAINT}; }}

    /* ---- radio buttons and sliders ---------------------------------- */
    /* Both were left to the platform style before, which on Windows draws
       them in the system's own light-mode chrome: a pale grey groove and a
       silver dot, sitting in the middle of a near-black card. */
    QRadioButton {{ spacing: 8px; color: {TEXT}; }}
    QRadioButton::indicator {{
        width: 15px; height: 15px;
        border-radius: 8px;
        border: 1px solid {BORDER_STRONG};
        background: {BG};
    }}
    QRadioButton::indicator:hover {{ border: 1px solid {ACCENT_DIM}; }}
    /* The centre dot is painted as a radial gradient rather than a thick
       border. A 4px border on a 15px box makes Qt give up on border-radius
       and draw a rounded SQUARE, which is exactly what the checked radio
       looked like before: a tick box pretending to be a radio. */
    QRadioButton::indicator:checked {{
        border: 1px solid {ACCENT};
        background: qradialgradient(
            cx: 0.5, cy: 0.5, radius: 0.5, fx: 0.5, fy: 0.5,
            stop: 0 {ACCENT}, stop: 0.5 {ACCENT},
            stop: 0.55 {BG}, stop: 1 {BG}
        );
    }}
    QRadioButton:disabled {{ color: {TEXT_FAINT}; }}

    QSlider::groove:horizontal {{
        height: 4px;
        background: {SURFACE_HOVER};
        border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{
        background: {ACCENT};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {TEXT};
        border: none;
        width: 14px;
        height: 14px;
        margin: -5px 0;
        border-radius: 7px;
    }}
    QSlider::handle:horizontal:hover {{ background: {TEXT_BRIGHT}; }}
    QSlider::handle:horizontal:pressed {{ background: {ACCENT_HOVER}; }}
    QSlider:disabled::sub-page:horizontal {{ background: {BORDER_STRONG}; }}
    QSlider:disabled::handle:horizontal {{ background: {TEXT_FAINT}; }}

    /* ---- monospace boxes ------------------------------------------- */
    /* The run log and the list of files a delete is about to remove are the
       same thing -- a quiet, bordered block of monospace lines -- so they
       are one rule rather than two near-identical inline sheets. */
    QPlainTextEdit#Log {{
        background: {BG};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM}px;
        padding: 10px;
        font-family: {MONO_STACK};
        font-size: 9pt;
        color: {TEXT_MUTED};
        selection-background-color: {ACCENT_DIM};
        selection-color: {TEXT};
    }}
    QPlainTextEdit#Listing {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM}px;
        padding: 9px;
        font-family: {MONO_STACK};
        font-size: 8.5pt;
        color: {TEXT_MUTED};
    }}

    /* ---- trees ------------------------------------------------------ */
    QTreeWidget {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_MD}px;
        outline: none;
    }}
    /* 8px at the sides, not 2. The first column's tick and the last
       column's sentence both ran up against the tree's own border. */
    QTreeWidget::item {{ padding: 6px 8px; border: none; }}
    QTreeWidget::item:hover {{ background: {SURFACE_HOVER}; }}
    QTreeWidget::item:selected {{ background: {tint(ACCENT, 0x2E)}; color: {TEXT}; }}
    QHeaderView::section {{
        background: {SURFACE_RAISED};
        color: {TEXT_FAINT};
        border: none;
        padding: 7px 8px;
        font-size: 8.5pt;
        font-weight: 600;
        letter-spacing: 0.4px;
    }}

    /* ---- thumbnails and frame tiles --------------------------------- */
    /* A picture's own mount, on a card and in the frame grid. These used to
       be inline sheets built once at construction, which is exactly what a
       palette switch cannot repaint -- so they are object names now, and
       SELECTED is a second name rather than a second sheet. */
    QLabel#Thumb {{
        background: {BG};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_XS + 2}px;
        color: {TEXT_FAINT};
        font-size: 8pt;
    }}
    QLabel#ThumbOpenable {{
        background: {BG};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_XS + 2}px;
        color: {TEXT_FAINT};
        font-size: 8pt;
    }}
    QLabel#ThumbOpenable:hover {{ border: 1px solid {ACCENT}; }}
    /* Chosen is a 2px accent edge; merely hovered is a 1px pale one. The
       difference in weight, not just colour, is what keeps a pointer
       passing over a tile from looking like a tile you picked. */
    QLabel#Tile {{
        background: {BG};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_XS + 2}px;
        color: {TEXT_FAINT};
        font-size: 8pt;
    }}
    QLabel#Tile:hover {{ border-color: {BORDER_STRONG}; }}
    QLabel#TileSelected {{
        background: {BG};
        border: 2px solid {ACCENT};
        border-radius: {RADIUS_XS + 2}px;
        color: {TEXT_FAINT};
        font-size: 8pt;
    }}
    QLabel#TileSelected:hover {{ border-color: {ACCENT}; }}

    /* ---- the ground behind a photograph ----------------------------- */
    /* BG_SUNKEN and its own text token. On Daylight this stays dark while
       the rest of the window is light, so it cannot borrow TEXT_MUTED --
       see the token's comment for why the mount is not inverted. */
    QLabel#Sunken {{
        background: {BG_SUNKEN};
        color: {SUNKEN_TEXT};
    }}

    /* ---- progress -------------------------------------------------- */
    /* Slimmer, and drawn in RUNNING rather than the accent: a blue bar on a
       blue-accented window reads as "selected", which a progress bar never
       means. See the RUNNING token for the rest of the reasoning. */
    QProgressBar {{
        background: {SURFACE_RAISED};
        border: none;
        border-radius: 3px;
        max-height: 6px;
        min-height: 6px;
        text-align: center;
        color: transparent;
    }}
    QProgressBar::chunk {{
        background: {RUNNING};
        border-radius: 3px;
    }}

    /* ---- scrollbars ------------------------------------------------ */
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 4px 2px 4px 0;
    }}
    QScrollBar::handle:vertical {{
        background: {BORDER_STRONG};
        border-radius: 5px;
        min-height: 40px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {BORDER_BRIGHT}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 0 4px 2px 4px;
    }}
    QScrollBar::handle:horizontal {{
        background: {BORDER_STRONG};
        border-radius: 5px;
        min-width: 40px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {BORDER_BRIGHT}; }}

    QToolTip {{
        background: {SURFACE_RAISED};
        color: {TEXT};
        border: 1px solid {BORDER_STRONG};
        border-radius: {RADIUS_SM}px;
        padding: 6px 10px;
    }}
    """


def pill(text: str, colour: str) -> str:
    """A small inline status chip, rendered with rich text in a QLabel."""
    return (
        f'<span style="background:{tint(colour, 0x26)}; color:{colour}; '
        f'padding:2px 9px; border-radius:9px; font-size:9pt; '
        f'font-weight:600;">{text}</span>'
    )
