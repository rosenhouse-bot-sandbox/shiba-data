"""Lays out the site's plan sheets as rows of the live Google Sheet."""
import json
from dataclasses import dataclass

import facts
import present

SITE = "https://pdxplans.org/"
TABS = {"main": "Main chart", "dvha": "Dental, vision, hearing, extras"}
DETAILS = "Details"
FACT_COLUMNS = {"Plan ID": "plan_id", "Plan": None, "Benefit": "benefit", "Setting": "setting", "Network": "network",
                "Covered by": "covered_by", "Cost kind": "cost_kind", "Amount": "amount", "Unit": "unit", "Limit": "limit",
                "Condition": "condition", "Package": "package", "Pool": "pool", "Provider tier": "provider_tier",
                "Source": "source", "Page": "page", "Quote or CMS field": None, "Note": "note"}
# Keep in sync with --comment and --hand-written in web/static/style.css.
FILLS = {"question": "FFF6D6", "hand_written": "E3F1E0"}
# Keep in sync with KIND_NAMES in web/static/app.js.
KIND_NAMES = {"question": "Open question", "hand_written": "Hand-written fact"}
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
        out.append(Row("plan", plan_id, [Cell(plans[plan_id]["plan_name"], link=f"{SITE}#/{site['year']}/plan/{plan_id}"), Cell(plan_id),
                                         *(value_cell(site["year"], name, plan_id, c, row["cells"][c["key"]]) for c in sheet["columns"])]))
    return out


def value_cell(year, name, plan_id, column, cell):
    out = Cell(cell["value"].replace(" | ", "\n"))
    if cell["value"] and (cell["cites"] or "comment" in cell):
        out.link = f"{SITE}#/{year}/{name}/{plan_id}/{column['id']}"
    if "comment" in cell:
        out.note = f"{KIND_NAMES[cell['comment']['kind']]}: {cell['comment']['text']}"
        out.fill = FILLS[cell["comment"]["kind"]]
    return out


def widths(sheet):
    """Character widths of all columns. Each benefit column fits its longest line, up to MAX_WIDTH."""
    return [MAX_WIDTH, PLAN_ID_WIDTH, *(min(MAX_WIDTH, 2 + max(map(len, lines(sheet, c)))) for c in sheet["columns"])]


def lines(sheet, column):
    return [line for r in sheet["rows"] for line in r["cells"][column["key"]]["value"].split(" | ")] + column["label"].split()


def details(site, data_dir):
    """One row per fact, with its page linked to the PDF."""
    names = {p["plan_id"]: p["plan_name"] for p in site["plans"]}
    found = [f for plan in present.plan_facts(data_dir).values() for f in plan]

    def cells(f):
        out = [Cell(f[key] if key else "") for key in FACT_COLUMNS.values()]
        out[1].value = names.get(f["plan_id"], "")
        out[list(FACT_COLUMNS).index("Quote or CMS field")].value = "\n".join(json.loads(f["quotes"] or "[]"))
        if f["doc_sha"]:
            out[list(FACT_COLUMNS).index("Page")].link = f"{SITE}docs/{f['doc_sha']}.pdf#page={f['page']}"
        return out

    order = [*facts.KEY, "source", "doc_sha", "page"]
    found = sorted(found, key=lambda f: [f[k] for k in order])
    return [Row("header", "", [Cell(h) for h in FACT_COLUMNS])] + [Row("plan", f["plan_id"], cells(f)) for f in found]
