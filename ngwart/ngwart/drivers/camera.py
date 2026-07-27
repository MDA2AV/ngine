"""Camera verbs -- registered as ``BaluffManager`` with ``CameraManager`` aliased.

v1 kept two near-identical modules, one per camera family, and a table chose
between them by editing its <Modules> line. Both names still resolve here, and
the backend picks the SDK at open time.

The verbs talk to the backend through ``configure`` / ``calibrate_white_balance``
/ ``set_exposure`` rather than a generic ``set_property(name, value)``. That
distinction matters: binning, a centred AOI and the User1 white-balance set
cannot be expressed as independent scalar properties, and pretending otherwise
is how a camera ends up capturing a perfectly good image of the wrong pixels.
"""

from __future__ import annotations

import os

from ..engine.errors import HardwareError, VerbError
from ..engine.registry import REGISTRY, p, verb
from .backends import make_camera

MODULE = "BaluffManager"
STATE = "camera"

#: Cameras the simulator pretends are attached.
SIM_CAMERAS = ["UB101256", "GX002467"]

#: SETPROPS packs its values into four comma-separated groups.
_PROP_GROUPS = {
    3: ("buffersize", "width", "height"),
    4: ("autofocus", "focus"),
    5: ("autoexposure", "exposure"),
    6: ("hue", "saturation", "brightness", "temperature"),
}


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


def _open(ctx, serial: str):
    """Open a camera, tolerating a backend that opened it during construction."""
    cam = make_camera(ctx.simulate, serial)
    if not getattr(cam, "is_open", False):
        cam.open()
    _cameras(ctx)[serial] = cam
    return cam


@verb(MODULE, "OPEN", params=[p(2, "serial")], config_only=True)
def open_camera(ctx, row):
    """Open one camera by serial (or serial substring)."""
    serial = ctx.text(row.raw(2))
    _open(ctx, serial)
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
            _open(ctx, serial)
            ctx.log(f"Camera {serial} opened.")
        except HardwareError as exc:
            ctx.log(f"Camera {serial}: {exc}", "warn")


def _enumerate_real() -> list[str]:
    """List attached Balluff serials.

    Uses the shared, module-scope DeviceManager. A local one would unload the
    driver stack when it went out of scope, invalidating handles OPEN returned.
    """
    try:
        from .backends.real import _device_manager
        mgr = _device_manager()
        return [mgr.getDevice(i).serial.read() for i in range(mgr.deviceCount())]
    except ImportError:
        return []
    except Exception:  # noqa: BLE001
        return []


@verb(MODULE, "SETPROPS",
      params=[p(2, "serial"),
              p(3, "buffer_wh", doc="buffersize,width,height"),
              p(4, "focus", required=False, doc="autofocus,focus"),
              p(5, "exposure", required=False, doc="autoexposure,exposure_us"),
              p(6, "image", required=False,
                doc="hue,saturation,brightness,temperature")])
def setprops(ctx, row):
    """Apply capture properties.

    Fails if the backend could not apply something it was asked for. A property
    that silently does not stick leaves the camera at its default geometry,
    which still produces a good-looking image of the wrong pixels -- and then
    every coordinate in the program misses, with nothing in the log to say why.

    Properties the sensor genuinely does not have (focus and hue on a BlueFOX)
    are reported as notes rather than failures, because v1 ignores them too.
    """
    serial = ctx.text(row.raw(2))
    cam = _get(ctx, serial)

    props: dict = {}
    for column, names in _PROP_GROUPS.items():
        if not row.has(column):
            continue
        values = [v.strip() for v in ctx.text(row.raw(column)).split(",")]
        for name, value in zip(names, values):
            if value in ("", "-"):
                continue
            try:
                props[name] = float(value)
            except ValueError:
                raise VerbError(
                    f"SETPROPS: '{value}' is not a number for {name}") from None

    result = cam.configure(props)
    for note in result.get("notes", []):
        ctx.log(f"Camera {serial}: {note}")
    if result.get("ignored"):
        raise VerbError(
            f"SETPROPS: camera {serial} could not apply "
            f"{', '.join(result['ignored'])}. The frame geometry would not match "
            f"what the program expects."
        )

    summary = ", ".join(f"{k}={v}" for k, v in result.get("applied", {}).items())
    ctx.log(f"Camera {serial} configured: {summary or 'nothing to do'}")


@verb(MODULE, "SETEXPOSURE", params=[p(2, "serial"), p(3, "exposure_us")])
def set_exposure(ctx, row):
    """Set manual exposure in microseconds, clamped to the sensor's range."""
    serial = ctx.text(row.raw(2))
    cam = _get(ctx, serial)
    try:
        wanted = float(ctx.text(row.raw(3)))
    except ValueError:
        raise VerbError(f"SETEXPOSURE: '{row.raw(3)}' is not a number") from None
    applied = cam.set_exposure(wanted)
    if applied != wanted:
        ctx.log(f"Camera {serial}: exposure {wanted}us clamped to {applied}us",
                "warn")
    else:
        ctx.log(f"Camera {serial}: exposure {applied}us")


@verb(MODULE, "CALIBRATEWB",
      params=[p(2, "serial"), p(3, "exposure_us", required=False),
              p(4, "warmup_frames", required=False)],
      config_only=True)
def calibrate_wb(ctx, row):
    """Calibrate white balance once and lock the gains.

    Run against a well-lit neutral reference. CAPTURE then reuses these gains on
    every frame instead of recalibrating -- grey-world auto-WB on a mostly-black
    inspection frame computes gains of ~1.0, i.e. no correction at all.
    """
    serial = ctx.text(row.raw(2))
    cam = _get(ctx, serial)
    exposure = _opt_float(ctx, row.raw(3), 20000.0)
    warmup = int(_opt_float(ctx, row.raw(4), 5.0))

    red, green, blue = cam.calibrate_white_balance(exposure, warmup)
    ctx.driver_state(STATE).setdefault("wb", {})[serial] = (red, green, blue)
    ctx.log(f"Camera {serial} WB calibrated: "
            f"R={red:.2f} G={green:.2f} B={blue:.2f}")

    # Neutral gains mean the reference was too dark to measure anything, so the
    # calibration was a no-op and any colour cast is still there.
    if abs(red - 1.0) < 0.02 and abs(blue - 1.0) < 0.02:
        ctx.log(f"Camera {serial}: WB gains are ~1.0 -- the reference was too "
                f"dark to measure. Calibrate on a brighter white target.", "warn")


@verb(MODULE, "CAPTURE",
      params=[p(2, "serial"), p(3, "path", required=False),
              p(4, "dest", required=False)])
def capture(ctx, row):
    """Grab a frame; save it, store it in the data array, or both."""
    serial = ctx.text(row.raw(2))
    cam = _get(ctx, serial)
    frame = cam.capture()
    shape = getattr(frame, "shape", None)
    ctx.log(f"Camera {serial} captured {shape}")

    gains = cam.white_balance_gains()
    if gains:
        ctx.log(f"Camera {serial} WB gains: "
                f"R={gains[0]:.2f} G={gains[1]:.2f} B={gains[2]:.2f}")

    if ctx.debug:
        ctx.debug.save_image(f"capture_{serial}", frame, row.index)
        ctx.debug.note(f"row {row.index} CAPTURE {serial}: shape={shape}")

    if row.has(3):
        path = ctx.text(row.raw(3))
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        _imwrite(path, frame)
        ctx.log(f"Capture saved to {path}")

    if row.has(4):
        # Frames stay live objects; stringifying them would turn a megabyte
        # image into the text "[[[18 18 18] ...".
        ctx.set_data(row.raw(4), frame, stringify=False)

    if not row.has(3) and not row.has(4):
        raise VerbError("CAPTURE: give a path, a destination index, or both")


def _imwrite(path: str, frame) -> None:
    try:
        import cv2
    except ImportError as exc:
        raise VerbError(
            "saving images needs OpenCV -- pip install opencv-python") from exc
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


REGISTRY.alias_module("CameraManager", MODULE)
REGISTRY.alias_module("Camera", MODULE)
