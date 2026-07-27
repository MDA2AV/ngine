"""Loader and report tests, including compatibility with the real cargo.ods."""

from __future__ import annotations

import os

import pytest

import ngwart.drivers  # noqa: F401
from ngwart.engine import LoaderError, validate
from ngwart.engine.loaders import load, save
from ngwart.engine.loaders.native import from_dict, to_dict
from ngwart.engine.loaders.ods import read_ods, write_ods
from ngwart.engine.runrecord import RunRecord, TestPoint
from ngwart.reports import to_csv, to_json, to_xml

HERE = os.path.dirname(os.path.abspath(__file__))
CARGO = os.path.join(HERE, "..", "..", "cargobay", "src", "TestTables", "cargo.ods")
DEMO = os.path.join(HERE, "..", "programs", "demo.yaml")


# --- ODS ----------------------------------------------------------------

def test_ods_round_trips(tmp_path):
    grid = [["a", "b", ""], ["c", "d,e", "f"], ["", "", ""]]
    path = str(tmp_path / "t.ods")
    write_ods(path, grid)
    back = read_ods(path)
    assert back[0][:2] == ["a", "b"]
    assert back[1] == ["c", "d,e", "f"]


def test_ods_preserves_text_not_floats(tmp_path):
    """pandas turned '5' into 5.0 and blanks into nan; reading XML does not."""
    path = str(tmp_path / "t.ods")
    write_ods(path, [["Flow", "DELAY", "5"], ["Flow", "STORE", "13.50"]])
    grid = read_ods(path)
    assert grid[0][2] == "5"
    assert grid[1][2] == "13.50"


def test_missing_file_is_a_clear_error():
    with pytest.raises(LoaderError, match="not found"):
        load("no-such-program.ods")


def test_unsupported_extension_is_rejected(tmp_path):
    path = tmp_path / "x.docx"
    path.write_text("nope")
    with pytest.raises(LoaderError, match="unsupported program format"):
        load(str(path))


# --- native format ------------------------------------------------------

def test_native_round_trip(tmp_path):
    doc = {
        "meta": {"name": "t"},
        "modules": {"Flow": "FlowManager"},
        "vars": {"a.b": "0,0,0"},
        "exec": [["Flow", "LABEL", "START"], ["Flow", "DELAY", "1"]],
        "teardown": [["Flow", "DISABLE_TIMER"]],
    }
    program = from_dict(doc).finalize()
    path = str(tmp_path / "p.yaml")
    save(program, path)
    back = load(path)
    assert back.modules == {"Flow": "FlowManager"}
    assert back.vars == {"a.b": "0,0,0"}
    assert back.has_teardown
    assert "START" in back.labels


def test_native_mapping_form():
    program = from_dict({
        "modules": {"Flow": "FlowManager"},
        "exec": [{"module": "Flow", "verb": "DELAY", "args": [2],
                  "route": "FLOW_EX", "alive": "0", "comment": "settle"}],
    }).finalize()
    row = program.rows[program.sections["Exec"].start + 1]
    assert (row.module, row.verb, row.raw(2)) == ("Flow", "DELAY", "2")
    assert row.route == "FLOW_EX"
    assert row.comment == "settle"


def test_too_many_arguments_is_rejected():
    with pytest.raises(LoaderError, match="at most"):
        from_dict({"exec": [{"module": "Flow", "verb": "X",
                             "args": [1, 2, 3, 4, 5, 6, 7]}]})


def test_ods_to_yaml_conversion_preserves_rows(tmp_path):
    program = from_dict({
        "modules": {"Flow": "FlowManager"},
        "exec": [["Flow", "LABEL", "A"], ["Flow", "DELAY", "1"]],
    }).finalize()
    ods_path = str(tmp_path / "p.ods")
    save(program, ods_path)
    reloaded = load(ods_path)
    yaml_path = str(tmp_path / "p.yaml")
    save(reloaded, yaml_path)
    final = load(yaml_path)
    assert "A" in final.labels
    assert final.modules == {"Flow": "FlowManager"}


# --- the real legacy table ---------------------------------------------

needs_cargo = pytest.mark.skipif(
    not os.path.exists(CARGO), reason="cargo.ods not present")


@needs_cargo
def test_real_cargo_table_loads():
    program = load(CARGO)
    assert len(program.rows) > 300
    assert program.modules["Serial"] == "WinSerialManager"
    assert "STD_EX" in program.labels
    assert program.section("Ehandling") is not None


@needs_cargo
def test_ehandling_labels_are_reachable():
    """They sit after <Exec/>, so the executable range must extend past it."""
    program = load(CARGO)
    assert program.exec_end > program.labels["STD_EX"]


@needs_cargo
def test_every_verb_used_by_cargo_resolves():
    """The compatibility guarantee: no unknown-verb errors on a real table."""
    program = load(CARGO)
    report = validate(program)
    unknown = [d for d in report.errors if "unknown verb" in d.message]
    assert unknown == []


@needs_cargo
def test_module_less_rows_never_block_loading():
    """A blank module cell is reported, skipped, and never fatal.

    No count is asserted: cargo.ods is a live file the test engineer edits, so
    pinning a number here would fail every time a row is fixed.
    """
    program = load(CARGO)
    report = validate(program)
    assert not [d for d in report.errors if "has no module" in d.message]
    for diag in report.warnings:
        if "has no module" in diag.message:
            assert "skipped" in diag.message


# --- reports ------------------------------------------------------------

def sample_record() -> RunRecord:
    record = RunRecord(program_name="demo", station="ST1", operator="dm")
    record.set_barcode(0, "R02XXXXXXXX")
    record.add_point(TestPoint("VBAT", 0, "PASS", "13.5", "13.0", "14.0"))
    record.add_point(TestPoint("ILOAD", 0, "FAIL", "9.9", "0.1", "1.0"))
    record.add_point(TestPoint("VBAT", 1, "PASS", "13.4", "13.0", "14.0"))
    record.finish([0, 1])
    return record


def test_xml_report_has_one_block_per_uut():
    xml = to_xml(sample_record())
    assert xml.count("<LOG_XML>") == 2
    assert "<serialnumber>R02XXXXXXXX</serialnumber>" in xml


def test_xml_escapes_special_characters():
    record = RunRecord(program_name="a&b")
    record.add_point(TestPoint("x<y", 0, "PASS"))
    record.finish([1])
    assert "&amp;" in to_xml(record) or "&lt;" in to_xml(record)


def test_simulated_runs_are_tagged_in_the_report():
    record = RunRecord(program_name="demo", simulate=True)
    record.add_point(TestPoint("X", 0, "PASS"))
    record.finish([1])
    assert "<simulated>true</simulated>" in to_xml(record)


def test_a_failed_point_makes_the_uut_fail():
    record = sample_record()
    assert record.passed(1) is True
    assert record.passed(0) is False


def test_a_run_with_no_points_does_not_pass():
    """A run that fell over before testing must never report a pass."""
    record = RunRecord(program_name="empty")
    record.finish([1])
    assert record.passed() is False


def test_csv_quotes_embedded_commas():
    record = RunRecord()
    record.add_point(TestPoint("a,b", 0, "PASS", "1"))
    record.finish([1])
    assert '"a,b"' in to_csv(record)


def test_json_report_is_parseable():
    import json
    doc = json.loads(to_json(sample_record()))
    assert doc["summary"]["failed_points"] == 1
    assert len(doc["points"]) == 3


# --- the demo program ---------------------------------------------------

def test_demo_program_is_valid():
    program = load(DEMO)
    report = validate(program)
    assert report.ok, "\n".join(str(d) for d in report.errors)


def test_demo_program_passes_in_simulation():
    from ngwart import run

    record = run(load(DEMO), simulate=True)
    assert not record.aborted, record.abort_reason
    assert record.passed(0) and record.passed(1)
    assert len(record.points) == 8
