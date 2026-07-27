"""Command line interface.

    ngwart ui [program]          launch the operator station
    ngwart run <program>         execute headlessly (CI, smoke tests)
    ngwart check <program>       validate without executing
    ngwart convert <in> <out>    .ods <-> .yaml <-> .csv
    ngwart verbs                 list the registered verbs
    ngwart adopt <v1-src-dir>    report which legacy managers can be adopted
"""

from __future__ import annotations

import argparse
import sys
import time

from . import __version__
from .engine.telemetry import DEFAULT_PORT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ngwart", description="NGWART functional test sequencer")
    parser.add_argument("--version", action="version", version=f"ngwart {__version__}")
    sub = parser.add_subparsers(dest="command")

    ui = sub.add_parser("ui", help="launch the operator station")
    ui.add_argument("program", nargs="?")
    ui.add_argument("--simulate", action="store_true")
    ui.add_argument("--light", action="store_true", help="use the light theme")
    ui.add_argument("--station", default="")
    ui.add_argument("--operator", default="")
    ui.add_argument("--legacy", metavar="V1_SRC_DIR", help=_LEGACY_HELP)
    ui.add_argument("--legacy-only", metavar="MODULES", help=_LEGACY_ONLY_HELP)
    ui.add_argument("--debug", nargs="?", const="debug", metavar="DIR",
                    help=_DEBUG_HELP)
    ui.add_argument("--telemetry", nargs="?", const=DEFAULT_PORT, type=int,
                    metavar="PORT", help=_TELEMETRY_HELP)


    run = sub.add_parser("run", help="execute a program without a UI")
    run.add_argument("program")
    run.add_argument("--simulate", action="store_true")
    run.add_argument("--no-strict", action="store_true",
                     help="run even if validation reports errors (bench use only)")
    run.add_argument("--report", help="write a report here (.xml/.json/.csv)")
    run.add_argument("--quiet", action="store_true")
    run.add_argument("--legacy", metavar="V1_SRC_DIR", help=_LEGACY_HELP)
    run.add_argument("--legacy-only", metavar="MODULES", help=_LEGACY_ONLY_HELP)
    run.add_argument("--debug", nargs="?", const="debug", metavar="DIR",
                    help=_DEBUG_HELP)
    run.add_argument("--telemetry", nargs="?", const=DEFAULT_PORT, type=int,
                    metavar="PORT", help=_TELEMETRY_HELP)


    check = sub.add_parser("check", help="validate a program")
    check.add_argument("program")
    check.add_argument("--warnings-as-errors", action="store_true")
    check.add_argument("--legacy", metavar="V1_SRC_DIR", help=_LEGACY_HELP)
    check.add_argument("--legacy-only", metavar="MODULES", help=_LEGACY_ONLY_HELP)

    convert = sub.add_parser("convert", help="convert between program formats")
    convert.add_argument("source")
    convert.add_argument("destination")

    verbs = sub.add_parser("verbs", help="list registered verbs")
    verbs.add_argument("--module")
    verbs.add_argument("--long", action="store_true")

    adopt = sub.add_parser("adopt", help="adopt legacy v1 manager modules")
    adopt.add_argument("directory", help="a v1 'src' directory")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    return globals()[f"_cmd_{args.command}"](args)


_TELEMETRY_HELP = (
    "serve live execution data on this port (default 8765). Open it in a "
    "browser for a dashboard, or connect a WebSocket client. Runs for the whole "
    "session; the test never waits for a client."
)

_DEBUG_HELP = (
    "write a debug bundle: captures, binary images, contour overlays with the "
    "search window drawn, every data cell, the full log and the run record. "
    "Defaults to ./debug. This is what to send when a test fails unexpectedly."
)

_LEGACY_HELP = (
    "directory of v1 *Manager.py files whose HARDWARE drivers should replace the "
    "bundled ones. Use when the site driver is the authority -- vendor SDK code "
    "often encodes knowledge a rewrite cannot re-derive."
)

_LEGACY_ONLY_HELP = (
    "comma-separated module names to take from --legacy, overriding the default "
    "hardware-only selection (e.g. BaluffManager,WinSerialManager)"
)

#: Never replaced by --legacy unless named explicitly with --legacy-only.
#:
#: UIManager drives Tk widgets directly, so the v1 version cannot paint the Qt
#: grids -- it would fail silently, which is worse than not running at all.
#: FlowManager and TestData are pure logic the v2 engine owns: their v2 forms
#: declare parameters (so the validator can see them), request jumps through the
#: sequencer, and route typed errors. Swapping those back loses real ground.
LEGACY_EXCLUDED = {"UIManager", "FlowManager", "TestData"}


def _use_legacy(directory: str | None, only: str | None = None) -> None:
    """Let a site's own v1 managers displace the bundled hardware drivers.

    Adopting with override=True is deliberate. A rewritten driver that merely
    looks correct is worse than the original: mvIMPACT's DeviceManager lifetime
    rules, packed-pixel buffer geometry and white-balance parameter sets are all
    things the v1 code learned against real hardware.
    """
    if not directory:
        return
    from .drivers.legacy import adopt_directory

    chosen = None
    if only:
        chosen = {name.strip() for name in only.split(",") if name.strip()}

    results = adopt_directory(directory, only=chosen, override=True,
                              exclude=None if chosen else LEGACY_EXCLUDED)
    for name, count in sorted(results.items()):
        if count > 0:
            print(f"  using site driver {name} ({count} verbs)")
    skipped = [k for k, v in results.items() if v < 0]
    if skipped:
        print(f"  unavailable (missing SDK): {', '.join(sorted(skipped))}")
    if not chosen:
        print(f"  keeping v2: {', '.join(sorted(LEGACY_EXCLUDED))} "
              f"(use --legacy-only to override)")


def _start_telemetry(port):
    """Bring up the live feed, or explain why it could not start.

    A port already in use must not stop a test running -- it usually means a
    second station process, which is the operator's problem, not the board's.
    """
    if port is None:
        return None
    from .engine.telemetry import TelemetryServer

    try:
        server = TelemetryServer(port=int(port)).start()
    except OSError as exc:
        print(f"  telemetry disabled: {exc}")
        return None
    print(f"  telemetry live on http://localhost:{server.bound_port}"
          f"  (browser dashboard, or ws://localhost:{server.bound_port})")
    return server


def _load(path: str, legacy: str | None = None, only: str | None = None):
    from . import drivers  # noqa: F401 - registers verbs
    from .engine.loaders import load

    _use_legacy(legacy, only)
    return load(path)


def _cmd_ui(args) -> int:
    from .ui import launch

    _use_legacy(getattr(args, "legacy", None),
                getattr(args, "legacy_only", None))
    return launch(program=args.program, simulate=args.simulate,
                  dark=not args.light, station=args.station,
                  operator=args.operator, debug_dir=getattr(args, "debug", None),
                  telemetry_port=getattr(args, "telemetry", None))


def _cmd_run(args) -> int:
    from .engine import RecordingListener, RunOptions, Sequencer, REGISTRY
    from .engine.events import LogEvent, ResultEvent

    program = _load(args.program, getattr(args, "legacy", None),
                          getattr(args, "legacy_only", None))

    class Printer:
        def emit(self, event):
            if isinstance(event, LogEvent) and not args.quiet:
                prefix = {"error": "!!", "warn": " *", "fail": "XX",
                          "pass": "ok"}.get(event.level, "  ")
                row = f"{event.row:>4}" if event.row is not None else "    "
                print(f"{prefix} {row}  {event.message}")

    recorder = RecordingListener()
    from .engine.events import FanOut

    telemetry = _start_telemetry(getattr(args, "telemetry", None))
    options = RunOptions(simulate=args.simulate, strict=not args.no_strict,
                         debug_dir=getattr(args, "debug", None),
                         telemetry=telemetry)
    sequencer = Sequencer(REGISTRY, FanOut(Printer(), recorder), options)
    record = sequencer.run(program)

    summary = record.summary()
    print()
    print(f"  program   {summary['program']}")
    print(f"  duration  {summary['duration_s']}s")
    print(f"  steps     {summary['steps']}")
    print(f"  points    {summary['points']} ({summary['failed_points']} failed)")
    for uut, ok in summary["uuts"].items():
        print(f"  UUT {uut}     {'PASS' if ok else 'FAIL'}")
    if summary["aborted"]:
        print(f"  ABORTED   {summary['abort_reason']}")

    if getattr(args, "debug", None):
        print()
        print("  Debug bundle written. Send the whole folder -- SUMMARY.txt "
              "lists what is in it.")

    if args.report:
        from .reports import write_report
        import os

        fmt = os.path.splitext(args.report)[1].lstrip(".").lower() or "json"
        write_report(record, args.report, fmt)
        print(f"  report    {args.report}")

    if telemetry is not None:
        # Give a dashboard a moment to drain the final events before the
        # process exits and the socket dies under it.
        time.sleep(0.4)
        telemetry.stop()

    return 0 if (record.passed() and not record.aborted) else 1


def _cmd_check(args) -> int:
    from .engine import REGISTRY, validate

    program = _load(args.program, getattr(args, "legacy", None),
                          getattr(args, "legacy_only", None))
    report = validate(program, REGISTRY)

    for diag in report:
        print(diag)
        if diag.detail:
            print(f"          {diag.detail}")

    print()
    print(f"{args.program}: {len(program.rows)} rows, {len(program.labels)} labels, "
          f"{len(program.modules)} modules")
    print(report.summary())

    if report.errors:
        return 1
    if args.warnings_as_errors and report.warnings:
        return 1
    return 0


def _cmd_convert(args) -> int:
    from .engine.loaders import save

    program = _load(args.source)
    save(program, args.destination)
    print(f"{args.source} -> {args.destination} ({len(program.rows)} rows)")
    return 0


def _cmd_verbs(args) -> int:
    from . import drivers  # noqa: F401
    from .engine import REGISTRY

    specs = sorted(REGISTRY.all(), key=lambda s: (s.module, s.name))
    if args.module:
        specs = [s for s in specs if s.module.lower() == args.module.lower()]
        if not specs:
            print(f"no module '{args.module}'. Known: "
                  f"{', '.join(REGISTRY.modules())}")
            return 1

    current = None
    for spec in specs:
        if spec.module != current:
            current = spec.module
            print(f"\n{current}")
        args_text = ", ".join(f"{p.name}{'' if p.required else '?'}"
                              for p in spec.params)
        line = f"  {spec.name:<26} {args_text}"
        if spec.legacy:
            line += "  [alias]"
        print(line)
        if args.long and spec.doc:
            print(f"      {spec.doc.splitlines()[0]}")
    print(f"\n{len(specs)} verb(s) across {len({s.module for s in specs})} module(s).")
    return 0


def _cmd_adopt(args) -> int:
    from . import drivers  # noqa: F401
    from .drivers.legacy import adopt_directory

    print(f"Adopting legacy managers from {args.directory}\n")
    results = adopt_directory(args.directory)
    for name, count in sorted(results.items()):
        if count < 0:
            print(f"  {name:<26} unavailable")
        elif count == 0:
            print(f"  {name:<26} already covered natively")
        else:
            print(f"  {name:<26} +{count} verb(s)")
    total = sum(c for c in results.values() if c > 0)
    print(f"\n{total} legacy verb(s) adopted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
