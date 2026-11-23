"""Reads a year's sheets and their citations, which present.py writes in generated/.

A citation cites the value of a cell, or of one line of it.
"""
import csv

import fields

SHEETS = {"main": "main_chart.csv", "dvha": "dvha.csv"}
COLUMNS = ["sheet", "plan_id", "column", "line", "value", "url", "pdf_page", "quote"]
PRESENTED = "generated/presented.csv"
# Why the site leaves out a citation.
NOT_SB_CITES_CELL = "not_sb_cites_cell"


def rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def read(data):
    return {sheet: rows(data / "generated" / name) for sheet, name in SHEETS.items()}


def where(c):
    return f"{c['sheet']} {c['plan_id']} {c['column']}" + (f" line {c['line']}" if c["line"] else "")


def shown(cell, line):
    """Returns the cell, or its line, or None if it has no such line."""
    if not line:
        return cell
    lines = cell.split(" | ")
    return lines[int(line) - 1] if 1 <= int(line) <= len(lines) else None


def citations(data, kind_of):
    """Returns (sheets, rows): the sheets, and each row of presented.csv with its `position` in the file and `hidden`,
    why the site leaves it out, or "" if the site shows it. kind_of maps each checked document's url to its kind.
    A cell cited by a document other than an SB shows no SB citation.
    Fails if a row's value is not its cell's, or it cites an unknown document."""
    by_sheet = read(data)
    index = {(sheet, r["plan_id"]): r for sheet, sheet_rows in by_sheet.items() for r in sheet_rows}
    with open(data / PRESENTED, newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise ValueError(f"{PRESENTED} has columns {reader.fieldnames}, not {COLUMNS}")
        cited = [dict(r, position=n) for n, r in enumerate(reader)]
    for c in cited:
        row = index.get((c["sheet"], c["plan_id"]), {})
        if c["column"] not in row or c["column"] not in fields.labels(c["sheet"]):
            raise ValueError(f"A citation names no cell: {where(c)}")
        if shown(row[c["column"]], c["line"]) != c["value"]:
            raise ValueError(f"A citation's value is not its cell's: {where(c)} {c['value']}")
        if c["url"] not in kind_of:
            raise ValueError(f"A citation names a document not in documents_checked.csv: {where(c)} {c['url']}")
    not_sb = {(c["sheet"], c["plan_id"], c["column"]) for c in cited if kind_of[c["url"]] != "SB"}
    for c in cited:
        c["hidden"] = NOT_SB_CITES_CELL if kind_of[c["url"]] == "SB" and (c["sheet"], c["plan_id"], c["column"]) in not_sb else ""
    return by_sheet, cited
