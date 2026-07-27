"""Debug bundle: everything needed to explain a run, in one folder.

Built for the question "why did INTENSITY_A fail?", which in practice needs the
frame that was captured, the binary it was thresholded to, the contours that
came out, and the search window the verb actually looked in. Reading a log
cannot answer it; looking at the images can.

Enable with ``--debug`` (or ``--debug DIR``). Off by default: it writes images,
so it costs disk and a little time per vision step.

Nothing here is required by the engine -- ``ctx.debug`` is None unless asked
for, and every call site guards on it.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import threading
import time
from dataclasses import asdict


class DebugBundle:
    """Collects artefacts for one run into a timestamped folder."""

    def __init__(self, root: str, run_name: str = "run") -> None:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.dir = os.path.join(root, f"{run_name}_{stamp}")
        self.images = os.path.join(self.dir, "images")
        os.makedirs(self.images, exist_ok=True)
        self._lock = threading.Lock()
        self._notes: list[str] = []
        self._counter = 0
        self.write_environment()

    # -- primitives -------------------------------------------------------

    def _next(self) -> int:
        with self._lock:
            self._counter += 1
            return self._counter

    def note(self, message: str) -> None:
        """A line in notes.txt -- the narrative of what was inspected."""
        with self._lock:
            self._notes.append(f"{time.strftime('%H:%M:%S')}  {message}")

    def save_json(self, name: str, payload) -> str:
        path = os.path.join(self.dir, name)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, default=str)
        except OSError:
            return ""
        return path

    def save_text(self, name: str, text: str) -> str:
        path = os.path.join(self.dir, name)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError:
            return ""
        return path

    def save_image(self, label: str, image, row: int | None = None) -> str:
        """Write an image, tagged with the row that produced it."""
        try:
            import cv2
        except ImportError:
            return ""
        if image is None:
            return ""
        index = self._next()
        prefix = f"{index:03d}" + (f"_row{row}" if row is not None else "")
        name = f"{prefix}_{_safe(label)}.png"
        path = os.path.join(self.images, name)
        try:
            if not cv2.imwrite(path, image):
                return ""
        except Exception:  # noqa: BLE001 - debug must never break a run
            return ""
        self.note(f"image {name}"
                  + (f"  shape={getattr(image, 'shape', '?')}"))
        return path

    # -- domain helpers ---------------------------------------------------

    def save_contours(self, label: str, frame, contours, row: int | None = None,
                      focus: tuple[int, int, int] | None = None) -> None:
        """Draw contours over the frame, optionally marking a search window.

        `focus` is (cx, cy, tol) -- the window an evaluation verb searched. Seeing
        it drawn is usually enough to tell "nothing was there" apart from "the
        coordinates point somewhere else".
        """
        try:
            import cv2
            import numpy as np
        except ImportError:
            return
        if frame is None:
            return
        try:
            canvas = frame.copy()
            if canvas.ndim == 2:
                canvas = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)
            cv2.drawContours(canvas, list(contours or []), -1, (0, 200, 255), 1)
            if focus:
                cx, cy, tol = focus
                cv2.rectangle(canvas, (cx - tol, cy - tol), (cx + tol, cy + tol),
                              (0, 0, 255), 1)
                cv2.drawMarker(canvas, (cx, cy), (255, 0, 255),
                               cv2.MARKER_CROSS, 12, 1)
            self.save_image(label, canvas, row)
        except Exception:  # noqa: BLE001
            return

    def describe_contours(self, contours, cal: float = 1.0) -> list[dict]:
        """Centroid and area of every contour, for contours.json."""
        try:
            import cv2
        except ImportError:
            return []
        out = []
        for i, contour in enumerate(contours or []):
            try:
                raw = cv2.contourArea(contour)
                m = cv2.moments(contour)
                centre = (int(m["m10"] / m["m00"]), int(m["m01"] / m["m00"])) \
                    if m["m00"] else None
                out.append({"index": i, "centroid": centre,
                            "area_raw": round(raw, 2),
                            "area_calibrated": round(raw * cal, 2)})
            except Exception:  # noqa: BLE001
                continue
        return out

    # -- lifecycle --------------------------------------------------------

    def write_environment(self) -> None:
        import ngwart

        lines = [
            f"ngwart      {ngwart.__version__}",
            f"python      {sys.version.split()[0]} ({sys.executable})",
            f"platform    {platform.platform()}",
            "",
            "packages:",
        ]
        for name in ("PySide6", "PyYAML", "pyserial", "pyvisa",
                     "opencv-python", "numpy"):
            try:
                import importlib.metadata as md
                lines.append(f"  {name:<16} {md.version(name)}")
            except Exception:  # noqa: BLE001
                lines.append(f"  {name:<16} not installed")
        try:
            from mvIMPACT import acquire  # noqa: F401
            lines.append("  mvIMPACT         present")
        except Exception:  # noqa: BLE001
            lines.append("  mvIMPACT         not present")
        self.save_text("environment.txt", "\n".join(lines) + "\n")

    def write_program(self, program) -> None:
        rows = ["\t".join(r.cells) for r in program.rows]
        self.save_text("program.tsv", "\n".join(rows) + "\n")
        self.save_json("program.json", {
            "source": program.source,
            "modules": program.modules,
            "vars": program.vars,
            "labels": program.labels,
            "sections": {k: [v.start, v.end] for k, v in program.sections.items()},
        })

    def write_diagnostics(self, report) -> None:
        self.save_json("validation.json",
                       [{"severity": d.severity, "row": d.row,
                         "message": d.message, "detail": d.detail} for d in report])

    def write_datastore(self, ctx) -> None:
        """Every populated cell, with its variable name where one exists."""
        if ctx.data is None:
            return
        names = {v: k for k, v in ctx.program.vars.items()}
        lines_n, cols_n, pages_n = ctx.dims
        cells = []
        for l in range(lines_n):
            for c in range(cols_n):
                for p in range(pages_n):
                    value = ctx.data[l][c][p]
                    if value is None:
                        continue
                    coord = f"{l},{c},{p}"
                    rendered = (f"<{type(value).__name__} "
                                f"shape={getattr(value, 'shape', '?')}>"
                                if not isinstance(value, (str, int, float))
                                else str(value))
                    cells.append({"coord": coord, "name": names.get(coord, ""),
                                  "value": rendered})
        self.save_json("datastore.json", cells)

    def finish(self, record, listener=None) -> str:
        """Write the record, the log and a human-readable summary."""
        if record is not None:
            self.save_text("run.json", record.to_json())
            self.save_json("points.json", [asdict(p) for p in record.points])
        if listener is not None:
            from .events import LogEvent

            lines = [f"{'' if e.row is None else e.row:>5}  [{e.level}] {e.message}"
                     for e in listener.of_type(LogEvent)]
            self.save_text("log.txt", "\n".join(lines) + "\n")
        with self._lock:
            self.save_text("notes.txt", "\n".join(self._notes) + "\n")

        summary = ["NGWART debug bundle", "=" * 40, ""]
        if record is not None:
            for key, value in record.summary().items():
                summary.append(f"{key:<16} {value}")
            failed = [p for p in record.points if p.result == "FAIL"]
            if failed:
                summary += ["", "FAILED POINTS", "-" * 40]
                for pt in failed:
                    summary.append(
                        f"  {pt.name:<20} uut={pt.uut} measured={pt.measured} "
                        f"limits=[{pt.low}, {pt.high}] row={pt.row}")
        summary += ["", "Files", "-" * 40,
                    "  environment.txt   versions and SDK presence",
                    "  program.tsv       the loaded program",
                    "  validation.json   pre-run diagnostics",
                    "  log.txt           full operator log",
                    "  run.json          every step, timing and outcome",
                    "  points.json       every pass/fail judgement",
                    "  datastore.json    every populated data cell",
                    "  notes.txt         what was inspected, in order",
                    "  images/           captures, binaries, contour overlays"]
        self.save_text("SUMMARY.txt", "\n".join(summary) + "\n")
        return self.dir


def _safe(text: str) -> str:
    keep = "-_."
    return "".join(c if (c.isalnum() or c in keep) else "_" for c in str(text))[:60]
