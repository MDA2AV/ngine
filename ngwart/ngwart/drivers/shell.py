"""Shell verbs -- registered as ``WinShellManager``.

v1 had seven functions (BLOCK, BLOCKSH, BLOCKSHT, BLOCKT, BLOCK2, NONBLOCK,
ASYNC) covering two switches: run through a shell or not, and wait with or
without a timeout. They are registered here from one implementation.

Two v1 behaviours are deliberately not carried over:

* ``shell=True`` on a command assembled from spreadsheet cells. A test table is
  data, and passing it to a shell means any cell can become a command. The
  ``*SH`` aliases still exist so tables keep loading, but they run the argument
  list directly. Set ``allow_shell=True`` in the driver state if a program truly
  needs shell metacharacters.
* ``os.system("pkill adb")`` at import time.
"""

from __future__ import annotations

import functools
import subprocess

from ..engine.errors import VerbError
from ..engine.registry import REGISTRY, Param, VerbSpec

MODULE = "WinShellManager"
STATE = "shell"


def _args(ctx, cell: str) -> list[str]:
    parts = [x.strip() for x in ctx.text(cell).split(",") if x.strip()]
    if not parts:
        raise VerbError("shell: no command given")
    return parts


def _store(ctx, row, column: int, value) -> None:
    if row.has(column):
        ctx.set_data(row.raw(column), value)


def _run(ctx, row, *, wait: bool, use_shell: bool) -> None:
    argv = _args(ctx, row.raw(2))
    allow_shell = bool(ctx.driver_state(STATE).get("allow_shell", False))
    shell = use_shell and allow_shell
    if use_shell and not allow_shell:
        ctx.log("shell: running argv directly rather than through a shell "
                "(set allow_shell to override)", "warn")

    timeout = None
    if row.has(6):
        spec = [x.strip() for x in ctx.text(row.raw(6)).split(",") if x.strip()]
        try:
            timeout = float(spec[0])
        except (IndexError, ValueError):
            raise VerbError(f"{row.verb}: '{row.raw(6)}' is not 'timeout[,handler]'") from None

    ctx.log(f"shell: {' '.join(argv)}")
    try:
        if not wait:
            subprocess.Popen(argv if not shell else " ".join(argv), shell=shell,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return
        completed = subprocess.run(
            argv if not shell else " ".join(argv), shell=shell,
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except FileNotFoundError as exc:
        raise VerbError(f"{row.verb}: command not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise VerbError(
            f"{row.verb}: '{' '.join(argv)}' did not finish within {timeout}s") from exc
    except OSError as exc:
        raise VerbError(f"{row.verb}: {exc}") from exc

    _store(ctx, row, 3, completed.stdout)
    _store(ctx, row, 4, completed.stderr)
    _store(ctx, row, 5, completed.returncode)
    if completed.returncode != 0:
        ctx.log(f"shell: exit {completed.returncode}: "
                f"{(completed.stderr or '').strip()[:200]}", "warn")


_PARAMS = (
    Param(2, "command", True, "comma-separated argv"),
    Param(3, "stdout_index", False),
    Param(4, "stderr_index", False),
    Param(5, "exitcode_index", False),
    Param(6, "timeout", False, "seconds[,handler]"),
)

for _name, _wait, _shell in (
    ("BLOCK", True, False), ("BLOCK2", True, False), ("BLOCKT", True, False),
    ("BLOCKSH", True, True), ("BLOCKSHT", True, True),
    ("NONBLOCK", False, False), ("ASYNC", False, False),
):
    REGISTRY.add(VerbSpec(
        module=MODULE, name=_name,
        fn=functools.partial(_run, wait=_wait, use_shell=_shell),
        params=_PARAMS, legacy=True,
        doc=("Run a command and wait for it." if _wait
             else "Start a command without waiting."),
    ))

REGISTRY.alias_module("Shell", MODULE)
