import csv, contextlib, io, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, ".."), HERE]
import reads, universe  # noqa: E402
from test_scripts import landscape_row  # noqa: E402


FULL = {"Plan Type": "HMO", "Organization Marketing Name": "Carrier", "Monthly Consolidated Premium (Part C + D)": "$10.00",
        "Part C Premium": "$4.00", "Part D Low Income Beneficiary Premium Amount": "$1.50",
        "In-Network Maximum Out-of-Pocket (MOOP) Amount": "$5,000.00", "Annual Part D Deductible Amount": "$600.00",
        "Offers Drug Tier with No Part D Deductible": "Yes", "Chronic or Disabling Condition SNP (C-SNP) Condition Type":
        "Not Applicable", "Overall Star Rating": "4"}


class LoggedTest(unittest.TestCase):
    def test_logs_each_field_read_and_reads_a_missing_field_as_blank(self):
        def compute(row):
            return row.get("a"), row["b"], row.get("missing", "x")
        result, log = reads.logged(compute, ("f", {"a": "1", "b": "2", "c": "3"}))
        self.assertEqual(result, ("1", "2", "x"))
        self.assertEqual(log, [("f", "a", "1"), ("f", "b", "2"), ("f", "missing", "")])


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
