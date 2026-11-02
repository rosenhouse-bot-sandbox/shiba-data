import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import build  # noqa: E402
import sheet_sync  # noqa: E402
from sheet_layout import FILLS, SITE, TABS, Cell, Row, rows  # noqa: E402
from test_build import data_copy  # noqa: E402


def layout(*plans, columns=("A", "B")):
    return [Row("header", "", [Cell(h) for h in ["Plan", "Plan ID", *columns]]),
            Row("section", "Sec", [Cell("Sec")] + [Cell() for _ in range(len(columns) + 1)]),
            *(Row("plan", p, [Cell(f"name {p}"), Cell(p), *(Cell(f"{p}{c}") for c in columns)]) for p in plans)]


def grid(header, keys, n_rows=1000, n_cols=26):
    return sheet_sync.Existing(sheet_id=7, header=header, keys=keys, row_count=n_rows, column_count=n_cols)


def inserted(requests):
    return [r["insertDimension"]["range"]["startIndex"] for r in requests if "insertDimension" in r]


def placed(requests):
    """Maps (row, column) to the value each updateCells request writes there."""
    out = {}
    for r in requests:
        if "updateCells" not in r:
            continue
        start = r["updateCells"]["start"]
        for i, row in enumerate(r["updateCells"]["rows"]):
            for j, cell in enumerate(row["values"]):
                out[(start["rowIndex"] + i, start["columnIndex"] + j)] = cell["userEnteredValue"]["stringValue"]
    return out


class PlanTest(unittest.TestCase):
    def test_fills_an_empty_sheet_from_the_top_left(self):
        cells = placed(sheet_sync.plan(grid([], []), layout("P1", "P2")))
        self.assertEqual(cells[(0, 0)], "Plan")
        self.assertEqual(cells[(1, 0)], "Sec")
        self.assertEqual(cells[(3, 1)], "P2")
        self.assertEqual(cells[(3, 3)], "P2B")

    def test_writes_each_value_onto_its_plans_row_and_columns_header(self):
        existing = grid(["Plan", "Plan ID", "B", "A"], ["", "P2", "Sec", "P1"])
        cells = placed(sheet_sync.plan(existing, layout("P1", "P2")))
        self.assertEqual(cells[(3, 2)], "P1B")
        self.assertEqual(cells[(3, 3)], "P1A")
        self.assertEqual(cells[(1, 3)], "P2A")
        self.assertEqual(cells[(2, 0)], "Sec")

    def test_leaves_unknown_rows_and_columns_alone(self):
        existing = grid(["Plan", "Plan ID", "Old", "A", "B"], ["", "Sec", "Gone", "P1"])
        cells = placed(sheet_sync.plan(existing, layout("P1")))
        self.assertFalse({(r, c) for r, c in cells if r == 2 or c == 2})
        self.assertEqual(cells[(3, 4)], "P1B")

    def test_a_renamed_column_keeps_its_place(self):
        old, new = next(iter(sheet_sync.RENAMED.items()))
        existing = grid(["Plan", "Plan ID", old, "A"], ["", "Sec", "P1"])
        cells = placed(sheet_sync.plan(existing, layout("P1", columns=("A", new))))
        self.assertEqual(cells[(0, 2)], new)
        self.assertEqual(cells[(2, 2)], f"P1{new}")
        self.assertNotIn((0, 4), cells)

    def test_appends_new_plans_and_columns_after_the_last_ones(self):
        existing = grid(["Plan", "Plan ID", "A"], ["", "Sec", "P1"])
        requests = sheet_sync.plan(existing, layout("P1", "P2"))
        cells = placed(requests)
        self.assertEqual(cells[(0, 3)], "B")
        self.assertEqual(cells[(1, 3)], "")
        self.assertEqual(cells[(2, 3)], "P1B")
        self.assertEqual(cells[(3, 1)], "P2")
        self.assertEqual(inserted(requests), [])

    def test_inserts_a_new_plan_under_its_section(self):
        two_sections = layout("P1", "P2") + [Row("section", "Sec2", [Cell("Sec2")]), Row("plan", "P3", [Cell("n"), Cell("P3")])]
        existing = grid(["Plan", "Plan ID", "A", "B"], ["", "Sec", "P1", "Sec2", "P3"])
        requests = sheet_sync.plan(existing, two_sections)
        self.assertEqual(inserted(requests), [3])
        cells = placed(requests)
        self.assertEqual(cells[(3, 1)], "P2")
        self.assertEqual(cells[(4, 0)], "Sec2")
        self.assertEqual(cells[(5, 1)], "P3")
        self.assertLess(requests.index(next(r for r in requests if "insertDimension" in r)),
                        requests.index(next(r for r in requests if "updateCells" in r)))

    def test_trims_empty_rows_below_the_data(self):
        requests = sheet_sync.plan(grid([], [], n_rows=1000), layout("P1", "P2"))
        [trim] = [r["deleteDimension"]["range"] for r in requests if "deleteDimension" in r]
        self.assertEqual(trim, {"sheetId": 7, "dimension": "ROWS", "startIndex": 4, "endIndex": 1000})

    def test_keeps_rows_the_data_no_longer_has(self):
        requests = sheet_sync.plan(grid(["Plan", "Plan ID", "A", "B"], ["", "Sec", "Gone", "P1"], n_rows=5), layout("P1"))
        [trim] = [r["deleteDimension"]["range"] for r in requests if "deleteDimension" in r]
        self.assertEqual((trim["startIndex"], trim["endIndex"]), (4, 5))

    def test_grows_a_grid_too_small_for_the_data(self):
        requests = sheet_sync.plan(grid([], [], n_rows=2, n_cols=3), layout("P1", "P2"))
        appends = {r["appendDimension"]["dimension"]: r["appendDimension"]["length"] for r in requests if "appendDimension" in r}
        self.assertEqual(appends, {"ROWS": 2, "COLUMNS": 1})
        self.assertLess(requests.index(next(r for r in requests if "appendDimension" in r)),
                        requests.index(next(r for r in requests if "updateCells" in r)))

    def test_keeps_header_and_plan_columns_in_view(self):
        [props] = [r["updateSheetProperties"] for r in sheet_sync.plan(grid([], []), layout("P1")) if "updateSheetProperties" in r]
        self.assertEqual(props["properties"]["gridProperties"], {"frozenRowCount": 1, "frozenColumnCount": 2})

    def test_sizes_columns_where_they_land(self):
        existing = grid(["Plan", "Plan ID", "B", "A"], ["", "Sec", "P1"])
        requests = sheet_sync.plan(existing, layout("P1"), column_widths=[40, 14, 5, 9])
        sizes = {r["updateDimensionProperties"]["range"]["startIndex"]: r["updateDimensionProperties"]["properties"]["pixelSize"]
                 for r in requests if "updateDimensionProperties" in r}
        self.assertEqual(sizes[3], sheet_sync.pixels(5))
        self.assertEqual(sizes[2], sheet_sync.pixels(9))


class CellDataTest(unittest.TestCase):
    def test_each_write_replaces_value_note_format_and_links(self):
        [update, *_] = [r["updateCells"] for r in sheet_sync.plan(grid([], []), layout("P1")) if "updateCells" in r]
        self.assertEqual(set(update["fields"].split(",")), {"userEnteredValue", "note", "userEnteredFormat", "textFormatRuns"})

    def test_tab_title_is_quoted_for_a_range(self):
        self.assertEqual(sheet_sync.quoted("Dental, vision & Bob's"), "'Dental, vision & Bob''s'")

    def test_value_stays_text(self):
        self.assertEqual(sheet_sync.cell_data(Cell("$0"), "plan")["userEnteredValue"], {"stringValue": "$0"})

    def test_link_note_and_fill(self):
        data = sheet_sync.cell_data(Cell("x", link="https://l", note="n", fill="FFF6D6"), "plan")
        self.assertEqual(data["textFormatRuns"], [{"startIndex": 0, "format": {"link": {"uri": "https://l"}}}])
        self.assertEqual(data["note"], "n")
        self.assertEqual(data["userEnteredFormat"]["backgroundColor"], {"red": 1.0, "green": 0xF6 / 255, "blue": 0xD6 / 255})

    def test_plain_cell_clears_an_old_note_link_and_fill(self):
        data = sheet_sync.cell_data(Cell("x"), "plan")
        self.assertEqual(data["note"], "")
        self.assertNotIn("textFormatRuns", data)
        self.assertEqual(data["userEnteredFormat"]["backgroundColor"], {"red": 1.0, "green": 1.0, "blue": 1.0})

    def test_header_and_section_rows_are_bold(self):
        self.assertTrue(sheet_sync.cell_data(Cell("h"), "header")["userEnteredFormat"]["textFormat"]["bold"])
        section = sheet_sync.cell_data(Cell("s"), "section")["userEnteredFormat"]
        self.assertTrue(section["textFormat"]["bold"])
        self.assertEqual(section["textFormat"]["foregroundColor"], {"red": 1.0, "green": 1.0, "blue": 1.0})


class FakeApi:
    def __init__(self, tabs):
        self.tabs = dict(tabs)
        self.batches = []

    def sheets(self):
        return [{"sheetId": i, "title": t, "gridProperties": {"rowCount": 1000, "columnCount": 26}} for i, t in enumerate(self.tabs)]

    def values(self, ranges):
        out = []
        for r in ranges:
            title, cells = r.rsplit("!", 1)
            data = self.tabs[title.strip("'").replace("''", "'")]
            out.append(data[:1] if cells == "1:1" else [row[:2] for row in data])
        return out

    def batch_update(self, requests):
        self.batches.append(requests)
        for r in requests:
            if "addSheet" in r:
                self.tabs[r["addSheet"]["properties"]["title"]] = []


class SyncTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            cls.site = build.site_data(data_copy(tmp, []))

    def test_adds_missing_tabs_then_fills_them(self):
        api = FakeApi({"Sheet1": []})
        sheet_sync.sync(api, self.site)
        self.assertEqual([r["addSheet"]["properties"]["title"] for r in api.batches[0]], list(TABS.values()))
        cells = placed(api.batches[1])
        self.assertEqual(cells[(0, 0)], "Plan")
        self.assertEqual(len([1 for (r, c), v in cells.items() if c == 1 and v.startswith("H")]),
                         len(self.site["plans"]))

    def test_rewrites_a_filled_sheet_in_place(self):
        tabs = {tab: [[c.value for c in row.cells] for row in rows(self.site, name)] for name, tab in TABS.items()}
        api = FakeApi(tabs)
        sheet_sync.sync(api, self.site)
        self.assertEqual(len(api.batches), len(TABS))
        cells = placed(api.batches[0])
        main = [[c.value for c in row.cells] for row in rows(self.site, "main")]
        self.assertEqual(cells[(len(main) - 1, len(main[0]) - 1)], main[-1][-1])
        self.assertLess(max(r for r, _ in cells), len(main))
        self.assertFalse([r for r in api.batches[0] if "insertDimension" in r or "appendDimension" in r and
                          r["appendDimension"]["dimension"] == "ROWS"])

    def test_cited_cell_links_to_the_site(self):
        api = FakeApi({})
        sheet_sync.sync(api, self.site)
        links = [c["textFormatRuns"][0]["format"]["link"]["uri"] if "textFormatRuns" in c else None
                 for r in api.batches[1] if "updateCells" in r for row in r["updateCells"]["rows"] for c in row["values"]]
        self.assertIn(f"{SITE}#/main/H2001-045-0/H_inpatient", links)
        fills = [c["userEnteredFormat"]["backgroundColor"]
                 for r in api.batches[1] if "updateCells" in r for row in r["updateCells"]["rows"] for c in row["values"]]
        self.assertIn(sheet_sync.color(FILLS["note"]), fills)


if __name__ == "__main__":
    unittest.main()
