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
