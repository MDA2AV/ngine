"""Image-processing verbs -- registered as ``ImageProcessManager``.

The nine colour-conversion verbs (RGB2GRAY, BGR2GRAY, GRAY2BIN, RGB2BIN,
BGR2BIN, BIN2CONT, GRAY2CONT, BGR2CONT, RGB2CONT) are one pipeline with a
source colourspace and a target stage. Written once, registered nine times.

Every verb takes its input either from a data cell (column 2) or from a file
(column 3), and writes to a data cell (column 4), a file (column 5), or both --
the same convention v1 used.

The *2CONT verbs bend it in the one way v1 did: column 4 holds the contours,
so column 5 saves the thresholded frame the contours came from rather than the
column-4 value.
"""

from __future__ import annotations

import functools
import os

from ..engine.errors import VerbError
from ..engine.events import FrameEvent, GridEvent
from ..engine.registry import REGISTRY, Param, VerbSpec, p, verb
from ..engine.runrecord import TestPoint

MODULE = "ImageProcessManager"

#: EVALLEDS clustering parameters, carried over from v1 unchanged. They were
#: tuned against real boards; changing them silently shifts every LED limit.
LED_CLUSTERS = 3
LED_TOLERANCE = 30

#: Contours smaller than this are noise and never considered. v1's value.
MIN_CONTOUR_PIXELS = 50


def _cv2():
    try:
        import cv2
        return cv2
    except ImportError as exc:
        raise VerbError(
            "image processing needs OpenCV -- pip install opencv-python"
        ) from exc


def _np():
    try:
        import numpy as np
        return np
    except ImportError as exc:
        raise VerbError("image processing needs numpy -- pip install numpy") from exc


def _load(ctx, row, data_col: int = 2, path_col: int = 3):
    """Take the image from a data cell or from disk."""
    if row.has(data_col):
        image = ctx.content(row.raw(data_col))
        if image is None:
            raise VerbError(f"{row.verb}: {row.raw(data_col)} holds no image")
        return image
    if row.has(path_col):
        cv2 = _cv2()
        path = ctx.text(row.raw(path_col))
        image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if image is None:
            raise VerbError(f"{row.verb}: cannot read image '{path}'")
        return image
    raise VerbError(f"{row.verb}: give an image index (column {data_col}) "
                    f"or a path (column {path_col})")


def _write(ctx, row, image, path_col: int) -> None:
    """Write an image to the path named by a column, creating its directory.

    cv2.imwrite reports a missing directory or an unwritable path by returning
    False, not by raising -- unchecked, a table asking for saved frames just
    quietly produces none.
    """
    path = ctx.text(row.raw(path_col))
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    if not _cv2().imwrite(path, image):
        raise VerbError(f"{row.verb}: could not write '{path}'")
    ctx.log(f"{row.verb}: saved {path}")


def _emit(ctx, row, image, data_col: int = 4, path_col: int = 5) -> None:
    """Store the result wherever the row asked for it."""
    wrote = False
    if row.has(data_col):
        ctx.set_data(row.raw(data_col), image, stringify=False)
        wrote = True
    if row.has(path_col):
        _write(ctx, row, image, path_col)
        wrote = True
    if not wrote:
        raise VerbError(f"{row.verb}: give a destination index (column {data_col}) "
                        f"or a save path (column {path_col})")


# --- the conversion pipeline -------------------------------------------

def _convert(ctx, row, *, source: str, stage: str) -> None:
    cv2 = _cv2()
    image = _load(ctx, row)

    grey = image
    if stage in ("gray", "bin", "cont"):
        if source == "rgb":
            grey = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        elif source == "bgr":
            grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        elif source == "gray" and image.ndim == 3:
            grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    if stage == "gray":
        _emit(ctx, row, grey)
        return

    threshold = None
    if stage in ("bin", "cont"):
        if source == "bin":
            binary = grey
        else:
            threshold = 127.0
            if row.has(6):
                try:
                    threshold = float(ctx.text(row.raw(6)))
                except ValueError:
                    raise VerbError(
                        f"{row.verb}: threshold '{row.raw(6)}' is not a number") from None
            _, binary = cv2.threshold(grey, threshold, 255, cv2.THRESH_BINARY)

    if stage == "bin":
        _emit(ctx, row, binary)
        return

    # A *2CONT row spends column 4 on the contours, so column 5 is the only
    # place left to ask for the thresholded frame -- that is what fills a
    # program's Binary_Captures directory, and how an operator sees what the
    # threshold actually produced. Written before findContours so the frame
    # lands even when contour extraction is what fails.
    if row.has(5):
        _write(ctx, row, binary, 5)

    # Show the operator what the threshold produced, before the contours are
    # traced from it. This is the frame the verdicts are about.
    ctx.emit(FrameEvent(image=binary, kind="binary", units=row.alive,
                        row=row.index, label=row.comment or row.verb))

    contours, _ = cv2.findContours(binary.astype(_np().uint8), cv2.RETR_TREE,
                                   cv2.CHAIN_APPROX_NONE)
    ctx.log(f"{row.verb}: {len(contours)} contour(s) found "
            f"(threshold {threshold}, frame {image.shape[1]}x{image.shape[0]})")
    if ctx.debug:
        ctx.debug.save_image(f"{row.verb}_source", image, row.index)
        ctx.debug.save_image(f"{row.verb}_binary", binary, row.index)
        ctx.debug.save_contours(f"{row.verb}_contours", image, contours, row.index)
        ctx.debug.save_json(f"contours_row{row.index}.json",
                            ctx.debug.describe_contours(contours))
        ctx.debug.note(f"row {row.index} {row.verb}: threshold={threshold} "
                       f"frame={image.shape} contours={len(contours)}")
    if not row.has(4):
        raise VerbError(f"{row.verb}: column 4 must name where to store the contours")
    ctx.set_data(row.raw(4), list(contours), stringify=False)


_CONV_PARAMS = (
    Param(2, "image_index", False, "source image held in the data store"),
    Param(3, "image_path", False, "source image on disk"),
    Param(4, "dest_index", False, "result, or the contours for a *2CONT verb"),
    Param(5, "save_path", False, "file to save the result to; for a *2CONT "
                                 "verb, the thresholded frame"),
    Param(6, "threshold", False, "binary threshold, default 127"),
)

for _name, _source, _stage in (
    ("RGB2GRAY", "rgb", "gray"), ("BGR2GRAY", "bgr", "gray"),
    ("GRAY2BIN", "gray", "bin"), ("RGB2BIN", "rgb", "bin"), ("BGR2BIN", "bgr", "bin"),
    ("BIN2CONT", "bin", "cont"), ("GRAY2CONT", "gray", "cont"),
    ("BGR2CONT", "bgr", "cont"), ("RGB2CONT", "rgb", "cont"),
):
    REGISTRY.add(VerbSpec(
        module=MODULE, name=_name,
        fn=functools.partial(_convert, source=_source, stage=_stage),
        params=_CONV_PARAMS,
        doc=f"Convert {_source.upper()} to {_stage.upper()}.",
    ))


# --- contour measurement ------------------------------------------------

def _centroid(cv2, contour):
    m = cv2.moments(contour)
    if m["m00"] == 0:
        return None
    return m["m10"] / m["m00"], m["m01"] / m["m00"]


def _find_at(cv2, contours, cx: float, cy: float, tol: float, cal: float = 1.0,
             noise: float | None = None):
    """Largest in-window contour above the noise floor.

    Matches v1's ``_detect_contour_at``. Two details matter and are not
    interchangeable with "nearest":

    * Selection is by **area**, not proximity. An area test wants the blob it is
      measuring, and a stray speck closer to the nominal centre would otherwise
      win and fail the limit.
    * Contours smaller than the noise floor are never considered.

    ``noise`` overrides MIN_CONTOUR_PIXELS for one site. It exists because one
    floor does not fit every indicator: cargo's button LED is a far smaller blob
    than its bar indicators, and at the shared 50 px floor it is invisible --
    so an EVALCONTN on it finds nothing and passes, whatever is actually lit.
    Omitted, the constant applies and behaviour is unchanged.

    Returns (area_calibrated, centroid) or (None, None).
    """
    floor = MIN_CONTOUR_PIXELS if noise is None else noise
    if contours is None:
        contours = []

    min_cx, min_cy = max(0, cx - tol), max(0, cy - tol)
    max_cx, max_cy = cx + tol, cy + tol

    best_area, best_centroid = None, None
    for contour in contours:
        raw = cv2.contourArea(contour)
        if raw < floor:
            continue
        moments = cv2.moments(contour)
        if moments["m00"] == 0:
            continue
        _cx = int(moments["m10"] / moments["m00"])
        _cy = int(moments["m01"] / moments["m00"])
        if not (min_cx <= _cx <= max_cx and min_cy <= _cy <= max_cy):
            continue
        area = raw * cal
        if best_area is None or area > best_area:
            best_area, best_centroid = area, (_cx, _cy)
    return best_area, best_centroid


@verb(MODULE, "MEASCONT", params=[p(2, "contours"), p(3, "target", doc="cx,cy,tol"),
                                  p(4, "dest")])
def meascont(ctx, row):
    """Store the calibrated area of the contour at (cx, cy)."""
    cv2 = _cv2()
    contours = ctx.content(row.raw(2)) or []
    cx, cy, tol = _floats(ctx, row.raw(3), 3, "MEASCONT")
    area, _ = _find_at(cv2, contours, cx, cy, tol)
    area = area if area is not None else 0.0
    ctx.log(f"MEASCONT at ({cx}, {cy}): area {area}")
    ctx.set_data(row.raw(4), area)


def _noise_floor(ctx, cell: str) -> float | None:
    """Optional sixth field of a contour spec: this site's noise floor.

    ``cx,cy,tol,minarea,cal[,noise]``. Absent means MIN_CONTOUR_PIXELS, so every
    row written before this existed behaves exactly as it did.

    One floor does not fit every indicator. cargo's button LED is a far smaller
    blob than its bar indicators, and at the shared 50 px floor it is invisible
    -- so an EVALCONTN on it finds nothing and passes, whatever is lit.
    """
    parts = [x.strip() for x in str(ctx.text(cell)).split(",") if x.strip()]
    if len(parts) < 6:
        return None
    try:
        return float(parts[5])
    except ValueError:
        raise VerbError(
            f"noise floor '{parts[5]}' is not a number (spec field 6)") from None


@verb(MODULE, "EVALCONT",
      params=[p(2, "contours"),
              p(3, "spec", doc="cx,cy,tol,minarea,cal[,noise]"),
              p(4, "dest"), p(5, "grid_style", required=False, doc="'min' or blank"),
              p(6, "kill_and_id", doc="kill_index,test_id")])
def evalcont(ctx, row):
    """Pass when a large enough contour sits at (cx, cy)."""
    cv2 = _cv2()
    contours = ctx.content(row.raw(2)) or []
    cx, cy, tol, minarea, cal = _floats(ctx, row.raw(3), 5, "EVALCONT")
    noise = _noise_floor(ctx, row.raw(3))
    kill_index, test_id = _kill_and_id(ctx, row)

    area, centroid = _find_at(cv2, contours, cx, cy, tol, cal, noise)
    found = area is not None
    if ctx.debug:
        near = [d for d in ctx.debug.describe_contours(contours, cal)
                if d["centroid"] and abs(d["centroid"][0] - cx) < tol * 8
                and abs(d["centroid"][1] - cy) < tol * 8]
        ctx.debug.save_json(f"evalcont_row{row.index}_{test_id}.json", {
            "target": {"cx": cx, "cy": cy, "tol": tol,
                       "minarea": minarea, "cal": cal},
            "found": found, "area": area, "centroid": centroid,
            "noise_floor": MIN_CONTOUR_PIXELS if noise is None else noise,
            "contours_total": len(contours),
            "contours_near_target": near,
        })
        ctx.debug.note(
            f"row {row.index} {test_id}: window ({cx},{cy})+/-{tol} "
            f"-> {'area ' + str(area) if found else 'NOT FOUND'}; "
            f"{len(near)} contour(s) nearby")
    if found:
        ctx.log(f"{test_id}: contour at {centroid}, calibrated area {area}")
    else:
        ctx.log(f"{test_id}: no contour within {tol}px of ({cx}, {cy})", "warn")

    result = "PASS" if found and area > minarea else "FAIL"
    measured = area if found else "NOT_FOUND"
    _publish(ctx, row, kill_index, test_id, result, measured, minarea)
    _store_triplet(ctx, row, measured, result, test_id)


@verb(MODULE, "EVALCONTN",
      params=[p(2, "contours"), p(3, "spec", doc="cx,cy,tol,minarea,cal[,noise]"),
              p(4, "dest"), p(5, "grid_style", required=False),
              p(6, "kill_and_id")])
def evalcontn(ctx, row):
    """Inverse of EVALCONT: pass when nothing is present at (cx, cy)."""
    cv2 = _cv2()
    contours = ctx.content(row.raw(2)) or []
    cx, cy, tol, minarea, cal = _floats(ctx, row.raw(3), 5, "EVALCONTN")
    noise = _noise_floor(ctx, row.raw(3))
    kill_index, test_id = _kill_and_id(ctx, row)

    area, _ = _find_at(cv2, contours, cx, cy, tol, cal, noise)
    result = "PASS" if area is None or area <= minarea else "FAIL"
    measured = area if area is not None else "NOT_FOUND"
    _publish(ctx, row, kill_index, test_id, result, measured, minarea)
    _store_triplet(ctx, row, measured, result, test_id)


@verb(MODULE, "EVALCONTS",
      params=[p(2, "contours"), p(3, "cx_list"), p(4, "cy_list"),
              p(5, "tol"), p(6, "minarea_list")])
def evalconts(ctx, row):
    """Evaluate a whole row of contour sites at once."""
    cv2 = _cv2()
    contours = ctx.content(row.raw(2)) or []
    xs = _float_list(ctx, row.raw(3), "EVALCONTS cx")
    ys = _float_list(ctx, row.raw(4), "EVALCONTS cy")
    areas = _float_list(ctx, row.raw(6), "EVALCONTS minarea")
    tol = float(ctx.text(row.raw(5)) or 0)
    if not (len(xs) == len(ys) == len(areas)):
        raise VerbError(
            f"EVALCONTS: {len(xs)} x-values, {len(ys)} y-values and "
            f"{len(areas)} minimum areas -- these must match")

    results = []
    for i, (cx, cy, minarea) in enumerate(zip(xs, ys, areas)):
        area, _ = _find_at(cv2, contours, cx, cy, tol)
        ok = area is not None and area > minarea
        area = area if area is not None else 0.0
        results.append("PASS" if ok else "FAIL")
        ctx.log(f"EVALCONTS[{i}] at ({cx}, {cy}): area {area} -> {results[-1]}",
                "pass" if ok else "fail")
    ctx.set_data(row.raw(2) if not row.has(4) else row.raw(4), ";".join(results))


@verb(MODULE, "EVALLEDS",
      params=[p(2, "image", doc="path or image held in the data store"),
              p(3, "leds", doc="'x,y,crop_radius,threshold;...' one group per LED"),
              p(4, "result_indexes", doc="value;result;id"),
              p(5, "target_bgr", doc="blue,green,red"),
              p(6, "kill_and_id", doc="kill_index,test_id")])
def evalleds(ctx, row):
    """Judge LED colour by K-means dominant-colour clustering.

    A faithful port of v1's ImageProcessManager.EVALLEDS. Each LED site is
    cropped, K-means (K=3) finds its dominant colours, and the LED passes when a
    cluster centre lands within TOLERANCE of the target BGR.

    Two v1 behaviours are reproduced deliberately rather than "improved":

    * The colour comparison runs on ``center`` from the **last** LED in the list,
      because v1 tests it after the loop rather than inside it. With one LED per
      row -- which is how cargo.ods calls it -- this makes no difference.
    * ``overall_pass`` only goes false on malformed coordinates or an empty crop,
      not on colour; the colour verdict is the post-loop check.

    Changing either would silently shift limits that were tuned against real
    boards, so they stay until someone re-qualifies them against real images.
    """
    cv2 = _cv2()
    np = _np()

    frame = _load_frame(ctx, row.raw(2), row.verb)
    coords = [c.strip() for c in str(ctx.text(row.raw(3))).split(";") if c.strip()]
    if not coords:
        raise VerbError("EVALLEDS: no LED coordinates given")

    target = [t.strip() for t in str(ctx.text(row.raw(5))).split(",")]
    if len(target) < 3:
        raise VerbError(
            f"EVALLEDS: column 5 must be 'blue,green,red', got '{row.raw(5)}'")
    try:
        target_bgr = [int(float(t)) for t in target[:3]]
    except ValueError:
        raise VerbError(f"EVALLEDS: target colour '{row.raw(5)}' is not numeric") from None

    kill_index, test_id = _kill_and_id(ctx, row)
    cells = [ctx.resolve_name(c.strip())
             for c in ctx.text(row.raw(4)).split(";") if c.strip()]

    overall_pass = True
    centres = None
    height, width = frame.shape[:2]

    for index, item in enumerate(coords):
        parts = [x.strip() for x in item.split(",")]
        if len(parts) < 4:
            ctx.log(f"EVALLEDS: LED {index} needs 'x,y,crop_radius,threshold', "
                    f"got '{item}'", "warn")
            overall_pass = False
            continue
        try:
            x, y, crop_radius = (int(float(parts[0])), int(float(parts[1])),
                                 int(float(parts[2])))
        except ValueError:
            ctx.log(f"EVALLEDS: LED {index} has non-numeric coordinates '{item}'",
                    "warn")
            overall_pass = False
            continue

        x1, y1 = max(x - crop_radius, 0), max(y - crop_radius, 0)
        x2, y2 = min(x + crop_radius, width), min(y + crop_radius, height)
        cropped = frame[y1:y2, x1:x2]
        if cropped.size == 0:
            ctx.log(f"EVALLEDS: LED {index} crop at ({x}, {y}) is empty -- "
                    f"outside the {width}x{height} image", "warn")
            overall_pass = False
            continue

        samples = cropped.reshape((-1, 3)).astype(np.float32)
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
        _, labels, centre = cv2.kmeans(samples, LED_CLUSTERS, None, criteria, 10,
                                       cv2.KMEANS_RANDOM_CENTERS)
        centres = centre.astype(np.uint8)
        counts = np.bincount(labels.flatten(), minlength=LED_CLUSTERS)
        dominant = centres[int(counts.argmax())]
        ctx.log(f"EVALLEDS: LED {index} at ({x}, {y}) dominant BGR "
                f"{list(int(v) for v in dominant)}")

    colour = ""
    matched = False
    if overall_pass and centres is not None:
        for centre in centres:
            if all(target_bgr[i] - LED_TOLERANCE <= int(centre[i])
                   <= target_bgr[i] + LED_TOLERANCE for i in range(3)):
                colour = "-".join(str(int(centre[i])) for i in range(3)) + "-"
                matched = True
                break

    result = "PASS" if matched else "FAIL"
    ctx.log(f"{test_id}: target BGR {target_bgr} +/-{LED_TOLERANCE} -> {result}"
            + (f" (matched {colour})" if matched else ""),
            "pass" if matched else "fail")

    for cell, value in zip(cells, [colour, result, test_id]):
        ctx.set_data(cell, value)

    low = "-".join(str(v - LED_TOLERANCE) for v in target_bgr)
    high = "-".join(str(v + LED_TOLERANCE) for v in target_bgr)
    ctx.record.add_point(TestPoint(
        name=test_id, uut=kill_index, result=result,
        measured=colour or "no match", low=low, high=high, row=row.index))
    if kill_index is not None:
        ctx.emit(GridEvent(
            grid=kill_index + 1, op="add", tag=result,
            values=[test_id, str(kill_index + 1), low, high,
                    colour or "no match", result]))
        if result == "FAIL":
            ctx.kill(kill_index, reason=test_id)


def _load_frame(ctx, cell: str, what: str):
    """Resolve an image cell that may hold either a path or an array.

    v1's EVALLEDS calls getImage("-", content, UI), which falls through to
    cv2.imread -- so the data cell holds a *path*. Other verbs store the frame
    itself. Accepting both means a table works either way.
    """
    value = ctx.content(cell)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise VerbError(f"{what}: {cell} holds no image")
    if isinstance(value, str):
        cv2 = _cv2()
        frame = cv2.imread(value)
        if frame is None:
            raise VerbError(f"{what}: cannot read image '{value}'")
        return frame
    return value


@verb(MODULE, "MASSCROP",
      params=[p(2, "image"), p(3, "centres", doc="'cx,cy;cx,cy;...'"),
              p(4, "radius"), p(5, "dests", doc="';'-separated indexes")])
def masscrop(ctx, row):
    """Crop several square patches out of one frame."""
    image = _load(ctx, row, data_col=2, path_col=2)
    radius = int(float(ctx.text(row.raw(4))))
    if radius <= 0:
        raise VerbError(f"MASSCROP: radius must be positive, got {radius}")

    centres = []
    for pair in str(ctx.text(row.raw(3))).split(";"):
        if not pair.strip():
            continue
        parts = [x.strip() for x in pair.split(",")]
        if len(parts) < 2:
            raise VerbError(f"MASSCROP: '{pair}' is not 'cx,cy'")
        centres.append((int(float(parts[0])), int(float(parts[1]))))

    dests = [d.strip() for d in ctx.text(row.raw(5)).split(";") if d.strip()]
    if len(dests) != len(centres):
        raise VerbError(f"MASSCROP: {len(centres)} centre(s) but {len(dests)} "
                        f"destination index(es)")

    height, width = image.shape[:2]
    for (cx, cy), dest in zip(centres, dests):
        x0, x1 = max(cx - radius, 0), min(cx + radius, width)
        y0, y1 = max(cy - radius, 0), min(cy + radius, height)
        if x0 >= x1 or y0 >= y1:
            raise VerbError(f"MASSCROP: crop at ({cx}, {cy}) falls outside the "
                            f"{width}x{height} image")
        ctx.set_data(dest, image[y0:y1, x0:x1].copy(), stringify=False)
    ctx.log(f"MASSCROP: {len(centres)} crop(s) stored")


# --- shared helpers -----------------------------------------------------

def _floats(ctx, cell: str, count: int, what: str) -> list[float]:
    parts = [x.strip() for x in ctx.text(cell).split(",") if x.strip()]
    if len(parts) < count:
        raise VerbError(f"{what}: expected {count} comma-separated numbers, "
                        f"got '{cell}'")
    try:
        return [float(x) for x in parts[:count]]
    except ValueError:
        raise VerbError(f"{what}: '{cell}' contains a non-number") from None


def _float_list(ctx, cell: str, what: str) -> list[float]:
    try:
        return [float(x.strip()) for x in ctx.text(cell).split(",") if x.strip()]
    except ValueError:
        raise VerbError(f"{what}: '{cell}' contains a non-number") from None


def _kill_and_id(ctx, row) -> tuple[int | None, str]:
    if not row.has(6):
        return None, row.comment or row.verb
    parts = [x.strip() for x in ctx.text(row.raw(6)).split(",")]
    if len(parts) < 2:
        raise VerbError(f"{row.verb}: column 6 must be 'kill_index,test_id'")
    try:
        return int(parts[0]), parts[1]
    except ValueError:
        raise VerbError(f"{row.verb}: '{parts[0]}' is not a UUT index") from None


def _store_triplet(ctx, row, measured, result, test_id) -> None:
    """Write value / result / test-id to column 4's destinations.

    Two forms, both in use:

    * ``0,0,1;0,1,1;0,2,1`` -- three explicit cells.
    * ``0,0,1``             -- one cell, from which the other two are derived by
      incrementing the **column**: (0,0,1), (0,1,1), (0,2,1). This is v1's
      ``getTripleIndex`` and is what the cargo table actually writes.

    Supporting only the explicit form silently dropped the PASS/FAIL and the
    test id, leaving the measured value stored but no verdict anywhere -- the
    area was right and the result was blank.
    """
    raw = ctx.text(row.raw(4)).strip()
    if not raw:
        return
    # Resolve <Vars> names to their coordinate first. The triple below is
    # derived by incrementing the column, which needs an l,c,p to work on --
    # a named destination would otherwise store the measurement and silently
    # drop the verdict and the test id.
    cells = [ctx.resolve_name(c.strip()) for c in raw.split(";") if c.strip()]
    if len(cells) == 1:
        parts = [x.strip() for x in cells[0].split(",")]
        if len(parts) == 3 and parts[1].lstrip("-").isdigit():
            column = int(parts[1])
            cells = [f"{parts[0]},{column + offset},{parts[2]}"
                     for offset in range(3)]
    for cell, value in zip(cells, [measured, result, test_id]):
        ctx.set_data(cell, value)


def _publish(ctx, row, kill_index, test_id, result, measured, limit) -> None:
    ctx.log(f"{test_id}: {measured} vs {limit} -> {result}",
            "pass" if result == "PASS" else "fail")
    ctx.record.add_point(TestPoint(
        name=test_id, uut=kill_index, result=result,
        measured=str(measured), low=str(limit), high="", row=row.index,
    ))
    if kill_index is not None:
        ctx.emit(GridEvent(grid=kill_index + 1, op="add", tag=result,
                           values=[test_id, str(kill_index + 1), str(limit), "-",
                                   str(measured), result]))
        if result == "FAIL":
            ctx.kill(kill_index, reason=test_id)


REGISTRY.alias_module("ImageProcess", MODULE)
REGISTRY.alias_module("Vision", MODULE)
