"""Writes the site's plan sheets as an .xlsx workbook that imports into Google Sheets."""
import openpyxl
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill

SITE = "https://shibasheets.org/"
TABS = {"main": "Main chart", "dvha": "Dental, vision, hearing, extras"}
# Keep in sync with --comment and --contradicts in web/static/style.css.
FILLS = {"note": "FFF6D6", "contradicts": "FFDCB8"}
HEAD = PatternFill("solid", fgColor="EEF1F6")
SECTION = PatternFill("solid", fgColor="1D2433")
TOP = Alignment(vertical="top", wrap_text=True)
MAX_WIDTH = 40


def write(site, path):
    book = openpyxl.Workbook()
    book.remove(book.active)
    plans = {p["plan_id"]: p for p in site["plans"]}
    for name, tab in TABS.items():
        add_tab(book.create_sheet(tab), name, site[name], plans, site["sections"])
    book.save(path)


def add_tab(ws, name, sheet, plans, sections):
    ws.append(["Plan", "Plan ID", *(c["label"] for c in sheet["columns"])])
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = HEAD
        c.alignment = TOP
    ws.freeze_panes = "C2"
    ws.column_dimensions["A"].width = MAX_WIDTH
    ws.column_dimensions["B"].width = 14
    for col, xl in zip(sheet["columns"], ws[1][2:]):
        lines = [line for r in sheet["rows"] for line in r["cells"][col["key"]]["value"].split(" | ")]
        ws.column_dimensions[xl.column_letter].width = min(MAX_WIDTH, 2 + max(map(len, lines + col["label"].split())))
    section = None
    for row in sheet["rows"]:
        if row["section"] != section:
            section = row["section"]
            ws.append([sections.get(section, section)] + [None] * (len(sheet["columns"]) + 1))
            for c in ws[ws.max_row]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = SECTION
        plan_id = row["plan_id"]
        ws.append([plans[plan_id]["plan_name"], plan_id,
                   *(row["cells"][c["key"]]["value"].replace(" | ", "\n") for c in sheet["columns"])])
        xl_row = ws[ws.max_row]
        xl_row[0].hyperlink = f"{SITE}#/plan/{plan_id}"
        for col, xl in zip(sheet["columns"], xl_row[2:]):
            xl.alignment = TOP
            cell = row["cells"][col["key"]]
            if cell["value"] and (cell["cites"] or "comment" in cell):
                xl.hyperlink = f"{SITE}#/{name}/{plan_id}/{col['key']}"
            if "comment" in cell:
                xl.comment = Comment(cell["comment"]["text"], "shibasheets.org", width=300, height=150)
                xl.fill = PatternFill("solid", fgColor=FILLS[cell["comment"]["kind"]])
