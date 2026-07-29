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
                               QSizePolicy, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from . import theme
from .trend import TrendChart
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
        # Low enough that a splitter can squeeze it; the size hint is what asks
        # for room, and a minimum that asks is a minimum that starves its
        # neighbours.
        self.setMinimumHeight(150)
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

    def __init__(self, history, programs_dir: str | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.history = history
        #: Programs the station actually offers. The filter used to list every
        #: distinct name in the database, which accumulates one-off tables and
        #: retired products forever; the folder is the current truth.
        self.programs_dir = programs_dir
        self.session_runs: list[int] = []
        self._palette = theme.palette(True)
        #: (run_id, test, uut) per search-table row, so a click on either the
        #: chart or the table can find its counterpart in the other.
        self._row_keys: list[tuple] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE["sm"])

        layout.addWidget(self._build_control_bar())

        # Three full-width blocks stacked in one column left each about 180px --
        # too short for a chart to have a shape. The two charts sit side by side
        # instead, so each gets the whole remaining height, and everything below
        # the tiles is in splitters the operator can drag.
        charts = QSplitter(Qt.Horizontal)
        charts.addWidget(self._build_pareto())
        charts.addWidget(self._build_trend())
        charts.setStretchFactor(0, 4)
        charts.setStretchFactor(1, 6)
        charts.setSizes([560, 840])
        charts.setChildrenCollapsible(False)

        body = QSplitter(Qt.Vertical)
        body.addWidget(charts)
        body.addWidget(self._build_search())
        body.setStretchFactor(0, 5)
        body.setStretchFactor(1, 4)
        # Enough for the charts to have a shape and for the table to show more
        # than its header. Both panes are draggable from here.
        body.setSizes([340, 300])
        body.setChildrenCollapsible(False)
        self.body_splitter = body

        layout.addWidget(body, 1)
        self.refresh()

    # -- construction -----------------------------------------------------

    def _build_control_bar(self) -> QWidget:
        """Figures and filters on one line.

        They were two stacked cards, roughly 116px of chrome above the charts on
        a tab whose whole complaint was that the charts had no room. The figures
        read left, the controls that scope them read right, and the tab gets the
        height back.
        """
        card = Card()
        card._layout.setContentsMargins(12, 8, 12, 8)
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE["lg"])

        self.tiles = {}
        for key, caption in (("yield", "first-pass yield"), ("units", "units"),
                             ("runs", "runs"), ("points", "points"),
                             ("failed", "failed"), ("aborted", "aborted")):
            stat = Stat(caption, "—")
            self.tiles[key] = stat
            row.addWidget(stat, 0, Qt.AlignVCenter)
        row.addStretch(1)

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

        row.addWidget(self.scope_session, 0, Qt.AlignVCenter)
        row.addWidget(self.scope_all, 0, Qt.AlignVCenter)
        row.addWidget(self.program_filter, 0, Qt.AlignVCenter)
        row.addWidget(self.include_sim, 0, Qt.AlignVCenter)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        row.addWidget(self.refresh_button, 0, Qt.AlignVCenter)
        card.add_layout(row)
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

    def _build_trend(self) -> QWidget:
        card = Card("Result trend — measurement by run")
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE["sm"])

        self.trend_test = QComboBox()
        self.trend_test.setMinimumWidth(190)
        self.trend_test.currentIndexChanged.connect(self.refresh_trend)

        self.trend_zoom = QCheckBox("Zoom to data")
        self.trend_zoom.setToolTip(
            "Scale to the measurements instead of to the limits.\n"
            "Off by default: a limit cropped off the axis makes an "
            "out-of-spec point look ordinary.")
        self.trend_zoom.toggled.connect(self._set_trend_zoom)

        self.trend_note = QLabel("")
        self.trend_note.setObjectName("ProgramMeta")

        row.addWidget(QLabel("Test"))
        row.addWidget(self.trend_test)
        row.addWidget(self.trend_zoom)
        row.addSpacing(theme.SPACE["md"])
        row.addWidget(self.trend_note, 1)
        card.add_layout(row)

        self.trend = TrendChart()
        self.trend.point_clicked.connect(self._show_run)
        card.add(self.trend, 1)
        return card

    def _build_search(self) -> QWidget:
        card = Card("Search results")
        # Tighter than the default card: every pixel here is a row of results.
        card._layout.setContentsMargins(12, 8, 12, 8)
        card._layout.setSpacing(4)
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
        self.table.itemSelectionChanged.connect(self._on_row_selected)
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

        # Before anything reads the filter, not after: on the first refresh the
        # combo is still empty, and the tiles would answer for every program.
        self._refresh_programs()

        simulated = self.include_sim.isChecked()
        runs = self._scope_runs
        program = self.program_filter.currentData() or ""

        summary = self.history.summary(runs, include_simulated=simulated,
                                       program=program)
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
                                     include_simulated=simulated,
                                     program=program)
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
        programs = self._available_programs()
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

    def _available_programs(self) -> list[str]:
        """What the station offers, not what the database happens to remember.

        Falls back to the database when there is no programs folder to read, so
        a station pointed straight at a table still gets a usable filter.
        """
        from ..engine.loaders import program_names

        names = program_names(self.programs_dir) if self.programs_dir else []
        return names or (self.history.programs() if self.history else [])

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
        self._row_keys = [(r.get("run_id"), r.get("name"), r.get("uut"))
                          for r in rows]
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
        self._offer_tests([r["name"] for r in rows])

    # -- trend ------------------------------------------------------------

    def _offer_tests(self, names: list[str]) -> None:
        """Populate the trend selector from what the search actually matched.

        Ordered by how often each test appears, so the default is the test the
        search was mostly about rather than whichever name sorts first.
        """
        counts: dict[str, int] = {}
        for name in names:
            counts[name] = counts.get(name, 0) + 1
        ordered = sorted(counts, key=lambda n: (-counts[n], n))
        if ordered == [self.trend_test.itemText(i)
                       for i in range(self.trend_test.count())]:
            return
        current = self.trend_test.currentText()
        self.trend_test.blockSignals(True)
        self.trend_test.clear()
        self.trend_test.addItems(ordered)
        if current in ordered:
            self.trend_test.setCurrentText(current)
        self.trend_test.blockSignals(False)
        self.refresh_trend()

    def refresh_trend(self) -> None:
        if self.history is None or not self.history.available:
            return
        name = self.trend_test.currentText()
        if not name:
            self.trend.set_data("", [])
            self.trend_note.setText("")
            return

        rows = self.history.trend(
            name,
            program=self.program_filter.currentData() or "",
            run_ids=self._scope_runs,
            include_simulated=self.include_sim.isChecked())
        self.trend.set_data(name, rows)
        self._update_trend_note()

    def _set_trend_zoom(self, on: bool) -> None:
        self.trend.set_zoom(on)
        self._update_trend_note()

    def _update_trend_note(self) -> None:
        note = self._trend_caption(self.trend.summary())
        if not self.trend.limits_visible:
            note += "   ·   ⚠ a limit is off-scale"
        self.trend_note.setText(note)

    @staticmethod
    def _trend_caption(s: dict) -> str:
        if not s.get("n"):
            return "No history for this test in the current scope."
        parts = [f"{s['n']} point(s) over {s['units']} unit(s)"]
        if s.get("mean") is not None:
            parts.append(f"mean {s['mean']:.4g}")
            parts.append(f"range {s['min']:.4g} … {s['max']:.4g}")
        margin = s.get("margin")
        if margin is not None:
            # The number an engineer acts on. Negative means it did not merely
            # approach the limit, it went through it -- so say that instead of
            # printing a negative distance.
            parts.append(
                f"closest to a limit {margin:.1f}% of band" if margin >= 0
                else f"worst excursion {abs(margin):.1f}% of band past a limit")
        parts.append(f"{s['fails']} failed")
        if s.get("dropped"):
            parts.append(f"{s['dropped']} further unit(s) not shown")
        return "   ·   ".join(parts)

    def _show_run(self, run_id: int) -> None:
        """Clicking a point selects that measurement in the table below."""
        name = self.trend_test.currentText()
        for i, (rid, rname, _uut) in enumerate(getattr(self, "_row_keys", [])):
            if rid == run_id and rname == name:
                self.table.selectRow(i)
                self.table.scrollToItem(self.table.item(i, 0))
                return

    def _on_row_selected(self) -> None:
        """Selecting a row retargets the chart at that row's test."""
        row = self.table.currentRow()
        keys = getattr(self, "_row_keys", [])
        if 0 <= row < len(keys):
            name = keys[row][1]
            if name and name != self.trend_test.currentText():
                if self.trend_test.findText(name) < 0:
                    self.trend_test.addItem(name)
                self.trend_test.setCurrentText(name)

    def _search_for_test(self, name: str) -> None:
        """Clicking a Pareto bar drills into that test's history."""
        self.query.setText(name)
        self.result_filter.setCurrentIndex(1)      # failures only
        self.refresh_search()
        if self.trend_test.findText(name) < 0:
            self.trend_test.addItem(name)
        self.trend_test.setCurrentText(name)

    def apply_palette(self, palette: dict) -> None:
        self._palette = palette
        self.pareto.set_palette_colours(palette)
        self.trend.set_palette_colours(palette)
        self.refresh()
