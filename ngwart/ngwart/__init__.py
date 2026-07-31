"""NGWART -- functional test sequencer.

A rewrite of NGINE that keeps what worked (a spreadsheet is the test program,
one row per instruction, a per-UUT alive mask) and replaces what did not (a
frozen UI, string-typed errors, no validation, no guaranteed teardown).

    from ngwart import load, run

    record = run(load("programs/demo/demo.yaml"), simulate=True)
    print(record.summary())
"""

from __future__ import annotations

__version__ = "2.0.0"

from .engine import (REGISTRY, Context, Program, RunOptions, RunRecord,
                     Sequencer, validate)
from .engine.loaders import load, save

__all__ = [
    "__version__", "load", "save", "run", "validate",
    "Program", "Context", "Sequencer", "RunOptions", "RunRecord", "REGISTRY",
]


def run(program: Program, *, simulate: bool = False, strict: bool = True,
        listener=None, operator: str = "", station: str = "",
        workdir: str = ".") -> RunRecord:
    """Execute a program on the calling thread and return its record."""
    from . import drivers  # noqa: F401 - registers the verbs

    options = RunOptions(simulate=simulate, strict=strict, operator=operator,
                         station=station, workdir=workdir)
    return Sequencer(listener=listener, options=options).run(program)
