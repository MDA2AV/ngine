"""Simulated instruments.

These are not stubs that return zeros -- they model the fixture well enough to
exercise a real test program: the relay boards echo their command frames, the
control board answers the detection poll, and the PSU tracks per-channel
voltage/current so a MEASURE verb reads back something consistent with what was
written.

That fidelity is what lets a test program be written and dry-run at a desk, and
lets the test suite assert on behaviour instead of on mocks.
"""

from __future__ import annotations

import random
import re
import threading
import time

# Deterministic by default: a simulated run should be reproducible so that a
# failing test is a real failure, not luck. Call seed() to vary it.
_rng = random.Random(0xC0FFEE)


def seed(value: int) -> None:
    global _rng
    _rng = random.Random(value)


# --- serial -------------------------------------------------------------

#: Simulated devices, keyed by the hardware id a program's FINDPORT looks for.
#: Mirrors the cargo fixture: one control board and two Denkovi relay boards.
SIM_DEVICES = {
    "066CFF3833554B3043165348 LOCATION=1-1:x.2": ("COM11", "Control board (sim)"),
    "DAE006GCA": ("COM12", "Denkovi DAE 1 (sim)"),
    "DAE00646A": ("COM13", "Denkovi DAE 2 (sim)"),
}


def sim_port_table() -> list[tuple[str, str, str]]:
    return [(dev, desc, "USB VID:PID=0483:5740 SER=" + hwid)
            for hwid, (dev, desc) in SIM_DEVICES.items()]


class SimSerialPort:
    """A serial port that answers like the boards on the cargo fixture.

    Response rules are matched in order; the first hit wins. Unmatched writes
    echo back, which is what the Denkovi relay boards do and what most of the
    EXCHANGEBYTES_LVS rows in cargo.ods expect.
    """

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0,
                 rules: list[tuple[str, str]] | None = None,
                 detect_after: int = 2, **_kw) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._open = True
        self._rx = bytearray()
        self._lock = threading.Lock()
        self._poll_count = 0
        #: How many detection polls before the simulated PCBAs "appear".
        self.detect_after = detect_after
        self.rules: list[tuple[re.Pattern, bytes]] = []
        for pattern, response in (rules or []):
            self.add_rule(pattern, response)
        self.history: list[bytes] = []

    # -- protocol ---------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def reset_buffers(self) -> None:
        with self._lock:
            self._rx.clear()

    def write(self, data: bytes) -> int:
        if not self._open:
            raise OSError(f"write to closed simulated port {self.port}")
        with self._lock:
            self.history.append(bytes(data))
            self._rx.extend(self._respond(bytes(data)))
        # Model wire time so timing-sensitive programs behave plausibly.
        time.sleep(min(0.002, len(data) / max(self.baudrate, 1) * 10))
        return len(data)

    def read(self, size: int) -> bytes:
        with self._lock:
            out = bytes(self._rx[:size])
            del self._rx[:size]
        return out

    def readline(self) -> bytes:
        deadline = time.monotonic() + max(self.timeout, 0.01)
        while True:
            with self._lock:
                idx = self._rx.find(b"\n")
                if idx >= 0:
                    out = bytes(self._rx[: idx + 1])
                    del self._rx[: idx + 1]
                    return out
                if time.monotonic() > deadline:
                    out = bytes(self._rx)   # timeout: return whatever arrived
                    self._rx.clear()
                    return out
            time.sleep(0.001)

    # -- behaviour --------------------------------------------------------

    def add_rule(self, pattern: str, response: str | bytes) -> None:
        body = response.encode() if isinstance(response, str) else response
        self.rules.append((re.compile(pattern, re.IGNORECASE | re.DOTALL), body))

    def _respond(self, data: bytes) -> bytes:
        text = data.decode("latin-1", "replace")

        for pattern, response in self.rules:
            if pattern.search(text):
                return response

        # Control board: "d\n" is the detection poll used by cargo.ods. It
        # returns 16 + a 4-bit mask of *absent* boards, so 16 means "all four
        # present". Report nothing detected until detect_after polls, so the
        # program's DETECTION retry loop is genuinely exercised.
        if text.strip() in ("d", "d\r"):
            self._poll_count += 1
            value = 16 if self._poll_count >= self.detect_after else 16 + 15
            return f"{value}\n".encode()

        if text.strip() in ("r", "r\r"):
            return b"Outputs Reset\n"

        # Denkovi-style relay frames end with "//" and are echoed verbatim.
        if data.endswith(b"//"):
            return data + b"\n"

        return data if data.endswith(b"\n") else data + b"\n"


# --- VISA ---------------------------------------------------------------

class SimVisaInstrument:
    """A simulated SCPI supply.

    Tracks per-channel setpoints and output state so that a program which sets
    13.5 V and then measures gets 13.5 V back (plus a little noise), and one
    that measures with the output off gets ~0. Behaviour a flat mock cannot give.
    """

    def __init__(self, resource: str, timeout_ms: int = 10000,
                 channels: int = 3, **_kw) -> None:
        self.resource = resource
        self.timeout_ms = timeout_ms
        self.channels = {i: {"volt": 0.0, "curr": 0.0, "out": False}
                         for i in range(1, channels + 1)}
        self.selected = 1
        self.history: list[str] = []
        self._closed = False

    def close(self) -> None:
        self._closed = True

    def write(self, command: str) -> None:
        if self._closed:
            raise OSError(f"write to closed simulated instrument {self.resource}")
        self.history.append(command)
        cmd = command.strip().upper()

        m = re.match(r"INST(?::NSEL)?\s+(\d+)", cmd)
        if m:
            self.selected = int(m.group(1))
            return
        m = re.match(r"VOLT\s+([\d.]+)", cmd)
        if m:
            self._chan()["volt"] = float(m.group(1))
            return
        m = re.match(r"CURR\s+([\d.]+)", cmd)
        if m:
            self._chan()["curr"] = float(m.group(1))
            return
        m = re.match(r"OUTP(?:UT)?\s+(ON|OFF|1|0)", cmd)
        if m:
            self._chan()["out"] = m.group(1) in ("ON", "1")
            return

    def query(self, command: str) -> str:
        self.history.append(command)
        cmd = command.strip().upper()

        if "IDN" in cmd:
            return "RIGOL TECHNOLOGIES,DP832,SIM0001,00.01.16"

        chan = self._chan()
        if "MEAS" in cmd and "CURR" in cmd:
            if not chan["out"]:
                return f"{_rng.uniform(0, 1e-4):.6f}"
            # A plausible load: roughly a third of the compliance setting.
            draw = chan["curr"] * 0.33 if chan["curr"] else 0.15
            return f"{draw + _rng.uniform(-0.002, 0.002):.6f}"
        if "MEAS" in cmd:  # voltage
            if not chan["out"]:
                return f"{_rng.uniform(0, 0.002):.6f}"
            return f"{chan['volt'] + _rng.uniform(-0.01, 0.01):.6f}"
        return "0"

    def _chan(self) -> dict:
        return self.channels.setdefault(self.selected,
                                        {"volt": 0.0, "curr": 0.0, "out": False})


# --- camera -------------------------------------------------------------

class SimCamera:
    """Generates a synthetic scene with lit indicators.

    The image contains four bright discs on a dark field, so the contour and
    LED-evaluation verbs have something real to find. `lit` controls which are
    on, letting a test drive a failure without hardware.
    """

    def __init__(self, serial: str, width: int = 640, height: int = 480,
                 lit: tuple[bool, ...] = (True, True, True, True), **_kw) -> None:
        self.serial = serial
        self.width = width
        self.height = height
        self.lit = list(lit)
        self.properties: dict[str, object] = {}
        self._open = False

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def set_property(self, name: str, value) -> bool:
        self.properties[name] = value
        if name == "width":
            self.width = max(1, int(value))
        elif name == "height":
            self.height = max(1, int(value))
        return True

    def configure(self, props: dict) -> dict:
        """Accept everything, and honour the geometry.

        Honouring width/height matters: a program that asks for 1296x972 and
        then evaluates a contour at (895, 659) must get a frame those
        coordinates fall inside, or the simulation tests nothing useful.
        """
        for name, value in props.items():
            self.set_property(name, value)
        return {"applied": dict(props), "ignored": [], "notes": []}

    def set_exposure(self, microseconds: float) -> float:
        self.properties["exposure"] = float(microseconds)
        return float(microseconds)

    def calibrate_white_balance(self, exposure_us: float = 20000.0,
                                warmup: int = 5) -> tuple:
        self.set_exposure(exposure_us)
        self._wb = (2.0, 1.0, 1.9)
        return self._wb

    def white_balance_gains(self):
        return getattr(self, "_wb", None)

    def capture(self):
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "the simulated camera needs numpy -- pip install numpy"
            ) from exc

        if not self._open:
            raise OSError(f"capture from closed simulated camera {self.serial}")

        img = np.full((self.height, self.width, 3), 18, dtype=np.uint8)
        step = self.width // (len(self.lit) + 1)
        radius = max(12, min(self.height, step) // 5)
        yy, xx = np.ogrid[: self.height, : self.width]
        for i, on in enumerate(self.lit):
            cx, cy = step * (i + 1), self.height // 2
            mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= radius ** 2
            img[mask] = (60, 220, 90) if on else (30, 30, 30)
        noise = np.random.default_rng(0).integers(0, 6, img.shape, dtype=np.uint8)
        return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
