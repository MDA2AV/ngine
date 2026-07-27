"""Hardware abstraction.

Every instrument sits behind a small protocol with two implementations: a real
one (pyserial / pyvisa / the camera SDK) and a simulated one. The verb layer
only ever sees the protocol, so a program runs unchanged on the bench, in CI,
or on a laptop with nothing plugged in.

v1 had no such seam -- ``import serial`` and ``import mvIMPACT`` sat at module
scope, so the application could not even be *imported* without the vendor SDKs
installed, let alone tested.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SerialPort(Protocol):
    """The subset of pyserial that the serial verbs actually use."""

    @property
    def is_open(self) -> bool: ...
    def open(self) -> None: ...
    def close(self) -> None: ...
    def write(self, data: bytes) -> int: ...
    def read(self, size: int) -> bytes: ...
    def readline(self) -> bytes: ...
    def reset_buffers(self) -> None: ...


@runtime_checkable
class VisaInstrument(Protocol):
    def write(self, command: str) -> None: ...
    def query(self, command: str) -> str: ...
    def close(self) -> None: ...


@runtime_checkable
class Camera(Protocol):
    def open(self) -> None: ...
    def close(self) -> None: ...
    def set_property(self, name: str, value) -> bool: ...
    def capture(self):
        """Return an HxWx3 BGR array."""


def make_serial(simulate: bool, port: str, baudrate: int, timeout: float, **kw):
    if simulate:
        from .sim import SimSerialPort
        return SimSerialPort(port, baudrate, timeout, **kw)
    from .real import RealSerialPort
    return RealSerialPort(port, baudrate, timeout, **kw)


def make_visa(simulate: bool, resource: str, timeout_ms: int = 10000, **kw):
    if simulate:
        from .sim import SimVisaInstrument
        return SimVisaInstrument(resource, timeout_ms, **kw)
    from .real import RealVisaInstrument
    return RealVisaInstrument(resource, timeout_ms, **kw)


def make_camera(simulate: bool, serial: str, **kw):
    if simulate:
        from .sim import SimCamera
        return SimCamera(serial, **kw)
    from .real import RealCamera
    return RealCamera(serial, **kw)


def list_serial_ports(simulate: bool) -> list[tuple[str, str, str]]:
    """Return [(device, description, hwid), ...]."""
    if simulate:
        from .sim import sim_port_table
        return sim_port_table()
    from .real import real_port_table
    return real_port_table()
