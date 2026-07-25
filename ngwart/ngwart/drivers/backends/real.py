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


class RealCamera:
    """Balluff / GenICam camera via mvIMPACT, falling back to OpenCV.

    The fallback matters in practice: several v1 fixtures used a plain UVC
    camera through OpenCV (CameraManager.py) while others used the Balluff SDK
    (BaluffManager.py). One class covers both, chosen at open time.
    """

    def __init__(self, serial: str, index: int | None = None, **_kw) -> None:
        self.serial = serial
        self.index = index
        self._impl = None
        self._kind = ""

    def open(self) -> None:
        try:
            from mvIMPACT import acquire  # type: ignore
        except ImportError:
            acquire = None

        if acquire is not None:
            try:
                mgr = acquire.DeviceManager()
                dev = mgr.getDeviceBySerial(self.serial)
                if dev is not None:
                    dev.open()
                    self._impl = (acquire, dev, acquire.FunctionInterface(dev))
                    self._kind = "mvimpact"
                    return
            except Exception:  # noqa: BLE001 - fall through to OpenCV
                self._impl = None

        try:
            import cv2
        except ImportError as exc:
            raise HardwareError(
                f"camera {self.serial}: neither mvIMPACT nor OpenCV is available"
            ) from exc
        idx = self.index if self.index is not None else 0
        cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            raise HardwareError(f"cannot open camera {self.serial} (OpenCV index {idx})")
        self._impl = cap
        self._kind = "opencv"

    def close(self) -> None:
        if self._impl is None:
            return
        try:
            if self._kind == "opencv":
                self._impl.release()
            else:
                self._impl[1].close()
        except Exception:  # noqa: BLE001
            pass
        self._impl = None

    def set_property(self, name: str, value) -> None:
        if self._impl is None or self._kind != "opencv":
            return
        import cv2

        prop = {
            "width": cv2.CAP_PROP_FRAME_WIDTH,
            "height": cv2.CAP_PROP_FRAME_HEIGHT,
            "exposure": cv2.CAP_PROP_EXPOSURE,
            "gain": cv2.CAP_PROP_GAIN,
            "brightness": cv2.CAP_PROP_BRIGHTNESS,
            "contrast": cv2.CAP_PROP_CONTRAST,
            "saturation": cv2.CAP_PROP_SATURATION,
            "wb_blue": cv2.CAP_PROP_WHITE_BALANCE_BLUE_U,
            "wb_red": cv2.CAP_PROP_WHITE_BALANCE_RED_V,
        }.get(name.lower())
        if prop is not None:
            self._impl.set(prop, float(value))

    def capture(self):
        if self._impl is None:
            raise HardwareError(f"camera {self.serial} is not open")
        if self._kind == "opencv":
            ok, frame = self._impl.read()
            if not ok or frame is None:
                raise HardwareError(f"camera {self.serial}: capture failed")
            return frame

        acquire, dev, fi = self._impl
        try:
            fi.imageRequestSingle()
            req_nr = fi.imageRequestWaitFor(10000)
            if not fi.isRequestNrValid(req_nr):
                raise HardwareError(f"camera {self.serial}: capture timed out")
            req = fi.getRequest(req_nr)
            import ctypes

            import numpy as np

            buf = (ctypes.c_char * req.imageSize.read()).from_address(
                int(req.imageData.read()))
            frame = np.frombuffer(buf, dtype=np.uint8).copy()
            frame = frame.reshape(req.imageHeight.read(), req.imageWidth.read(), -1)
            fi.imageRequestUnlock(req_nr)
            return frame
        except HardwareError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HardwareError(f"camera {self.serial}: capture failed: {exc}") from exc
