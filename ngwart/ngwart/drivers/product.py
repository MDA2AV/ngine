"""Product-specific validators.

v1 kept these in CargoManager and 1211Manager, where ``VALIDATE_BCODE`` was
byte-for-byte identical between the two files. Written once here and registered
under both module names, so existing <Modules> lines keep working.
"""

from __future__ import annotations

from ..engine.errors import VerbError
from ..engine.events import GridEvent
from ..engine.registry import REGISTRY, p, verb
from ..engine.runrecord import TestPoint

MODULE = "CargoManager"


def _grid_row(ctx, kill_index: int, name: str, expected, measured, result: str) -> None:
    ctx.emit(GridEvent(
        grid=kill_index + 1, op="add", tag=result,
        values=[name, str(kill_index + 1), "-", str(expected), str(measured), result],
    ))


def _fail(ctx, row, cells, kill_index, name, expected, measured) -> None:
    _store(ctx, cells, measured, "FAIL", name)
    _grid_row(ctx, kill_index, name, expected, measured, "FAIL")
    ctx.record.add_point(TestPoint(name=name, uut=kill_index, result="FAIL",
                                   measured=str(measured), low=str(expected),
                                   row=row.index))
    ctx.log(f"{name}: expected {expected}, got {measured} -> FAIL", "fail")
    ctx.kill(kill_index, reason=name)


def _store(ctx, cells, value, result, name) -> None:
    for cell, item in zip(cells, [value, result, name]):
        ctx.set_data(cell, item)


@verb(MODULE, "VALIDATE_DET", params=[p(2, "detection_value")])
def validate_det(ctx, row):
    """Kill whichever UUTs the fixture reports as absent.

    The control board answers the detection poll with ``16 + mask``, where each
    set bit marks a *missing* board. v1 subtracted 16 and killed the set bits.
    """
    raw = ctx.text(row.raw(2))
    try:
        value = int(float(raw)) - 16
    except (TypeError, ValueError):
        raise VerbError(f"VALIDATE_DET: '{raw}' is not a detection value") from None
    if not 0 <= value <= 15:
        raise VerbError(
            f"VALIDATE_DET: detection value {value} is outside 0-15 "
            f"(raw reading was '{raw}')"
        )

    missing = [bit for bit in range(4) if value & (1 << bit)]
    if not missing:
        ctx.log("Detection: all units present.")
        return
    for bit in missing:
        if bit < len(ctx.alive):
            ctx.kill(bit, reason="not detected")
    ctx.log(f"Detection: unit(s) {', '.join(str(b) for b in missing)} absent.", "warn")


@verb(MODULE, "VALIDATE_BCODE",
      params=[p(2, "barcode"), p(3, "result_indexes", doc="value;result;id"),
              p(4, "length"), p(5, "eng_level"), p(6, "kill_index")])
def validate_bcode(ctx, row):
    """Check a barcode's length and engineering-level prefix."""
    barcode = str(ctx.text(row.raw(2)) or "")
    cells = [c.strip() for c in ctx.text(row.raw(3)).split(";") if c.strip()]
    try:
        target_length = int(float(ctx.text(row.raw(4))))
        kill_index = int(float(ctx.text(row.raw(6))))
    except (TypeError, ValueError):
        raise VerbError(
            "VALIDATE_BCODE: length and kill_index must be whole numbers") from None
    target_level = ctx.text(row.raw(5))

    if len(barcode) != target_length:
        _fail(ctx, row, cells, kill_index, "BCODE Length",
              target_length, len(barcode))
        return

    level = barcode[:len(target_level)] if target_level else ""
    if target_level and level != target_level:
        _fail(ctx, row, cells, kill_index, "BCODE Eng Level", target_level, level)
        return

    _store(ctx, cells, barcode, "PASS", "Bcode")
    _grid_row(ctx, kill_index, "BCODE", target_level or target_length, barcode, "PASS")
    ctx.record.add_point(TestPoint(name="BCODE", uut=kill_index, result="PASS",
                                   measured=barcode, row=row.index))
    ctx.record.set_barcode(kill_index, barcode)
    ctx.log(f"Barcode {barcode} accepted for UUT {kill_index}.", "pass")


@verb(MODULE, "VALIDATE",
      params=[p(2, "expected_points", required=False),
              p(3, "result_index", required=False)])
def validate(ctx, row):
    """Final per-UUT verdict, derived from the recorded test points.

    v1 re-read a hard-coded list of data coordinates per product to work out
    whether a unit passed -- so the list had to be edited whenever the test plan
    changed, and any point written after the coordinate was reused was lost.
    Here the verdict comes from the run record, so it is correct by construction
    and product-independent.
    """
    expected = None
    if row.has(2):
        try:
            expected = int(float(ctx.text(row.raw(2))))
        except (TypeError, ValueError):
            raise VerbError(
                f"VALIDATE: '{row.raw(2)}' is not a point count") from None

    verdicts: dict[int, bool] = {}
    for uut in range(len(ctx.alive)):
        points = ctx.record.points_for(uut)
        failed = [pt for pt in points if pt.result == "FAIL"]
        enough = expected is None or len(points) >= expected
        alive = ctx.alive[uut] == 1
        ok = alive and not failed and points and enough

        verdicts[uut] = ok
        detail = (f"{len(points)} point(s)"
                  + (f", {len(failed)} failed" if failed else "")
                  + ("" if alive else ", killed")
                  + ("" if enough else f", expected {expected}"))
        ctx.log(f"UUT {uut}: {'PASS' if ok else 'FAIL'} ({detail})",
                "pass" if ok else "fail")
        if not ok and alive:
            ctx.kill(uut, reason="final validation")

    if row.has(3):
        ctx.set_data(row.raw(3), ";".join(
            f"{u}={'PASS' if v else 'FAIL'}" for u, v in sorted(verdicts.items())))


REGISTRY.alias_module("1211Manager", MODULE)
REGISTRY.alias_module("Cargo", MODULE)
