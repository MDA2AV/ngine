"""Qt operator interface.

Imported lazily by the CLI so that headless use never requires PySide6.
"""

from __future__ import annotations


def launch(program: str | None = None, simulate: bool = False, dark: bool = True,
           station: str = "", operator: str = "", debug_dir: str | None = None,
           telemetry_port: int | None = None,
           legacy_dir: str | None = None,
           history_path: str | None = None) -> int:
    """Start the operator station. Returns the Qt exit code."""
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit(
            "The operator UI needs PySide6.\n"
            "  pip install PySide6\n"
            "Headless use (ngwart run/check) does not require it."
        ) from exc

    import sys

    from .. import drivers  # noqa: F401 - registers verbs
    from .main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("NGWART")
    window = MainWindow(program_path=program, simulate=simulate, dark=dark,
                        station=station, operator=operator, debug_dir=debug_dir,
                        telemetry_port=telemetry_port,
                        legacy_dir=legacy_dir,
                        history_path=history_path)
    window.show()
    return app.exec()


def launch_teach(capture, target, out_path: str, simulate: bool = False,
                 dark: bool = True, station: str = "", operator: str = "",
                 quiet: bool = False, row_index: int | None = None) -> int:
    """Run a capture program, then open the teach window over its frame.

    The capture runs *before* the window exists, deliberately. It energises the
    fixture and takes a picture; nothing should be waiting on a widget while
    that happens, and by the time anyone is clicking, teardown has already put
    the supplies back down.
    """
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit(
            "Teaching coordinates needs PySide6.\n"
            "  pip install PySide6"
        ) from exc

    import sys

    from .. import drivers  # noqa: F401 - registers verbs
    from .. import teach as teachlib
    from ..engine.events import LogEvent

    class Printer:
        def emit(self, event) -> None:
            if isinstance(event, LogEvent) and not quiet:
                prefix = {"error": "!!", "warn": " *"}.get(event.level, "  ")
                print(f"{prefix} {event.message}")

    sites, notes = teachlib.sites_from_program(target or capture)
    result = teachlib.run_capture(capture, simulate=simulate,
                                  listener=Printer(), station=station,
                                  operator=operator, row_index=row_index)

    if not result.ok:
        print("  no contours were produced -- there is nothing to click.")
        print(f"  Row {result.cells.row} thresholds at "
              f"{result.cells.threshold} and stores contours in "
              f"'{result.cells.contours}'. Check that the capture reached the "
              f"camera and that the threshold suits the exposure.")
        return 1
    if result.frame is None:
        # Worth saying rather than showing an empty canvas: the contours exist,
        # so the run worked -- it is only the picture that could not be found.
        print(f"  contours were produced, but the frame at "
              f"'{result.cells.frame.cell}' could not be read. Clicking still "
              f"works; there is just nothing underneath it.")

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("NGWART")

    from .teach_window import TeachWindow

    window = TeachWindow(
        sites=sites, capture=result, notes=notes, out_path=out_path, dark=dark,
        program=(target or capture),
        meta={
            "capture_program": capture.source,
            "target_program": (target or capture).source,
            "simulated": simulate,
            "station": station,
            "operator": operator,
            "contour_row": result.cells.row,
            "threshold": result.cells.threshold,
            "cells": result.cells.as_dict(),
        })
    window.set_capture(frame=result.frame, binary=result.binary,
                       contours=result.contours)
    # A capture program may take several frames -- cargo_calibrate takes one per
    # board pair, because the camera only ever sees two lit at a time. All of
    # them are still in the context, so switching is a re-read, not a re-run.
    window.offer_captures(result.context)
    window.show()
    return app.exec()
