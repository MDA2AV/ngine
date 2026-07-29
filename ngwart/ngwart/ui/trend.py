"""Run chart: how one test's measurement varies from run to run.

A yield figure says how often a board passed. It cannot say that a current has
been climbing for three weeks and will cross the limit on Thursday. That is what
this answers, and it is the difference between reacting to failures and seeing
them coming.

Three decisions are worth stating.

**One lane per unit, not one line per unit.** A four-up fixture measures the same
test at four physical positions, and a bad position is exactly the failure this
chart should expose -- so the unit has to be visible. Encoding it as four
coloured lines fails: run the palette validator on any four hues and the best
separation achievable under deuteranopia is far below the threshold, because
green-blind vision keeps essentially one usable hue axis. Faceting is the
prescribed remedy, and it is also the better chart -- lanes share a y scale, so
positions can be compared by eye without untangling crossing lines.

**Colour is left to carry state, and only the exception.** With the unit encoded
by position, hue is free. Passing points are neutral ink -- there are hundreds of
them and they are not news. A failure is the only coloured mark, and it is also
a diamond rather than a circle and carries its value as a label, so it survives
any colour vision deficiency, a greyscale print, and a glance.

**A limit is drawn as a region, not a rule.** What an engineer reads here is
margin -- how much room is left -- and a shaded in-spec band shows that as a
distance, where two lines make it something you have to measure by eye.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QPainter,
                           QPolygonF, QPen)
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import theme

#: Lanes beyond this stop being readable in the space available. Whatever is
#: dropped is named in the caption -- a silent cap reads as "this is everything".
MAX_LANES = 6

#: What a lane wants, so four units read comfortably on a 1080p panel.
LANE_HEIGHT = 62

#: What a lane will accept. Kept well below LANE_HEIGHT so the chart can be
#: squeezed by a splitter instead of pinning it: a minimum tall enough to be
#: comfortable is a minimum that starves whatever shares the window.
LANE_MINIMUM = 30


class TrendChart(QWidget):
    """One test's measurements over time, one lane per unit."""

    point_clicked = Signal(int)          # run_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(96)
        self._wanted = 240
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self._palette = theme.palette(True)
        self._name = ""
        self._lanes: list[tuple[int, list[dict]]] = []
        self._low: float | None = None
        self._high: float | None = None
        self._span: tuple[float, float] = (0.0, 1.0)
        self._hits: list[tuple[QPointF, dict]] = []
        self._hover = -1
        self._dropped = 0
        self._numeric = True
        self._zoom = False

    # -- data -------------------------------------------------------------

    def set_palette_colours(self, palette: dict) -> None:
        self._palette = palette
        self.update()

    def set_data(self, name: str, rows: list[dict]) -> None:
        """rows: history.trend() output, oldest first."""
        self._name = name
        self._hover = -1
        self._hits = []
        self._lanes = []
        self._dropped = 0

        by_unit: dict[int, list[dict]] = {}
        for row in rows:
            by_unit.setdefault(row.get("uut") if row.get("uut") is not None else -1,
                               []).append(row)
        order = sorted(by_unit)
        self._lanes = [(u, by_unit[u]) for u in order[:MAX_LANES]]
        self._dropped = max(0, len(order) - MAX_LANES)

        values = [r["value"] for _u, pts in self._lanes for r in pts
                  if r["value"] is not None]
        self._numeric = len(values) >= 2
        self._low = _first(r["low_value"] for _u, pts in self._lanes for r in pts)
        self._high = _first(r["high_value"] for _u, pts in self._lanes for r in pts)
        self._rescale(values)

        lanes = max(len(self._lanes), 1)
        self.setMinimumHeight(max(96, 26 + LANE_MINIMUM * lanes))
        self._wanted = max(150, 34 + LANE_HEIGHT * lanes)
        self.updateGeometry()
        self.update()

    def sizeHint(self):  # noqa: N802 - Qt name
        from PySide6.QtCore import QSize

        return QSize(560, getattr(self, "_wanted", 240))

    def _rescale(self, values=None) -> None:
        if values is None:
            values = [r["value"] for _u, pts in self._lanes for r in pts
                      if r["value"] is not None]
        limits = (None, None) if self._zoom else (self._low, self._high)
        self._span = _scale(values, *limits)

    def set_zoom(self, zoom: bool) -> None:
        """Scale to the data instead of to the limits.

        Off by default, and it has to stay that way: a limit cropped off the
        axis makes an out-of-spec point look ordinary, which is the one reading
        this chart must never produce. It is offered because a test whose limits
        sit far from its working range -- a current spec'd 0-1A that runs at
        0.23A -- otherwise draws every board as the same flat line, and the
        drift that predicts next month's failures is invisible. Deliberate and
        labelled, so nobody is misled by an axis they did not ask for.
        """
        self._zoom = bool(zoom)
        self._rescale()
        self.update()

    @property
    def limits_visible(self) -> bool:
        """Whether both limits still fall inside the drawn range."""
        lo, hi = self._span
        return all(v is None or lo <= v <= hi for v in (self._low, self._high))

    def summary(self) -> dict:
        """Figures for the caption above the chart."""
        values = [r["value"] for _u, pts in self._lanes for r in pts
                  if r["value"] is not None]
        points = [r for _u, pts in self._lanes for r in pts]
        fails = sum(1 for r in points if str(r["result"]).upper() == "FAIL")
        out = {"n": len(points), "fails": fails, "units": len(self._lanes),
               "dropped": self._dropped, "numeric": self._numeric}
        if values:
            out["mean"] = sum(values) / len(values)
            out["min"] = min(values)
            out["max"] = max(values)
            out["margin"] = _worst_margin(values, self._low, self._high)
        return out

    # -- interaction ------------------------------------------------------

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt name
        pos = event.position()
        hit, best = -1, 12.0 ** 2
        for i, (point, _row) in enumerate(self._hits):
            d = (point.x() - pos.x()) ** 2 + (point.y() - pos.y()) ** 2
            if d < best:
                hit, best = i, d
        if hit != self._hover:
            self._hover = hit
            self.setToolTip(_tooltip(self._hits[hit][1]) if hit >= 0 else "")
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt name
        self._hover = -1
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt name
        if self._hover >= 0:
            self.point_clicked.emit(self._hits[self._hover][1]["run_id"])

    # -- painting ---------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        c = self._palette
        painter.fillRect(self.rect(), QColor(c["surface"]))

        if not self._lanes:
            self._empty(painter, "Search for a test to see how it varies between runs.")
            return
        if not self._numeric:
            self._strip(painter)
            return

        label_font = QFont(theme.SANS.split(",")[0], 8)
        metrics = QFontMetrics(label_font)
        gutter = max(52, metrics.horizontalAdvance("UNIT 8") + 12)
        right = 58
        bottom = 18

        self._hits = []
        lanes = len(self._lanes)
        usable = max(self.height() - bottom, LANE_HEIGHT)
        height = usable / lanes

        for i, (unit, points) in enumerate(self._lanes):
            lane = QRectF(gutter, i * height + 6,
                          max(self.width() - gutter - right, 10), height - 12)
            self._lane(painter, lane, unit, points, label_font, metrics,
                       last=i == lanes - 1)

        self._x_axis(painter, gutter, label_font, metrics, bottom)

    def _lane(self, painter, lane, unit, points, font, metrics, last: bool) -> None:
        c = self._palette
        lo, hi = self._span

        def y_of(value: float) -> float:
            return lane.bottom() - lane.height() * ((value - lo) / (hi - lo))

        # The in-spec band as a region: margin is a distance, so show it as one.
        if self._low is not None or self._high is not None:
            top = y_of(self._high) if self._high is not None else lane.top()
            base = y_of(self._low) if self._low is not None else lane.bottom()
            painter.fillRect(QRectF(lane.left(), max(top, lane.top()),
                                    lane.width(),
                                    max(min(base, lane.bottom()) - max(top, lane.top()), 0)),
                             QColor(c["elevated"]))

        painter.setPen(QPen(QColor(c["border"]), 1))
        painter.drawLine(int(lane.left()), int(lane.bottom()),
                         int(lane.right()), int(lane.bottom()))

        for value, text in ((self._high, "high"), (self._low, "low")):
            if value is None:
                continue
            y = y_of(value)
            if not (lane.top() - 1 <= y <= lane.bottom() + 1):
                continue
            painter.setPen(QPen(QColor(c["warn"]), 1, Qt.DashLine))
            painter.drawLine(int(lane.left()), int(y), int(lane.right()), int(y))
            if last:
                painter.setFont(font)
                painter.setPen(QColor(c["warn"]))
                painter.drawText(QRectF(lane.right() + 4, y - 7, 52, 14),
                                 Qt.AlignLeft | Qt.AlignVCenter,
                                 f"{text} {_fmt(value)}")

        painter.setFont(font)
        painter.setPen(QColor(c["faint"]))
        painter.drawText(QRectF(0, lane.top(), lane.left() - 8, lane.height()),
                         Qt.AlignRight | Qt.AlignVCenter,
                         "UNIT " + (str(unit + 1) if unit >= 0 else "-"))

        plotted = [(i, r) for i, r in enumerate(points) if r["value"] is not None]
        if not plotted:
            return
        step = lane.width() / max(len(points) - 1, 1)
        coords = [(QPointF(lane.left() + step * i, y_of(r["value"])), r)
                  for i, r in plotted]

        if len(coords) > 1:
            painter.setPen(QPen(QColor(c["muted"]), 2, Qt.SolidLine,
                                Qt.RoundCap, Qt.RoundJoin))
            for (p1, _a), (p2, _b) in zip(coords, coords[1:]):
                painter.drawLine(p1, p2)

        for point, row in coords:
            failed = str(row["result"]).upper() == "FAIL"
            index = len(self._hits)
            self._hits.append((point, row))
            self._mark(painter, point, failed, index == self._hover)

        self._labels(painter, coords, font, metrics, lane)

    def _mark(self, painter, point, failed: bool, hovered: bool) -> None:
        """A surface ring keeps overlapping marks separable."""
        c = self._palette
        painter.setPen(QPen(QColor(c["surface"]), 2))
        if failed:
            # A different shape, not only a different colour.
            painter.setBrush(QBrush(QColor(c["fail"])))
            r = 6.0 if hovered else 5.0
            painter.drawPolygon(QPolygonF([
                QPointF(point.x(), point.y() - r), QPointF(point.x() + r, point.y()),
                QPointF(point.x(), point.y() + r), QPointF(point.x() - r, point.y())]))
        else:
            painter.setBrush(QBrush(QColor(c["accent"] if hovered else c["muted"])))
            r = 5.0 if hovered else 4.0
            painter.drawEllipse(point, r, r)

    def _labels(self, painter, coords, font, metrics, lane) -> None:
        """Label the exceptions and the latest value -- never every point."""
        c = self._palette
        painter.setFont(font)
        wanted = [(p, r) for p, r in coords if str(r["result"]).upper() == "FAIL"]
        if coords:
            wanted.append(coords[-1])
        drawn: list[QRectF] = []
        for point, row in wanted:
            failed = str(row["result"]).upper() == "FAIL"
            text = _fmt(row["value"])
            width = metrics.horizontalAdvance(text) + 6
            box = QRectF(point.x() - width / 2, point.y() - 20, width, 13)
            if box.right() > lane.right():
                box.moveRight(lane.right())
            if box.left() < lane.left():
                box.moveLeft(lane.left())
            if any(box.intersects(other) for other in drawn):
                continue
            drawn.append(box)
            painter.setPen(QColor(c["fail"] if failed else c["faint"]))
            painter.drawText(box, Qt.AlignCenter, text)

    def _x_axis(self, painter, gutter, font, metrics, bottom) -> None:
        """Oldest and newest, named. A tick per run would be unreadable."""
        points = [r for _u, pts in self._lanes for r in pts]
        if not points:
            return
        painter.setFont(font)
        painter.setPen(QColor(self._palette["faint"]))
        y = self.height() - bottom + 2
        painter.drawText(QRectF(gutter, y, 220, 14), Qt.AlignLeft | Qt.AlignVCenter,
                         _when(points[0]["started"]) + "  ←  oldest")
        painter.drawText(QRectF(self.width() - 278, y, 220, 14),
                         Qt.AlignRight | Qt.AlignVCenter,
                         "newest  →  " + _when(points[-1]["started"]))

    def _strip(self, painter) -> None:
        """Fallback for a test that does not record a number.

        EVALLEDS stores a colour triple and a failed EVALCONT stores NOT_FOUND;
        there is no value axis for those, but pass/fail per run is still a shape
        worth seeing, so it is drawn as one row of cells per unit.
        """
        c = self._palette
        font = QFont(theme.SANS.split(",")[0], 8)
        metrics = QFontMetrics(font)
        gutter = max(52, metrics.horizontalAdvance("UNIT 8") + 12)
        self._hits = []

        painter.setFont(font)
        painter.setPen(QColor(c["faint"]))
        painter.drawText(QRectF(gutter, 2, self.width() - gutter - 8, 14),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         f"{self._name} records no numeric value — "
                         f"showing pass/fail per run")

        top = 22
        height = max((self.height() - top - 8) / max(len(self._lanes), 1), 14)
        for i, (unit, points) in enumerate(self._lanes):
            y = top + i * height
            painter.setPen(QColor(c["faint"]))
            painter.drawText(QRectF(0, y, gutter - 8, height - 4),
                             Qt.AlignRight | Qt.AlignVCenter,
                             "UNIT " + (str(unit + 1) if unit >= 0 else "-"))
            width = (self.width() - gutter - 8) / max(len(points), 1)
            for j, row in enumerate(points):
                failed = str(row["result"]).upper() == "FAIL"
                cell = QRectF(gutter + j * width + 1, y + 2,
                              max(width - 2, 1), max(height - 8, 4))
                painter.fillRect(cell, QColor(c["fail"] if failed else c["idle"]))
                self._hits.append((QPointF(cell.center()), row))

    def _empty(self, painter, message: str) -> None:
        painter.setPen(QColor(self._palette["faint"]))
        painter.drawText(self.rect(), Qt.AlignCenter, message)


# --- helpers -------------------------------------------------------------

def _first(values):
    for value in values:
        if value is not None:
            return value
    return None


def _scale(values, low, high) -> tuple[float, float]:
    """A y range containing the values, and the limits when they are given.

    The caller passes the limits unless the operator has explicitly asked to
    zoom to the data -- cropping a limit off the axis by default would make an
    out-of-spec point look normal.
    """
    candidates = [v for v in (*values, low, high) if v is not None]
    if not candidates:
        return 0.0, 1.0
    lo, hi = min(candidates), max(candidates)
    if hi - lo < 1e-12:
        pad = abs(hi) * 0.1 or 1.0
        return lo - pad, hi + pad
    pad = (hi - lo) * 0.12
    return lo - pad, hi + pad


def _worst_margin(values, low, high) -> float | None:
    """Closest approach to a limit, as a share of the limit band."""
    if low is None or high is None or high <= low:
        return None
    band = high - low
    return min(min(v - low, high - v) for v in values) / band * 100.0


def _fmt(value) -> str:
    if value is None:
        return "—"
    if abs(value) >= 1000 or (value and abs(value) < 0.001):
        return f"{value:.3g}"
    return f"{value:.4g}"


def _when(started: str) -> str:
    return (started or "").replace("T", " ")[:16]


def _tooltip(row: dict) -> str:
    when = _when(row.get("started"))
    unit = row.get("uut")
    lines = [f"{row.get('name', '')}   {row.get('result', '')}",
             f"measured {row.get('measured')}"]
    if row.get("low") not in (None, "", "None"):
        lines.append(f"limits {row.get('low')} … {row.get('high')}")
    lines.append(f"unit {unit + 1 if isinstance(unit, int) and unit >= 0 else '-'}"
                 f"   run {row.get('run_id')}   {when}")
    if row.get("barcode"):
        lines.append(str(row["barcode"]))
    return "\n".join(lines)
