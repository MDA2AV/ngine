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

from . import __version__


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

    run = sub.add_parser("run", help="execute a program without a UI")
    run.add_argument("program")
    run.add_argument("--simulate", action="store_true")
    run.add_argument("--no-strict", action="store_true",
                     help="run even if validation reports errors (bench use only)")
    run.add_argument("--report", help="write a report here (.xml/.json/.csv)")
    run.add_argument("--quiet", action="store_true")

    check = sub.add_parser("check", help="validate a program")
    check.add_argument("program")
    check.add_argument("--warnings-as-errors", action="store_true")

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


def _load(path: str):
    from . import drivers  # noqa: F401 - registers verbs
    from .engine.loaders import load

    return load(path)


def _cmd_ui(args) -> int:
    from .ui import launch

    return launch(program=args.program, simulate=args.simulate,
                  dark=not args.light, station=args.station,
                  operator=args.operator)


def _cmd_run(args) -> int:
    from .engine import RecordingListener, RunOptions, Sequencer, REGISTRY
    from .engine.events import LogEvent, ResultEvent

    program = _load(args.program)

    class Printer:
        def emit(self, event):
            if isinstance(event, LogEvent) and not args.quiet:
                prefix = {"error": "!!", "warn": " *", "fail": "XX",
                          "pass": "ok"}.get(event.level, "  ")
                row = f"{event.row:>4}" if event.row is not None else "    "
                print(f"{prefix} {row}  {event.message}")

    recorder = RecordingListener()
    from .engine.events import FanOut

    options = RunOptions(simulate=args.simulate, strict=not args.no_strict)
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

    if args.report:
        from .reports import write_report
        import os

        fmt = os.path.splitext(args.report)[1].lstrip(".").lower() or "json"
        write_report(record, args.report, fmt)
        print(f"  report    {args.report}")

    return 0 if (record.passed() and not record.aborted) else 1


def _cmd_check(args) -> int:
    from .engine import REGISTRY, validate

    program = _load(args.program)
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
