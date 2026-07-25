"""Adopt an unported NGINE v1 manager module as-is.

This is the migration path. A v1 manager is a module of

    async def VERBNAME(line, UI): ...

functions that read state from ``TestData`` module globals and call
``UI.addToLbox(...)``. Rather than requiring all 138 verbs be rewritten before
anything can run, this wraps such a module: each function becomes a registered
verb, ``line`` is rebuilt as the 11-element list v1 passed, and a shim object
stands in for the Tk UI.

So day one every legacy verb works, and modules get ported one at a time --
which is the only way a migration like this actually finishes.

Caveats, stated plainly:

* Legacy verbs are opaque to the validator. It can confirm the verb exists, not
  that its arguments are sane.
* They still raise ``Exception("LABEL::message")``; the shim parses that back
  into a typed error so routing keeps working.
* They run on the sequencer's worker thread. A legacy verb that touches Tk
  directly will misbehave -- port those first.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import inspect
import os
import sys
import types

from ..engine.errors import ProgramError, VerbError
from ..engine.registry import REGISTRY, Param, Registry, VerbSpec

#: v1 handed verbs an 11-cell list; several index up to line[10].
_LEGACY_WIDTH = 11

_LEGACY_PARAMS = tuple(
    Param(i, f"arg{i}", False, "legacy verb -- arguments are not declared")
    for i in range(2, 7)
)


class LegacyUI:
    """Stands in for v1's Tk UI object.

    Only the surface legacy managers actually touch is provided; anything else
    raises a clear error naming the attribute, rather than an AttributeError
    from deep inside a driver.
    """

    def __init__(self, ctx) -> None:
        self._ctx = ctx
        self.frames = [_LegacyFrame(ctx)]

    def addToLbox(self, message) -> None:  # noqa: N802 - v1 spelling
        self._ctx.log(str(message))

    def addToTestPageLbox(self, message) -> None:  # noqa: N802
        self._ctx.log(str(message))

    def clearLbox(self) -> None:  # noqa: N802
        pass

    def __getattr__(self, name):
        raise AttributeError(
            f"legacy verb used UI.{name}, which the v2 shim does not provide. "
            f"Port this manager, or extend LegacyUI."
        )


class _LegacyFrame:
    def __init__(self, ctx) -> None:
        self._ctx = ctx
        self.Tree = _NullWidget()
        self.Tree2 = _NullWidget()
        self.Tree3 = _NullWidget()
        self.Tree4 = _NullWidget()
        self.DGRID1_iid = self.DGRID2_iid = 0
        self.DGRID3_iid = self.DGRID4_iid = 0

    def addToLbox(self, message) -> None:  # noqa: N802
        self._ctx.log(str(message))

    def getAllLbox(self) -> str:  # noqa: N802
        return ""


class _NullWidget:
    """Absorbs Tk calls from legacy verbs that paint grids directly."""

    def __getattr__(self, _name):
        return lambda *a, **k: None


def _bind_testdata(ctx, module) -> None:
    """Point a legacy module's ``TestData`` globals at the live context.

    ``data`` and ``Alive`` are shared by reference, so writes a legacy verb makes
    land in the v2 store with no copying back.
    """
    testdata = sys.modules.get("TestData")
    if testdata is None:
        return
    testdata.data = ctx.data
    testdata.Alive = ctx.alive
    testdata.TestTable = [list(r.cells) for r in ctx.program.rows]
    testdata.pointer = ctx.pointer
    testdata.Labels = [{"index": i, "Label": n} for n, i in ctx.program.labels.items()]
    testdata.log_flag = ctx.log_enabled
    lines, cols, pages = ctx.dims
    testdata.lines, testdata.cols, testdata.pages = lines, cols, pages


def _sync_back(ctx) -> None:
    testdata = sys.modules.get("TestData")
    if testdata is None:
        return
    alive = getattr(testdata, "Alive", None)
    if isinstance(alive, list) and len(alive) == len(ctx.alive):
        for i, value in enumerate(alive):
            if value == 0 and ctx.alive[i] == 1:
                ctx.kill(i, reason="legacy verb")
    ctx.log_enabled = bool(getattr(testdata, "log_flag", ctx.log_enabled))


def _call_legacy(ctx, row, *, fn, module, name):
    """Invoke one legacy verb."""
    _bind_testdata(ctx, module)
    line = list(row.cells) + [""] * (_LEGACY_WIDTH - len(row.cells))
    # v1 read empty cells as "-", and several verbs test for exactly that.
    line = [c if c else "-" for c in line[:_LEGACY_WIDTH]]
    ui = LegacyUI(ctx)

    try:
        if inspect.iscoroutinefunction(fn):
            asyncio.run(fn(line, ui))
        else:
            fn(line, ui)
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc, row) from exc
    finally:
        _sync_back(ctx)


def _translate(exc: Exception, row):
    """Turn v1's ``"LABEL::message"`` convention back into a typed error."""
    text = str(exc)
    route, message = row.route, text
    if "::" in text:
        head, _, tail = text.partition("::")
        head = head.strip()
        if head and head != "-":
            route = head
        message = tail.strip() or text
    return VerbError(f"{row.module}.{row.verb}: {message}", route=route, row=row.index)


def adopt(module_name: str, source: str | types.ModuleType | None = None,
          registry: Registry | None = None, skip: set[str] | None = None) -> int:
    """Register every ``UPPERCASE`` function of a legacy manager as a verb.

    :param module_name: the name tables use in <Modules>, e.g. ``CANManager``.
    :param source: an imported module, or a path to the .py file. Defaults to
                   importing `module_name` from sys.path.
    :param skip: verb names to leave unregistered (usually because a native
                 implementation already covers them).
    :returns: how many verbs were registered.
    """
    reg = registry or REGISTRY
    skip = skip or set()

    if isinstance(source, types.ModuleType):
        module = source
    elif isinstance(source, str) and os.path.exists(source):
        module = _load_from_path(module_name, source)
    else:
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            raise ProgramError(
                f"cannot adopt legacy module '{module_name}': {exc}"
            ) from exc

    count = 0
    for name, fn in vars(module).items():
        if name.startswith("_") or not callable(fn):
            continue
        if not isinstance(fn, types.FunctionType):
            continue
        if name != name.upper() and name not in ("initAlive", "updateLabels"):
            continue
        if name in skip or reg.lookup(module_name, name) is not None:
            continue
        import functools

        reg.add(VerbSpec(
            module=module_name, name=name,
            fn=functools.partial(_call_legacy, fn=fn, module=module, name=name),
            params=_LEGACY_PARAMS, legacy=True,
            doc=(inspect.getdoc(fn) or f"Legacy verb {module_name}.{name}."),
        ))
        count += 1
    return count


def _load_from_path(module_name: str, path: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ProgramError(f"cannot load '{path}' as a Python module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        sys.modules.pop(module_name, None)
        raise ProgramError(
            f"legacy module '{path}' failed to import: {exc}. "
            f"Its vendor dependencies must be installed to adopt it."
        ) from exc
    return module


def adopt_directory(directory: str, registry: Registry | None = None,
                    only: set[str] | None = None) -> dict[str, int]:
    """Adopt every ``*Manager.py`` in a v1 ``src`` directory.

    Modules whose vendor SDK is missing are skipped with a note rather than
    aborting the whole sweep -- one absent camera SDK should not stop the serial
    verbs from loading.
    """
    if not os.path.isdir(directory):
        raise ProgramError(f"not a directory: {directory}")
    sys.path.insert(0, directory)
    results: dict[str, int] = {}
    try:
        for entry in sorted(os.listdir(directory)):
            if not entry.endswith(".py"):
                continue
            name = entry[:-3]
            if only is not None and name not in only:
                continue
            if not (name.endswith("Manager") or name == "TestData"):
                continue
            try:
                results[name] = adopt(name, os.path.join(directory, entry), registry)
            except ProgramError as exc:
                results[name] = -1
                print(f"  skipped {name}: {exc}")
    finally:
        if sys.path and sys.path[0] == directory:
            sys.path.pop(0)
    return results
