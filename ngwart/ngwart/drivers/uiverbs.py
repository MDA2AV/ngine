"""UI verbs -- registered as ``UIManager``.

v1 wrote GRID1, GRID2, GRID3 and GRID4 (plus SYNCGRID1..4, GRID1_CONFIG..4 and
GRID1_D..2_D) as separate copy-pasted functions -- 24 functions where there is
one behaviour parameterised by a grid number. Here the implementation is written
once and registered four times.

The verbs emit events rather than touching widgets, so they work identically
under the Qt UI, under a headless run, and in the test suite.
"""

from __future__ import annotations

import functools

from ..engine.errors import VerbError
from ..engine.events import FieldEvent, GridEvent, ProgressEvent, StatusEvent
from ..engine.registry import REGISTRY, Param, VerbSpec, p, verb

MODULE = "UIManager"

_GRID_OPS = {"add", "clear", "place", "unplace"}
_CONFIG_OPS = {"place", "add_columns", "edit_column", "edit_heading", "tag_config"}


# --- grids --------------------------------------------------------------

def _grid(ctx, row, grid: int) -> None:
    """``GRIDn Add const a;b;c;tag`` / ``Add var *l,c,p`` / ``Clear`` / ``Place ...``."""
    op = ctx.text(row.raw(2)).strip().lower()
    if op not in _GRID_OPS:
        raise VerbError(
            f"GRID{grid}: unknown operation '{row.raw(2)}' "
            f"(expected {', '.join(sorted(_GRID_OPS))})"
        )

    if op == "clear":
        ctx.emit(GridEvent(grid=grid, op="clear"))
        return

    if op == "unplace":
        ctx.emit(GridEvent(grid=grid, op="unplace"))
        return

    if op == "place":
        ctx.emit(GridEvent(grid=grid, op="place", config=_place_config(ctx, row, 3)))
        return

    # add
    source = ctx.text(row.raw(3)).strip().lower()
    if source == "const":
        payload = ctx.text(row.raw(4))
    elif source == "var":
        payload = ctx.text(row.raw(4))
    else:
        raise VerbError(f"GRID{grid} Add: expected 'const' or 'var', got '{source}'")

    parts = [x for x in str(payload).split(";")]
    if not parts:
        raise VerbError(f"GRID{grid} Add: nothing to add")
    # v1 convention: the final field is the colour tag, the rest are cell values.
    tag = parts[-1] if len(parts) > 1 else ""
    values = parts[:-1] if len(parts) > 1 else parts
    ctx.emit(GridEvent(grid=grid, op="add", values=values, tag=tag))


def _grid_config(ctx, row, grid: int) -> None:
    """Layout and styling for one grid, applied during <Config>."""
    op = ctx.text(row.raw(2)).strip().lower()
    if op not in _CONFIG_OPS:
        raise VerbError(
            f"GRID{grid}_CONFIG: unknown operation '{row.raw(2)}' "
            f"(expected {', '.join(sorted(_CONFIG_OPS))})"
        )

    if op == "place":
        ctx.emit(GridEvent(grid=grid, op="place", config=_place_config(ctx, row, 3)))
        return

    if op == "add_columns":
        columns = [c.strip() for c in ctx.text(row.raw(3)).split(",") if c.strip()]
        if not columns:
            raise VerbError(f"GRID{grid}_CONFIG Add_Columns: no column names given")
        ctx.emit(GridEvent(grid=grid, op="config",
                           config={"columns": columns}))
        return

    if op == "edit_column":
        parts = [x.strip() for x in ctx.text(row.raw(3)).split(",")]
        if len(parts) < 2:
            raise VerbError(
                f"GRID{grid}_CONFIG Edit_Column: expected 'name,width[,stretch]'")
        ctx.emit(GridEvent(grid=grid, op="config", config={
            "column": parts[0],
            "width": _int_or(parts[1], 100),
            "stretch": bool(_int_or(parts[2], 0)) if len(parts) > 2 else False,
        }))
        return

    if op == "edit_heading":
        parts = [x.strip() for x in ctx.text(row.raw(3)).split(",")]
        if len(parts) < 2:
            raise VerbError(f"GRID{grid}_CONFIG Edit_Heading: expected 'name,text'")
        ctx.emit(GridEvent(grid=grid, op="config",
                           config={"heading": parts[0], "text": parts[1]}))
        return

    # tag_config
    parts = [x.strip() for x in ctx.text(row.raw(3)).split(",")]
    if len(parts) < 2:
        raise VerbError(f"GRID{grid}_CONFIG Tag_Config: expected 'TAG,#rrggbb'")
    ctx.emit(GridEvent(grid=grid, op="config",
                       config={"tag": parts[0], "colour": parts[1]}))


def _place_config(ctx, row, start: int) -> dict:
    keys = ("relx", "rely", "relwidth", "relheight")
    out = {}
    for i, key in enumerate(keys):
        cell = row.raw(start + i)
        if cell:
            try:
                out[key] = float(ctx.text(cell))
            except (TypeError, ValueError):
                raise VerbError(f"Place: '{cell}' is not a fraction") from None
    return out


def _int_or(value: str, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


# Register GRIDn / SYNCGRIDn / GRIDn_CONFIG / GRIDn_D for n in 1..4 from the
# single implementation above.
_GRID_PARAMS = (
    Param(2, "operation", True, "Add | Clear | Place | Unplace"),
    Param(3, "source", False, "const | var (for Add)"),
    Param(4, "payload", False, "';'-separated values, last field is the colour tag"),
    Param(5, "extra", False),
    Param(6, "extra2", False),
)
_CONFIG_PARAMS = (
    Param(2, "operation", True,
          "Place | Add_Columns | Edit_Column | Edit_Heading | Tag_Config"),
    Param(3, "argument", False),
    Param(4, "argument2", False),
    Param(5, "argument3", False),
    Param(6, "argument4", False),
)

for _n in (1, 2, 3, 4):
    for _prefix in ("GRID", "SYNCGRID"):
        REGISTRY.add(VerbSpec(
            module=MODULE, name=f"{_prefix}{_n}",
            fn=functools.partial(_grid, grid=_n),
            params=_GRID_PARAMS,
            doc=f"Result grid {_n}: add rows, clear, or place it.",
        ))
        # The _D ("data") variants behave identically; v1 duplicated them so a
        # table could target a second pair of grids on the detail page.
        if _n <= 2:
            REGISTRY.add(VerbSpec(
                module=MODULE, name=f"{_prefix}{_n}_D",
                fn=functools.partial(_grid, grid=_n),
                params=_GRID_PARAMS, legacy=True,
                doc=f"Alias of {_prefix}{_n}.",
            ))
    REGISTRY.add(VerbSpec(
        module=MODULE, name=f"GRID{_n}_CONFIG",
        fn=functools.partial(_grid_config, grid=_n),
        params=_CONFIG_PARAMS, config_only=True,
        doc=f"Configure result grid {_n}.",
    ))


# --- single fields ------------------------------------------------------

def _field_verb(name: str, field: str, doc: str):
    def impl(ctx, row):
        op = ctx.text(row.raw(2)).strip().lower()
        if op == "clear":
            ctx.field(field, "")
        elif op == "set":
            ctx.field(field, ctx.text(row.raw(3)))
        else:
            # v1's "default" case set the field to the raw argument.
            ctx.field(field, ctx.text(row.raw(2)))

    impl.__name__ = name.lower()
    impl.__doc__ = doc
    REGISTRY.add(VerbSpec(
        module=MODULE, name=name, fn=impl,
        params=(Param(2, "operation", True, "Set | Clear"),
                Param(3, "value", False)),
        doc=doc,
    ))


_field_verb("BCODE1", "barcode1", "First barcode entry.")
_field_verb("BCODE2", "barcode2", "Second barcode entry.")
_field_verb("WID", "worker_id", "Worker/operator id field.")


@verb(MODULE, "STATUS", params=[p(2, "operation", doc="Set | Clear"),
                                p(3, "text", required=False),
                                p(4, "colour", required=False)])
def status(ctx, row):
    """Set the big status banner."""
    op = ctx.text(row.raw(2)).strip().lower()
    if op == "clear":
        ctx.emit(StatusEvent(text="", color=None))
        return
    text = ctx.text(row.raw(3)) if op == "set" else ctx.text(row.raw(2))
    ctx.emit(StatusEvent(text=text, color=ctx.text(row.raw(4)) or None))


@verb(MODULE, "LBOX", params=[p(2, "operation", doc="Clear | <message>")])
def lbox(ctx, row):
    """Clear the log view, or push a literal line into it."""
    op = ctx.text(row.raw(2)).strip().lower()
    if op == "clear":
        ctx.emit(FieldEvent(name="log", value="", color="clear"))
    else:
        ctx.log(ctx.text(row.raw(2)))


@verb(MODULE, "PBAR", params=[p(2, "value", doc="0..1, or -1 for indeterminate")])
def pbar(ctx, row):
    """Drive the progress bar directly."""
    raw = ctx.text(row.raw(2))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise VerbError(f"PBAR: '{raw}' is not a number") from None
    ctx.emit(ProgressEvent(value=value))


@verb(MODULE, "RESETPBARCOLOR")
def reset_pbar_colour(ctx, row):
    """Return the progress bar to its neutral colour."""
    ctx.emit(FieldEvent(name="progress_colour", value="", color=None))


@verb(MODULE, "CMONITOR", params=[p(2, "message"), p(3, "colour", required=False),
                                  p(4, "kill_index", required=False)])
def cmonitor(ctx, row):
    """Current-monitor readout line."""
    index = ctx.text(row.raw(4)) or "1"
    ctx.field(f"monitor{index}", ctx.text(row.raw(2)), ctx.text(row.raw(3)) or None)


REGISTRY.alias_module("UI", MODULE)
