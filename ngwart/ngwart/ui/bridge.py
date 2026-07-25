"""Adapter between the engine's event stream and Qt signals.

The engine calls ``emit()`` from its worker thread. Because this object lives on
the GUI thread, Qt delivers each signal through the event queue, so every slot
runs on the GUI thread. That is the whole reason the UI cannot freeze: no
widget is ever touched from the thread doing serial I/O.

This is also the seam that keeps Qt out of the engine -- the engine knows only
about the ``Listener`` protocol.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..engine.events import (AliveEvent, FieldEvent, GridEvent, LogEvent,
                             ProgressEvent, ResultEvent, RunStateEvent,
                             StatusEvent, StepEvent, TimerEvent)


class QtBridge(QObject):
    """Re-emits engine events as Qt signals."""

    logged = Signal(str, str, object)          # message, level, row
    stepped = Signal(int, str, str)            # row, text, comment
    status_changed = Signal(str, object)       # text, colour
    progressed = Signal(float)
    ticked = Signal(float)
    grid_changed = Signal(int, str, list, str, object)
    field_changed = Signal(str, str, object)
    alive_changed = Signal(list)
    state_changed = Signal(str, str)
    finished = Signal(bool, object, str)

    _DISPATCH = {}

    def emit_event(self, event) -> None:
        handler = self._DISPATCH.get(type(event))
        if handler is not None:
            handler(self, event)

    # The engine's Listener protocol.
    def emit(self, event) -> None:  # noqa: A003 - protocol name
        self.emit_event(event)


def _log(self, e):
    self.logged.emit(e.message, e.level, e.row)


def _step(self, e):
    self.stepped.emit(e.row, e.text, e.comment)


def _status(self, e):
    self.status_changed.emit(e.text, e.color)


def _progress(self, e):
    self.progressed.emit(e.value)


def _timer(self, e):
    self.ticked.emit(e.seconds)


def _grid(self, e):
    self.grid_changed.emit(e.grid, e.op, list(e.values), e.tag, dict(e.config))


def _field(self, e):
    self.field_changed.emit(e.name, e.value, e.color)


def _alive(self, e):
    self.alive_changed.emit(list(e.alive))


def _state(self, e):
    self.state_changed.emit(e.state, e.detail)


def _result(self, e):
    self.finished.emit(e.passed, dict(e.per_uut), e.detail)


QtBridge._DISPATCH = {
    LogEvent: _log,
    StepEvent: _step,
    StatusEvent: _status,
    ProgressEvent: _progress,
    TimerEvent: _timer,
    GridEvent: _grid,
    FieldEvent: _field,
    AliveEvent: _alive,
    RunStateEvent: _state,
    ResultEvent: _result,
}
