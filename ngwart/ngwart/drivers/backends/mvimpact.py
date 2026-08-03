"""Balluff / MATRIX VISION camera via the mvIMPACT Acquire SDK.

A faithful port of the site's BaluffManager. The behaviour here was learned
against real hardware, and several details are not derivable from a datasheet:

* The DeviceManager must outlive every device handle. When the last one is
  collected the driver stack unloads and every open pDev / FunctionInterface
  becomes a dangling native pointer, so the next call crashes the process
  rather than raising. One is held at module scope in ``real.py``.

* WIDTH/HEIGHT are the desired **output** size, but the AOI is measured in
  full-sensor pixels and is independent of binning. Under 2x2 binning a
  1296x972 output therefore needs a 2592x1944 AOI, centred. The AOI is sticky
  between captures, hence the reset to full sensor first -- without it a
  smaller AOI set earlier silently persists and every coordinate in the test
  program lands somewhere else.

* White balance is calibrated once and the gains held in the User1 parameter
  set. Recalibrating per frame on a mostly-black inspection scene computes
  gains of ~1.0 -- no correction -- which is what leaves a green cast.

* A frame cannot be reshaped from channelCount. Packed formats carry a padding
  byte, so bytesPerPixel (4) != channelCount (3), and linePitch absorbs row
  padding. Reshaping on channelCount yields a skewed image that still looks
  plausible enough to be measured, which is the worst kind of wrong.

This module is imported only when mvIMPACT is present; ``real.py`` falls back
to OpenCV otherwise.
"""

from __future__ import annotations

from ...engine.errors import HardwareError


class MvImpactCamera:
    """One Balluff device, with the properties the fixture actually needs."""

    #: cbmBinningHV is 2x2.
    BIN_X = 2
    BIN_Y = 2

    #: Frames discarded before the kept one, so a pending WB calibration settles.
    WARMUP = 3

    #: Properties this sensor genuinely does not have. Ignoring them is correct
    #: -- v1 does the same -- so they must not be reported as a failure.
    NOT_APPLICABLE = ("autofocus", "focus", "hue")

    def __init__(self, serial: str, device_manager=None, **_kw) -> None:
        self.serial = serial
        self.buffersize = 4
        self._device_manager = device_manager
        self._acquire = None
        self._helper = None
        self._dev = None
        self._fi = None
        self._settings = None
        self._processing = None
        self._last_request = None

    # -- lifecycle --------------------------------------------------------

    def open(self) -> None:
        from mvIMPACT import acquire  # type: ignore
        from mvIMPACT.Common import exampleHelper  # type: ignore

        self._acquire, self._helper = acquire, exampleHelper
        mgr = self._device_manager
        if mgr is None:
            from .real import _device_manager
            mgr = _device_manager()

        for i in range(mgr.deviceCount()):
            candidate = mgr.getDevice(i)
            # Tables address cameras by a fragment of the serial ("UB101256"),
            # not the whole string.
            if not self.serial or self.serial in candidate.serial.read():
                if not candidate.isOpen:
                    candidate.open()
                self._dev = candidate
                self._fi = acquire.FunctionInterface(candidate)
                self._settings = acquire.CameraSettingsBlueFOX(candidate)
                self._processing = acquire.ImageProcessing(candidate)
                return
        raise HardwareError(f"no mvIMPACT camera matching serial '{self.serial}'")

    def close(self) -> None:
        # The device is deliberately left open. The shared DeviceManager owns the
        # driver stack for the process, and closing here would invalidate handles
        # another camera object may still hold.
        self._fi = None

    @property
    def is_open(self) -> bool:
        return self._dev is not None

    # -- configuration ----------------------------------------------------

    def configure(self, props: dict) -> dict:
        """Apply SETPROPS values.

        Returns ``{"applied": {...}, "ignored": [...], "notes": [...]}``.
        ``ignored`` means "this backend could not do it" and is treated as an
        error by the verb; ``notes`` covers things that legitimately do not
        apply to this sensor.
        """
        acquire, helper = self._acquire, self._helper
        cs, ip = self._settings, self._processing
        applied: dict = {}
        ignored: list[str] = []
        notes: list[str] = []

        if "buffersize" in props:
            self.buffersize = max(1, int(float(props["buffersize"])))
            applied["buffersize"] = self.buffersize

        helper.conditionalSetProperty(cs.binningMode, acquire.cbmBinningHV)

        width = int(float(props.get("width", 0) or 0))
        height = int(float(props.get("height", 0) or 0))
        try:
            max_w = cs.aoiWidth.getMaxValue()
            max_h = cs.aoiHeight.getMaxValue()
            # Clear any crop a previous SETPROPS left behind.
            helper.conditionalSetProperty(cs.aoiStartX, 0)
            helper.conditionalSetProperty(cs.aoiStartY, 0)
            helper.conditionalSetProperty(cs.aoiWidth, max_w)
            helper.conditionalSetProperty(cs.aoiHeight, max_h)

            if width > 0 and height > 0:
                aoi_w = min(width * self.BIN_X, max_w)
                aoi_h = min(height * self.BIN_Y, max_h)
                # Centre, aligned to the binning factor to satisfy the AOI step.
                start_x = ((max_w - aoi_w) // 2) // self.BIN_X * self.BIN_X
                start_y = ((max_h - aoi_h) // 2) // self.BIN_Y * self.BIN_Y
                helper.conditionalSetProperty(cs.aoiWidth, aoi_w)
                helper.conditionalSetProperty(cs.aoiHeight, aoi_h)
                helper.conditionalSetProperty(cs.aoiStartX, start_x)
                helper.conditionalSetProperty(cs.aoiStartY, start_y)
                applied["aoi"] = f"{aoi_w}x{aoi_h}@({start_x},{start_y})"
                applied["output"] = f"{aoi_w // self.BIN_X}x{aoi_h // self.BIN_Y}"
        except Exception as exc:  # noqa: BLE001
            ignored.append(f"width/height ({exc})")

        if "autoexposure" in props:
            auto = int(float(props["autoexposure"]))
            helper.conditionalSetProperty(cs.autoExposeControl, auto)
            applied["autoexposure"] = auto
            exposure = int(float(props.get("exposure", 0) or 0))
            if auto == 0 and exposure > 0:
                applied["exposure_us"] = self.set_exposure(exposure)

        if "brightness" in props:                       # -> sensor gain, in dB
            try:
                low = cs.gain_dB.getMinValue()
                high = cs.gain_dB.getMaxValue()
                value = max(low, min(high, float(props["brightness"])))
                cs.gain_dB.write(value)
                applied["gain_dB"] = value
            except Exception as exc:  # noqa: BLE001
                ignored.append(f"brightness ({exc})")

        if "saturation" in props:
            try:
                ip.setSaturation(float(props["saturation"]))
                applied["saturation"] = float(props["saturation"])
            except Exception as exc:  # noqa: BLE001
                ignored.append(f"saturation ({exc})")

        if float(props.get("temperature", 0) or 0) != 0:
            helper.conditionalSetProperty(ip.whiteBalanceCalibration,
                                          acquire.wbcmNextFrame)
            applied["wb_calibration"] = "next frame"

        for name in self.NOT_APPLICABLE:
            if float(props.get(name, 0) or 0) != 0:
                notes.append(f"{name} is not controllable on this sensor")

        return {"applied": applied, "ignored": ignored, "notes": notes}

    def set_exposure(self, microseconds: float) -> float:
        """Manual exposure, clamped to the sensor's range rather than dropped.

        Auto-exposure is turned off first; the driver ignores expose_us while it
        is on, so setting exposure without this silently does nothing.
        """
        cs, helper = self._settings, self._helper
        helper.conditionalSetProperty(cs.autoExposeControl, 0)
        value = int(microseconds)
        try:
            low, high = cs.expose_us.getMinValue(), cs.expose_us.getMaxValue()
            value = max(low, min(high, value))
        except Exception:  # noqa: BLE001
            pass
        cs.expose_us.write(value)
        return float(value)

    # -- white balance ----------------------------------------------------

    def calibrate_white_balance(self, exposure_us: float = 20000.0,
                                warmup: int = 5) -> tuple:
        """One-shot calibration; the gains are then locked in the User1 set.

        <Config> normally runs at a very low exposure, far too dark to measure
        white balance on. WB gains are exposure-independent ratios, so the
        exposure is raised for the calibration frames and restored afterwards.
        """
        acquire, helper = self._acquire, self._helper
        cs, ip, fi, dev = self._settings, self._processing, self._fi, self._dev
        if fi is None:
            raise HardwareError(f"camera {self.serial} is not open")

        previous_auto = cs.autoExposeControl.read()
        previous_exposure = cs.expose_us.read()

        helper.conditionalSetProperty(ip.colorProcessing, acquire.cpmAuto)
        helper.conditionalSetProperty(ip.whiteBalance, acquire.wbpUser1)
        self.set_exposure(exposure_us)
        helper.conditionalSetProperty(ip.whiteBalanceCalibration,
                                      acquire.wbcmNextFrame)

        for _ in range(4):
            if fi.imageRequestSingle() != acquire.DMR_NO_ERROR:
                break
        helper.manuallyStartAcquisitionIfNeeded(dev, fi)
        try:
            for _ in range(max(2, int(warmup))):
                number = fi.imageRequestWaitFor(10000)
                if not fi.isRequestNrValid(number):
                    raise HardwareError(
                        f"camera {self.serial}: imageRequestWaitFor failed "
                        f"({number}, "
                        f"{acquire.ImpactAcquireException.getErrorCodeAsString(number)})")
                fi.getRequest(number).unlock()
                fi.imageRequestSingle()
        finally:
            helper.manuallyStopAcquisitionIfNeeded(dev, fi)
            fi.imageRequestReset(0, 0)
            # Freeze the gains, and put the configured exposure state back.
            helper.conditionalSetProperty(ip.whiteBalanceCalibration,
                                          acquire.wbcmOff)
            helper.conditionalSetProperty(cs.autoExposeControl, previous_auto)
            if previous_auto == 0:
                cs.expose_us.write(previous_exposure)

        return self.white_balance_gains() or (1.0, 1.0, 1.0)

    def set_white_balance(self, red: float, green: float, blue: float) -> tuple:
        """Write gains straight into the User1 set, skipping calibration.

        Calibrating needs a neutral reference in view, which a fixture only has
        at one moment -- while the indicators are lit. Measuring once and
        applying the result every session is both more repeatable and possible
        at config time, where a grey-world pass would otherwise be looking at
        bare PCB and pulling green down to neutralise it.
        """
        acquire, helper = self._acquire, self._helper
        ip = self._processing
        if self._fi is None:
            raise HardwareError(f"camera {self.serial} is not open")
        helper.conditionalSetProperty(ip.colorProcessing, acquire.cpmAuto)
        helper.conditionalSetProperty(ip.whiteBalance, acquire.wbpUser1)
        wbs = ip.getWBUserSetting(0)
        wbs.redGain.write(float(red))
        wbs.greenGain.write(float(green))
        wbs.blueGain.write(float(blue))
        return (wbs.redGain.read(), wbs.greenGain.read(), wbs.blueGain.read())

    def white_balance_gains(self):
        """(red, green, blue) from the User1 set, or None."""
        try:
            wbs = self._processing.getWBUserSetting(0)
            return (wbs.redGain.read(), wbs.greenGain.read(), wbs.blueGain.read())
        except Exception:  # noqa: BLE001
            return None

    # -- capture ----------------------------------------------------------

    def capture(self):
        """Grab a frame, discarding a few so a pending calibration settles."""
        acquire, helper = self._acquire, self._helper
        fi, dev, ip = self._fi, self._dev, self._processing
        if fi is None:
            raise HardwareError(f"camera {self.serial} is not open")

        # Only make sure the pipeline applies the locked gains. Deliberately do
        # NOT recalibrate here -- see the module docstring.
        helper.conditionalSetProperty(ip.colorProcessing, acquire.cpmAuto)
        helper.conditionalSetProperty(ip.whiteBalance, acquire.wbpUser1)

        for _ in range(self.buffersize):
            if fi.imageRequestSingle() != acquire.DMR_NO_ERROR:
                break
        helper.manuallyStartAcquisitionIfNeeded(dev, fi)

        previous = kept = None
        try:
            for i in range(self.WARMUP):
                number = fi.imageRequestWaitFor(10000)
                if not fi.isRequestNrValid(number):
                    raise HardwareError(
                        f"camera {self.serial}: imageRequestWaitFor failed "
                        f"({number}, "
                        f"{acquire.ImpactAcquireException.getErrorCodeAsString(number)})")
                request = fi.getRequest(number)
                if not request.isOK:
                    request.unlock()
                    fi.imageRequestSingle()
                    continue
                if i == self.WARMUP - 1:
                    kept = request
                else:
                    if previous is not None:
                        previous.unlock()
                    previous = request
                    fi.imageRequestSingle()

            if kept is None:
                raise HardwareError(f"camera {self.serial}: no valid frame captured")
            frame = request_to_bgr(kept)
            self._save_with_sdk = kept.getImageBufferDesc()
            return frame
        finally:
            if previous is not None and previous is not kept:
                previous.unlock()
            if kept is not None:
                kept.unlock()
            helper.manuallyStopAcquisitionIfNeeded(dev, fi)
            fi.imageRequestReset(0, 0)      # drain, so the next capture is clean

    def set_property(self, name: str, value) -> bool:
        """Single-property form, for callers that do not use configure()."""
        if name == "exposure":
            self.set_exposure(float(value))
            return True
        result = self.configure({name: value})
        return bool(result["applied"]) and not result["ignored"]


def request_to_bgr(request):
    """Rebuild a frame from the buffer geometry the driver reports.

    Not from channelCount: packed colour formats carry a padding byte, so
    bytesPerPixel (4) != channelCount (3), and linePitch absorbs row padding.
    """
    import ctypes

    import numpy as np

    width = request.imageWidth.read()
    height = request.imageHeight.read()
    bit_depth = request.imageChannelBitDepth.read()
    size = request.imageSize.read()
    line_pitch = request.imageLinePitch.read()
    bytes_per_pixel = request.imageBytesPerPixel.read()

    dtype = np.uint16 if bit_depth > 8 else np.uint8
    itemsize = np.dtype(dtype).itemsize
    slots = max(1, bytes_per_pixel // itemsize)     # channels plus padding
    row_slots = line_pitch // itemsize              # including row padding

    buffer = (ctypes.c_ubyte * size).from_address(int(request.imageData.read()))
    array = np.frombuffer(buffer, dtype=dtype)
    array = array[: height * row_slots].reshape((height, row_slots))
    array = array[:, : width * slots].reshape((height, width, slots))

    if slots == 1:
        return array[:, :, 0].copy()                # mono

    # mvIMPACT's packed colour formats are little-endian DWORDs, so the in-memory
    # slot order is already B, G, R[, x] -- OpenCV's order. Only true three-byte
    # RGB888Packed is stored R, G, B.
    bgr = array[:, :, :3]
    if request.imagePixelFormat.readS() == "RGB888Packed":
        bgr = bgr[:, :, ::-1]
    return bgr.copy()
