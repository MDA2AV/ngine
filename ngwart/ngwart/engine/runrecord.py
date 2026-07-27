"""Structured record of a run.

v1 produced its traceability XML by re-reading the data store at the end
(CargoManager.py:176-223), which meant the report could only contain whatever
happened to still be in the array -- anything overwritten mid-run was lost, and
the report logic had to know the coordinate layout of every product.

Here the sequencer appends a StepRecord as each row executes. The report
generators are then pure functions over the record, and adding a new report
format costs nothing.
"""

from __future__ import annotations

import datetime as _dt
import json
import threading
from dataclasses import asdict, dataclass, field


@dataclass
class StepRecord:
    row: int
    module: str
    verb: str
    args: list[str]
    comment: str
    started: str
    duration_s: float
    outcome: str                     # ok | skipped | failed | routed
    detail: str = ""
    alive_before: list[int] = field(default_factory=list)
    #: Populated when the verb recorded a measurement.
    measurement: dict | None = None


@dataclass
class TestPoint:
    """A named pass/fail judgement, the unit a quality system cares about."""

    #: Stops pytest trying to collect this as a test class.
    __test__ = False

    name: str
    uut: int | None
    result: str                      # PASS | FAIL | RETRY | IRR
    measured: str = ""
    low: str = ""
    high: str = ""
    row: int | None = None
    at: str = ""


class RunRecord:
    """Append-only log of one execution. Thread-safe."""

    def __init__(self, program_name: str = "", operator: str = "",
                 station: str = "", simulate: bool = False) -> None:
        self.program_name = program_name
        self.operator = operator
        self.station = station
        self.simulate = simulate
        self.started = _dt.datetime.now()
        self.ended: _dt.datetime | None = None
        self.steps: list[StepRecord] = []
        self.points: list[TestPoint] = []
        self.barcodes: dict[int, str] = {}
        self.final_alive: list[int] = []
        self.aborted: bool = False
        self.abort_reason: str = ""
        self._lock = threading.Lock()

    # -- writing ----------------------------------------------------------

    def add_step(self, rec: StepRecord) -> None:
        with self._lock:
            self.steps.append(rec)

    def add_point(self, point: TestPoint) -> None:
        if not point.at:
            point.at = _dt.datetime.now().isoformat(timespec="seconds")
        with self._lock:
            self.points.append(point)

    def set_barcode(self, uut: int, code: str) -> None:
        with self._lock:
            self.barcodes[uut] = code

    def finish(self, alive: list[int], aborted: bool = False, reason: str = "") -> None:
        with self._lock:
            self.ended = _dt.datetime.now()
            self.final_alive = list(alive)
            self.aborted = aborted
            self.abort_reason = reason

    # -- reading ----------------------------------------------------------

    @property
    def duration_s(self) -> float:
        end = self.ended or _dt.datetime.now()
        return (end - self.started).total_seconds()

    def points_for(self, uut: int | None) -> list[TestPoint]:
        with self._lock:
            return [p for p in self.points if p.uut == uut]

    def passed(self, uut: int | None = None) -> bool:
        """A UUT passes when it has at least one judged point and none failed.

        Requiring a point to exist is deliberate: a run that fell over before
        testing anything must not be reported as a pass.

        The overall verdict additionally requires that no step failed or was
        diverted to an error handler. Without that, a run whose vision stage
        raised and jumped to VISION_EX would skip every optical test and still
        report PASS on the strength of the measurements that happened to run
        before it -- which is precisely the failure a test station must never
        make.
        """
        pts = self.points_for(uut) if uut is not None else list(self.points)
        if not pts:
            return False
        if any(p.result == "FAIL" for p in pts):
            return False
        if uut is None and self.diverted:
            return False
        return True

    @property
    def diverted(self) -> bool:
        """True when any step failed or was routed to an error handler."""
        with self._lock:
            return any(s.outcome in ("failed", "routed") for s in self.steps)

    def uuts(self) -> list[int]:
        with self._lock:
            return sorted({p.uut for p in self.points if p.uut is not None})

    def summary(self) -> dict:
        return {
            "program": self.program_name,
            "station": self.station,
            "operator": self.operator,
            "simulated": self.simulate,
            "started": self.started.isoformat(timespec="seconds"),
            "ended": self.ended.isoformat(timespec="seconds") if self.ended else None,
            "duration_s": round(self.duration_s, 3),
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
            "steps": len(self.steps),
            "points": len(self.points),
            "failed_points": sum(1 for p in self.points if p.result == "FAIL"),
            "diverted_steps": sum(1 for s in self.steps
                                  if s.outcome in ("failed", "routed")),
            "uuts": {str(u): self.passed(u) for u in self.uuts()},
            "barcodes": {str(k): v for k, v in self.barcodes.items()},
        }

    def to_json(self, indent: int = 2) -> str:
        payload = {
            "summary": self.summary(),
            "points": [asdict(p) for p in self.points],
            "steps": [asdict(s) for s in self.steps],
        }
        return json.dumps(payload, indent=indent, default=str)
