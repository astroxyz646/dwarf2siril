"""Dark theme for the Dwarf2Siril window.

Tuned for the situation the tool is used in: a dark room, at night, often
straight after a session. Two consequences drive the palette.

The background is near-black rather than mid-grey, because a bright panel at
2am is genuinely unpleasant and washes out dark-adapted vision. The accent is
amber rather than the usual blue: long-wavelength light costs the least
dark adaptation, which is also why red torches are standard at a telescope.

Everything is one flat token set so the whole window stays consistent.
"""

from __future__ import annotations

# Surfaces, darkest first.
BG = "#0A0C10"
SURFACE = "#12161F"
SURFACE_RAISED = "#1A202C"
SURFACE_HOVER = "#222A38"
BORDER = "#232B3A"
BORDER_STRONG = "#33405480"

# Text.
TEXT = "#E6EAF2"
TEXT_MUTED = "#8B95A7"
TEXT_FAINT = "#5C6678"

# Accent and status.
ACCENT = "#E8A33D"
ACCENT_DIM = "#B87F2C"
ACCENT_FG = "#1A1204"
OK = "#5CC98E"
WARN = "#E0B341"
ERROR = "#E5675E"

FONT_STACK = '"Segoe UI Variable Text", "Segoe UI", "Inter", system-ui, sans-serif'
MONO_STACK = '"Cascadia Code", "Consolas", "SF Mono", monospace'


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
    QLabel#Title {{
        font-size: 16pt;
        font-weight: 600;
        color: {TEXT};
        letter-spacing: -0.3px;
    }}
    QLabel#Subtitle {{
        font-size: 9pt;
        color: {TEXT_MUTED};
    }}
    QLabel#StepLabel {{
        font-size: 8pt;
        font-weight: 700;
        color: {ACCENT};
        letter-spacing: 1.2px;
    }}
    QLabel#CardTitle {{
        font-size: 12pt;
        font-weight: 600;
        color: {TEXT};
    }}
    QLabel#Muted {{ color: {TEXT_MUTED}; }}
    QLabel#Faint {{ color: {TEXT_FAINT}; font-size: 8.5pt; }}
    QLabel#Mono {{ font-family: {MONO_STACK}; font-size: 8.5pt; color: {TEXT_MUTED}; }}

    /* ---- cards ----------------------------------------------------- */
    QFrame#Card {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 10px;
    }}
    QFrame#CardSelected {{
        background: {SURFACE_RAISED};
        border: 1px solid {ACCENT_DIM};
        border-radius: 10px;
    }}
    QFrame#CardBad {{
        background: {SURFACE};
        border: 1px solid {ERROR}66;
        border-radius: 10px;
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
        border-radius: 8px;
    }}
    QPushButton#Mode {{
        background: transparent;
        border: none;
        border-radius: 6px;
        padding: 5px 14px;
        color: {TEXT_MUTED};
        font-size: 9pt;
        font-weight: 600;
    }}
    QPushButton#Mode:hover {{ color: {TEXT}; }}
    QPushButton#Mode:checked {{
        background: {SURFACE_RAISED};
        color: {TEXT};
    }}
    /* The dangerous mode is the only one that colours itself, and only once
       you are actually in it. */
    QPushButton#ModeDanger:checked {{
        background: {ERROR}22;
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
        border: none;
        color: {TEXT_MUTED};
        padding: 2px 6px;
        font-size: 12pt;
        font-weight: 600;
    }}
    QPushButton#SidebarToggle:hover {{ color: {ACCENT}; }}

    /* ---- drive tiles ----------------------------------------------- */
    QPushButton#DriveTile {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 12px;
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
        border: 1px solid {ACCENT_DIM};
    }}
    QPushButton#DriveTile:checked {{
        background: {SURFACE_RAISED};
        border: 1px solid {ACCENT};
    }}

    /* ---- buttons --------------------------------------------------- */
    QPushButton {{
        background: {SURFACE_RAISED};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 5px 12px;
        color: {TEXT};
    }}
    QPushButton:hover {{ background: {SURFACE_HOVER}; }}
    QPushButton:disabled {{ color: {TEXT_FAINT}; background: {SURFACE}; }}

    QPushButton#Primary {{
        background: {ACCENT};
        color: {ACCENT_FG};
        border: none;
        border-radius: 6px;
        padding: 7px 16px;
        font-size: 9.5pt;
        font-weight: 650;
    }}
    QPushButton#Link {{
        background: transparent;
        border: none;
        color: {TEXT_MUTED};
        padding: 2px 4px;
        font-size: 8.5pt;
        text-align: left;
    }}
    QPushButton#Link:hover {{ color: {ACCENT}; }}
    QPushButton#Primary:hover {{ background: #F2B155; }}
    QPushButton#Primary:disabled {{ background: {SURFACE_RAISED}; color: {TEXT_FAINT}; }}

    QPushButton#Ghost {{
        background: transparent;
        border: 1px solid {BORDER};
        color: {TEXT_MUTED};
    }}
    QPushButton#Ghost:hover {{ color: {TEXT}; border: 1px solid {ACCENT_DIM}; }}

    /* ---- inputs ---------------------------------------------------- */
    QLineEdit {{
        background: {BG};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 5px 9px;
        color: {TEXT};
        selection-background-color: {ACCENT_DIM};
    }}
    QLineEdit:focus {{ border: 1px solid {ACCENT_DIM}; }}
    QLineEdit:read-only {{ color: {TEXT_MUTED}; }}

    QComboBox {{
        background: {SURFACE_RAISED};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 4px 8px;
        color: {TEXT};
    }}
    QComboBox:hover {{ border: 1px solid {ACCENT_DIM}; }}
    QComboBox QAbstractItemView {{
        background: {SURFACE_RAISED};
        border: 1px solid {BORDER};
        selection-background-color: {ACCENT_DIM};
        color: {TEXT};
    }}

    QCheckBox {{ spacing: 7px; color: {TEXT}; }}
    QCheckBox::indicator {{
        width: 15px; height: 15px;
        border-radius: 4px;
        border: 1px solid {BORDER_STRONG};
        background: {BG};
    }}
    QCheckBox::indicator:hover {{ border: 1px solid {ACCENT_DIM}; }}
    QCheckBox::indicator:checked {{
        background: {ACCENT};
        border: 1px solid {ACCENT};
        image: none;
    }}
    QCheckBox:disabled {{ color: {TEXT_FAINT}; }}

    /* ---- progress -------------------------------------------------- */
    QProgressBar {{
        background: {BG};
        border: 1px solid {BORDER};
        border-radius: 7px;
        height: 8px;
        text-align: center;
        color: transparent;
    }}
    QProgressBar::chunk {{
        background: {ACCENT};
        border-radius: 6px;
    }}

    /* ---- scrollbars ------------------------------------------------ */
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 4px 2px 4px 0;
    }}
    QScrollBar::handle:vertical {{
        background: {BORDER};
        border-radius: 5px;
        min-height: 40px;
    }}
    QScrollBar::handle:vertical:hover {{ background: #3A465C; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QToolTip {{
        background: {SURFACE_RAISED};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 6px 9px;
    }}
    """


def pill(text: str, colour: str) -> str:
    """A small inline status chip, rendered with rich text in a QLabel."""
    return (
        f'<span style="background:{colour}22; color:{colour}; '
        f'padding:2px 9px; border-radius:9px; font-size:9pt; '
        f'font-weight:600;">{text}</span>'
    )
