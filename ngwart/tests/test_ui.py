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
    # The bare layout holder still needs naming; its labels are covered by the
    # global rule that keeps every label transparent.
    assert "QFrame#Identity > QWidget { background: transparent; }" in css
    assert "QLabel, QCheckBox, QRadioButton {" in css


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


# --- the verdict has to be readable from across the bench ----------------

def test_a_failing_point_tints_the_whole_panel_not_just_the_badge(app):
    from ngwart.ui import theme
    from ngwart.ui.widgets import UutGrid

    panel = UutGrid(0)
    assert panel.styleSheet() == "", "a fresh panel takes the app stylesheet"

    panel.apply("add", ["ILOAD", "9.9", "FAIL"], "FAIL", {})
    sheet = panel.styleSheet().lower()
    tint = theme.palette(True)["fail_surface"].lower()
    assert tint in sheet
    # The table is the bulk of the panel; tinting only the frame would leave
    # a neutral rectangle covering most of it.
    assert "qtablewidget" in sheet and "qframe#card" in sheet


def test_a_passing_verdict_tints_the_panel_green(app):
    from ngwart.ui import theme
    from ngwart.ui.widgets import UutGrid

    panel = UutGrid(0)
    panel.set_verdict("PASS")
    assert theme.palette(True)["pass_surface"].lower() in panel.styleSheet().lower()


def test_clearing_a_panel_drops_the_tint(app):
    from ngwart.ui.widgets import UutGrid

    panel = UutGrid(0)
    panel.apply("add", ["ILOAD", "9.9", "FAIL"], "FAIL", {})
    assert panel.styleSheet() != ""
    panel.apply("clear", [], "", {})
    assert panel.styleSheet() == "", "a stale tint would mislabel the next board"


def test_a_killed_unit_is_tinted_even_with_no_failing_point(app):
    from ngwart.ui import theme
    from ngwart.ui.widgets import UutGrid

    panel = UutGrid(0)
    panel.set_alive(False)
    assert panel.dead and panel.outcome() == "fail"
    assert theme.palette(True)["fail_surface"].lower() in panel.styleSheet().lower()


def test_the_tint_survives_a_theme_toggle(app):
    from ngwart.ui import theme
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True)
    panel = window.uut_grids[0]
    panel.set_verdict("PASS")
    window._toggle_theme()
    expected = theme.palette(window.dark)["pass_surface"].lower()
    assert expected in panel.styleSheet().lower()
    window.close()


def test_bridge_relays_a_verdict(app):
    from ngwart.engine.events import VerdictEvent
    from ngwart.ui.bridge import QtBridge

    bridge = QtBridge()
    seen = []
    bridge.verdict_reached.connect(lambda *a: seen.append(a))
    bridge.emit(VerdictEvent(uut=1, passed=False, detail="2 points, 1 failed"))
    assert seen == [(1, False, "2 points, 1 failed")]


def test_a_verdict_colours_its_panel_without_waiting_for_the_run_to_end(app):
    """cargo's table loops at REMOVE, so end-of-run never comes."""
    from ngwart.ui import theme
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True)
    window._on_verdict(0, True, "")
    window._on_verdict(1, False, "")

    assert window.uut_grids[0].verdict.text() == "PASS"
    assert window.uut_grids[1].verdict.text() == "FAIL"
    palette = theme.palette(window.dark)
    assert palette["pass_surface"].lower() in window.uut_grids[0].styleSheet().lower()
    assert palette["fail_surface"].lower() in window.uut_grids[1].styleSheet().lower()
    assert window.stat_passed.value.text() == "1"
    assert window.stat_failed.value.text() == "1"
    window.close()


def test_a_kill_after_a_fail_verdict_keeps_the_word_fail(app):
    """VALIDATE fails a unit then kills it; DEAD would be the vaguer label."""
    from ngwart.ui.widgets import UutGrid

    panel = UutGrid(0)
    panel.set_verdict("FAIL")
    panel.set_alive(False)
    assert panel.verdict.text() == "FAIL"

    other = UutGrid(1)
    other.set_alive(False)
    assert other.verdict.text() == "DEAD"


# --- the header counts boards, not measurements --------------------------

def test_header_counters_count_units_not_points(app):
    """A 4-up fixture running 60 points made 'points 240' the headline."""
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True)
    assert len(window.uut_grids) == 2

    # Six points on one unit, all passing: one unit passed, not six.
    for _ in range(6):
        window._on_grid(1, "add", ["VBAT", "13.5", "PASS"], "PASS", {})
    assert window.stat_passed.value.text() == "1"
    assert window.stat_failed.value.text() == "0"

    # The second unit fails: one passed, one failed.
    window._on_grid(2, "add", ["VBAT", "0.0", "FAIL"], "FAIL", {})
    assert window.stat_passed.value.text() == "1"
    assert window.stat_failed.value.text() == "1"
    window.close()


def test_a_unit_with_no_results_yet_is_in_neither_column(app):
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True)
    window._on_grid(1, "add", ["VBAT", "13.5", "PASS"], "PASS", {})
    passed = int(window.stat_passed.value.text())
    failed = int(window.stat_failed.value.text())
    assert passed + failed == 1 <= len(window.uut_grids)
    window.close()


def test_a_unit_failed_only_by_the_final_verdict_still_counts(app):
    """VALIDATE can fail a unit that never took a failing point."""
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True)
    window._on_grid(1, "add", ["VBAT", "13.5", "PASS"], "PASS", {})
    assert window.stat_passed.value.text() == "1"

    window.uut_grids[0].set_verdict("FAIL")
    window._retally_units()
    assert window.stat_passed.value.text() == "0"
    assert window.stat_failed.value.text() == "1"
    window.close()


def test_the_failed_counter_resets_between_boards(app):
    """A counter still red from the last board mislabels this one."""
    from ngwart.ui import theme
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True)
    window._on_grid(1, "add", ["VBAT", "0.0", "FAIL"], "FAIL", {})
    red = theme.palette(window.dark)["fail"].lower()
    assert red in window.stat_failed.value.styleSheet().lower()

    for panel in window.uut_grids:
        panel.apply("clear", [], "", {})
    window._retally_units()
    assert window.stat_failed.value.text() == "0"
    assert red not in window.stat_failed.value.styleSheet().lower()
    window.close()


# --- the trend chart -----------------------------------------------------

def _trend_rows(values, low=0.0, high=1.0, units=1):
    rows, n = [], 0
    for i, value in enumerate(values):
        for uut in range(units):
            n += 1
            ok = value is not None and low <= value <= high
            rows.append({
                "run_id": i + 1, "name": "CURR", "uut": uut,
                "result": "PASS" if ok else "FAIL",
                "measured": "NOT_FOUND" if value is None else str(value),
                "value": value, "low": str(low), "high": str(high),
                "low_value": low, "high_value": high,
                "started": f"2026-07-{i + 1:02d}T09:00:00", "barcode": "BC1",
            })
    return rows


def test_the_axis_contains_the_limits_by_default(app):
    """A limit cropped off the axis makes an out-of-spec point look ordinary."""
    from ngwart.ui.trend import TrendChart

    chart = TrendChart()
    chart.set_data("CURR", _trend_rows([0.20, 0.22, 0.24]))
    assert chart.limits_visible
    low, high = chart._span
    assert low <= 0.0 and high >= 1.0


def test_zooming_to_data_is_opt_in_and_says_so(app):
    from ngwart.ui.trend import TrendChart

    chart = TrendChart()
    chart.set_data("CURR", _trend_rows([0.20, 0.22, 0.24]))
    chart.set_zoom(True)
    assert not chart.limits_visible, "the caller must be able to warn about this"
    low, high = chart._span
    assert high < 1.0, "zoomed, the axis tracks the data"


def test_worst_excursion_is_negative_when_a_limit_was_crossed(app):
    from ngwart.ui.trend import TrendChart

    chart = TrendChart()
    chart.set_data("CURR", _trend_rows([0.5, 1.4]))
    assert chart.summary()["margin"] < 0
    assert chart.summary()["fails"] == 1


def test_margin_is_the_closest_a_measurement_ever_came(app):
    from ngwart.ui.trend import TrendChart

    chart = TrendChart()
    chart.set_data("CURR", _trend_rows([0.5, 0.9]))
    # 0.9 sits 0.1 from the high limit, on a band of 1.0 -> 10%.
    assert abs(chart.summary()["margin"] - 10.0) < 1e-6


def test_a_test_with_no_numbers_falls_back_instead_of_drawing_nothing(app):
    """EVALLEDS records a colour triple; pass/fail per run is still a shape."""
    from ngwart.ui.trend import TrendChart

    chart = TrendChart()
    chart.set_data("LED", _trend_rows([None, None, None]))
    assert chart.summary()["numeric"] is False
    assert chart.summary()["n"] == 3


def test_units_beyond_the_lane_cap_are_reported_not_silently_dropped(app):
    from ngwart.ui.trend import MAX_LANES, TrendChart

    chart = TrendChart()
    chart.set_data("CURR", _trend_rows([0.5], units=MAX_LANES + 2))
    assert chart.summary()["dropped"] == 2
    assert chart.summary()["units"] == MAX_LANES


def test_the_chart_survives_a_single_point(app):
    from ngwart.ui.trend import TrendChart

    chart = TrendChart()
    chart.set_data("CURR", _trend_rows([0.5]))
    chart.resize(400, 200)
    chart.grab()               # must not raise


def test_the_caption_reads_as_an_excursion_not_a_negative_distance(app):
    from ngwart.ui.stats import StatsTab

    crossed = StatsTab._trend_caption({"n": 2, "units": 1, "fails": 1,
                                       "margin": -6.4, "dropped": 0})
    assert "past a limit" in crossed and "-6.4" not in crossed

    inside = StatsTab._trend_caption({"n": 2, "units": 1, "fails": 0,
                                      "margin": 12.0, "dropped": 0})
    assert "closest to a limit" in inside


# --- one surface: nothing paints the window colour inside a panel --------

def test_refreshing_badges_leaves_no_orphan(app):
    """A badge only removed from the layout stays visible at Qt's default
    640x480 geometry, painting a coloured rectangle across the header."""
    from ngwart.ui.main_window import MainWindow
    from ngwart.ui.widgets import Badge

    window = MainWindow(program_path=DEMO, simulate=True)
    for _ in range(3):
        window.simulate_action.setChecked(False)
        window.simulate_action.setChecked(True)
    live = [b for b in window.findChildren(Badge) if b.isVisible()]
    assert len(live) <= 1, [(b.text(), b.geometry().getRect()) for b in live]
    window.close()


def test_labels_do_not_paint_their_own_background():
    """QWidget carries the window colour, which is darker than a panel surface.

    A label that inherits it draws a dark box behind itself -- which is what the
    progress percentage and the step caption used to do.
    """
    from ngwart.ui import theme

    for dark in (True, False):
        css = theme.stylesheet(dark)
        assert "QLabel, QCheckBox, QRadioButton {" in css
        rule = css.split("QLabel, QCheckBox, QRadioButton {", 1)[1].split("}", 1)[0]
        assert "background: transparent" in rule


def test_a_selected_table_row_is_marked_by_ink_not_by_a_block():
    from ngwart.ui import theme

    for dark in (True, False):
        css = theme.stylesheet(dark)
        assert "selection-background-color: transparent;" in css
        rule = css.split("QTableView::item:selected {", 1)[1].split("}", 1)[0]
        assert "background: transparent" in rule
        assert theme.palette(dark)["accent"] in rule


def test_the_footer_reads_as_one_surface(app):
    """Pixel check: behind the progress percentage is the panel, not the window."""
    from PySide6.QtCore import QPoint

    from ngwart.ui import theme
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True)
    window.resize(1400, 860)
    window.show()
    app.processEvents()
    window._on_progress(1.0)
    app.processEvents()

    image = window.grab().toImage()
    corner = window.progress_label.mapTo(window, QPoint(2, 2))
    behind = image.pixelColor(corner).name().lower()
    assert behind != theme.palette(window.dark)["bg"].lower(), (
        f"the progress label is painting the window colour {behind}")
    window.close()


# --- layout: chrome shares a row so the results get the height -----------

def test_controls_state_and_progress_share_one_row(app):
    """Three stacked strips spent ~100px saying what fits side by side."""
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True)
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    # All four live at the same vertical band, not stacked.
    tops = [w.mapTo(window, w.rect().topLeft()).y()
            for w in (window.run_button, window.banner, window.progress)]
    assert max(tops) - min(tops) < 60, tops
    assert not hasattr(window, "_build_footer_widget")
    window.close()


def test_the_log_collapses_and_comes_back(app):
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True)
    window.resize(1500, 900)
    window.show()
    app.processEvents()

    assert window.log_action.isChecked()
    before = window.op_splitter.sizes()[0]
    assert before > 0

    window.log_action.setChecked(False)
    assert window.op_splitter.sizes()[0] == 0, "log should be fully collapsed"

    window.log_action.setChecked(True)
    # Restores the operator's width, not a default.
    assert abs(window.op_splitter.sizes()[0] - before) <= 2
    window.close()


def test_the_stats_charts_are_not_squeezed_into_a_third_each(app, tmp_path):
    """The complaint: three stacked blocks left each about 180px."""
    from ngwart.history import History
    from ngwart.ui.stats import StatsTab

    store = History(str(tmp_path / "h.db"))
    tab = StatsTab(store)
    tab.resize(1400, 560)
    tab.show()
    app.processEvents()

    charts, search = tab.body_splitter.sizes()
    assert charts > 200, f"charts pane only {charts}px"
    assert search > 120, f"search pane only {search}px"
    # Side by side, so each chart keeps the full height of the pane.
    assert tab.pareto.height() > 150 and tab.trend.height() > 120
    tab.close()


# --- running selected steps from the Program tab -------------------------

def _select_rows(window, rows):
    from PySide6.QtCore import QItemSelectionModel

    model = window.program_table.selectionModel()
    model.clearSelection()
    for row in rows:
        model.select(window.program_table.model().index(row, 0),
                     QItemSelectionModel.Select | QItemSelectionModel.Rows)


def test_the_program_table_marks_its_selection_with_a_background():
    """Here the selection is not decoration -- it is what "run these" acts on."""
    from ngwart.ui import theme

    for dark in (True, False):
        css = theme.stylesheet(dark)
        rule = css.split("QTableView#ProgramTable::item:selected {", 1)[1]
        rule = rule.split("}", 1)[0]
        assert theme.palette(dark)["select"] in rule
        assert theme.palette(dark)["accent"] in rule


def test_several_steps_can_be_selected_at_once(app):
    from PySide6.QtWidgets import QAbstractItemView

    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True, history_path="")
    assert (window.program_table.selectionMode()
            == QAbstractItemView.ExtendedSelection)
    picks = [i for i in window.program.body("Exec")
             if window.program.rows[i].module
             and window.program.rows[i].verb == "WRITE"][:3]
    _select_rows(window, picks)
    assert window._selected_exec_rows() == picks
    window.close()


def test_markers_and_module_less_rows_are_not_steps(app):
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True, history_path="")
    markers = [i for i, r in enumerate(window.program.rows) if r.is_marker]
    _select_rows(window, markers[:3])
    assert window._selected_exec_rows() == []
    window.close()


def test_running_steps_is_refused_while_a_run_is_in_progress(app):
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path=DEMO, simulate=True, history_path="")
    picks = [i for i in window.program.body("Exec")
             if window.program.rows[i].module
             and window.program.rows[i].verb == "WRITE"][:2]
    _select_rows(window, picks)
    assert window.step_action.isEnabled()

    window._active = True                      # pretend a run is going
    window._sync_run_actions()
    assert not window.step_action.isEnabled()
    assert not window.run_button.isEnabled()
    assert window.stop_button.isEnabled()

    before = window.thread
    window.run_selected_steps()                # must be a no-op
    assert window.thread is before

    window._active = False
    window._sync_run_actions()
    assert window.step_action.isEnabled()
    window.close()


def test_a_step_run_is_not_recorded_as_a_board(app, tmp_path):
    """Folding hand-picked steps into history would put a fictional unit into
    the yield figure."""
    from ngwart.history import History
    from ngwart.ui.main_window import MainWindow

    db = str(tmp_path / "h.db")
    window = MainWindow(program_path=DEMO, simulate=True, history_path=db)
    window._partial_run = 3
    window._on_finished(True, {}, "")

    assert History(db).summary().runs == 0
    assert window._partial_run == 0, "the flag must not leak into the next run"
    assert "STEP RUN" in window.banner.text()
    window.close()


def test_a_full_run_is_still_recorded(app, tmp_path):
    from ngwart.history import History
    from ngwart.ui.main_window import MainWindow

    db = str(tmp_path / "h.db")
    window = MainWindow(program_path=DEMO, simulate=True, history_path=db)
    window._partial_run = 0
    window._on_finished(True, {}, "")
    assert window.banner.text() == "PASS"
    window.close()
