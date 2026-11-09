import csv, contextlib, io, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, ".."), HERE]
import cms_sources, dvha, main_chart, reads, universe  # noqa: E402
from test_cms_sources import DICTIONARY, FIXTURE, PLANS  # noqa: E402
from test_scripts import landscape_row  # noqa: E402


def keep(plan, landscape, found):
    """The plan's PBP rows and plans.csv row with only the fields in found."""
    files = {file for file, field, _ in found if field == reads.ROWS}
    fields = {(file, field) for file, field, _ in found}
    return ({file: [{k: v for k, v in r.items() if (file, k) in fields} for r in rows]
             for file, rows in plan.items() if file in files},
            {k: v for k, v in landscape.items() if (main_chart.PLANS, k) in fields})


class LoggedTest(unittest.TestCase):
    def test_logs_each_field_read_and_reads_a_missing_field_as_blank(self):
        def compute(row):
            return row.get("a"), row["b"], row.get("missing", "x")
        result, log = reads.logged(compute, ("f", {"a": "1", "b": "2", "c": "3"}))
        self.assertEqual(result, ("1", "2", "x"))
        self.assertEqual(log, [("f", "a", "1"), ("f", "b", "2"), ("f", "missing", "")])

    def test_logs_each_files_row_count_once(self):
        def compute(plan):
            return [plan.get("f"), plan.get("f"), plan.get("absent", [])]
        result, log = reads.logged(compute, ("plan", {"f": [{"a": "1"}]}))
        self.assertEqual(result, [[{"a": "1"}], [{"a": "1"}], []])
        self.assertEqual(log, [("f", reads.ROWS, "1"), ("absent", reads.ROWS, "0")])


class MainChartReadsTest(unittest.TestCase):
    def test_each_cell_comes_from_the_fields_it_read(self):
        for make_row, columns in ((main_chart.chart_row, main_chart.COLUMNS), (dvha.dvha_row, dvha.COLUMNS)):
            for landscape in PLANS:
                plan = FIXTURE["plans"][landscape["plan_id"]]
                whole = make_row(landscape, plan)
                for column, compute in columns.items():
                    with self.subTest(plan=landscape["plan_id"], column=column):
                        found = reads.logged(compute, (main_chart.PLANS, landscape), ("plan", plan))[1]
                        self.assertEqual(compute(*reversed(keep(plan, landscape, found))), whole[column])

    def test_reads_cover_the_fields_cms_sources_lists(self):
        for landscape in PLANS:
            rows = main_chart.reads(landscape, FIXTURE["plans"][landscape["plan_id"]], DICTIONARY)
            for column, (stem, fields) in cms_sources.PBP_FIELDS.items():
                with self.subTest(plan=landscape["plan_id"], column=column):
                    read = {r["field"] for r in rows if r["column"] == column and r["file"] == stem}
                    present = {f for f in fields if any(f in r for r in FIXTURE["plans"][landscape["plan_id"]].get(stem, []))}
                    self.assertLessEqual(present, read)

    def test_decodes_coded_fields(self):
        landscape = PLANS[0]
        rows = main_chart.reads(landscape, FIXTURE["plans"][landscape["plan_id"]], DICTIONARY)
        self.assertTrue(any(r["title"] for r in rows))
        self.assertTrue(all(r["title"] == r["meaning"] == "" for r in rows if r["field"] == reads.ROWS))


class DvhaReadsTest(unittest.TestCase):
    def test_lists_the_reads_of_every_column(self):
        rows = dvha.reads(PLANS[0], FIXTURE["plans"][PLANS[0]["plan_id"]], DICTIONARY)
        self.assertEqual({r["column"] for r in rows}, set(dvha.COLUMNS))
        self.assertTrue(any(r["title"] for r in rows))


FULL = {"Plan Type": "HMO", "Organization Marketing Name": "Carrier", "Monthly Consolidated Premium (Part C + D)": "$10.00",
        "Part C Premium": "$4.00", "Part D Low Income Beneficiary Premium Amount": "$1.50",
        "In-Network Maximum Out-of-Pocket (MOOP) Amount": "$5,000.00", "Annual Part D Deductible Amount": "$600.00",
        "Offers Drug Tier with No Part D Deductible": "Yes", "Chronic or Disabling Condition SNP (C-SNP) Condition Type":
        "Not Applicable", "Overall Star Rating": "4"}


class UniverseReadsTest(unittest.TestCase):
    def test_each_plans_column_comes_from_the_landscape_fields_it_read(self):
        for part_d in ("Yes", "No"):
            row = landscape_row(**{"Part D Coverage Indicator": part_d}, **FULL)
            by_field = {}
            for r in universe.reads(row):
                by_field.setdefault(r["plan_field"], {})[r["field"]] = r["value"]
            for name, compute in universe.FIELDS.items():
                with self.subTest(part_d=part_d, field=name):
                    self.assertEqual(compute(by_field[name]), compute(row))

    def test_main_writes_the_reads_of_each_plan(self):
        row = landscape_row(**FULL)
        with tempfile.TemporaryDirectory() as d:
            with open(f"{d}/landscape.csv", "w", newline="") as f:
                w = csv.DictWriter(f, list(row))
                w.writeheader()
                w.writerow(row)
            with contextlib.redirect_stdout(io.StringIO()):
                universe.main(f"{d}/landscape.csv", f"{d}/plans.csv", f"{d}/reads.csv", "OR", "Multnomah")
            with open(f"{d}/reads.csv", newline="") as f:
                self.assertEqual(list(csv.DictReader(f)), universe.reads(row))


if __name__ == "__main__":
    unittest.main()
