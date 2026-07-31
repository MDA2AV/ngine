"""Run context: the data store, the alive mask, and everything a verb needs.

The data store keeps v1's ``data[line][col][page]`` shape and its ``*l,c,p``
reference syntax, because existing test tables are full of both and must keep
running. What is added is a *name layer*: a <Vars> section maps friendly names
onto coordinates, so a new program can say ``*uut1.vbat`` where an old one said
``*0,1,2``. Both resolve through the same accessor, so a table can mix them
during migration.
"""

from __future__ import annotations

import datetime as _dt
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .errors import ProgramError, VerbError
from .events import (AliveEvent, Event, FieldEvent, Listener, LogEvent,
                     NullListener, ProgressEvent, TimerEvent, VerdictEvent)
from .program import Program

_COORD_RE = re.compile(r"^\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*$")


@dataclass
class Timers:
    enabled: bool = False
    ref: float = 0.0

    def reset(self) -> None:
        self.ref = time.perf_counter()

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self.ref if self.ref else 0.0


class Context:
    """Everything a verb is handed, besides its own row.

    One instance per run. Drivers stash their own state in ``ctx.store`` keyed
    by driver name rather than using module-level globals -- v1 had 29 ``global``
    statements in TestData alone, which meant two runs could never be isolated
    and nothing could be unit-tested without process restarts.
    """

    def __init__(self, program: Program, listener: Listener | None = None,
                 simulate: bool = False, workdir: str | None = None) -> None:
        self.program = program
        self.listener = listener or NullListener()
        self.simulate = simulate
        self.workdir = workdir or "."

        # Data store -- allocated by INITDATA, matching v1's lazy behaviour.
        self.data: list[list[list[Any]]] | None = None
        self.dims: tuple[int, int, int] = (0, 0, 0)
        #: First page of the program region, which INITDATA does not clear.
        #: None means the whole store is board data, as in v1.
        self.preserve_from: int | None = None

        self.alive: list[int] = []
        self.pointer: int = 0
        self.log_enabled: bool = True
        self.timers = Timers()

        self.datecode: str | None = None
        self.extended_datecode: str | None = None

        #: Per-driver scratch space, e.g. ctx.store["serial"]["ports"].
        self.store: dict[str, dict] = {}

        #: Set by the sequencer when the operator asks to stop.
        self.stop_requested = threading.Event()

        #: Label a verb has asked to jump to, consumed by the sequencer after
        #: the verb returns. v1 had jump() poke ``pointer = index - 1`` directly
        #: so that the loop's unconditional increment landed on target -- an
        #: off-by-one waiting to happen, and impossible to do from a worker
        #: thread. Requesting a jump and letting the loop own the pointer keeps
        #: control flow in one place.
        self.pending_jump: str | None = None

        #: Structured record of everything that happened; feeds reports.
        self.record = None  # set by the sequencer

        #: DebugBundle when --debug is on, else None. Drivers guard on it, so
        #: the cost of the instrumentation is zero on a normal run.
        self.debug = None

        self._lock = threading.RLock()

    # -- driver scratch ---------------------------------------------------

    def driver_state(self, name: str) -> dict:
        with self._lock:
            return self.store.setdefault(name, {})

    # -- events -----------------------------------------------------------

    def emit(self, event: Event) -> None:
        self.listener.emit(event)

    def log(self, message: str, level: str = "info") -> None:
        """Operator-visible log line.

        Honours the LOG_FLAG verb, which v1 tables use to silence the noisy
        detection polling loop.
        """
        if not self.log_enabled and level == "info":
            return
        self.emit(LogEvent(message=str(message), level=level, row=self.pointer))

    def field(self, name: str, value: str, color: str | None = None) -> None:
        self.emit(FieldEvent(name=name, value=str(value), color=color))

    def progress(self, value: float) -> None:
        self.emit(ProgressEvent(value=value))

    def tick_timer(self) -> None:
        if self.timers.enabled:
            self.emit(TimerEvent(seconds=self.timers.elapsed))

    # -- control flow -----------------------------------------------------

    def jump(self, label: str) -> None:
        """Ask the sequencer to continue at `label` after this verb returns.

        Validated eagerly so a bad target is reported against the row that
        asked for it, not wherever the pointer happens to land.
        """
        if label not in self.program.labels:
            raise ProgramError(f"jump to undefined label '{label}'", row=self.pointer)
        self.pending_jump = label

    def take_jump(self) -> str | None:
        label, self.pending_jump = self.pending_jump, None
        return label

    # -- data store -------------------------------------------------------

    def init_data(self, lines: int, cols: int, pages: int,
                  preserve_from: int | None = None) -> None:
        """Allocate the data store, optionally keeping the program region.

        A fixture program loops: it tests a board, waits for it to be removed,
        and jumps back to the top, where INITDATA clears the store for the next
        one. That is right for measurements and wrong for anything the *program*
        knows -- LED coordinates, limits, paths -- which is constant for the
        whole session and would otherwise have to be reloaded per board.

        ``preserve_from`` is a page index. Pages below it are board data and are
        cleared; pages at or above it are program data and carry across. Pages
        are the natural axis because that is how real tables already organise
        the store -- a page is a category (detection, paths, per-UUT results),
        not an index within one.
        """
        with self._lock:
            previous = self.data
            previous_dims = self.dims
            self.dims = (lines, cols, pages)
            self.preserve_from = preserve_from
            fresh = [[[None] * pages for _ in range(cols)] for _ in range(lines)]

            if previous is not None and preserve_from is not None:
                keep_from = max(0, min(preserve_from, pages))
                for l in range(min(previous_dims[0], lines)):
                    for c in range(min(previous_dims[1], cols)):
                        for p in range(keep_from, min(previous_dims[2], pages)):
                            fresh[l][c][p] = previous[l][c][p]
            self.data = fresh

        self._seed_variables()

    def _seed_variables(self) -> None:
        """Write every <Vars> initial value into its cell.

        Runs on each INITDATA, which is what makes these constants *static in
        runtime*: a fixture program clears the store at the top of its loop for
        the next board, and these are back before the first step of it runs.
        No <Config> rows, nothing to forget.
        """
        for name, value in self.program.var_values.items():
            coord = self.program.vars.get(name)
            if not coord:
                continue
            try:
                l, c, p = self.parse_coord(coord)
                self.data[l][c][p] = value
            except (ProgramError, IndexError):
                # Reported by the validator against the <Vars> row, where it can
                # be read next to the coordinate that is wrong.
                continue

    def resolve_name(self, ref: str) -> str:
        """Turn a friendly variable name into an ``l,c,p`` coordinate.

        Unknown names pass through untouched so that a literal like ``PASS``
        is not mistaken for a variable.
        """
        return self.program.vars.get(ref, ref)

    def parse_coord(self, ref: str) -> tuple[int, int, int]:
        # A destination is conventionally written bare ("0,0,1") and a source
        # with a leading "*". Accepting "*" on both removes a whole class of
        # authoring slips, at no cost: a destination cannot mean anything else.
        coord = self.resolve_name(ref.strip().lstrip("*").strip())
        m = _COORD_RE.match(coord)
        if not m:
            known = ", ".join(sorted(self.program.vars)[:6])
            hint = f" (known variables: {known})" if self.program.vars else ""
            raise ProgramError(f"bad data reference '{ref}'{hint}")
        return int(m.group(1)), int(m.group(2)), int(m.group(3))

    def get_data(self, ref: str) -> Any:
        if self.data is None:
            raise VerbError("data store not initialised -- call INITDATA first")
        l, c, p = self.parse_coord(ref)
        try:
            return self.data[l][c][p]
        except IndexError:
            raise ProgramError(
                f"data reference {l},{c},{p} is outside the allocated store "
                f"{self.dims[0]}x{self.dims[1]}x{self.dims[2]}"
            ) from None

    def set_data(self, ref: str, value: Any, stringify: bool = True) -> None:
        if self.data is None:
            raise VerbError("data store not initialised -- call INITDATA first")
        l, c, p = self.parse_coord(ref)
        try:
            self.data[l][c][p] = str(value) if stringify else value
        except IndexError:
            raise ProgramError(
                f"data reference {l},{c},{p} is outside the allocated store "
                f"{self.dims[0]}x{self.dims[1]}x{self.dims[2]}"
            ) from None

    def content(self, value: str) -> Any:
        """Resolve one cell: ``*ref`` dereferences, anything else is a literal.

        Mirrors v1's TestData.getContent, including the detail that a
        dereference of an unwritten cell yields None rather than raising.
        """
        if value is None:
            return ""
        value = str(value)
        if value.startswith("*"):
            return self.get_data(value[1:])
        return value

    def text(self, value: str) -> str:
        """content() coerced to str, with None becoming ''.

        Most verbs want this; a raw None sneaking into string concatenation was
        a recurring v1 crash.
        """
        out = self.content(value)
        return "" if out is None else str(out)

    # -- alive mask -------------------------------------------------------

    def init_alive(self, count: int) -> None:
        with self._lock:
            self.alive = [1] * count
        self.emit(AliveEvent(alive=list(self.alive)))

    def start_alive(self) -> None:
        with self._lock:
            self.alive = [1] * len(self.alive)
        self.emit(AliveEvent(alive=list(self.alive)))

    def kill(self, index: int, reason: str = "") -> None:
        with self._lock:
            if not (0 <= index < len(self.alive)):
                raise VerbError(
                    f"cannot kill UUT {index}: alive mask holds "
                    f"{len(self.alive)} unit(s)"
                )
            already = self.alive[index] == 0
            self.alive[index] = 0
        if not already:
            self.log(f"UUT {index} killed{f': {reason}' if reason else ''}", "fail")
            self.emit(AliveEvent(alive=list(self.alive)))

    def verdict(self, index: int, passed: bool, detail: str = "") -> None:
        """Publish one unit's verdict as soon as it is known."""
        self.emit(VerdictEvent(uut=index, passed=passed, detail=detail))

    def is_any_alive(self, mask: str) -> bool:
        """Evaluate column 8.

        - ``-``            run unconditionally
        - ``0,2``          run if UUT 0 **or** 2 is still alive
        - ``-,0,2``        run only if UUT 0 **and** 2 are *both* alive

        The leading-dash "all of" form is v1 behaviour and several tables rely
        on it for steps that only make sense when a whole group survived.
        """
        mask = (mask or "-").strip()
        if mask == "-" or not mask:
            return True
        parts = [x.strip() for x in mask.split(",") if x.strip()]
        if not parts:
            return True

        def _at(token: str) -> int:
            try:
                idx = int(token)
            except ValueError:
                raise ProgramError(f"bad alive mask entry '{token}'") from None
            if not (0 <= idx < len(self.alive)):
                raise ProgramError(
                    f"alive mask references UUT {idx} but only "
                    f"{len(self.alive)} are configured"
                )
            return self.alive[idx]

        if parts[0] == "-":
            return all(_at(t) == 1 for t in parts[1:])
        return any(_at(t) == 1 for t in parts)

    @property
    def any_alive(self) -> bool:
        return any(self.alive) if self.alive else True

    # -- datecodes --------------------------------------------------------

    def set_datecodes(self, now: _dt.datetime | None = None) -> tuple[str, str]:
        now = now or _dt.datetime.now()
        self.datecode = f"{now.year}y_{now.month}m_{now.day}d"
        self.extended_datecode = f"{now.hour}h_{now.minute}m_{now.second}s"
        return self.datecode, self.extended_datecode
