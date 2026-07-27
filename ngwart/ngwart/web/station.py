"""Headless station controller.

Everything the operator window does, minus the widgets: hold a program, validate
it, run it on a worker thread, stop it, and report what happened. The Qt window
and the web server are two front ends over this same object, which is what stops
the web mode becoming a second, subtly different application.
"""

from __future__ import annotations

import os
import threading

from ..engine import (REGISTRY, Context, RunOptions, RunThread, Sequencer,
                      validate)
from ..engine.loaders import load
from ..engine.program import Program


class Station:
    """One test station: a loaded program and at most one run at a time."""

    def __init__(self, listener=None, simulate: bool = False,
                 debug_dir: str | None = None, station: str = "",
                 operator: str = "", allow_control: bool = False) -> None:
        self.listener = listener
        self.simulate = simulate
        self.debug_dir = debug_dir
        self.station = station
        self.operator = operator
        self.allow_control = allow_control

        self.program: Program | None = None
        self.program_path: str | None = None
        self.report: object | None = None
        self.record = None

        self._sequencer: Sequencer | None = None
        self._thread: RunThread | None = None
        self._lock = threading.Lock()

    # -- state ------------------------------------------------------------

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def state(self) -> dict:
        """Everything a client needs to render the station, in one object."""
        program = self.program
        return {
            "program": {
                "name": program.meta.get("name") if program else None,
                "path": self.program_path,
                "rows": len(program.rows) if program else 0,
                "labels": len(program.labels) if program else 0,
                "units": self.unit_count(),
                "valid": bool(self.report and self.report.ok),
            } if program else None,
            "diagnostics": [
                {"severity": d.severity, "row": d.row, "message": d.message,
                 "detail": d.detail}
                for d in (self.report or [])
            ],
            "running": self.running,
            "simulate": self.simulate,
            "debug": bool(self.debug_dir),
            "control": self.allow_control,
            "station": self.station,
            "operator": self.operator,
            "last_run": self.record.summary() if self.record else None,
        }

    def unit_count(self) -> int:
        """How many units the program declares, so a client sizes its panels."""
        if self.program is None:
            return 0
        from ..engine.validator import _declared_alive_size

        return _declared_alive_size(self.program) or 0

    # -- commands ---------------------------------------------------------

    def load(self, path: str) -> dict:
        if self.running:
            raise RuntimeError("a test is running; stop it before loading")
        program = load(path)
        report = validate(program, REGISTRY)
        with self._lock:
            self.program = program
            self.program_path = os.path.abspath(path)
            self.report = report
        return self.state()

    def start(self) -> dict:
        if not self.allow_control:
            raise PermissionError(
                "this server is read-only; start it with --allow-control to "
                "run tests remotely")
        if self.program is None:
            raise RuntimeError("no program loaded")
        if self.running:
            raise RuntimeError("a test is already running")
        if self.report is not None and not self.report.ok:
            raise RuntimeError(
                f"program failed validation: {self.report.summary()}")

        options = RunOptions(
            simulate=self.simulate,
            strict=True,
            operator=self.operator,
            station=self.station,
            workdir=os.path.dirname(self.program_path or ".") or ".",
            debug_dir=self.debug_dir,
        )
        self._sequencer = Sequencer(REGISTRY, self.listener, options)
        ctx = Context(self.program, self.listener, simulate=self.simulate,
                      workdir=options.workdir)
        self._thread = RunThread(self._sequencer, self.program, ctx)
        self._thread.start()
        return self.state()

    def stop(self) -> dict:
        if not self.allow_control:
            raise PermissionError("this server is read-only")
        if self._sequencer is not None:
            self._sequencer.stop()
        return self.state()

    def collect(self) -> None:
        """Pick up the record once a finished thread has been joined."""
        if self._thread and not self._thread.is_alive():
            self.record = self._thread.record or self.record

    def programs(self, directory: str) -> list[dict]:
        """List loadable programs in a directory, for a client's picker."""
        from ..engine.loaders import LEGACY_EXTS, NATIVE_EXTS

        allowed = LEGACY_EXTS | NATIVE_EXTS
        out = []
        if not os.path.isdir(directory):
            return out
        for entry in sorted(os.listdir(directory)):
            path = os.path.join(directory, entry)
            if not os.path.isfile(path):
                continue
            if os.path.splitext(entry)[1].lower() not in allowed:
                continue
            # LibreOffice lock files sit next to the real thing and are not
            # programs.
            if entry.startswith("~$") or entry.startswith(".~lock"):
                continue
            out.append({"name": entry, "path": os.path.abspath(path),
                        "size": os.path.getsize(path)})
        return out
