"""Lays out the site's plan sheets as spreadsheet rows, for the .xlsx download and the live Google Sheet."""
from dataclasses import dataclass

SITE = "https://pdxplans.org/"
TABS = {"main": "Main chart", "dvha": "Dental, vision, hearing, extras"}
# Keep in sync with --comment and --contradicts in web/static/style.css.
FILLS = {"note": "FFF6D6", "contradicts": "FFDCB8"}
HEAD = "EEF1F6"
SECTION = "1D2433"
MAX_WIDTH = 40
PLAN_ID_WIDTH = 14


@dataclass
class Cell:
    value: str = ""
    link: str = None
    note: str = None
    fill: str = None


@dataclass
class Row:
    kind: str  # header, section or plan
    key: str
    cells: list


def rows(site, name):
    sheet = site[name]
    plans = {p["plan_id"]: p for p in site["plans"]}
    width = len(sheet["columns"]) + 2
    out = [Row("header", "", [Cell(label) for label in ["Plan", "Plan ID", *(c["label"] for c in sheet["columns"])]])]
    section = None
    for row in sheet["rows"]:
        if row["section"] != section:
            section = row["section"]
            label = site["sections"].get(section, section)
            out.append(Row("section", label, [Cell(label)] + [Cell() for _ in range(width - 1)]))
        plan_id = row["plan_id"]
        out.append(Row("plan", plan_id, [Cell(plans[plan_id]["plan_name"], link=f"{SITE}#/plan/{plan_id}"), Cell(plan_id),
                                         *(value_cell(name, plan_id, c["key"], row["cells"][c["key"]]) for c in sheet["columns"])]))
    return out


def value_cell(name, plan_id, key, cell):
    out = Cell(cell["value"].replace(" | ", "\n"))
    if cell["value"] and (cell["cites"] or "comment" in cell):
        out.link = f"{SITE}#/{name}/{plan_id}/{key}"
    if "comment" in cell:
        out.note = cell["comment"]["text"]
        out.fill = FILLS[cell["comment"]["kind"]]
    return out


def widths(sheet):
    """Character widths of all columns. Each benefit column fits its longest line, up to MAX_WIDTH."""
    return [MAX_WIDTH, PLAN_ID_WIDTH, *(min(MAX_WIDTH, 2 + max(map(len, lines(sheet, c)))) for c in sheet["columns"])]


def lines(sheet, column):
    return [line for r in sheet["rows"] for line in r["cells"][column["key"]]["value"].split(" | ")] + column["label"].split()
