"""Native v2 program format: YAML.

Why a text format at all, when .ods still works? Because a file that controls
mains-powered hardware should be reviewable. A binary spreadsheet cannot be
diffed, so nobody can answer "what changed between the revision that passed
qualification and the one running now" -- which is a quality-system problem
before it is a developer-comfort one. It also stops LibreOffice lock files
(``.~lock.cargo.ods#``, ``~$cargo.ods``) from landing in the repo.

The format deliberately mirrors the row layout rather than inventing a nested
DSL, so a table can be converted in either direction without loss.

    meta:
      name: cargo
      product: CARGO
    modules:
      Flow: FlowManager
      Serial: SerialManager
    vars:
      uut1.vbat: 0,1,2
    config:
      - [TestData, initAlive, 4]
    exec:
      - [Flow, LABEL, START, Test started, '', '', '', '', '', yellow]
      - {verb: DELAY, module: Flow, args: [1], comment: settle}
    teardown:
      - [VISA, WRITE, PSU1, 'OUTP OFF']
"""

from __future__ import annotations

import os

from ..errors import LoaderError
from ..program import ARG_END, ARG_START, NCOLS, Program, Row

#: Order matters: these are emitted as rows in this sequence, and <Teardown>
#: must come last because it bounds the executable range.
_SECTION_KEYS = (
    ("config", "Config"),
    ("exec", "Exec"),
    ("ehandling", "Ehandling"),
    ("teardown", "Teardown"),
)


def _require_yaml():
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise LoaderError(
            "the native program format needs PyYAML -- pip install pyyaml"
        ) from exc
    return yaml


def load(path: str) -> Program:
    yaml = _require_yaml()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
    except OSError as exc:
        raise LoaderError(f"cannot read '{path}': {exc}") from exc
    except yaml.YAMLError as exc:
        raise LoaderError(f"malformed YAML in '{path}': {exc}") from exc

    if not isinstance(doc, dict):
        raise LoaderError(f"'{path}' must contain a mapping at the top level")

    return from_dict(doc, source=path)


def from_dict(doc: dict, source: str = "") -> Program:
    """Build a Program from the parsed document.

    Sections are emitted as real marker rows so that everything downstream --
    the sequencer, the validator, the editor -- sees exactly the same structure
    it would get from a legacy .ods. There is one program model, not two.
    """
    rows: list[Row] = []

    def add(cells: list[str]) -> None:
        rows.append(Row(index=len(rows), cells=cells))

    def marker(tag: str) -> None:
        add([tag] + [""] * (NCOLS - 1))

    modules = doc.get("modules") or {}
    if modules:
        if not isinstance(modules, dict):
            raise LoaderError("'modules' must be a mapping of alias -> module name")
        marker("<Modules>")
        for alias, target in modules.items():
            add([str(alias), str(target)] + [""] * (NCOLS - 2))
        marker("<Modules/>")

    variables = doc.get("vars") or {}
    if variables:
        if not isinstance(variables, dict):
            raise LoaderError("'vars' must be a mapping of name -> 'l,c,p'")
        marker("<Vars>")
        for name, coord in variables.items():
            add([str(name), str(coord)] + [""] * (NCOLS - 2))
        marker("<Vars/>")

    for key, tag in _SECTION_KEYS:
        entries = doc.get(key)
        if entries is None:
            continue
        if not isinstance(entries, list):
            raise LoaderError(f"'{key}' must be a list of steps")
        marker(f"<{tag}>")
        for pos, entry in enumerate(entries):
            add(_entry_to_cells(entry, key, pos))
        marker(f"<{tag}/>")

    program = Program(rows=rows, source=source, meta=dict(doc.get("meta") or {}))
    return program


def _entry_to_cells(entry, section: str, pos: int) -> list[str]:
    """Accept either the compact list form or the explicit mapping form."""
    if entry is None:
        return [""] * NCOLS

    if isinstance(entry, list):
        cells = [_cell(c) for c in entry]
        return (cells + [""] * NCOLS)[:NCOLS]

    if isinstance(entry, str):
        # A bare string is a comment/spacer row -- handy for section headings.
        return ["", "", "", "", "", "", "", "", "", entry]

    if isinstance(entry, dict):
        cells = [""] * NCOLS
        cells[0] = _cell(entry.get("module", ""))
        cells[1] = _cell(entry.get("verb", ""))
        args = entry.get("args") or []
        if not isinstance(args, list):
            args = [args]
        if len(args) > (ARG_END - ARG_START + 1):
            raise LoaderError(
                f"{section}[{pos}] ({cells[0]}.{cells[1]}): "
                f"{len(args)} arguments given, at most "
                f"{ARG_END - ARG_START + 1} fit the row layout"
            )
        for i, value in enumerate(args):
            cells[ARG_START + i] = _cell(value)
        cells[7] = _cell(entry.get("route", entry.get("on_error", "")))
        cells[8] = _cell(entry.get("alive", ""))
        cells[9] = _cell(entry.get("comment", entry.get("color", "")))
        return cells

    raise LoaderError(f"{section}[{pos}]: expected a list or mapping, got {type(entry).__name__}")


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return str(value).strip()


# --- writing ------------------------------------------------------------

def to_dict(program: Program) -> dict:
    """Convert a Program (from any source) into the native document shape."""
    doc: dict = {}
    if program.meta:
        doc["meta"] = dict(program.meta)
    if program.modules:
        doc["modules"] = dict(program.modules)
    if program.vars:
        doc["vars"] = dict(program.vars)

    for key, tag in _SECTION_KEYS:
        section = program.section(tag)
        if section is None:
            continue
        entries = []
        for i in section.body:
            if i >= len(program.rows):
                break
            cells = list(program.rows[i].cells)
            while cells and not cells[-1]:
                cells.pop()
            entries.append(cells)
        doc[key] = entries
    return doc


def save(program: Program, path: str) -> None:
    yaml = _require_yaml()
    doc = to_dict(program)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(doc, fh, sort_keys=False, allow_unicode=True,
                           default_flow_style=None, width=200)
    except OSError as exc:
        raise LoaderError(f"cannot write '{path}': {exc}") from exc
