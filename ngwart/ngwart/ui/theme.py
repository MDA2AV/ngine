"""Visual language for the operator station.

A shop floor drives most of the choices. The surface is dark so a lit indicator
reads instantly; the two things an operator looks at from a metre away -- the
status banner and each unit's verdict -- are the largest things on screen; and
results are never distinguished by colour alone, because roughly 8% of men have
a red/green colour vision deficiency. PASS and FAIL differ in lightness, in
weight, and carry a word.

Everything derives from the tokens below. That is what keeps a dense instrument
UI from drifting into a collection of one-off paddings: a panel, a table header
and a menu all take their radius, spacing and type from the same scale, so they
still look related after a year of edits.

Nothing is positioned in absolute pixels, so the window is correct on a
1366x768 panel PC and on a 4K monitor. v1 drew onto a hardcoded 1920x1080
canvas and placed every control at a fixed fraction of it.
"""

from __future__ import annotations

# --- tokens -------------------------------------------------------------

#: One spacing scale. A value between these is a smell, not a nuance.
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24}

#: Two radii -- controls, and the panels that hold them -- plus pills.
RADIUS = {"control": 6, "panel": 10, "pill": 5}

#: Type scale in points. Each step is a role, not a size to pick from.
TYPE = {
    "display": 21,   # status banner
    "title": 13,     # panel titles, unit numbers
    "body": 10.5,    # menus, buttons, prose
    "data": 10,      # tables, log
    "figure": 15,    # header statistics
    "caption": 8,    # uppercase tracked labels
}

MONO = "Cascadia Mono, Consolas, DejaVu Sans Mono, monospace"
SANS = "Segoe UI, Inter, DejaVu Sans, sans-serif"


# --- palette ------------------------------------------------------------
#
# Neutrals carry a slight cool bias toward the accent rather than being pure
# grey, so the two read as one family. Semantic colours are deliberately not
# the accent: a verdict must never look like branding.

DARK = {
    "bg": "#0E1215",
    "surface": "#151A1E",
    "elevated": "#1C2328",
    "overlay": "#232B31",
    "border": "#283238",
    "border_strong": "#36434B",
    "text": "#E7ECEF",
    "muted": "#A0ADB5",
    "faint": "#6C7A82",
    "accent": "#3E9BD5",
    "accent_soft": "#16303F",
    "pass": "#3BB878",
    "fail": "#E8545B",
    "warn": "#DFA13C",
    "info": "#3E9BD5",
    "idle": "#333E45",
    # Verdict tints for a whole unit panel. Deliberately near the neutral
    # surface they replace -- the panel should read as "this one passed" at a
    # glance without turning the results inside it into low-contrast text.
    # Selected row in the program table. Lifted off the surface enough to find
    # at a glance, far short of the filled block that made a table look like two
    # different panels.
    "select": "#1B2833",
    "pass_surface": "#122320",
    "pass_elevated": "#162B26",
    "pass_border": "#2B5645",
    "fail_surface": "#231619",
    "fail_elevated": "#2B1B1F",
    "fail_border": "#653036",
}

LIGHT = {
    "bg": "#F1F4F6",
    "surface": "#FFFFFF",
    "elevated": "#EDF1F4",
    "overlay": "#E2E8ED",
    "border": "#D5DDE3",
    "border_strong": "#B9C4CC",
    "text": "#11171B",
    "muted": "#54626C",
    "faint": "#7C8A93",
    "accent": "#0F6FA8",
    "accent_soft": "#DCEDF7",
    "pass": "#1B7A4B",
    "fail": "#C0353B",
    "warn": "#8F6212",
    "info": "#0F6FA8",
    "idle": "#C6CFD6",
    "select": "#E4EEF6",
    "pass_surface": "#F2FAF5",
    "pass_elevated": "#E4F2E9",
    "pass_border": "#A9D4BD",
    "fail_surface": "#FEF4F4",
    "fail_elevated": "#FAE8E9",
    "fail_border": "#E9B5B8",
}

#: Result tag -> palette key. A table's own Tag_Config colours win over these.
RESULT_COLOURS = {
    "PASS": "pass",
    "FAIL": "fail",
    "RETRY": "warn",
    "IRR": "info",
    "SKIP": "faint",
}

LOG_COLOURS = {
    "info": "text",
    "warn": "warn",
    "error": "fail",
    "pass": "pass",
    "fail": "fail",
}


def palette(dark: bool = True) -> dict:
    return dict(DARK if dark else LIGHT)


def stylesheet(dark: bool = True) -> str:
    c = palette(dark)
    s, r, t = SPACE, RADIUS, TYPE
    return f"""
QWidget {{
    background: {c['bg']};
    color: {c['text']};
    font-family: {SANS};
    font-size: {t['body']}pt;
}}
/* Text and controls never paint their own background.

   The rule above gives every QWidget the *window* colour, which is darker than
   the surface a panel sits on. Any label inside a panel therefore drew a darker
   rectangle behind itself -- visible as a box around the progress percentage,
   the step caption and the header figures. Whatever is behind them should show
   through; only the handful of things that are deliberately a chip or a pill
   set a background, and those do it with an ID rule that wins over this one. */
QLabel, QCheckBox, QRadioButton {{ background: transparent; }}

/* A widget that exists only to hold a layout is not a surface. Without this it
   paints the window colour inside whatever panel it sits in -- the same dark
   rectangle, one level up from the labels. */
QWidget#Bare {{ background: transparent; }}

QMainWindow::separator {{ background: {c['border']}; width: 1px; height: 1px; }}
QToolTip {{
    background: {c['overlay']}; color: {c['text']};
    border: 1px solid {c['border_strong']};
    padding: {s['sm']}px {s['md']}px; border-radius: {r['control']}px;
}}

/* --- panels --- */
QFrame#Card {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: {r['panel']}px;
}}
QLabel#CardTitle {{
    color: {c['faint']};
    font-size: {t['caption']}pt;
    font-weight: 700;
    letter-spacing: 1.4px;
    padding: 0 0 {s['xs']}px 2px;
    background: transparent;
}}

/* --- status banner ---
   Slim. Reading it from a metre away is a function of type size and contrast,
   not of how much height the widget occupies. */
QLabel#StatusBanner {{
    font-size: {t['display']}pt;
    font-weight: 700;
    letter-spacing: 1.5px;
    padding: {s['sm']}px {s['lg']}px;
    border-radius: {r['panel']}px;
    background: {c['elevated']};
    color: {c['text']};
}}

/* --- verdicts and unit headers --- */
QLabel#Verdict {{
    font-size: {t['body']}pt;
    font-weight: 800;
    letter-spacing: 0.8px;
    border-radius: {r['pill']}px;
    padding: {s['xs']}px {s['md']}px;
    background: {c['idle']};
    color: {c['text']};
}}
QLabel#UnitNumber {{
    font-family: {MONO};
    font-size: {t['title']}pt;
    font-weight: 700;
    color: {c['text']};
    background: {c['elevated']};
    border: 1px solid {c['border']};
    border-radius: {r['pill']}px;
    padding: 1px {s['sm']}px;
}}
QLabel#UnitCount {{
    font-family: {MONO};
    font-size: {t['caption']}pt;
    letter-spacing: 0.6px;
    color: {c['faint']};
    background: transparent;
}}

/* --- tables --- */
QTableWidget, QTableView {{
    background: {c['surface']};
    alternate-background-color: {c['elevated']};
    gridline-color: transparent;
    border: none;
    font-family: {MONO};
    font-size: {t['data']}pt;
    selection-background-color: transparent;
    selection-color: {c['accent']};
}}
QTableView::item {{ padding: {s['xs']}px {s['sm']}px; border: none; }}
/* The running step, and a row the operator clicks, are marked by their ink
   rather than by a filled block. A tinted rectangle behind one row of a table
   reads as a different surface and breaks the panel it sits in; recolouring
   the text says the same thing without introducing a second background. */
QTableView::item:selected {{
    background: transparent;
    color: {c['accent']};
    font-weight: 700;
}}
/* The program table is the exception: its selection is not just a highlight,
   it is what "run these steps" acts on, so it has to be unmistakable. A tint
   this close to the surface reads as one panel; the accent ink still carries
   it for anyone who cannot see the tint. */
QTableView#ProgramTable::item:selected {{
    background: {c['select']};
    color: {c['accent']};
    font-weight: 700;
}}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: {c['surface']};
    color: {c['faint']};
    border: none;
    border-bottom: 1px solid {c['border']};
    padding: {s['sm']}px;
    font-family: {SANS};
    font-weight: 700;
    font-size: {t['caption']}pt;
    letter-spacing: 1.1px;
}}
QTableCornerButton::section {{ background: {c['surface']}; border: none; }}

/* --- log --- */
QPlainTextEdit#Log {{
    background: {c['surface']};
    border: none;
    font-family: {MONO};
    font-size: {t['data']}pt;
    color: {c['text']};
    selection-background-color: {c['accent_soft']};
}}

/* --- inputs --- */
QLineEdit, QComboBox {{
    background: {c['elevated']};
    border: 1px solid {c['border']};
    border-radius: {r['control']}px;
    padding: {s['sm']}px {s['md']}px;
    font-family: {MONO};
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {c['overlay']};
    border: 1px solid {c['border_strong']};
    selection-background-color: {c['accent']};
}}

/* --- buttons --- */
QPushButton {{
    background: {c['elevated']};
    border: 1px solid {c['border']};
    border-radius: {r['control']}px;
    padding: {s['sm']}px {s['lg']}px;
    font-weight: 600;
}}
QPushButton:hover {{ background: {c['overlay']}; border-color: {c['border_strong']}; }}
QPushButton:pressed {{ background: {c['elevated']}; }}
QPushButton:focus {{ border-color: {c['accent']}; }}
QPushButton:disabled {{ color: {c['faint']}; background: {c['surface']}; }}
QPushButton#Run {{
    background: {c['pass']}; color: #FFFFFF; border: 1px solid transparent;
    font-size: {t['title']}pt; font-weight: 700; letter-spacing: 0.8px;
    padding: {s['md']}px {s['xl']}px;
}}
QPushButton#Run:disabled {{ background: {c['idle']}; color: {c['faint']}; }}
QPushButton#Stop {{
    background: {c['fail']}; color: #FFFFFF; border: 1px solid transparent;
    font-size: {t['title']}pt; font-weight: 700; letter-spacing: 0.8px;
    padding: {s['md']}px {s['xl']}px;
}}
QPushButton#Stop:disabled {{ background: {c['idle']}; color: {c['faint']}; }}

/* --- progress --- */
QProgressBar {{
    background: {c['elevated']};
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 4px; }}

/* --- tabs --- */
QTabWidget::pane {{ border: none; background: transparent; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent;
    color: {c['faint']};
    padding: {s['sm']}px {s['lg']}px;
    margin-right: 2px;
    border-bottom: 2px solid transparent;
    font-weight: 600;
    font-size: {t['body']}pt;
}}
QTabBar::tab:hover {{ color: {c['muted']}; }}
QTabBar::tab:selected {{ color: {c['text']}; border-bottom-color: {c['accent']}; }}

/* --- menu bar --- */
QMenuBar {{
    background: {c['surface']};
    border-bottom: 1px solid {c['border']};
    padding: 2px {s['sm']}px;
    font-size: {t['body']}pt;
}}
QMenuBar::item {{
    background: transparent;
    padding: {s['xs']}px {s['md']}px;
    border-radius: {r['pill']}px;
    color: {c['text']};
}}
QMenuBar::item:selected {{ background: {c['elevated']}; }}
QMenuBar::item:pressed {{ background: {c['accent']}; color: #FFFFFF; }}
QMenu {{
    background: {c['overlay']};
    border: 1px solid {c['border_strong']};
    border-radius: {r['control']}px;
    padding: {s['xs']}px;
}}
QMenu::item {{
    padding: {s['sm']}px {s['xl']}px {s['sm']}px 28px;
    border-radius: {r['pill']}px;
    color: {c['text']};
}}
QMenu::item:selected {{ background: {c['accent']}; color: #FFFFFF; }}
QMenu::item:disabled {{ color: {c['faint']}; }}
QMenu::separator {{
    height: 1px; background: {c['border']}; margin: {s['xs']}px {s['sm']}px;
}}
QMenu::indicator {{ width: 15px; height: 15px; left: 7px; }}

/* --- identity strip --- */
QFrame#Identity {{
    background: {c['surface']};
    border: none;
    border-bottom: 1px solid {c['border']};
}}
/* Children inherit the window background otherwise, which paints a darker
   rectangle behind every group and makes the strip look like a row of boxes. */
/* The layout holder is a bare QWidget, so it needs this even though labels are
   handled globally above -- otherwise it paints the window colour behind the
   whole identity group. */
QFrame#Identity > QWidget {{ background: transparent; }}
QLabel#ProgramName {{
    font-size: {t['title']}pt; font-weight: 700; letter-spacing: -0.2px;
    color: {c['text']};
}}
QLabel#ProgramMeta {{
    font-size: {t['caption']}pt; color: {c['faint']}; letter-spacing: 0.3px;
}}
QLabel#StatCaption {{
    font-size: {t['caption']}pt; font-weight: 700; letter-spacing: 1.4px;
    color: {c['faint']};
}}
QLabel#StatValue {{
    font-family: {MONO}; font-size: {t['figure']}pt; font-weight: 600;
    color: {c['text']};
}}
QLabel#Badge {{
    font-size: {t['caption']}pt; font-weight: 800; letter-spacing: 1.2px;
    border-radius: {r['pill']}px; padding: 3px {s['sm']}px;
}}
QLabel#Placeholder {{
    color: {c['faint']}; font-size: {t['body']}pt; background: transparent;
}}

/* --- scrollbars --- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {c['border_strong']}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {c['faint']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: {c['border_strong']}; border-radius: 5px; min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {c['faint']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* --- splitter --- */
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: {s['sm']}px; }}
QSplitter::handle:vertical {{ height: {s['sm']}px; }}

/* --- status bar --- */
QStatusBar {{
    background: {c['surface']};
    border-top: 1px solid {c['border']};
    color: {c['faint']};
    font-size: {t['caption']}pt;
    letter-spacing: 0.4px;
}}
QStatusBar::item {{ border: none; }}
"""
