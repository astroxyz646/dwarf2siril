"""Dark theme for the Dwarf2Siril window.

Tuned for the situation the tool is used in: a dark room, at night, often
straight after a session. The background is near-black rather than mid-grey,
because a bright panel at 2am is genuinely unpleasant and washes out
dark-adapted vision.

The accent is a deep, slightly desaturated blue. A pure #0080FF on near-black
glares; this one is pulled down in both lightness and saturation so it reads
as a calm, deliberate highlight rather than a light source. Note that blue is
the WORST colour for dark adaptation -- short-wavelength light costs the most
of it, which is why red torches are standard at a telescope -- so this is a
considered aesthetic choice, not a physiological one. Anyone at the eyepiece
should be dimming their screen anyway.

Everything is one flat token set so the whole window stays consistent. Nothing
outside this module should name a colour: if a widget needs one, it either
takes an object name that is styled here, or it imports a token.

Three scales carry the rhythm, and every margin, gap and corner in the window
is one of their values:

* ``SPACE_*``   -- 4px steps, for layout margins and spacing.
* ``RADIUS_*``  -- corner radii, small for controls, larger for surfaces.
* the surfaces  -- BG through SURFACE_HOVER, which do the work borders used
  to. Elevation separates panels; a hairline is only added where two
  same-coloured surfaces meet.
"""

from __future__ import annotations

# ---- surfaces, darkest first --------------------------------------------
# BG_SUNKEN is only for the ground behind a photograph, where anything
# lighter would sit in the picture's tonal range and compete with it.
BG_SUNKEN = "#05070A"
BG = "#0A0C10"
SURFACE = "#141924"
SURFACE_RAISED = "#1C2231"
SURFACE_HOVER = "#242C3E"
SURFACE_PRESSED = "#161B27"

# Borders are deliberately quiet. Most separation in this window comes from
# the surface steps above; a line is a last resort, not the default.
BORDER = "#1F2634"
BORDER_STRONG = "#2E3849"
BORDER_BRIGHT = "#3F4B60"

# ---- text ----------------------------------------------------------------
TEXT_BRIGHT = "#FFFFFF"
TEXT = "#E8ECF4"
TEXT_MUTED = "#8E99AC"
TEXT_FAINT = "#5E6879"

# ---- accent --------------------------------------------------------------
ACCENT = "#4C8FD9"
ACCENT_HOVER = "#6BA6E8"
ACCENT_PRESSED = "#3B79BE"
ACCENT_DIM = "#2E567F"
ACCENT_FG = "#04101C"

# The keyboard focus ring. A SEPARATE token from the accent because it is
# doing a different job: the accent marks what is selected, focus marks
# where the keyboard is, and the two are on screen at the same time. It was
# ACCENT_DIM, which on a near-black surface is a 1px line at about the same
# lightness as the border it replaces -- tabbing through the window moved
# something you could not see. Brighter than the accent, so a focused
# primary button and an unfocused one are different at a glance, and light
# enough to clear WCAG's 3:1 for a non-text indicator against every surface
# in this file.
#
# It stays ONE PIXEL. Every control here keeps a 1px border at all times so
# that gaining focus recolours it rather than resizing the control and
# shoving its neighbours along the row; a 2px ring would undo that.
FOCUS = "#8FC2F5"

# ---- status --------------------------------------------------------------
# Each of these has to survive being seen next to the accent, so all three
# sit well away from it in hue. RUNNING is the odd one out and the reason it
# exists: work in progress used to be drawn in the accent, which on a blue
# theme is indistinguishable from "this one is selected". A cyan-teal reads
# as motion instead, at a glance, without joining the warn/error vocabulary.
OK = "#4FC98C"
WARN = "#E3A93F"
ERROR = "#E5675E"
ERROR_HOVER = "#EE7C73"
ERROR_PRESSED = "#CF574F"
RUNNING = "#38BEC9"

# Text drawn on top of a filled ERROR button. Near-black rather than white:
# white on this red is the weaker pairing, and a destructive button should
# not also be the hardest thing to read.
DANGER_FG = "#1A0806"

# ---- spacing and radii ---------------------------------------------------
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


def tint(colour: str, alpha: int) -> str:
    """``colour`` at ``alpha``/255, in the form Qt actually parses.

    Qt reads an eight-digit hex colour as **#AARRGGBB**, not the web's
    #RRGGBBAA. Appending the alpha -- "#E5675E" + "22" -- therefore does not
    give a faint red, it gives an olive (#675E22) at 90% opacity. Every
    translucent colour in the window goes through here so that cannot happen
    again.
    """
    return f"#{alpha:02X}{colour.lstrip('#')}"


def stylesheet() -> str:
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
    QPushButton#Mode:hover {{ color: {TEXT}; background: {tint(TEXT, 0x0D)}; }}
    QPushButton#Mode:checked {{
        background: {SURFACE_RAISED};
        color: {TEXT};
    }}
    QPushButton#Mode:focus {{ border: 1px solid {FOCUS}; }}
    /* The dangerous mode is the only one that colours itself, and only once
       you are actually in it. */
    QPushButton#ModeDanger:checked {{
        background: {tint(ERROR, 0x24)};
        color: {ERROR};
    }}

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
        background: {tint(TEXT, 0x0D)};
    }}
    QPushButton#SidebarToggle:pressed {{ background: {tint(TEXT, 0x1A)}; }}
    QPushButton#SidebarToggle:focus {{ border: 1px solid {FOCUS}; }}

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
    QPushButton#DriveTile:focus {{ border: 1px solid {FOCUS}; }}

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
    QPushButton:focus {{ border: 1px solid {FOCUS}; }}
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
       into the fill -- so focus lightens the fill and pales the edge. */
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
        background: {tint(TEXT, 0x0A)};
        border-color: {BORDER_STRONG};
    }}
    QPushButton#Ghost:pressed {{ background: {SURFACE_PRESSED}; }}
    QPushButton#Ghost:focus {{ border-color: {FOCUS}; }}

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
    QPushButton#Link:focus {{ border-color: {FOCUS}; }}

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
    /* Keyboard focus on a tick box has to be visible on the BOX, not on the
       word beside it -- the box is the control. Written AFTER the checked
       rules on purpose: Qt resolves equal specificity by source order, so a
       focus border placed above ::indicator:checked is simply overwritten
       by it, and tabbing onto a ticked box shows nothing at all. */
    QCheckBox::indicator:focus {{ border: 1px solid {FOCUS}; }}
    QCheckBox::indicator:checked:focus {{ border: 1px solid {FOCUS}; }}

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
    QRadioButton::indicator:focus {{ border: 1px solid {FOCUS}; }}
    QRadioButton::indicator:checked:focus {{ border: 1px solid {FOCUS}; }}
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

    /* ---- message boxes ---------------------------------------------- */
    /* Every warning and every question in this app is a QMessageBox, and
       none of them were styled -- so its headline, which Qt puts in a label
       of its own, was drawn at exactly the same size and weight as the
       paragraph under it. A box whose first line is meant to be read first
       has to look like it. Named sub-widgets rather than a blanket QLabel
       rule, so the informative text keeps the body size. */
    QMessageBox {{ background: {BG}; }}
    QMessageBox QLabel#qt_msgbox_label {{
        font-size: 11.5pt;
        font-weight: 620;
        color: {TEXT};
    }}
    QMessageBox QLabel#qt_msgbox_informativelabel {{
        color: {TEXT_MUTED};
    }}
    /* Wide enough not to read as a pair of afterthoughts under a paragraph
       that long. */
    QMessageBox QPushButton {{ min-width: 96px; }}
    """


def pill(text: str, colour: str) -> str:
    """A small inline status chip, rendered with rich text in a QLabel."""
    return (
        f'<span style="background:{tint(colour, 0x26)}; color:{colour}; '
        f'padding:2px 9px; border-radius:9px; font-size:9pt; '
        f'font-weight:600;">{text}</span>'
    )
