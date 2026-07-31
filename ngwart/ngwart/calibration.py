"""Teach contour coordinates by clicking them.

Every optical test carries a nominal ``cx,cy`` in its arguments: ``EVALCONT``
and ``EVALCONTN`` in column 3 as ``cx,cy,tol,minarea,cal``, ``EVALLEDS`` as
``cx,cy,crop,threshold``, ``MEASCONT`` as ``cx,cy,tol``. In cargo.ods the
tolerance is 10 px and the LEDs sit 17 px apart.

Nudge the camera, re-seat the fixture or change a lens, and every one of those
windows misses at once -- 48 coordinates in one table, all wrong by the same few
pixels, each reported as

    INTENSITY_A: no contour within 10px of (895, 659)

which reads like 48 dead LEDs rather than one moved camera.

Re-teaching by hand means pulling a centroid out of a debug bundle and retyping
it once per site. This module is the machine-readable half of doing it by
clicking instead:

* it finds every coordinate site a program declares, grouped by **physical
  location** rather than by test -- one LED is one place on the board, even
  though an intensity check, an off-check and a colour check all point at it;
* it resolves a click to the contour under it using the *same* selection rule
  and noise floor the runtime uses, so a site can never be taught to a blob the
  test would then refuse to see;
* it writes what was taught, against which rows, in a file phase 2 applies.

Nothing here imports Qt. ``ui/calibration_window.py`` is a view over these objects and
the tests drive them headlessly.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime

from .drivers.imageproc import MIN_CONTOUR_PIXELS
from .engine.errors import LoaderError
from .engine.program import Program

#: Bumped when the on-disk shape changes in a way a reader must notice.
FORMAT_VERSION = 1


# --- what a verb keeps where --------------------------------------------

@dataclass(frozen=True)
class Layout:
    """Where a verb keeps its coordinate, and what shares the cell.

    ``fields`` is the whole cell, not just the coordinate: rewriting a site must
    preserve the tolerance, minimum area and calibration factor that follow it.
    Those were qualified against real boards and are not ours to touch.
    """

    column: int
    fields: tuple[str, ...]
    #: ';'-separated groups in one cell. EVALLEDS accepts several LEDs per row;
    #: cargo.ods writes one, but the parser must not assume that.
    multi: bool = False


COORD_VERBS: dict[str, Layout] = {
    "EVALCONT": Layout(3, ("cx", "cy", "tol", "minarea", "cal")),
    "EVALCONTN": Layout(3, ("cx", "cy", "tol", "minarea", "cal")),
    "MEASCONT": Layout(3, ("cx", "cy", "tol")),
    "EVALLEDS": Layout(3, ("cx", "cy", "crop", "threshold"), multi=True),
}

#: Carries coordinates too, but as parallel lists across columns 3 and 4.
#: Reported rather than parsed: rewriting one entry of a list is a different
#: edit from replacing a cell, and dropping the row silently would leave a site
#: untaught with nothing said about it.
LIST_VERBS = ("EVALCONTS",)

#: Verbs whose column 4 names the cell they write, used to walk a pipeline back
#: from contours to the colour frame the operator should actually look at.
_DEST_COLUMN = 4
_SOURCE_COLUMN = 2


# --- the model ----------------------------------------------------------

def setter_dest(row) -> str:
    """The cell a row writes, or '' if it writes none.

    These are how a table keeps a coordinate in one place instead of a hundred.
    ``JSON`` needs looking at because its destination column depends on the
    operation -- ``Load`` writes column 4, ``Get`` writes column 5.
    """
    verb = row.verb.upper()
    if verb in ("STORE", "STOREF"):
        return row.raw(3)
    if verb == "JSON":
        op = row.raw(2).strip().lower()
        if op == "load":
            return row.raw(4)
        if op == "get":
            return row.raw(5)
    return ""

#: How deep to follow a chain of setters before giving up. A table that writes a
#: cell from itself would otherwise spin.
_TRACE_DEPTH = 6


@dataclass(frozen=True)
class Use:
    """One row that *reads* a site's coordinate.

    Separate from Ref because once a coordinate lives in a variable the row that
    holds it and the rows that consume it are different rows. The consumers give
    the site its name; only the holder gets rewritten.
    """

    row: int
    verb: str
    test_id: str
    uut: int | None


@dataclass(frozen=True)
class Ref:
    """One place in the program where a coordinate is written."""

    row: int
    module: str
    verb: str
    column: int
    #: Index within a ';'-separated cell; 0 for the single-group verbs.
    group: int
    #: The cell exactly as it stands, so phase 2 can diff against it and refuse
    #: to write if the table changed under the calibration.
    cell: str
    test_id: str
    uut: int | None
    #: Key in the values file, when the value lives outside the table.
    cell_key: str = ""

    def rewritten(self, cx: int, cy: int) -> str:
        """This cell with the coordinate replaced and everything else kept."""
        groups = self.cell.split(";") if self.group or ";" in self.cell else [self.cell]
        parts = [p.strip() for p in groups[self.group].split(",")]
        if len(parts) < 2:
            return self.cell
        parts[0], parts[1] = str(cx), str(cy)
        groups[self.group] = ",".join(parts)
        return ";".join(groups)


@dataclass
class Site:
    """One physical location on the board, and every row that points at it."""

    uut: int | None
    cx: int
    cy: int
    tol: float
    #: Rows to rewrite. One entry when the coordinate lives in a variable.
    refs: list[Ref] = field(default_factory=list)
    #: Rows that read it. Same rows as `refs` when the coordinate is written
    #: inline, a different (larger) set once it has been factored into a <Vars>
    #: entry.
    uses: list[Use] = field(default_factory=list)

    #: Set when the coordinate lives in a file rather than in the table: the
    #: dotted key the program looks up, and the file it loads.
    file_key: str = ""
    file_path: str = ""
    #: False when the table declares this site but the file has no entry yet --
    #: a first cal. cx/cy are then 0 and mean nothing.
    known: bool = True

    #: Filled in by the operator. None until the site has been taught.
    taught: tuple[int, int] | None = None
    area: float | None = None
    note: str = ""

    @property
    def key(self) -> tuple:
        return (self.uut, self.cx, self.cy)

    @property
    def in_file(self) -> bool:
        return bool(self.file_key)

    @property
    def tests(self) -> list[str]:
        """Every test id that depends on this location, in row order."""
        seen: list[str] = []
        for use in self.uses or []:
            if use.test_id and use.test_id not in seen:
                seen.append(use.test_id)
        if seen:
            return seen
        for ref in self.refs:
            if ref.test_id and ref.test_id not in seen:
                seen.append(ref.test_id)
        return seen

    @property
    def name(self) -> str:
        """What to call this site.

        A site read from a table is named by the tests that depend on it. A
        free-form site has no tests, so the operator's own label is the name --
        without this the typed name would show until the next table refresh and
        then revert to the coordinate.
        """
        if self.tests:
            return " / ".join(self.tests)
        return self.note or f"({self.cx},{self.cy})"

    @property
    def label(self) -> str:
        unit = f"UUT{self.uut}" if self.uut is not None else "--"
        return f"{unit}  {self.name}"

    @property
    def delta(self) -> tuple[int, int] | None:
        """How far the taught point sits from the value already recorded.

        None when there is nothing to compare against -- either untaught, or a
        site whose key has no entry yet, where a delta would be measured from a
        coordinate nobody ever declared.
        """
        if self.taught is None or not self.known:
            return None
        return self.taught[0] - self.cx, self.taught[1] - self.cy

    @property
    def drift(self) -> float | None:
        d = self.delta
        return None if d is None else (d[0] ** 2 + d[1] ** 2) ** 0.5

    @property
    def within_tolerance(self) -> bool | None:
        """Whether the old window would still have found the taught point.

        A site that is already inside tolerance did not need teaching, and
        saying so lets an operator tell "the camera moved" from "this one LED is
        dark" -- which look identical in a log full of NOT_FOUND.
        """
        d = self.delta
        if d is None:
            return None
        return abs(d[0]) <= self.tol and abs(d[1]) <= self.tol

    def teach(self, cx: int, cy: int, area: float | None = None) -> None:
        self.taught = (int(cx), int(cy))
        self.area = area

    def clear(self) -> None:
        self.taught = None
        self.area = None


# --- reading sites out of a program -------------------------------------

def _int(text: str) -> int | None:
    try:
        return int(float(str(text).strip()))
    except (TypeError, ValueError):
        return None


def _float(text: str, default: float = 0.0) -> float:
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return default


def _tol_from_spec(program: Program, cell: str, writers: dict) -> float:
    """The search window a referenced spec carries.

    Where it lives depends on how the table holds the coordinate: in the value
    itself when a variable carries the whole spec, or in the STOREF template
    when a STORE row holds only ``cx,cy``. Taking it from the right place keeps
    the drawn window honest instead of falling back to a guess -- cargo's
    INTENSITY_G sites use 5 px where every other site uses 10.
    """
    name = cell.strip().lstrip("*")
    if name in program.var_values:
        parts = [p.strip() for p in str(program.var_values[name]).split(",")]
        return _float(parts[2], 10.0) if len(parts) > 2 else 10.0

    row = writers.get(name)
    if row is None:
        return 10.0
    value = row.raw(2)
    if row.verb.upper() == "STOREF":
        tail = value.split(";")[0]
        parts = [p.strip() for p in tail.split(",")]
        # '%0,10,50,1' -- %0 stands for cx,cy, so the window is the next field.
        for part in parts:
            if part.startswith("%"):
                continue
            found = _float(part, 0.0)
            if found:
                return found
        return 10.0
    parts = [p.strip() for p in value.split(",")]
    return _float(parts[2], 10.0) if len(parts) > 2 else 10.0


def _test_id(row) -> tuple[int | None, str]:
    """Column 6 as ``kill_index,test_id``, matching imageproc._kill_and_id."""
    if not row.has(6):
        return None, row.comment or row.verb
    parts = [x.strip() for x in row.raw(6).split(",")]
    if len(parts) < 2:
        return None, row.comment or row.verb
    return _int(parts[0]), parts[1]


@dataclass(frozen=True)
class Origin:
    """Where a referenced coordinate is actually written down.

    Two kinds, because a table can hold its coordinates either way:

    * ``cell`` -- a STORE row in the table carries the literal. Re-teaching
      edits the table.
    * ``file`` -- a JSON Get pulls it from a coordinates file loaded at
      startup. Re-teaching rewrites the file and the table is never touched.
    """

    kind: str                 # "cell" | "file"
    row: int
    module: str
    verb: str
    column: int
    cell: str
    cx: int | None = None
    cy: int | None = None
    #: file kind only: the dotted key, and the path it was loaded from.
    key: str = ""
    path: str = ""


def _setter_index(program: Program) -> dict:
    """cell name -> the row that writes it."""
    writers = {}
    for row in program.rows:
        if not row.module or not row.verb:
            continue
        dest = setter_dest(row).strip().lstrip("*")
        if dest:
            writers.setdefault(dest, row)
    return writers


def _storef_source(cell: str) -> str | None:
    """The cell a STOREF template reads for ``%0``.

    ``'%0,10,50,1;*led.u0.a.xy'`` -> ``'*led.u0.a.xy'``. The tail after %0 is
    the window, which belongs to the consuming verb and is left alone.
    """
    parts = cell.split(";")
    for arg in parts[1:]:
        arg = arg.strip()
        if arg.startswith("*"):
            return arg
    return None


def trace_origin(program: Program, cell: str,
                 writers: dict | None = None) -> Origin | None:
    """Follow ``*ref`` back to the row that writes a literal coordinate.

    A table that has factored its coordinates into variables reads

        EVALCONT  *led.u0.a.cont          <- consumes
        STOREF    '%0,10,50,1;*led.u0.a.xy' -> *led.u0.a.cont
        STORE     '895,659'                 -> *led.u0.a.xy   <- the one truth

    so the teachable row is the STORE, and rewriting it fixes every verb that
    reads through it. Returns None when the chain does not end in a literal --
    a coordinate genuinely computed at run time cannot be taught.
    """
    writers = writers if writers is not None else _setter_index(program)
    name = cell.strip().lstrip("*")

    for _ in range(_TRACE_DEPTH):
        # A variable that names a key takes its value from the values file.
        # This is the shortest chain there is -- no rows involved at all -- so
        # it is checked first.
        key = program.var_sources.get(name)
        if key:
            value = program.var_values.get(name, "")
            bits = [b.strip() for b in str(value).split(",")]
            cx = _int(bits[0]) if bits and bits[0] else None
            cy = _int(bits[1]) if len(bits) > 1 else None
            return Origin(kind="file", row=_vars_row(program, name),
                          module="", verb="<Vars>", column=2, cell=str(value),
                          cx=cx, cy=cy, key=key,
                          path=program.values_path or program.values_source)

        row = writers.get(name)
        if row is None:
            return None
        verb = row.verb.upper()
        value = row.raw(2)

        if verb == "STOREF":
            source = _storef_source(value)
            if source is None:
                return None
            name = source.lstrip("*")
            continue

        if verb == "JSON" and value.strip().lower() == "get":
            # The coordinate lives outside the table. The field is column 4;
            # the file is whatever JSON Load read into the document cell.
            key = row.raw(4).strip()
            path = _json_source_path(row.raw(3), writers)
            if not key:
                return None
            return Origin(kind="file", row=row.index, module=row.module,
                          verb=row.verb, column=4, cell=key,
                          key=key, path=path)

        # STORE: either the literal, or another reference to follow.
        if value.startswith("*"):
            name = value.lstrip("*")
            continue

        parts = [p.strip() for p in value.split(",")]
        cx = _int(parts[0]) if parts else None
        cy = _int(parts[1]) if len(parts) > 1 else None
        if cx is None or cy is None:
            return None
        return Origin(kind="cell", row=row.index, module=row.module,
                      verb=row.verb, column=2, cell=value, cx=cx, cy=cy)
    return None


def _vars_row(program: Program, name: str) -> int:
    """The <Vars> row declaring `name`, so a finding can point at it."""
    for i in program.body("Vars"):
        if program.rows[i].module == name:
            return i
    return -1


def _json_source_path(doc_cell: str, writers: dict) -> str:
    """The file a JSON Get is ultimately reading, via its JSON Load."""
    name = doc_cell.strip().lstrip("*")
    for _ in range(_TRACE_DEPTH):
        row = writers.get(name)
        if row is None:
            return ""
        if row.verb.upper() == "JSON" and row.raw(2).strip().lower() == "load":
            return row.raw(3).strip()
        source = row.raw(2).strip()
        if not source.startswith("*"):
            return source
        name = source.lstrip("*")
    return ""


def read_coords(path: str) -> dict:
    """The coordinates file as a flat {dotted key: 'cx,cy'} map.

    Missing or unreadable is not an error here: teaching a fixture for the
    first time is exactly the case where the file does not exist yet.
    """
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {}

    flat: dict[str, str] = {}

    def walk(node, prefix=""):
        if isinstance(node, dict):
            for k, v in node.items():
                if str(k).startswith("_"):
                    continue                       # metadata, not a coordinate
                walk(v, f"{prefix}.{k}" if prefix else str(k))
        elif isinstance(node, str):
            flat[prefix] = node

    walk(doc)
    return flat


def write_coords(path: str, sites: list, meta: dict | None = None) -> str:
    """Update the values file the program loads, in place.

    **Merged, never replaced.** A calibration covers the sites its own frame can
    show -- the bright indicators at one exposure, the dim one at another -- so
    the window holds a subset of what the table declares. Writing only that
    subset would delete every other key, and the next run would abort on the
    first missing one. So the file is read, the taught keys are updated, and
    everything else stays exactly as it was.

    Flat, keyed by variable name. Each key keeps its own tail: EVALCONT's
    ``cx,cy,tol,minarea,cal`` and EVALLEDS's ``cx,cy,crop,threshold`` are the
    same point in two shapes, and only the point moves.
    """
    doc: dict = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
            if isinstance(existing, dict):
                doc = {k: v for k, v in existing.items()
                       if not str(k).startswith("_")}
        except (OSError, ValueError):
            doc = {}

    for site in sites:
        point = site.taught or ((site.cx, site.cy) if site.known else None)
        for ref in site.refs:
            if not ref.cell_key:
                continue
            doc[ref.cell_key] = (ref.rewritten(*point) if point else ref.cell)

    if meta:
        doc["_calibration"] = dict(meta)

    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path


def sites_from_program(program: Program) -> tuple[list[Site], list[str]]:
    """Every teachable coordinate in a program, grouped by location.

    Returns (sites, notes). Notes name what could *not* be read -- a coordinate
    held in a data cell, or an EVALCONTS row -- because a site missing from this
    list is a test that silently keeps its old coordinate.
    """
    sites: dict[tuple, Site] = {}
    notes: list[str] = []
    writers = _setter_index(program)
    coord_cache: dict[str, dict] = {}
    missing: set[tuple[str, str]] = set()

    for row in program.rows:
        verb = row.verb.upper()

        if verb in LIST_VERBS:
            notes.append(
                f"row {row.index}: {row.verb} keeps its coordinates as parallel "
                f"lists across columns 3 and 4 -- set those by hand for now")
            continue

        layout = COORD_VERBS.get(verb)
        if layout is None:
            continue

        cell = row.raw(layout.column)
        if not cell:
            continue

        if cell.startswith("*"):
            # The table keeps this coordinate in a variable. Follow it to the
            # row that writes it: that row is the single place a re-teach has
            # to change, however many verbs read through it.
            origin = trace_origin(program, cell, writers)
            if origin is None:
                notes.append(
                    f"row {row.index}: {row.verb} takes its coordinate from "
                    f"{cell}, which is computed at run time and cannot be taught")
                continue

            uut, test_id = _test_id(row)
            # The window belongs to whoever reads it, not to the row that holds
            # the point.
            tol = _tol_from_spec(program, cell, writers)

            cx, cy = origin.cx, origin.cy
            if origin.kind == "file" and cx is None:
                # A JSON Get chain, where the value is not in the program model.
                if origin.path not in coord_cache:
                    coord_cache[origin.path] = read_coords(
                        _resolve_path(program, origin.path))
                current = coord_cache[origin.path].get(origin.key, "")
                bits = [b.strip() for b in current.split(",")]
                cx = _int(bits[0]) if bits and bits[0] else None
                cy = _int(bits[1]) if len(bits) > 1 else None
            if origin.kind == "file" and cx is None:
                missing.add((origin.path, origin.key))

            # Grouped by physical location only. One LED is one place even
            # though EVALCONT and EVALLEDS read it through two different keys
            # -- and both keys have to move together, so both are refs here.
            group_key = (uut, cx, cy)
            site = sites.get(group_key)
            if site is None:
                site = sites[group_key] = Site(
                    uut=uut,
                    cx=cx if cx is not None else 0,
                    cy=cy if cy is not None else 0,
                    tol=tol,
                    file_key=origin.key,
                    file_path=origin.path,
                    known=cx is not None)
            if origin.key not in {r.cell_key for r in site.refs}:
                site.refs.append(Ref(
                    row=origin.row, module=origin.module, verb=origin.verb,
                    column=origin.column, group=0, cell=origin.cell,
                    test_id=test_id, uut=uut, cell_key=origin.key))
            site.tol = min(site.tol, tol)
            site.uses.append(Use(row=row.index, verb=row.verb,
                                 test_id=test_id, uut=uut))
            continue

        uut, test_id = _test_id(row)
        groups = cell.split(";") if layout.multi else [cell]

        for index, group in enumerate(groups):
            if not group.strip():
                continue
            parts = [p.strip() for p in group.split(",")]
            cx, cy = _int(parts[0] if parts else ""), _int(
                parts[1] if len(parts) > 1 else "")
            if cx is None or cy is None:
                notes.append(
                    f"row {row.index}: {row.verb} coordinate '{group.strip()}' "
                    f"is not 'cx,cy,...'")
                continue

            # Field 2 is the search tolerance for the CONT verbs and the crop
            # radius for EVALLEDS. Both answer "how far off may this be", which
            # is what the operator needs drawn.
            tol = _float(parts[2], 10.0) if len(parts) > 2 else 10.0

            ref = Ref(row=row.index, module=row.module, verb=row.verb,
                      column=layout.column, group=index if layout.multi else 0,
                      cell=cell, test_id=test_id, uut=uut)

            key = (uut, cx, cy)
            site = sites.get(key)
            if site is None:
                site = sites[key] = Site(uut=uut, cx=cx, cy=cy, tol=tol)
            # Several verbs share one location; keep the tightest window, since
            # that is the one that will fail first.
            site.tol = min(site.tol, tol)
            site.refs.append(ref)
            site.uses.append(Use(row=row.index, verb=row.verb,
                                 test_id=test_id, uut=uut))

    for path, key in sorted(missing):
        notes.append(
            f"'{key}' has no entry in {path} yet -- click it to create one")

    ordered = sorted(sites.values(),
                     key=lambda s: (s.uut if s.uut is not None else -1,
                                    s.refs[0].row))
    return ordered, notes


def _resolve_path(program: Program, path: str) -> str:
    """A coordinates path as written in the table, made openable from here.

    Tables name it relative to where the station runs, which is normally the
    package root. Falling back to a path relative to the program itself means
    calibration works when it is invoked from somewhere else.
    """
    if not path or os.path.isabs(path):
        return path
    if os.path.exists(path):
        return path
    beside = os.path.join(os.path.dirname(os.path.abspath(program.source or ".")),
                          os.path.basename(path))
    return beside if os.path.exists(beside) else path


# --- finding the capture in a finished run ------------------------------

#: Where a *2CONT verb saves the thresholded frame it built. Column 4 is spent
#: on the contours, so column 5 is the only place left -- see imageproc._convert.
_BINARY_COLUMN = 5

#: Column 3 is the "image on disk" source. A conversion verb reads column 2
#: first and falls back to column 3, so discovery has to follow the same order:
#: cargo.ods leaves column 2 blank and passes frames as file paths throughout.
_PATH_COLUMN = 3


@dataclass
class Source:
    """Where one image is: a data cell holding an array, or a path to a file."""

    cell: str = ""
    is_path: bool = False

    def __bool__(self) -> bool:
        return bool(self.cell)


@dataclass
class CaptureCells:
    """Where a program's vision pipeline put the things worth looking at."""

    contours: str = ""
    frame: Source = field(default_factory=Source)
    binary: Source = field(default_factory=Source)
    threshold: float | None = None
    row: int | None = None

    def as_dict(self) -> dict:
        return {"contours": self.contours,
                "frame": self.frame.cell, "frame_is_path": self.frame.is_path,
                "binary": self.binary.cell, "binary_is_path": self.binary.is_path}


#: Suffixes of the nine conversion verbs imageproc registers. A cell written by
#: one of these has something upstream; a cell written by anything else -- a
#: CAPTURE, a load -- is where the pipeline starts.
_CONVERSION_SUFFIXES = ("2GRAY", "2BIN", "2CONT")


def is_conversion(verb: str) -> bool:
    return str(verb).upper().endswith(_CONVERSION_SUFFIXES)


def contour_rows(program: Program) -> list:
    """Every ``*2CONT`` row, in program order."""
    return [r for r in program.rows if r.verb.upper().endswith("2CONT")]


@dataclass
class Calibration:
    """A capture program that offers itself as a calibration.

    Declared in the program's own meta::

        meta:
          calibrates: programs/cargo.yaml
          title: LEDs A-F

    The station lists these under Tools, so an operator picks "LEDs A-F" rather
    than knowing which file to load. One program per set of camera settings,
    because a scene that shows a bright indicator at exposure 120 does not show
    a dim one, and there is no single frame that covers both.
    """

    path: str
    title: str
    target: str
    product: str = ""
    notes: str = ""
    #: Glob over variable keys, naming the sites this capture can actually
    #: cal. Without it the window lists every site in the table, including
    #: the ones invisible at this exposure -- which an operator has no way to
    #: tell apart from ones they simply have not clicked yet.
    sites: str = ""
    #: Smallest contour this calibration lets you click, in pixels. Defaults to
    #: the runtime's own floor.
    #:
    #: Lower it only where the runtime does not have to *find* the blob. The
    #: button indicators are the case: they are judged with EVALCONTN, which
    #: passes when nothing is there, so teaching marks where the indicator sits
    #: rather than something a limit is measured against. For an EVALCONT site,
    #: lowering this lets you teach a coordinate the test can never match --
    #: which is the exact failure the shared constant exists to prevent.
    min_area: int = MIN_CONTOUR_PIXELS

    @property
    def lowered_floor(self) -> bool:
        return self.min_area < MIN_CONTOUR_PIXELS

    @property
    def label(self) -> str:
        return self.title or os.path.splitext(os.path.basename(self.path))[0]

    def covers(self, site) -> bool:
        """Whether this calibration is responsible for a site."""
        if not self.sites:
            return True
        from fnmatch import fnmatch

        keys = [r.cell_key for r in site.refs if r.cell_key] or [site.file_key]
        return any(key and fnmatch(key, self.sites) for key in keys)

    def select(self, sites: list) -> list:
        return [s for s in sites if self.covers(s)]


def calibrations(directory: str) -> list[Calibration]:
    """Every calibration program in a directory, by title.

    Reads each candidate's meta rather than relying on a naming convention: a
    program says what it calibrates, so adding one is dropping in a file.
    """
    from .engine.loaders import NATIVE_EXTS

    found: list[Calibration] = []
    if not directory or not os.path.isdir(directory):
        return found
    try:
        entries = sorted(os.listdir(directory))
    except OSError:
        return found

    for entry in entries:
        if os.path.splitext(entry)[1].lower() not in NATIVE_EXTS:
            continue
        path = os.path.join(directory, entry)
        try:
            import yaml

            with open(path, "r", encoding="utf-8") as fh:
                doc = yaml.safe_load(fh) or {}
        except Exception:  # noqa: BLE001 - an unreadable file is not a menu item
            continue
        meta = (doc.get("meta") or {}) if isinstance(doc, dict) else {}
        target = meta.get("calibrates")
        if not target:
            continue
        try:
            floor = int(meta.get("min_area", MIN_CONTOUR_PIXELS))
        except (TypeError, ValueError):
            floor = MIN_CONTOUR_PIXELS
        found.append(Calibration(
            path=path, title=str(meta.get("title") or ""), target=str(target),
            product=str(meta.get("product") or ""),
            notes=str(meta.get("notes") or ""),
            sites=str(meta.get("sites") or ""),
            min_area=max(1, floor)))
    return found


def find_capture(program: Program, row_index: int | None = None) -> CaptureCells:
    """Locate a contour row and work out where its images ended up.

    The source of a conversion verb is column 2 (a data cell) *or* column 3 (a
    path), in that order -- the same precedence ``imageproc._load`` applies. Both
    forms are in use: demo.yaml keeps frames in the data store, cargo.ods writes
    them to disk and passes filenames.

    A ``BIN2CONT`` row is already looking at a binary image, so the colour frame
    is further back and the pipeline is walked to find it. A ``BGR2CONT`` row
    thresholds the colour frame itself, so its own source is the frame.
    """
    rows = contour_rows(program)
    if not rows:
        raise LoaderError(
            "this program has no *2CONT row, so it never produces contours. "
            "The capture program needs a BIN2CONT (or GRAY2CONT / BGR2CONT) "
            "step for there to be anything to click.")

    cont_row = rows[0]
    if row_index is not None:
        match = [r for r in rows if r.index == row_index]
        if not match:
            available = ", ".join(str(r.index) for r in rows)
            raise LoaderError(
                f"row {row_index} is not a *2CONT row. This program has "
                f"contours at row(s) {available}.")
        cont_row = match[0]

    def source_of(row) -> Source:
        if row.has(_SOURCE_COLUMN):
            return Source(row.raw(_SOURCE_COLUMN), is_path=False)
        if row.has(_PATH_COLUMN):
            return Source(row.raw(_PATH_COLUMN), is_path=True)
        return Source()

    found = CaptureCells(
        contours=cont_row.raw(_DEST_COLUMN),
        binary=Source(cont_row.raw(_BINARY_COLUMN), is_path=True)
        if cont_row.has(_BINARY_COLUMN) else Source(),
        row=cont_row.index,
        threshold=_float(cont_row.raw(6), 127.0) if cont_row.has(6) else None,
    )

    source = source_of(cont_row)
    if not cont_row.verb.upper().startswith("BIN"):
        # The row thresholds a colour or grey frame, so its own source is the
        # picture the operator wants to look at.
        found.frame = source
        return found

    # BIN2CONT: its source is already thresholded. Follow the writers back to
    # whatever the camera produced. Bounded, so a cell written from itself
    # cannot spin.
    writers: dict[str, object] = {}
    for row in program.rows:
        dest = row.raw(_DEST_COLUMN)
        if dest and row.verb:
            writers.setdefault(dest.lstrip("*"), row)

    if not found.binary:
        found.binary = source
    cell = source.cell
    for _ in range(8):
        writer = writers.get(cell.lstrip("*"))
        if writer is None:
            break
        if not is_conversion(writer.verb):
            # CAPTURE wrote this cell, so the cell *is* the frame. Reading the
            # writer's column 2 here would follow the chain one step too far and
            # come back with the camera's serial number, which then resolves to
            # nothing and leaves the canvas showing the binary instead.
            break
        upstream = source_of(writer)
        if not upstream or upstream.cell == cell:
            break
        found.frame = upstream
        cell = upstream.cell
    if not found.frame:
        found.frame = source
    return found


# --- running the capture ------------------------------------------------

@dataclass
class Capture:
    """What a capture run left behind for the operator to click on."""

    frame: object = None
    binary: object = None
    contours: list = field(default_factory=list)
    cells: CaptureCells = field(default_factory=CaptureCells)
    record: object = None
    #: The run's context, kept so the window can switch between the several
    #: frames one run captured without taking another picture.
    context: object = None

    @property
    def ok(self) -> bool:
        return self.contours is not None and len(self.contours) > 0


def _read_image(path: str):
    """Load an image from disk, or None. Never raises."""
    try:
        import cv2
    except ImportError:
        return None
    try:
        if not path or not os.path.exists(path):
            return None
        return cv2.imread(path, cv2.IMREAD_UNCHANGED)
    except Exception:  # noqa: BLE001
        return None


def resolve_image(ctx, source: Source):
    """Get the image a Source points at, whichever form it takes.

    A path cell holds a *filename*, so it has to be dereferenced and then read;
    a data cell holds the array already. Getting this wrong is silent -- an
    array stringified into a filename yields None from imread and the canvas
    just comes up blank.
    """
    if not source:
        return None
    if not source.is_path:
        try:
            return ctx.get_data(source.cell)
        except Exception:  # noqa: BLE001 - an unwritten cell is not fatal here
            return None
    try:
        path = ctx.text(source.cell)
    except Exception:  # noqa: BLE001
        return None
    if not path:
        return None
    if os.path.isabs(path):
        return _read_image(path)

    # A relative capture path is written by CAPTURE against the *process*
    # working directory (it calls abspath on the raw cell), while a run may
    # carry a different ctx.workdir -- the station sets it to the program's
    # folder. Try both rather than picking one: getting it wrong shows up only
    # as an empty canvas saying "no capture", with the file sitting on disk.
    for base in (".", ctx.workdir or "."):
        found = _read_image(os.path.join(base, path))
        if found is not None:
            return found
    return None


def capture_from_context(program: Program, ctx, *, row_index: int | None = None,
                         record=None) -> Capture:
    """Pull the frame and contours a finished run left in its data store.

    Split out from run_capture so the operator station can calibrate from the run
    it *just did* -- which is the better moment for it. A board whose optical
    tests all reported NOT_FOUND has already produced the evidence; taking a
    second picture to look at it is a step nobody needs.
    """
    cells = find_capture(program, row_index)

    contours = None
    if cells.contours:
        try:
            contours = ctx.get_data(cells.contours)
        except Exception:  # noqa: BLE001
            contours = None

    frame = resolve_image(ctx, cells.frame)
    binary = resolve_image(ctx, cells.binary)
    if frame is None and binary is not None:
        frame = binary

    return Capture(
        frame=frame,
        binary=binary,
        contours=list(contours) if contours is not None else [],
        cells=cells,
        record=record,
        context=ctx,
    )


def run_capture(program: Program, *, simulate: bool = False,
                listener=None, workdir: str = ".", row_index: int | None = None,
                station: str = "", operator: str = "") -> Capture:
    """Execute a capture program and keep what it put in the data store.

    The program runs normally, teardown included -- so the supplies come back
    down before anyone starts clicking. The frame survives because the context
    outlives the run: teaching happens against the captured image, never against
    live hardware.
    """
    from .engine.context import Context
    from .engine.sequencer import RunOptions, Sequencer

    ctx = Context(program, listener, simulate=simulate, workdir=workdir)
    options = RunOptions(simulate=simulate, station=station, operator=operator,
                         workdir=workdir)
    record = Sequencer(listener=listener, options=options).run(program, ctx)
    return capture_from_context(program, ctx, row_index=row_index, record=record)


# --- resolving a click to a contour -------------------------------------

@dataclass(frozen=True)
class Blob:
    """One contour, measured the way the runtime measures it."""

    index: int
    cx: int
    cy: int
    area: float

    @property
    def centre(self) -> tuple[int, int]:
        return self.cx, self.cy


def measure(contours, noise_floor: int = MIN_CONTOUR_PIXELS) -> list[Blob]:
    """Centroid and area of every contour big enough for the runtime to see.

    The noise floor is imported from the image driver rather than repeated, so
    a site can never be taught to a speck ``_find_at`` would skip. Centroids use
    the same integer truncation, so a taught coordinate is bit-identical to the
    number the test will compare against.
    """
    try:
        import cv2
    except ImportError:
        return []

    out: list[Blob] = []
    for i, contour in enumerate(contours or []):
        try:
            area = float(cv2.contourArea(contour))
            if area < noise_floor:
                continue
            m = cv2.moments(contour)
            if not m["m00"]:
                continue
            out.append(Blob(index=i, cx=int(m["m10"] / m["m00"]),
                            cy=int(m["m01"] / m["m00"]), area=area))
        except Exception:  # noqa: BLE001 - one bad contour must not lose the rest
            continue
    return out


def blob_at(contours, x: float, y: float, radius: float = 40.0,
            noise_floor: int = MIN_CONTOUR_PIXELS) -> Blob | None:
    """The blob a click at (x, y) means, or None.

    A click inside a contour wins outright. Otherwise the nearest centroid
    within `radius` is taken, which is what makes a small LED clickable without
    demanding pixel accuracy from someone using a trackpad on a shop floor.

    Note this is *not* the runtime's rule -- ``_find_at`` picks the largest blob
    in a window, because an area test wants the thing it is measuring. Here the
    operator is pointing at one specific blob, so proximity is right. The two
    agree on what a blob *is*, which is the part that has to match.
    """
    try:
        import cv2
    except ImportError:
        return None

    blobs = measure(contours, noise_floor)
    by_index = {b.index: b for b in blobs}

    for i, contour in enumerate(contours or []):
        if i not in by_index:
            continue
        try:
            if cv2.pointPolygonTest(contour, (float(x), float(y)), False) >= 0:
                return by_index[i]
        except Exception:  # noqa: BLE001
            continue

    best, best_distance = None, radius
    for blob in blobs:
        distance = ((blob.cx - x) ** 2 + (blob.cy - y) ** 2) ** 0.5
        if distance <= best_distance:
            best, best_distance = blob, distance
    return best


# --- the file -----------------------------------------------------------

def to_dict(sites: list[Site], *, meta: dict | None = None,
            notes: list[str] | None = None) -> dict:
    """The calibration result, in the shape an applier reads.

    Every ref carries the cell as it stood when the site was taught. That is
    what lets an applier refuse to write into a table someone edited in the
    meantime, instead of overwriting their change.
    """
    payload = {
        "version": FORMAT_VERSION,
        "taught_at": datetime.now().isoformat(timespec="seconds"),
        "meta": dict(meta or {}),
        "notes": list(notes or []),
        "sites": [],
    }
    for site in sites:
        if site.taught is None:
            continue
        payload["sites"].append({
            "uut": site.uut,
            # One field a reader can always display, whether the site came from
            # a table's tests or from an operator naming it.
            "name": site.name,
            "tests": site.tests,
            "key": site.file_key,
            "file": site.file_path,
            "was": ({"cx": site.cx, "cy": site.cy} if site.known else None),
            "now": {"cx": site.taught[0], "cy": site.taught[1]},
            "delta": list(site.delta or (0, 0)),
            "tol": site.tol,
            "within_tolerance": site.within_tolerance,
            "area": site.area,
            "note": site.note,
            "refs": [{
                "row": r.row,
                "module": r.module,
                "verb": r.verb,
                "column": r.column,
                "group": r.group,
                "test_id": r.test_id,
                "uut": r.uut,
                "was_cell": r.cell,
                "now_cell": r.rewritten(site.taught[0], site.taught[1]),
            } for r in site.refs],
            # Not rewritten -- listed so a reviewer can see how much rides on
            # the one cell that is. A table that factored its coordinates into
            # <Vars> has one ref here and many uses; that ratio is the reason
            # to do it.
            "uses": [{"row": u.row, "verb": u.verb, "test_id": u.test_id,
                      "uut": u.uut} for u in site.uses],
        })
    return payload


def save(path: str, sites: list[Site], *, meta: dict | None = None,
         notes: list[str] | None = None, program=None) -> list[str]:
    """Write what a calibration produced. Returns every path written.

    Two outputs, because they answer different questions:

    * the **coordinates file** the program loads -- written only when the table
      actually reads one, and written in full so the next run cannot hit a
      missing key;
    * the **calibration record**, which carries the deltas, the rows that read each
      site, and what was left untaught. Nothing reads it at run time; it is
      what someone looks at to decide whether a re-teach was sane.
    """
    written: list[str] = []

    for target in sorted({s.file_path for s in sites if s.in_file and s.file_path}):
        resolved = _resolve_path(program, target) if program is not None else target
        written.append(write_coords(
            resolved, [s for s in sites if s.file_path == target],
            meta={"written_by": "ngwart calibrate",
                  "at": datetime.now().isoformat(timespec="seconds"),
                  **{k: v for k, v in (meta or {}).items()
                     if k in ("capture_program", "target_program", "simulated",
                              "station", "operator")}}))

    # The record must never land on a values file. They are both JSON next to
    # the same table, so a careless default puts them at one path and the record
    # -- written second -- silently destroys every coordinate the program loads.
    if any(os.path.abspath(path) == os.path.abspath(p) for p in written):
        stem, ext = os.path.splitext(path)
        path = f"{stem}-teach{ext or '.json'}"

    payload = to_dict(sites, meta=meta, notes=notes)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    written.append(path)
    return written


def load(path: str) -> dict:
    """Read a calibration record, checking the version rather than trusting it."""
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    version = payload.get("version")
    if version != FORMAT_VERSION:
        raise LoaderError(
            f"{path} is calibration format version {version!r}, this build reads "
            f"{FORMAT_VERSION}")
    return payload


def summarise(sites: list[Site]) -> str:
    """One line an operator can act on, for the CLI and the window's status."""
    taught = [s for s in sites if s.taught is not None]
    if not taught:
        return f"0 of {len(sites)} site(s) taught."
    moved = [s for s in taught if s.within_tolerance is False]
    drift = max((s.drift or 0.0) for s in taught)
    text = f"{len(taught)} of {len(sites)} site(s) taught, largest drift {drift:.1f}px"
    if moved:
        text += f"; {len(moved)} outside the current tolerance"
    return text + "."
