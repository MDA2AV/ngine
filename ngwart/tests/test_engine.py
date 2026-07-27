"""Engine tests: program model, context, validation, sequencing.

These run headlessly against the simulated backends -- no Qt, no hardware. That
is the point of keeping the engine free of UI imports.
"""

from __future__ import annotations

import pytest

import ngwart.drivers  # noqa: F401 - registers verbs
from ngwart.engine import (REGISTRY, Context, ProgramError, RecordingListener,
                           RunOptions, Sequencer, validate)
from ngwart.engine.events import GridEvent, LogEvent, ResultEvent
from ngwart.engine.loaders.native import from_dict
from ngwart.engine.program import Program, Row


def build(**sections) -> Program:
    doc = {"modules": {"Flow": "FlowManager", "UI": "UIManager"}}
    doc.update(sections)
    return from_dict(doc).finalize()


def run(program, *, simulate=True, strict=True):
    listener = RecordingListener()
    seq = Sequencer(REGISTRY, listener, RunOptions(simulate=simulate, strict=strict))
    record = seq.run(program)
    return record, listener


# --- program model ------------------------------------------------------

def test_row_pads_to_ten_columns():
    row = Row(index=0, cells=["Flow", "J"])
    assert len(row.cells) == 10
    assert row.raw(9) == ""


def test_dash_is_treated_as_absent():
    row = Row(index=0, cells=["Flow", "DELAY", "-", "", "", "", "", "", "", ""])
    assert not row.has(2)


def test_sections_and_labels_are_parsed():
    program = build(
        exec=[["Flow", "LABEL", "START"], ["Flow", "DELAY", "0"],
              ["Flow", "LABEL", "END"]])
    assert "Exec" in program.sections
    assert program.labels["START"] < program.labels["END"]


def test_duplicate_label_is_rejected():
    with pytest.raises(ProgramError, match="duplicate label"):
        build(exec=[["Flow", "LABEL", "A"], ["Flow", "LABEL", "A"]])


def test_ehandling_is_inside_the_executable_range():
    """Labels after <Exec/> must still be reachable -- real tables rely on it."""
    program = build(
        exec=[["Flow", "J", "HANDLER"]],
        ehandling=[["Flow", "LABEL", "HANDLER"]],
    )
    assert program.exec_end > program.labels["HANDLER"]


def test_teardown_bounds_the_executable_range():
    program = build(
        exec=[["Flow", "LABEL", "A"]],
        teardown=[["Flow", "DISABLE_TIMER"]],
    )
    assert program.exec_end == program.sections["Teardown"].start


# --- context ------------------------------------------------------------

def make_ctx(program=None, **vars_):
    program = program or build(exec=[["Flow", "LABEL", "A"]])
    program.vars.update(vars_)
    ctx = Context(program)
    ctx.init_data(4, 3, 2)
    ctx.init_alive(4)
    return ctx


def test_named_variables_resolve_to_coordinates():
    ctx = make_ctx(**{"uut0.vbat": "1,2,0"})
    ctx.set_data("uut0.vbat", "13.5")
    assert ctx.get_data("1,2,0") == "13.5"
    assert ctx.content("*uut0.vbat") == "13.5"


def test_star_prefix_is_accepted_on_destinations():
    ctx = make_ctx(**{"x": "0,0,0"})
    ctx.set_data("*x", "7")
    assert ctx.content("*x") == "7"


def test_unknown_variable_gives_a_helpful_error():
    ctx = make_ctx(**{"known": "0,0,0"})
    with pytest.raises(ProgramError, match="known variables"):
        ctx.get_data("nope")


def test_out_of_range_reference_names_the_dimensions():
    ctx = make_ctx()
    with pytest.raises(Exception, match="outside the allocated store"):
        ctx.get_data("99,0,0")


def test_alive_mask_any_semantics():
    ctx = make_ctx()
    ctx.kill(0)
    assert ctx.is_any_alive("0,1") is True      # 1 still alive
    ctx.kill(1)
    assert ctx.is_any_alive("0,1") is False


def test_alive_mask_all_semantics():
    """A leading dash means 'every listed unit must be alive'."""
    ctx = make_ctx()
    assert ctx.is_any_alive("-,0,1") is True
    ctx.kill(1)
    assert ctx.is_any_alive("-,0,1") is False
    assert ctx.is_any_alive("0,1") is True


def test_alive_mask_dash_runs_always():
    ctx = make_ctx()
    for i in range(4):
        ctx.kill(i)
    assert ctx.is_any_alive("-") is True


def test_killing_out_of_range_is_an_error():
    ctx = make_ctx()
    with pytest.raises(Exception, match="alive mask holds"):
        ctx.kill(9)


# --- validation ---------------------------------------------------------

def test_unknown_verb_is_an_error_with_a_suggestion():
    program = build(exec=[["Flow", "DELY", "1"]])
    report = validate(program)
    assert not report.ok
    assert "DELAY" in report.errors[0].message


def test_missing_required_argument_is_caught():
    program = build(exec=[["Flow", "DELAY"]])
    report = validate(program)
    assert any("missing required argument" in d.message for d in report.errors)


def test_undefined_jump_target_is_caught():
    program = build(exec=[["Flow", "J", "NOWHERE"]])
    report = validate(program)
    assert any("undefined label" in d.message for d in report.errors)


def test_verb_without_module_warns_but_does_not_block():
    """The exact defect present in cargo.ods: a verb with a blank column 0.

    Reported, but not fatal -- the row is skipped and the program still loads,
    which is no worse than v1, where globals()[""] raised KeyError and the step
    never ran either.
    """
    program = build(exec=[["", "LOG_FLAG", "OFF"]])
    report = validate(program)
    assert report.ok
    assert any("has no module" in d.message for d in report.warnings)


def test_a_module_less_row_is_skipped_at_runtime():
    program = build(exec=[["TestData", "INITDATA", "4", "3", "2"],
                          ["", "LOG_FLAG", "OFF"],
                          ["Flow", "STORE", "after", "0,0,0"]])
    record, listener = run(program)
    assert not record.aborted
    assert any("has no module" in m for m in listener.messages())
    assert any(s.verb == "STORE" for s in record.steps)   # execution continued


def test_alive_index_beyond_initalive_is_caught():
    program = build(
        config=[["TestData", "initAlive", "2"]],
        exec=[["Flow", "DELAY", "0", "", "", "", "", "", "3"]])
    report = validate(program)
    assert any("initAlive declares 2" in d.message for d in report.errors)


def test_reference_outside_initdata_is_caught():
    program = build(exec=[["TestData", "INITDATA", "4", "3", "2"],
                          ["Flow", "STORE", "*99,0,0", "0,0,0"]])
    report = validate(program)
    assert any("outside the data store" in d.message for d in report.errors)


def test_unclosed_parallel_block_is_caught():
    program = build(exec=[["<ParallelTask>"], ["Flow", "DELAY", "0"]])
    report = validate(program)
    assert any("never closed" in d.message for d in report.errors)


def test_missing_teardown_is_a_warning_not_an_error():
    program = build(exec=[["Flow", "LABEL", "A"]])
    report = validate(program)
    assert report.ok
    assert any("Teardown" in d.message for d in report.warnings)


def test_strict_mode_refuses_to_execute_an_invalid_program():
    program = build(exec=[["Flow", "NOPE"]])
    record, listener = run(program)
    assert record.aborted
    assert "validation" in record.abort_reason
    # Nothing ran: no step was recorded.
    assert record.steps == []


# --- sequencing ---------------------------------------------------------

def test_jump_moves_the_pointer():
    program = build(exec=[
        ["Flow", "LABEL", "START"],
        ["TestData", "INITDATA", "4", "3", "2"],
        ["Flow", "J", "SKIP"],
        ["Flow", "STORE", "reached", "0,0,0"],
        ["Flow", "LABEL", "SKIP"],
    ])
    record, listener = run(program)
    assert not record.aborted
    stored = [s for s in record.steps if s.verb == "STORE"]
    assert stored == []          # the skipped row never executed


def test_alive_mask_skips_rows_for_dead_units():
    program = build(
        config=[["TestData", "initAlive", "2"]],
        exec=[["TestData", "INITDATA", "4", "3", "2"],
              ["TestData", "AKILL", "0"],
              ["Flow", "STORE", "x", "0,0,0", "", "", "", "", "0"]])
    record, _ = run(program)
    skipped = [s for s in record.steps if s.outcome == "skipped"]
    assert len(skipped) == 1


def test_failure_routes_to_the_rows_handler():
    program = build(
        config=[["TestData", "initAlive", "1"]],
        exec=[["TestData", "INITDATA", "4", "3", "2"],
              ["Flow", "DIV", "0,0,0", "1", "0", "", "", "MATH_EX"],
              ["Flow", "STORE", "not-reached", "0,0,1"],
              ["Flow", "J", "DONE"]],
        ehandling=[["Flow", "LABEL", "MATH_EX"],
                   ["Flow", "STORE", "handled", "0,0,2"],
                   ["Flow", "LABEL", "DONE"]])
    record, _ = run(program)
    verbs = [(s.verb, s.args[0] if s.args else "") for s in record.steps]
    assert ("STORE", "handled") in verbs
    assert ("STORE", "not-reached") not in verbs


def test_blank_exception_column_falls_back_to_std_ex():
    """v1 behaviour that real tables depend on."""
    program = build(
        exec=[["TestData", "INITDATA", "4", "3", "2"],
              ["Flow", "DIV", "0,0,0", "1", "0"],
              ["Flow", "J", "DONE"]],
        ehandling=[["Flow", "LABEL", "STD_EX"],
                   ["Flow", "STORE", "caught", "0,0,1"],
                   ["Flow", "LABEL", "DONE"]])
    record, _ = run(program)
    assert any(s.args[0] == "caught" for s in record.steps if s.verb == "STORE")


def test_program_error_is_never_routed():
    """A malformed program must stop, not limp along on its own handlers."""
    program = build(
        exec=[["TestData", "INITDATA", "4", "3", "2"],
              ["Flow", "STORE", "x", "999,0,0", "", "", "", "ANY_EX"],
              ["Flow", "J", "DONE"]],
        ehandling=[["Flow", "LABEL", "ANY_EX"],
                   ["Flow", "LABEL", "DONE"]])
    record, _ = run(program, strict=False)
    assert record.aborted


def test_teardown_runs_after_a_failure():
    program = build(
        exec=[["TestData", "INITDATA", "4", "3", "2"],
              ["Flow", "DIV", "0,0,0", "1", "0"]],
        teardown=[["Flow", "STORE", "safe", "0,0,1"]])
    record, _ = run(program)
    assert record.aborted
    assert any(s.verb == "STORE" and s.args[0] == "safe" for s in record.steps)


def test_teardown_runs_after_an_operator_stop():
    program = build(
        exec=[["Flow", "DELAY", "5"]],
        teardown=[["Flow", "DISABLE_TIMER"]])
    listener = RecordingListener()
    seq = Sequencer(REGISTRY, listener, RunOptions(simulate=True))

    import threading
    threading.Timer(0.15, seq.stop).start()
    record = seq.run(program)

    assert record.aborted
    assert any(s.verb == "DISABLE_TIMER" for s in record.steps)


def test_a_failing_teardown_step_does_not_stop_the_rest():
    program = build(
        exec=[["TestData", "INITDATA", "4", "3", "2"]],
        teardown=[["Flow", "DIV", "0,0,0", "1", "0"],
                  ["Flow", "STORE", "still-ran", "0,0,1"]])
    record, _ = run(program)
    assert any(s.verb == "STORE" and s.args[0] == "still-ran" for s in record.steps)


def test_parallel_block_runs_every_task():
    program = build(
        exec=[["TestData", "INITDATA", "4", "3", "2"],
              ["<ParallelTask>"],
              ["Flow", "DELAY", "0.05"],
              ["Flow", "DELAY", "0.05"],
              ["Flow", "DELAY", "0.05"],
              ["<ParallelTask/>"]])
    record, _ = run(program)
    assert not record.aborted
    assert len([s for s in record.steps if s.verb == "DELAY"]) == 3


def test_parallel_block_is_actually_concurrent():
    """Three 0.25 s waits must finish in well under their 0.75 s sum.

    In v1 these were coroutines performing blocking I/O, so they serialised.
    """
    program = build(
        exec=[["<ParallelTask>"],
              ["Flow", "DELAY", "0.25"],
              ["Flow", "DELAY", "0.25"],
              ["Flow", "DELAY", "0.25"],
              ["<ParallelTask/>"]])
    record, _ = run(program)
    assert record.duration_s < 0.6


def test_run_record_captures_points_and_verdicts():
    program = build(
        config=[["TestData", "initAlive", "1"]],
        exec=[["TestData", "INITDATA", "4", "3", "2"],
              ["Flow", "EVAFLOAT", "1.0,2.0", "1.5", "0,0,0;0,1,0;0,2,0",
               "min", "0,VTEST"]])
    record, _ = run(program)
    assert len(record.points) == 1
    assert record.points[0].name == "VTEST"
    assert record.points[0].result == "PASS"
    assert record.passed(0)


def test_out_of_limits_measurement_kills_the_unit():
    program = build(
        config=[["TestData", "initAlive", "2"]],
        exec=[["TestData", "INITDATA", "4", "3", "2"],
              ["Flow", "EVAFLOAT", "1.0,2.0", "9.9", "0,0,0;0,1,0;0,2,0",
               "min", "0,VTEST"]])
    record, listener = run(program)
    assert record.points[0].result == "FAIL"
    assert not record.passed(0)
    assert record.final_alive[0] == 0
    assert record.final_alive[1] == 1        # the other unit is untouched
    assert listener.of_type(GridEvent)


def test_result_event_reports_per_uut_verdicts():
    program = build(
        config=[["TestData", "initAlive", "2"]],
        exec=[["TestData", "INITDATA", "4", "3", "2"],
              ["Flow", "EVAFLOAT", "1.0,2.0", "1.5", "0,0,0;0,1,0;0,2,0",
               "min", "0,A"],
              ["Flow", "EVAFLOAT", "1.0,2.0", "9.9", "1,0,0;1,1,0;1,2,0",
               "min", "1,B"]])
    record, listener = run(program)
    results = listener.of_type(ResultEvent)
    assert results and results[-1].per_uut == {0: True, 1: False}
