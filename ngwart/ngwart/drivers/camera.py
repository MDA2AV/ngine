"""Camera verbs -- registered as ``BaluffManager`` with ``CameraManager`` aliased.

v1 kept two near-identical modules, one per camera family, and a table chose
between them by editing its <Modules> line. That still works -- both names
resolve here -- but there is one implementation, and the backend picks the SDK
at open time.

Captured frames are stored in the data array as live numpy objects rather than
stringified, which is what the image-processing verbs then consume.
"""

from __future__ import annotations

import os

from ..engine.errors import HardwareError, VerbError
from ..engine.registry import p, verb
from .backends import make_camera

MODULE = "BaluffManager"
STATE = "camera"

#: Cameras the simulator pretends are attached.
SIM_CAMERAS = ["UB101256", "GX002467"]


def _cameras(ctx) -> dict:
    return ctx.driver_state(STATE).setdefault("cameras", {})


def _get(ctx, serial: str):
    cameras = _cameras(ctx)
    if serial in cameras:
        return cameras[serial]
    for key, cam in cameras.items():
        if serial and serial in key:
            return cam
    if ctx.simulate:
        cam = make_camera(True, serial)
        cam.open()
        cameras[serial] = cam
        ctx.log(f"Camera: simulating '{serial}'")
        return cam
    known = ", ".join(sorted(cameras)) or "none"
    raise HardwareError(f"camera '{serial}' is not open (known: {known})")


@verb(MODULE, "OPEN", params=[p(2, "serial")], config_only=True)
def open_camera(ctx, row):
    """Open one camera by serial (or serial substring)."""
    serial = ctx.text(row.raw(2))
    cam = make_camera(ctx.simulate, serial)
    cam.open()
    _cameras(ctx)[serial] = cam
    ctx.log(f"Camera {serial} opened.")


@verb(MODULE, "OPENALL", config_only=True)
def open_all(ctx, row):
    """Open every camera the system reports."""
    serials = SIM_CAMERAS if ctx.simulate else _enumerate_real()
    if not serials:
        ctx.log("Camera: none found", "warn")
        return
    for serial in serials:
        try:
            cam = make_camera(ctx.simulate, serial)
            cam.open()
            _cameras(ctx)[serial] = cam
            ctx.log(f"Camera {serial} opened.")
        except HardwareError as exc:
            ctx.log(f"Camera {serial}: {exc}", "warn")


def _enumerate_real() -> list[str]:
    try:
        from mvIMPACT import acquire  # type: ignore
    except ImportError:
        return []
    try:
        mgr = acquire.DeviceManager()
        return [mgr.getDevice(i).serial.read() for i in range(mgr.deviceCount())]
    except Exception:  # noqa: BLE001
        return []


@verb(MODULE, "SETPROPS",
      params=[p(2, "serial"),
              p(3, "buffer_wh", doc="buffersize,width,height"),
              p(4, "focus", required=False, doc="autofocus,focus"),
              p(5, "exposure", required=False, doc="autoexposure,exposure_us"),
              p(6, "image", required=False, doc="hue,saturation,brightness,temperature")])
def setprops(ctx, row):
    """Apply capture properties."""
    cam = _get(ctx, ctx.text(row.raw(2)))
    groups = {
        3: ("buffersize", "width", "height"),
        4: ("autofocus", "focus"),
        5: ("autoexposure", "exposure"),
        6: ("hue", "saturation", "brightness", "temperature"),
    }
    for column, names in groups.items():
        if not row.has(column):
            continue
        values = [v.strip() for v in ctx.text(row.raw(column)).split(",")]
        for name, value in zip(names, values):
            if value in ("", "-"):
                continue
            try:
                cam.set_property(name, float(value))
            except ValueError:
                raise VerbError(
                    f"SETPROPS: '{value}' is not a number for {name}") from None
    ctx.log(f"Camera {ctx.text(row.raw(2))} configured.")


@verb(MODULE, "SETEXPOSURE", params=[p(2, "serial"), p(3, "exposure_us")])
def set_exposure(ctx, row):
    """Set manual exposure in microseconds."""
    cam = _get(ctx, ctx.text(row.raw(2)))
    try:
        cam.set_property("exposure", float(ctx.text(row.raw(3))))
    except ValueError:
        raise VerbError(f"SETEXPOSURE: '{row.raw(3)}' is not a number") from None


@verb(MODULE, "CALIBRATEWB",
      params=[p(2, "serial"), p(3, "exposure_us", required=False),
              p(4, "warmup_frames", required=False)],
      config_only=True)
def calibrate_wb(ctx, row):
    """Grey-world white balance from a few warm-up frames."""
    serial = ctx.text(row.raw(2))
    cam = _get(ctx, serial)
    exposure = _opt_float(ctx, row.raw(3), 20000.0)
    warmup = int(_opt_float(ctx, row.raw(4), 5.0))
    cam.set_property("exposure", exposure)

    try:
        import numpy as np
    except ImportError as exc:
        raise VerbError("CALIBRATEWB needs numpy") from exc

    means = []
    for _ in range(max(warmup, 1)):
        frame = cam.capture()
        means.append(np.asarray(frame, dtype=float).reshape(-1, 3).mean(axis=0))
    mean = np.mean(means, axis=0)
    grey = float(mean.mean())
    if grey <= 0:
        raise VerbError(f"CALIBRATEWB: camera {serial} returned a black image")
    gains = [grey / m if m > 0 else 1.0 for m in mean]
    cam.set_property("wb_blue", gains[0])
    cam.set_property("wb_red", gains[2])
    ctx.driver_state(STATE).setdefault("wb", {})[serial] = gains
    ctx.log(f"Camera {serial} white balance: "
            f"B={gains[0]:.3f} G={gains[1]:.3f} R={gains[2]:.3f}")


@verb(MODULE, "CAPTURE",
      params=[p(2, "serial"), p(3, "path", required=False),
              p(4, "dest", required=False)])
def capture(ctx, row):
    """Grab a frame; save it, store it in the data array, or both."""
    serial = ctx.text(row.raw(2))
    cam = _get(ctx, serial)
    frame = cam.capture()

    if row.has(3):
        path = ctx.text(row.raw(3))
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        _imwrite(path, frame)
        ctx.log(f"Capture saved to {path}")

    if row.has(4):
        # Frames stay live objects; stringifying them (v1's default path) would
        # turn a megabyte image into the text "[[[18 18 18] ...".
        ctx.set_data(row.raw(4), frame, stringify=False)

    if not row.has(3) and not row.has(4):
        raise VerbError("CAPTURE: give a path, a destination index, or both")


def _imwrite(path: str, frame) -> None:
    try:
        import cv2
    except ImportError as exc:
        raise VerbError("saving images needs OpenCV -- pip install opencv-python") from exc
    if not cv2.imwrite(path, frame):
        raise VerbError(f"could not write image to '{path}'")


def _opt_float(ctx, cell: str, default: float) -> float:
    text = ctx.text(cell)
    if not text or text == "-":
        return default
    try:
        return float(text)
    except ValueError:
        raise VerbError(f"'{text}' is not a number") from None


from ..engine.registry import REGISTRY  # noqa: E402

REGISTRY.alias_module("CameraManager", MODULE)
REGISTRY.alias_module("Camera", MODULE)
