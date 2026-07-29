"""NGWART execution engine -- framework-agnostic, no UI imports."""

from __future__ import annotations

from .context import Context
from .errors import (AbortRun, HardwareError, LoaderError, NgwartError,
                     ProgramError, ValidationFailure, VerbError)
from .events import (AliveEvent, Event, FanOut, FieldEvent, GridEvent, Listener,
                     LogEvent, NullListener, ProgressEvent, RecordingListener,
                     ResultEvent, RunStateEvent, StatusEvent, StepEvent,
                     TimerEvent, VerdictEvent)
from .program import Program, Row, Section
from .registry import REGISTRY, Param, Registry, VerbSpec, p, verb
from .runrecord import RunRecord, StepRecord, TestPoint
from .sequencer import RunOptions, RunThread, Sequencer
from .telemetry import DEFAULT_PORT, TelemetryServer
from .validator import Diagnostic, Report, validate

__all__ = [
    "Context", "Program", "Row", "Section",
    "REGISTRY", "Registry", "VerbSpec", "Param", "verb", "p",
    "Sequencer", "RunOptions", "RunThread",
    "TelemetryServer", "DEFAULT_PORT",
    "validate", "Report", "Diagnostic",
    "RunRecord", "StepRecord", "TestPoint",
    "NgwartError", "VerbError", "HardwareError", "ValidationFailure",
    "ProgramError", "AbortRun", "LoaderError",
    "Listener", "NullListener", "RecordingListener", "FanOut", "Event",
    "LogEvent", "StepEvent", "StatusEvent", "ProgressEvent", "TimerEvent",
    "GridEvent", "FieldEvent", "AliveEvent", "RunStateEvent", "ResultEvent",
    "VerdictEvent",
]
