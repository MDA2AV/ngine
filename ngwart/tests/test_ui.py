"""UI smoke tests.

Qt is exercised offscreen so these run in CI. They check wiring, not looks:
that the bridge relays engine events onto the GUI thread, and that the window
refuses to arm Play for an invalid program.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

import ngwart.drivers  # noqa: F401,E402
from ngwart.engine.events import (GridEvent, LogEvent, ResultEvent,  # noqa: E402
                                  StatusEvent)
from ngwart.engine.loaders import load  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.join(HERE, "..", "programs", "demo.yaml")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_bridge_relays_every_event_type(app):
    from ngwart.ui.bridge import QtBridge

    bridge = QtBridge()
    seen = []
    bridge.logged.connect(lambda *a: seen.append(("log", a)))
    bridge.status_changed.connect(lambda *a: seen.append(("status", a)))
    bridge.grid_changed.connect(lambda *a: seen.append(("grid", a)))
    bridge.finished.connect(lambda *a: seen.append(("done", a)))

    bridge.emit(LogEvent("hello", "info", 3))
    bridge.emit(StatusEvent("RUNNING", "#123456"))
    bridge.emit(GridEvent(grid=1, op="add", values=["a"], tag="PASS"))
    bridge.emit(ResultEvent(passed=True, per_uut={0: True}))

    assert [kind for kind, _ in seen] == ["log", "status", "grid", "done"]


def test_unknown_events_are_ignored(app):
    from ngwart.ui.bridge import QtBridge

    QtBridge().emit(object())          # must not raise


def test_window_loads_a_valid_program_and_arms_run(app):
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True)
    assert window.run_button.isEnabled()
    assert window.program_table.rowCount() == len(load(DEMO).rows)
    window.close()


def test_window_refuses_to_arm_run_for_an_invalid_program(app, tmp_path):
    import yaml

    from ngwart.ui.main_window import MainWindow

    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({
        "modules": {"Flow": "FlowManager"},
        "exec": [["Flow", "NOSUCHVERB", "x"]],
    }))
    window = MainWindow(program_path=str(bad))
    assert not window.run_button.isEnabled()
    assert window.diagnostics.rowCount() >= 1
    window.close()


def test_grid_colours_stay_legible_on_any_background(app):
    """Tag_Config can set an arbitrary colour; text must remain readable."""
    from ngwart.ui.widgets import _readable_on

    assert _readable_on("#FFFFFF") == "#0B0E11"
    assert _readable_on("#000000") == "#FFFFFF"
    assert _readable_on("#35B26B") == "#FFFFFF"


def test_theme_covers_both_modes():
    from ngwart.ui import theme

    for dark in (True, False):
        css = theme.stylesheet(dark)
        assert "QTableWidget" in css and "QPushButton#Run" in css
        assert len(theme.palette(dark)) >= 10
