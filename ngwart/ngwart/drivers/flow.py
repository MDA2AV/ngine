"""Control flow, arithmetic, strings, files and limit evaluation.

Registered as ``FlowManager`` so existing <Modules> lines keep resolving.

The evaluation verbs (EVAFLOAT / EVACSTR / EVALIM) do three things at once:
store a result, paint a grid row, and kill the UUT on failure. In v1 each of
them repeated a four-way ``if kill_index == "0"/"1"/"2"/"3"`` chain three times
over -- twelve near-identical blocks per verb. Here the grid is simply
``kill_index + 1``.
"""

from __future__ import annotations

import json
import os
import shutil
import time

from ..engine.errors import ProgramError, VerbError
from ..engine.events import GridEvent, StatusEvent
from ..engine.registry import REGISTRY, p, verb
from ..engine.runrecord import TestPoint

MODULE = "FlowManager"


# --- helpers ------------------------------------------------------------

def _num(ctx, cell: str, what: str) -> float:
    raw = ctx.text(cell)
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        raise VerbError(f"{what}: '{raw}' is not a number") from None


def _pair(ctx, cell: str, what: str) -> tuple[str, str]:
    parts = [x.strip() for x in ctx.text(cell).split(",")]
    if len(parts) != 2:
        raise VerbError(f"{what}: expected two comma-separated values, got '{cell}'")
    return parts[0], parts[1]


def _jump_if(ctx, row, condition: bool) -> None:
    label = row.raw(2)
    if condition:
        ctx.log(f"Jumping to {label}")
        ctx.jump(label)
    else:
        ctx.log(f"Not jumping to {label}")


def _emit_point(ctx, row, name: str, uut: int | None, result: str,
                measured="", low="", high="") -> None:
    ctx.record.add_point(TestPoint(
        name=name, uut=uut, result=result, measured=str(measured),
        low=str(low), high=str(high), row=row.index,
    ))


# --- jumps --------------------------------------------------------------

@verb(MODULE, "J", params=[p(2, "label")])
def j(ctx, row):
    """Unconditional jump."""
    _jump_if(ctx, row, True)


@verb(MODULE, "JC", params=[p(2, "label"), p(3, "haystack"), p(4, "needle")])
def jc(ctx, row):
    """Jump if 3 contains 4."""
    _jump_if(ctx, row, ctx.text(row.raw(4)) in ctx.text(row.raw(3)))


@verb(MODULE, "JCM", params=[p(2, "label"), p(3, "haystack"),
                             p(4, "needles", doc="';'-separated")])
def jcm(ctx, row):
    """Jump if 3 contains every ';'-separated word in 4."""
    haystack = ctx.text(row.raw(3))
    words = [w for w in ctx.text(row.raw(4)).split(";") if w]
    _jump_if(ctx, row, all(w in haystack for w in words))


@verb(MODULE, "JNC", params=[p(2, "label"), p(3, "haystack"), p(4, "needle")])
def jnc(ctx, row):
    """Jump if 3 does not contain 4."""
    _jump_if(ctx, row, ctx.text(row.raw(4)) not in ctx.text(row.raw(3)))


@verb(MODULE, "JE", params=[p(2, "label"), p(3, "a"), p(4, "b")])
def je(ctx, row):
    """Jump if 3 equals 4 (string compare)."""
    _jump_if(ctx, row, ctx.text(row.raw(3)) == ctx.text(row.raw(4)))


@verb(MODULE, "JNE", params=[p(2, "label"), p(3, "a"), p(4, "b")])
def jne(ctx, row):
    """Jump if 3 differs from 4."""
    _jump_if(ctx, row, ctx.text(row.raw(3)) != ctx.text(row.raw(4)))


@verb(MODULE, "JET", params=[p(2, "label"), p(3, "a"), p(4, "b"), p(5, "tolerance")])
def jet(ctx, row):
    """Jump if 3 equals 4 within tolerance 5."""
    a, b = _num(ctx, row.raw(3), "JET"), _num(ctx, row.raw(4), "JET")
    tol = abs(_num(ctx, row.raw(5), "JET"))
    _jump_if(ctx, row, abs(a - b) <= tol)


@verb(MODULE, "JNET", params=[p(2, "label"), p(3, "a"), p(4, "b"), p(5, "tolerance")])
def jnet(ctx, row):
    """Jump if 3 differs from 4 by more than tolerance 5."""
    a, b = _num(ctx, row.raw(3), "JNET"), _num(ctx, row.raw(4), "JNET")
    tol = abs(_num(ctx, row.raw(5), "JNET"))
    _jump_if(ctx, row, abs(a - b) > tol)


@verb(MODULE, "JG", params=[p(2, "label"), p(3, "a"), p(4, "b")])
def jg(ctx, row):
    """Jump if 3 > 4."""
    _jump_if(ctx, row, _num(ctx, row.raw(3), "JG") > _num(ctx, row.raw(4), "JG"))


@verb(MODULE, "JL", params=[p(2, "label"), p(3, "a"), p(4, "b")])
def jl(ctx, row):
    """Jump if 3 < 4."""
    _jump_if(ctx, row, _num(ctx, row.raw(3), "JL") < _num(ctx, row.raw(4), "JL"))


@verb(MODULE, "JGE", params=[p(2, "label"), p(3, "a"), p(4, "b")])
def jge(ctx, row):
    """Jump if 3 >= 4."""
    _jump_if(ctx, row, _num(ctx, row.raw(3), "JGE") >= _num(ctx, row.raw(4), "JGE"))


@verb(MODULE, "JLE", params=[p(2, "label"), p(3, "a"), p(4, "b")])
def jle(ctx, row):
    """Jump if 3 <= 4."""
    _jump_if(ctx, row, _num(ctx, row.raw(3), "JLE") <= _num(ctx, row.raw(4), "JLE"))


@verb(MODULE, "LABEL", params=[p(2, "name"), p(3, "status", required=False),
                               p(5, "colour", required=False)])
def label(ctx, row):
    """A jump target, optionally updating the status banner."""
    text = ctx.text(row.raw(3))
    colour = ctx.text(row.raw(5)) or None
    if text:
        ctx.emit(StatusEvent(text=text, color=colour))
    ctx.log(f"== {row.raw(2)} ==")


# --- timing -------------------------------------------------------------

@verb(MODULE, "DELAY", params=[p(2, "seconds")])
def delay(ctx, row):
    """Wait, remaining responsive to a stop request.

    v1 used ``await asyncio.sleep`` on the same loop that drove the UI, so a
    long delay was survivable; a long *serial read* on that loop was not. Here
    the wait is chunked so pressing stop takes effect within 50 ms instead of
    at the end of a multi-second delay.
    """
    seconds = _num(ctx, row.raw(2), "DELAY")
    if seconds < 0:
        raise VerbError(f"DELAY: negative duration {seconds}")
    ctx.log(f"Delay {seconds}s")
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if ctx.stop_requested.is_set():
            return
        time.sleep(min(0.05, max(deadline - time.monotonic(), 0)))


@verb(MODULE, "RESET_TIMER")
def reset_timer(ctx, row):
    """Restart the elapsed-time counter."""
    ctx.timers.reset()
    ctx.tick_timer()


@verb(MODULE, "ENABLE_TIMER")
def enable_timer(ctx, row):
    """Show elapsed time in the UI."""
    ctx.timers.enabled = True
    ctx.tick_timer()


@verb(MODULE, "DISABLE_TIMER")
def disable_timer(ctx, row):
    """Stop updating the elapsed-time display."""
    ctx.timers.enabled = False


@verb(MODULE, "START_TIME", params=[p(2, "index")])
def start_time(ctx, row):
    """Store the wall-clock start time."""
    ctx.set_data(row.raw(2), time.strftime("%Y-%m-%d %H:%M:%S"))


# --- data movement ------------------------------------------------------

@verb(MODULE, "STORE", params=[p(2, "value"), p(3, "index")])
def store(ctx, row):
    """Store a literal or dereferenced value."""
    ctx.set_data(row.raw(3), ctx.text(row.raw(2)))


@verb(MODULE, "STOREF", params=[p(2, "template", doc="'text with %0;arg0;arg1'"),
                                p(3, "index")])
def storef(ctx, row):
    """Store a formatted string.

    ``template;arg0;arg1`` with ``%0``/``%1`` placeholders. Used heavily to
    build log paths: ``C:\\Logs\\%0\\%1;*2,0,23;*3,0,23``.
    """
    parts = row.raw(2).split(";")
    template = parts[0]
    for i, arg in enumerate(parts[1:]):
        template = template.replace(f"%{i}", str(ctx.text(arg)))
    ctx.set_data(row.raw(3), template)


@verb(MODULE, "COPY", params=[p(2, "source"), p(3, "dest")])
def copy(ctx, row):
    """Copy one data cell to another."""
    ctx.set_data(row.raw(3), ctx.text(row.raw(2)))


# --- arithmetic ---------------------------------------------------------

def _arith(ctx, row, op, name):
    a, b = _num(ctx, row.raw(3), name), _num(ctx, row.raw(4), name)
    if name == "DIV" and b == 0:
        raise VerbError("DIV: division by zero")
    ctx.set_data(row.raw(2), op(a, b))


@verb(MODULE, "ADD", params=[p(2, "dest"), p(3, "a"), p(4, "b")])
def add(ctx, row):
    """dest = a + b"""
    _arith(ctx, row, lambda x, y: x + y, "ADD")


@verb(MODULE, "SUB", params=[p(2, "dest"), p(3, "a"), p(4, "b")])
def sub(ctx, row):
    """dest = a - b"""
    _arith(ctx, row, lambda x, y: x - y, "SUB")


@verb(MODULE, "MULT", params=[p(2, "dest"), p(3, "a"), p(4, "b")])
def mult(ctx, row):
    """dest = a * b"""
    _arith(ctx, row, lambda x, y: x * y, "MULT")


@verb(MODULE, "DIV", params=[p(2, "dest"), p(3, "a"), p(4, "b")])
def div(ctx, row):
    """dest = a / b"""
    _arith(ctx, row, lambda x, y: x / y, "DIV")


# --- strings ------------------------------------------------------------

@verb(MODULE, "EQUAL", params=[p(2, "a"), p(3, "b"), p(4, "dest"),
                               p(5, "if_true"), p(6, "if_false")])
def equal(ctx, row):
    """dest = if_true when a == b, else if_false."""
    hit = ctx.text(row.raw(2)) == ctx.text(row.raw(3))
    ctx.set_data(row.raw(4), ctx.text(row.raw(5) if hit else row.raw(6)))


@verb(MODULE, "CONTAIN", params=[p(2, "haystack"), p(3, "needle"), p(4, "dest"),
                                 p(5, "if_true"), p(6, "if_false")])
def contain(ctx, row):
    """dest = if_true when haystack contains needle, else if_false."""
    hit = ctx.text(row.raw(3)) in ctx.text(row.raw(2))
    ctx.set_data(row.raw(4), ctx.text(row.raw(5) if hit else row.raw(6)))


@verb(MODULE, "REPLACE", params=[p(2, "index"), p(3, "find"), p(4, "replace")])
def replace(ctx, row):
    """In-place substring replacement on a data cell."""
    current = str(ctx.get_data(row.raw(2)) or "")
    ctx.set_data(row.raw(2), current.replace(ctx.text(row.raw(3)),
                                             ctx.text(row.raw(4))))


@verb(MODULE, "SUBSTRING", params=[p(2, "source"), p(3, "start"), p(4, "end"),
                                   p(5, "dest")])
def substring(ctx, row):
    """dest = source[start:end]."""
    text = ctx.text(row.raw(2))
    try:
        start, end = int(ctx.text(row.raw(3))), int(ctx.text(row.raw(4)))
    except ValueError:
        raise VerbError("SUBSTRING: start and end must be whole numbers") from None
    if start < 0 or end > len(text) or start > end:
        raise VerbError(
            f"SUBSTRING: [{start}:{end}] is outside a string of length {len(text)}"
        )
    ctx.set_data(row.raw(5), text[start:end])


@verb(MODULE, "COUNT", params=[p(2, "haystack"), p(3, "needle"), p(4, "dest")])
def count(ctx, row):
    """dest = number of times needle occurs in haystack."""
    ctx.set_data(row.raw(4), ctx.text(row.raw(2)).count(ctx.text(row.raw(3))))


# --- arrays -------------------------------------------------------------

@verb(MODULE, "ARRAY", params=[p(2, "op", doc="Init | Store | Get"),
                               p(3, "name"), p(4, "index_or_size", required=False),
                               p(5, "value_or_dest", required=False)])
def array(ctx, row):
    """Named list storage: ``Init name size`` / ``Store name i value`` / ``Get name i dest``."""
    arrays = ctx.driver_state("flow").setdefault("arrays", {})
    op = ctx.text(row.raw(2)).lower()
    name = ctx.text(row.raw(3))

    if op == "init":
        size = int(_num(ctx, row.raw(4), "ARRAY Init"))
        arrays[name] = [None] * size
        return
    if name not in arrays:
        raise VerbError(f"ARRAY {op}: '{name}' was never initialised")
    index = int(_num(ctx, row.raw(4), f"ARRAY {op}"))
    cells = arrays[name]
    if not (0 <= index < len(cells)):
        raise VerbError(f"ARRAY {op}: index {index} outside '{name}' "
                        f"(size {len(cells)})")
    if op == "store":
        cells[index] = ctx.text(row.raw(5))
    elif op == "get":
        ctx.set_data(row.raw(5), cells[index] if cells[index] is not None else "")
    else:
        raise VerbError(f"ARRAY: unknown operation '{op}' (expected Init, Store or Get)")


# --- files --------------------------------------------------------------

@verb(MODULE, "READTXT", params=[p(2, "path"), p(3, "dest")])
def readtxt(ctx, row):
    """Read a whole text file into a data cell."""
    path = ctx.text(row.raw(2))
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            ctx.set_data(row.raw(3), fh.read())
    except OSError as exc:
        raise VerbError(f"READTXT: cannot read '{path}': {exc}") from exc


def _write_text(ctx, row, mode: str, name: str):
    path = ctx.text(row.raw(2))
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        with open(path, mode, encoding="utf-8") as fh:
            fh.write(ctx.text(row.raw(3)))
    except OSError as exc:
        raise VerbError(f"{name}: cannot write '{path}': {exc}") from exc


@verb(MODULE, "WRITETXT", params=[p(2, "path"), p(3, "content")])
def writetxt(ctx, row):
    """Write a data value to a file, replacing it."""
    _write_text(ctx, row, "w", "WRITETXT")


@verb(MODULE, "APPENDTXT", params=[p(2, "path"), p(3, "content")])
def appendtxt(ctx, row):
    """Append a data value to a file."""
    _write_text(ctx, row, "a", "APPENDTXT")


@verb(MODULE, "DELFILE", params=[p(2, "path")])
def delfile(ctx, row):
    """Delete a file if it exists."""
    path = ctx.text(row.raw(2))
    try:
        if os.path.isdir(path):
            raise VerbError(f"DELFILE: '{path}' is a directory")
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        raise VerbError(f"DELFILE: cannot delete '{path}': {exc}") from exc


@verb(MODULE, "CREATEDIR", params=[p(2, "path")])
def createdir(ctx, row):
    """Create a directory tree if it does not exist."""
    path = ctx.text(row.raw(2))
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        raise VerbError(f"CREATEDIR: cannot create '{path}': {exc}") from exc


@verb(MODULE, "MAKEDIR", params=[p(2, "path")])
def makedir(ctx, row):
    """Alias of CREATEDIR, kept because both names appear in legacy tables."""
    createdir(ctx, row)


@verb(MODULE, "COPYFILE", params=[p(2, "source"), p(3, "dest")])
def copyfile(ctx, row):
    """Copy a file (new in v2 -- tables previously shelled out for this)."""
    src, dst = ctx.text(row.raw(2)), ctx.text(row.raw(3))
    parent = os.path.dirname(os.path.abspath(dst))
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        shutil.copy2(src, dst)
    except OSError as exc:
        raise VerbError(f"COPYFILE: {src} -> {dst}: {exc}") from exc


@verb(MODULE, "JSON", params=[p(2, "op", doc="Load | Get"), p(3, "a"),
                              p(4, "b"), p(5, "dest", required=False)])
def json_verb(ctx, row):
    """``Load path dest`` reads a JSON file; ``Get *src field dest`` pulls a field.

    ``field`` may be dotted (``a.b.c``) to reach into nested objects.
    """
    op = ctx.text(row.raw(2)).lower()
    if op == "load":
        path = ctx.text(row.raw(3))
        try:
            with open(path, "r", encoding="utf-8") as fh:
                ctx.set_data(row.raw(4), fh.read())
        except OSError as exc:
            raise VerbError(f"JSON Load: cannot read '{path}': {exc}") from exc
        except ValueError as exc:
            raise VerbError(f"JSON Load: '{path}' is not valid JSON: {exc}") from exc
        return
    if op == "get":
        try:
            doc = json.loads(ctx.text(row.raw(3)) or "{}")
        except ValueError as exc:
            raise VerbError(f"JSON Get: source is not valid JSON: {exc}") from exc
        node = doc
        for part in ctx.text(row.raw(4)).split("."):
            if not isinstance(node, dict) or part not in node:
                raise VerbError(f"JSON Get: field '{ctx.text(row.raw(4))}' not found")
            node = node[part]
        ctx.set_data(row.raw(5), node if isinstance(node, str) else json.dumps(node))
        return
    raise VerbError(f"JSON: unknown operation '{op}' (expected Load or Get)")


# --- evaluation ---------------------------------------------------------

def _eval_common(ctx, row, result_cells, grid_style, extra):
    """Shared tail of the evaluation verbs: parse kill index and test id."""
    parts = [x.strip() for x in ctx.text(extra).split(",")]
    if len(parts) < 2:
        raise VerbError(
            f"{row.verb}: column 6 must be 'kill_index,test_id', got '{extra}'"
        )
    try:
        kill_index = int(parts[0])
    except ValueError:
        raise VerbError(f"{row.verb}: '{parts[0]}' is not a UUT index") from None
    return kill_index, ",".join(parts[1:])


def _publish(ctx, row, kill_index, test_id, low, high, measured, result, style):
    """Write results, paint the grid, kill on failure -- once, for all evaluators."""
    device = kill_index + 1
    if style == "min":
        values = [test_id, str(device), str(low), str(high), str(measured), result]
    else:
        values = [test_id, str(device), str(low), "-", str(high), str(measured),
                  "-", "-", result]
    ctx.emit(GridEvent(grid=kill_index + 1, op="add", values=values, tag=result))
    _emit_point(ctx, row, test_id, kill_index, result, measured, low, high)
    if result == "FAIL":
        ctx.kill(kill_index, reason=test_id)


@verb(MODULE, "EVAFLOAT",
      params=[p(2, "limits", doc="lower,upper"), p(3, "value"),
              p(4, "result_indexes", doc="value;result;id"),
              p(5, "grid_style", required=False, doc="'min' or blank"),
              p(6, "kill_and_id", doc="kill_index,test_id")])
def evafloat(ctx, row):
    """Judge a float against limits, record it, and kill the UUT on failure."""
    low_s, high_s = _pair(ctx, row.raw(2), "EVAFLOAT limits")
    try:
        low, high = float(low_s), float(high_s)
    except ValueError:
        raise VerbError(f"EVAFLOAT: limits '{row.raw(2)}' are not numbers") from None
    if low > high:
        raise VerbError(f"EVAFLOAT: lower limit {low} exceeds upper limit {high}")

    cells = [c.strip() for c in ctx.text(row.raw(4)).split(";") if c.strip()]
    style = ctx.text(row.raw(5))
    kill_index, test_id = _eval_common(ctx, row, cells, style, row.raw(6))

    raw = ctx.text(row.raw(3))
    try:
        measured = float(raw)
    except (TypeError, ValueError):
        # Unreadable measurement is a failure, not a crash -- same as v1, but
        # without the malformed grid row v1 produced on this path.
        ctx.log(f"{test_id}: '{raw}' is not a number -> FAIL", "fail")
        _store_triplet(ctx, cells, "None", "FAIL", test_id)
        _publish(ctx, row, kill_index, test_id, low, high, "None", "FAIL", style)
        return

    result = "PASS" if low <= measured <= high else "FAIL"
    ctx.log(f"{test_id}: {measured} in [{low}, {high}] -> {result}",
            "pass" if result == "PASS" else "fail")
    _store_triplet(ctx, cells, measured, result, test_id)
    _publish(ctx, row, kill_index, test_id, low, high, measured, result, style)


@verb(MODULE, "EVACSTR",
      params=[p(2, "target"), p(3, "value"),
              p(4, "result_indexes", doc="value;result;id"),
              p(5, "grid_style", required=False),
              p(6, "kill_and_id", doc="kill_index,test_id")])
def evacstr(ctx, row):
    """Judge a string against an expected value."""
    target = ctx.text(row.raw(2))
    measured = ctx.text(row.raw(3))
    cells = [c.strip() for c in ctx.text(row.raw(4)).split(";") if c.strip()]
    style = ctx.text(row.raw(5))
    kill_index, test_id = _eval_common(ctx, row, cells, style, row.raw(6))

    result = "PASS" if target == measured else "FAIL"
    ctx.log(f"{test_id}: '{measured}' vs '{target}' -> {result}",
            "pass" if result == "PASS" else "fail")
    _store_triplet(ctx, cells, measured, result, test_id)
    _publish(ctx, row, kill_index, test_id, target, target, measured, result, style)


@verb(MODULE, "EVALIM",
      params=[p(2, "value"), p(3, "limits", doc="lower,upper"), p(4, "dest"),
              p(5, "jumps", doc="jump_good,jump_bad"), p(6, "arg", required=False)])
def evalim(ctx, row):
    """Limit check that branches instead of killing."""
    low_s, high_s = _pair(ctx, row.raw(3), "EVALIM limits")
    try:
        low, high = float(low_s), float(high_s)
    except ValueError:
        raise VerbError(f"EVALIM: limits '{row.raw(3)}' are not numbers") from None
    measured = _num(ctx, row.raw(2), "EVALIM")
    ok = low <= measured <= high
    if row.has(4):
        ctx.set_data(row.raw(4), "PASS" if ok else "FAIL")
    ctx.log(f"EVALIM: {measured} in [{low}, {high}] -> {'PASS' if ok else 'FAIL'}",
            "pass" if ok else "fail")

    if row.has(5):
        good, bad = _pair(ctx, row.raw(5), "EVALIM jumps")
        target = good if ok else bad
        if target and target != "-":
            ctx.jump(target)


def _store_triplet(ctx, cells, value, result, test_id) -> None:
    """Write value/result/id into however many destination cells were given."""
    payload = [value, result, test_id]
    for cell, item in zip(cells, payload):
        ctx.set_data(cell, item)


REGISTRY.alias_module("Flow", MODULE)
