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
