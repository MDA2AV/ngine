"""Hold the fixture powered while the camera is adjusted by hand.

Aiming a camera and setting focus are physical jobs: the board has to stay lit,
and the frame has to be re-taken after every small movement. A run that powers
up, captures once and tears down is useless for that -- by the time the frame
is on screen the indicators are dark again.

So this keeps the run's context alive -- supply on, ports open, teardown
deferred -- and streams the camera straight into the window at the exposure
and threshold the test itself uses. What is on screen while the lens is being
turned is what the test will see.

Beside it is the variance of the frame's Laplacian, which rises as focus
improves. Its absolute value means nothing; watching it peak while turning the
ring is a judgement an operator can make reliably, and "does that look
sharper" through a fixture window is not.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QWidget)

from .. import calibration as cal
from . import theme
from .calibration_window import ImageCanvas
from .widgets import Card


class FrameStreamer(QThread):
    """Grabs frames from a live camera and pushes them at the window.

    On its own thread because a grab is tens of milliseconds of USB transfer,
    and doing that on the GUI thread would stutter the very display someone is
    watching while they turn a focus ring.

    It goes straight to the camera rather than through the sequencer: a run
    validates a program, clears grids and emits a whole result cycle, none of
    which belongs in a viewfinder refreshing four times a second.
    """

    #: colour frame, thresholded frame, contours
    frame = Signal(object, object, object)
    failed = Signal(str)

    def __init__(self, camera, exposure_us: float, threshold: float,
                 interval_s: float = 0.25, parent=None) -> None:
        super().__init__(parent)
        self.camera = camera
        self.exposure_us = exposure_us
        self.threshold = threshold
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._paused = threading.Event()

    def stop(self) -> None:
        self._stop.set()
        self.wait(3000)

    def set_paused(self, paused: bool) -> None:
        self._paused.set() if paused else self._paused.clear()

    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.failed.emit("streaming needs OpenCV and numpy")
            return

        try:
            self.camera.set_exposure(float(self.exposure_us))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"cannot set exposure: {exc}")
            return

        while not self._stop.is_set():
            if self._paused.is_set():
                self._stop.wait(0.1)
                continue
            try:
                image = self.camera.capture()
                grey = image if image.ndim == 2 else cv2.cvtColor(
                    image, cv2.COLOR_BGR2GRAY)
                _, binary = cv2.threshold(grey, float(self.threshold), 255,
                                          cv2.THRESH_BINARY)
                contours, _ = cv2.findContours(binary.astype(np.uint8),
                                               cv2.RETR_TREE,
                                               cv2.CHAIN_APPROX_NONE)
                self.frame.emit(image, binary, list(contours))
            except Exception as exc:  # noqa: BLE001
                # One bad grab must not end the stream -- a camera being
                # physically handled drops frames, which is exactly when this
                # window is in use.
                self.failed.emit(str(exc))
                self._stop.wait(0.5)
                continue
            self._stop.wait(self.interval_s)


class FocusWindow(QMainWindow):
    """A live-ish view of the frame, while the fixture stays powered."""

    def __init__(self, title: str, dark: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.palette_ = theme.palette(dark)
        self.setWindowTitle(f"NGWART -- {title}")
        self.resize(1100, 780)
        self.setStyleSheet(theme.stylesheet(dark))

        #: Set by the station: called when the operator is finished.
        self.on_done = None

        self._best = 0.0
        self._last = None
        self._shots = 0
        self._streamer = None
        self._started = None

        card = Card(title)

        bar = QHBoxLayout()
        bar.setSpacing(theme.SPACE["sm"])

        self.pause_button = QPushButton("Pause")
        self.pause_button.setCheckable(True)
        self.pause_button.setShortcut("Space")
        self.pause_button.setToolTip(
            "Hold the last frame, to look at it without it changing "
            "underneath you. (Space)")
        self.pause_button.toggled.connect(self._pause)
        bar.addWidget(self.pause_button)

        self.fps = QLabel("--")
        self.fps.setStyleSheet(
            f"color:{self.palette_['muted']}; font-family:{theme.MONO};")
        bar.addWidget(self.fps)

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
            "The fixture is powered and the camera is streaming. Adjust it "
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
        import time

        now = time.monotonic()
        if self._started is None:
            self._started = now
        elapsed = max(now - self._started, 1e-6)
        self.fps.setText(f"{self._shots / elapsed:.1f} fps")
        self.status.setText(
            f"{self._shots} frame(s). {len(self.canvas.blobs)} contour(s) above "
            f"the {cal.MIN_CONTOUR_PIXELS}px floor. The fixture is still "
            f"powered — press Done when the camera is where you want it.")

    # -- streaming --------------------------------------------------------

    def start_stream(self, camera, exposure_us: float, threshold: float) -> None:
        """Begin a live view. Safe to call when there is no camera."""
        self.stop_stream()
        if camera is None:
            self.status.setText(
                "No camera in the run's context -- nothing to stream.")
            return
        self._streamer = FrameStreamer(camera, exposure_us, threshold,
                                       parent=self)
        self._streamer.frame.connect(self._on_stream_frame)
        self._streamer.failed.connect(self._on_stream_error)
        self._streamer.start()

    def stop_stream(self) -> None:
        """Always before anything else touches the camera.

        Teardown sets the exposure back, and two threads driving one camera is
        how a vendor SDK crashes rather than raises.
        """
        streamer, self._streamer = self._streamer, None
        if streamer is not None:
            streamer.stop()

    def _pause(self, paused: bool) -> None:
        self.pause_button.setText("Resume" if paused else "Pause")
        if self._streamer is not None:
            self._streamer.set_paused(paused)

    def _on_stream_frame(self, image, binary, contours) -> None:
        self.show_frame(image, binary, contours)

    def _on_stream_error(self, message: str) -> None:
        self.status.setText(f"Stream: {message}")

    # -- actions ----------------------------------------------------------

    def _done(self) -> None:
        self.stop_stream()
        if callable(self.on_done):
            self.on_done()
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt name
        # Stop first: teardown restores the exposure, and two threads on
        # one camera is how a vendor SDK crashes rather than raises.
        self.stop_stream()
        # Closing the window is not a reason to leave a supply at 13.5 V.
        if callable(self.on_done):
            self.on_done()
        super().closeEvent(event)
