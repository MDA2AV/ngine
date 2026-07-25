"""Serial verbs -- registered as ``WinSerialManager`` (and ``SerialManager``).

v1 shipped 27 near-identical serial functions. Decoding the names shows they
are one operation with four independent switches:

    READ | EXCHANGE      write first, or only read
    LINE | BYTES         payload is text, or a comma-separated byte list
    _LT_                 read until newline, rather than a fixed byte count
    _LV0 _LV1 _LV2 _LV3 _LVS    what to do with the response

        LV0   store it, no judgement
        LV1   compare against a target, store PASS/FAIL
        LV2   as LV1, but retry N times first
        LV3   as LV2, and kill the UUT + log a grid row on failure
        LVS   "strict": retry N times, then raise -- aborts or routes

So there is one function here and 27 aliases that pre-bind a combination. Fixing
a bug in the retry logic now fixes it everywhere, which was emphatically not
true before.
"""

from __future__ import annotations

import functools

from ..engine.errors import HardwareError, VerbError
from ..engine.events import GridEvent
from ..engine.registry import REGISTRY, Param, VerbSpec, p, verb
from ..engine.runrecord import TestPoint
from .backends import list_serial_ports, make_serial

MODULE = "WinSerialManager"
STATE = "serial"


# --- port table ---------------------------------------------------------

def _ports(ctx) -> dict:
    return ctx.driver_state(STATE).setdefault("ports", {})


def _get_port(ctx, port_id: str):
    ports = _ports(ctx)
    if port_id not in ports:
        known = ", ".join(sorted(ports)) or "none opened"
        raise VerbError(f"serial port '{port_id}' is not open (known: {known})")
    return ports[port_id]


@verb(MODULE, "RESETPORTLIST", config_only=True)
def reset_port_list(ctx, row):
    """Forget every port mapping."""
    for port in _ports(ctx).values():
        try:
            port.close()
        except Exception:  # noqa: BLE001
            pass
    _ports(ctx).clear()
    ctx.log("Serial port list reset.")


@verb(MODULE, "FINDPORT",
      params=[p(2, "baud_timeout", doc="baudrate,timeout_seconds"),
              p(3, "hwid", doc="USB serial number to match"),
              p(4, "id", doc="name the program will use for this port")],
      config_only=True)
def findport(ctx, row):
    """Locate a port by its USB hardware id and bind it to a name.

    Matching is a substring test on the full hwid. v1 sliced ``hwid[26:]`` and
    compared for equality -- a magic offset that broke whenever the driver
    reported a slightly different prefix.
    """
    baud_s, timeout_s = (ctx.text(row.raw(2)).split(",") + ["1"])[:2]
    try:
        baudrate, timeout = int(float(baud_s)), float(timeout_s)
    except ValueError:
        raise VerbError(
            f"FINDPORT: '{row.raw(2)}' is not 'baudrate,timeout'") from None

    target = ctx.text(row.raw(3)).strip()
    port_id = ctx.text(row.raw(4)).strip()
    if not port_id:
        raise VerbError("FINDPORT: no id given for the port")

    for device, description, hwid in list_serial_ports(ctx.simulate):
        if target and target not in hwid and target not in description:
            continue
        port = make_serial(ctx.simulate, device, baudrate, timeout)
        _ports(ctx)[port_id] = port
        ctx.log(f"Port {device} bound to '{port_id}' ({description})")
        return

    available = ", ".join(f"{d} [{h}]" for d, _, h in
                          list_serial_ports(ctx.simulate)) or "none"
    raise HardwareError(
        f"FINDPORT: no serial port matching '{target}' for id '{port_id}'. "
        f"Available: {available}"
    )


@verb(MODULE, "OPEN", params=[p(2, "id")])
def open_port(ctx, row):
    """Open (or reopen) a bound port."""
    port = _get_port(ctx, ctx.text(row.raw(2)))
    if port.is_open:
        port.close()
    port.open()
    port.reset_buffers()


@verb(MODULE, "CLOSE", params=[p(2, "id")])
def close_port(ctx, row):
    """Close a bound port if it is open."""
    port = _get_port(ctx, ctx.text(row.raw(2)))
    if port.is_open:
        port.close()


# --- encoding helpers ---------------------------------------------------

def _encode(ctx, payload: str, cell: str, what: str) -> bytes:
    """Turn a program cell into wire bytes."""
    text = ctx.text(cell)
    if payload == "line":
        # Tables write "/n" for a newline because a real newline cannot be typed
        # into a spreadsheet cell.
        return str(text).replace("/n", "\n").replace("/r", "\r").encode("latin-1",
                                                                        "replace")
    out = bytearray()
    for token in str(text).split(","):
        token = token.strip()
        if not token:
            continue
        try:
            value = int(token, 0)
        except ValueError:
            raise VerbError(f"{what}: '{token}' is not a byte value") from None
        if not 0 <= value <= 255:
            raise VerbError(f"{what}: byte value {value} is outside 0-255")
        out.append(value)
    return bytes(out)


def _decode(payload: str, raw: bytes) -> str:
    if payload == "line":
        return raw.decode("latin-1", "replace").strip("\r\n")
    return ",".join(str(b) for b in raw)


def _matches(payload: str, received: str, target: str) -> bool:
    if payload == "line":
        return target in received          # substring, as v1
    got = [x for x in received.split(",") if x]
    want = [x.strip() for x in target.split(",") if x.strip()]
    return len(got) == len(want) and got == want


# --- the one implementation --------------------------------------------

def _serial_op(ctx, row, *, op: str, payload: str, lt: bool, level) -> None:
    port_id = ctx.text(row.raw(2))
    port = _get_port(ctx, port_id)
    port.reset_buffers()

    read_line = lt or payload == "line"
    extra = [x.strip() for x in ctx.text(row.raw(5)).split(",") if x.strip()]
    nbytes, tries, kill_index, test_name = None, 1, None, None

    if level == 3:
        if len(extra) < 3:
            raise VerbError(
                f"{row.verb}: column 5 must be 'tries,kill_index,test_name', "
                f"got '{row.raw(5)}'")
        tries, kill_index, test_name = int(extra[0]), int(extra[1]), extra[2]
    elif level in ("S", 2):
        if read_line:
            tries = int(extra[0]) if extra else 1
        else:
            if len(extra) < 2:
                raise VerbError(
                    f"{row.verb}: column 5 must be 'nbytes,tries', "
                    f"got '{row.raw(5)}'")
            nbytes, tries = int(extra[0]), int(extra[1])
    elif not read_line:
        if not extra:
            raise VerbError(f"{row.verb}: column 5 must give the byte count to read")
        nbytes = int(extra[0])

    if tries < 1:
        raise VerbError(f"{row.verb}: tries must be at least 1, got {tries}")

    message = _encode(ctx, payload, row.raw(3), row.verb) if op == "exchange" else b""
    target = ctx.text(row.raw(4)) if level != 0 else ""

    received = ""
    matched = False
    for attempt in range(1, tries + 1):
        if ctx.stop_requested.is_set():
            raise VerbError(f"{row.verb}: stopped by operator")
        if op == "exchange":
            ctx.log(f"{port_id} << {row.raw(3)}"
                    + (f" (attempt {attempt}/{tries})" if tries > 1 else ""))
            port.write(message)
        raw = port.readline() if read_line else port.read(nbytes or 0)
        received = _decode(payload, raw)
        ctx.log(f"{port_id} >> {received!r}")

        if level == 0:
            break
        if _matches(payload, received, target):
            matched = True
            break

    _apply_level(ctx, row, level=level, matched=matched, received=received,
                 target=target, port_id=port_id, kill_index=kill_index,
                 test_name=test_name)


def _apply_level(ctx, row, *, level, matched, received, target, port_id,
                 kill_index, test_name) -> None:
    """Everything after the wire exchange: store, judge, kill, or raise."""
    if level == 0:
        if row.has(6):
            ctx.set_data(row.raw(6), received)
        return

    if level == "S":
        if not matched:
            raise VerbError(
                f"{row.verb}: {port_id} never returned '{target}' "
                f"(last response {received!r})"
            )
        return

    result = "PASS" if matched else "FAIL"
    indexes = [x.strip() for x in ctx.text(row.raw(6)).split(";") if x.strip()]
    if not indexes:
        raise VerbError(f"{row.verb}: column 6 must name where to store the result")
    ctx.set_data(indexes[0], result)
    if len(indexes) > 1:
        ctx.set_data(indexes[1], received)

    name = test_name or f"{port_id}:{row.comment or row.verb}"
    ctx.record.add_point(TestPoint(
        name=name, uut=kill_index, result=result,
        measured=received, low=target, high=target, row=row.index,
    ))
    ctx.log(f"{name}: {result}", "pass" if matched else "fail")

    if level == 3:
        ctx.emit(GridEvent(
            grid=(kill_index or 0) + 1, op="add", tag=result,
            values=[name, str((kill_index or 0) + 1), target, target,
                    received, result],
        ))
        if not matched and kill_index is not None:
            ctx.kill(kill_index, reason=name)


# --- plain writes -------------------------------------------------------

def _write_only(ctx, row, payload: str) -> None:
    port_id = ctx.text(row.raw(2))
    port = _get_port(ctx, port_id)
    data = _encode(ctx, payload, row.raw(3), row.verb)
    ctx.log(f"{port_id} << {row.raw(3)}")
    port.write(data)


@verb(MODULE, "WRITE", params=[p(2, "id"), p(3, "text")])
def write(ctx, row):
    """Write text with no terminator added."""
    _write_only(ctx, row, "line")


@verb(MODULE, "WRITELINE", params=[p(2, "id"), p(3, "text")])
def writeline(ctx, row):
    """Write text, appending a newline if the cell did not include one."""
    port_id = ctx.text(row.raw(2))
    port = _get_port(ctx, port_id)
    data = _encode(ctx, "line", row.raw(3), row.verb)
    if not data.endswith(b"\n"):
        data += b"\n"
    ctx.log(f"{port_id} << {row.raw(3)}")
    port.write(data)


@verb(MODULE, "WRITEBYTES", params=[p(2, "id"), p(3, "bytes", doc="comma-separated")])
def writebytes(ctx, row):
    """Write a comma-separated byte list."""
    _write_only(ctx, row, "bytes")


# --- alias table --------------------------------------------------------

#: (verb name) -> (op, payload, line-terminated read, validation level)
_ALIASES: dict[str, tuple[str, str, bool, object]] = {}

for _op, _op_name in (("read", "READ"), ("exchange", "EXCHANGE")):
    for _payload, _pay_name in (("line", "LINE"), ("bytes", "BYTES")):
        for _lt, _lt_name in ((False, ""), (True, "_LT")):
            for _level, _lv_name in ((0, "_LV0"), (1, "_LV1"), (2, "_LV2"),
                                     (3, "_LV3"), ("S", "_LVS")):
                _ALIASES[f"{_op_name}{_pay_name}{_lt_name}{_lv_name}"] = (
                    _op, _payload, _lt, _level)

# LVS never carries the _LT infix in v1's naming -- it always reads a line for
# text and a fixed count for bytes.
_ALIASES["EXCHANGELINE_LVS"] = ("exchange", "line", True, "S")
_ALIASES["EXCHANGEBYTES_LVS"] = ("exchange", "bytes", False, "S")
_ALIASES["READVKING"] = ("read", "line", True, 0)

_PARAMS = (
    Param(2, "id", True, "port name bound by FINDPORT"),
    Param(3, "message", False, "text, or comma-separated bytes"),
    Param(4, "target", False, "expected response (levels 1-3 and S)"),
    Param(5, "extra", False, "tries / nbytes,tries / tries,kill_index,test_name"),
    Param(6, "store", False, "destination index, or 'result;response'"),
)

for _name, (_op, _payload, _lt, _level) in _ALIASES.items():
    REGISTRY.add(VerbSpec(
        module=MODULE, name=_name,
        fn=functools.partial(_serial_op, op=_op, payload=_payload,
                             lt=_lt, level=_level),
        params=_PARAMS,
        legacy=True,
        doc=(f"{_op} {_payload}"
             f"{', line-terminated' if _lt else ''}, validation level {_level}."),
    ))

# Both names resolve to the same table, so a v2 program can use the neutral one.
REGISTRY.alias_module("SerialManager", MODULE)
REGISTRY.alias_module("Serial", MODULE)
