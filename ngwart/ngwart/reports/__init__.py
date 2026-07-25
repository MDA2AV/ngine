"""Report generation from a RunRecord.

Pure functions over the record: adding a format costs nothing and needs no
knowledge of any product's data-store layout.
"""

from __future__ import annotations

import datetime as _dt
import os
from xml.sax.saxutils import escape

from ..engine.runrecord import RunRecord

__all__ = ["write_report", "to_xml", "to_json", "to_csv", "FORMATS"]

FORMATS = ("xml", "json", "csv")


def write_report(record: RunRecord, path: str, fmt: str = "json") -> str:
    fmt = fmt.lower()
    if fmt not in FORMATS:
        raise ValueError(f"unknown report format '{fmt}' "
                         f"(expected {', '.join(FORMATS)})")
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    text = {"xml": to_xml, "json": to_json, "csv": to_csv}[fmt](record)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def to_json(record: RunRecord) -> str:
    return record.to_json()


def to_csv(record: RunRecord) -> str:
    rows = ["uut,test,result,measured,low,high,row,at"]
    for pt in record.points:
        rows.append(",".join(_csv_cell(x) for x in (
            "" if pt.uut is None else pt.uut, pt.name, pt.result, pt.measured,
            pt.low, pt.high, "" if pt.row is None else pt.row, pt.at)))
    return "\n".join(rows) + "\n"


def _csv_cell(value) -> str:
    text = "" if value is None else str(value)
    if any(c in text for c in ',"\n'):
        return '"' + text.replace('"', '""') + '"'
    return text


def to_xml(record: RunRecord, uut: int | None = None) -> str:
    """One ``<LOG_XML>`` per UUT, matching the shape v1 produced.

    Kept deliberately close to the v1 output so whatever consumes these files
    downstream does not need changing -- but generated from recorded points, so
    nothing is lost to an overwritten data cell.
    """
    uuts = [uut] if uut is not None else (record.uuts() or [None])
    parts = []
    for target in uuts:
        points = record.points_for(target) if target is not None else record.points
        passed = record.passed(target) if target is not None else record.passed()
        parts.append(_one_xml(record, target, points, passed))
    if len(parts) == 1:
        return parts[0]
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<LOGS>\n'
            + "\n".join(_strip_decl(p) for p in parts) + "\n</LOGS>\n")


def _strip_decl(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not l.startswith("<?xml"))


def _one_xml(record: RunRecord, uut, points, passed: bool) -> str:
    started = record.started
    ended = record.ended or _dt.datetime.now()
    name = f"{record.program_name}_{uut if uut is not None else 'ALL'}"
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<LOG_XML>",
        f"  <filename>{escape(name)}</filename>",
        f"  <serialnumber>{escape(record.barcodes.get(uut, ''))}</serialnumber>",
        "  <supplier>UARTRONICA</supplier>",
        f"  <station>{escape(record.station)}</station>",
        f"  <operator>{escape(record.operator)}</operator>",
        f"  <starttime>{started:%Y-%m-%d %H:%M:%S}</starttime>",
        f"  <endtime>{ended:%Y-%m-%d %H:%M:%S}</endtime>",
        f"  <duration>{record.duration_s:.2f}</duration>",
        f"  <result>{'PASS' if passed else 'FAIL'}</result>",
    ]
    if record.simulate:
        # Never let a simulated run be mistaken for a real one downstream.
        lines.append("  <simulated>true</simulated>")
    lines.append("  <tasks>")
    for pt in points:
        lines.append(f'    <task name="{escape(pt.name)}">')
        lines.append(f"      <result>{escape(pt.result)}</result>")
        if pt.measured != "":
            lines.append(f"      <measured>{escape(str(pt.measured))}</measured>")
        if pt.low != "":
            lines.append(f"      <min>{escape(str(pt.low))}</min>")
        if pt.high != "":
            lines.append(f"      <max>{escape(str(pt.high))}</max>")
        lines.append("    </task>")
    lines.append("  </tasks>")
    lines.append("</LOG_XML>")
    return "\n".join(lines) + "\n"
