"""Driver tests -- especially the consolidated serial verb."""

from __future__ import annotations

import pytest

import ngwart.drivers  # noqa: F401
from ngwart.drivers.backends.sim import SimSerialPort, SimVisaInstrument
from ngwart.engine import REGISTRY, Context, VerbError
from ngwart.engine.loaders.native import from_dict
from ngwart.engine.program import Row
from ngwart.engine.runrecord import RunRecord


def ctx_with_port(port_id="P1", **port_kw):
    program = from_dict({"modules": {"Serial": "WinSerialManager"},
                         "exec": [["Flow", "LABEL", "A"]]}).finalize()
    ctx = Context(program, simulate=True)
    ctx.init_data(8, 3, 2)
    ctx.init_alive(2)
    ctx.record = RunRecord()
    ctx.driver_state("serial").setdefault("ports", {})[port_id] = \
        SimSerialPort("COM99", 115200, 0.2, **port_kw)
    return ctx


def row(*cells):
    padded = list(cells) + [""] * (10 - len(cells))
    return Row(index=0, cells=padded[:10])


def call(ctx, module, verb, r):
    REGISTRY.require(module, verb).fn(ctx, r)


# --- the serial matrix --------------------------------------------------

def test_every_legacy_serial_verb_is_registered():
    """All 27 v1 names must resolve, or existing tables break."""
    legacy = [
        "READLINE_LV0", "READBYTES_LV0", "READBYTES_LT_LV0",
        "READLINE_LV1", "READBYTES_LV1", "READBYTES_LT_LV1",
        "READBYTES_LV2", "READBYTES_LT_LV3",
        "EXCHANGELINE_LVS", "EXCHANGEBYTES_LVS",
        "EXCHANGEBYTES_LT_LV0", "EXCHANGELINE_LT_LV0",
        "EXCHANGELINE_LV1", "EXCHANGEBYTES_LV1", "EXCHANGEBYTES_LT_LV1",
        "EXCHANGELINE_LV2", "EXCHANGEBYTES_LV2", "EXCHANGEBYTES_LT_LV2",
        "EXCHANGEBYTES_LT_LV3", "READVKING",
    ]
    missing = [v for v in legacy if REGISTRY.lookup("WinSerialManager", v) is None]
    assert missing == []


def test_level0_stores_the_raw_response():
    ctx = ctx_with_port()
    call(ctx, "Serial", "EXCHANGELINE_LT_LV0",
         row("Serial", "EXCHANGELINE_LT_LV0", "P1", "hello/n", "", "", "0,0,0"))
    assert ctx.get_data("0,0,0") == "hello"


def test_level1_stores_pass_when_the_target_matches():
    ctx = ctx_with_port()
    call(ctx, "Serial", "EXCHANGELINE_LV1",
         row("Serial", "EXCHANGELINE_LV1", "P1", "ping/n", "ping", "", "0,0,0;0,1,0"))
    assert ctx.get_data("0,0,0") == "PASS"
    assert ctx.get_data("0,1,0") == "ping"


def test_level1_stores_fail_when_it_does_not():
    ctx = ctx_with_port()
    call(ctx, "Serial", "EXCHANGELINE_LV1",
         row("Serial", "EXCHANGELINE_LV1", "P1", "ping/n", "pong", "", "0,0,0"))
    assert ctx.get_data("0,0,0") == "FAIL"


def test_strict_level_raises_after_exhausting_retries():
    ctx = ctx_with_port()
    with pytest.raises(VerbError, match="never returned"):
        call(ctx, "Serial", "EXCHANGELINE_LVS",
             row("Serial", "EXCHANGELINE_LVS", "P1", "ping/n", "nope", "3"))
    # It really did retry.
    assert len(ctx.driver_state("serial")["ports"]["P1"].history) == 3


def test_strict_level_returns_quietly_on_a_match():
    ctx = ctx_with_port()
    call(ctx, "Serial", "EXCHANGELINE_LVS",
         row("Serial", "EXCHANGELINE_LVS", "P1", "ok/n", "ok", "5"))
    assert len(ctx.driver_state("serial")["ports"]["P1"].history) == 1


def test_level3_kills_the_unit_on_mismatch():
    ctx = ctx_with_port()
    call(ctx, "Serial", "EXCHANGEBYTES_LT_LV3",
         row("Serial", "EXCHANGEBYTES_LT_LV3", "P1", "1,2,3", "9,9,9",
             "2,1,UART_TEST", "0,0,0"))
    assert ctx.get_data("0,0,0") == "FAIL"
    assert ctx.alive[1] == 0
    assert ctx.record.points[0].name == "UART_TEST"


def test_byte_payload_round_trips_as_a_comma_list():
    ctx = ctx_with_port()
    call(ctx, "Serial", "EXCHANGEBYTES_LVS",
         row("Serial", "EXCHANGEBYTES_LVS", "P1", "111,102,102,47,47",
             "111,102,102,47,47", "5,5"))
    assert ctx.driver_state("serial")["ports"]["P1"].history[0] == b"off//"


def test_byte_compare_requires_equal_length():
    ctx = ctx_with_port()
    with pytest.raises(VerbError):
        call(ctx, "Serial", "EXCHANGEBYTES_LVS",
             row("Serial", "EXCHANGEBYTES_LVS", "P1", "1,2,3", "1,2", "3,2"))


def test_bad_byte_value_is_reported_clearly():
    ctx = ctx_with_port()
    with pytest.raises(VerbError, match="not a byte value"):
        call(ctx, "Serial", "EXCHANGEBYTES_LVS",
             row("Serial", "EXCHANGEBYTES_LVS", "P1", "1,zzz", "1", "1,1"))


def test_out_of_range_byte_is_reported_clearly():
    ctx = ctx_with_port()
    with pytest.raises(VerbError, match="outside 0-255"):
        call(ctx, "Serial", "EXCHANGEBYTES_LVS",
             row("Serial", "EXCHANGEBYTES_LVS", "P1", "300", "1", "1,1"))


def test_missing_port_names_what_is_available():
    ctx = ctx_with_port("CONTROL")
    with pytest.raises(VerbError, match="CONTROL"):
        call(ctx, "Serial", "EXCHANGELINE_LT_LV0",
             row("Serial", "EXCHANGELINE_LT_LV0", "NOSUCH", "x", "", "", "0,0,0"))


def test_missing_byte_count_is_reported():
    ctx = ctx_with_port()
    with pytest.raises(VerbError, match="byte count"):
        call(ctx, "Serial", "READBYTES_LV0",
             row("Serial", "READBYTES_LV0", "P1", "", "", "", "0,0,0"))


# --- simulated instruments ---------------------------------------------

def test_simulated_supply_tracks_its_setpoint():
    psu = SimVisaInstrument("SIM::PSU")
    psu.write("INST:NSEL 1")
    psu.write("VOLT 13.5")
    psu.write("OUTP ON")
    assert 13.4 < float(psu.query("MEAS:VOLT?")) < 13.6


def test_simulated_supply_reads_zero_when_output_is_off():
    psu = SimVisaInstrument("SIM::PSU")
    psu.write("INST:NSEL 1")
    psu.write("VOLT 13.5")
    psu.write("OUTP OFF")
    assert float(psu.query("MEAS:VOLT?")) < 0.1


def test_simulated_supply_keeps_channels_separate():
    psu = SimVisaInstrument("SIM::PSU")
    psu.write("INST:NSEL 1")
    psu.write("VOLT 5")
    psu.write("OUTP ON")
    psu.write("INST:NSEL 2")
    psu.write("VOLT 12")
    psu.write("OUTP ON")
    assert 11.9 < float(psu.query("MEAS:VOLT?")) < 12.1
    psu.write("INST:NSEL 1")
    assert 4.9 < float(psu.query("MEAS:VOLT?")) < 5.1


def test_detection_poll_reports_absent_then_present():
    port = SimSerialPort("COM1", detect_after=2)
    port.write(b"d\n")
    assert port.readline().strip() == b"31"      # 16 + all four missing
    port.write(b"d\n")
    assert port.readline().strip() == b"16"      # all present


# --- flow verbs ---------------------------------------------------------

def flow_ctx():
    program = from_dict({"modules": {"Flow": "FlowManager"},
                         "exec": [["Flow", "LABEL", "A"]]}).finalize()
    ctx = Context(program, simulate=True)
    ctx.init_data(8, 3, 2)
    ctx.init_alive(2)
    ctx.record = RunRecord()
    return ctx


def test_storef_substitutes_placeholders():
    ctx = flow_ctx()
    ctx.set_data("0,0,0", "2026y")
    ctx.set_data("0,1,0", "12h")
    call(ctx, "Flow", "STOREF",
         row("Flow", "STOREF", r"C:\Logs\%0\%1;*0,0,0;*0,1,0", "1,0,0"))
    assert ctx.get_data("1,0,0") == r"C:\Logs\2026y\12h"


def test_division_by_zero_is_a_clear_error():
    ctx = flow_ctx()
    with pytest.raises(VerbError, match="division by zero"):
        call(ctx, "Flow", "DIV", row("Flow", "DIV", "0,0,0", "1", "0"))


def test_substring_out_of_range_is_reported():
    ctx = flow_ctx()
    ctx.set_data("0,0,0", "abc")
    with pytest.raises(VerbError, match="outside a string"):
        call(ctx, "Flow", "SUBSTRING",
             row("Flow", "SUBSTRING", "*0,0,0", "0", "99", "1,0,0"))


def test_inverted_limits_are_rejected():
    ctx = flow_ctx()
    with pytest.raises(VerbError, match="exceeds upper limit"):
        call(ctx, "Flow", "EVAFLOAT",
             row("Flow", "EVAFLOAT", "5.0,1.0", "3", "0,0,0;0,1,0;0,2,0",
                 "min", "0,X"))


def test_unreadable_measurement_fails_rather_than_crashing():
    ctx = flow_ctx()
    call(ctx, "Flow", "EVAFLOAT",
         row("Flow", "EVAFLOAT", "1.0,2.0", "not-a-number",
             "0,0,0;0,1,0;0,2,0", "min", "0,X"))
    assert ctx.get_data("0,1,0") == "FAIL"
    assert ctx.alive[0] == 0


def test_array_index_out_of_range_is_reported():
    ctx = flow_ctx()
    call(ctx, "Flow", "ARRAY", row("Flow", "ARRAY", "Init", "a", "2"))
    with pytest.raises(VerbError, match="outside"):
        call(ctx, "Flow", "ARRAY", row("Flow", "ARRAY", "Store", "a", "5", "x"))


def test_uninitialised_array_is_reported():
    ctx = flow_ctx()
    with pytest.raises(VerbError, match="never initialised"):
        call(ctx, "Flow", "ARRAY", row("Flow", "ARRAY", "Get", "ghost", "0", "0,0,0"))


# --- product verbs ------------------------------------------------------

def test_validate_det_kills_the_absent_units():
    ctx = flow_ctx()
    ctx.init_alive(4)
    # 16 + 0b0101 -> units 0 and 2 missing
    call(ctx, "Cargo", "VALIDATE_DET", row("Cargo", "VALIDATE_DET", "21"))
    assert ctx.alive[0] == 0 and ctx.alive[2] == 0
    assert ctx.alive[1] == 1 and ctx.alive[3] == 1


def test_validate_det_rejects_an_impossible_reading():
    ctx = flow_ctx()
    with pytest.raises(VerbError, match="outside 0-15"):
        REGISTRY.require("CargoManager", "VALIDATE_DET").fn(
            ctx, row("Cargo", "VALIDATE_DET", "99"))


def test_barcode_length_check():
    ctx = flow_ctx()
    REGISTRY.require("CargoManager", "VALIDATE_BCODE").fn(
        ctx, row("Cargo", "VALIDATE_BCODE", "SHORT", "0,0,0;0,1,0;0,2,0",
                 "24", "R02", "0"))
    assert ctx.get_data("0,1,0") == "FAIL"
    assert ctx.alive[0] == 0


def test_barcode_engineering_level_check():
    ctx = flow_ctx()
    code = "R01" + "X" * 21
    REGISTRY.require("CargoManager", "VALIDATE_BCODE").fn(
        ctx, row("Cargo", "VALIDATE_BCODE", code, "0,0,0;0,1,0;0,2,0",
                 "24", "R02", "0"))
    assert ctx.get_data("0,1,0") == "FAIL"


def test_barcode_accepted_when_both_checks_pass():
    ctx = flow_ctx()
    code = "R02" + "X" * 21
    REGISTRY.require("CargoManager", "VALIDATE_BCODE").fn(
        ctx, row("Cargo", "VALIDATE_BCODE", code, "0,0,0;0,1,0;0,2,0",
                 "24", "R02", "0"))
    assert ctx.get_data("0,1,0") == "PASS"
    assert ctx.alive[0] == 1
    assert ctx.record.barcodes[0] == code


# --- legacy adoption / site-driver override -----------------------------

def test_legacy_adoption_can_override_a_bundled_verb(tmp_path):
    """A site's own driver must be able to displace the bundled one.

    The camera is the motivating case: v1's BaluffManager holds the mvIMPACT
    DeviceManager at module scope because letting it be collected unloads the
    driver stack and invalidates every open handle. Vendor knowledge like that
    is not re-derivable, so the site driver has to be able to win.
    """
    from ngwart.drivers.legacy import adopt
    from ngwart.engine.registry import Registry, VerbSpec

    module = tmp_path / "FakeManager.py"
    module.write_text(
        "def PING(line, UI):\n"
        "    UI.addToLbox('site driver ran')\n"
    )

    reg = Registry()
    reg.add(VerbSpec(module="FakeManager", name="PING",
                     fn=lambda ctx, row: ctx.log("bundled ran")))

    # Without override the bundled verb stands.
    assert adopt("FakeManager", str(module), reg) == 0

    # With override the site driver replaces it.
    assert adopt("FakeManager", str(module), reg, override=True) == 1
    assert reg.lookup("FakeManager", "PING").legacy is True


def test_registry_still_rejects_accidental_duplicates():
    from ngwart.engine.registry import Registry, VerbSpec

    reg = Registry()
    spec = VerbSpec(module="M", name="V", fn=lambda ctx, row: None)
    reg.add(spec)
    with pytest.raises(ValueError, match="duplicate verb"):
        reg.add(spec)


def test_ui_and_engine_modules_are_excluded_from_legacy_override():
    """--legacy must not swap back the modules the v2 engine owns.

    v1's UIManager writes to Tk widgets, so adopting it would leave the Qt grids
    silently blank -- worse than not running.
    """
    from ngwart.cli import LEGACY_EXCLUDED

    assert {"UIManager", "FlowManager", "TestData"} <= LEGACY_EXCLUDED
