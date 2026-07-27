"""Statistics tab: session and all-time yield, a Pareto of failures, and search.

The Pareto deserves a note, because the textbook version is drawn the one way a
chart should never be drawn.

Classic Pareto puts failure *counts* on a left axis and *cumulative percent* on
a right one. Two y-scales in a single plot let the author place the crossover
anywhere by choosing the scales, so the reader cannot trust what they see. Here
both series share one 0-100% axis: each bar is that test's share of all
failures, the line is the running total of those shares, and the raw count sits
on the bar. Nothing is lost and the geometry means what it looks like it means.

Colour carries one thing: whether a bar falls inside the 80% cutoff -- the
"vital few" that cause most failures. That is the whole point of a Pareto, and
it is encoded three ways over: colour, sort order, and a labelled cutoff line.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox,
                               QComboBox, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QRadioButton,
                               QSizePolicy, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from . import theme
from .widgets import Card, Stat

#: The Pareto principle's own threshold: bars up to here are the vital few.
CUTOFF = 80.0

#: More than this and the axis labels stop being readable; the rest is a tail
#: that a Pareto is explicitly not about.
MAX_BARS = 12


class ParetoChart(QWidget):
    """Failures by test: share as bars, cumulative share as a line, one axis."""

    bar_clicked = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(230)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self._palette = theme.palette(True)
        self._data: list[tuple[str, int, int]] = []
        self._bars: list[tuple[QRectF, str, int, int, float]] = []
        self._hover = -1

    def set_palette_colours(self, palette: dict) -> None:
        self._palette = palette
        self.update()

    def set_data(self, rows: list[tuple[str, int, int]]) -> None:
        """rows: (test name, failures, attempts), already sorted worst first."""
        self._data = list(rows)[:MAX_BARS]
        self._hover = -1
        self.update()

    # -- interaction ------------------------------------------------------

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt name
        hit = -1
        for i, (rect, *_rest) in enumerate(self._bars):
            if rect.left() <= event.position().x() <= rect.right():
                hit = i
                break
        if hit != self._hover:
            self._hover = hit
            if hit >= 0:
                name, fails, attempts, share = self._bars[hit][1:]
                rate = 100.0 * fails / attempts if attempts else 0.0
                self.setToolTip(
                    f"{name}\n{fails} failed of {attempts} attempts "
                    f"({rate:.1f}% fail rate)\n{share:.1f}% of all failures")
            else:
                self.setToolTip("")
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt name
        self._hover = -1
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt name
        if self._hover >= 0:
            self.bar_clicked.emit(self._bars[self._hover][1])

    # -- painting ---------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        c = self._palette
        painter.fillRect(self.rect(), QColor(c["surface"]))

        if not self._data:
            painter.setPen(QColor(c["faint"]))
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "No failures recorded in this scope.")
            return

        total = sum(f for _n, f, _a in self._data) or 1
        label_font = QFont(theme.SANS.split(",")[0], 8)
        value_font = QFont(theme.MONO.split(",")[0], 8, QFont.Bold)
        metrics = QFontMetrics(label_font)

        left, right = 44, 16
        top, bottom = 18, 20 + metrics.height() * 2
        plot = QRectF(left, top, max(self.width() - left - right, 10),
                      max(self.height() - top - bottom, 10))

        self._grid(painter, plot, c, label_font)

        count = len(self._data)
        slot = plot.width() / count
        # Thin marks: the bar is a fraction of its slot, so bars never touch and
        # no 2px spacer is needed between them.
        width = min(slot * 0.56, 46.0)

        self._bars = []
        cumulative = 0.0
        points = []

        for i, (name, fails, attempts) in enumerate(self._data):
            share = 100.0 * fails / total
            cumulative += share
            centre = plot.left() + slot * (i + 0.5)
            height = plot.height() * (share / 100.0)
            rect = QRectF(centre - width / 2, plot.bottom() - height,
                          width, height)
            vital = cumulative <= CUTOFF + 1e-9 or i == 0
            self._bars.append((QRectF(plot.left() + slot * i, plot.top(),
                                      slot, plot.height()),
                               name, fails, attempts, share))
            self._bar(painter, rect, c, vital, i == self._hover)
            self._bar_label(painter, rect, fails, c, value_font)
            self._axis_label(painter, centre, plot, slot, name, c, label_font,
                             metrics, i == self._hover)
            points.append((centre, plot.bottom() - plot.height() * (cumulative / 100.0)))

        self._cutoff(painter, plot, c, label_font)
        self._cumulative(painter, points, c)
        self._legend(painter, plot, c, label_font)

    def _grid(self, painter, plot, c, font) -> None:
        """Recessive gridlines and the single percentage axis."""
        painter.setFont(font)
        for value in (0, 25, 50, 75, 100):
            y = plot.bottom() - plot.height() * (value / 100.0)
            painter.setPen(QPen(QColor(c["border"]), 1, Qt.SolidLine))
            painter.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))
            painter.setPen(QColor(c["faint"]))
            painter.drawText(QRectF(0, y - 8, plot.left() - 8, 16),
                             Qt.AlignRight | Qt.AlignVCenter, f"{value}%")

    def _bar(self, painter, rect, c, vital: bool, hovered: bool) -> None:
        colour = QColor(c["fail"] if vital else c["idle"])
        if hovered:
            colour = colour.lighter(118)
        path = QPainterPath()
        # 4px rounded data-end, square where it meets the baseline.
        radius = min(4.0, rect.width() / 2, max(rect.height(), 1))
        path.moveTo(rect.left(), rect.bottom())
        path.lineTo(rect.left(), rect.top() + radius)
        path.quadTo(rect.left(), rect.top(), rect.left() + radius, rect.top())
        path.lineTo(rect.right() - radius, rect.top())
        path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + radius)
        path.lineTo(rect.right(), rect.bottom())
        path.closeSubpath()
        painter.fillPath(path, QBrush(colour))

    def _bar_label(self, painter, rect, fails, c, font) -> None:
        """The raw count, which the percentage axis alone would hide."""
        painter.setFont(font)
        painter.setPen(QColor(c["text"]))
        painter.drawText(QRectF(rect.left() - 12, rect.top() - 15,
                                rect.width() + 24, 14),
                         Qt.AlignCenter, str(fails))

    def _axis_label(self, painter, centre, plot, slot, name, c, font,
                    metrics, hovered: bool) -> None:
        painter.setFont(font)
        painter.setPen(QColor(c["text"] if hovered else c["faint"]))
        text = metrics.elidedText(name, Qt.ElideRight, int(slot) - 2)
        painter.drawText(QRectF(centre - slot / 2, plot.bottom() + 4, slot, 16),
                         Qt.AlignCenter, text)

    def _cutoff(self, painter, plot, c, font) -> None:
        y = plot.bottom() - plot.height() * (CUTOFF / 100.0)
        painter.setPen(QPen(QColor(c["warn"]), 1, Qt.DashLine))
        painter.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))
        painter.setFont(font)
        painter.setPen(QColor(c["warn"]))
        painter.drawText(QRectF(plot.right() - 78, y - 15, 76, 14),
                         Qt.AlignRight | Qt.AlignVCenter, "80% cutoff")

    def _cumulative(self, painter, points, c) -> None:
        if len(points) < 2:
            return
        painter.setPen(QPen(QColor(c["accent"]), 2, Qt.SolidLine,
                            Qt.RoundCap, Qt.RoundJoin))
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))
        # A surface ring so a marker over a bar stays separable.
        for x, y in points:
            painter.setPen(QPen(QColor(c["surface"]), 2))
            painter.setBrush(QBrush(QColor(c["accent"])))
            painter.drawEllipse(QRectF(x - 4, y - 4, 8, 8))

    def _legend(self, painter, plot, c, font) -> None:
        """Two series means a legend, always -- identity is never colour alone."""
        painter.setFont(font)
        entries = [(c["fail"], "vital few"), (c["idle"], "the rest"),
                   (c["accent"], "cumulative")]
        x = plot.left()
        y = plot.bottom() + 22
        for colour, text in entries:
            painter.fillRect(QRectF(x, y + 3, 9, 9), QColor(colour))
            painter.setPen(QColor(c["faint"]))
            width = QFontMetrics(font).horizontalAdvance(text)
            painter.drawText(QRectF(x + 13, y, width + 4, 14),
                             Qt.AlignLeft | Qt.AlignVCenter, text)
            x += 13 + width + 18


class StatsTab(QWidget):
    """Session and all-time figures, the Pareto, and a search over history."""

    def __init__(self, history, parent=None) -> None:
        super().__init__(parent)
        self.history = history
        self.session_runs: list[int] = []
        self._palette = theme.palette(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE["sm"])

        layout.addWidget(self._build_scope())
        layout.addWidget(self._build_tiles())
        layout.addWidget(self._build_pareto(), 3)
        layout.addWidget(self._build_search(), 4)
        self.refresh()

    # -- construction -----------------------------------------------------

    def _build_scope(self) -> QWidget:
        card = Card()
        card._layout.setContentsMargins(12, 8, 12, 8)
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE["md"])

        self.scope_session = QRadioButton("This session")
        self.scope_all = QRadioButton("All time")
        self.scope_session.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.scope_session)
        group.addButton(self.scope_all)
        self.scope_session.toggled.connect(self.refresh)

        self.program_filter = QComboBox()
        self.program_filter.addItem("All programs", "")
        self.program_filter.currentIndexChanged.connect(self.refresh)

        self.include_sim = QCheckBox("Include simulated")
        self.include_sim.setToolTip(
            "Off by default. Folding dry runs into a yield figure would "
            "quietly corrupt the number that matters most.")
        self.include_sim.toggled.connect(self.refresh)

        row.addWidget(QLabel("Scope"))
        row.addWidget(self.scope_session)
        row.addWidget(self.scope_all)
        row.addSpacing(theme.SPACE["lg"])
        row.addWidget(self.program_filter)
        row.addWidget(self.include_sim)
        row.addStretch(1)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        row.addWidget(self.refresh_button)
        card.add_layout(row)
        return card

    def _build_tiles(self) -> QWidget:
        card = Card()
        card._layout.setContentsMargins(12, 8, 12, 10)
        grid = QGridLayout()
        grid.setSpacing(theme.SPACE["xl"])
        self.tiles = {}
        for column, (key, caption) in enumerate((
                ("yield", "first-pass yield"), ("units", "units"),
                ("runs", "runs"), ("points", "points"),
                ("failed", "failed"), ("aborted", "aborted"))):
            stat = Stat(caption, "—")
            self.tiles[key] = stat
            grid.addWidget(stat, 0, column)
        grid.setColumnStretch(6, 1)
        card.add_layout(grid)
        return card

    def _build_pareto(self) -> QWidget:
        card = Card("Failures by test — Pareto")
        self.pareto = ParetoChart()
        self.pareto.bar_clicked.connect(self._search_for_test)
        card.add(self.pareto, 1)
        self.pareto_note = QLabel("")
        self.pareto_note.setObjectName("ProgramMeta")
        card.add(self.pareto_note)
        return card

    def _build_search(self) -> QWidget:
        card = Card("Search results")
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE["sm"])

        self.query = QLineEdit()
        self.query.setPlaceholderText("test id or barcode…")
        self.query.returnPressed.connect(self.refresh_search)

        self.result_filter = QComboBox()
        for label, value in (("All results", ""), ("Failures only", "FAIL"),
                             ("Passes only", "PASS")):
            self.result_filter.addItem(label, value)
        self.result_filter.currentIndexChanged.connect(self.refresh_search)

        search_button = QPushButton("Search")
        search_button.clicked.connect(self.refresh_search)

        self.match_count = QLabel("")
        self.match_count.setObjectName("ProgramMeta")

        row.addWidget(self.query, 2)
        row.addWidget(self.result_filter)
        row.addWidget(search_button)
        row.addWidget(self.match_count)
        row.addStretch(1)
        card.add_layout(row)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["When", "Program", "Test", "Unit", "Result", "Measured",
             "Limits", "Barcode"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        card.add(self.table, 1)
        return card

    # -- data -------------------------------------------------------------

    @property
    def _scope_runs(self) -> list[int] | None:
        return self.session_runs if self.scope_session.isChecked() else None

    def note_run(self, run_id: int | None) -> None:
        """Called when a run finishes, so 'this session' means something."""
        if run_id is not None:
            self.session_runs.append(run_id)
        self.refresh()

    def refresh(self) -> None:
        if self.history is None or not self.history.available:
            self.pareto_note.setText(
                "History unavailable" +
                (f": {self.history.error}" if self.history else ""))
            return

        simulated = self.include_sim.isChecked()
        runs = self._scope_runs

        summary = self.history.summary(runs, include_simulated=simulated)
        self.tiles["yield"].set_value(
            f"{summary.yield_pct:.1f}%" if summary.units else "—",
            "pass" if summary.yield_pct >= 95 else
            ("warn" if summary.yield_pct >= 80 else "fail"),
            self._palette)
        self.tiles["units"].set_value(str(summary.units))
        self.tiles["runs"].set_value(str(summary.runs))
        self.tiles["points"].set_value(str(summary.points))
        self.tiles["failed"].set_value(
            str(summary.failed), "fail" if summary.failed else None,
            self._palette)
        self.tiles["aborted"].set_value(
            str(summary.aborted), "warn" if summary.aborted else None,
            self._palette)

        pareto = self.history.pareto(runs, limit=MAX_BARS,
                                     include_simulated=simulated)
        self.pareto.set_data(pareto)
        total_failures = summary.failed
        shown = sum(f for _n, f, _a in pareto)
        if not pareto:
            self.pareto_note.setText("No failures in this scope.")
        else:
            vital = self._vital_few(pareto)
            note = (f"{len(vital)} of {len(pareto)} tests account for "
                    f"{CUTOFF:.0f}% of failures: {', '.join(vital)}")
            if shown < total_failures:
                note += f"   ·   showing top {len(pareto)} of {total_failures} failures"
            self.pareto_note.setText(note)

        self._refresh_programs()
        self.refresh_search()

    @staticmethod
    def _vital_few(pareto: list[tuple[str, int, int]]) -> list[str]:
        total = sum(f for _n, f, _a in pareto) or 1
        names, cumulative = [], 0.0
        for name, fails, _attempts in pareto:
            cumulative += 100.0 * fails / total
            names.append(name)
            if cumulative >= CUTOFF:
                break
        return names

    def _refresh_programs(self) -> None:
        current = self.program_filter.currentData()
        programs = self.history.programs()
        if [self.program_filter.itemData(i)
                for i in range(self.program_filter.count())][1:] == programs:
            return
        self.program_filter.blockSignals(True)
        self.program_filter.clear()
        self.program_filter.addItem("All programs", "")
        for name in programs:
            self.program_filter.addItem(name, name)
        index = self.program_filter.findData(current)
        self.program_filter.setCurrentIndex(max(index, 0))
        self.program_filter.blockSignals(False)

    def refresh_search(self) -> None:
        if self.history is None or not self.history.available:
            return
        rows = self.history.search(
            text=self.query.text().strip(),
            result=self.result_filter.currentData() or "",
            program=self.program_filter.currentData() or "",
            include_simulated=self.include_sim.isChecked())

        self.match_count.setText(f"{len(rows)} result(s)")
        self.table.setRowCount(len(rows))
        palette = self._palette
        for i, row in enumerate(rows):
            limits = " / ".join(x for x in (row["low"], row["high"])
                                if x and x not in ("None", ""))
            cells = [row["started"], row["program"] or "", row["name"],
                     "" if row["uut"] is None else str(row["uut"] + 1),
                     row["result"], row["measured"] or "", limits,
                     row["barcode"] or ""]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(str(text))
                if column == 4:
                    key = theme.RESULT_COLOURS.get(str(text).upper())
                    if key:
                        item.setForeground(QColor(palette[key]))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.table.setItem(i, column, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

    def _search_for_test(self, name: str) -> None:
        """Clicking a Pareto bar drills into that test's history."""
        self.query.setText(name)
        self.result_filter.setCurrentIndex(1)      # failures only
        self.refresh_search()

    def apply_palette(self, palette: dict) -> None:
        self._palette = palette
        self.pareto.set_palette_colours(palette)
        self.refresh()
