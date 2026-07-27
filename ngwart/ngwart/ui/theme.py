"""Visual language for the operator station.

Designed for a shop floor, which drives most of the choices: a dark surface so
a bright indicator reads instantly, large type for the two things an operator
looks at from a metre away (the status banner and the per-UUT verdict), and
result colours that stay distinguishable for the ~8% of men with a red/green
colour vision deficiency -- PASS and FAIL differ in lightness and carry a text
label, never colour alone.

Everything is a stylesheet plus relative sizing; no widget is positioned in
absolute pixels, so the window is correct on a 1366x768 panel PC and on a 4K
monitor. v1 drew onto a hardcoded 1920x1080 canvas and placed every control at
a fixed fraction of it.
"""

from __future__ import annotations

# --- palette ------------------------------------------------------------

DARK = {
    "bg": "#101317",
    "surface": "#171B21",
    "elevated": "#1E232A",
    "border": "#2A313A",
    "text": "#E6E9ED",
    "muted": "#98A2AE",
    "accent": "#4C9AFF",
    "pass": "#35B26B",
    "fail": "#E5484D",
    "warn": "#E0A22B",
    "info": "#4C9AFF",
    "idle": "#3A424C",
}

LIGHT = {
    "bg": "#F4F6F8",
    "surface": "#FFFFFF",
    "elevated": "#EDF0F3",
    "border": "#D3D9E0",
    "text": "#12161B",
    "muted": "#5A6572",
    "accent": "#0B6BCB",
    "pass": "#1F7A44",
    "fail": "#C22B30",
    "warn": "#96650F",
    "info": "#0B6BCB",
    "idle": "#C2C9D1",
}

#: Result tag -> palette key. Tables also set explicit hex colours via
#: Tag_Config; those win.
RESULT_COLOURS = {
    "PASS": "pass",
    "FAIL": "fail",
    "RETRY": "warn",
    "IRR": "info",
    "SKIP": "muted",
}

LOG_COLOURS = {
    "info": "text",
    "warn": "warn",
    "error": "fail",
    "pass": "pass",
    "fail": "fail",
}

MONO = "Cascadia Mono, Consolas, DejaVu Sans Mono, monospace"
SANS = "Segoe UI, Inter, DejaVu Sans, sans-serif"


def palette(dark: bool = True) -> dict:
    return dict(DARK if dark else LIGHT)


def stylesheet(dark: bool = True) -> str:
    c = palette(dark)
    return f"""
QWidget {{
    background: {c['bg']};
    color: {c['text']};
    font-family: {SANS};
    font-size: 11pt;
}}
QMainWindow::separator {{ background: {c['border']}; width: 1px; height: 1px; }}

/* --- panels --- */
QFrame#Card {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 10px;
}}
QLabel#CardTitle {{
    color: {c['muted']};
    font-size: 9.5pt;
    font-weight: 600;
    letter-spacing: 1.2px;
    padding: 2px 2px 6px 2px;
}}

/* --- status banner ---
   Slimmer than it was. It still has to read from a metre away, which is a
   function of type size and contrast, not of how much height it occupies. */
QLabel#StatusBanner {{
    font-size: 21pt;
    font-weight: 700;
    letter-spacing: 1.5px;
    padding: 7px 18px;
    border-radius: 8px;
    background: {c['elevated']};
    color: {c['text']};
}}

/* --- verdict chips --- */
QLabel#Verdict {{
    font-size: 13pt;
    font-weight: 700;
    border-radius: 6px;
    padding: 4px 12px;
    background: {c['idle']};
    color: {c['text']};
}}

/* --- tables --- */
QTableWidget, QTableView {{
    background: {c['surface']};
    alternate-background-color: {c['elevated']};
    gridline-color: {c['border']};
    border: none;
    font-family: {MONO};
    font-size: 10pt;
    selection-background-color: {c['accent']};
    selection-color: #FFFFFF;
}}
QHeaderView::section {{
    background: {c['elevated']};
    color: {c['muted']};
    border: none;
    border-bottom: 1px solid {c['border']};
    padding: 6px 8px;
    font-weight: 600;
    font-size: 9.5pt;
}}
QTableCornerButton::section {{ background: {c['elevated']}; border: none; }}

/* --- log --- */
QPlainTextEdit#Log {{
    background: {c['surface']};
    border: none;
    font-family: {MONO};
    font-size: 10pt;
    color: {c['text']};
}}

/* --- inputs --- */
QLineEdit, QComboBox {{
    background: {c['elevated']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 6px 10px;
    font-family: {MONO};
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {c['elevated']};
    border: 1px solid {c['border']};
    selection-background-color: {c['accent']};
}}

/* --- buttons --- */
QPushButton {{
    background: {c['elevated']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    padding: 9px 18px;
    font-weight: 600;
}}
QPushButton:hover {{ border-color: {c['accent']}; }}
QPushButton:disabled {{ color: {c['muted']}; border-color: {c['border']}; }}
QPushButton#Run {{
    background: {c['pass']}; color: #FFFFFF; border: none;
    font-size: 13pt; padding: 12px 34px;
}}
QPushButton#Run:disabled {{ background: {c['idle']}; color: {c['muted']}; }}
QPushButton#Stop {{
    background: {c['fail']}; color: #FFFFFF; border: none;
    font-size: 13pt; padding: 12px 34px;
}}
QPushButton#Stop:disabled {{ background: {c['idle']}; color: {c['muted']}; }}

/* --- progress --- */
QProgressBar {{
    background: {c['elevated']};
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 5px; }}

/* --- tabs --- */
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent;
    color: {c['muted']};
    padding: 9px 20px;
    border-bottom: 2px solid transparent;
    font-weight: 600;
}}
QTabBar::tab:selected {{ color: {c['text']}; border-bottom-color: {c['accent']}; }}

/* --- menu bar --- */
QMenuBar {{
    background: {c['surface']};
    border-bottom: 1px solid {c['border']};
    padding: 2px 6px;
    font-size: 10.5pt;
}}
QMenuBar::item {{
    background: transparent;
    padding: 6px 12px;
    border-radius: 5px;
    color: {c['text']};
}}
QMenuBar::item:selected {{ background: {c['elevated']}; }}
QMenuBar::item:pressed {{ background: {c['accent']}; color: #FFFFFF; }}
QMenu {{
    background: {c['elevated']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 26px 7px 30px;
    border-radius: 5px;
    color: {c['text']};
}}
QMenu::item:selected {{ background: {c['accent']}; color: #FFFFFF; }}
QMenu::item:disabled {{ color: {c['muted']}; }}
QMenu::separator {{
    height: 1px; background: {c['border']}; margin: 5px 10px;
}}
QMenu::indicator {{ width: 16px; height: 16px; left: 8px; }}

/* --- identity strip --- */
QFrame#Identity {{
    background: {c['surface']};
    border: none;
    border-bottom: 1px solid {c['border']};
}}
/* Children inherit the window background otherwise, which paints a darker
   rectangle behind every group and makes the strip look like a row of boxes. */
QFrame#Identity > QWidget {{ background: transparent; }}
QFrame#Identity QLabel {{ background: transparent; }}
QLabel#ProgramName {{
    font-size: 17pt; font-weight: 700; letter-spacing: -0.3px;
    color: {c['text']};
}}
QLabel#ProgramMeta {{
    font-size: 9.5pt; color: {c['muted']};
}}
QLabel#StatCaption {{
    font-size: 8pt; font-weight: 700; letter-spacing: 1.4px;
    color: {c['muted']};
}}
QLabel#StatValue {{
    font-family: {MONO}; font-size: 16pt; font-weight: 600;
    color: {c['text']};
}}
QLabel#ScanCaption {{
    font-size: 8pt; font-weight: 700; letter-spacing: 1.4px;
    color: {c['muted']};
}}
QLabel#ScanValue {{
    font-family: {MONO}; font-size: 13pt;
    color: {c['text']};
    background: {c['elevated']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 7px 12px;
}}
QLabel#Badge {{
    font-size: 8.5pt; font-weight: 800; letter-spacing: 1.2px;
    border-radius: 4px; padding: 4px 9px;
}}

/* --- misc --- */
QSplitter::handle {{ background: {c['border']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {c['border']}; border-radius: 5px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{
    background: {c['border']}; border-radius: 5px; min-width: 28px;
}}
QToolTip {{
    background: {c['elevated']}; color: {c['text']};
    border: 1px solid {c['border']}; padding: 6px;
}}
QStatusBar {{ background: {c['surface']}; color: {c['muted']}; }}
QStatusBar::item {{ border: none; }}
"""
