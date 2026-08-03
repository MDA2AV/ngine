"""Hold the fixture powered while the camera is adjusted by hand.

Aiming a camera and setting focus are physical jobs: the board has to stay lit,
and the frame has to be re-taken after every small movement. A run that powers
up, captures once and tears down is useless for that -- by the time the frame
is on screen the indicators are dark again.

So this keeps the run's context alive. The supply stays on and the ports stay
open until Done, and Capture again re-takes the picture without powering
anything a second time.

The number next to it is the variance of the frame's Laplacian, which rises as
focus improves. Its absolute value means nothing; watching it peak while
turning the ring is a judgement an operator can make reliably, and "does that
look sharper" through a fixture window is not.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QWidget)

from .. import calibration as cal
from . import theme
from .calibration_window import ImageCanvas
from .widgets import Card


class FocusWindow(QMainWindow):
    """A live-ish view of the frame, while the fixture stays powered."""

    def __init__(self, title: str, dark: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.palette_ = theme.palette(dark)
        self.setWindowTitle(f"NGWART -- {title}")
        self.resize(1100, 780)
        self.setStyleSheet(theme.stylesheet(dark))

        #: Set by the station: called on Capture again / Done.
        self.on_refresh = None
        self.on_done = None

        self._best = 0.0
        self._last = None
        self._shots = 0

        card = Card(title)

        bar = QHBoxLayout()
        bar.setSpacing(theme.SPACE["sm"])

        self.refresh_button = QPushButton("Capture again")
        self.refresh_button.setShortcut("Space")
        self.refresh_button.setToolTip(
            "Re-take the picture. The fixture stays powered, so this is the "
            "one to press after every small adjustment. (Space)")
        self.refresh_button.clicked.connect(self._refresh)
        bar.addWidget(self.refresh_button)

        self.sharp = QLabel("--")
        self.sharp.setStyleSheet(
            f"color:{self.palette_['text']}; font-family:{theme.MONO};")
        bar.addWidget(self.sharp)
        bar.addStretch(1)

        self.done_button = QPushButton("Done — power down")
        self.done_button.setObjectName("Stop")
        self.done_button.setToolTip(
            "Run <Teardown> and release the ports. Until this, the fixture "
            "stays powered.")
        self.done_button.clicked.connect(self._done)
        bar.addWidget(self.done_button)
        card.add_layout(bar)

        self.canvas = ImageCanvas(self.palette_)
        card.add(self.canvas, 1)

        self.status = QLabel(
            "The fixture is powered. Adjust the camera, press Capture again, "
            "and watch the sharpness figure — higher is sharper.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{self.palette_['muted']};")
        card.add(self.status)

        self.setCentralWidget(card)

    # -- content ----------------------------------------------------------

    def show_frame(self, frame, binary=None, contours=None) -> None:
        self.canvas.set_images(frame=frame, binary=binary)
        self.canvas.set_contours(contours or [])
        self._shots += 1

        value = cal.sharpness(frame if frame is not None else binary)
        trend = ""
        if self._last is not None:
            change = value - self._last
            # Only the direction matters, so that is what is said.
            trend = ("  sharper" if change > self._last * 0.01 else
                     "  softer" if change < -self._last * 0.01 else "  no change")
        best = ""
        if value > self._best:
            self._best = value
            best = "   <-- best so far"
        elif self._best:
            best = f"   best {self._best:,.0f}"

        self._last = value
        self.sharp.setText(f"sharpness {value:,.0f}{trend}{best}")
        self.status.setText(
            f"{self._shots} frame(s). {len(self.canvas.blobs)} contour(s) above "
            f"the {cal.MIN_CONTOUR_PIXELS}px floor. The fixture is still "
            f"powered — press Done when the camera is where you want it.")

    def set_busy(self, busy: bool) -> None:
        self.refresh_button.setEnabled(not busy)
        self.done_button.setEnabled(not busy)
        if busy:
            self.status.setText("Capturing…")

    # -- actions ----------------------------------------------------------

    def _refresh(self) -> None:
        if callable(self.on_refresh):
            self.on_refresh()

    def _done(self) -> None:
        if callable(self.on_done):
            self.on_done()
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt name
        # Closing the window is not a reason to leave a supply at 13.5 V.
        if callable(self.on_done):
            self.on_done()
        super().closeEvent(event)
