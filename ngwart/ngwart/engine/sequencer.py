"""The run loop.

Differences from NGINE v1's ``Loop.Go`` that matter:

1. It runs on a worker thread, not on the UI's event loop. Blocking driver
   calls therefore cannot freeze the display -- which is what actually made v1
   feel broken during every serial read.

2. ``<Teardown>`` is guaranteed. v1 ended a failed run with ``break``, leaving
   supplies energised and relays closed until the *next* run's opening rows
   happened to reset them. Here teardown executes in a ``finally``, and runs
   even after an operator stop or a crash.

3. ``<ParallelTask>`` is real. v1 gathered coroutines that performed blocking
   I/O, so "parallel" steps ran strictly one after another. Here they go to a
   thread pool.

4. Errors carry a routing label as a field rather than being packed into the
   message string and split back out.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .context import Context
from .errors import AbortRun, NgwartError, ProgramError, VerbError
from .events import (Listener, NullListener, ProgressEvent, ResultEvent,
                     RunStateEvent, StepEvent)
from .program import Program, Row
from .registry import REGISTRY, Registry
from .runrecord import RunRecord, StepRecord
from .validator import validate

PARALLEL_OPEN = "<ParallelTask>"
PARALLEL_CLOSE = "<ParallelTask/>"

#: Label a failure falls back to when its row names no handler. Established by
#: v1's tables, which put it in an <Ehandling> block alongside the per-subsystem
#: handlers (SERIAL_EX, VISA_EX, CAM_EX, ...).
DEFAULT_ROUTE = "STD_EX"


@dataclass
class RunOptions:
    simulate: bool = False
    #: Refuse to start when validation reports errors. Turning this off is for
    #: bench debugging only; the UI never does.
    strict: bool = True
    max_parallel: int = 8
    operator: str = ""
    station: str = ""
    workdir: str = "."
    #: Emit a progress update at most this often, to keep the UI cheap.
    progress_interval_s: float = 0.1
    #: Directory for a debug bundle, or None. Costs disk and a little time per
    #: vision step, so it is opt-in.
    debug_dir: str | None = None


class Sequencer:
    """Executes one Program. Reusable, but not concurrently."""

    def __init__(self, registry: Registry | None = None,
                 listener: Listener | None = None,
                 options: RunOptions | None = None) -> None:
        self.registry = registry or REGISTRY
        self.listener = listener or NullListener()
        self.options = options or RunOptions()
        self._stop = threading.Event()
        self._running = threading.Event()
        self._last_progress = 0.0

    # -- lifecycle --------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running.is_set()

    def stop(self) -> None:
        """Ask the run to wind up. Teardown still executes."""
        self._stop.set()

    def run(self, program: Program, ctx: Context | None = None) -> RunRecord:
        """Execute a program end to end and return its record."""
        self._stop.clear()
        self._running.set()

        ctx = ctx or Context(program, self.listener, simulate=self.options.simulate,
                             workdir=self.options.workdir)
        ctx.stop_requested = self._stop
        record = RunRecord(
            program_name=program.meta.get("name", program.source),
            operator=self.options.operator,
            station=self.options.station,
            simulate=self.options.simulate,
        )
        ctx.record = record

        bundle, recorder = None, None
        if self.options.debug_dir:
            from .debug import DebugBundle
            from .events import FanOut, RecordingListener

            bundle = DebugBundle(self.options.debug_dir,
                                 program.meta.get("name", "run"))
            # The engine's own recorder, so log.txt is complete regardless of
            # what the caller attached -- a FanOut or a Qt bridge cannot be
            # replayed after the fact.
            recorder = RecordingListener()
            ctx.listener = FanOut(ctx.listener, recorder)
            ctx.debug = bundle
            bundle.write_program(program)
            ctx.log(f"Debug bundle: {bundle.dir}")

        aborted, reason = False, ""
        try:
            self._emit(RunStateEvent("validating"))
            report = validate(program, self.registry)
            if bundle:
                bundle.write_diagnostics(report)
            for diag in report:
                ctx.log(str(diag), "error" if diag.is_error else "warn")
            if self.options.strict and not report.ok:
                raise AbortRun(
                    f"program failed validation: {report.summary()} -- nothing was executed"
                )

            self._emit(RunStateEvent("running"))
            ctx.timers.reset()

            if program.section("Config") is not None:
                self._run_section(ctx, program, "Config")
            self._run_exec(ctx, program)

        except AbortRun as exc:
            aborted, reason = True, str(exc)
            ctx.log(str(exc), "error")
        except NgwartError as exc:
            aborted, reason = True, str(exc)
            ctx.log(f"Run aborted: {exc}", "error")
        except Exception as exc:  # noqa: BLE001 - last line of defence
            aborted, reason = True, f"internal error: {exc!r}"
            ctx.log(f"Run aborted, internal error: {exc!r}", "error")
        finally:
            self._run_teardown(ctx, program)
            record.finish(ctx.alive, aborted=aborted, reason=reason)
            if bundle:
                try:
                    bundle.write_datastore(ctx)
                    bundle.finish(record, recorder)
                    ctx.log(f"Debug bundle written: {bundle.dir}")
                except Exception as exc:  # noqa: BLE001 - never fail a run for this
                    ctx.log(f"Debug bundle incomplete: {exc}", "warn")
            self._running.clear()
            self._emit(RunStateEvent("idle"))
            self._emit(ResultEvent(
                passed=(not aborted) and record.passed(),
                per_uut={u: record.passed(u) for u in record.uuts()},
                detail=reason,
            ))
        return record

    # -- sections ---------------------------------------------------------

    def _run_section(self, ctx: Context, program: Program, name: str) -> None:
        section = program.section(name)
        if section is None:
            return
        ctx.log(f"--- {name} ---")
        for index in section.body:
            if index >= len(program.rows):
                break
            if self._stop.is_set() and name != "Teardown":
                raise AbortRun("stopped by operator")
            row = program.rows[index]
            ctx.pointer = index
            if self._skippable(row):
                continue
            self._dispatch(ctx, row, phase=name)
            ctx.take_jump()  # jumps are meaningless outside <Exec>

    def _run_teardown(self, ctx: Context, program: Program) -> None:
        """Always-run safe-state block.

        Deliberately tolerant: a teardown step that fails must not prevent the
        remaining steps from running, or one stuck relay would leave the supply
        on. Failures are logged and recorded, never re-raised.
        """
        section = program.section("Teardown")
        if section is None:
            return
        self._emit(RunStateEvent("teardown"))
        ctx.log("--- Teardown ---")
        for index in section.body:
            if index >= len(program.rows):
                break
            row = program.rows[index]
            ctx.pointer = index
            if self._skippable(row):
                continue
            try:
                self._dispatch(ctx, row, phase="Teardown", check_alive=False)
            except Exception as exc:  # noqa: BLE001
                ctx.log(f"Teardown step failed (continuing): {exc}", "error")
            finally:
                ctx.take_jump()

    def _run_exec(self, ctx: Context, program: Program) -> None:
        section = program.section("Exec")
        if section is None:
            raise ProgramError("program has no <Exec> section")

        end = min(program.exec_end, len(program.rows))
        span_start, span_end = program.span
        span = max(span_end - span_start, 1)

        ctx.pointer = section.start + 1
        while ctx.pointer < end:
            if self._stop.is_set():
                raise AbortRun("stopped by operator")

            row = program.rows[ctx.pointer]
            self._report_progress(ctx, span_start, span)

            if row.verb and not row.module.strip():
                # Loud, because it is silent data loss: v1 raised KeyError on
                # globals()[""] and diverted to the row's handler, so the step
                # never ran and nobody noticed.
                ctx.log(f"{row.index}- '{row.verb}' has no module in column 0 "
                        f"-- step skipped", "warn")
                ctx.pointer += 1
                continue

            if self._skippable(row):
                ctx.pointer += 1
                continue

            if row.module.strip() == PARALLEL_OPEN:
                ctx.pointer = self._run_parallel(ctx, program, ctx.pointer, end)
                continue
            if row.module.strip() == PARALLEL_CLOSE:
                ctx.pointer += 1
                continue

            if not ctx.is_any_alive(row.alive):
                self._record_skip(ctx, row, f"no live UUT in mask '{row.alive}'")
                ctx.pointer += 1
                continue

            try:
                self._dispatch(ctx, row, phase="Exec")
            except NgwartError as exc:
                target = self._route(ctx, exc, row)
                if target is None:
                    raise
                ctx.pointer = program.label_index(target)
                continue

            jump = ctx.take_jump()
            if jump is not None:
                ctx.pointer = program.label_index(jump)
                continue

            ctx.pointer += 1

        ctx.progress(1.0)

    # -- dispatch ---------------------------------------------------------

    def _dispatch(self, ctx: Context, row: Row, phase: str,
                  check_alive: bool = True) -> None:
        module = ctx.program.modules.get(row.module, row.module)
        spec = self.registry.require(module, row.verb, row=row.index)

        self._emit(StepEvent(row=row.index, text=str(row), comment=row.comment))
        started = time.time()
        alive_before = list(ctx.alive)
        outcome, detail = "ok", ""

        try:
            spec.fn(ctx, row)
        except NgwartError as exc:
            exc.with_context(row.route, row.index)
            outcome = "failed"
            detail = str(exc)
            raise
        except Exception as exc:  # noqa: BLE001 - driver raised something raw
            outcome = "failed"
            detail = f"{type(exc).__name__}: {exc}"
            # Wrap, preserving the original as __cause__ so the traceback
            # survives -- the thing v1's string-formatted exceptions destroyed.
            raise VerbError(
                f"{row.module}.{row.verb}: {detail}", route=row.route, row=row.index
            ) from exc
        finally:
            ctx.record.add_step(StepRecord(
                row=row.index, module=row.module, verb=row.verb,
                args=row.args, comment=row.comment,
                started=time.strftime("%H:%M:%S", time.localtime(started)),
                duration_s=round(time.time() - started, 4),
                outcome=outcome, detail=detail, alive_before=alive_before,
            ))
        ctx.tick_timer()

    def _route(self, ctx: Context, exc: NgwartError, row: Row) -> str | None:
        """Decide where a failure goes.

        A ProgramError is never routable: a malformed program must stop, not
        limp along on its own error handlers.
        """
        if isinstance(exc, ProgramError):
            ctx.log(f"Program error: {exc}", "error")
            return None

        target = exc.route or row.route
        if not target:
            # v1 default: a blank exception column became "-", which the run
            # loop rewrote to STD_EX. Real tables rely on this -- cargo.ods
            # defines STD_EX ("System FAIL") in its <Ehandling> block and most
            # rows leave column 7 empty on purpose.
            target = DEFAULT_ROUTE if DEFAULT_ROUTE in ctx.program.labels else None
        if not target:
            ctx.log(f"Unhandled failure: {exc}", "error")
            return None
        if target not in ctx.program.labels:
            # v1 left the pointer untouched here, which re-executed the failing
            # row forever. Aborting is the honest outcome.
            ctx.log(f"Failure routed to '{target}', which is not a label: {exc}", "error")
            return None

        ctx.log(f"{exc} -> jumping to {target}", "warn")
        if ctx.record.steps:
            ctx.record.steps[-1].outcome = "routed"
        return target

    # -- parallel ---------------------------------------------------------

    def _run_parallel(self, ctx: Context, program: Program, start: int, end: int) -> int:
        """Execute a <ParallelTask> block concurrently; return the next pointer."""
        rows: list[Row] = []
        i = start + 1
        while i < end and program.rows[i].module.strip() != PARALLEL_CLOSE:
            row = program.rows[i]
            if not self._skippable(row):
                rows.append(row)
            i += 1
        if i >= end:
            raise ProgramError("<ParallelTask> is never closed", row=start)

        runnable = []
        for row in rows:
            if ctx.is_any_alive(row.alive):
                runnable.append(row)
            else:
                self._record_skip(ctx, row, f"no live UUT in mask '{row.alive}'")

        if not runnable:
            return i + 1

        ctx.log(f"Parallel block: {len(runnable)} task(s)")
        workers = min(len(runnable), max(1, self.options.max_parallel))
        errors: list[NgwartError] = []

        with ThreadPoolExecutor(max_workers=workers,
                                thread_name_prefix="ngwart-par") as pool:
            futures = {pool.submit(self._parallel_one, ctx, row): row for row in runnable}
            for future in futures:
                try:
                    future.result()
                except NgwartError as exc:
                    errors.append(exc)
                except Exception as exc:  # noqa: BLE001
                    errors.append(VerbError(str(exc), row=futures[future].index))

        if errors:
            # Surface the first failure; the rest are already logged. Routing
            # uses the failing row's own label.
            raise errors[0]
        return i + 1

    def _parallel_one(self, ctx: Context, row: Row) -> None:
        try:
            self._dispatch(ctx, row, phase="Parallel")
        except NgwartError as exc:
            ctx.log(f"Parallel task failed: {exc}", "error")
            raise
        finally:
            # A jump requested inside a parallel block has no defined target
            # ordering, so it is dropped rather than silently racing.
            if ctx.pending_jump:
                ctx.log(
                    f"Ignoring jump to '{ctx.pending_jump}' requested inside a "
                    f"parallel block (row {row.index})", "warn")
                ctx.pending_jump = None

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _skippable(row: Row) -> bool:
        module = row.module.strip()
        # Parallel markers carry no verb but are not skippable -- they are
        # handled by the exec loop itself.
        if module in (PARALLEL_OPEN, PARALLEL_CLOSE):
            return False
        if row.is_blank:
            return True
        if module in ("", "-"):
            return True
        if module.startswith("<"):
            return True
        return not row.verb

    def _record_skip(self, ctx: Context, row: Row, why: str) -> None:
        ctx.log(f"{row.index}- skipped: {why}")
        ctx.record.add_step(StepRecord(
            row=row.index, module=row.module, verb=row.verb, args=row.args,
            comment=row.comment, started=time.strftime("%H:%M:%S"),
            duration_s=0.0, outcome="skipped", detail=why,
            alive_before=list(ctx.alive),
        ))

    def _report_progress(self, ctx: Context, span_start: int, span: int) -> None:
        now = time.monotonic()
        if now - self._last_progress < self.options.progress_interval_s:
            return
        self._last_progress = now
        value = (ctx.pointer - span_start) / span
        if 0.0 <= value <= 1.0:
            self._emit(ProgressEvent(value=value))
        ctx.tick_timer()

    def _emit(self, event) -> None:
        self.listener.emit(event)


class RunThread(threading.Thread):
    """Convenience wrapper: run a program off the calling thread.

    The Qt layer uses this so the GUI thread only ever handles events.
    """

    def __init__(self, sequencer: Sequencer, program: Program,
                 ctx: Context | None = None) -> None:
        super().__init__(name="ngwart-sequencer", daemon=True)
        self.sequencer = sequencer
        self.program = program
        self.ctx = ctx
        self.record: RunRecord | None = None
        self.error: BaseException | None = None

    def run(self) -> None:
        try:
            self.record = self.sequencer.run(self.program, self.ctx)
        except BaseException as exc:  # noqa: BLE001
            self.error = exc
