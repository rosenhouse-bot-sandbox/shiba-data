import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import expected

EOC = "https://x/eoc.pdf"
EXPECTED = [
    dict(sheet="main", plan_id="H1-001-0", column="L_xray_imaging", line="2", value="$0-$300", eoc_url=EOC, eoc_pages=[7]),
    dict(sheet="main", plan_id="H2-001-0", column="L_xray_imaging", line="", value="20%", eoc_url="", eoc_pages=[]),
    dict(sheet="dvha", plan_id="H1-001-0", column="F_dental", line="", value="PREV $0", eoc_url=EOC, eoc_pages=[52, 111]),
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

    def test_misses_an_uncited_eoc_page(self):
        result = self.score({("dvha", "H1-001-0", "F_dental"): cell("PREV $0", 52)})
        self.assertEqual(result[("dvha", "F_dental")], dict(matches=[], misses=[
            (("dvha", "H1-001-0", "F_dental", ""), f"cites no {EOC} page 111")]))

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

    def test_tells_a_column_from_its_namesake_on_the_other_sheet(self):
        self.assertEqual(self.score({}, [("main", "F_dental")]), {("main", "F_dental"): dict(matches=[], misses=[])})


class FixtureTest(unittest.TestCase):
    def test_loads_every_edited_cell_line(self):
        cells = expected.load()
        self.assertEqual(len(cells), 358)
        self.assertEqual(sum(1 for c in cells if not c["eoc_pages"]), 129)
        self.assertEqual(sum(1 for c in cells if c["column"] == "L_xray_imaging"), 41)
        self.assertTrue(all(c["eoc_url"] for c in cells if c["eoc_pages"]))
        self.assertTrue(all(isinstance(p, int) for c in cells for p in c["eoc_pages"]))


if __name__ == "__main__":
    unittest.main()
