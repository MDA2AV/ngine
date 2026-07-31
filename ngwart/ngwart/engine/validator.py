"""Static checks run before a program is allowed to execute.

This is the single highest-value addition in v2. In v1 a mistyped verb became

    AttributeError: module 'WinSerialManager' has no attribute 'EXCHANGBYTES_LVS'

raised from ``getattr`` at ngine.py:285 -- discovered at row 200, with the PSU
already at 13.5 V and relays closed. Everything checkable here is checked while
the fixture is still cold, and the UI refuses to arm Play until it is clean.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .program import ARG_END, ARG_START, Program
from .registry import REGISTRY, Registry

#: Verbs whose column-2 argument names a label.
_JUMP_VERBS = {
    "J", "JC", "JCM", "JNC", "JE", "JNE", "JET", "JNET", "JG", "JL", "JGE", "JLE",
}

_REF_RE = re.compile(r"^\*(.+)$")
_COORD_RE = re.compile(r"^\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*$")

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    row: int | None
    message: str
    detail: str = ""

    @property
    def is_error(self) -> bool:
        return self.severity == ERROR

    def __str__(self) -> str:
        where = f"row {self.row}" if self.row is not None else "program"
        return f"{self.severity.upper():7} {where}: {self.message}"


class Report(list):
    """A list of Diagnostics that knows whether it blocks execution."""

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self if d.is_error]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self if d.severity == WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        if self.ok and not self.warnings:
            return "Program valid."
        bits = []
        if self.errors:
            bits.append(f"{len(self.errors)} error(s)")
        if self.warnings:
            bits.append(f"{len(self.warnings)} warning(s)")
        return ", ".join(bits)


def validate(program: Program, registry: Registry | None = None) -> Report:
    reg = registry or REGISTRY
    report = Report()

    def err(row, msg, detail=""):
        report.append(Diagnostic(ERROR, row, msg, detail))

    def warn(row, msg, detail=""):
        report.append(Diagnostic(WARNING, row, msg, detail))

    # -- structure --------------------------------------------------------
    if program.section("Exec") is None:
        err(None, "program has no <Exec> section -- nothing would run")

    # -- <values> ---------------------------------------------------------
    # An error, not a warning: a variable whose value never arrived surfaces
    # much later as "bad data reference ''" or as a test that silently measured
    # the wrong place. The whole point of reading the file at load time is to
    # find this while the fixture is still cold.
    for problem in getattr(program, "value_problems", []):
        err(None, problem,
            "Variables take their value from the <values> file named in "
            "<Vars>. Re-run `ngwart teach` to regenerate it, or fix the key.")
    unclaimed = set(program.values_loaded) - set(program.var_sources.values())
    if unclaimed:
        listed = ", ".join(sorted(unclaimed)[:6])
        warn(None,
             f"{len(unclaimed)} key(s) in the values file match no variable: "
             f"{listed}",
             "Harmless, but usually a renamed variable that left its value "
             "behind.")
    if not program.modules:
        warn(None, "program declares no <Modules>; only built-in verbs will resolve")
    if not program.has_teardown:
        warn(None, "program has no <Teardown> section",
             "Without one, an aborted run leaves the fixture in whatever state it "
             "reached. Add <Teardown> to power down supplies and open relays.")

    # -- modules ----------------------------------------------------------
    known_modules = set(reg.modules())
    for alias, target in program.modules.items():
        if reg.resolve_module(target) not in known_modules:
            err(None, f"module alias '{alias}' -> '{target}' is not a registered driver",
                f"Registered drivers: {', '.join(sorted(known_modules))}")

    alive_size = _declared_alive_size(program)
    dims = _declared_dims(program)

    # -- rows -------------------------------------------------------------
    for row in program.rows:
        if row.is_blank or row.is_marker or row.module == "-":
            continue
        # <Modules> and <Vars> hold declarations, not instructions.
        if program.in_declarative_section(row.index):
            continue
        if not row.module:
            if row.verb:
                # A warning, not an error: the row is skipped and the program
                # still loads. v1 raised KeyError on globals()[""] and diverted
                # to the row's handler, so the step never ran there either --
                # blocking the load would be stricter than the behaviour this
                # replaces. The warning stays so the skip is never silent.
                warn(row.index,
                     f"'{row.verb}' has no module in column 0 -- row will be skipped",
                     "Fill in column 0 to make this step run. In v1 it raised "
                     "KeyError and diverted to the row's exception handler, so "
                     "it never executed there either.")
            continue

        module = program.modules.get(row.module, row.module)
        spec = reg.lookup(module, row.verb)
        if spec is None:
            if reg.resolve_module(module) not in known_modules:
                err(row.index, f"unknown module '{row.module}'")
            else:
                near = _suggest(row.verb, reg.verbs_for(module))
                hint = f" -- did you mean {near}?" if near else ""
                err(row.index, f"unknown verb {row.module}.{row.verb}{hint}")
            continue

        # arity
        for param in spec.params:
            if param.required and not row.has(param.index):
                err(row.index,
                    f"{row.module}.{row.verb}: missing required argument "
                    f"'{param.name}' (column {param.index})",
                    param.doc)

        # arguments beyond what the verb declares are almost always a
        # copy-paste slip from a neighbouring row
        if spec.params:
            for i in range(ARG_START, ARG_END + 1):
                if row.has(i) and spec.param_at(i) is None:
                    warn(row.index,
                         f"{row.module}.{row.verb}: unexpected argument in column {i} "
                         f"('{row.raw(i)}') -- this verb ignores it")

        # jump targets
        if row.verb in _JUMP_VERBS and row.has(2):
            target = row.raw(2)
            if not target.startswith("*") and target not in program.labels:
                near = _suggest(target, list(program.labels))
                hint = f" -- did you mean {near}?" if near else ""
                err(row.index, f"jump to undefined label '{target}'{hint}")

        # exception routing target
        route = row.route
        if route and route not in program.labels and route != "STD_EX":
            warn(row.index,
                 f"exception label '{route}' has no matching LABEL row",
                 "On failure the run will abort instead of recovering.")

        # alive mask
        if alive_size is not None:
            for token in [t.strip() for t in row.alive.split(",")]:
                if token in ("", "-"):
                    continue
                if not token.isdigit():
                    err(row.index, f"bad alive mask entry '{token}'")
                elif int(token) >= alive_size:
                    err(row.index,
                        f"alive mask references UUT {token} but initAlive "
                        f"declares {alive_size}")

        # data references
        for i in range(ARG_START, ARG_END + 1):
            raw = row.raw(i)
            m = _REF_RE.match(raw)
            if not m:
                continue
            ref = program.vars.get(m.group(1), m.group(1))
            coord = _COORD_RE.match(ref)
            if not coord:
                near = _suggest(m.group(1), list(program.vars))
                hint = f" -- did you mean *{near}?" if near else ""
                err(row.index,
                    f"column {i}: '{raw}' is neither an l,c,p coordinate nor a "
                    f"declared variable{hint}")
                continue
            if dims:
                l, c, p = (int(coord.group(1)), int(coord.group(2)), int(coord.group(3)))
                if l >= dims[0] or c >= dims[1] or p >= dims[2]:
                    err(row.index,
                        f"column {i}: {raw} is outside the data store declared by "
                        f"INITDATA ({dims[0]}x{dims[1]}x{dims[2]})")

    _check_parallel_blocks(program, report)
    return report


def _check_parallel_blocks(program: Program, report: Report) -> None:
    """Every <ParallelTask> must be closed, and nesting is not supported."""
    open_at: int | None = None
    for row in program.rows:
        tok = row.module.strip()
        if tok == "<ParallelTask>":
            if open_at is not None:
                report.append(Diagnostic(
                    ERROR, row.index,
                    "<ParallelTask> nested inside another parallel block",
                    f"Outer block opened at row {open_at}."))
            open_at = row.index
        elif tok == "<ParallelTask/>":
            if open_at is None:
                report.append(Diagnostic(
                    ERROR, row.index, "<ParallelTask/> closes a block that was never opened"))
            open_at = None
    if open_at is not None:
        report.append(Diagnostic(
            ERROR, open_at,
            "<ParallelTask> is never closed",
            "v1 would run off the end of the table here."))


def _declared_alive_size(program: Program) -> int | None:
    for row in program.rows:
        if row.verb == "initAlive" and row.has(2) and row.raw(2).isdigit():
            return int(row.raw(2))
    return None


def _declared_dims(program: Program) -> tuple[int, int, int] | None:
    for row in program.rows:
        if row.verb == "INITDATA":
            vals = [row.raw(i) for i in (2, 3, 4)]
            if all(v.isdigit() for v in vals):
                return tuple(int(v) for v in vals)  # type: ignore[return-value]
    return None


def _suggest(word: str, candidates: list[str]) -> str | None:
    import difflib

    hits = difflib.get_close_matches(word, [c for c in candidates if c], n=1, cutoff=0.7)
    return hits[0] if hits else None
