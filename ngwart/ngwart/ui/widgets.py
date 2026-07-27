"""Reusable widgets for the operator station."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QLabel,
                               QPlainTextEdit, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from . import theme

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
        self.setWordWrap(True)
        self.setMinimumHeight(84)
        self._palette = theme.palette(True)

    def set_palette_colours(self, colours: dict) -> None:
        self._palette = colours

    def show_status(self, text: str, colour: str | None = None) -> None:
        self.setText(text or "")
        background = colour or self._palette["elevated"]
        foreground = _readable_on(background)
        self.setStyleSheet(
            f"background: {background}; color: {foreground};"
            f"border-radius: 10px; padding: 14px 20px;"
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

        header = QHBoxLayout()
        self.title = QLabel(f"UUT {index}")
        self.title.setFont(QFont(theme.SANS.split(",")[0], 12, QFont.Bold))
        self.verdict = VerdictChip()
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.verdict)
        self.add_layout(header)

        self.table = QTableWidget(0, len(self._columns))
        self.table.setHorizontalHeaderLabels(self._columns)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.add(self.table, 1)

    # -- engine operations ------------------------------------------------

    def apply(self, op: str, values: list[str], tag: str, config: dict) -> None:
        if op == "add":
            self._add(values, tag)
        elif op == "clear":
            self.table.setRowCount(0)
            self.verdict.set_state("--")
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
        colour = self._colour_for(tag)
        for column in range(self.table.columnCount()):
            text = values[column] if column < len(values) else ""
            item = QTableWidgetItem(str(text))
            if colour:
                item.setForeground(QColor(colour))
            if column >= len(self._columns) - 1:
                item.setFont(QFont(theme.MONO.split(",")[0], 10, QFont.Bold))
            self.table.setItem(row, column, item)
        self.table.scrollToBottom()

    def _colour_for(self, tag: str) -> str | None:
        key = (tag or "").strip().upper()
        if key in self._tag_colours:
            return self._tag_colours[key]
        palette_key = theme.RESULT_COLOURS.get(key)
        return self._palette.get(palette_key) if palette_key else None

    def set_alive(self, alive: bool) -> None:
        if not alive:
            self.verdict.set_state("DEAD")

    def set_verdict(self, state: str) -> None:
        self.verdict.set_state(state)


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
        if tone and palette:
            self.value.setStyleSheet(
                f"color: {palette.get(tone, palette['text'])};"
                f"font-family: {theme.MONO}; font-size: 16pt; font-weight: 600;")


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
