"""The program model: rows, sections and labels.

A NGWART program keeps NGINE v1's shape -- a flat list of rows, each one
instruction -- because that shape is genuinely right for the domain. Test
engineers read a sequence top to bottom; nesting would not help them.

What changes is that the structure is *parsed once, up front* into an object
with named sections and a label index, instead of being rediscovered by
scanning for marker strings on every run (v1 did a linear scan of the whole
table inside resetPointer() and again in updateLabels()).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .errors import ProgramError

#: Number of argument columns. Legacy layout: cells[2] .. cells[6].
ARG_START = 2
ARG_END = 6

#: Fixed column meanings, inherited from the v1 spreadsheet layout.
COL_MODULE = 0
COL_VERB = 1
COL_ROUTE = 7
COL_ALIVE = 8
COL_COMMENT = 9

NCOLS = 10

# Section markers. <Vars> and <Teardown> are new in v2; <Modules>, <Config>
# and <Exec> are read exactly as v1 wrote them.
#: <Ehandling> holds the error-handler labels. It sits *after* <Exec/> in real
#: tables, but its rows are jump targets, so it is part of the executable range
#: -- reachable only by a jump, never by falling into it.
SECTIONS = ("Modules", "Vars", "Config", "Exec", "Ehandling", "Teardown")

#: Sections whose rows are declarations, not instructions.
DECLARATIVE = ("Modules", "Vars")

#: Where a partial run lands when its last selected step finishes. Named with
#: underscores so it cannot collide with a label a real table declares.
END_LABEL = "__SELECTION_END__"


def _row(index: int, cells: list[str]) -> "Row":
    return Row(index=index, cells=(list(cells) + [""] * NCOLS)[:NCOLS])


@dataclass
class Row:
    """One instruction."""

    index: int
    cells: list[str]
    #: Source line number in the originating file, for error messages.
    source_line: int | None = None

    def __post_init__(self) -> None:
        if len(self.cells) < NCOLS:
            self.cells = list(self.cells) + [""] * (NCOLS - len(self.cells))

    # -- fixed columns ----------------------------------------------------

    @property
    def module(self) -> str:
        return self.cells[COL_MODULE].strip()

    @property
    def verb(self) -> str:
        return self.cells[COL_VERB].strip()

    @property
    def route(self) -> str | None:
        """Exception label from column 7, or None if blank/placeholder."""
        v = self.cells[COL_ROUTE].strip()
        return v if v and v != "-" else None

    @property
    def alive(self) -> str:
        """UUT mask from column 8. '-' means 'run regardless'."""
        v = self.cells[COL_ALIVE].strip()
        return v if v else "-"

    @property
    def comment(self) -> str:
        return self.cells[COL_COMMENT].strip()

    # -- arguments --------------------------------------------------------

    def raw(self, index: int) -> str:
        """Unresolved cell text. Blank for out-of-range columns."""
        if index < 0 or index >= len(self.cells):
            return ""
        return self.cells[index].strip()

    def has(self, index: int) -> bool:
        v = self.raw(index)
        return bool(v) and v != "-"

    @property
    def args(self) -> list[str]:
        return [self.raw(i) for i in range(ARG_START, ARG_END + 1)]

    @property
    def is_blank(self) -> bool:
        """A spacer row. v1 tables use them liberally for readability."""
        return not any(c.strip() for c in self.cells)

    @property
    def is_marker(self) -> bool:
        m = self.module
        return m.startswith("<") and m.endswith(">")

    def __str__(self) -> str:
        body = " ".join(a for a in [self.module, self.verb] + self.args if a)
        return f"[{self.index}] {body}"


@dataclass
class Section:
    name: str
    start: int  # index of the opening marker row
    end: int    # index of the closing marker row (exclusive of content)

    @property
    def body(self) -> range:
        return range(self.start + 1, self.end)


@dataclass
class Program:
    """A parsed, structurally-validated test program."""

    rows: list[Row] = field(default_factory=list)
    #: alias -> module name, from <Modules>.
    modules: dict[str, str] = field(default_factory=dict)
    #: friendly name -> "l,c,p" coordinate, from <Vars>. New in v2.
    vars: dict[str, str] = field(default_factory=dict)
    #: variable name -> the JSON key it takes its value from (<Vars> column 2).
    var_sources: dict[str, str] = field(default_factory=dict)
    #: variable name -> the value INITDATA seeds its cell with, once resolved.
    var_values: dict[str, str] = field(default_factory=dict)
    #: <values> file as written in the table, and as actually opened.
    values_source: str = ""
    values_path: str = ""
    #: Everything the file held, whether or not a variable claimed it.
    values_loaded: dict[str, str] = field(default_factory=dict)
    #: Anything wrong with the <values> file, filled in by finalize().
    value_problems: list[str] = field(default_factory=list)
    sections: dict[str, Section] = field(default_factory=dict)
    #: label name -> row index, built once at load.
    labels: dict[str, int] = field(default_factory=dict)
    source: str = ""
    #: Free-form metadata (product, revision, author) from the native format.
    meta: dict = field(default_factory=dict)

    # -- section access ---------------------------------------------------

    def section(self, name: str) -> Section | None:
        return self.sections.get(name)

    def body(self, name: str) -> range:
        sec = self.sections.get(name)
        return sec.body if sec else range(0)

    @property
    def exec_start(self) -> int:
        sec = self.sections.get("Exec")
        if sec is None:
            raise ProgramError("program has no <Exec> section")
        return sec.start + 1

    @property
    def exec_end(self) -> int:
        """One past the last row a jump may legitimately land on.

        Everything from <Exec> to the start of <Teardown> (or the end of the
        program) is reachable, because <Ehandling> lives past <Exec/> and its
        labels are jump targets. v1 had no upper bound at all here and simply
        ran off the end of the table into an IndexError.
        """
        teardown = self.sections.get("Teardown")
        if teardown is not None and teardown.start > self.exec_start:
            return teardown.start
        return len(self.rows)

    @property
    def has_teardown(self) -> bool:
        return "Teardown" in self.sections

    def in_declarative_section(self, index: int) -> bool:
        for name in DECLARATIVE:
            section = self.sections.get(name)
            if section is not None and section.start <= index <= section.end:
                return True
        return False

    #: Exec rows that create the store every other verb writes into. A selection
    #: is carried out against a fresh context, so without these almost any step
    #: run on its own dies with "data store not initialised".
    SETUP_VERBS = ("INITDATA", "STARTALIVE")

    def subset(self, indices, with_setup: bool = True) -> "Program":
        """A runnable program holding only the given <Exec> rows.

        Everything declarative is carried over verbatim -- <Modules> so verbs
        resolve, <Vars> so names resolve, <Config> so ports and instruments are
        opened, <Ehandling> so the rows' error routes still name real labels,
        and <Teardown> so a partial run still powers the fixture down. Only the
        body of <Exec> is replaced.

        ``with_setup`` prepends the program's own INITDATA and STARTALIVE rows
        when the selection does not already include them. They are idempotent
        setup, and without them a single selected step has nowhere to write.
        """
        exec_section = self.sections.get("Exec")
        if exec_section is None:
            raise ProgramError("program has no <Exec> section")

        body = self.body("Exec")
        chosen = sorted(i for i in indices if i in body)
        if with_setup:
            chosen = self._with_setup(chosen, body)

        rows: list[Row] = []

        def carry(name: str) -> None:
            section = self.sections.get(name)
            if section is None:
                return
            for i in range(section.start, section.end + 1):
                rows.append(Row(index=len(rows), cells=list(self.rows[i].cells)))

        carry("Modules")
        carry("Vars")
        carry("Config")

        flow = self._flow_alias()

        rows.append(Row(index=len(rows),
                        cells=list(self.rows[exec_section.start].cells)))
        for i in chosen:
            rows.append(Row(index=len(rows), cells=list(self.rows[i].cells)))
        # Without this the pointer runs off the end of the selection and keeps
        # going: <Exec/> is not the end of the executable span, <Teardown> is,
        # so the next thing it would reach is the first error handler. Jump to a
        # label parked immediately before teardown instead.
        rows.append(_row(len(rows), [flow, "J", END_LABEL]))
        rows.append(Row(index=len(rows),
                        cells=list(self.rows[exec_section.end].cells)))

        carry("Ehandling")
        rows.append(_row(len(rows), [flow, "LABEL", END_LABEL]))
        carry("Teardown")

        meta = dict(self.meta)
        meta["partial"] = True
        return Program(rows=rows, source=self.source, meta=meta).finalize()

    def _flow_alias(self) -> str:
        """Whatever this program calls FlowManager. Tables do rename it."""
        for alias, module in self.modules.items():
            if module.strip().lower() in ("flowmanager", "flow"):
                return alias
        return "Flow"

    def _with_setup(self, chosen: list[int], body: range) -> list[int]:
        present = {self.rows[i].verb.upper() for i in chosen}
        extra = []
        for verb in self.SETUP_VERBS:
            if verb in present:
                continue
            for i in body:
                if self.rows[i].verb.upper() == verb and self.rows[i].module:
                    extra.append(i)
                    break
        return sorted(set(chosen) | set(extra))

    # -- labels -----------------------------------------------------------

    def label_index(self, name: str) -> int:
        if name not in self.labels:
            raise ProgramError(f"jump to undefined label '{name}'")
        return self.labels[name]

    def build_labels(self) -> None:
        """Index every ``* LABEL <name>`` row.

        v1 rebuilt this list at config time by scanning the table and matching
        on column 1 regardless of module, so a verb named LABEL in any module
        would register. That behaviour is preserved intentionally -- existing
        tables call it as ``Flow LABEL`` and occasionally with a blank module.
        """
        self.labels.clear()
        for row in self.rows:
            if row.verb == "LABEL" and row.has(2):
                name = row.raw(2)
                if name in self.labels:
                    raise ProgramError(
                        f"duplicate label '{name}' at rows "
                        f"{self.labels[name]} and {row.index}",
                        row=row.index,
                    )
                self.labels[name] = row.index

    @property
    def span(self) -> tuple[int, int]:
        """(START, END) label indices, used for the progress bar.

        Falls back to the whole Exec section when the program does not define
        the conventional START/END labels.
        """
        start = self.labels.get("START")
        end = self.labels.get("END")
        if start is not None and end is not None and end > start:
            return start, end
        sec = self.sections.get("Exec")
        if sec:
            return sec.start + 1, sec.end
        return 0, max(len(self.rows) - 1, 1)

    # -- construction -----------------------------------------------------

    def finalize(self) -> "Program":
        """Parse sections, modules and vars out of the row list.

        The <values> file is read here, at load time, so that a missing file or
        an unmatched key is a *loading* problem the validator can report -- not
        something discovered mid-run.
        """
        self._parse_sections()
        self._parse_modules()
        self._parse_vars()
        self.value_problems = self.load_values()
        self.build_labels()
        return self

    def _parse_sections(self) -> None:
        open_at: dict[str, int] = {}
        for row in self.rows:
            tok = row.module
            if not (tok.startswith("<") and tok.endswith(">")):
                continue
            inner = tok[1:-1]
            closing = inner.endswith("/")
            name = inner[:-1] if closing else inner
            if name not in SECTIONS:
                continue
            if closing:
                if name not in open_at:
                    raise ProgramError(f"<{name}/> closes a section that was never opened",
                                       row=row.index)
                self.sections[name] = Section(name, open_at.pop(name), row.index)
            else:
                if name in open_at:
                    raise ProgramError(f"<{name}> opened twice", row=row.index)
                open_at[name] = row.index

        # <Exec> conventionally has no closing marker in v1 tables -- it simply
        # runs to the end of the sheet. Accept that, and let <Teardown> (if
        # present) bound it.
        for name, start in list(open_at.items()):
            end = len(self.rows)
            if name == "Exec":
                td = self.sections.get("Teardown")
                if td and td.start > start:
                    end = td.start
            self.sections[name] = Section(name, start, end)

    def _parse_modules(self) -> None:
        for i in self.body("Modules"):
            row = self.rows[i]
            if row.is_blank or not row.module:
                continue
            alias, target = row.module, row.verb
            if not target:
                raise ProgramError(f"module alias '{alias}' has no target module",
                                   row=row.index)
            self.modules[alias] = target

    def _parse_vars(self) -> None:
        """Read the <Vars> section: name -> l,c,p coordinate, and its value.

        This is the readability fix for ``data[39][0][29]``. It is additive --
        a program with no <Vars> section behaves exactly as it did in v1.

        Column 2 is an optional **initial value**. A variable that has one is a
        program constant: INITDATA writes it into the cell, every time, so it is
        there before the first step runs and survives the per-board re-init a
        fixture program does at the top of its loop. Nothing in <Config> has to
        set it up.

        The special name ``<values>`` names a JSON file those values are read
        from instead of being written in the table -- see load_values().
        """
        for i in self.body("Vars"):
            row = self.rows[i]
            if row.is_blank or not row.module:
                continue
            name, coord = row.module, row.verb

            if name.lower() in ("<values>", "<values/>"):
                if not coord:
                    raise ProgramError("<values> needs a file path", row=row.index)
                self.values_source = coord
                continue

            if not coord:
                raise ProgramError(f"variable '{name}' has no coordinate", row=row.index)
            if name.startswith("*"):
                raise ProgramError(f"variable name '{name}' must not start with '*'",
                                   row=row.index)
            self.vars[name] = coord
            if row.has(2):
                self.var_sources[name] = row.raw(2)

    # -- variable values --------------------------------------------------

    def load_values(self, base: str | None = None) -> list[str]:
        """Fill each variable that names a key from the <values> file.

        A ``<Vars>`` row's column 2 names the JSON key that variable takes its
        value from -- usually the same string as the variable itself, but
        written out so the link is visible and checkable rather than implied.

        Returns a list of problems, empty when all is well. It does not raise:
        the validator reports these while the fixture is still cold, which is a
        far better place to find out than row 400 with the supply at 13.5 V.
        """
        problems: list[str] = []
        if not self.var_sources:
            return problems
        if not self.values_source:
            return [f"{len(self.var_sources)} variable(s) take their value from "
                    f"a JSON key, but no <values> file is declared"]

        path = self.values_source
        if not os.path.isabs(path) and not os.path.exists(path):
            root = base or os.path.dirname(os.path.abspath(self.source or "."))
            candidate = os.path.join(root, os.path.basename(path))
            if os.path.exists(candidate):
                path = candidate
        self.values_path = path

        try:
            with open(path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except OSError as exc:
            return [f"<values> file '{path}' could not be read: {exc}"]
        except ValueError as exc:
            return [f"<values> file '{path}' is not valid JSON: {exc}"]

        if not isinstance(doc, dict):
            return [f"<values> file '{path}' must be a flat object of "
                    f"variable name -> value"]

        flat = {str(k): str(v) for k, v in doc.items()
                if not str(k).startswith("_")}
        self.values_loaded = dict(flat)

        for name, key in self.var_sources.items():
            if key in flat:
                self.var_values[name] = flat[key]
            else:
                # Loud, and by name. A variable left empty here surfaces much
                # later as "bad data reference ''" or a silently skipped test.
                problems.append(
                    f"variable '{name}' takes its value from key '{key}', "
                    f"which is not in {os.path.basename(path)}")
        return problems
