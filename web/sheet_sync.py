"""Updates the live Google Sheet in place to match the site's data.

Rows are matched by plan ID (or section name) and columns by header, so cells keep their comments.
Rows and columns the data no longer has are left alone. New ones go after the last row or column.

Usage: SHEETS_TOKEN=<OAuth access token> SHIBA_SHEET_ID=<id> python3 -I web/sheet_sync.py
"""
import json
import os
import pathlib
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "pipeline")]
from sheet_layout import HEAD, SECTION, TABS, rows, widths  # noqa: E402

WHITE = "FFFFFF"
FIELDS = "userEnteredValue,note,userEnteredFormat"


@dataclass
class Existing:
    sheet_id: int
    header: list
    keys: list  # one per row: the plan ID, else the section name, else ""
    row_count: int
    column_count: int


def pixels(chars):
    return 7 * chars + 5


def color(hex_rgb):
    return {k: int(hex_rgb[i:i + 2], 16) / 255 for k, i in (("red", 0), ("green", 2), ("blue", 4))}


def cell_data(cell, kind):
    text = {"bold": kind != "plan"}
    if kind == "section":
        text["foregroundColor"] = color(WHITE)
    if cell.link:
        text["link"] = {"uri": cell.link}
    fill = cell.fill or {"header": HEAD, "section": SECTION}.get(kind, WHITE)
    return {
        "userEnteredValue": {"stringValue": cell.value},
        "note": cell.note or "",
        "userEnteredFormat": {"wrapStrategy": "WRAP", "verticalAlignment": "TOP", "textFormat": text,
                              "backgroundColor": color(fill)},
    }


def place(wanted, have):
    """Index in `have` of each item of `wanted`, or the next index after `have` for items it lacks."""
    at = {k: i for i, k in enumerate(have) if k}
    out, end = [], len(have)
    for k in wanted:
        if k not in at:
            at[k], end = end, end + 1
        out.append(at[k])
    return out


def plan(existing, layout, widths=None):
    """The batchUpdate requests that write `layout` into `existing`."""
    sheet_id = existing.sheet_id
    columns = place([c.value for c in layout[0].cells], existing.header)
    row_at = place(["\0header"] + [r.key for r in layout[1:]], ["\0header"] + existing.keys[1:])
    requests = []
    for dimension, need, have in (("ROWS", max(row_at) + 1, existing.row_count),
                                  ("COLUMNS", max(columns) + 1, existing.column_count)):
        if need > have:
            requests.append({"appendDimension": {"sheetId": sheet_id, "dimension": dimension, "length": need - have}})
    requests.append({"updateSheetProperties": {
        "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 2}},
        "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}})
    for col, chars in zip(columns, widths or []):
        requests.append({"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": col, "endIndex": col + 1},
            "properties": {"pixelSize": pixels(chars)}, "fields": "pixelSize"}})
    for row, r in zip(layout, row_at):
        for start, cells in runs(columns, row.cells):
            requests.append({"updateCells": {
                "start": {"sheetId": sheet_id, "rowIndex": r, "columnIndex": start},
                "rows": [{"values": [cell_data(c, row.kind) for c in cells]}], "fields": FIELDS}})
    return requests


def runs(columns, cells):
    """Splits cells into (first column, cells) runs of adjacent columns."""
    out = []
    for col, cell in sorted(zip(columns, cells), key=lambda p: p[0]):
        if out and out[-1][0] + len(out[-1][1]) == col:
            out[-1][1].append(cell)
        else:
            out.append((col, [cell]))
    return out


def quoted(title):
    return "'" + title.replace("'", "''") + "'"


def existing_tab(api, props):
    header, ab = api.values([f"{quoted(props['title'])}!1:1", f"{quoted(props['title'])}!A:B"])
    keys = [(r[1] if len(r) > 1 and r[1] else r[0] if r else "") for r in ab]
    grid = props["gridProperties"]
    return Existing(props["sheetId"], header[0] if header else [], keys, grid["rowCount"], grid["columnCount"])


def sync(api, site):
    missing = [t for t in TABS.values() if t not in {s["title"] for s in api.sheets()}]
    if missing:
        api.batch_update([{"addSheet": {"properties": {"title": t}}} for t in missing])
    tabs = {s["title"]: s for s in api.sheets()}
    for name, title in TABS.items():
        api.batch_update(plan(existing_tab(api, tabs[title]), rows(site, name), widths(site[name])))


class Api:
    def __init__(self, sheet_id, token):
        self.base = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
        self.token = token

    def call(self, path, body=None):
        req = urllib.request.Request(self.base + path, data=body and json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)

    def sheets(self):
        return [s["properties"] for s in self.call("?fields=sheets.properties")["sheets"]]

    def values(self, ranges):
        query = urllib.parse.urlencode([("ranges", r) for r in ranges])
        return [v.get("values", []) for v in self.call(f"/values:batchGet?{query}")["valueRanges"]]

    def batch_update(self, requests):
        self.call(":batchUpdate", {"requests": requests})


if __name__ == "__main__":
    import build
    sync(Api(os.environ["SHIBA_SHEET_ID"], os.environ["SHEETS_TOKEN"]), build.site_data())
