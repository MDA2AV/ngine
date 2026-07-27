"""Accumulated state of the current run.

A client that connects late must see everything, not just what happened
recently. Replaying the last N raw events cannot do that: a program emitting
hundreds of log lines pushes its earlier results out of any bounded window, so a
browser opened partway through showed three results per unit while the desktop
station -- attached from the start -- showed twenty.

So the server keeps a model. A new client is sent the model in full and then
follows the event stream from there. That is the difference between "here is
what just happened" and "here is where the run has got to".
"""

from __future__ import annotations

import threading

from ..engine.events import (AliveEvent, FieldEvent, GridEvent, LogEvent,
                             ProgressEvent, ResultEvent, RunStateEvent,
                             StatusEvent, StepEvent, TimerEvent)

#: The log is the one thing kept bounded -- a shift's worth would be megabytes
#: over the wire on every connect, and older lines are in the run record.
LOG_TAIL = 400


class LiveModel:
    """Everything a client needs to render the run as it stands. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.grids: dict[int, dict] = {}
            self.log: list[dict] = []
            self.banner = {"text": "READY", "colour": None}
            self.progress = 0.0
            self.elapsed = 0.0
            self.alive: list[int] = []
            self.fields: dict[str, str] = {}
            self.step = ""
            self.run_state = "idle"
            self.points = 0
            self.failed = 0
            self.result: dict | None = None

    # -- ingest -----------------------------------------------------------

    def observe(self, event) -> None:
        """Fold one engine event into the model. Never raises."""
        try:
            self._observe(event)
        except Exception:  # noqa: BLE001 - telemetry must not break a run
            pass

    def _observe(self, event) -> None:
        with self._lock:
            if isinstance(event, GridEvent):
                self._grid(event)
            elif isinstance(event, LogEvent):
                self.log.append({"message": event.message, "level": event.level,
                                 "row": event.row})
                if len(self.log) > LOG_TAIL:
                    del self.log[: len(self.log) - LOG_TAIL]
            elif isinstance(event, StatusEvent):
                self.banner = {"text": event.text, "colour": event.color}
            elif isinstance(event, ProgressEvent):
                self.progress = event.value
            elif isinstance(event, TimerEvent):
                self.elapsed = event.seconds
            elif isinstance(event, AliveEvent):
                self.alive = list(event.alive)
            elif isinstance(event, FieldEvent):
                self.fields[event.name] = event.value
            elif isinstance(event, StepEvent):
                self.step = f"{event.text} {event.comment}".strip()
            elif isinstance(event, RunStateEvent):
                self.run_state = event.state
                if event.state == "validating":
                    # A new run starts here, so drop the previous one's results
                    # rather than letting a client see two runs interleaved.
                    self._reset_run()
            elif isinstance(event, ResultEvent):
                self.result = {"passed": event.passed,
                               "per_uut": {str(k): v
                                           for k, v in event.per_uut.items()},
                               "detail": event.detail}

    def _reset_run(self) -> None:
        for grid in self.grids.values():
            grid["rows"] = []
            grid["passed"] = 0
            grid["failed"] = 0
        self.log = []
        self.points = self.failed = 0
        self.progress = 0.0
        self.result = None
        self.step = ""

    def _grid(self, event: GridEvent) -> None:
        grid = self.grids.setdefault(
            event.grid, {"columns": [], "rows": [], "passed": 0, "failed": 0})

        if event.op == "clear":
            grid["rows"] = []
            grid["passed"] = grid["failed"] = 0
        elif event.op == "config":
            if event.config.get("columns"):
                grid["columns"] = list(event.config["columns"])
        elif event.op == "add":
            grid["rows"].append({"values": list(event.values), "tag": event.tag})
            tag = (event.tag or "").upper()
            if tag == "FAIL":
                grid["failed"] += 1
                self.failed += 1
            else:
                grid["passed"] += 1
            self.points += 1

    # -- emit -------------------------------------------------------------

    def snapshot(self) -> dict:
        """The whole run so far, for a client that has just connected."""
        with self._lock:
            return {
                "grids": {str(k): {"columns": v["columns"],
                                   "rows": v["rows"],
                                   "passed": v["passed"],
                                   "failed": v["failed"]}
                          for k, v in sorted(self.grids.items())},
                "log": list(self.log),
                "banner": dict(self.banner),
                "progress": self.progress,
                "elapsed": self.elapsed,
                "alive": list(self.alive),
                "fields": dict(self.fields),
                "step": self.step,
                "run_state": self.run_state,
                "points": self.points,
                "failed": self.failed,
                "result": self.result,
            }
