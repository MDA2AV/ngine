"""Image-processing verbs -- registered as ``ImageProcessManager``.

The nine colour-conversion verbs (RGB2GRAY, BGR2GRAY, GRAY2BIN, RGB2BIN,
BGR2BIN, BIN2CONT, GRAY2CONT, BGR2CONT, RGB2CONT) are one pipeline with a
source colourspace and a target stage. Written once, registered nine times.

Every verb takes its input either from a data cell (column 2) or from a file
(column 3), and writes to a data cell (column 4), a file (column 5), or both --
the same convention v1 used.
"""

from __future__ import annotations

import functools
import os

from ..engine.errors import VerbError
from ..engine.events import GridEvent
from ..engine.registry import REGISTRY, Param, VerbSpec, p, verb
from ..engine.runrecord import TestPoint

MODULE = "ImageProcessManager"


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


def _emit(ctx, row, image, data_col: int = 4, path_col: int = 5) -> None:
    """Store the result wherever the row asked for it."""
    wrote = False
    if row.has(data_col):
        ctx.set_data(row.raw(data_col), image, stringify=False)
        wrote = True
    if row.has(path_col):
        path = ctx.text(row.raw(path_col))
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        if not _cv2().imwrite(path, image):
            raise VerbError(f"{row.verb}: could not write '{path}'")
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

    contours, _ = cv2.findContours(binary.astype(_np().uint8), cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    ctx.log(f"{row.verb}: {len(contours)} contour(s) found")
    if not row.has(4):
        raise VerbError(f"{row.verb}: column 4 must name where to store the contours")
    ctx.set_data(row.raw(4), list(contours), stringify=False)


_CONV_PARAMS = (
    Param(2, "image_index", False, "source image held in the data store"),
    Param(3, "image_path", False, "source image on disk"),
    Param(4, "dest_index", False),
    Param(5, "save_path", False),
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


def _find_at(cv2, contours, cx: float, cy: float, tol: float):
    """Nearest contour whose centroid sits within `tol` of (cx, cy)."""
    best, best_d = None, None
    for contour in contours:
        centre = _centroid(cv2, contour)
        if centre is None:
            continue
        distance = max(abs(centre[0] - cx), abs(centre[1] - cy))
        if distance <= tol and (best_d is None or distance < best_d):
            best, best_d = contour, distance
    return best


@verb(MODULE, "MEASCONT", params=[p(2, "contours"), p(3, "target", doc="cx,cy,tol"),
                                  p(4, "dest")])
def meascont(ctx, row):
    """Store the calibrated area of the contour at (cx, cy)."""
    cv2 = _cv2()
    contours = ctx.content(row.raw(2)) or []
    cx, cy, tol = _floats(ctx, row.raw(3), 3, "MEASCONT")
    found = _find_at(cv2, contours, cx, cy, tol)
    area = cv2.contourArea(found) if found is not None else 0.0
    ctx.log(f"MEASCONT at ({cx}, {cy}): area {area}")
    ctx.set_data(row.raw(4), area)


@verb(MODULE, "EVALCONT",
      params=[p(2, "contours"), p(3, "spec", doc="cx,cy,tol,minarea,cal"),
              p(4, "dest"), p(5, "grid_style", required=False, doc="'min' or blank"),
              p(6, "kill_and_id", doc="kill_index,test_id")])
def evalcont(ctx, row):
    """Pass when a large enough contour sits at (cx, cy)."""
    cv2 = _cv2()
    contours = ctx.content(row.raw(2)) or []
    cx, cy, tol, minarea, cal = _floats(ctx, row.raw(3), 5, "EVALCONT")
    kill_index, test_id = _kill_and_id(ctx, row)

    found = _find_at(cv2, contours, cx, cy, tol)
    area = cv2.contourArea(found) * cal if found is not None else 0.0
    result = "PASS" if found is not None and area > minarea else "FAIL"
    _publish(ctx, row, kill_index, test_id, result, area, minarea)
    if row.has(4):
        ctx.set_data(row.raw(4), result)


@verb(MODULE, "EVALCONTN",
      params=[p(2, "contours"), p(3, "spec", doc="cx,cy,tol,minarea,cal"),
              p(4, "dest"), p(5, "grid_style", required=False),
              p(6, "kill_and_id")])
def evalcontn(ctx, row):
    """Inverse of EVALCONT: pass when nothing is present at (cx, cy)."""
    cv2 = _cv2()
    contours = ctx.content(row.raw(2)) or []
    cx, cy, tol, minarea, cal = _floats(ctx, row.raw(3), 5, "EVALCONTN")
    kill_index, test_id = _kill_and_id(ctx, row)

    found = _find_at(cv2, contours, cx, cy, tol)
    area = cv2.contourArea(found) * cal if found is not None else 0.0
    result = "PASS" if found is None or area <= minarea else "FAIL"
    _publish(ctx, row, kill_index, test_id, result, area, minarea)
    if row.has(4):
        ctx.set_data(row.raw(4), result)


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
        found = _find_at(cv2, contours, cx, cy, tol)
        area = cv2.contourArea(found) if found is not None else 0.0
        ok = found is not None and area > minarea
        results.append("PASS" if ok else "FAIL")
        ctx.log(f"EVALCONTS[{i}] at ({cx}, {cy}): area {area} -> {results[-1]}",
                "pass" if ok else "fail")
    ctx.set_data(row.raw(2) if not row.has(4) else row.raw(4), ";".join(results))


@verb(MODULE, "EVALLEDS",
      params=[p(2, "image"), p(3, "coords", doc="'cx,cy;cx,cy;...' or an index"),
              p(4, "dest"), p(5, "extra", required=False),
              p(6, "kill_and_id")])
def evalleds(ctx, row):
    """Check that each named site is lit.

    Brightness is sampled in a small patch and compared against the frame's own
    median, so the check survives a change in ambient light -- v1 used a fixed
    threshold and had to be re-tuned per fixture.
    """
    np = _np()
    image = _load(ctx, row, data_col=2, path_col=2)
    kill_index, test_id = _kill_and_id(ctx, row)

    grey = image if image.ndim == 2 else _cv2().cvtColor(image, _cv2().COLOR_BGR2GRAY)
    baseline = float(np.median(grey))

    sites = []
    for pair in str(ctx.text(row.raw(3))).split(";"):
        pair = pair.strip()
        if not pair:
            continue
        parts = [x.strip() for x in pair.split(",")]
        if len(parts) < 2:
            raise VerbError(f"EVALLEDS: '{pair}' is not 'cx,cy'")
        sites.append((float(parts[0]), float(parts[1])))
    if not sites:
        raise VerbError("EVALLEDS: no coordinates given")

    results, half = [], 6
    for i, (cx, cy) in enumerate(sites):
        x0, x1 = max(int(cx) - half, 0), min(int(cx) + half, grey.shape[1])
        y0, y1 = max(int(cy) - half, 0), min(int(cy) + half, grey.shape[0])
        if x0 >= x1 or y0 >= y1:
            raise VerbError(f"EVALLEDS: site ({cx}, {cy}) is outside the image")
        patch = float(grey[y0:y1, x0:x1].mean())
        lit = patch > baseline * 1.5
        results.append("PASS" if lit else "FAIL")
        ctx.log(f"LED {i} at ({cx}, {cy}): {patch:.1f} vs baseline {baseline:.1f} "
                f"-> {results[-1]}", "pass" if lit else "fail")

    overall = "PASS" if all(r == "PASS" for r in results) else "FAIL"
    if row.has(4):
        ctx.set_data(row.raw(4), overall)
    _publish(ctx, row, kill_index, test_id, overall,
             results.count("PASS"), len(results))


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
        return int(parts[0]), ",".join(parts[1:])
    except ValueError:
        raise VerbError(f"{row.verb}: '{parts[0]}' is not a UUT index") from None


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
