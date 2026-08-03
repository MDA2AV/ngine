"""Coordinate teaching: site extraction, capture discovery, click resolution.

Headless -- no Qt and no hardware. The window is a view over these objects, so
everything that decides *what gets written into a test table* is under test
here rather than behind a mouse.
"""

from __future__ import annotations

import json

import pytest

import ngwart.drivers  # noqa: F401 - registers verbs
from ngwart import calibration as cal
from ngwart.drivers import imageproc
from ngwart.engine.errors import LoaderError
from ngwart.engine.loaders.native import from_dict

cv2 = pytest.importorskip("cv2")

import pathlib  # noqa: E402

#: Calibration captures are tools, not test programs, so they live
#: outside programs/.
CAL_DIR = "tools/calibration"


def build(**sections):
    doc = {"modules": {"Flow": "FlowManager", "Vision": "ImageProcessManager",
                       "Camera": "BaluffManager", "TestData": "TestData"}}
    doc.update(sections)
    return from_dict(doc).finalize()


# --- reading sites out of a program -------------------------------------

def test_evalcont_row_becomes_a_site():
    program = build(exec=[
        ["Vision", "EVALCONT", "*c", "895,659,10,50,1", "*d", "min", "0,LED_A"]])
    sites, notes = cal.sites_from_program(program)

    assert notes == []
    assert len(sites) == 1
    site = sites[0]
    assert (site.cx, site.cy, site.tol, site.uut) == (895, 659, 10.0, 0)
    assert site.tests == ["LED_A"]


def test_verbs_sharing_a_coordinate_make_one_site():
    """One LED is one place, even though three verbs point at it.

    This is the whole economy of the tool: on cargo.ods each physical LED is
    named by an intensity check, a colour check and an off-check, so grouping by
    test id would ask the operator to click the same LED three times.
    """
    program = build(exec=[
        ["Vision", "EVALCONT", "*c", "895,659,10,50,1", "*d", "min", "0,INTENSITY_A"],
        ["Vision", "EVALLEDS", "*i", "895,659,10,50", "*d", "240,240,240", "0,COLOR_A"],
        ["Vision", "EVALCONTN", "*c", "895,659,10,50,1", "*d", "min", "0,INTENSITY_A"],
    ])
    sites, _ = cal.sites_from_program(program)

    assert len(sites) == 1
    assert sites[0].tests == ["INTENSITY_A", "COLOR_A"]
    # All three rows, in program order, so phase 2 updates every one of them.
    exec_rows = [i for i in program.body("Exec") if program.rows[i].verb]
    assert [r.row for r in sites[0].refs] == exec_rows


def test_same_coordinate_on_different_units_stays_separate():
    program = build(exec=[
        ["Vision", "EVALCONT", "*c", "100,100,10,50,1", "*d", "min", "0,LED_A"],
        ["Vision", "EVALCONT", "*c", "100,100,10,50,1", "*d", "min", "1,LED_A"]])
    sites, _ = cal.sites_from_program(program)

    assert len(sites) == 2
    assert [s.uut for s in sites] == [0, 1]


def test_tightest_tolerance_wins():
    """The narrowest window is the one that fails first, so it is the one drawn."""
    program = build(exec=[
        ["Vision", "EVALCONT", "*c", "50,50,20,50,1", "*d", "min", "0,A"],
        ["Vision", "EVALCONT", "*c", "50,50,5,50,1", "*d", "min", "0,A"]])
    sites, _ = cal.sites_from_program(program)
    assert sites[0].tol == 5.0


def test_computed_coordinate_is_reported_not_dropped():
    """A site missing from the list is a test that silently keeps its old value."""
    program = build(exec=[
        ["Vision", "EVALCONT", "*c", "*where", "*d", "min", "0,LED_A"]])
    sites, notes = cal.sites_from_program(program)

    assert sites == []
    assert any("cannot be taught" in n for n in notes)


def test_evalconts_is_reported_as_unsupported():
    program = build(exec=[
        ["Vision", "EVALCONTS", "*c", "10;20", "30;40", "5", "50;50"]])
    sites, notes = cal.sites_from_program(program)

    assert sites == []
    assert any("EVALCONTS" in n for n in notes)


def test_evalleds_accepts_several_leds_in_one_cell():
    program = build(exec=[
        ["Vision", "EVALLEDS", "*i", "10,20,5,50;30,40,5,50", "*d",
         "240,240,240", "0,COLOR_A"]])
    sites, _ = cal.sites_from_program(program)

    assert [(s.cx, s.cy) for s in sites] == [(10, 20), (30, 40)]
    assert [r.group for s in sites for r in s.refs] == [0, 1]


# --- rewriting a cell ---------------------------------------------------

def test_rewrite_keeps_everything_but_the_coordinate():
    """Tolerance, minimum area and calibration were qualified against boards."""
    program = build(exec=[
        ["Vision", "EVALCONT", "*c", "895,659,10,50,1.5", "*d", "min", "0,LED_A"]])
    sites, _ = cal.sites_from_program(program)

    assert sites[0].refs[0].rewritten(900, 662) == "900,662,10,50,1.5"


def test_rewrite_touches_only_its_own_group():
    program = build(exec=[
        ["Vision", "EVALLEDS", "*i", "10,20,5,50;30,40,5,50", "*d",
         "240,240,240", "0,COLOR_A"]])
    sites, _ = cal.sites_from_program(program)

    assert sites[1].refs[0].rewritten(99, 88) == "10,20,5,50;99,88,5,50"


# --- drift --------------------------------------------------------------

def test_delta_and_tolerance_verdict():
    program = build(exec=[
        ["Vision", "EVALCONT", "*c", "100,100,10,50,1", "*d", "min", "0,LED_A"]])
    site = cal.sites_from_program(program)[0][0]

    assert site.delta is None
    site.teach(104, 97, area=1890.0)
    assert site.delta == (4, -3)
    assert site.within_tolerance is True

    site.teach(130, 100)
    assert site.within_tolerance is False
    assert site.drift == pytest.approx(30.0)


# --- finding the capture ------------------------------------------------

def test_pipeline_is_walked_back_to_the_colour_frame():
    program = build(exec=[
        ["Camera", "CAPTURE", "UB101256", "", "*img.raw"],
        ["Vision", "BGR2GRAY", "*img.raw", "", "*img.grey"],
        ["Vision", "GRAY2BIN", "*img.grey", "", "*img.binary", "", "100"],
        ["Vision", "BIN2CONT", "*img.binary", "", "*img.contours"]])
    cells = cal.find_capture(program)

    assert cells.contours == "*img.contours"
    assert cells.binary.cell == "*img.binary"
    assert (cells.frame.cell, cells.frame.is_path) == ("*img.raw", False)


def test_walk_stops_at_the_capture_not_the_camera_serial():
    """CAPTURE's column 2 is a serial number, not an image.

    Following the chain one step further returns 'UB101256', which resolves to
    nothing -- and the canvas then quietly shows the binary instead of the
    picture the operator meant to look at.
    """
    program = build(exec=[
        ["Camera", "CAPTURE", "UB101256", "", "*img.raw"],
        ["Vision", "BGR2GRAY", "*img.raw", "", "*img.grey"],
        ["Vision", "BIN2CONT", "*img.grey", "", "*img.contours"]])

    assert cal.find_capture(program).frame.cell == "*img.raw"


def test_path_based_pipeline_is_recognised():
    """cargo.ods passes frames as filenames in column 3, not arrays in column 2."""
    program = build(exec=[
        ["Camera", "CAPTURE", "UB101256", "*img.color"],
        ["Vision", "BGR2CONT", "", "*img.color", "img.contours", "*img.binary",
         "180"]])
    cells = cal.find_capture(program)

    assert (cells.frame.cell, cells.frame.is_path) == ("*img.color", True)
    assert (cells.binary.cell, cells.binary.is_path) == ("*img.binary", True)
    assert cells.threshold == 180.0


def test_program_without_contours_says_so():
    program = build(exec=[["Camera", "CAPTURE", "UB101256", "", "*img.raw"]])
    with pytest.raises(LoaderError, match="no \\*2CONT row"):
        cal.find_capture(program)


def test_contour_row_can_be_chosen():
    """cargo.ods has six contour rows -- LEDs on, LEDs off, buttons, per pair."""
    program = build(exec=[
        ["Vision", "BIN2CONT", "*a", "", "*ca"],
        ["Vision", "BIN2CONT", "*b", "", "*cb"]])
    first, second = (r.index for r in cal.contour_rows(program))

    assert cal.find_capture(program).contours == "*ca"
    assert cal.find_capture(program, row_index=second).contours == "*cb"
    with pytest.raises(LoaderError, match="not a \\*2CONT row"):
        cal.find_capture(program, row_index=first - 1)


# --- clicking -----------------------------------------------------------

def _discs(centres, radius=18, size=(240, 640)):
    """A binary frame with a filled disc at each centre, and its contours."""
    import numpy as np

    frame = np.zeros(size, dtype=np.uint8)
    for cx, cy in centres:
        cv2.circle(frame, (cx, cy), radius, 255, -1)
    contours, _ = cv2.findContours(frame, cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE)
    return frame, list(contours)


def test_measure_matches_the_runtime_centroid():
    """The taught value must be the number _find_at will compare against."""
    _, contours = _discs([(128, 120)])
    blob = cal.measure(contours)[0]

    moments = cv2.moments(contours[0])
    assert (blob.cx, blob.cy) == (int(moments["m10"] / moments["m00"]),
                                  int(moments["m01"] / moments["m00"]))


def test_specks_below_the_noise_floor_are_invisible():
    """The runtime skips them, so a site must never be teachable to one."""
    _, contours = _discs([(100, 100), (200, 100)], radius=2)
    assert cal.measure(contours) == []
    assert cal.blob_at(contours, 100, 100) is None


def test_click_inside_a_contour_snaps_to_its_centroid():
    _, contours = _discs([(128, 120)])
    blob = cal.blob_at(contours, 133, 126)

    assert blob is not None
    assert (blob.cx, blob.cy) == (128, 120)


def test_click_near_a_contour_still_finds_it():
    _, contours = _discs([(128, 120)])
    assert cal.blob_at(contours, 150, 120) is not None


def test_click_in_empty_space_finds_nothing():
    _, contours = _discs([(128, 120)])
    assert cal.blob_at(contours, 500, 20) is None


def test_click_between_two_blobs_takes_the_nearer():
    _, contours = _discs([(100, 120), (200, 120)])
    assert cal.blob_at(contours, 130, 120).cx == 100
    assert cal.blob_at(contours, 170, 120).cx == 200


# --- the file -----------------------------------------------------------

def test_saved_file_carries_what_phase_two_needs(tmp_path):
    program = build(exec=[
        ["Vision", "EVALCONT", "*c", "895,659,10,50,1", "*d", "min", "0,INTENSITY_A"],
        ["Vision", "EVALLEDS", "*i", "895,659,10,50", "*d", "240,240,240", "0,COLOR_A"]])
    sites, notes = cal.sites_from_program(program)
    # Further than the 10px window, so this is a site the old table could not
    # have found -- which is the case the file exists to fix.
    sites[0].teach(910, 675, area=1890.0)

    path = tmp_path / "coords.json"
    cal.save(str(path), sites, meta={"capture_program": "cap.yaml"}, notes=notes)
    payload = json.loads(path.read_text())

    assert payload["version"] == cal.FORMAT_VERSION
    entry = payload["sites"][0]
    assert entry["was"] == {"cx": 895, "cy": 659}
    assert entry["now"] == {"cx": 910, "cy": 675}
    assert entry["delta"] == [15, 16]
    assert entry["within_tolerance"] is False

    # Both rows are listed, each with the exact cell to replace and what it was.
    exec_rows = [i for i in program.body("Exec") if program.rows[i].verb]
    assert [r["row"] for r in entry["refs"]] == exec_rows
    assert [r["was_cell"] for r in entry["refs"]] == ["895,659,10,50,1",
                                                      "895,659,10,50"]
    assert [r["now_cell"] for r in entry["refs"]] == ["910,675,10,50,1",
                                                      "910,675,10,50"]


def test_untaught_sites_are_left_out_of_the_file(tmp_path):
    program = build(exec=[
        ["Vision", "EVALCONT", "*c", "10,10,5,50,1", "*d", "min", "0,A"],
        ["Vision", "EVALCONT", "*c", "20,20,5,50,1", "*d", "min", "0,B"]])
    sites, _ = cal.sites_from_program(program)
    sites[0].teach(11, 11)

    path = tmp_path / "coords.json"
    cal.save(str(path), sites)

    payload = json.loads(path.read_text())
    assert [s["tests"] for s in payload["sites"]] == [["A"]]


def test_load_rejects_a_future_format(tmp_path):
    path = tmp_path / "coords.json"
    path.write_text(json.dumps({"version": 99, "sites": []}))
    with pytest.raises(LoaderError, match="format version"):
        cal.load(str(path))


def test_round_trip(tmp_path):
    program = build(exec=[
        ["Vision", "EVALCONT", "*c", "10,10,5,50,1", "*d", "min", "0,A"]])
    sites, _ = cal.sites_from_program(program)
    sites[0].teach(12, 9, area=400.0)

    path = tmp_path / "coords.json"
    cal.save(str(path), sites)
    assert cal.load(str(path))["sites"][0]["now"] == {"cx": 12, "cy": 9}


# --- end to end ---------------------------------------------------------

def test_capture_run_yields_a_frame_and_clickable_contours():
    """The whole phase-1 path, against the simulated camera."""
    from ngwart.engine.loaders import load

    program = load("tools/calibration/demo/demo_calibrate.yaml")
    result = cal.run_capture(program, simulate=True)

    assert result.ok
    assert result.frame is not None and result.frame.ndim == 3   # colour
    assert result.binary is not None and result.binary.ndim == 2  # thresholded

    blobs = cal.measure(result.contours)
    assert len(blobs) == 4
    # Every blob the operator can see is one a click resolves to.
    for blob in blobs:
        assert cal.blob_at(result.contours, blob.cx, blob.cy) == blob


def test_teaching_the_demo_table_against_a_real_capture():
    from ngwart.engine.loaders import load

    sites, notes = cal.sites_from_program(load("programs/demo/demo.yaml"))
    result = cal.run_capture(load("tools/calibration/demo/demo_calibrate.yaml"), simulate=True)

    assert notes == []
    assert len(sites) == 4
    for site in sites:
        blob = cal.blob_at(result.contours, site.cx, site.cy)
        assert blob is not None, f"{site.label} has no contour to teach to"
        site.teach(blob.cx, blob.cy, blob.area)

    # The demo's coordinates already match the simulated camera, so a correct
    # teach must report no drift at all -- a non-zero delta here would mean the
    # centroid rule had drifted from the runtime's.
    assert all(s.delta == (0, 0) for s in sites)
    assert "4 of 4" in cal.summarise(sites)


# --- the window ---------------------------------------------------------
#
# Offscreen, so this runs in CI. It checks wiring, not looks: that a click
# lands on the selected site, snaps to the centroid and advances.

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _window(app, sites=None, capture=None):
    from ngwart.ui.teach_window import CalibrationWindow

    frame, contours = _discs([(100, 120), (300, 120)])
    window = CalibrationWindow(sites=sites if sites is not None else [],
                         capture=None, notes=[], meta={}, out_path="unused.json")
    window.set_capture(frame=frame, binary=frame, contours=contours)
    return window, contours


def test_window_opens_over_a_capture(app):
    window, contours = _window(app)
    assert len(window.canvas.blobs) == 2


def test_click_teaches_the_selected_site_and_advances(app):
    program = build(exec=[
        ["Vision", "EVALCONT", "*c", "100,120,10,50,1", "*d", "min", "0,A"],
        ["Vision", "EVALCONT", "*c", "300,120,10,50,1", "*d", "min", "0,B"]])
    sites, _ = cal.sites_from_program(program)
    window, _ = _window(app, sites)

    window._select(0)
    window._on_pick(103, 118, 900.0)          # as the canvas emits it

    assert sites[0].taught == (103, 118)
    # Selection moved on to the next untaught site, so an operator works down
    # the list without touching the mouse twice per LED.
    assert window._current_index() == 1


def test_free_form_click_appends_a_named_site(app):
    window, _ = _window(app, sites=[])
    assert window._free_form

    window._on_pick(100, 120, 900.0)
    window._on_pick(300, 120, 900.0)

    assert [s.taught for s in window.sites] == [(100, 120), (300, 120)]
    assert [s.note for s in window.sites] == ["SITE_1", "SITE_2"]


def test_saving_writes_only_taught_sites(app, tmp_path):
    program = build(exec=[
        ["Vision", "EVALCONT", "*c", "100,120,10,50,1", "*d", "min", "0,A"],
        ["Vision", "EVALCONT", "*c", "300,120,10,50,1", "*d", "min", "0,B"]])
    sites, _ = cal.sites_from_program(program)
    window, _ = _window(app, sites)
    window.out_path = str(tmp_path / "coords.json")

    window._select(0)
    window._on_pick(100, 120, 900.0)
    cal.save(window.out_path, window.sites, meta=window.meta)

    payload = cal.load(window.out_path)
    assert [s["tests"] for s in payload["sites"]] == [["A"]]


def test_free_form_name_survives_a_table_refresh(app):
    """A typed name is the site's name, not decoration on top of a coordinate."""
    window, _ = _window(app, sites=[])
    window._on_pick(100, 120, 900.0)

    window.table.item(0, 1).setText("D14 POWER LED")
    window._reload_table()

    assert window.sites[0].name == "D14 POWER LED"
    assert window.table.item(0, 1).text() == "D14 POWER LED"


def test_free_form_site_is_named_in_the_file(tmp_path):
    site = cal.Site(uut=None, cx=100, cy=120, tol=10)
    site.teach(100, 120, 900.0)
    site.note = "D14 POWER LED"

    path = tmp_path / "coords.json"
    cal.save(str(path), [site])

    assert cal.load(str(path))["sites"][0]["name"] == "D14 POWER LED"


# --- the whole point ----------------------------------------------------
#
# A camera that moved is the condition this tool exists for. These drive it
# end to end: shift the camera, confirm the table's coordinates now miss, teach
# the new ones, confirm they land.

@pytest.fixture
def shifted():
    """Move the simulated camera, and put it back afterwards."""
    from ngwart.drivers.backends import sim

    previous = sim.CAMERA_SHIFT

    def move(dx, dy):
        sim.set_camera_shift(dx, dy)
        return dx, dy

    yield move
    sim.CAMERA_SHIFT = previous


def _capture():
    from ngwart.engine.loaders import load
    return cal.run_capture(load("tools/calibration/demo/demo_calibrate.yaml"), simulate=True)


def _sites():
    from ngwart.engine.loaders import load
    return cal.sites_from_program(load("programs/demo/demo.yaml"))[0]


def test_unshifted_camera_needs_no_teaching():
    """The baseline: demo.yaml's coordinates are already right."""
    result = _capture()
    for site in _sites():
        blob = cal.blob_at(result.contours, site.cx, site.cy)
        assert blob is not None
        assert (blob.cx, blob.cy) == (site.cx, site.cy)


def test_a_moved_camera_makes_every_site_miss(shifted):
    """25px is beyond demo's 40px window on neither axis alone but both together.

    Uses the runtime's own rule, not the click rule: this is what EVALCONT will
    do when the fixture is run, and it is what an operator sees as a board full
    of dead LEDs.
    """
    shifted(45, 30)
    result = _capture()

    for site in _sites():
        area, _ = imageproc._find_at(cv2, result.contours,
                                     site.cx, site.cy, site.tol)
        assert area is None, f"{site.label} still found -- the shift did nothing"


def test_teaching_recovers_a_moved_camera(shifted):
    """Shift, teach, and the new coordinates find their blobs again."""
    dx, dy = shifted(45, 30)
    result = _capture()
    sites = _sites()

    # What an operator does: click each blob. Resolve the click from where the
    # LED now is, which is what they would see on the canvas.
    for site in sites:
        blob = cal.blob_at(result.contours, site.cx + dx, site.cy + dy)
        assert blob is not None, f"{site.label}: nothing to click"
        site.teach(blob.cx, blob.cy, blob.area)

    # Every site moved by exactly the camera's shift -- a field of parallel
    # arrows, which is the signature of a camera that moved rather than of
    # boards that changed.
    assert {s.delta for s in sites} == {(dx, dy)}
    assert all(s.within_tolerance is False for s in sites)

    # And the taught coordinates are ones the runtime will actually find.
    for site in sites:
        area, centroid = imageproc._find_at(cv2, result.contours,
                                            *site.taught, site.tol)
        assert area is not None, f"{site.label}: taught coordinate still misses"
        assert centroid == site.taught


def test_a_shift_inside_tolerance_is_reported_as_such(shifted):
    """Not every drift needs fixing, and saying so is the useful part."""
    shifted(6, 4)
    result = _capture()
    sites = _sites()

    for site in sites:
        blob = cal.blob_at(result.contours, site.cx + 6, site.cy + 4)
        site.teach(blob.cx, blob.cy, blob.area)

    assert {s.delta for s in sites} == {(6, 4)}
    assert all(s.within_tolerance for s in sites)


# --- coordinates factored into <Vars> -----------------------------------
#
# A table can keep each coordinate in one place and have the eval rows read it
# through a variable. Then a re-teach edits one row per LED instead of four, so
# teaching has to follow the reference back to whoever wrote it.

def build_factored():
    """The shape cargo.yaml uses: STORE the point, STOREF each spec."""
    return build(exec=[
        ["Flow", "STORE", "895,659", "*led.a.xy"],
        ["Flow", "STOREF", "%0,10,50,1;*led.a.xy", "*led.a.cont"],
        ["Flow", "STOREF", "%0,10,50;*led.a.xy", "*led.a.leds"],
        ["Vision", "EVALCONT", "*c", "*led.a.cont", "*d", "min", "0,INTENSITY_A"],
        ["Vision", "EVALLEDS", "*i", "*led.a.leds", "*d", "240,240,240", "0,COLOR_A"],
        ["Vision", "EVALCONTN", "*c", "*led.a.cont", "*d", "min", "0,INTENSITY_A"],
    ])


def test_a_referenced_coordinate_is_traced_to_its_store_row():
    program = build_factored()
    sites, notes = cal.sites_from_program(program)

    assert notes == []
    assert len(sites) == 1
    site = sites[0]
    assert (site.cx, site.cy) == (895, 659)
    assert site.tests == ["INTENSITY_A", "COLOR_A"]


def test_only_the_store_row_is_rewritten():
    """Four verbs read it; one row holds it. That ratio is the whole point."""
    program = build_factored()
    site = cal.sites_from_program(program)[0][0]

    store_row = next(i for i in program.body("Exec")
                     if program.rows[i].verb == "STORE")
    assert [r.row for r in site.refs] == [store_row]
    assert len(site.uses) == 3
    assert site.refs[0].rewritten(898, 661) == "898,661"


def test_tolerance_comes_from_the_composed_spec_not_the_store():
    """A STORE row holds only cx,cy -- the window is in the STOREF template."""
    site = cal.sites_from_program(build_factored())[0][0]
    assert site.tol == 10.0


def test_a_chain_that_never_reaches_a_literal_is_reported():
    program = build(exec=[
        ["Vision", "EVALCONT", "*c", "*computed", "*d", "min", "0,LED_A"]])
    sites, notes = cal.sites_from_program(program)

    assert sites == []
    assert any("cannot be taught" in n for n in notes)




# --- coordinates valued from a file -------------------------------------
#
# A <Vars> row's column 2 names the JSON key its value comes from, and INITDATA
# seeds it. No rows in <Config> set anything up, so teaching has to trace to
# the <Vars> entry and rewrite the file.

def build_valued(tmp_path, values):
    import json as _json

    path = tmp_path / "coords.json"
    path.write_text(_json.dumps(values))
    doc = {
        "modules": {"Flow": "FlowManager", "Vision": "ImageProcessManager"},
        "values": str(path),
        "vars": {
            "led.a.cont": ["0,0,30", "led.a.cont"],
            "led.a.leds": ["0,1,30", "led.a.leds"],
            "c": "1,0,0", "i": "1,1,0", "d": "1,2,0",
        },
        "exec": [
            ["Vision", "EVALCONT", "*c", "*led.a.cont", "*d", "min", "0,INTENSITY_A"],
            ["Vision", "EVALLEDS", "*i", "*led.a.leds", "*d", "240,240,240", "0,COLOR_A"],
            ["Vision", "EVALCONTN", "*c", "*led.a.cont", "*d", "min", "0,INTENSITY_A"],
        ],
    }
    return from_dict(doc, source=str(tmp_path / "p.yaml")).finalize()


def test_values_file_fills_the_variables(tmp_path):
    program = build_valued(tmp_path, {"led.a.cont": "895,659,10,50,1",
                                      "led.a.leds": "895,659,10,50"})
    assert program.value_problems == []
    assert program.var_values["led.a.cont"] == "895,659,10,50,1"


def test_initdata_seeds_them_and_reseeds_after_a_clear(tmp_path):
    """'Static in runtime': present before step one, and again next board."""
    from ngwart.engine.context import Context

    program = build_valued(tmp_path, {"led.a.cont": "895,659,10,50,1",
                                      "led.a.leds": "895,659,10,50"})
    ctx = Context(program, simulate=True)
    ctx.init_data(40, 3, 32)
    assert ctx.text("*led.a.cont") == "895,659,10,50,1"

    ctx.set_data("0,0,0", "board measurement")
    ctx.init_data(40, 3, 32)                       # the TOP loop, next board
    assert ctx.text("*led.a.cont") == "895,659,10,50,1"
    assert ctx.get_data("0,0,0") is None


def test_a_missing_key_is_an_error_before_anything_runs(tmp_path):
    """Found while the fixture is cold, not at row 400 with the supply up."""
    from ngwart.engine import REGISTRY, validate

    program = build_valued(tmp_path, {"led.a.cont": "895,659,10,50,1"})
    assert any("led.a.leds" in p for p in program.value_problems)

    report = validate(program, REGISTRY)
    assert not report.ok
    assert any("led.a.leds" in d.message for d in report.errors)


def test_a_key_no_variable_claims_is_only_a_warning(tmp_path):
    from ngwart.engine import REGISTRY, validate

    program = build_valued(tmp_path, {"led.a.cont": "1,2,10,50,1",
                                      "led.a.leds": "1,2,10,50",
                                      "led.z.cont": "9,9,10,50,1"})
    report = validate(program, REGISTRY)
    assert report.ok
    assert any("led.z.cont" in d.message for d in report.warnings)


def test_both_keys_of_one_led_are_one_site(tmp_path):
    """EVALCONT and EVALLEDS read different keys for the same physical LED."""
    program = build_valued(tmp_path, {"led.a.cont": "895,659,10,50,1",
                                      "led.a.leds": "895,659,10,50"})
    sites, notes = cal.sites_from_program(program)

    assert notes == []
    assert len(sites) == 1
    site = sites[0]
    assert (site.cx, site.cy) == (895, 659)
    assert {r.cell_key for r in site.refs} == {"led.a.cont", "led.a.leds"}
    assert len(site.uses) == 3


def test_teaching_rewrites_the_file_keeping_each_tail(tmp_path):
    """One click moves both keys; the tolerances stay where they were."""
    program = build_valued(tmp_path, {"led.a.cont": "895,659,10,50,1",
                                      "led.a.leds": "895,659,10,50"})
    sites, _ = cal.sites_from_program(program)
    sites[0].teach(898, 662, area=1900.0)

    written = cal.save(str(tmp_path / "record.json"), sites, program=program)
    values = cal.read_coords(written[0])

    assert values["led.a.cont"] == "898,662,10,50,1"
    assert values["led.a.leds"] == "898,662,10,50"


def test_untaught_sites_keep_their_value_in_the_file(tmp_path):
    """A partial file would abort the next run on the first missing key."""
    program = build_valued(tmp_path, {"led.a.cont": "895,659,10,50,1",
                                      "led.a.leds": "895,659,10,50"})
    sites, _ = cal.sites_from_program(program)

    written = cal.save(str(tmp_path / "record.json"), sites, program=program)
    values = cal.read_coords(written[0])
    assert values["led.a.cont"] == "895,659,10,50,1"
    assert len(values) == 2


# --- the real table -----------------------------------------------------

def test_cargo_is_valued_from_its_file():
    from ngwart.engine.loaders import load

    program = load("programs/cargo/cargo.yaml")
    assert program.value_problems == []
    assert program.values_source.endswith("cargo-values.json")
    assert len(program.var_values) == 52          # 28 LEDs, 24 with a colour check

    sites, notes = cal.sites_from_program(program)
    assert notes == []
    assert len(sites) == 28
    assert sum(len(s.uses) for s in sites) == 100
    assert all(s.in_file for s in sites)
    # INTENSITY_G is the only one with a 5px window; the tolerance has to come
    # from each value, not from a default.
    assert sorted({s.tol for s in sites}) == [5.0, 10.0]


def test_every_cargo_coordinate_row_resolves_to_a_usable_spec():
    """The wiring from <Vars> through the values file to each verb.

    The one-time migration off literals was verified against the pre-refactor
    table at the time; git holds that. What is worth guarding from here on is
    that every row still resolves to a spec of the shape its verb expects --
    which is what breaks if someone renames a key or edits the file by hand.
    """
    from ngwart.engine.context import Context
    from ngwart.engine.loaders import load

    program = load("programs/cargo/cargo.yaml")
    assert program.value_problems == []

    ctx = Context(program, simulate=True)
    ctx.init_data(40, 3, 32)                      # seeds every <Vars> value

    sites, _ = cal.sites_from_program(program)
    by_row = {u.row: s for s in sites for u in s.uses}

    checked = 0
    for row in program.rows:
        verb = row.verb.upper()
        if verb not in cal.COORD_VERBS:
            continue
        site = by_row[row.index]
        fields = [f.strip() for f in ctx.text(row.raw(3)).split(",")]
        assert (int(fields[0]), int(fields[1])) == (site.cx, site.cy)
        # EVALLEDS wants four fields; the contour verbs five, or six with a
        # per-site noise floor.
        assert len(fields) in ((4,) if verb == "EVALLEDS" else (5, 6))
        assert all(f.replace(".", "").replace("-", "").isdigit() for f in fields)
        checked += 1
    assert checked == 100

def test_the_station_teaches_from_the_run_it_just_did(app, shifted):
    """The whole point of putting it in the station.

    A board whose optical tests all reported NOT_FOUND has already produced the
    evidence. Teaching reads the frame that failed rather than taking another.
    """
    from ngwart.ui.main_window import MainWindow

    dx, dy = shifted(45, 30)
    window = MainWindow(program_path="programs/demo/demo.yaml", simulate=True,
                        history_path="")
    assert not window.calibrate_last_action.isEnabled()      # nothing captured yet

    # The engine runs on a worker thread and reports through queued signals, so
    # the GUI thread has to actually sit in its event loop for them to arrive.
    from PySide6.QtCore import QEventLoop, QTimer

    def settle(ms=150):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    window.start_run()
    for _ in range(60):
        settle()
        if not window.is_running and window._last_ctx is not None:
            break
    assert window._last_ctx is not None
    assert window.calibrate_last_action.isEnabled()

    window._calibrate_from_last_run()
    teach_window = window._calibration_window
    assert teach_window is not None
    assert len(teach_window.sites) == 4
    assert len(teach_window.canvas.blobs) == 4     # the frame from that run

    site = teach_window.sites[0]
    blob = cal.blob_at(teach_window.capture.contours,
                         site.cx + dx, site.cy + dy)
    teach_window._select(0)
    teach_window._on_pick(blob.cx, blob.cy, blob.area)
    assert site.delta == (dx, dy)

    teach_window.close()
    window.close()


def test_the_record_never_overwrites_the_values_file(tmp_path):
    """They are both JSON beside the same table, so this is one slip away.

    The record is written second. Point it at the values file and every
    coordinate the program loads is gone, with the run that follows dying on a
    missing key.
    """
    program = build_valued(tmp_path, {"led.a.cont": "895,659,10,50,1",
                                      "led.a.leds": "895,659,10,50"})
    sites, _ = cal.sites_from_program(program)
    sites[0].teach(898, 662, area=1900.0)

    values_file = sites[0].file_path
    written = cal.save(values_file, sites, program=program)   # same path!

    assert written[0] == values_file
    assert written[1] != values_file
    # The values survived and are still loadable.
    assert cal.read_coords(values_file)["led.a.cont"] == "898,662,10,50,1"


def test_calibrations_are_discovered_from_their_own_meta():
    """A calibration declares itself; the station does not hold a list."""
    found = cal.calibrations(CAL_DIR)
    titles = {c.title for c in found}

    assert {"LEDs A-F", "Button LED (G)"} <= titles
    assert all(c.target.endswith("cargo.yaml") for c in found)
    for c in found:
        assert pathlib.Path(c.path).exists()


def test_each_calibration_is_one_exposure():
    """One frame per set of camera settings.

    A scene exposed for the bright indicators does not show the dim one, which
    is the whole reason these are two programs and not one with two frames.
    """
    from ngwart.engine.loaders import load

    settings = {}
    for c in cal.calibrations(CAL_DIR):
        program = load(c.path)
        stages = cal.contour_rows(program)
        assert len(stages) == 1, f"{c.title} should take exactly one frame"
        exposures = [r.raw(3) for r in program.rows
                     if r.verb.upper() == "SETEXPOSURE" and r.module]
        settings[c.title] = (exposures[0],
                             cal.find_capture(program).threshold)

    assert settings["LEDs A-F"] == ("120", 180.0)
    assert settings["Button LED (G)"] == ("20000", 100.0)


def test_a_calibration_powers_every_board_and_leaves_no_magnet_on():
    from ngwart.engine.loaders import load

    for c in cal.calibrations(CAL_DIR):
        program = load(c.path)
        assert not [r for r in program.rows if "EIMAN" in r.comment.upper()],             f"{c.title} energises the magnet"
        # Six relay closes: two positives per channel plus the shared returns.
        assert sum(1 for r in program.rows if ",43," in r.raw(3)) == 6
        assert program.has_teardown, f"{c.title} has no teardown"


def test_the_station_teaches_from_the_run_it_just_did(app, shifted):
    """The whole point of putting it in the station.

    A board whose optical tests all reported NOT_FOUND has already produced the
    evidence. Teaching reads the frame that failed rather than taking another.
    """
    from ngwart.ui.main_window import MainWindow

    dx, dy = shifted(45, 30)
    window = MainWindow(program_path="programs/demo/demo.yaml", simulate=True,
                        history_path="")
    assert not window.calibrate_last_action.isEnabled()      # nothing captured yet

    # The engine runs on a worker thread and reports through queued signals, so
    # the GUI thread has to actually sit in its event loop for them to arrive.
    from PySide6.QtCore import QEventLoop, QTimer

    def settle(ms=150):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    window.start_run()
    for _ in range(60):
        settle()
        if not window.is_running and window._last_ctx is not None:
            break
    assert window._last_ctx is not None
    assert window.calibrate_last_action.isEnabled()

    window._calibrate_from_last_run()
    teach_window = window._calibration_window
    assert teach_window is not None
    assert len(teach_window.sites) == 4
    assert len(teach_window.canvas.blobs) == 4     # the frame from that run

    site = teach_window.sites[0]
    blob = cal.blob_at(teach_window.capture.contours,
                         site.cx + dx, site.cy + dy)
    teach_window._select(0)
    teach_window._on_pick(blob.cx, blob.cy, blob.area)
    assert site.delta == (dx, dy)

    teach_window.close()
    window.close()


def test_the_station_offers_each_calibration_and_runs_it(app):
    """Open the app, pick a calibration, click. Nothing is loaded first.

    The simulated camera draws its discs at BGR (60,220,90), which is grey ~163
    -- below cargo's threshold of 180 -- so a simulated calibration finds no
    contours. That is correct behaviour, so this checks the wiring around it
    rather than the clicking, which the drift tests cover.
    """
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(simulate=True, history_path="")     # no program at all
    titles = [a.text().rstrip("…")
              for a in window.calibrate_menu.actions() if a.isEnabled()]
    assert "LEDs A-F" in titles
    assert "Button LED (G)" in titles

    from PySide6.QtCore import QEventLoop, QTimer

    def settle(ms=150):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    calibration = next(c for c in window._calibrations if c.title == "LEDs A-F")
    window._start_calibration(calibration)
    for _ in range(60):
        settle()
        if not window.is_running and window._calibration is None:
            break

    assert window._calibration is None, "the calibration never finished"
    # A calibration is not a board: it gets its own banner, never a verdict.
    assert "CALIBRAT" in window.banner.text().upper()
    # It opened the canvas against cargo.yaml, whatever the frame held.
    assert window._calibration_window is not None
    assert len(window._calibration_window.sites) == 28

    if window._calibration_window is not None:
        window._calibration_window.close()
    window.close()


def test_a_capture_frame_is_found_whatever_the_working_directory():
    """CAPTURE saves relative to the process directory; a run may not be there.

    Getting this wrong showed up only as an empty canvas saying "no capture",
    with the image sitting on disk the whole time.
    """
    from ngwart.engine.loaders import load

    program = load("programs/cargo_cal_leds.yaml")
    for workdir in (".", "programs", "tests"):
        result = cal.run_capture(program, simulate=True, workdir=workdir)
        assert result.frame is not None, f"no frame with workdir={workdir!r}"
        assert result.frame.ndim == 3
        assert result.binary is not None, f"no binary with workdir={workdir!r}"


# --- a calibration covers only what its frame can show ------------------

def test_each_calibration_claims_its_own_sites():
    """A-F and G need different exposures, so they are different jobs.

    Listing all 28 in either window gives an operator no way to tell "not
    clicked yet" from "not visible in this frame", and the untaught count never
    reaches zero.
    """
    from ngwart.engine.loaders import load

    sites, _ = cal.sites_from_program(load("programs/cargo/cargo.yaml"))
    by_title = {c.title: c for c in cal.calibrations(CAL_DIR)}

    af = by_title["LEDs A-F"].select(sites)
    g = by_title["Button LED (G)"].select(sites)

    assert len(af) == 24
    assert len(g) == 4
    assert {t for s in g for t in s.tests} == {"INTENSITY_G"}
    assert "INTENSITY_G" not in {t for s in af for t in s.tests}
    # Between them they cover the table exactly once.
    assert len(af) + len(g) == len(sites)
    assert not ({id(s) for s in af} & {id(s) for s in g})


def test_calibrating_one_group_leaves_the_others_alone(tmp_path):
    """The failure this guards against loses half a fixture's geometry.

    A calibration window holds a subset, so writing only that subset would
    delete every other key -- and the next run aborts on the first missing one,
    at load, with no coordinates left to recover from.
    """
    import json as _json
    import shutil

    from ngwart.engine.loaders import load

    values = tmp_path / "cargo-values.json"
    shutil.copy("programs/cargo/cargo-values.json", values)
    before = _json.loads(values.read_text())

    sites, _ = cal.sites_from_program(load("programs/cargo/cargo.yaml"))
    for site in sites:
        site.file_path = str(values)

    af = next(c for c in cal.calibrations(CAL_DIR)
              if c.title == "LEDs A-F").select(sites)
    for site in af:
        site.teach(site.cx + 4, site.cy + 3, area=1900.0)
    cal.write_coords(str(values), af)

    after = _json.loads(values.read_text())
    assert set(after) >= set(before), "keys were dropped"
    assert after["led.u0.a.cont"] == "899,662,10,50,1"      # moved
    assert after["led.u0.g.cont"] == before["led.u0.g.cont"]  # untouched


def test_a_calibration_without_a_sites_pattern_takes_everything():
    """Omitting `sites:` keeps the old behaviour rather than silently hiding."""
    everything = cal.Calibration(path="x", title="all", target="y")
    site = cal.Site(uut=0, cx=1, cy=2, tol=10, file_key="anything")
    assert everything.covers(site)


# --- a looping fixture judges the board in front of it ------------------

def test_a_verdict_is_about_the_current_board_not_the_run():
    """cargo's table loops, so one run holds many boards.

    Reported from the bench: a unit with 28 passes still showed FAIL. It had
    failed two boards earlier, and VALIDATE read every point the run had ever
    recorded.
    """
    from ngwart.engine.runrecord import RunRecord, TestPoint

    record = RunRecord(program_name="cargo")

    record.begin_cycle()                       # board 1: this one really failed
    record.add_point(TestPoint(name="INTENSITY_G", uut=0, result="FAIL",
                               measured="NOT_FOUND"))
    for i in range(27):
        record.add_point(TestPoint(name=f"T{i}", uut=0, result="PASS"))

    record.begin_cycle()                       # board 2: a good one
    for i in range(28):
        record.add_point(TestPoint(name=f"T{i}", uut=0, result="PASS"))

    current = record.points_for(0, this_cycle=True)
    assert len(current) == 28
    assert not [p for p in current if p.result == "FAIL"]

    # The whole run still holds both boards -- reports and history want that.
    everything = record.points_for(0)
    assert len(everything) == 56
    assert len([p for p in everything if p.result == "FAIL"]) == 1


def test_startalive_opens_a_new_board():
    """It is what a looping table runs at the top of each pass."""
    from ngwart.engine import REGISTRY
    from ngwart.engine.context import Context
    from ngwart.engine.runrecord import RunRecord, TestPoint

    program = build(exec=[["TestData", "STARTALIVE"]])
    ctx = Context(program, simulate=True)
    ctx.init_alive(2)
    ctx.record = RunRecord(program_name="t")
    ctx.record.add_point(TestPoint(name="old", uut=0, result="FAIL"))

    row = next(program.rows[i] for i in program.body("Exec")
               if program.rows[i].verb == "STARTALIVE")
    REGISTRY.require("TestData", "STARTALIVE").fn(ctx, row)

    assert ctx.record.points_for(0, this_cycle=True) == []
    assert len(ctx.record.points_for(0)) == 1


def test_evalleds_stores_its_verdict_not_just_the_colour():
    """It decides PASS/FAIL and can kill a unit, so it has to record it.

    cargo names one destination cell; zipping three values against it wrote the
    colour and dropped the rest, leaving 43 result cells reading '-' in a log
    where every one had been decided.
    """
    import numpy as np

    from ngwart.engine import REGISTRY
    from ngwart.engine.context import Context
    from ngwart.engine.runrecord import RunRecord

    program = build(
        vars={"img": "0,0,0", "res": "6,0,1"},
        exec=[["Vision", "EVALLEDS", "*img", "128,120,20,50", "res",
               "60,220,90", "0,COLOR_A"]])
    ctx = Context(program, simulate=True)
    ctx.init_data(40, 3, 32)
    ctx.init_alive(1)
    ctx.record = RunRecord(program_name="t")

    frame = np.zeros((240, 320, 3), np.uint8)
    cv2.circle(frame, (128, 120), 18, (60, 220, 90), -1)
    ctx.set_data("img", frame, stringify=False)

    row = next(program.rows[i] for i in program.body("Exec")
               if program.rows[i].verb == "EVALLEDS")
    REGISTRY.require("ImageProcessManager", "EVALLEDS").fn(ctx, row)

    assert ctx.get_data("6,1,1") == "PASS"      # the verdict, not '-'
    assert ctx.get_data("6,2,1") == "COLOR_A"   # and the test id


# --- a calibration that measures rather than asks ------------------------

def test_the_white_balance_calibration_declares_what_it_captures():
    by_title = {c.title: c for c in cal.calibrations(CAL_DIR)}
    wb = by_title["White balance"]

    assert wb.measures == ["cam.wb"]
    assert not wb.sites, "a measuring calibration has nothing to click"
    # The others teach coordinates and measure nothing.
    assert all(not c.measures for t, c in by_title.items() if t != "White balance")


def test_the_white_balance_capture_lights_the_board_before_measuring():
    """The whole point: CALIBRATEWB neutralises whatever is in view.

    Run against a bare fixture it reads the solder mask as a cast and pulls
    green down. The indicators have to be lit before it fires.
    """
    from ngwart.engine.loaders import load

    wb = next(c for c in cal.calibrations(CAL_DIR) if c.measures)
    program = load(wb.path)
    body = list(program.body("Exec"))

    def first(verb):
        return next(i for i in body if program.rows[i].verb.upper() == verb)

    power = max(i for i in body if ",43," in program.rows[i].raw(3))
    assert power < first("CALIBRATEWB"), "calibrates before the board is lit"
    assert first("CALIBRATEWB") < first("GETWB")
    # And it is not left in <Config>, where nothing is powered yet.
    assert not [i for i in program.body("Config")
                if program.rows[i].verb.upper() == "CALIBRATEWB"]


def test_measured_values_merge_without_losing_the_coordinates(tmp_path):
    """One calibration must not delete what another taught."""
    import json as _json
    import shutil

    values = tmp_path / "cargo-values.json"
    shutil.copy("programs/cargo/cargo-values.json", values)
    before = {k: v for k, v in _json.loads(values.read_text()).items()
              if not k.startswith("_")}

    cal.write_values(str(values), {"cam.wb": "2.0000,1.0000,1.9000"})

    after = {k: v for k, v in _json.loads(values.read_text()).items()
             if not k.startswith("_")}
    assert set(after) == set(before)
    assert after["cam.wb"] == "2.0000,1.0000,1.9000"
    assert after["led.u0.a.cont"] == before["led.u0.a.cont"]


def test_cargo_applies_the_stored_gains_instead_of_recalibrating():
    from ngwart.engine import REGISTRY
    from ngwart.engine.context import Context
    from ngwart.engine.loaders import load

    program = load("programs/cargo/cargo.yaml")
    assert program.value_problems == []
    assert "cam.wb" in program.var_values

    config = list(program.body("Config"))
    verbs = [program.rows[i].verb.upper() for i in config]
    assert "SETWB" in verbs
    assert "CALIBRATEWB" not in verbs, "config has nothing lit to calibrate on"

    ctx = Context(program, simulate=True)
    ctx.init_data(40, 3, 32)
    for i in config:
        row = program.rows[i]
        if row.module == "Camera" and row.verb.upper() in ("OPENALL", "SETPROPS",
                                                           "SETWB"):
            REGISTRY.require("BaluffManager", row.verb).fn(ctx, row)

    camera = list(ctx.store["camera"]["cameras"].values())[0]
    expected = tuple(float(x) for x in program.var_values["cam.wb"].split(","))
    assert camera.white_balance_gains() == expected


def test_getwb_writes_what_setwb_reads():
    """Same shape both ways, so nothing reformats between measure and apply."""
    from ngwart.engine import REGISTRY
    from ngwart.engine.context import Context

    program = build(
        vars={"wb": "0,0,0"},
        config=[["Camera", "OPENALL"]],
        exec=[["Camera", "SETWB", "UB101256", "2.5,1.0,1.75"],
              ["Camera", "GETWB", "UB101256", "wb"]])
    ctx = Context(program, simulate=True)
    ctx.init_data(10, 3, 3)
    for section in ("Config", "Exec"):
        for i in program.body(section):
            row = program.rows[i]
            if row.module == "Camera":
                REGISTRY.require("BaluffManager", row.verb).fn(ctx, row)

    assert ctx.get_data("wb") == "2.5000,1.0000,1.7500"


# --- who measured what ---------------------------------------------------

def test_provenance_attributes_every_value_without_flooding_the_file(tmp_path):
    """Grouped by calibration, not nested under each value.

    Nesting would triple a file the program has to read as a flat map, and
    grow with every coordinate. A run is described once and its keys listed on
    one line, so four values and four hundred cost the same few lines.
    """
    import json as _json
    import shutil

    values = tmp_path / "cargo-values.json"
    shutil.copy("programs/cargo/cargo-values.json", values)
    before_lines = len(values.read_text().splitlines())

    cal.write_values(str(values), {"cam.wb": "2.0,1.0,1.9"},
                     meta={"calibration": "White balance", "station": "BENCH1"})
    doc = _json.loads(values.read_text())

    book = doc[cal.PROVENANCE]
    assert "White balance" in book
    assert book["White balance"]["keys"] == "cam.wb"
    assert book["White balance"]["station"] == "BENCH1"
    # The values themselves stay a flat name -> string map.
    assert isinstance(doc["cam.wb"], str)
    assert len(values.read_text().splitlines()) - before_lines < 12


def test_a_re_run_replaces_its_own_attribution(tmp_path):
    import json as _json

    values = tmp_path / "v.json"
    cal.write_values(str(values), {"a": "1", "b": "2"},
                     meta={"calibration": "First"})
    cal.write_values(str(values), {"a": "9"}, meta={"calibration": "First"})

    book = _json.loads(values.read_text())[cal.PROVENANCE]
    assert list(book) == ["First"]
    assert sorted(book["First"]["keys"].split()) == ["a"]


def test_a_key_moves_to_whoever_measured_it_last(tmp_path):
    """Otherwise an old group keeps claiming values it no longer produced."""
    import json as _json

    values = tmp_path / "v.json"
    cal.write_values(str(values), {"a": "1", "b": "2"},
                     meta={"calibration": "Wide"})
    cal.write_values(str(values), {"a": "9"}, meta={"calibration": "Narrow"})

    book = _json.loads(values.read_text())[cal.PROVENANCE]
    assert book["Wide"]["keys"] == "b"
    assert book["Narrow"]["keys"] == "a"
    claimed = [k for e in book.values() for k in e["keys"].split()]
    assert sorted(claimed) == ["a", "b"], "a value is claimed twice or not at all"


def test_an_older_stamp_is_dropped_rather_than_carried(tmp_path):
    """The file used to carry one whole-file _teach block. It is not kept."""
    import json as _json

    values = tmp_path / "v.json"
    values.write_text(_json.dumps({"a": "1", "_teach": {"written_by": "old"}}))

    cal.write_values(str(values), {"a": "2"}, meta={"calibration": "Now"})
    doc = _json.loads(values.read_text())

    assert "_teach" not in doc
    assert set(k for k in doc if k.startswith("_")) == {cal.PROVENANCE}


# --- calibrations belong to a product ------------------------------------

def test_calibrations_are_found_one_folder_per_product():
    """As programs/ is laid out, so a second product has its own folder."""
    found = cal.calibrations(CAL_DIR)
    assert found, "nothing discovered"
    for c in found:
        product = pathlib.Path(c.path).parent.name
        assert product != "calibration", f"{c.title} is loose in the root"
        assert product in c.target.replace("\\", "/"), \
            f"{c.title} sits under {product} but calibrates {c.target}"


def test_only_the_loaded_program_is_offered():
    """Another product's would power a fixture for a board that is not on it,
    and write into a values file the loaded program never reads."""
    from ngwart.engine.loaders import load

    cargo = load("programs/cargo/cargo.yaml")
    demo = load("programs/demo/demo.yaml")

    for_cargo = cal.calibrations_for(CAL_DIR, cargo)
    assert {c.title for c in for_cargo} == {
        "LEDs A-F", "Button LED - UUT 1+2", "Button LED - UUT 3+4",
        "White balance"}
    assert cal.calibrations_for(CAL_DIR, demo) == []
    # With nothing loaded each one still loads its own target, so all are valid.
    assert len(cal.calibrations_for(CAL_DIR, None)) == len(cal.calibrations(CAL_DIR))


def test_the_menu_follows_the_loaded_program(app):
    from ngwart.ui.main_window import MainWindow

    def offered(window):
        return [a.text().rstrip("…")
                for a in window.calibrate_menu.actions() if a.isEnabled()]

    window = MainWindow(simulate=True, history_path="")
    window.open_program("programs/demo/demo.yaml")
    assert offered(window) == []

    window.open_program("programs/cargo/cargo.yaml")
    assert "White balance" in offered(window)

    window.open_program("programs/demo/demo.yaml")
    assert offered(window) == [], "cargo's calibrations survived a program change"
    window.close()


def test_a_declared_value_is_readable_before_initdata(tmp_path):
    """<Config> runs before INITDATA and legitimately reads these.

    cargo applies its stored white-balance gains there -- the one place a
    camera can be set up before anything is powered. Without this the run
    aborted at the SETWB row with "data store not initialised".
    """
    from ngwart.engine.context import Context
    from ngwart.engine.errors import VerbError

    program = build_valued(tmp_path, {"led.a.cont": "895,659,10,50,1",
                                      "led.a.leds": "895,659,10,50"})
    ctx = Context(program, simulate=True)
    assert ctx.data is None
    assert ctx.text("*led.a.cont") == "895,659,10,50,1"

    # A variable with no declared value, and a bare coordinate, still say so.
    for ref in ("*c", "*1,0,0"):
        with pytest.raises(VerbError, match="not initialised"):
            ctx.text(ref)

    # Once the store exists it is the truth: a value written there wins over
    # the declaration, or nothing a step wrote would ever be read back.
    ctx.init_data(40, 3, 32)
    assert ctx.text("*led.a.cont") == "895,659,10,50,1"
    ctx.set_data("led.a.cont", "1,2,3,4,5")
    assert ctx.text("*led.a.cont") == "1,2,3,4,5"


def test_cargo_config_runs_to_the_end():
    """The whole block, in order, as a run does it."""
    from ngwart.engine import REGISTRY
    from ngwart.engine.context import Context
    from ngwart.engine.loaders import load

    program = load("programs/cargo/cargo.yaml")
    ctx = Context(program, simulate=True)

    for i in program.body("Config"):
        row = program.rows[i]
        if not row.module or not row.verb:
            continue
        module = program.modules.get(row.module, row.module)
        REGISTRY.require(module, row.verb).fn(ctx, row)

    camera = list(ctx.store["camera"]["cameras"].values())[0]
    expected = tuple(float(x)
                     for x in program.var_values["cam.wb"].split(","))
    assert camera.white_balance_gains() == expected


# --- holding the fixture while the camera is adjusted --------------------

def test_the_camera_tool_holds_the_fixture():
    """Aiming and focusing need the board lit and the frame re-taken.

    A capture that powers up, shoots once and tears down is no use: by the time
    the frame is on screen the indicators are dark.
    """
    from ngwart.engine.loaders import load

    holding = [c for c in cal.calibrations(CAL_DIR) if c.holds]
    assert len(holding) == 1
    tool = holding[0]
    assert tool.title == "Camera position and focus"
    assert not tool.measures and not tool.sites, "it produces no values"

    # It can re-take a picture without powering anything a second time.
    program = load(tool.path)
    rows = cal.refresh_rows(program)
    verbs = [program.rows[i].verb.upper() for i in rows]
    assert "CAPTURE" in verbs
    assert any(v.endswith("2CONT") for v in verbs)
    assert not [v for v in verbs if v == "EXCHANGEBYTES_LVS"], \
        "a re-capture must not touch the relays"


def test_sharpness_rises_with_focus():
    """The number an operator turns the ring against."""
    import numpy as np

    sharp = np.zeros((200, 200), np.uint8)
    cv2.circle(sharp, (100, 100), 40, 255, -1)
    blurred = cv2.GaussianBlur(sharp, (31, 31), 0)

    assert cal.sharpness(sharp) > cal.sharpness(blurred)
    assert cal.sharpness(None) == 0.0


def test_the_focus_window_powers_down_when_closed(app):
    """Closing the window is not a reason to leave a supply at 13.5 V."""
    from ngwart.ui.focus_window import FocusWindow

    powered = [True]
    window = FocusWindow("Camera position and focus")
    window.on_done = lambda: powered.__setitem__(0, False)

    window.close()
    assert powered[0] is False


def test_calibrations_are_grouped_by_product_in_the_menu(app):
    from ngwart.ui.main_window import MainWindow

    window = MainWindow(program_path="programs/cargo/cargo.yaml",
                        simulate=True, history_path="")
    groups = {a.text(): a.menu() for a in window.calibrate_menu.actions()
              if a.menu() is not None}
    assert groups, "calibrations are not grouped"

    # The loaded product is first and says so.
    first = list(groups)[0]
    assert first.startswith("cargo") and "loaded" in first
    titles = [a.text().rstrip("…") for a in groups[first].actions()]
    assert "Camera position and focus" in titles
    assert "White balance" in titles
    window.close()


def test_the_camera_tool_streams_at_the_test_exposure(app):
    """What is on screen while the lens is turned must be what the test sees."""
    from ngwart.engine.loaders import load
    from ngwart.ui.main_window import MainWindow

    tool = next(c for c in cal.calibrations(CAL_DIR) if c.holds)
    program = load(tool.path)

    window = MainWindow(simulate=True, history_path="")
    assert window._program_exposure(program) == 120.0
    assert cal.find_capture(program).threshold == 180.0
    window.close()


def test_the_streamer_stops_before_anything_else_touches_the_camera(app):
    """Teardown restores the exposure; two threads on one camera is a crash."""
    from ngwart.drivers.backends.sim import SimCamera
    from ngwart.ui.focus_window import FocusWindow

    camera = SimCamera("SIM", width=320, height=240)
    camera.open()

    window = FocusWindow("Camera position and focus")
    window.start_stream(camera, exposure_us=120.0, threshold=180.0)
    assert window._streamer is not None and window._streamer.isRunning()

    window.stop_stream()
    assert window._streamer is None
    window.close()


def test_a_dropped_frame_does_not_end_the_stream(app):
    """A camera being physically handled drops frames -- which is exactly when
    this window is in use."""
    from ngwart.ui.focus_window import FrameStreamer

    class Flaky:
        def __init__(self):
            self.calls = 0

        def set_exposure(self, us):
            return us

        def capture(self):
            self.calls += 1
            raise OSError("dropped")

    camera = Flaky()
    streamer = FrameStreamer(camera, 120.0, 180.0, interval_s=0.01)
    problems = []
    streamer.failed.connect(problems.append)
    streamer.start()

    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(1200, loop.quit)
    loop.exec()
    streamer.stop()

    assert camera.calls > 1, "the stream gave up after one bad grab"
    assert problems, "the failure was never reported"


def test_streaming_never_runs_without_a_camera(app):
    from ngwart.ui.focus_window import FocusWindow

    window = FocusWindow("Camera position and focus")
    window.start_stream(None, exposure_us=120.0, threshold=180.0)
    assert window._streamer is None
    assert "No camera" in window.status.text()
    window.close()
