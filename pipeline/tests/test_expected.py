import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import expected

EOC = "https://x/eoc.pdf"
EXPECTED = [
    dict(sheet="main", plan_id="H1-001-0", column="L_xray_imaging", line="2", value="$0-$300", eoc_url=EOC, eoc_pages=[7]),
    dict(sheet="main", plan_id="H2-001-0", column="L_xray_imaging", line="", value="20%", eoc_url="", eoc_pages=[]),
    dict(sheet="dvha", plan_id="H1-001-0", column="F_dental", line="", value="PREV $0", eoc_url=EOC, eoc_pages=[52, 111]),
    dict(sheet="dvha", plan_id="H1-001-0", column="C_premium", line="", value="$0", eoc_url="", eoc_pages=[]),
]


def cell(value, *pages):
    return dict(value=value, cites={(EOC, p) for p in pages})


class ScoreTest(unittest.TestCase):
    def score(self, cells, columns=(("main", "L_xray_imaging"), ("dvha", "F_dental"))):
        return expected.score(cells, columns, EXPECTED)

    def test_matches_a_line_and_its_eoc_page(self):
        result = self.score({("main", "H1-001-0", "L_xray_imaging"): cell("$0 | $0-$300", 7, 8)})
        self.assertEqual(result[("main", "L_xray_imaging")]["matches"], [("main", "H1-001-0", "L_xray_imaging", "2")])

    def test_misses_a_wrong_value(self):
        result = self.score({("main", "H1-001-0", "L_xray_imaging"): cell("$0 | $0-$250", 7)})
        self.assertEqual(result[("main", "L_xray_imaging")]["misses"][0],
                         (("main", "H1-001-0", "L_xray_imaging", "2"), "value $0-$250, not $0-$300"))

    def test_misses_uncited_eoc_pages(self):
        result = self.score({("dvha", "H1-001-0", "F_dental"): cell("PREV $0")})
        self.assertEqual(result[("dvha", "F_dental")], dict(matches=[], misses=[
            (("dvha", "H1-001-0", "F_dental", ""), f"cites no {EOC} page 52 111")]))

    def test_misses_a_page_of_another_document(self):
        got = dict(value="PREV $0", cites={("https://x/other.pdf", 52), (EOC, 111)})
        result = self.score({("dvha", "H1-001-0", "F_dental"): got})
        self.assertEqual(result[("dvha", "F_dental")]["misses"][0][1], f"cites no {EOC} page 52")

    def test_reads_pages_given_as_strings(self):
        got = dict(value="PREV $0", cites={(EOC, "52"), (EOC, "111")})
        result = self.score({("dvha", "H1-001-0", "F_dental"): got})
        self.assertEqual(len(result[("dvha", "F_dental")]["matches"]), 1)

    def test_checks_only_values_where_edits_cite_only_sbs(self):
        result = self.score({("main", "H2-001-0", "L_xray_imaging"): cell("20%")})
        self.assertIn(("main", "H2-001-0", "L_xray_imaging", ""), result[("main", "L_xray_imaging")]["matches"])

    def test_misses_an_absent_cell_or_line(self):
        result = self.score({("main", "H1-001-0", "L_xray_imaging"): cell("$0", 7)})
        self.assertEqual(result[("main", "L_xray_imaging")]["misses"], [
            (("main", "H1-001-0", "L_xray_imaging", "2"), "no line 2"),
            (("main", "H2-001-0", "L_xray_imaging", ""), "no cell")])

    def test_scores_only_the_columns_asked_for(self):
        self.assertEqual(list(self.score({}, [("dvha", "F_dental")])), [("dvha", "F_dental")])

    def test_refuses_a_column_with_no_expected_cells(self):
        for column in [("main", "C_premium"), "F_dental"]:
            with self.assertRaises(ValueError):
                self.score({}, [column])


class FixtureTest(unittest.TestCase):
    def test_loads_every_edited_cell_line(self):
        cells = expected.load()
        self.assertEqual(len(cells), 358)
        self.assertEqual(sum(1 for c in cells if not c["eoc_pages"]), 129)
        self.assertEqual(sum(1 for c in cells if c["column"] == "L_xray_imaging"), 41)
        self.assertTrue(all(c["eoc_url"] for c in cells if c["eoc_pages"]))
        self.assertTrue(all(isinstance(p, int) for c in cells for p in c["eoc_pages"]))
        self.assertEqual(max(len(c["eoc_pages"]) for c in cells), 4)

    def test_scores_against_the_fixture_by_default(self):
        result = expected.score({}, [("main", "L_xray_imaging")])
        self.assertEqual(len(result[("main", "L_xray_imaging")]["misses"]), 41)


if __name__ == "__main__":
    unittest.main()
