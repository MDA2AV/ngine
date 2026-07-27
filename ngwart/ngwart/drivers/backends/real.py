"""Real instrument backends.

Vendor imports are deferred into the constructors so that importing NGWART --
or running its test suite -- never requires pyserial, pyvisa or a camera SDK to
be present. v1 imported all of them at module scope, which is why the app could
not start on a machine that was missing any one of them.
"""

from __future__ import annotations

from ...engine.errors import HardwareError


class RealSerialPort:
    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0,
                 **kwargs) -> None:
        try:
            import serial
        except ImportError as exc:
            raise HardwareError(
                "pyserial is not installed -- pip install pyserial, "
                "or run with --simulate"
            ) from exc
        try:
            self._port = serial.Serial(port=port, baudrate=baudrate,
                                       timeout=timeout, **kwargs)
        except Exception as exc:  # noqa: BLE001 - serial raises many types
            raise HardwareError(f"cannot open serial port {port}: {exc}") from exc
        self.port = port

    @property
    def is_open(self) -> bool:
        return bool(self._port.is_open)

    def open(self) -> None:
        if not self._port.is_open:
            self._port.open()

    def close(self) -> None:
        if self._port.is_open:
            self._port.close()

    def write(self, data: bytes) -> int:
        try:
            return self._port.write(data) or 0
        except Exception as exc:  # noqa: BLE001
            raise HardwareError(f"write failed on {self.port}: {exc}") from exc

    def read(self, size: int) -> bytes:
        try:
            return self._port.read(size)
        except Exception as exc:  # noqa: BLE001
            raise HardwareError(f"read failed on {self.port}: {exc}") from exc

    def readline(self) -> bytes:
        try:
            return self._port.readline()
        except Exception as exc:  # noqa: BLE001
            raise HardwareError(f"readline failed on {self.port}: {exc}") from exc

    def reset_buffers(self) -> None:
        try:
            self._port.reset_input_buffer()
            self._port.reset_output_buffer()
        except Exception:  # noqa: BLE001 - flushing must never abort a run
            pass


def real_port_table() -> list[tuple[str, str, str]]:
    try:
        import serial.tools.list_ports as lp
    except ImportError as exc:
        raise HardwareError(
            "pyserial is not installed -- pip install pyserial, or run with --simulate"
        ) from exc
    return [(p.device, p.description or "", p.hwid or "") for p in lp.comports()]


class RealVisaInstrument:
    _rm = None

    def __init__(self, resource: str, timeout_ms: int = 10000, **_kw) -> None:
        try:
            import pyvisa
        except ImportError as exc:
            raise HardwareError(
                "pyvisa is not installed -- pip install pyvisa, or run with --simulate"
            ) from exc
        if RealVisaInstrument._rm is None:
            try:
                RealVisaInstrument._rm = pyvisa.ResourceManager()
            except Exception as exc:  # noqa: BLE001
                raise HardwareError(f"no VISA backend available: {exc}") from exc
        try:
            self._inst = RealVisaInstrument._rm.open_resource(resource)
            self._inst.timeout = timeout_ms
        except Exception as exc:  # noqa: BLE001
            raise HardwareError(f"cannot open VISA resource {resource}: {exc}") from exc
        self.resource = resource

    def write(self, command: str) -> None:
        try:
            self._inst.write(command)
        except Exception as exc:  # noqa: BLE001
            raise HardwareError(f"VISA write '{command}' failed on "
                                f"{self.resource}: {exc}") from exc

    def query(self, command: str) -> str:
        try:
            return str(self._inst.query(command)).strip()
        except Exception as exc:  # noqa: BLE001
            raise HardwareError(f"VISA query '{command}' failed on "
                                f"{self.resource}: {exc}") from exc

    def close(self) -> None:
        try:
            self._inst.close()
        except Exception:  # noqa: BLE001
            pass


def visa_resources() -> list[str]:
    try:
        import pyvisa
    except ImportError as exc:
        raise HardwareError("pyvisa is not installed") from exc
    try:
        rm = RealVisaInstrument._rm or pyvisa.ResourceManager()
        RealVisaInstrument._rm = rm
        return list(rm.list_resources())
    except Exception as exc:  # noqa: BLE001
        raise HardwareError(f"cannot enumerate VISA resources: {exc}") from exc


#: The mvIMPACT DeviceManager must outlive every device handle it hands out.
#: When the last DeviceManager is collected, the driver stack unloads and every
#: open pDev / FunctionInterface becomes a dangling native handle -- the next
#: driver call then crashes the process rather than raising. Holding one at
#: module scope is the documented fix, and matches what v1's BaluffManager does.
_DEVICE_MANAGER = None


def _device_manager():
    global _DEVICE_MANAGER
    if _DEVICE_MANAGER is None:
        from mvIMPACT import acquire  # type: ignore
        _DEVICE_MANAGER = acquire.DeviceManager()
    return _DEVICE_MANAGER


class OpenCvCamera:
    """Plain UVC camera through OpenCV -- the CameraManager fixtures."""

    _PROPS = {
        "width": "CAP_PROP_FRAME_WIDTH", "height": "CAP_PROP_FRAME_HEIGHT",
        "exposure": "CAP_PROP_EXPOSURE", "brightness": "CAP_PROP_BRIGHTNESS",
        "saturation": "CAP_PROP_SATURATION", "contrast": "CAP_PROP_CONTRAST",
        "focus": "CAP_PROP_FOCUS", "autofocus": "CAP_PROP_AUTOFOCUS",
        "hue": "CAP_PROP_HUE",
    }

    def __init__(self, serial: str, index=None, **_kw) -> None:
        self.serial = serial
        self.index = index if index is not None else 0
        self._cap = None

    def open(self) -> None:
        import cv2

        cap = cv2.VideoCapture(self.index)
        if not cap.isOpened():
            raise HardwareError(
                f"cannot open camera {self.serial} (OpenCV index {self.index})")
        self._cap = cap

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    @property
    def is_open(self) -> bool:
        return self._cap is not None

    def set_property(self, name: str, value) -> bool:
        import cv2

        if self._cap is None:
            return False
        attr = self._PROPS.get(name.lower())
        if attr is None:
            return False
        return bool(self._cap.set(getattr(cv2, attr), float(value)))

    def configure(self, props: dict) -> dict:
        applied, ignored = {}, []
        for name, value in props.items():
            if name == "buffersize":
                continue
            if self.set_property(name, value):
                applied[name] = value
            elif float(value or 0) != 0:
                ignored.append(f"{name}={value}")
        return {"applied": applied, "ignored": ignored, "notes": []}

    def set_exposure(self, microseconds: float) -> float:
        self.set_property("exposure", microseconds)
        return float(microseconds)

    def calibrate_white_balance(self, exposure_us: float = 20000.0,
                                warmup: int = 5) -> tuple:
        """Grey-world estimate -- OpenCV exposes no calibration primitive."""
        import numpy as np

        self.set_exposure(exposure_us)
        means = []
        for _ in range(max(1, int(warmup))):
            means.append(np.asarray(self.capture(), dtype=float)
                         .reshape(-1, 3).mean(axis=0))
        mean = np.mean(means, axis=0)
        grey = float(mean.mean())
        if grey <= 0:
            raise HardwareError(f"camera {self.serial} returned a black image")
        blue, green, red = (grey / m if m > 0 else 1.0 for m in mean)
        return (red, green, blue)

    def white_balance_gains(self):
        return None

    def capture(self):
        if self._cap is None:
            raise HardwareError(f"camera {self.serial} is not open")
        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise HardwareError(f"camera {self.serial}: capture failed")
        return frame


def RealCamera(serial: str, index=None, **kw):  # noqa: N802 - factory, not a class
    """Pick the SDK that can actually drive this camera.

    mvIMPACT first: a Balluff device needs binning, AOI and User1 white balance,
    which only that path can express. OpenCV otherwise, for the UVC fixtures the
    old CameraManager served.
    """
    try:
        from mvIMPACT import acquire  # noqa: F401
        from mvIMPACT.Common import exampleHelper  # noqa: F401
    except ImportError:
        return OpenCvCamera(serial, index, **kw)

    from .mvimpact import MvImpactCamera

    camera = MvImpactCamera(serial, device_manager=_device_manager(), **kw)
    try:
        camera.open()
        return camera
    except Exception:  # noqa: BLE001 - no such Balluff device; try OpenCV
        return OpenCvCamera(serial, index, **kw)
