import os, sqlite3, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), os.path.join(os.path.dirname(os.path.dirname(HERE)), "web")]
import blobs, build, fields, layers, present, trace, years

SHA = "0" * 40
AMBULANCE = ("main", "H1036-153-0", "AB_ambulance")
STATUSES = {trace.TRACED, trace.NONE, trace.NOT_YET, trace.NOT_RECORDED}


def statuses(records):
    """Every status in the records, at any depth."""
    if isinstance(records, dict):
        return ({records["status"]} if "status" in records else set()) | {
            s for v in records.values() for s in statuses(v)}
    if isinstance(records, list):
        return {s for v in records for s in statuses(v)}
    return set()


class TraceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        path = os.path.join(cls.tmp.name, "trace.sqlite")
        trace.build(years.LIVE, path, SHA)
        cls.db = sqlite3.connect(path)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.tmp.cleanup()

    def cell(self, *key):
        return trace.cell(self.db, *key)

    def test_every_main_cell_has_every_record_with_a_known_status(self):
        sheets = layers.live(years.data_dir())[0]
        for r in sheets["main"]:
            for col in fields.labels("main"):
                with self.subTest(plan_id=r["plan_id"], col=col):
                    records = self.cell("main", r["plan_id"], col)
                    self.assertEqual(records["cell"]["value"], r[col])
                    self.assertEqual(set(records), {
                        "cell", "plan", "documents", "draft", "answers", "fact_checks", "rule", "added_facts", "notes",
                        "struck_quotes", "model_citations", "layers", "build"})
                    self.assertLessEqual(statuses(records), STATUSES)

    def test_shows_the_values_and_citations_the_site_shows_in_its_order(self):
        site = build.site_data()
        doc = {d["url"]: i for i, d in site["docs"].items()}
        for sheet in ("main", "dvha"):
            for r in site[sheet]["rows"]:
                for col, shown in r["cells"].items():
                    with self.subTest(sheet=sheet, plan_id=r["plan_id"], col=col):
                        live = self.cell(sheet, r["plan_id"], col)["layers"]["live"]
                        self.assertEqual(live["value"], shown["value"])
                        self.assertEqual([dict(line=c.get("line"), value=c["value"], doc=doc[c["url"]], page=c["pdf_page"],
                                               quote=c["quote"]) for c in live["citations"]], shown["cites"])

    def test_says_when_a_document_other_than_an_sb_hides_an_sb_citation(self):
        site = build.site_data()
        sb_rows = [(r["plan_id"], col) for r in site["main"]["rows"] for col in r["cells"]
                   if any(c["hidden"] == layers.NOT_SB_CITES_CELL
                          for c in self.cell("main", r["plan_id"], col)["layers"]["hidden"])]
        self.assertTrue(sb_rows)

    def test_traces_a_dvha_cell_from_its_own_code(self):
        records = self.cell("dvha", "H2923-001-0", "F_dental")
        self.assertEqual(records["draft"]["code"]["file"], "pipeline/dvha.py")
        self.assertEqual(records["layers"]["live"]["set_by"], layers.EDITS)
        self.assertEqual(records["rule"]["status"], trace.NONE)

    def test_reads_a_page_of_a_layout_text(self):
        with tempfile.TemporaryDirectory() as work:
            path = blobs.text_path(work, "layout", "ab" * 32)
            path.parent.mkdir(parents=True)
            path.write_text("=====PAGE 1=====\nfirst\n=====PAGE 2=====\nsecond\n")
            self.assertEqual(trace.page(work, "ab" * 32, "2"), "second\n")

    def test_shows_the_citations_the_site_shows(self):
        live = self.cell(*AMBULANCE)["layers"]["live"]
        self.assertEqual(live["value"], "$325 or 20% | $325")
        self.assertEqual(live["set_by"], layers.PRESENTED)
        self.assertEqual({(c["line"], c["pdf_page"]) for c in live["citations"]}, {(1, 46), (2, 46)})
        self.assertTrue(all(c["layer"] == layers.PRESENTED for c in live["citations"]))

    def test_lists_the_value_after_each_layer(self):
        applied = self.cell(*AMBULANCE)["layers"]["applied"]
        self.assertEqual([a["layer"] for a in applied], list(layers.LAYERS))
        self.assertEqual(applied[-1]["value"], "$325 or 20% | $325")
        self.assertEqual(self.cell(*AMBULANCE)["layers"]["draft"],
                         layers.generated(years.data_dir())["main"][[r["plan_id"] for r in layers.generated(
                             years.data_dir())["main"]].index("H1036-153-0")]["AB_ambulance"])

    def test_says_why_the_site_hides_a_citation(self):
        hidden = self.cell("main", "H3805-048-0", "T_chiropractic")["layers"]["hidden"]
        self.assertIn(("Excluded rom Medicare coverage is any", layers.STRUCK_QUOTE),
                      [(r["quote"], r["hidden"]) for r in hidden])
        self.assertEqual(self.cell("main", "H3805-048-0", "T_chiropractic")["struck_quotes"]["status"], trace.TRACED)

    def test_says_none_when_no_step_touched_the_cell(self):
        records = self.cell(*AMBULANCE)
        self.assertEqual(records["notes"], {"status": trace.NONE, "rows": []})
        self.assertEqual(records["struck_quotes"]["status"], trace.NONE)

    def test_says_not_traced_yet_for_records_later_milestones_fill(self):
        records = self.cell(*AMBULANCE)
        self.assertEqual(records["model_citations"]["status"], trace.NOT_YET)
        for name in ("answers", "fact_checks"):
            self.assertEqual(records[name]["status"], trace.NOT_YET, name)
        self.assertEqual(records["draft"]["cms_fields"]["status"], trace.NOT_YET)
        self.assertEqual(records["plan"]["landscape_row"]["status"], trace.NOT_YET)

    def test_lists_the_facts_each_line_used_and_why_the_rule_set_others_aside(self):
        rule = self.cell(*AMBULANCE)["rule"]
        self.assertEqual(rule["code"]["function"], "ambulance")
        self.assertEqual([(n["line"], n["value"], n["presented"]) for n in rule["lines"]],
                         [(1, "$325 or 20%", True), (2, "$325", True)])
        self.assertIn("ae326523b26fbf5e", [f["fact_id"] for f in rule["lines"][0]["facts"]])
        self.assertEqual([f["fact_id"] for f in rule["lines"][1]["facts"]], ["dcc6a0f01e6c0594"])
        aside = {f["fact_id"]: f["reasons"] for f in rule["set_aside"]}
        self.assertEqual(aside["aab50a29be55fef4"], ["SB ranks below EOC"])

    def test_a_line_without_a_document_fact_is_not_presented(self):
        (plan_id, col), = self.db.execute("SELECT plan_id, col FROM rule_line WHERE presented = 0 LIMIT 1").fetchall()
        lines = self.cell("main", plan_id, col)["rule"]["lines"]
        self.assertTrue(any(not n["presented"] for n in lines))
        for n in lines:
            self.assertEqual(n["presented"], any(f["source"] in ("SB", "EOC") for f in n["facts"]), n)

    def test_says_why_the_pinned_version_holds_a_cell(self):
        rule = self.cell("main", "H5439-010-0", "K_tests_labs")["rule"]
        self.assertEqual(rule["held"], present.HELD_1[("K_tests_labs", "H5439-010-0")])

    def test_lists_the_added_facts_a_rule_considered(self):
        added = self.cell("main", "H1372-003-0", "AB_ambulance")["added_facts"]
        self.assertEqual([(f["fact_id"], f["origin"]) for f in added["rows"]], [("279e0b3e50b5b24d", "added")])
        self.assertEqual(self.cell(*AMBULANCE)["added_facts"]["status"], trace.NONE)

    def test_a_column_without_a_rule_has_no_rule_record(self):
        self.assertNotIn("C_premium", present.COLUMNS)
        self.assertEqual(self.cell("main", "H1036-153-0", "C_premium")["rule"]["status"], trace.NONE)

    def test_lists_the_cms_fields_where_cms_sources_has_them(self):
        cms = self.cell("main", "H3805-048-0", "D_premium_full_extra_help")["draft"]["cms_fields"]
        self.assertEqual(cms["status"], trace.TRACED)
        self.assertIn("Part C Premium", [r["field"] for r in cms["rows"]])

    def test_lists_the_plans_documents_with_their_text_hashes(self):
        documents = self.cell(*AMBULANCE)["documents"]["documents"]
        eoc = [d for d in documents if d["kind"] == "EOC"]
        self.assertEqual(eoc[0]["url"], "https://assets.humana.com/is/content/humana/H1036153000EOC27pdf")
        self.assertTrue(eoc[0]["sha256"].startswith("64e05773e847b56e"))
        self.assertEqual(len(eoc[0]["text"]["layout"]), 64)

    def test_model_citations_name_their_step_and_say_answers_come_later(self):
        model = self.cell("main", "H3805-048-0", "T_chiropractic")["model_citations"]
        self.assertEqual(model["status"], trace.TRACED)
        self.assertEqual({r["step"] for r in model["rows"]}, {"blanks"})
        self.assertEqual({r["answers"]["status"] for r in model["rows"]}, {trace.NOT_YET})
        self.assertNotIn("answers", self.cell("main", "H3805-048-0", "T_chiropractic")["layers"]["live"]["citations"][0])

    def test_xref_citations_have_no_recorded_answer(self):
        rows = self.cell("main", "H3805-048-0", "E_moop")["model_citations"]["rows"]
        self.assertIn(("xref", trace.NOT_RECORDED), [(r["step"], r["answers"]["status"]) for r in rows])

    def test_names_the_build_commit_and_pins(self):
        build = self.cell(*AMBULANCE)["build"]
        self.assertEqual(build["sha"], SHA)
        self.assertEqual(build["steps"]["present"], 2)
        self.assertEqual(self.cell(*AMBULANCE)["draft"]["code"]["url"],
                         f"{trace.REPO_URL}/blob/{SHA}/pipeline/main_chart.py")

    def test_rejects_an_unknown_cell(self):
        with self.assertRaises(LookupError):
            self.cell("main", "H1036-153-0", "ZZ_nothing")


if __name__ == "__main__":
    unittest.main()
