"""Typed exceptions for the NGWART engine.

NGINE v1 signalled errors by formatting them into a string:

    raise Exception(line[7] + "::" + str(e))

and then splitting on "::" back in the run loop. That destroyed tracebacks,
made every failure the same type, and corrupted routing whenever a driver
message happened to contain "::".

Here the routing label is a field. The traceback is preserved by chaining.
"""

from __future__ import annotations


class NgwartError(Exception):
    """Base for every engine-raised error.

    :param message: human-readable description, shown to the operator.
    :param route: label to jump to for recovery, or None to abort the run.
                  Comes from the program row's exception column.
    :param row: index of the program row that failed, filled in by the
                sequencer if the driver did not set it.
    """

    def __init__(self, message: str, route: str | None = None, row: int | None = None):
        super().__init__(message)
        self.message = message
        self.route = route
        self.row = row

    def with_context(self, route: str | None, row: int | None) -> "NgwartError":
        """Attach routing info discovered by the caller, without overwriting."""
        if self.route is None:
            self.route = route
        if self.row is None:
            self.row = row
        return self

    def __str__(self) -> str:
        where = f"row {self.row}: " if self.row is not None else ""
        return f"{where}{self.message}"


class VerbError(NgwartError):
    """A driver verb failed. Routable: the row's exception label applies."""


class HardwareError(VerbError):
    """A verb failed because the instrument misbehaved or is absent.

    Separated from VerbError so the UI can distinguish "the board failed the
    test" from "the test rig is broken" -- operators need to react differently.
    """


class ValidationFailure(VerbError):
    """A measurement was taken successfully but fell outside limits.

    This is a *test* failure, not a *system* failure. The distinction matters
    for yield reporting: a unit that fails a limit is a real reject, whereas a
    HardwareError invalidates the run.
    """

    def __init__(self, message: str, route: str | None = None, row: int | None = None,
                 measured=None, low=None, high=None):
        super().__init__(message, route, row)
        self.measured = measured
        self.low = low
        self.high = high


class ProgramError(NgwartError):
    """The program itself is malformed -- bad reference, unknown verb, etc.

    Never routable. A broken program must not limp along on its own error
    handlers; that is how v1 ended up running past real problems.
    """

    def __init__(self, message: str, row: int | None = None):
        super().__init__(message, route=None, row=row)


class AbortRun(NgwartError):
    """Operator pressed stop, or an unrecoverable condition was hit.

    Teardown still runs -- see Sequencer.run's finally block.
    """


class LoaderError(NgwartError):
    """A program file could not be parsed."""
