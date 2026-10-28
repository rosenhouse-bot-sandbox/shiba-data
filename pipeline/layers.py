"""Builds a year's live sheets by applying layers to its generated sheets, in order.

A layer row cites a value for a cell, or for one line of it. Rows of the code and edits layers also set that value,
and a later layer wins. The live sheets drop a citation whose value is not the live cell's.
"""
import csv

import fields

SHEETS = {"main": "main_chart.csv", "dvha": "dvha.csv"}
COLUMNS = ["sheet", "plan_id", "column", "line", "value", "url", "pdf_page", "quote"]
# Machine rows also name the step that wrote them and a hash of its prompts, which is blank if not recorded.
MACHINE_COLUMNS = ["step", "prompt"] + COLUMNS
XREF, BLANKS, FILLED = "machine/eoc_citations.csv", "machine/blanks.csv", "machine/filled.csv"
# Code-made cells come first, then model steps' rows, then edits by people or the Claude sessions they steer.
LAYERS = ("generated/citations.csv", XREF, BLANKS, FILLED, "edits.csv")
# Model steps only cite, because a person reviews their corrections first (issue #48).
CITE_ONLY = {XREF, BLANKS, FILLED}


def rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def generated(data):
    return {sheet: rows(data / "generated" / name) for sheet, name in SHEETS.items()}


def layer(data, name):
    """Reads a layer's rows and adds the layer's name to each. A missing layer has no rows."""
    if not (data / name).exists():
        return []
    with open(data / name, newline="") as f:
        reader = csv.DictReader(f)
        columns = MACHINE_COLUMNS if name in CITE_ONLY else COLUMNS
        if reader.fieldnames != columns:
            raise ValueError(f"{name} has columns {reader.fieldnames}, not {columns}")
        return [dict(r, layer=name) for r in reader]


def where(c):
    return f"{c['layer']} {c['sheet']} {c['plan_id']} {c['column']}" + (f" line {c['line']}" if c["line"] else "")


def shown(cell, line):
    """Returns the cell, or its line, or None if it has no such line."""
    if not line:
        return cell
    lines = cell.split(" | ")
    return lines[int(line) - 1] if 1 <= int(line) <= len(lines) else None


def without(name):
    return tuple(n for n in LAYERS if n != name)


def live(data, names=LAYERS):
    """Returns (sheets, kept, dropped): the sheets after the layers, and the layer rows whose value they show or not.
    Kept rows from the latest layer come first, so a cell's first citation is from the layer that set its value."""
    sheets = generated(data)
    index = {(sheet, r["plan_id"]): r for sheet, sheet_rows in sheets.items() for r in sheet_rows}
    by_layer = [layer(data, name) for name in names]
    for layer_rows in by_layer:
        values = {}
        for c in layer_rows:
            row = index.get((c["sheet"], c["plan_id"]), {})
            if c["column"] not in row or c["column"] not in fields.labels(c["sheet"]):
                raise ValueError(f"A layer row names no cell: {where(c)}")
            if c["layer"] in CITE_ONLY:
                continue
            if values.setdefault((c["sheet"], c["plan_id"], c["column"], c["line"]), c["value"]) != c["value"]:
                raise ValueError(f"Rows of one layer set different values: {where(c)}")
            if shown(row[c["column"]], c["line"]) is None:
                raise ValueError(f"A layer row names no line: {where(c)}")
            if c["line"]:
                lines = row[c["column"]].split(" | ")
                lines[int(c["line"]) - 1] = c["value"]
                row[c["column"]] = " | ".join(lines)
            else:
                row[c["column"]] = c["value"]
    cites = [c for layer_rows in reversed(by_layer) for c in layer_rows]
    matches = [shown(index[(c["sheet"], c["plan_id"])][c["column"]], c["line"]) == c["value"] for c in cites]
    return sheets, [c for c, ok in zip(cites, matches) if ok], [c for c, ok in zip(cites, matches) if not ok]
