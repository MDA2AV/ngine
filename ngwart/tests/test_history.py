"""Run history and the statistics derived from it."""

from __future__ import annotations

import os

import pytest

from ngwart.engine.runrecord import RunRecord, TestPoint
from ngwart.history import History


def make_record(points, simulate=False, program="cargo", barcodes=None):
    """points: {uut: [(name, result), ...]}"""
    record = RunRecord(program_name=program, station="ST1", simulate=simulate)
    for uut, entries in points.items():
        record.set_barcode(uut, (barcodes or {}).get(uut, f"R02-{uut}"))
        for name, result in entries:
            record.add_point(TestPoint(name, uut, result, measured="1.0",
                                       low="0.0", high="2.0"))
    record.finish([1] * max(len(points), 1))
    return record


@pytest.fixture
def history(tmp_path):
    store = History(str(tmp_path / "h.db"))
    yield store
    store.close()


def test_a_run_round_trips(history):
    run_id = history.add_run(make_record({0: [("VBAT", "PASS")]}))
    assert run_id is not None
    assert history.summary().points == 1


def test_yield_counts_units_not_points(history):
    """First-pass yield is units passed over units tested.

    Counting points instead flatters the figure: a board failing one test of
    twenty would read as 95% good rather than as a reject.
    """
    history.add_run(make_record({
        0: [("A", "PASS"), ("B", "PASS")],
        1: [("A", "PASS"), ("B", "FAIL")]}))
    summary = history.summary()
    assert summary.units == 2
    assert summary.units_passed == 1
    assert summary.yield_pct == 50.0
    assert summary.point_pass_pct == 75.0


def test_simulated_runs_are_excluded_by_default(history):
    history.add_run(make_record({0: [("A", "PASS")]}))
    history.add_run(make_record({0: [("A", "FAIL")]}, simulate=True))

    assert history.summary().runs == 1
    assert history.summary().failed == 0
    assert history.summary(include_simulated=True).runs == 2
    assert history.summary(include_simulated=True).failed == 1


def test_pareto_ranks_failures_and_keeps_attempts(history):
    """A bare count cannot tell 5-of-5 from 5-of-500 apart."""
    for _ in range(10):
        history.add_run(make_record({0: [("RARE", "PASS"), ("OFTEN", "FAIL")]}))
    history.add_run(make_record({0: [("RARE", "FAIL"), ("OFTEN", "FAIL")]}))

    pareto = history.pareto()
    assert pareto[0][0] == "OFTEN"
    assert pareto[0][1] == 11              # failures
    assert pareto[0][2] == 11              # attempts
    assert ("RARE", 1, 11) in pareto


def test_pareto_omits_tests_that_never_failed(history):
    history.add_run(make_record({0: [("GOOD", "PASS"), ("BAD", "FAIL")]}))
    assert [n for n, _f, _a in history.pareto()] == ["BAD"]


def test_session_scope_is_a_subset(history):
    first = history.add_run(make_record({0: [("A", "FAIL")]}))
    history.add_run(make_record({0: [("A", "FAIL"), ("B", "FAIL")]}))

    assert history.summary().failed == 3
    assert history.summary(run_ids=[first]).failed == 1
    assert history.summary(run_ids=[]).failed == 0     # a session with no runs


def test_search_by_test_id(history):
    history.add_run(make_record({0: [("INTENSITY_A", "FAIL"),
                                     ("INTENSITY_B", "PASS"),
                                     ("VBAT", "PASS")]}))
    assert len(history.search(text="INTENSITY")) == 2
    assert len(history.search(text="INTENSITY", result="FAIL")) == 1
    assert history.search(text="INTENSITY", result="FAIL")[0]["name"] == "INTENSITY_A"


def test_search_by_barcode(history):
    history.add_run(make_record({0: [("A", "FAIL")]},
                                barcodes={0: "R02ABCDEF"}))
    rows = history.search(text="ABCDEF")
    assert rows and rows[0]["barcode"] == "R02ABCDEF"


def test_search_filters_by_result_and_program(history):
    history.add_run(make_record({0: [("A", "PASS"), ("B", "FAIL")]},
                                program="cargo"))
    history.add_run(make_record({0: [("A", "FAIL")]}, program="1211"))

    assert len(history.search(result="FAIL")) == 2
    assert len(history.search(result="FAIL", program="1211")) == 1
    assert len(history.search(program="cargo")) == 2


def test_a_broken_store_never_raises(tmp_path):
    """A locked or unwritable history must not fail a test run."""
    store = History(str(tmp_path))            # a directory, not a file
    assert not store.available
    assert store.add_run(make_record({0: [("A", "PASS")]})) is None
    assert store.summary().runs == 0
    assert store.pareto() == []
    assert store.search() == []


def test_programs_are_listed_for_the_filter(history):
    history.add_run(make_record({0: [("A", "PASS")]}, program="cargo"))
    history.add_run(make_record({0: [("A", "PASS")]}, program="1211"))
    assert history.programs() == ["1211", "cargo"]


# --- the stats tab ------------------------------------------------------

def test_vital_few_stops_at_the_cutoff():
    """The point of a Pareto: the few tests behind most of the failures."""
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from ngwart.ui.stats import CUTOFF, StatsTab

    # 60 + 25 = 85% of 100 failures, so two tests clear the 80% line.
    pareto = [("A", 60, 60), ("B", 25, 25), ("C", 10, 10), ("D", 5, 5)]
    assert StatsTab._vital_few(pareto) == ["A", "B"]
    assert CUTOFF == 80.0


def test_stats_tab_renders_without_a_history(qt_app=None):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from ngwart.ui.stats import StatsTab

    app = QApplication.instance() or QApplication([])
    tab = StatsTab(None)
    assert "unavailable" in tab.pareto_note.text().lower()
    tab.deleteLater()


def test_stats_tab_summarises_a_history(tmp_path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from ngwart.ui.stats import StatsTab

    store = History(str(tmp_path / "h.db"))
    store.add_run(make_record({0: [("A", "PASS"), ("B", "FAIL")],
                               1: [("A", "PASS"), ("B", "PASS")]}))

    app = QApplication.instance() or QApplication([])
    tab = StatsTab(store)
    tab.scope_all.setChecked(True)

    assert tab.tiles["units"].value.text() == "2"
    assert tab.tiles["failed"].value.text() == "1"
    assert tab.tiles["yield"].value.text() == "50.0%"
    assert tab.table.rowCount() == 4                 # every point is searchable

    # Clicking a Pareto bar drills into that test.
    tab._search_for_test("B")
    assert tab.query.text() == "B"
    assert tab.table.rowCount() == 1
    tab.deleteLater()
    store.close()


# --- trend: how a measurement varies between runs ------------------------

def _measured_record(values, name="CURR", low="0.0", high="1.0", program="cargo"):
    """One run, one point per unit, with explicit measurements."""
    record = RunRecord(program_name=program, station="ST1", simulate=False)
    for uut, value in enumerate(values):
        record.set_barcode(uut, f"BC-{uut}")
        result = "PASS" if float(low) <= float(value) <= float(high) else "FAIL"
        record.add_point(TestPoint(name, uut, result, measured=str(value),
                                   low=low, high=high))
    record.finish([1] * len(values))
    return record


def test_trend_returns_points_oldest_first(history):
    for value in (0.10, 0.20, 0.30):
        history.add_run(_measured_record([value]))
    values = [r["value"] for r in history.trend("CURR")]
    assert values == [0.10, 0.20, 0.30], "a chart of this reads left to right"


def test_trend_keeps_the_newest_rows_when_it_has_to_truncate(history):
    """Sorting ascending with a LIMIT would chart the oldest points as current."""
    for value in (0.1, 0.2, 0.3, 0.4, 0.5):
        history.add_run(_measured_record([value]))
    values = [r["value"] for r in history.trend("CURR", limit=2)]
    assert values == [0.4, 0.5]


def test_trend_reports_non_numeric_measurements_as_none(history):
    """EVALCONT stores NOT_FOUND and EVALLEDS stores a colour triple."""
    record = RunRecord(program_name="cargo", station="ST1")
    record.add_point(TestPoint("LED", 0, "FAIL", measured="NOT_FOUND",
                               low="50", high=""))
    record.add_point(TestPoint("LED", 1, "PASS", measured="238,241,239",
                               low="50", high=""))
    record.finish([1, 1])
    history.add_run(record)

    values = [r["value"] for r in history.trend("LED")]
    assert values == [None, None]
    assert [r["measured"] for r in history.trend("LED")] == ["NOT_FOUND",
                                                             "238,241,239"]


def test_trend_carries_the_limits_it_was_judged_against(history):
    history.add_run(_measured_record([0.5], low="0.0", high="1.0"))
    row = history.trend("CURR")[0]
    assert (row["low_value"], row["high_value"]) == (0.0, 1.0)


def test_trend_separates_units(history):
    history.add_run(_measured_record([0.1, 0.9]))
    units = sorted({r["uut"] for r in history.trend("CURR")})
    assert units == [0, 1]


def test_test_names_are_ordered_by_how_often_they_appear(history):
    record = RunRecord(program_name="cargo", station="ST1")
    for _ in range(3):
        record.add_point(TestPoint("COMMON", 0, "PASS", measured="1"))
    record.add_point(TestPoint("RARE", 0, "PASS", measured="1"))
    record.finish([1])
    history.add_run(record)
    assert history.test_names()[0] == "COMMON"


def test_simulated_runs_stay_out_of_the_trend(history):
    history.add_run(_measured_record([0.5]))
    sim = _measured_record([0.9])
    sim.simulate = True
    history.add_run(sim)
    assert [r["value"] for r in history.trend("CURR")] == [0.5]
    assert len(history.trend("CURR", include_simulated=True)) == 2


# --- the filter is scoped to the programs the station offers -------------

def test_program_names_lists_stems_and_ignores_lock_files(tmp_path):
    from ngwart.engine.loaders import program_names

    for name in ("cargo.ods", "cargo.yaml", "demo.yaml", "notes.md",
                 "~$cargo.ods", ".~lock.cargo.ods#"):
        (tmp_path / name).write_text("x")
    # cargo.ods and cargo.yaml are one fixture in two formats, so one entry.
    assert program_names(str(tmp_path)) == ["cargo", "demo"]


def test_program_names_survives_a_missing_directory():
    from ngwart.engine.loaders import program_names

    assert program_names("") == []
    assert program_names("/no/such/place") == []


def test_the_program_filter_scopes_every_panel(tmp_path):
    """It used to narrow the result table while the tiles and the Pareto went
    on aggregating every product in the file, and said nothing about it."""
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from ngwart.ui.stats import StatsTab

    store = History(str(tmp_path / "h.db"))
    store.add_run(make_record({0: [("A", "PASS"), ("B", "PASS")]}, program="cargo"))
    store.add_run(make_record({0: [("A", "FAIL"), ("B", "FAIL")]}, program="demo"))

    programs = tmp_path / "programs"
    programs.mkdir()
    (programs / "cargo.yaml").write_text("x")
    (programs / "demo.yaml").write_text("x")

    app = QApplication.instance() or QApplication([])
    tab = StatsTab(store, programs_dir=str(programs))
    tab.scope_all.setChecked(True)

    assert [tab.program_filter.itemText(i)
            for i in range(tab.program_filter.count())] == [
        "All programs", "cargo", "demo"]

    tab.program_filter.setCurrentIndex(tab.program_filter.findData("cargo"))
    assert tab.tiles["yield"].value.text() == "100.0%"
    assert tab.tiles["failed"].value.text() == "0"
    assert store.pareto(None, program="cargo") == []

    tab.program_filter.setCurrentIndex(tab.program_filter.findData("demo"))
    assert tab.tiles["yield"].value.text() == "0.0%"
    assert tab.tiles["failed"].value.text() == "2"
    assert [n for n, *_ in store.pareto(None, program="demo")] == ["A", "B"]


def test_the_filter_ignores_products_the_station_no_longer_runs(tmp_path):
    """A retired table lingers in history forever; the folder is the truth."""
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from ngwart.ui.stats import StatsTab

    store = History(str(tmp_path / "h.db"))
    store.add_run(make_record({0: [("A", "PASS")]}, program="retired1211"))
    programs = tmp_path / "programs"
    programs.mkdir()
    (programs / "cargo.yaml").write_text("x")

    app = QApplication.instance() or QApplication([])
    tab = StatsTab(store, programs_dir=str(programs))
    offered = [tab.program_filter.itemText(i)
               for i in range(tab.program_filter.count())]
    assert offered == ["All programs", "cargo"]
    assert "retired1211" in store.programs()      # still recorded, just not offered
