"""Verb registry.

NGINE v1 dispatched with ``getattr(globals()[module], verb)`` -- no signature
was known ahead of time, so a typo in a spreadsheet cell surfaced as an
AttributeError partway through a run, with the fixture powered up.

Here every verb declares itself. That single change is what makes it possible
to lint a whole program *before* energising anything (see validator.py).

A verb is registered against the *module name* the program's <Modules> section
maps to, not the alias, so `Camera -> BaluffManager` and `Camera -> CameraManager`
both work without the verb knowing which alias was used.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .errors import ProgramError


@dataclass(frozen=True)
class Param:
    """One argument column of a verb.

    Columns map onto the legacy layout: index 2 is the first argument,
    index 6 the last. Naming them is what lets error messages say
    "EXCHANGELINE_LVS: missing 'tries'" instead of "index out of range".
    """

    index: int
    name: str
    required: bool = True
    doc: str = ""


@dataclass
class VerbSpec:
    module: str
    name: str
    fn: Callable
    params: tuple[Param, ...] = ()
    doc: str = ""
    legacy: bool = False
    #: Verbs that only make sense during <Config> (they build UI, open ports).
    config_only: bool = False
    #: Verbs the sequencer must run on the calling thread (they touch the UI).
    main_thread: bool = False

    @property
    def key(self) -> tuple[str, str]:
        return (self.module, self.name)

    @property
    def min_args(self) -> int:
        req = [p.index for p in self.params if p.required]
        return max(req) if req else 1

    @property
    def max_args(self) -> int:
        idx = [p.index for p in self.params]
        return max(idx) if idx else 1

    def param_at(self, index: int) -> Param | None:
        for p in self.params:
            if p.index == index:
                return p
        return None


class Registry:
    """Maps (module, verb) -> VerbSpec, with alias support."""

    def __init__(self) -> None:
        self._verbs: dict[tuple[str, str], VerbSpec] = {}
        self._module_aliases: dict[str, str] = {}

    # -- registration -----------------------------------------------------

    def add(self, spec: VerbSpec, override: bool = False) -> VerbSpec:
        """Register a verb.

        `override` exists for one purpose: letting a site's own, hardware-proven
        driver displace the bundled one. Some vendor code encodes knowledge that
        cannot be re-derived from a datasheet -- buffer geometry, parameter-set
        semantics, driver lifetime rules -- and a rewrite of it is a liability,
        not an improvement.
        """
        if spec.key in self._verbs and not override:
            raise ValueError(f"duplicate verb {spec.module}.{spec.name}")
        self._verbs[spec.key] = spec
        return spec

    def alias_verb(self, module: str, new_name: str, target: str, **overrides) -> VerbSpec:
        """Register `new_name` pointing at an already-registered verb.

        This is how the 27 legacy serial verbs collapse onto one implementation:
        each old name becomes an alias that pre-binds its (op, payload,
        terminator, level) combination. Old programs keep working; there is one
        function to maintain.
        """
        base = self._verbs.get((module, target))
        if base is None:
            raise ValueError(f"cannot alias {new_name}: {module}.{target} not registered")
        spec = VerbSpec(
            module=module,
            name=new_name,
            fn=overrides.pop("fn", base.fn),
            params=overrides.pop("params", base.params),
            doc=overrides.pop("doc", base.doc),
            legacy=overrides.pop("legacy", True),
            config_only=overrides.pop("config_only", base.config_only),
            main_thread=overrides.pop("main_thread", base.main_thread),
        )
        return self.add(spec)

    def alias_module(self, alias: str, module: str) -> None:
        """Make one module name resolve to another's verb table.

        Used so `CameraManager` and `BaluffManager` can share an implementation
        where the verbs are identical.
        """
        self._module_aliases[alias] = module

    # -- lookup -----------------------------------------------------------

    def resolve_module(self, module: str) -> str:
        seen = set()
        while module in self._module_aliases and module not in seen:
            seen.add(module)
            module = self._module_aliases[module]
        return module

    def lookup(self, module: str, verb: str) -> VerbSpec | None:
        return self._verbs.get((self.resolve_module(module), verb))

    def require(self, module: str, verb: str, row: int | None = None) -> VerbSpec:
        spec = self.lookup(module, verb)
        if spec is None:
            known = self.verbs_for(module)
            hint = ""
            if known:
                near = _closest(verb, known)
                if near:
                    hint = f" (did you mean {near}?)"
            else:
                hint = f" (module '{module}' has no registered verbs)"
            raise ProgramError(f"unknown verb {module}.{verb}{hint}", row=row)
        return spec

    def verbs_for(self, module: str) -> list[str]:
        real = self.resolve_module(module)
        return sorted(name for (mod, name) in self._verbs if mod == real)

    def modules(self) -> list[str]:
        return sorted({mod for (mod, _) in self._verbs})

    def all(self) -> Iterable[VerbSpec]:
        return self._verbs.values()

    def __len__(self) -> int:
        return len(self._verbs)


#: The registry the bundled drivers populate at import time.
REGISTRY = Registry()


def verb(module: str, name: str, *, params: Iterable[Param] = (), doc: str = "",
         config_only: bool = False, main_thread: bool = False,
         registry: Registry | None = None):
    """Decorator registering a verb implementation.

    The function is called as ``fn(ctx, row)``. Keeping the calling convention
    uniform (rather than unpacking declared params into positional arguments)
    is deliberate: it lets legacy shims and native verbs share one dispatch
    path, and lets a verb decide for itself whether an optional column is
    present.
    """

    reg = registry or REGISTRY

    def deco(fn: Callable) -> Callable:
        reg.add(VerbSpec(
            module=module,
            name=name,
            fn=fn,
            params=tuple(params),
            doc=doc or inspect.getdoc(fn) or "",
            config_only=config_only,
            main_thread=main_thread,
        ))
        return fn

    return deco


def p(index: int, name: str, required: bool = True, doc: str = "") -> Param:
    """Shorthand for declaring a parameter."""
    return Param(index=index, name=name, required=required, doc=doc)


def _closest(word: str, candidates: list[str]) -> str | None:
    """Cheap typo suggestion -- no stdlib difflib import cost at call time."""
    import difflib

    hits = difflib.get_close_matches(word, candidates, n=1, cutoff=0.75)
    return hits[0] if hits else None
