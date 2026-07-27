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

def test_validate_det_kills_the_units_whose_bit_is_clear():
    """A set bit means the slot is OCCUPIED, so clear bits are killed."""
    ctx = flow_ctx()
    ctx.init_alive(4)
    # 16 + 0b0101 -> slots 0 and 2 occupied, 1 and 3 empty
    call(ctx, "Cargo", "VALIDATE_DET", row("Cargo", "VALIDATE_DET", "21"))
    assert ctx.alive[0] == 1 and ctx.alive[2] == 1
    assert ctx.alive[1] == 0 and ctx.alive[3] == 0


def test_validate_det_accepts_the_hex_the_board_actually_sends():
    """The cargo control board answers "1F" -- all four present, kill none."""
    ctx = flow_ctx()
    ctx.init_alive(4)
    call(ctx, "Cargo", "VALIDATE_DET", row("Cargo", "VALIDATE_DET", "1F"))
    assert ctx.alive == [1, 1, 1, 1]


def test_validate_det_kills_everything_when_the_fixture_is_empty():
    """Written as decimal 16 on purpose.

    The board would send "10" for this, but decimal-first parsing reads that as
    ten -- the documented ambiguity of unprefixed hex. Asserting on 16 tests the
    polarity without baking in the ambiguity.
    """
    ctx = flow_ctx()
    ctx.init_alive(4)
    call(ctx, "Cargo", "VALIDATE_DET", row("Cargo", "VALIDATE_DET", "16"))
    assert ctx.alive == [0, 0, 0, 0]


def test_an_all_digit_hex_reading_is_ambiguous_and_says_so():
    """"10" from the board means sixteen, but reads as ten. Fails loudly."""
    ctx = flow_ctx()
    ctx.init_alive(4)
    with pytest.raises(VerbError, match="outside 0-15"):
        call(ctx, "Cargo", "VALIDATE_DET", row("Cargo", "VALIDATE_DET", "10"))


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


# --- EVALLEDS: faithful port of v1's K-means colour check ----------------

def _led_ctx():
    program = from_dict({"modules": {"Vision": "ImageProcessManager"},
                         "exec": [["Flow", "LABEL", "A"]]}).finalize()
    ctx = Context(program, simulate=True)
    ctx.init_data(8, 3, 2)
    ctx.init_alive(2)
    ctx.record = RunRecord()
    return ctx


def _solid_frame(bgr, size=80):
    np = pytest.importorskip("numpy")
    frame = np.zeros((size, size, 3), dtype=np.uint8)
    frame[:, :] = bgr
    return frame


def test_evalleds_passes_when_the_dominant_colour_matches_the_target():
    pytest.importorskip("cv2")
    ctx = _led_ctx()
    ctx.set_data("0,0,0", _solid_frame((75, 221, 243)), stringify=False)
    call(ctx, "Vision", "EVALLEDS",
         row("Vision", "EVALLEDS", "*0,0,0", "40,40,20,4000",
             "1,0,0;1,1,0;1,2,0", "75,221,243", "0,COLOR_A"))
    assert ctx.get_data("1,1,0") == "PASS"
    assert ctx.alive[0] == 1


def test_evalleds_fails_and_kills_when_the_colour_is_wrong():
    pytest.importorskip("cv2")
    ctx = _led_ctx()
    ctx.set_data("0,0,0", _solid_frame((10, 10, 200)), stringify=False)
    call(ctx, "Vision", "EVALLEDS",
         row("Vision", "EVALLEDS", "*0,0,0", "40,40,20,4000",
             "1,0,0;1,1,0;1,2,0", "75,221,243", "0,COLOR_A"))
    assert ctx.get_data("1,1,0") == "FAIL"
    assert ctx.alive[0] == 0


def test_evalleds_reads_a_path_from_the_data_cell(tmp_path):
    """v1 stores a file path there and cv2.imread's it -- both forms must work."""
    cv2 = pytest.importorskip("cv2")
    ctx = _led_ctx()
    path = str(tmp_path / "led.png")
    cv2.imwrite(path, _solid_frame((75, 221, 243)))
    ctx.set_data("0,0,0", path)
    call(ctx, "Vision", "EVALLEDS",
         row("Vision", "EVALLEDS", "*0,0,0", "40,40,20,4000",
             "1,0,0;1,1,0;1,2,0", "75,221,243", "0,COLOR_A"))
    assert ctx.get_data("1,1,0") == "PASS"


def test_evalleds_uses_the_four_part_coordinate_form():
    """x,y,crop_radius,threshold -- a 2-part form is a program error, not silent."""
    pytest.importorskip("cv2")
    ctx = _led_ctx()
    ctx.set_data("0,0,0", _solid_frame((75, 221, 243)), stringify=False)
    call(ctx, "Vision", "EVALLEDS",
         row("Vision", "EVALLEDS", "*0,0,0", "40,40",
             "1,0,0;1,1,0;1,2,0", "75,221,243", "0,COLOR_A"))
    assert ctx.get_data("1,1,0") == "FAIL"


def test_evalleds_tolerance_matches_v1():
    from ngwart.drivers.imageproc import LED_CLUSTERS, LED_TOLERANCE

    assert (LED_CLUSTERS, LED_TOLERANCE) == (3, 30)


# --- EVALCONT: contour selection must match v1 ---------------------------

def _contour_ctx():
    program = from_dict({"modules": {"Vision": "ImageProcessManager"},
                         "exec": [["Flow", "LABEL", "A"]]}).finalize()
    ctx = Context(program, simulate=True)
    ctx.init_data(8, 3, 2)
    ctx.init_alive(2)
    ctx.record = RunRecord()
    return ctx


def _blobs(*specs, size=400):
    """Render filled circles and return their external contours."""
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    img = np.zeros((size, size), dtype=np.uint8)
    for cx, cy, r in specs:
        cv2.circle(img, (cx, cy), r, 255, -1)
    contours, _ = cv2.findContours(img, cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE)
    return list(contours)


def test_evalcont_picks_the_largest_in_window_contour_not_the_nearest():
    """The bug that failed INTENSITY_A..F on the real fixture.

    A small speck sits nearer the nominal centre than the blob being measured.
    Selecting by proximity picks the speck and fails the area limit; v1 selects
    by area and passes.
    """
    ctx = _contour_ctx()
    ctx.set_data("0,0,0", _blobs((200, 200, 5), (208, 200, 30)), stringify=False)
    call(ctx, "Vision", "EVALCONT",
         row("Vision", "EVALCONT", "*0,0,0", "200,200,40,500,1",
             "1,0,0;1,1,0;1,2,0", "min", "0,INTENSITY_A"))
    assert ctx.get_data("1,1,0") == "PASS"
    assert ctx.alive[0] == 1


def test_evalcont_ignores_contours_below_the_noise_floor():
    ctx = _contour_ctx()
    ctx.set_data("0,0,0", _blobs((200, 200, 3)), stringify=False)   # ~28 px
    call(ctx, "Vision", "EVALCONT",
         row("Vision", "EVALCONT", "*0,0,0", "200,200,40,10,1",
             "1,0,0;1,1,0;1,2,0", "min", "0,INTENSITY_A"))
    assert ctx.get_data("1,1,0") == "FAIL"
    assert ctx.get_data("1,0,0") == "NOT_FOUND"


def test_evalcont_reports_not_found_rather_than_zero_area():
    ctx = _contour_ctx()
    ctx.set_data("0,0,0", _blobs((50, 50, 30)), stringify=False)
    call(ctx, "Vision", "EVALCONT",
         row("Vision", "EVALCONT", "*0,0,0", "300,300,20,100,1",
             "1,0,0;1,1,0;1,2,0", "min", "0,INTENSITY_B"))
    assert ctx.get_data("1,0,0") == "NOT_FOUND"
    assert ctx.alive[0] == 0


def test_evalcont_applies_the_calibration_factor():
    ctx = _contour_ctx()
    ctx.set_data("0,0,0", _blobs((200, 200, 20)), stringify=False)  # ~1250 px
    # raw area ~1250; x0.1 -> ~125, which clears a limit of 100.
    call(ctx, "Vision", "EVALCONT",
         row("Vision", "EVALCONT", "*0,0,0", "200,200,30,100,0.1",
             "1,0,0;1,1,0;1,2,0", "min", "0,CAL"))
    assert ctx.get_data("1,1,0") == "PASS"
    assert 100 < float(ctx.get_data("1,0,0")) < 200


def test_test_id_ignores_a_trailing_grid_hint():
    """cargo.ods writes '0,COLOR_A,min' -- the id is COLOR_A, not 'COLOR_A,min'."""
    ctx = _contour_ctx()
    ctx.set_data("0,0,0", _blobs((200, 200, 25)), stringify=False)
    call(ctx, "Vision", "EVALCONT",
         row("Vision", "EVALCONT", "*0,0,0", "200,200,30,100,1",
             "1,0,0;1,1,0;1,2,0", "min", "0,COLOR_A,min"))
    assert ctx.record.points[0].name == "COLOR_A"


# --- JL hex tolerance (the cargo control board answers in hex) ----------

def test_jl_accepts_a_hex_reading():
    """The detection poll returns "1F"; a plain float() raises on it."""
    ctx = flow_ctx()
    ctx.program.labels["DETECTION"] = 0
    ctx.set_data("0,0,0", "1F")
    call(ctx, "Flow", "JL", row("Flow", "JL", "DETECTION", "*0,0,0", "16"))
    assert ctx.pending_jump is None          # 31 >= 16, so no jump


def test_jl_still_prefers_decimal():
    """v1's order: "10" is ten, not sixteen. Kept deliberately."""
    ctx = flow_ctx()
    ctx.program.labels["DETECTION"] = 0
    ctx.set_data("0,0,0", "10")
    call(ctx, "Flow", "JL", row("Flow", "JL", "DETECTION", "*0,0,0", "16"))
    assert ctx.pending_jump == "DETECTION"   # 10 < 16 -> jumps


def test_jl_reports_a_value_that_is_neither():
    ctx = flow_ctx()
    ctx.program.labels["DETECTION"] = 0
    ctx.set_data("0,0,0", "ZZZ")
    with pytest.raises(VerbError, match="neither a decimal nor a hex"):
        call(ctx, "Flow", "JL", row("Flow", "JL", "DETECTION", "*0,0,0", "16"))


# --- legacy UI shim must absorb every way a Tk widget gets used ----------

def test_inert_widget_absorbs_subscripting():
    """The bench failure: SYNCGRID1 indexes UI.frames[0].Tree.

    __getattr__ alone does not cover it -- Python resolves dunders on the type,
    so widget[0] raised "not subscriptable" and a PASSING optical test was
    reported as an image-processing failure.
    """
    from ngwart.drivers.legacy import _NullWidget

    w = _NullWidget()
    w["columns"] = ("a", "b")            # __setitem__
    assert w["columns"] is not None      # __getitem__
    assert w.insert(parent="", index="end", values=(1, 2)) is not None
    assert w.column("#0", width=0).heading("x") is not None   # chains
    assert list(w) == [] and len(w) == 0
    assert "x" not in w and not w
    assert str(w) == ""


def test_legacy_ui_frame_exposes_the_grid_attributes_v1_touches():
    from ngwart.drivers.legacy import LegacyUI

    class Ctx:
        def log(self, *a, **k): pass

    ui = LegacyUI(Ctx())
    frame = ui.frames[0]
    for name in ("Tree", "Tree2", "Tree3", "Tree4"):
        widget = getattr(frame, name)
        widget["columns"] = ("A",)
        widget.insert(parent="", index="end", iid=0, values=("x",), tag="PASS")
    assert frame.DGRID1_iid == 0


# --- VISA OPENALL must not fight pyserial for the COM ports -------------

def test_openall_skips_serial_resources_by_default(monkeypatch):
    """ASRL resources are COM ports that FINDPORT already owns.

    Opening them through VISA as well gives VI_ERROR_RSRC_BUSY at best, and
    steals the port from the running test at worst.
    """
    from ngwart.drivers import visa as visa_mod

    seen = []
    monkeypatch.setattr(visa_mod, "SIM_RESOURCES",
                        ["USB0::0x1AB1::0xA4A8::DP2A::INSTR",
                         "ASRL1::INSTR", "ASRL13::INSTR"])
    real_make = visa_mod.make_visa

    def spy(simulate, resource, timeout, **kw):
        seen.append(resource)
        return real_make(simulate, resource, timeout, **kw)

    monkeypatch.setattr(visa_mod, "make_visa", spy)

    ctx = flow_ctx()
    ctx.simulate = True
    call(ctx, "VISA", "OPENALL", row("VISA", "OPENALL", "10000"))
    assert not any(r.startswith("ASRL") for r in seen), seen
    assert any("DP2A" in r for r in seen)


def test_openall_can_be_asked_for_serial_resources(monkeypatch):
    from ngwart.drivers import visa as visa_mod

    seen = []
    monkeypatch.setattr(visa_mod, "SIM_RESOURCES",
                        ["USB0::0x1AB1::0xA4A8::DP2A::INSTR", "ASRL1::INSTR"])
    real_make = visa_mod.make_visa
    monkeypatch.setattr(visa_mod, "make_visa",
                        lambda s, r, t, **k: (seen.append(r), real_make(s, r, t, **k))[1])

    ctx = flow_ctx()
    ctx.simulate = True
    call(ctx, "VISA", "OPENALL", row("VISA", "OPENALL", "10000", "ALL"))
    assert any(r.startswith("ASRL") for r in seen), seen


def test_result_triplet_is_derived_from_a_single_index():
    """v1's getTripleIndex: one index implies three, by incrementing column.

    cargo.ods writes a single "0,0,1". Supporting only the explicit
    ';'-separated form stored the measured area but left the verdict nowhere.
    """
    pytest.importorskip("cv2")
    ctx = _contour_ctx()
    ctx.set_data("0,0,0", _blobs((200, 200, 25)), stringify=False)
    call(ctx, "Vision", "EVALCONT",
         row("Vision", "EVALCONT", "*0,0,0", "200,200,30,100,1",
             "1,0,0", "min", "0,INTENSITY_A"))
    assert ctx.get_data("1,1,0") == "PASS"          # derived +1 column
    assert ctx.get_data("1,2,0") == "INTENSITY_A"   # derived +2 columns
    assert float(ctx.get_data("1,0,0")) > 100


def test_explicit_triplet_still_works():
    pytest.importorskip("cv2")
    ctx = _contour_ctx()
    ctx.set_data("0,0,0", _blobs((200, 200, 25)), stringify=False)
    call(ctx, "Vision", "EVALCONT",
         row("Vision", "EVALCONT", "*0,0,0", "200,200,30,100,1",
             "1,0,0;2,0,0;3,0,0", "min", "0,X"))
    assert ctx.get_data("2,0,0") == "PASS"
    assert ctx.get_data("3,0,0") == "X"


# --- camera backend contract --------------------------------------------

def test_every_camera_backend_implements_the_same_interface():
    """set_property(name, value) was the wrong abstraction.

    Binning, a centred AOI and the User1 white-balance set are not independent
    scalars, and an interface that cannot report "I could not apply that" lets a
    camera sit at its default geometry while every coordinate downstream misses.
    """
    from ngwart.drivers.backends.real import OpenCvCamera
    from ngwart.drivers.backends.sim import SimCamera

    required = ("open", "close", "capture", "configure", "set_exposure",
                "calibrate_white_balance", "white_balance_gains")
    backends = [SimCamera, OpenCvCamera]
    try:
        from ngwart.drivers.backends.mvimpact import MvImpactCamera
        backends.append(MvImpactCamera)
    except ImportError:
        pass

    for backend in backends:
        missing = [n for n in required if not hasattr(backend, n)]
        assert missing == [], f"{backend.__name__} is missing {missing}"


def test_configure_reports_what_it_could_not_apply():
    from ngwart.drivers.backends.sim import SimCamera

    cam = SimCamera("SIM"); cam.open()
    result = cam.configure({"width": 1296, "height": 972, "buffersize": 4})
    assert result["ignored"] == []
    assert cam.width == 1296 and cam.height == 972
    assert cam.capture().shape[:2] == (972, 1296)


def test_setprops_fails_when_geometry_cannot_be_applied():
    """A silently-dropped AOI is the bug this guard exists for."""
    ctx = flow_ctx()
    ctx.simulate = False

    class Deaf:
        is_open = True
        def configure(self, props):
            return {"applied": {}, "ignored": ["width=1296", "height=972"],
                    "notes": []}

    ctx.driver_state("camera").setdefault("cameras", {})["CAM"] = Deaf()
    with pytest.raises(VerbError, match="could not apply"):
        call(ctx, "Camera", "SETPROPS",
             row("Camera", "SETPROPS", "CAM", "4,1296,972"))


def test_setprops_tolerates_properties_the_sensor_lacks():
    """Focus and hue do not exist on a BlueFOX; v1 ignores them, so must we."""
    ctx = flow_ctx()
    ctx.simulate = True
    call(ctx, "Camera", "SETPROPS",
         row("Camera", "SETPROPS", "UB101256", "4,640,480", "0,0",
             "0,120", "0,100,0,0"))
    cam = ctx.driver_state("camera")["cameras"]["UB101256"]
    assert (cam.width, cam.height) == (640, 480)


def test_calibratewb_warns_when_the_reference_was_too_dark():
    ctx = flow_ctx()
    ctx.simulate = True
    cam = ctx.driver_state("camera").setdefault("cameras", {})
    class Neutral:
        is_open = True
        def calibrate_white_balance(self, exposure_us, warmup):
            return (1.0, 1.0, 1.0)          # no correction computed
    cam["CAM"] = Neutral()

    logs = []
    ctx.listener = type("L", (), {"emit": lambda _s, e: logs.append(
        getattr(e, "message", ""))})()
    call(ctx, "Camera", "CALIBRATEWB", row("Camera", "CALIBRATEWB", "CAM"))
    assert any("too" in m and "dark" in m for m in logs), logs
