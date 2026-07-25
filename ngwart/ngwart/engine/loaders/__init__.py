"""Program loaders.

``load(path)`` dispatches on extension:

    .ods            legacy spreadsheet (read via ods.py, no pandas)
    .txt            legacy '$'-separated export
    .csv            comma-separated, same 10-column layout
    .yaml / .yml    native v2 format -- git-diffable, supports <Vars>/<Teardown>

All four produce the same Program object, so the engine neither knows nor
cares which one an operator loaded.
"""

from __future__ import annotations

import csv
import io
import os

from ..errors import LoaderError
from ..program import NCOLS, Program, Row
from . import native, ods

__all__ = ["load", "load_rows", "save", "detect_format", "ods", "native"]

LEGACY_EXTS = {".ods", ".txt", ".csv"}
NATIVE_EXTS = {".yaml", ".yml", ".ngw"}


def detect_format(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in NATIVE_EXTS:
        return "native"
    if ext in LEGACY_EXTS:
        return ext.lstrip(".")
    raise LoaderError(
        f"unsupported program format '{ext}' -- expected one of "
        f"{', '.join(sorted(LEGACY_EXTS | NATIVE_EXTS))}"
    )


def load(path: str) -> Program:
    """Load any supported program file into a finalised Program."""
    if not os.path.exists(path):
        raise LoaderError(f"program file not found: {path}")

    kind = detect_format(path)
    if kind == "native":
        program = native.load(path)
    else:
        program = Program(rows=load_rows(path), source=path)
    program.source = path
    if not program.meta.get("name"):
        program.meta["name"] = os.path.splitext(os.path.basename(path))[0]
    return program.finalize()


def load_rows(path: str) -> list[Row]:
    """Read a legacy table into normalised 10-column Rows."""
    kind = detect_format(path)
    if kind == "ods":
        grid = ods.read_ods(path)
    elif kind == "txt":
        grid = _read_dollar_txt(path)
    elif kind == "csv":
        grid = _read_csv(path)
    else:
        raise LoaderError(f"'{path}' is not a legacy table")

    grid = _strip_header(grid)
    return _normalise(grid)


def _read_dollar_txt(path: str) -> list[list[str]]:
    """v1's ``odsTableToTxt`` export: cells joined by '$', '-$' for empty."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    grid = []
    for line in lines:
        cells = line.split("$")
        if cells and cells[-1] == "":
            cells.pop()
        grid.append([("" if c == "-" else c).strip() for c in cells])
    return grid


def _read_csv(path: str) -> list[list[str]]:
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        sample = fh.read(8192)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return [[c.strip() for c in row] for row in csv.reader(fh, dialect)]


def _strip_header(grid: list[list[str]]) -> list[list[str]]:
    """Drop the ``C0,C1,...`` header row if present.

    v1's ODS path consumed it implicitly (pandas treats row 0 as column names)
    while its .txt path did not -- a genuine inconsistency between the two
    loaders. Detecting the header explicitly makes both paths agree, and a
    table that opens straight into a section marker still works.
    """
    if not grid:
        return grid
    first = [c.strip() for c in grid[0]]
    if not first:
        return grid[1:]
    head = first[0]
    if head.startswith("<"):
        return grid            # no header; starts with a section marker
    if head.upper() in {"C0", "#", "ID", "MODULE"} or not head:
        return grid[1:]
    return grid


def _normalise(grid: list[list[str]]) -> list[Row]:
    """Pad/trim every row to the 10-column layout.

    Some legacy tables carry a leading index column (11+ cells); v1 detected
    this with ``len(words) < 12`` and shifted. Same rule here, expressed once.
    """
    rows: list[Row] = []
    for i, cells in enumerate(grid):
        cells = [("" if c is None else str(c)).strip() for c in cells]
        if len(cells) > NCOLS + 1:
            cells = cells[1:]                      # drop leading index column
        cells = [("" if c == "-" else c) for c in cells]
        cells = (cells + [""] * NCOLS)[:NCOLS]
        rows.append(Row(index=len(rows), cells=cells, source_line=i + 1))
    return rows


def save(program: Program, path: str) -> None:
    """Write a Program out in whichever format `path` implies."""
    kind = detect_format(path)
    if kind == "native":
        native.save(program, path)
        return
    grid = [["C0", "C1", "C2", "C3", "C4", "C5", "C6",
             "EXCEPTION", "ALIVE", "COMMENT/COLOR"]]
    grid.extend(list(r.cells) for r in program.rows)
    if kind == "ods":
        ods.write_ods(path, grid, sheet_name=program.meta.get("name", "Sheet1"))
    elif kind == "csv":
        with open(path, "w", encoding="utf-8", newline="") as fh:
            csv.writer(fh).writerows(grid)
    elif kind == "txt":
        buf = io.StringIO()
        for row in grid[1:]:
            buf.write("$".join(c if c else "-" for c in row) + "$\n")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(buf.getvalue())
