"""Writes the site's plan sheets as an .xlsx workbook that imports into Google Sheets."""
import openpyxl
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from sheet_layout import HEAD, SECTION, TABS, rows, widths

TOP = Alignment(vertical="top", wrap_text=True)


def write(site, path):
    book = openpyxl.Workbook()
    book.remove(book.active)
    for name, tab in TABS.items():
        add_tab(book.create_sheet(tab), site, name)
    book.save(path)


def add_tab(ws, site, name):
    ws.freeze_panes = "C2"
    for i, width in enumerate(widths(site[name]), 1):
        ws.column_dimensions[get_column_letter(i)].width = width
    for row in rows(site, name):
        ws.append([c.value or None for c in row.cells])
        for cell, xl in zip(row.cells, ws[ws.max_row]):
            xl.alignment = TOP
            if row.kind == "header":
                xl.font = Font(bold=True)
                xl.fill = PatternFill("solid", fgColor=HEAD)
            elif row.kind == "section":
                xl.font = Font(bold=True, color="FFFFFF")
                xl.fill = PatternFill("solid", fgColor=SECTION)
            if cell.link:
                xl.hyperlink = cell.link
            if cell.note:
                xl.comment = Comment(cell.note, "pdxplans.org", width=300, height=150)
            if cell.fill:
                xl.fill = PatternFill("solid", fgColor=cell.fill)
