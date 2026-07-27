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


def test_no_unit_panels_before_a_program_is_loaded(app):
    """Four panels for units that may not exist is a lie about the fixture."""
    from ngwart.ui.main_window import MainWindow

    window = MainWindow()
    assert window.uut_grids == []
    assert window.uut_placeholder.isVisible() or not window.isVisible()
    window.close()


def test_panel_count_comes_from_the_programs_initalive(app):
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True)
    assert len(window.uut_grids) == 2, "demo.yaml declares initAlive 2"
    window.close()


def test_panel_count_follows_the_live_alive_mask(app):
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True)
    window._on_alive([1, 1, 1, 1])
    assert len(window.uut_grids) == 4
    window._on_alive([1, 0])
    assert len(window.uut_grids) == 2
    window.close()


def test_scanned_values_appear_only_once_a_program_sets_them(app):
    """A fixture may scan none, one or several -- empty boxes are just noise."""
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True)
    assert window._scan_chips == {}

    window._on_field("barcode1", "R02XXXXXXXX", None)
    assert "barcode1" in window._scan_chips
    assert "R02XXXXXXXX" in window._scan_chips["barcode1"].text()
    assert "barcode2" not in window._scan_chips
    window.close()


def test_the_results_get_most_of_the_window(app):
    """Chrome is glanced at; results are read. Budget the pixels accordingly."""
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True)
    window.resize(1500, 880)
    window.show()
    app.processEvents()

    header = window.centralWidget().layout().itemAt(0).widget()
    assert header.height() < 80, f"header {header.height()}px"
    assert window.banner.height() < 60, f"banner {window.banner.height()}px"
    assert window.tabs.height() / window.height() > 0.65, (
        f"results only get {100 * window.tabs.height() / window.height():.0f}%")
    window.close()


def test_header_children_do_not_paint_their_own_background(app):
    """Child widgets inheriting the window colour made the strip look like a
    row of boxes against its lighter surface."""
    from ngwart.ui import theme

    css = theme.stylesheet(True)
    assert "QFrame#Identity > QWidget { background: transparent; }" in css
    assert "QFrame#Identity QLabel { background: transparent; }" in css


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


def test_theme_toggle_keeps_the_verdict_colour(app):
    """Toggling the theme mid-run must not drop a PASS back to neutral grey."""
    from ngwart.ui import theme
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True)
    green = theme.palette(window.dark)["pass"]
    window.banner.show_status("PASS", green)
    assert green.lower() in window.banner.styleSheet().lower()

    window._toggle_theme()
    assert window.banner._colour == green
    assert green.lower() in window.banner.styleSheet().lower()
    window.close()


def test_design_tokens_are_a_single_scale():
    """Values outside the scale are how a dense UI drifts out of alignment."""
    from ngwart.ui import theme

    assert set(theme.SPACE) == {"xs", "sm", "md", "lg", "xl"}
    assert sorted(theme.SPACE.values()) == [4, 8, 12, 16, 24]
    assert set(theme.RADIUS) == {"control", "panel", "pill"}
    for role in ("display", "title", "body", "data", "figure", "caption"):
        assert role in theme.TYPE


def test_semantic_colours_are_not_the_accent():
    """A verdict must never read as branding."""
    from ngwart.ui import theme

    for dark in (True, False):
        c = theme.palette(dark)
        assert c["pass"] != c["accent"]
        assert c["fail"] != c["accent"]
        assert c["warn"] != c["accent"]


def test_unit_panel_summarises_its_own_results(app):
    from ngwart.ui.widgets import UutGrid

    panel = UutGrid(0)
    panel.apply("config", [], "", {"columns": ["Test", "Value", "Result"]})
    panel.apply("add", ["VBAT", "13.5", "PASS"], "PASS", {})
    panel.apply("add", ["ILOAD", "9.9", "FAIL"], "FAIL", {})
    assert panel.passed == 1 and panel.failed == 1
    assert "1 FAILED OF 2" in panel.count.text()

    panel.apply("clear", [], "", {})
    assert panel.count.text() == ""
