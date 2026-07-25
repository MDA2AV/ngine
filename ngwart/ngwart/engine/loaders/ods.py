"""OpenDocument spreadsheet reader/writer -- no third-party dependency.

v1 reached for ``pandas_ods_reader`` + ``pyexcel_ods``, which drags in pandas
(and with it numpy) purely to read a grid of strings. It also routed every cell
through a DataFrame, so integers came back as floats and empty cells as the
float ``nan`` -- which is why v1 has ``if word == "nan"`` scattered through its
table loader.

Reading the XML directly avoids all of that: a cell's displayed text is exactly
what the engineer typed.
"""

from __future__ import annotations

import zipfile
from xml.sax.saxutils import escape

from ..errors import LoaderError

TABLE_NS = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
T = "{%s}" % TABLE_NS

#: ODS pads rows out to the sheet width with a huge repeat count. Anything
#: above this is padding, not real columns.
_REPEAT_CAP = 64


def read_ods(path: str, sheet: int = 0) -> list[list[str]]:
    """Return the sheet as a list of rows of trimmed cell strings."""
    import xml.etree.ElementTree as ET

    try:
        with zipfile.ZipFile(path) as zf:
            content = zf.read("content.xml")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise LoaderError(f"cannot read ODS file '{path}': {exc}") from exc

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise LoaderError(f"malformed ODS content in '{path}': {exc}") from exc

    tables = root.findall(f".//{T}table")
    if not tables:
        raise LoaderError(f"no sheets found in '{path}'")
    if sheet >= len(tables):
        raise LoaderError(f"'{path}' has {len(tables)} sheet(s); sheet {sheet} requested")

    rows: list[list[str]] = []
    for tr in tables[sheet].findall(f".//{T}table-row"):
        repeat_row = _int_attr(tr, "number-rows-repeated", 1)
        if repeat_row > _REPEAT_CAP:
            repeat_row = 1
        cells: list[str] = []
        for tc in tr:
            if tc.tag not in (f"{T}table-cell", f"{T}covered-table-cell"):
                continue
            repeat = _int_attr(tc, "number-columns-repeated", 1)
            if repeat > _REPEAT_CAP:
                repeat = 1
            cells.extend([_cell_text(tc)] * repeat)
        while cells and not cells[-1]:
            cells.pop()
        for _ in range(repeat_row):
            rows.append(list(cells))

    while rows and not any(rows[-1]):
        rows.pop()
    return rows


def _int_attr(el, name: str, default: int) -> int:
    raw = el.get(f"{T}{name}")
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _cell_text(cell) -> str:
    """Displayed text of a cell.

    Multiple ``text:p`` children mean hard line breaks inside the cell; join
    them with a space rather than losing the separation, since test tables
    occasionally wrap a long comment.
    """
    parts = ["".join(p.itertext()) for p in cell]
    text = " ".join(part.strip() for part in parts if part.strip())
    return text.strip()


# --- writing ------------------------------------------------------------

_MIMETYPE = "application/vnd.oasis.opendocument.spreadsheet"

_CONTENT_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<office:document-content '
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'office:version="1.2"><office:body><office:spreadsheet>'
)
_CONTENT_TAIL = "</office:spreadsheet></office:body></office:document-content>"

_MANIFEST = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<manifest:manifest '
    'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" '
    'manifest:version="1.2">'
    f'<manifest:file-entry manifest:full-path="/" manifest:media-type="{_MIMETYPE}"/>'
    '<manifest:file-entry manifest:full-path="content.xml" '
    'manifest:media-type="text/xml"/>'
    "</manifest:manifest>"
)


def write_ods(path: str, rows: list[list[str]], sheet_name: str = "Sheet1") -> None:
    """Write rows back to a minimal but valid ODS.

    Enough for LibreOffice and Excel to open. Lets the program editor round-trip
    a legacy table without the engineer having to leave the spreadsheet world.
    """
    body = [_CONTENT_HEAD, f'<table:table table:name="{escape(sheet_name)}">']
    width = max((len(r) for r in rows), default=1)
    body.append(f'<table:table-column table:number-columns-repeated="{width}"/>')
    for row in rows:
        body.append("<table:table-row>")
        for cell in row:
            value = "" if cell is None else str(cell)
            if value:
                body.append(
                    '<table:table-cell office:value-type="string">'
                    f"<text:p>{escape(value)}</text:p></table:table-cell>"
                )
            else:
                body.append("<table:table-cell/>")
        body.append("</table:table-row>")
    body.append("</table:table>")
    body.append(_CONTENT_TAIL)

    try:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            # The mimetype entry must be first and stored uncompressed.
            zf.writestr(zipfile.ZipInfo("mimetype"), _MIMETYPE,
                        compress_type=zipfile.ZIP_STORED)
            zf.writestr("META-INF/manifest.xml", _MANIFEST)
            zf.writestr("content.xml", "".join(body))
    except OSError as exc:
        raise LoaderError(f"cannot write ODS file '{path}': {exc}") from exc
