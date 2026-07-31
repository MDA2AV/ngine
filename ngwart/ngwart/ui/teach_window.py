"""The teach window: click a contour, keep its centroid.

A view over ``ngwart.teach``. It holds no rules of its own -- which blob a click
means, what a site is and what gets written are all decided there, so the same
behaviour is under test headlessly.

Two things drive the layout:

* **The operator is comparing two numbers a few pixels apart.** cargo.ods puts
  its LEDs 17 px apart with a 10 px window, so a fit-to-window view of a
  1296x972 frame cannot show whether a click landed on the right one. Zoom is
  therefore not a convenience; the canvas opens fitted and zooms to the cursor.
* **Teaching is a list you work down, not a canvas you decorate.** The sites
  come from the table in row order, one row is current, and a click fills it in
  and advances. Which means the job has a visible end -- the untaught count.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QAction, QBrush, QColor, QFont, QImage, QKeySequence,
                           QPainter, QPen, QPixmap, QPolygonF, QTransform)
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QMainWindow, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QWidget)

from .. import teach as teachlib
from . import theme
from .widgets import Card

#: Zoom limits. Below the lower bound a 4000px frame is unreadable anyway;
#: above the upper one a single pixel fills the panel and the operator is
#: aiming at nothing.
MIN_ZOOM, MAX_ZOOM = 0.05, 40.0

#: How far from a centroid a click still counts, in *image* pixels. Generous on
#: purpose -- the click only has to name a blob, and the coordinate that gets
#: stored is the centroid, not where the mouse was.
PICK_RADIUS = 40.0


def _to_qimage(frame):
    """Turn a numpy frame into a QImage, keeping the buffer alive.

    QImage wraps the memory it is given rather than copying it, so the array has
    to outlive the image. The caller stores both.
    """
    if frame is None:
        return None, None
    try:
        import numpy as np
    except ImportError:
        return None, None

    array = np.ascontiguousarray(frame)
    if array.ndim == 2:
        height, width = array.shape
        image = QImage(array.data, width, height, array.strides[0],
                       QImage.Format_Grayscale8)
    elif array.ndim == 3 and array.shape[2] >= 3:
        # OpenCV hands out BGR; QImage reads RGB. The copy is what makes the
        # result contiguous as well as reordered.
        array = np.ascontiguousarray(array[:, :, 2::-1])
        height, width = array.shape[:2]
        image = QImage(array.data, width, height, array.strides[0],
                       QImage.Format_RGB888)
    else:
        return None, None
    return image.copy(), array


class ImageCanvas(QWidget):
    """The frame, its contours, and the sites taught on it."""

    picked = Signal(int, int, float)      # cx, cy, area
    hovered = Signal(float, float)

    def __init__(self, palette: dict, parent=None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(360, 280)

        self._palette = palette
        self._pixmaps: dict[str, QPixmap] = {}
        self._buffers: list = []          # keeps QImage backing stores alive
        # The thresholded frame, not the capture. The contours come from this
        # one, so it is the image that answers "will the test find this blob?"
        # -- a bright LED in the colour frame that thresholds away is exactly
        # the case an operator needs to see before clicking it.
        self._view = "binary"
        self._contours = []
        self._polygons: list[QPolygonF] = []
        self._blobs: list = []
        self._sites: list = []
        self._current = -1
        self._show_contours = True
        self._show_windows = True

        #: Smallest contour a click may select. Defaults to the runtime's floor;
        #: a calibration can lower it where the test does not have to find the
        #: blob (see Calibration.min_area).
        self.noise_floor = teachlib.MIN_CONTOUR_PIXELS

        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self._dragging = False
        self._drag_from = QPointF(0, 0)

    # -- content ----------------------------------------------------------

    def set_images(self, frame=None, binary=None) -> None:
        """Show a new frame, keeping the view when the geometry has not changed.

        Switching between a program's captures shows the same scene at the same
        size -- so refitting would throw away the zoom and pan the operator set
        up to work at, for no reason. Fit only when there is nothing to preserve
        or the frame is genuinely a different shape.
        """
        was = self.size_hint_image

        self._pixmaps.clear()
        self._buffers.clear()
        for name, source in (("frame", frame), ("binary", binary)):
            image, buffer = _to_qimage(source)
            if image is not None:
                self._pixmaps[name] = QPixmap.fromImage(image)
                self._buffers.append(buffer)
        # Fall back to whichever image exists, rather than showing nothing.
        if self._view not in self._pixmaps:
            for candidate in ("binary", "frame"):
                if candidate in self._pixmaps:
                    self._view = candidate
                    break

        if was == (0, 0) or was != self.size_hint_image:
            self.fit()
        else:
            self.update()

    def set_contours(self, contours) -> None:
        self._contours = list(contours or [])
        self._blobs = teachlib.measure(self._contours, self.noise_floor)
        self._polygons = []
        for contour in self._contours:
            points = [QPointF(float(p[0][0]), float(p[0][1])) for p in contour]
            if len(points) > 1:
                self._polygons.append(QPolygonF(points))
        self.update()

    def set_sites(self, sites: list, current: int = -1) -> None:
        self._sites = sites
        self._current = current
        self.update()

    def set_view(self, name: str) -> None:
        self._view = name
        self.update()

    def set_show_contours(self, on: bool) -> None:
        self._show_contours = on
        self.update()

    def set_show_windows(self, on: bool) -> None:
        self._show_windows = on
        self.update()

    @property
    def blobs(self) -> list:
        return self._blobs

    @property
    def size_hint_image(self) -> tuple[int, int]:
        pixmap = self._pixmap()
        return (pixmap.width(), pixmap.height()) if pixmap else (0, 0)

    # -- view -------------------------------------------------------------

    def _pixmap(self) -> QPixmap | None:
        return self._pixmaps.get(self._view) or self._pixmaps.get("frame") \
            or self._pixmaps.get("binary")

    def _transform(self) -> QTransform:
        t = QTransform()
        t.translate(self._pan.x(), self._pan.y())
        t.scale(self._zoom, self._zoom)
        return t

    def to_image(self, point: QPointF) -> QPointF:
        inverted, ok = self._transform().inverted()
        return inverted.map(point) if ok else point

    def fit(self) -> None:
        pixmap = self._pixmap()
        if pixmap is None or not pixmap.width():
            return
        scale = min(self.width() / pixmap.width(), self.height() / pixmap.height())
        self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, scale * 0.98))
        self._pan = QPointF(
            (self.width() - pixmap.width() * self._zoom) / 2,
            (self.height() - pixmap.height() * self._zoom) / 2)
        self.update()

    def centre_on(self, cx: float, cy: float, zoom: float | None = None) -> None:
        """Put an image coordinate in the middle, optionally zooming in.

        Used when the operator selects a site: the point they need to look at is
        17 px from its neighbour, so scrolling to it by hand is the slow part of
        the job.
        """
        if zoom is not None:
            self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        self._pan = QPointF(self.width() / 2 - cx * self._zoom,
                            self.height() / 2 - cy * self._zoom)
        self.update()

    def zoom_by(self, factor: float, anchor: QPointF | None = None) -> None:
        anchor = anchor or QPointF(self.width() / 2, self.height() / 2)
        before = self.to_image(anchor)
        self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, self._zoom * factor))
        after = self.to_image(anchor)
        self._pan += QPointF((after.x() - before.x()) * self._zoom,
                             (after.y() - before.y()) * self._zoom)
        self.update()

    # -- events -----------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt name
        super().resizeEvent(event)
        if self._zoom == 1.0 and self._pan.isNull():
            self.fit()

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta:
            self.zoom_by(1.15 if delta > 0 else 1 / 1.15,
                         QPointF(event.position()))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() in (Qt.MiddleButton, Qt.RightButton):
            self._dragging = True
            self._drag_from = QPointF(event.position())
            self.setCursor(Qt.ClosedHandCursor)
            return
        if event.button() != Qt.LeftButton:
            return
        point = self.to_image(QPointF(event.position()))
        blob = teachlib.blob_at(self._contours, point.x(), point.y(),
                                PICK_RADIUS, self.noise_floor)
        if blob is not None:
            self.picked.emit(blob.cx, blob.cy, blob.area)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        position = QPointF(event.position())
        if self._dragging:
            self._pan += position - self._drag_from
            self._drag_from = position
            self.update()
            return
        point = self.to_image(position)
        self.hovered.emit(point.x(), point.y())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._dragging:
            self._dragging = False
            self.unsetCursor()

    # -- painting ---------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self._palette["bg"]))

        pixmap = self._pixmap()
        if pixmap is None:
            painter.setPen(QColor(self._palette["faint"]))
            painter.drawText(
                self.rect(), Qt.AlignCenter,
                "No frame to show.\n\n"
                "The capture ran but its image could not be read.\n"
                "Look in debug/teach for what it wrote.")
            painter.end()
            return

        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setTransform(self._transform())
        # Nearest-neighbour above 1:1 -- a smoothed pixel edge would misrepresent
        # where a threshold actually put the boundary.
        painter.setRenderHint(QPainter.SmoothPixmapTransform, self._zoom < 1.0)
        painter.drawPixmap(0, 0, pixmap)

        painter.setRenderHint(QPainter.Antialiasing, True)
        hair = max(1.0 / max(self._zoom, 0.01), 0.05)

        if self._show_contours and self._polygons:
            painter.setPen(QPen(QColor(self._palette["accent"]), hair))
            painter.setBrush(Qt.NoBrush)
            for polygon in self._polygons:
                painter.drawPolygon(polygon)

        self._paint_sites(painter, hair)
        painter.end()

    def _paint_sites(self, painter: QPainter, hair: float) -> None:
        pal = self._palette
        for index, site in enumerate(self._sites):
            current = index == self._current
            taught = site.taught is not None

            if self._show_windows:
                # The window as the table has it now: this is what the test
                # searches today, so seeing it empty is the diagnosis.
                colour = QColor(pal["accent"] if current else pal["faint"])
                colour.setAlpha(230 if current else 90)
                painter.setPen(QPen(colour, hair * (2 if current else 1),
                                    Qt.DashLine))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(QRectF(site.cx - site.tol, site.cy - site.tol,
                                        site.tol * 2, site.tol * 2))

            if taught:
                cx, cy = site.taught
                ok = site.within_tolerance
                colour = QColor(pal["pass"] if ok else pal["warn"])
                painter.setPen(QPen(colour, hair * 2))
                painter.setBrush(QBrush(QColor(colour.red(), colour.green(),
                                               colour.blue(), 70)))
                radius = max(site.tol * 0.55, 4)
                painter.drawEllipse(QPointF(cx, cy), radius, radius)
                painter.setPen(QPen(colour, hair * 2))
                painter.drawLine(QPointF(cx - radius * 1.6, cy),
                                 QPointF(cx + radius * 1.6, cy))
                painter.drawLine(QPointF(cx, cy - radius * 1.6),
                                 QPointF(cx, cy + radius * 1.6))
                if (cx, cy) != (site.cx, site.cy):
                    # The move itself, drawn. A field of parallel arrows is the
                    # signature of a camera that shifted; one odd arrow is a
                    # site that was mis-taught.
                    painter.setPen(QPen(QColor(pal["warn"]), hair,
                                        Qt.DotLine))
                    painter.drawLine(QPointF(site.cx, site.cy), QPointF(cx, cy))

            if current:
                painter.setPen(QPen(QColor(pal["accent"]), hair * 2))
                painter.setBrush(Qt.NoBrush)
                reach = site.tol * 2.2
                painter.drawEllipse(QPointF(site.cx, site.cy), reach, reach)


class TeachWindow(QMainWindow):
    """Teach every coordinate site in a program, then write the file."""

    def __init__(self, sites: list, capture, notes: list[str],
                 meta: dict, out_path: str, dark: bool = True,
                 program=None, parent=None) -> None:
        super().__init__(parent)
        self.sites = sites
        self.capture = capture
        self.program = program
        self.notes = list(notes)
        self.meta = dict(meta)
        self.out_path = out_path
        self.dark = dark
        self.palette_ = theme.palette(dark)
        self._free_form = not sites
        self._saved_to = ""

        self.setWindowTitle(f"NGWART -- teach coordinates "
                            f"[{meta.get('capture_program', '')}]")
        self.setStyleSheet(theme.stylesheet(dark))
        self.resize(1360, 860)

        self._build()
        self._reload_table()
        self._select(0 if self.sites else -1)
        self._announce()

    # -- construction -----------------------------------------------------

    def _build(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(*(theme.SPACE["md"],) * 4)
        layout.setSpacing(theme.SPACE["md"])

        layout.addWidget(self._build_canvas(), 3)
        layout.addWidget(self._build_side(), 2)
        self.setCentralWidget(central)
        self._build_menus()

    def _build_canvas(self) -> QWidget:
        card = Card("Capture")

        bar = QHBoxLayout()
        bar.setSpacing(theme.SPACE["sm"])

        self.view_pick = QComboBox()
        # Binary first, and the default: it is what the contours were traced
        # from, so it is what decides whether a blob is clickable at all.
        self.view_pick.addItem("Binary (thresholded)", "binary")
        self.view_pick.addItem("Capture", "frame")
        self.view_pick.currentIndexChanged.connect(
            lambda: self.canvas.set_view(self.view_pick.currentData()))
        bar.addWidget(QLabel("View"))
        bar.addWidget(self.view_pick)

        # A product program captures several times -- cargo.ods takes eight,
        # with different boards powered and different thresholds. Which one is
        # on screen decides which sites have anything to click, so it is a
        # control, not a detail.
        self.capture_pick = QComboBox()
        self.capture_pick.setVisible(False)
        self.capture_pick.currentIndexChanged.connect(self._choose_capture)
        self.capture_label = QLabel("Capture")
        self.capture_label.setVisible(False)
        bar.addWidget(self.capture_label)
        bar.addWidget(self.capture_pick)

        self.show_contours = QCheckBox("Contours")
        self.show_contours.setChecked(True)
        self.show_contours.toggled.connect(self.canvas_show_contours)
        bar.addWidget(self.show_contours)

        self.show_windows = QCheckBox("Search windows")
        self.show_windows.setChecked(True)
        self.show_windows.toggled.connect(self.canvas_show_windows)
        bar.addWidget(self.show_windows)

        bar.addStretch(1)
        self.cursor_label = QLabel("--")
        self.cursor_label.setStyleSheet(
            f"color:{self.palette_['muted']}; font-family:{theme.MONO};")
        bar.addWidget(self.cursor_label)
        card.add_layout(bar)

        self.canvas = ImageCanvas(self.palette_)
        self.canvas.picked.connect(self._on_pick)
        self.canvas.hovered.connect(self._on_hover)
        card.add(self.canvas, 1)

        self.hint = QLabel(
            "Click a contour to teach the selected site. "
            "Wheel zooms, right-drag pans.")
        self.hint.setStyleSheet(f"color:{self.palette_['faint']};")
        card.add(self.hint)
        return card

    def canvas_show_contours(self, on: bool) -> None:
        self.canvas.set_show_contours(on)

    def canvas_show_windows(self, on: bool) -> None:
        self.canvas.set_show_windows(on)

    def _build_side(self) -> QWidget:
        card = Card("Sites")

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["UUT", "Test", "Table", "Taught", "Δ", "Area"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for column in (0, 2, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        self.table.itemChanged.connect(self._on_item_changed)
        # Double-click to go to a site. Explicit, because the view moving on its
        # own is the one thing that makes this window hard to work in.
        self.table.itemDoubleClicked.connect(
            lambda _item: self._centre_current())
        self.table.setToolTip(
            "Double-click a row to centre the view on it. Ctrl+G does the same.")
        card.add(self.table, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(theme.SPACE["sm"])
        self.clear_button = QPushButton("Clear site")
        self.clear_button.clicked.connect(self._clear_current)
        buttons.addWidget(self.clear_button)
        self.next_button = QPushButton("Next untaught")
        self.next_button.clicked.connect(self._advance)
        buttons.addWidget(self.next_button)
        buttons.addStretch(1)
        card.add_layout(buttons)

        # "Run" is the design system's affirmative-action style; this window's
        # affirmative action is writing the file.
        self.save_button = QPushButton("Save coordinates")
        self.save_button.setObjectName("Run")
        self.save_button.clicked.connect(self.save)
        card.add(self.save_button)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{self.palette_['muted']};")
        card.add(self.status)

        if self.notes:
            warn = QLabel("\n".join(f"• {n}" for n in self.notes))
            warn.setWordWrap(True)
            warn.setStyleSheet(f"color:{self.palette_['warn']};")
            card.add(warn)
        return card

    def _build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        self._action(file_menu, "&Save coordinates", self.save, QKeySequence.Save)
        self._action(file_menu, "Save &as...", self.save_as)
        file_menu.addSeparator()
        self._action(file_menu, "&Close", self.close, QKeySequence.Close)

        view_menu = bar.addMenu("&View")
        self._action(view_menu, "Zoom &in", lambda: self.canvas.zoom_by(1.25),
                     QKeySequence.ZoomIn)
        self._action(view_menu, "Zoom &out", lambda: self.canvas.zoom_by(0.8),
                     QKeySequence.ZoomOut)
        self._action(view_menu, "&Fit", self.canvas.fit, "Ctrl+0")
        self._action(view_menu, "Centre on selected site", self._centre_current,
                     "Ctrl+G")

    def _action(self, menu, text, slot, shortcut=None) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(slot)
        if shortcut:
            action.setShortcut(shortcut)
        menu.addAction(action)
        self.addAction(action)
        return action

    # -- data -------------------------------------------------------------

    def set_capture(self, frame=None, binary=None, contours=None) -> None:
        self.canvas.set_images(frame=frame, binary=binary)
        self.canvas.set_contours(contours or [])
        width, height = self.canvas.size_hint_image
        self.meta["frame"] = {"width": width, "height": height}
        self._announce()

    def offer_captures(self, context) -> None:
        """Let the operator switch between a program's several captures.

        Everything a run captured is still in its data store, so switching is a
        re-read rather than another picture. Without this, a table that captures
        per board pair can only ever teach the pair that happened to be lit in
        the first frame.
        """
        from .. import teach as teachlib

        if self.program is None or context is None:
            return
        rows = teachlib.contour_rows(self.program)
        if len(rows) < 2:
            return

        self._context = context
        self.capture_pick.blockSignals(True)
        self.capture_pick.clear()
        for row in rows:
            name = row.raw(4) or row.raw(2) or f"row {row.index}"
            threshold = row.raw(6)
            self.capture_pick.addItem(
                f"{name}" + (f"  (thr {threshold})" if threshold else ""),
                row.index)
        self.capture_pick.blockSignals(False)
        self.capture_pick.setVisible(True)
        self.capture_label.setVisible(True)

    def _choose_capture(self, index: int) -> None:
        from .. import teach as teachlib

        context = getattr(self, "_context", None)
        if context is None or index < 0:
            return
        row_index = self.capture_pick.itemData(index)
        try:
            capture = teachlib.capture_from_context(
                self.program, context, row_index=row_index)
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"Could not read that capture: {exc}")
            return
        self.capture = capture
        self.set_capture(frame=capture.frame, binary=capture.binary,
                         contours=capture.contours)

    def _reload_table(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.sites))
        for index, site in enumerate(self.sites):
            self._fill_row(index, site)
        self.table.blockSignals(False)
        self.canvas.set_sites(self.sites, self._current_index())

    def _fill_row(self, index: int, site) -> None:
        taught = site.taught
        delta = site.delta
        values = [
            "--" if site.uut is None else str(site.uut),
            site.name,
            f"{site.cx},{site.cy}",
            f"{taught[0]},{taught[1]}" if taught else "",
            f"{delta[0]:+d},{delta[1]:+d}" if delta else "",
            f"{site.area:.0f}" if site.area else "",
        ]
        for column, text in enumerate(values):
            item = self.table.item(index, column)
            if item is None:
                item = QTableWidgetItem()
                self.table.setItem(index, column, item)
            item.setText(text)
            # Only a free-form site's name is the operator's to write; a name
            # taken from the table is how phase 2 finds the row again.
            editable = self._free_form and column == 1
            item.setFlags(
                (Qt.ItemIsEnabled | Qt.ItemIsSelectable |
                 (Qt.ItemIsEditable if editable else Qt.NoItemFlags)))
            if column in (2, 3, 4, 5):
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                item.setFont(QFont(theme.MONO.split(",")[0]))

        tone = "faint"
        if site.taught is not None:
            tone = "pass" if site.within_tolerance else "warn"
        colour = QColor(self.palette_[tone])
        for column in range(self.table.columnCount()):
            self.table.item(index, column).setForeground(colour)

    def _current_index(self) -> int:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return rows[0].row() if rows else -1

    def _select(self, index: int) -> None:
        if 0 <= index < len(self.sites):
            self.table.selectRow(index)
        self.canvas.set_sites(self.sites, self._current_index())

    # -- interaction ------------------------------------------------------

    def _on_row_selected(self) -> None:
        self.canvas.set_sites(self.sites, self._current_index())
        self._announce()

    def _on_item_changed(self, item) -> None:
        if not self._free_form or item.column() != 1:
            return
        index = item.row()
        if 0 <= index < len(self.sites):
            self.sites[index].note = item.text().strip()

    def _on_hover(self, x: float, y: float) -> None:
        self.cursor_label.setText(f"{int(x)}, {int(y)}")

    def _on_pick(self, cx: int, cy: int, area: float) -> None:
        index = self._current_index()

        if self._free_form:
            # No table to teach against, so each click is a new site. Recording
            # `was` as the clicked point keeps the delta honest at zero rather
            # than inventing a drift against a coordinate nobody declared.
            site = teachlib.Site(uut=None, cx=cx, cy=cy, tol=PICK_RADIUS / 4)
            site.teach(cx, cy, area)
            site.note = f"SITE_{len(self.sites) + 1}"
            self.sites.append(site)
            self._reload_table()
            self._select(len(self.sites) - 1)
            self._announce()
            return

        if index < 0:
            self.status.setText("Select a site in the list first.")
            return

        self.sites[index].teach(cx, cy, area)
        self.table.blockSignals(True)
        self._fill_row(index, self.sites[index])
        self.table.blockSignals(False)
        self.canvas.set_sites(self.sites, index)
        self._advance()
        self._announce()

    def _advance(self) -> None:
        """Move the selection to the next untaught site. Does not move the view.

        Selecting used to recentre and zoom, which sounds helpful and is not:
        neighbouring sites are a few pixels apart, so the operator is already
        looking at the right place and the image jumping out from under the
        cursor after every click is just disorienting. The view moves when
        asked -- Ctrl+G, or double-clicking a row -- and never on its own.
        """
        start = self._current_index()
        for offset in range(1, len(self.sites) + 1):
            index = (start + offset) % len(self.sites)
            if self.sites[index].taught is None:
                self._select(index)
                return
        self._announce()

    def _clear_current(self) -> None:
        index = self._current_index()
        if index < 0:
            return
        if self._free_form:
            self.sites.pop(index)
            self._reload_table()
            self._select(min(index, len(self.sites) - 1))
        else:
            self.sites[index].clear()
            self.table.blockSignals(True)
            self._fill_row(index, self.sites[index])
            self.table.blockSignals(False)
            self.canvas.set_sites(self.sites, index)
        self._announce()

    def _centre_current(self) -> None:
        index = self._current_index()
        if index < 0:
            return
        site = self.sites[index]
        # Enough magnification that a 10px window fills a usable part of the
        # panel, without leaving the operator unable to see its neighbours.
        target = max(self.canvas.height() / max(site.tol * 12, 1), 1.0)
        self.canvas.centre_on(site.cx, site.cy, min(target, 8.0))

    # -- output -----------------------------------------------------------

    def _announce(self) -> None:
        text = teachlib.summarise(self.sites)
        blobs = len(self.canvas.blobs)
        floor = self.canvas.noise_floor
        text += f"  {blobs} contour(s) at or above {floor}px."
        if floor < teachlib.MIN_CONTOUR_PIXELS:
            # Said out loud, because it is a deliberate relaxation of the
            # rule that stops a site being taught to a blob the test skips.
            text += (f"  Floor lowered from {teachlib.MIN_CONTOUR_PIXELS} "
                     f"for this calibration.")

        if self.capture_pick.isVisible() and self.sites:
            # Which sites this frame can actually teach. A capture taken with
            # one board pair powered has nothing to click for the other, and
            # silence about that reads as "these LEDs are dead".
            reach = max((s.tol for s in self.sites), default=40) * 4
            visible = sum(
                1 for s in self.sites
                if teachlib.blob_at(self.capture.contours, s.cx, s.cy, reach,
                                    self.canvas.noise_floor))
            text += (f"  {visible} of {len(self.sites)} site(s) have a contour "
                     f"in this capture.")
        if self._saved_to:
            text += f"  Saved to {self._saved_to}."
        self.status.setText(text)
        untaught = sum(1 for s in self.sites if s.taught is None)
        self.save_button.setEnabled(len(self.sites) > untaught)

    def save(self) -> None:
        self._write(self.out_path)

    def save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save coordinates", self.out_path, "Teach files (*.json)")
        if path:
            self.out_path = path
            self._write(path)

    def _write(self, path: str) -> None:
        taught = [s for s in self.sites if s.taught is not None]
        if not taught:
            QMessageBox.information(self, "Nothing to save",
                                    "No site has been taught yet.")
            return
        try:
            written = teachlib.save(path, self.sites, meta=self.meta,
                                    notes=self.notes, program=self.program)
        except OSError as exc:
            QMessageBox.critical(self, "Could not save", str(exc))
            return
        self._saved_to = os.path.abspath(written[0])
        untaught = [s.label for s in self.sites if s.taught is None]
        message = f"{len(taught)} site(s) taught.\n\n" + "\n".join(
            os.path.abspath(p) for p in written)
        if any(s.in_file for s in self.sites):
            message += ("\n\nThe first file is the one the program loads at "
                        "startup. The table itself is unchanged.")
        if untaught:
            # Named, not counted: a partial teach file is legitimate, but which
            # sites it leaves alone is the thing to know before applying it.
            listed = ", ".join(untaught[:6])
            more = f" and {len(untaught) - 6} more" if len(untaught) > 6 else ""
            message += (f"\n\n{len(untaught)} site(s) were left untaught and are "
                        f"not in the file: {listed}{more}.")
        QMessageBox.information(self, "Saved", message)
        self._announce()
