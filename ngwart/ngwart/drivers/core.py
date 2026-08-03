"""Core state verbs -- registered under the module name ``TestData``.

Legacy tables call these without declaring them in <Modules> (v1 reached them
through ``globals()["TestData"]``), so the module name is matched literally.
"""

from __future__ import annotations

import os

from ..engine.errors import VerbError
from ..engine.registry import p, verb


@verb("TestData", "initAlive", params=[p(2, "count", doc="number of UUTs on the fixture")],
      config_only=True)
def init_alive(ctx, row):
    """Size the alive mask."""
    raw = ctx.text(row.raw(2))
    try:
        count = int(float(raw))
    except ValueError:
        raise VerbError(f"initAlive: '{raw}' is not a whole number") from None
    if count <= 0:
        raise VerbError(f"initAlive: need at least one UUT, got {count}")
    ctx.init_alive(count)
    ctx.log(f"Alive mask initialised with {count} unit(s).")


@verb("TestData", "updateLabels", config_only=True)
def update_labels(ctx, row):
    """Index the program's labels.

    Kept for table compatibility only -- v2 builds the label index at load time,
    so this is a no-op that reports what was already found. v1 rescanned the
    whole table here on every run.
    """
    labels = ctx.program.labels
    ctx.log(f"Labels indexed: {len(labels)}")
    start, end = ctx.program.span
    ctx.log(f"Test span: {end - start} rows")


@verb("TestData", "STARTALIVE")
def start_alive(ctx, row):
    """Bring every UUT back to alive, and start a new board.

    A looping table runs this at the top of each pass, so it is also where
    one board ends and the next begins -- and the verdict has to be about
    the board on the fixture, not every board the run has seen.
    """
    if not ctx.alive:
        raise VerbError("STARTALIVE: alive mask not sized -- call initAlive first")
    ctx.start_alive()
    if ctx.record is not None:
        ctx.record.begin_cycle()
    ctx.log("All units alive.")


@verb("TestData", "AKILL", params=[p(2, "targets", doc="comma-separated UUT indices")])
def akill(ctx, row):
    """Kill one or more UUTs."""
    targets = [t.strip() for t in ctx.text(row.raw(2)).split(",") if t.strip()]
    if not targets:
        raise VerbError("AKILL: no targets given")
    for target in targets:
        try:
            index = int(target)
        except ValueError:
            raise VerbError(f"AKILL: '{target}' is not a UUT index") from None
        ctx.kill(index, reason=row.comment or "AKILL")


@verb("TestData", "INITDATA",
      params=[p(2, "lines"), p(3, "cols"), p(4, "pages"),
              p(5, "program_from", required=False,
                doc="first page of the program region, which is never cleared")])
def init_data(ctx, row):
    """Allocate the data store, optionally reserving a program region.

    Column 5 is new in v2 and additive: a table that omits it behaves exactly
    as v1 did, clearing everything. Giving it names the first page of the
    *program* region -- constants the table loads once and needs for the whole
    session, which a per-board re-init must not wipe.
    """
    try:
        lines, cols, pages = (int(float(ctx.text(row.raw(i)))) for i in (2, 3, 4))
    except ValueError as exc:
        raise VerbError(f"INITDATA: dimensions must be whole numbers ({exc})") from None
    if min(lines, cols, pages) <= 0:
        raise VerbError(f"INITDATA: dimensions must be positive, got "
                        f"{lines}x{cols}x{pages}")

    preserve = None
    if row.has(5):
        try:
            preserve = int(float(ctx.text(row.raw(5))))
        except ValueError:
            raise VerbError(
                f"INITDATA: program region '{row.raw(5)}' is not a page number"
            ) from None
        if not 0 <= preserve <= pages:
            raise VerbError(
                f"INITDATA: program region starts at page {preserve}, outside "
                f"the {pages} pages allocated")

    ctx.init_data(lines, cols, pages, preserve)
    detail = ""
    if preserve is not None:
        kept = pages - preserve
        detail = (f"; pages {preserve}-{pages - 1} are program data "
                  f"({kept} page(s) kept)")
    ctx.log(f"Data initialised: {lines} lines, {cols} cols, {pages} pages{detail}.")


@verb("TestData", "SETDATACODES",
      params=[p(2, "datecode_index"), p(3, "extended_index")])
def set_datacodes(ctx, row):
    """Stamp the run date/time and store both codes."""
    datecode, extended = ctx.set_datecodes()
    ctx.set_data(row.raw(2), datecode)
    ctx.set_data(row.raw(3), extended)
    ctx.log(f"Datecode: {datecode}  Extended: {extended}")


@verb("TestData", "LOG_FLAG", params=[p(2, "state", doc="ON or OFF")])
def log_flag(ctx, row):
    """Silence or restore the operator log.

    Tables use this around polling loops that would otherwise flood the view.
    """
    state = ctx.text(row.raw(2)).strip().upper()
    if state not in ("ON", "OFF"):
        raise VerbError(f"LOG_FLAG: expected ON or OFF, got '{state}'")
    ctx.log_enabled = state == "ON"
    if ctx.log_enabled:
        ctx.log("Logging resumed.")


@verb("TestData", "SAVELOG", params=[p(2, "path")])
def save_log(ctx, row):
    """Write the operator log to disk."""
    path = ctx.text(row.raw(2))
    _ensure_parent(path)
    lines = [
        f"{e.get('at', '')}{e['message']}" if isinstance(e, dict) else str(e)
        for e in _log_lines(ctx)
    ]
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError as exc:
        raise VerbError(f"SAVELOG: cannot write '{path}': {exc}") from exc
    ctx.log(f"Log saved to {path}")


@verb("TestData", "SAVEDATA", params=[p(2, "path")])
def save_data(ctx, row):
    """Dump the data store, one line per populated cell.

    v1 hard-coded three columns here and silently dropped anything in column 3
    or beyond. This walks the real dimensions.
    """
    path = ctx.text(row.raw(2))
    if ctx.data is None:
        raise VerbError("SAVEDATA: data store not initialised")
    _ensure_parent(path)
    lines_n, cols_n, pages_n = ctx.dims
    out = []
    for page in range(pages_n):
        out.append(f"PAGE {page}::")
        for line in range(lines_n):
            cells = [ctx.data[line][c][page] for c in range(cols_n)]
            if all(c is None for c in cells):
                continue
            rendered = "\t|| ".join(
                f"[{line},{c},{page}]: {'-' if cells[c] is None else cells[c]}"
                for c in range(cols_n)
            )
            out.append(rendered)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(out) + "\n")
    except OSError as exc:
        raise VerbError(f"SAVEDATA: cannot write '{path}': {exc}") from exc
    ctx.log(f"Data saved to {path}")


@verb("TestData", "SAVEREPORT", params=[p(2, "path"), p(3, "format", required=False)])
def save_report(ctx, row):
    """Write the structured run record (new in v2).

    ``format`` is json (default) or xml. The XML matches the shape v1 hand-built
    in CargoManager, but is generated from the recorded test points rather than
    by re-reading the data store, so nothing overwritten mid-run is lost.
    """
    from ..reports import write_report

    path = ctx.text(row.raw(2))
    fmt = (ctx.text(row.raw(3)) or "json").lower()
    _ensure_parent(path)
    try:
        write_report(ctx.record, path, fmt)
    except ValueError as exc:
        raise VerbError(f"SAVEREPORT: {exc}") from exc
    except OSError as exc:
        raise VerbError(f"SAVEREPORT: cannot write '{path}': {exc}") from exc
    ctx.log(f"Report ({fmt}) saved to {path}")


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            raise VerbError(f"cannot create directory '{parent}': {exc}") from exc


def _log_lines(ctx) -> list:
    """Best-effort recovery of the operator log for SAVELOG.

    The engine does not retain the log itself (the UI owns it), so fall back to
    the run record, which holds every step regardless of who was listening.
    """
    if ctx.record is None:
        return []
    return [f"{s.started} [{s.row}] {s.module}.{s.verb} -> {s.outcome}"
            f"{': ' + s.detail if s.detail else ''}"
            for s in ctx.record.steps]
