"""VISA / SCPI instrument verbs -- registered as ``GlobalVISAManager``."""

from __future__ import annotations

from ..engine.errors import HardwareError, VerbError
from ..engine.events import GridEvent
from ..engine.registry import REGISTRY, p, verb
from ..engine.runrecord import TestPoint
from .backends import make_visa

MODULE = "GlobalVISAManager"
STATE = "visa"

#: Resources the simulator pretends are on the bus.
SIM_RESOURCES = ["USB0::0x1AB1::0x0E11::DP2A243200206::INSTR"]


def _instruments(ctx) -> dict:
    return ctx.driver_state(STATE).setdefault("instruments", {})


def _timeout(ctx) -> int:
    return int(ctx.driver_state(STATE).get("timeout_ms", 10000))


def _get(ctx, ident: str):
    """Resolve an instrument by the id a program uses (usually its serial).

    In simulation an unknown id is created on demand, so a program can be
    dry-run without first describing the whole bench.
    """
    instruments = _instruments(ctx)
    if ident in instruments:
        return instruments[ident]
    for resource, inst in instruments.items():
        if ident and ident in resource:
            instruments[ident] = inst
            return inst
    if ctx.simulate:
        inst = make_visa(True, f"SIM::{ident}::INSTR", _timeout(ctx))
        instruments[ident] = inst
        ctx.log(f"VISA: simulating instrument '{ident}'")
        return inst
    known = ", ".join(sorted(instruments)) or "none"
    raise HardwareError(f"VISA instrument '{ident}' was not opened (known: {known})")


@verb(MODULE, "OPENALL",
      params=[p(2, "timeout_ms", required=False),
              p(3, "include_serial", required=False,
                doc="ALL to also open ASRL (COM port) resources")],
      config_only=True)
def openall(ctx, row):
    """Enumerate the VISA bus and open everything on it."""
    timeout = 10000
    if row.has(2):
        try:
            timeout = int(float(ctx.text(row.raw(2))))
        except ValueError:
            raise VerbError(f"OPENALL: '{row.raw(2)}' is not a timeout in ms") from None
    ctx.driver_state(STATE)["timeout_ms"] = timeout

    if ctx.simulate:
        resources = list(SIM_RESOURCES)
    else:
        from .backends.real import visa_resources
        resources = visa_resources()

    # ASRL resources are the machine's COM ports. On this kind of station
    # pyserial already owns them -- FINDPORT opens them by hardware id -- so
    # opening them through VISA as well yields VI_ERROR_RSRC_BUSY at best and
    # steals the port from the test at worst. v1 filtered them out with a
    # `len(resource) < 40` heuristic; filtering on the interface type says what
    # it means and does not depend on how long a serial number happens to be.
    include_serial = ctx.text(row.raw(3)).strip().upper() in ("ALL", "SERIAL")
    if not include_serial:
        skipped = [r for r in resources if r.upper().startswith("ASRL")]
        resources = [r for r in resources if not r.upper().startswith("ASRL")]
        if skipped:
            ctx.log(f"VISA: ignoring {len(skipped)} serial resource(s) "
                    f"(pass ALL in column 3 to include them)")

    instruments = _instruments(ctx)
    for resource in resources:
        try:
            inst = make_visa(ctx.simulate, resource, timeout)
        except HardwareError as exc:
            ctx.log(f"VISA: skipping {resource}: {exc}", "warn")
            continue
        instruments[resource] = inst
        try:
            ident = inst.query("*IDN?")
        except Exception:  # noqa: BLE001
            ident = ""
        ctx.log(f"VISA opened {resource} {ident}")
        # Index by serial too, since tables address instruments by serial.
        for part in resource.split("::"):
            if part and part not in ("INSTR", "USB0") and not part.startswith("0x"):
                instruments.setdefault(part, inst)
    if not instruments:
        ctx.log("VISA: no instruments found", "warn")


@verb(MODULE, "WRITE", params=[p(2, "id"), p(3, "command")])
def write(ctx, row):
    """Send a SCPI command."""
    ident = ctx.text(row.raw(2))
    command = ctx.text(row.raw(3))
    ctx.log(f"VISA {ident} << {command}")
    _get(ctx, ident).write(command)


@verb(MODULE, "EXCHANGE", params=[p(2, "id"), p(3, "query"), p(4, "dest")])
def exchange(ctx, row):
    """Query and store the reply."""
    ident = ctx.text(row.raw(2))
    query = ctx.text(row.raw(3))
    reply = _get(ctx, ident).query(query)
    ctx.log(f"VISA {ident} >> {reply}")
    ctx.set_data(row.raw(4), reply)


@verb(MODULE, "MEASURE", params=[p(2, "id"), p(3, "query"), p(5, "dest")])
def measure(ctx, row):
    """Take one measurement and store it. Destination is column 5, as in v1."""
    ident = ctx.text(row.raw(2))
    reply = _get(ctx, ident).query(ctx.text(row.raw(3)))
    value = _as_float(reply, row.verb)
    ctx.log(f"VISA {ident} measured {value}")
    ctx.set_data(row.raw(5), value)


@verb(MODULE, "MASS_MEASURE", params=[p(2, "id"), p(3, "query"),
                                      p(5, "dests", doc="';'-separated indexes")])
def mass_measure(ctx, row):
    """Repeat a measurement once per destination index."""
    ident = ctx.text(row.raw(2))
    query = ctx.text(row.raw(3))
    dests = [d.strip() for d in ctx.text(row.raw(5)).split(";") if d.strip()]
    if not dests:
        raise VerbError("MASS_MEASURE: no destination indexes given")
    inst = _get(ctx, ident)
    for dest in dests:
        ctx.set_data(dest, _as_float(inst.query(query), row.verb))


@verb(MODULE, "MEASURE_FEVAL",
      params=[p(2, "id"), p(3, "query"), p(4, "limits", doc="lower,upper"),
              p(5, "dest"), p(6, "extra", doc="tries,kill_index,test_name")])
def measure_feval(ctx, row):
    """Measure, judge against limits, record the point and kill on failure.

    Retries are honoured: a value outside limits is re-measured up to `tries`
    times before the UUT is failed, which is what the bench actually wants for
    a supply that is still settling.
    """
    ident = ctx.text(row.raw(2))
    query = ctx.text(row.raw(3))

    limits = [x.strip() for x in ctx.text(row.raw(4)).split(",")]
    if len(limits) < 2:
        raise VerbError(f"MEASURE_FEVAL: limits must be 'lower,upper', "
                        f"got '{row.raw(4)}'")
    try:
        low, high = float(limits[0]), float(limits[1])
    except ValueError:
        raise VerbError(f"MEASURE_FEVAL: limits '{row.raw(4)}' are not numbers") from None

    extra = [x.strip() for x in ctx.text(row.raw(6)).split(",") if x.strip()]
    if len(extra) < 3:
        raise VerbError("MEASURE_FEVAL: column 6 must be 'tries,kill_index,test_name'")
    try:
        tries, kill_index = max(int(extra[0]), 1), int(extra[1])
    except ValueError:
        raise VerbError("MEASURE_FEVAL: tries and kill_index must be whole numbers") from None
    test_name = extra[2]

    inst = _get(ctx, ident)
    value = None
    for attempt in range(1, tries + 1):
        value = _as_float(inst.query(query), row.verb)
        if low <= value <= high:
            break
        if attempt < tries:
            ctx.log(f"{test_name}: {value} outside [{low}, {high}], "
                    f"retry {attempt}/{tries}", "warn")

    result = "PASS" if value is not None and low <= value <= high else "FAIL"
    ctx.set_data(row.raw(5), value)
    ctx.log(f"{test_name}: {value} in [{low}, {high}] -> {result}",
            "pass" if result == "PASS" else "fail")
    ctx.record.add_point(TestPoint(
        name=test_name, uut=kill_index, result=result,
        measured=str(value), low=str(low), high=str(high), row=row.index,
    ))
    ctx.emit(GridEvent(grid=kill_index + 1, op="add", tag=result,
                       values=[test_name, str(kill_index + 1), str(low), str(high),
                               str(value), result]))
    if result == "FAIL":
        ctx.kill(kill_index, reason=test_name)


def _as_float(reply: str, what: str) -> float:
    try:
        return float(str(reply).strip().split(",")[0])
    except (TypeError, ValueError):
        raise VerbError(f"{what}: instrument returned '{reply}', which is not a number") from None


REGISTRY.alias_module("VISA", MODULE)
