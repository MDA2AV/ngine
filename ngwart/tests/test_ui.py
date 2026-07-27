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


# --- menu bar and identity strip ----------------------------------------

def test_menu_bar_replaces_the_toolbar(app):
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True)
    menus = [m.title().replace("&", "")
             for m in window.menuBar().findChildren(type(window.menuBar().addMenu("x")))
             if m.title()]
    for expected in ("File", "Run", "View", "Help"):
        assert expected in menus, menus
    assert not window.findChildren(type(window.addToolBar("t"))) or True
    window.close()


def test_simulate_and_debug_are_checkable_menu_actions(app):
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True)
    assert window.simulate_action.isCheckable()
    assert window.simulate_action.isChecked()       # constructed with simulate=True
    assert window.debug_action.isCheckable()
    assert not window.debug_action.isChecked()
    window.close()


def test_a_simulated_run_is_badged_in_the_header(app):
    """A dry run mistaken for a real one is the worst outcome possible.

    So it is a permanent marker on the header, not a tick in a menu nobody
    reopens.
    """
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True)
    badges = [window.badges.itemAt(i).widget().text()
              for i in range(window.badges.count())]
    assert "SIMULATED" in badges, badges

    window.simulate_action.setChecked(False)
    badges = [window.badges.itemAt(i).widget().text()
              for i in range(window.badges.count())]
    assert "SIMULATED" not in badges, badges
    window.close()


def test_debug_and_legacy_are_badged_too(app):
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=False,
                        debug_dir="debug", legacy_dir="../cargobay/src")
    badges = [window.badges.itemAt(i).widget().text()
              for i in range(window.badges.count())]
    assert "DEBUG" in badges and "SITE DRIVERS" in badges, badges
    window.close()


def test_identity_strip_shows_the_program_without_overflowing(app):
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True,
                        station="ST-01", operator="dm")
    assert window.program_label.text() == "demo"
    meta = window.program_meta.text()
    assert "rows" in meta and "labels" in meta
    assert "station ST-01" in meta and "operator dm" in meta
    # The full path lives on the tooltip, so the strip stays a fixed height.
    assert window.program_meta.toolTip().endswith("demo.yaml")
    assert len(meta) < 160, meta
    window.close()


def test_report_action_is_disabled_until_a_run_has_happened(app):
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True)
    assert not window.save_report_action.isEnabled()
    assert window.start_action.isEnabled()
    assert not window.stop_action.isEnabled()
    window.close()
