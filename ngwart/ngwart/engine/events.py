"""Engine -> UI event channel.

The engine never imports Qt. It emits plain dataclass events to a listener,
and the Qt layer adapts those into signals (see ui/bridge.py). That keeps the
whole sequencer testable headlessly -- the test suite runs it with a recording
listener and asserts on the event stream.

It also means the engine thread never touches a widget, which is the actual
root cause of v1's frozen UI: there, the Tk update loop and the test loop were
coroutines on one event loop, so a blocking serial read froze the display.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Protocol


# --- events -------------------------------------------------------------

@dataclass
class LogEvent:
    message: str
    level: str = "info"  # info | warn | error | pass | fail
    row: int | None = None


@dataclass
class StepEvent:
    row: int
    text: str
    comment: str = ""


@dataclass
class StatusEvent:
    text: str
    color: str | None = None


@dataclass
class ProgressEvent:
    #: 0.0-1.0, or -1.0 for indeterminate.
    value: float


@dataclass
class TimerEvent:
    seconds: float


@dataclass
class GridEvent:
    """A mutation of one of the result grids."""

    grid: int
    op: str                      # add | clear | place | unplace | config
    values: list[str] = field(default_factory=list)
    tag: str = ""
    config: dict = field(default_factory=dict)


@dataclass
class FieldEvent:
    """A named single-value UI field (barcode entries, counters, monitors)."""

    name: str
    value: str
    color: str | None = None


@dataclass
class AliveEvent:
    alive: list[int]


@dataclass
class RunStateEvent:
    state: str                   # idle | validating | running | stopping | teardown
    detail: str = ""


@dataclass
class ResultEvent:
    """Terminal verdict for the run."""

    passed: bool
    per_uut: dict[int, bool] = field(default_factory=dict)
    detail: str = ""


Event = Any


# --- listeners ----------------------------------------------------------

class Listener(Protocol):
    def emit(self, event: Event) -> None: ...


class NullListener:
    """Discards everything. Default so the engine can run truly headless."""

    def emit(self, event: Event) -> None:  # noqa: D102
        pass


class RecordingListener:
    """Keeps every event. Used by the test suite and the run recorder."""

    def __init__(self) -> None:
        self.events: list[Event] = []
        self._lock = threading.Lock()

    def emit(self, event: Event) -> None:
        with self._lock:
            self.events.append(event)

    def of_type(self, cls) -> list:
        with self._lock:
            return [e for e in self.events if isinstance(e, cls)]

    def messages(self) -> list[str]:
        return [e.message for e in self.of_type(LogEvent)]

    def clear(self) -> None:
        with self._lock:
            self.events.clear()


class FanOut:
    """Broadcasts to several listeners.

    Registration is guarded because the UI may attach while the engine thread
    is already emitting.
    """

    def __init__(self, *listeners: Listener) -> None:
        self._listeners: list[Listener] = list(listeners)
        self._lock = threading.Lock()

    def add(self, listener: Listener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def remove(self, listener: Listener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def emit(self, event: Event) -> None:
        with self._lock:
            targets = list(self._listeners)
        for listener in targets:
            # A misbehaving listener must never take down a test run mid-fixture.
            try:
                listener.emit(event)
            except Exception:  # noqa: BLE001
                pass
