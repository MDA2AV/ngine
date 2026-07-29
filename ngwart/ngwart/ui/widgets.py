"""Reusable widgets for the operator station."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QLabel,
                               QHeaderView, QPlainTextEdit, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from . import theme


def _looks_numeric(text: str) -> bool:
    try:
        float(text)
        return True
    except (TypeError, ValueError):
        return False

#: Cap the log so a long production shift cannot grow it without bound. v1's
#: Tk text widget accumulated every line until the process was restarted.
MAX_LOG_LINES = 4000


class Card(QFrame):
    """A titled panel."""

    def __init__(self, title: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 10, 12, 12)
        self._layout.setSpacing(6)
        if title:
            label = QLabel(title.upper())
            label.setObjectName("CardTitle")
            self._layout.addWidget(label)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self._layout.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)


class StatusBanner(QLabel):
    """The one thing an operator reads from across the bench."""

    def __init__(self, parent=None) -> None:
        super().__init__("READY", parent)
        self.setObjectName("StatusBanner")
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(False)
        self.setMinimumHeight(46)
        self._palette = theme.palette(True)
        # Remembered so a theme change can repaint without being told the
        # colour again -- otherwise toggling the theme mid-run silently drops a
        # PASS or FAIL back to neutral grey.
        self._colour: str | None = None

    def set_palette_colours(self, colours: dict) -> None:
        self._palette = colours

    def repaint_status(self) -> None:
        """Re-apply the current state under a new palette."""
        self.show_status(self.text(), self._colour)

    def show_status(self, text: str, colour: str | None = None) -> None:
        self.setText(text or "")
        self._colour = colour
        background = colour or self._palette["elevated"]
        foreground = _readable_on(background)
        self.setStyleSheet(
            f"background: {background}; color: {foreground};"
            f"border-radius: 8px; padding: 7px 18px;"
            f"font-size: 21pt; font-weight: 700; letter-spacing: 1.5px;"
        )


class VerdictChip(QLabel):
    """Per-UUT PASS/FAIL badge.

    Carries a word as well as a colour, so it is unambiguous to an operator with
    a red/green colour vision deficiency.
    """

    def __init__(self, parent=None) -> None:
        super().__init__("--", parent)
        self.setObjectName("Verdict")
        self.setAlignment(Qt.AlignCenter)
        self._palette = theme.palette(True)

    def set_state(self, state: str) -> None:
        colours = {
            "PASS": self._palette["pass"],
            "FAIL": self._palette["fail"],
            "DEAD": self._palette["fail"],
            "RUN": self._palette["accent"],
        }
        background = colours.get(state, self._palette["idle"])
        self.setText(state)
        self.setStyleSheet(
            f"background: {background}; color: {_readable_on(background)};"
            f"border-radius: 6px; padding: 4px 12px; font-weight: 700;"
        )


class UutGrid(Card):
    """One unit under test: its verdict and its measured points."""

    def __init__(self, index: int, parent=None) -> None:
        super().__init__("", parent)
        self.index = index
        self._palette = theme.palette(True)
        self._tag_colours: dict[str, str] = {}
        self._columns: list[str] = ["Test", "Device", "Min", "Max", "Value", "Result"]

        self.passed = 0
        self.failed = 0
        self.dead = False
        #: None, "pass" or "fail" -- drives the whole-panel tint.
        self._tone: str | None = None

        header = QHBoxLayout()
        header.setSpacing(theme.SPACE["sm"])
        self.number = QLabel(f"{index + 1:02d}")
        self.number.setObjectName("UnitNumber")
        self.title = QLabel("UNIT")
        self.title.setObjectName("CardTitle")
        self.count = QLabel("")
        self.count.setObjectName("UnitCount")
        self.verdict = VerdictChip()

        header.addWidget(self.number)
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.count)
        header.addWidget(self.verdict)
        self.add_layout(header)

        self.table = QTableWidget(0, len(self._columns))
        self.table.setHorizontalHeaderLabels(self._columns)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.verticalHeader().setDefaultSectionSize(24)
        head = self.table.horizontalHeader()
        head.setStretchLastSection(True)
        head.setSectionResizeMode(0, QHeaderView.Stretch)
        head.setHighlightSections(False)
        self.add(self.table, 1)

    # -- engine operations ------------------------------------------------

    def apply(self, op: str, values: list[str], tag: str, config: dict) -> None:
        if op == "add":
            self._add(values, tag)
        elif op == "clear":
            self.table.setRowCount(0)
            self.passed = self.failed = 0
            self.dead = False
            self._update_count()
            self.verdict.set_state("--")
            self.set_tone(None)
        elif op == "config":
            self._configure(config)

    def _configure(self, config: dict) -> None:
        if "columns" in config:
            self._columns = list(config["columns"])
            self.table.setColumnCount(len(self._columns))
            self.table.setHorizontalHeaderLabels(self._columns)
        if "heading" in config and config["heading"] in self._columns:
            i = self._columns.index(config["heading"])
            self.table.setHorizontalHeaderItem(i, QTableWidgetItem(config["text"]))
        if "column" in config and config["column"] in self._columns:
            i = self._columns.index(config["column"])
            self.table.setColumnWidth(i, int(config.get("width", 100)))
        if "tag" in config:
            self._tag_colours[str(config["tag"]).upper()] = str(config["colour"])

    def _add(self, values: list[str], tag: str) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setRowHeight(row, 24)

        key = (tag or "").strip().upper()
        colour = self._colour_for(tag)
        last = self.table.columnCount() - 1

        for column in range(self.table.columnCount()):
            text = str(values[column]) if column < len(values) else ""
            item = QTableWidgetItem(text)

            # Numbers right-align on the decimal so a column of measurements
            # can be scanned down; names stay left.
            if column and _looks_numeric(text):
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            else:
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

            if column == last:
                # Only the verdict is coloured. Tinting the whole row makes a
                # table of mostly-passing results into a wall of green, and the
                # one failure stops standing out.
                font = QFont(theme.MONO.split(",")[0], 10)
                font.setBold(True)
                item.setFont(font)
                if colour:
                    item.setForeground(QColor(colour))
            elif key == "FAIL":
                item.setForeground(QColor(self._palette["text"]))
            else:
                item.setForeground(QColor(self._palette["muted"]))

            self.table.setItem(row, column, item)

        if key == "PASS":
            self.passed += 1
        elif key == "FAIL":
            self.failed += 1
            # A failing point kills the unit, so tint now rather than waiting
            # for the end of the run -- the operator can pull the board.
            self.set_tone("fail")
        self._update_count()
        self.table.scrollToBottom()

    def _update_count(self) -> None:
        total = self.passed + self.failed
        if not total:
            self.count.setText("")
        elif self.failed:
            self.count.setText(f"{self.failed} FAILED OF {total}")
        else:
            self.count.setText(f"{total} PASSED")

    def _colour_for(self, tag: str) -> str | None:
        key = (tag or "").strip().upper()
        if key in self._tag_colours:
            return self._tag_colours[key]
        palette_key = theme.RESULT_COLOURS.get(key)
        return self._palette.get(palette_key) if palette_key else None

    def set_alive(self, alive: bool) -> None:
        if alive:
            return
        self.dead = True
        self.set_tone("fail")
        # VALIDATE fails a unit and then kills it. FAIL is the more specific of
        # the two words, so it stays; anything else becomes DEAD, including a
        # stale PASS from a unit that died after being judged.
        if self.verdict.text() != "FAIL":
            self.verdict.set_state("DEAD")

    def set_verdict(self, state: str) -> None:
        self.verdict.set_state(state)
        self.set_tone({"PASS": "pass", "FAIL": "fail", "DEAD": "fail"}.get(state))

    def outcome(self) -> str | None:
        """'pass', 'fail', or None while the unit has produced nothing yet.

        Kept here rather than in the window so the header counters and the
        panel tint can never disagree about what a unit is doing.
        """
        if self.dead or self.failed:
            return "fail"
        state = self.verdict.text()
        if state in ("PASS", "FAIL"):
            return "pass" if state == "PASS" else "fail"
        return "pass" if self.passed else None

    # -- whole-panel verdict tint -----------------------------------------

    def set_tone(self, tone: str | None) -> None:
        """Wash the whole panel, not just the badge in its corner.

        A verdict on a 6-inch panel is easy to miss when four units are on
        screen; the surface behind the numbers is not. The tints sit close to
        the neutral surface on purpose -- enough to name the state across the
        bench, not so much that the measurements inside stop being readable.
        """
        self._tone = tone
        self.setStyleSheet(self._tone_sheet())

    def repaint_tone(self) -> None:
        """Re-apply the current tone after a palette change."""
        self.setStyleSheet(self._tone_sheet())

    def _tone_sheet(self) -> str:
        if not self._tone:
            return ""            # fall back to the application stylesheet
        p = self._palette
        surface = p.get(f"{self._tone}_surface", p["surface"])
        elevated = p.get(f"{self._tone}_elevated", p["elevated"])
        border = p.get(f"{self._tone}_border", p["border"])
        radius = theme.RADIUS["panel"]
        return (
            f"QFrame#Card {{ background: {surface};"
            f" border: 1px solid {border}; border-radius: {radius}px; }}"
            f"QTableWidget {{ background: {surface};"
            f" alternate-background-color: {elevated}; }}"
            f"QHeaderView::section {{ background: {surface};"
            f" border-bottom: 1px solid {border}; }}"
            f"QLabel#UnitNumber {{ background: {elevated};"
            f" border: 1px solid {border}; }}"
        )


class LogView(QPlainTextEdit):
    """Operator log with per-level colouring and a bounded backlog."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Log")
        self.setReadOnly(True)
        self.setMaximumBlockCount(MAX_LOG_LINES)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._palette = theme.palette(True)

    def append(self, message: str, level: str = "info", row=None) -> None:
        colour = self._palette.get(theme.LOG_COLOURS.get(level, "text"),
                                   self._palette["text"])
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(colour))
        if level in ("error", "fail"):
            fmt.setFontWeight(QFont.Bold)

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        prefix = f"{row:>4}  " if isinstance(row, int) else "      "
        cursor.insertText(f"{prefix}{message}\n", fmt)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def clear_log(self) -> None:
        self.clear()


class FieldRow(QWidget):
    """A compact label/value pair for the header strip."""

    def __init__(self, caption: str, value: str = "--", parent=None) -> None:
        super().__init__(parent)
        palette = theme.palette(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)

        self.caption = QLabel(caption.upper())
        self.caption.setStyleSheet(
            f"color: {palette['muted']}; font-size: 8.5pt; "
            f"font-weight: 600; letter-spacing: 1px;")
        self.value = QLabel(value)
        self.value.setStyleSheet(
            f"color: {palette['text']}; font-size: 13pt; "
            f"font-family: {theme.MONO};")
        layout.addWidget(self.caption)
        layout.addWidget(self.value)

    def set_value(self, text: str) -> None:
        self.value.setText(text or "--")


def _readable_on(background: str) -> str:
    """Pick black or white text for a given background.

    Uses relative luminance rather than a fixed choice, so a table that sets an
    unexpected Tag_Config colour still produces legible text.
    """
    colour = QColor(background)
    if not colour.isValid():
        return "#FFFFFF"

    def channel(value: float) -> float:
        value /= 255.0
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    luminance = (0.2126 * channel(colour.red())
                 + 0.7152 * channel(colour.green())
                 + 0.0722 * channel(colour.blue()))
    return "#0B0E11" if luminance > 0.45 else "#FFFFFF"


class Badge(QLabel):
    """A small state pill: SIMULATED, DEBUG, LEGACY.

    SIMULATED especially has to be visible without looking for it. A dry run
    that an operator mistakes for a real one is the single worst outcome a test
    station can produce, so it is a permanent marker on the header rather than a
    checkbox somewhere in a menu.
    """

    def __init__(self, text: str, tone: str = "warn", parent=None) -> None:
        super().__init__(text.upper(), parent)
        self.setObjectName("Badge")
        self.tone = tone
        self.setAlignment(Qt.AlignCenter)
        self.apply_palette(theme.palette(True))

    def apply_palette(self, palette: dict) -> None:
        colour = palette.get(self.tone, palette["muted"])
        self.setStyleSheet(
            f"background: {colour}; color: {_readable_on(colour)};"
            f"border-radius: 4px; padding: 4px 9px;"
            f"font-size: 8.5pt; font-weight: 800; letter-spacing: 1.2px;")


class Stat(QWidget):
    """A caption over a large monospace number.

    Tabular figures, so a changing value does not make the row jitter.
    """

    def __init__(self, caption: str, value: str = "--", parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.caption = QLabel(caption.upper())
        self.caption.setObjectName("StatCaption")
        self.value = QLabel(value)
        self.value.setObjectName("StatValue")
        font = self.value.font()
        font.setStyleHint(QFont.Monospace)
        self.value.setFont(font)

        layout.addWidget(self.caption)
        layout.addWidget(self.value)

    def set_value(self, text: str, tone: str | None = None,
                  palette: dict | None = None) -> None:
        self.value.setText(str(text))
        if palette is None:
            return
        # Clearing matters as much as setting: a counter that went red on the
        # last board must not still be red on the next one.
        colour = palette.get(tone, palette["text"]) if tone else palette["text"]
        self.value.setStyleSheet(
            f"background: transparent; color: {colour};"
            f"font-family: {theme.MONO}; font-size: 15pt; font-weight: 600;")


class ScanField(QWidget):
    """A scanned value -- barcode, worker id.

    Reads as an input even though it is filled by the program, because that is
    what the operator is scanning into. Empty shows a placeholder rather than
    collapsing, so the row keeps its shape between boards.
    """

    def __init__(self, caption: str, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        self.caption = QLabel(caption.upper())
        self.caption.setObjectName("ScanCaption")
        self.value = QLabel("—")
        self.value.setObjectName("ScanValue")
        self.value.setMinimumWidth(190)

        layout.addWidget(self.caption)
        layout.addWidget(self.value)

    def set_value(self, text: str) -> None:
        self.value.setText(text or "—")
