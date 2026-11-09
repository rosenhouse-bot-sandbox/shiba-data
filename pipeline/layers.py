"""Builds a year's live sheets by applying layers to its generated sheets, in order.

A layer row cites a value for a cell, or for one line of it. Rows of the code and edits layers also set that value,
and a later layer wins. Within the edits layer, a later row wins. The live sheets drop a citation whose value is not
the live cell's.
"""
import csv

import fields

SHEETS = {"main": "main_chart.csv", "dvha": "dvha.csv"}
COLUMNS = ["sheet", "plan_id", "column", "line", "value", "url", "pdf_page", "quote"]
# Machine rows also name the step that wrote them and a hash of its prompts, which is blank if not recorded.
MACHINE_COLUMNS = ["step", "prompt"] + COLUMNS
# An edit also records the value its author saw, who wrote it, and why.
# source is "session" for a Claude session a person steered, or "volunteer" or "manager" for issue #11 users.
# author is an ID that the issue #11 Worker maps to a person, never a name or email.
EDIT_COLUMNS = COLUMNS + ["saw", "source", "author", "note"]
XREF, BLANKS, FILLED, EDITS = "machine/eoc_citations.csv", "machine/blanks.csv", "machine/filled.csv", "edits.csv"
PRESENTED = "generated/presented.csv"
# Code-made cells come first, then model steps' rows, then columns presented from facts,
# then edits by people or the Claude sessions they steer.
LAYERS = ("generated/citations.csv", XREF, BLANKS, FILLED, PRESENTED, EDITS)
# Model steps only cite until a person reviews their corrections (issue #48).
CITE_ONLY = {XREF, BLANKS, FILLED}
# struck.csv hides a machine quote that does not support its cell.
STRUCK, STRUCK_COLUMNS = "struck.csv", ["sheet", "plan_id", "column", "quote", "note"]


def rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def generated(data):
    return {sheet: rows(data / "generated" / name) for sheet, name in SHEETS.items()}


def layer(data, name):
    """Reads a layer's rows and adds the layer's name and each row's place in the file. A missing layer has no rows."""
    if not (data / name).exists():
        return []
    with open(data / name, newline="") as f:
        reader = csv.DictReader(f)
        columns = MACHINE_COLUMNS if name in CITE_ONLY else EDIT_COLUMNS if name == EDITS else COLUMNS
        if reader.fieldnames != columns:
            raise ValueError(f"{name} has columns {reader.fieldnames}, not {columns}")
        return [dict(r, layer=name, position=n) for n, r in enumerate(reader)]


def strikes(data):
    if not (data / STRUCK).exists():
        return []
    with open(data / STRUCK, newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != STRUCK_COLUMNS:
            raise ValueError(f"{STRUCK} has columns {reader.fieldnames}, not {STRUCK_COLUMNS}")
        return list(reader)


def strike_key(r):
    return r["sheet"], r["plan_id"], r["column"], r["quote"]


def stale_strikes(data):
    """Lists strikes that match no machine row, such as after a rerun picked another quote."""
    quoted = {strike_key(r) for name in CITE_ONLY for r in layer(data, name)}
    return [s for s in strikes(data) if strike_key(s) not in quoted]


def where(c):
    return f"{c['layer']} {c['sheet']} {c['plan_id']} {c['column']}" + (f" line {c['line']}" if c["line"] else "")


def shown(cell, line):
    """Returns the cell, or its line, or None if it has no such line."""
    if not line:
        return cell
    lines = cell.split(" | ")
    return lines[int(line) - 1] if 1 <= int(line) <= len(lines) else None


def without(*names):
    return tuple(n for n in LAYERS if n not in names)


def live(data, names=LAYERS, ignore=None):
    """Returns (sheets, kept, dropped): the sheets after the layers, and the layer rows whose value they show or not.
    Rows for which ignore(row) is true are skipped.
    Kept rows from the latest layer come first, so a cell's first citation is from the layer that set its value.
    An edit whose cell has changed since its author saw it gets `beneath`, the value it now replaces.
    A blank `saw` means the author's view is unknown."""
    sheets = generated(data)
    index = {(sheet, r["plan_id"]): r for sheet, sheet_rows in sheets.items() for r in sheet_rows}
    by_layer = [[r for r in layer(data, name) if not (ignore and ignore(r))] for name in names]
    for layer_rows in by_layer:
        values = {}
        for c in layer_rows:
            row = index.get((c["sheet"], c["plan_id"]), {})
            if c["column"] not in row or c["column"] not in fields.labels(c["sheet"]):
                raise ValueError(f"A layer row names no cell: {where(c)}")
            if c["layer"] in CITE_ONLY:
                continue
            before = shown(row[c["column"]], c["line"])
            if before is None:
                raise ValueError(f"A layer row names no line: {where(c)}")
            if c["layer"] == EDITS:
                if c["saw"] and before not in (c["saw"], c["value"]):
                    c["beneath"] = before
            elif values.setdefault((c["sheet"], c["plan_id"], c["column"], c["line"]), c["value"]) != c["value"]:
                raise ValueError(f"Rows of one layer set different values: {where(c)}")
            if c["line"]:
                lines = row[c["column"]].split(" | ")
                lines[int(c["line"]) - 1] = c["value"]
                row[c["column"]] = " | ".join(lines)
            else:
                row[c["column"]] = c["value"]
    struck = {strike_key(s) for s in strikes(data)}
    cites = [c for layer_rows in reversed(by_layer) for c in layer_rows
             if not (c["layer"] in CITE_ONLY and strike_key(c) in struck)]
    matches = [shown(index[(c["sheet"], c["plan_id"])][c["column"]], c["line"]) == c["value"] for c in cites]
    return sheets, [c for c, ok in zip(cites, matches) if ok], [c for c, ok in zip(cites, matches) if not ok]


# Why the site leaves out a layer row's citation.
OTHER_VALUE, STRUCK_QUOTE, NO_DOCUMENT, UNKNOWN_DOCUMENT, NOT_SB_CITES_CELL = (
    "other_value", "struck", "no_document", "unknown_document", "not_sb_cites_cell")


def citations(data, kind_of, names=LAYERS, ignore=None):
    """Returns (sheets, rows): live()'s sheets, and every layer row with `hidden`, why the site leaves its citation out,
    or "" if the site shows it. kind_of maps each checked document's url to its kind.
    Shown rows keep live()'s order. A cell cited by a document other than an SB shows no SB citation."""
    sheets, kept, dropped = live(data, names, ignore)
    struck = {strike_key(s) for s in strikes(data)}
    struck_rows = [r for name in reversed(names) if name in CITE_ONLY for r in layer(data, name)
                   if not (ignore and ignore(r)) and strike_key(r) in struck]
    for c in kept:
        if c["url"] in kind_of:
            c["hidden"] = ""
        elif c["layer"] == EDITS:
            c["hidden"] = UNKNOWN_DOCUMENT if c["url"] else NO_DOCUMENT
        else:
            raise ValueError(f"A citation names a document not in documents_checked.csv: {where(c)} {c['url']}")
    not_sb = {(c["sheet"], c["plan_id"], c["column"]) for c in kept if not c["hidden"] and kind_of[c["url"]] != "SB"}
    for c in kept:
        if not c["hidden"] and kind_of[c["url"]] == "SB" and (c["sheet"], c["plan_id"], c["column"]) in not_sb:
            c["hidden"] = NOT_SB_CITES_CELL
    return sheets, (kept + [dict(c, hidden=OTHER_VALUE) for c in dropped]
                    + [dict(c, hidden=STRUCK_QUOTE) for c in struck_rows])
