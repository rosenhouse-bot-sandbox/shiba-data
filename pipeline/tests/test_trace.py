import csv, hashlib, json, os, shutil, sqlite3, subprocess, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), os.path.join(os.path.dirname(os.path.dirname(HERE)), "web")]
import ask, blobs, build, document_facts, extract, fields, layers, present, reads, run, trace, years

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
        path = os.path.join(cls.tmp.name, "trace", "2027.sqlite")  # as CI names it
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
                    self.assertLessEqual(statuses(records), STATUSES - {trace.NOT_YET})

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

    def test_check_passes_when_every_main_cell_is_traced(self):
        trace.check(self.db)

    def test_check_names_each_record_left_not_traced_yet(self):
        def cell(db, sheet, plan_id, col):
            return {"draft": {"status": trace.TRACED, "cms_fields": {"status": trace.NOT_YET}}}
        with mock.patch.object(trace, "cell", cell), self.assertRaisesRegex(SystemExit, "H1036-153-0 AB_ambulance: draft/cms_fields"):
            trace.check(self.db)

    def test_says_none_when_no_model_step_cited_the_cell(self):
        self.assertEqual(self.cell(*AMBULANCE)["model_citations"], {"status": trace.NONE, "rows": []})

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
        records = self.cell("main", "H1036-153-0", "C_premium")
        self.assertEqual((records["rule"]["status"], records["answers"]["status"]), (trace.NONE, trace.NONE))

    def test_lists_the_pbp_fields_a_cell_read(self):
        cms = self.cell(*AMBULANCE)["draft"]["cms_fields"]
        self.assertIn(("pbp_b10_amb_trans", "pbp_b10a_copay_gas_amt_min", "325.00"),
                      [(r["file"], r["field"], r["value"]) for r in cms["rows"]])
        self.assertIn(("pbp_b10_amb_trans", reads.ROWS, "1"), [(r["file"], r["field"], r["value"]) for r in cms["rows"]])

    def test_lists_the_landscape_fields_behind_a_plans_csv_field(self):
        cms = self.cell("main", "H3805-048-0", "D_premium_full_extra_help")["draft"]["cms_fields"]
        self.assertEqual([r["field"] for r in cms["rows"]], ["premium_full_extra_help"])
        self.assertIn("Part C Premium", [n["field"] for n in cms["rows"][0]["landscape"]])

    def test_says_none_for_a_cell_that_read_no_cms_field(self):
        self.assertEqual(self.cell("main", "H3805-048-0", "U_naturopath")["draft"]["cms_fields"]["status"], trace.NONE)

    def test_lists_the_landscape_fields_behind_the_plan(self):
        fields = self.cell(*AMBULANCE)["plan"]["landscape_row"]["fields"]
        self.assertIn(("Plan Name", "Humana Total Complete (HMO)"), [(f["field"], f["value"]) for f in fields])

    def test_lists_the_cms_fields_where_cms_sources_has_them_on_dvha(self):
        cms = self.cell("dvha", "H3805-048-0", "D_premium_full_extra_help")["draft"]["cms_fields"]
        self.assertEqual(cms["status"], trace.TRACED)
        self.assertIn("Part C Premium", [r["field"] for r in cms["rows"]])

    def test_lists_the_plans_documents_with_their_text_hashes(self):
        documents = self.cell(*AMBULANCE)["documents"]["documents"]
        eoc = [d for d in documents if d["kind"] == "EOC"]
        self.assertEqual(eoc[0]["url"], "https://assets.humana.com/is/content/humana/H1036153000EOC27pdf")
        self.assertTrue(eoc[0]["sha256"].startswith("64e05773e847b56e"))
        self.assertEqual(len(eoc[0]["text"]["layout"]), 64)

    def test_model_citations_name_their_step_and_need_a_run_for_their_answers(self):
        model = self.cell("main", "H3805-048-0", "T_chiropractic")["model_citations"]
        self.assertEqual(model["status"], trace.TRACED)
        self.assertEqual({r["step"] for r in model["rows"]}, {"blanks"})
        self.assertEqual({r["answers"]["status"] for r in model["rows"]}, {trace.NOT_RECORDED})
        self.assertEqual(self.cell("main", "H3805-048-0", "T_chiropractic")["answers"]["status"], trace.NOT_RECORDED)
        self.assertNotIn("answers", self.cell("main", "H3805-048-0", "T_chiropractic")["layers"]["live"]["citations"][0])

    def test_xref_citations_have_no_recorded_answer(self):
        rows = self.cell("main", "H3805-048-0", "E_moop")["model_citations"]["rows"]
        self.assertIn(("xref", trace.NOT_RECORDED), [(r["step"], r["answers"]["status"]) for r in rows])

    def test_names_the_build_commit_and_pins(self):
        build = self.cell(*AMBULANCE)["build"]
        self.assertEqual(build["sha"], SHA)
        self.assertEqual(build["steps"], json.loads((years.data_dir() / "steps.json").read_text()))
        self.assertEqual(self.cell(*AMBULANCE)["draft"]["code"]["url"],
                         f"{trace.REPO_URL}/blob/{SHA}/pipeline/main_chart.py")

    def test_exports_each_main_cells_records_once_by_content_without_the_commit(self):
        with tempfile.TemporaryDirectory() as out:
            trace.export(self.db, out)
            with open(os.path.join(out, f"{SHA}.json")) as f:
                manifest = json.load(f)
            texts = {}
            for name in os.listdir(os.path.join(out, "cells")):
                with open(os.path.join(out, "cells", name), encoding="utf-8") as f:
                    texts[name] = f.read()
        main = self.db.execute("SELECT count(*) FROM draft_cell WHERE sheet = 'main'").fetchone()[0]
        self.assertEqual((manifest["sha"], manifest["year"], len(manifest["cells"])), (SHA, years.LIVE, main))
        self.assertEqual(set(texts), {f"{h}.json" for h in manifest["cells"].values()})
        for name, text in texts.items():
            self.assertEqual(name, hashlib.sha256(text.encode()).hexdigest() + ".json")
            self.assertNotIn(SHA, text)
        text = texts[manifest["cells"]["/".join(AMBULANCE[1:])] + ".json"]
        self.assertEqual(json.loads(text.replace(trace.COMMIT, SHA)), self.cell(*AMBULANCE))

    def test_rejects_an_unknown_cell(self):
        with self.assertRaises(LookupError):
            self.cell("main", "H1036-153-0", "ZZ_nothing")

    def test_trace_and_run_start_as_scripts(self):
        for module in (trace, run):
            done = subprocess.run([sys.executable, "-I", module.__file__], capture_output=True, text=True)
            self.assertEqual(done.stderr.strip(), module.__doc__.strip())


class RunTest(unittest.TestCase):
    """Builds from a copy of the year without its saved answers, and a run that asked one task."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root, self.work = os.path.join(tmp.name, "data"), os.path.join(tmp.name, "work")
        self.data = os.path.join(self.root, str(years.LIVE))
        shutil.copytree(years.data_dir(), self.data, ignore=shutil.ignore_patterns("answers", "rebuilds", "evaluations"))
        os.makedirs(os.path.join(self.data, "answers"))
        os.makedirs(os.path.join(self.work, "facts/ambulance/read"))
        with open(os.path.join(self.work, "facts/ambulance/read/doc.md"), "w") as f:
            f.write("Read the facts.")
        key = ask.key(run.READER, "Read the facts.", "high")
        ask.write(os.path.join(self.data, "answers", f"{key}.json"),
                  {"model": run.READER, "effort": "high", "task": "doc.md", "reply": "[]", "usage": {"input_tokens": 9}})
        with mock.patch.dict(os.environ, {"SHIBA_DATA": self.root}):
            run.Answers(years.data_dir(), None, self.work)(os.path.join(self.work, "facts/ambulance/read"), run.READER, "high")
        self.key = key

    def build(self):
        path = os.path.join(self.work, "trace.sqlite")
        with mock.patch.dict(os.environ, {"SHIBA_DATA": self.root}):
            trace.build(years.LIVE, path, SHA, self.work)
        db = sqlite3.connect(path)
        self.addCleanup(db.close)
        return db


class AnswersTest(RunTest):
    def test_loads_each_prompt_and_its_saved_answer(self):
        db = self.build()
        self.assertEqual(db.execute("SELECT answer_key, dir, task FROM task").fetchall(),
                         [(self.key, "facts/ambulance/read", "doc.md")])
        self.assertEqual(db.execute("SELECT model, effort, reply FROM answer").fetchall(), [(run.READER, "high", "[]")])

    def test_keeps_each_models_answer_to_one_prompt(self):
        os.makedirs(os.path.join(self.work, "facts/ambulance/again"))
        shutil.copy(os.path.join(self.work, "facts/ambulance/read/doc.md"), os.path.join(self.work, "facts/ambulance/again"))
        key = ask.key(run.VERIFIER, "Read the facts.")
        ask.write(os.path.join(self.data, "answers", f"{key}.json"),
                  {"model": run.VERIFIER, "task": "doc.md", "reply": "[1]", "usage": {}})
        with mock.patch.dict(os.environ, {"SHIBA_DATA": self.root}):
            run.Answers(years.data_dir(), None, self.work)(os.path.join(self.work, "facts/ambulance/again"), run.VERIFIER)
        db = self.build()
        self.assertEqual(db.execute("SELECT answer_key, dir FROM task ORDER BY dir").fetchall(),
                         [(key, "facts/ambulance/again"), (self.key, "facts/ambulance/read")])
        self.assertEqual(db.execute("SELECT count(*) FROM answer").fetchall(), [(2,)])

    def test_fails_when_a_prompt_does_not_hash_to_its_answers_key(self):
        with open(os.path.join(self.work, blobs.LEDGER)) as f:
            prompt = next(csv.DictReader(f))["prompt"]
        with open(os.path.join(self.work, blobs.PROMPTS, prompt), "a") as f:
            f.write("changed")
        with self.assertRaisesRegex(ValueError, "does not hash to the key of facts/ambulance/read/doc.md"):
            self.build()

    def test_without_a_run_the_checks_are_not_recorded(self):
        with mock.patch.dict(os.environ, {"SHIBA_DATA": self.root}):
            path = os.path.join(self.work, "plain.sqlite")
            trace.build(years.LIVE, path, SHA)
        db = sqlite3.connect(path)
        self.addCleanup(db.close)
        records = trace.cell(db, *AMBULANCE)
        self.assertEqual((records["answers"]["status"], records["fact_checks"]["status"]),
                         (trace.NOT_RECORDED, trace.NOT_RECORDED))
        self.assertEqual({d["unlinked_answers"]["status"] for d in records["documents"]["documents"]}, {trace.NOT_RECORDED})

    def test_a_run_without_check_outcomes_records_no_answers_for_a_rule(self):
        records = trace.cell(self.build(), *AMBULANCE)
        self.assertEqual((records["answers"]["status"], records["fact_checks"]["status"]),
                         (trace.NOT_RECORDED, trace.NOT_RECORDED))


EOC = "64e05773e847b56e0eeb5425979d54996c5f1975307c9ae186f5af4fecafc44c"
STATED = dict(plan_id="H1036-153-0", benefit="ambulance", amount="$325")
CHECKED = dict(fact_id="dcc6a0f01e6c0594", source="EOC", doc_sha=EOC, page="46")
PACKAGES_EOC = "0050f865534f41bbbc1c785cb45951a27165b9d114a54a0680f353a81aeed66d"
DENTAL_PACKAGE = dict(fact_id="d7df1ed404d93051", source="EOC", doc_sha=PACKAGES_EOC, page="15")


class FactChecksTest(RunTest):
    """A run whose reader stated a fact the Ambulance rule uses, and three answers it rejected."""

    def setUp(self):
        super().setUp()
        self.prompt, self.check = ask.sha("Read the facts."), ask.sha("Check the facts.")
        os.makedirs(os.path.join(self.work, "facts/ambulance/check"))
        with open(os.path.join(self.work, "facts/ambulance/check/v-doc.md"), "w") as f:
            f.write("Check the facts.")
        self.check_key = ask.key(run.VERIFIER, "Check the facts.", "medium")
        ask.write(os.path.join(self.data, "answers", f"{self.check_key}.json"),
                  {"model": run.VERIFIER, "effort": "medium", "task": "v-doc.md", "reply": "[]", "usage": {}})
        with mock.patch.dict(os.environ, {"SHIBA_DATA": self.root}):
            run.Answers(years.data_dir(), None, self.work)(os.path.join(self.work, "facts/ambulance/check"), run.VERIFIER,
                                                           "medium")
        outcomes = {
            "facts/ambulance/read": [
                dict(prompt=self.prompt, item=0, doc_sha=EOC, stated=STATED, problem=None, fact=CHECKED),
                dict(prompt=self.prompt, item=1, doc_sha=EOC, stated=dict(STATED, benefit="ambulance.air", amount="$9"),
                     problem="no quote shows $9", fact=None),
                dict(prompt=self.prompt, item=2, doc_sha=EOC, stated=dict(STATED, plan_id="H0000-000-0"),
                     problem="plan_id: this document covers H1036-153-0", fact=None),
                dict(prompt=self.prompt, item=3, doc_sha=EOC, stated="(not JSON)", problem="not an object", fact=None),
                dict(prompt=self.prompt, item=4, doc_sha=PACKAGES_EOC, stated=dict(plan_id="H1036-323-0", benefit="dental"),
                     problem=None, fact=DENTAL_PACKAGE),
                dict(prompt=self.prompt, item=5, doc_sha=EOC, stated=dict(STATED, benefit="ambulance.boat"),
                     problem="benefit: ambulance.boat is not in ambulance", fact=None)],
            "facts/ambulance/check": [
                dict(prompt=self.check, item=0, decoy=True, shown=dict(STATED, network="in"), fact=None, ok=False,
                     reason="wrong network"),
                dict(prompt=self.check, item=1, decoy=False, shown=STATED, fact=CHECKED, ok=True, reason="page 46 says so")],
            "facts/review": []}
        for folder, rows in outcomes.items():
            os.makedirs(os.path.join(self.work, folder), exist_ok=True)
            with open(os.path.join(self.work, folder, extract.OUTCOMES), "w") as f:
                json.dump(rows, f)
        self.records = trace.cell(self.build(), *AMBULANCE)

    def test_lists_each_answer_behind_the_cells_checks_with_its_prompts(self):
        answers = self.records["answers"]
        self.assertEqual(answers["status"], trace.TRACED)
        read, check = answers["rows"]
        self.assertEqual((read["key"], read["model"], read["effort"], read["reply"]), (self.key, run.READER, "high", "[]"))
        self.assertEqual(read["prompts"], [dict(prompt=self.prompt, dir="facts/ambulance/read", task="doc.md",
                                                url=trace.PROMPT_URL.format(self.prompt))])
        self.assertEqual((check["key"], check["prompts"][0]["dir"]), (self.check_key, "facts/ambulance/check"))

    def test_follows_a_used_fact_through_each_check(self):
        (checked,) = [r for r in self.records["fact_checks"]["rows"] if r["fact"] == CHECKED]
        self.assertEqual(checked["stated_by"], [dict(prompt=self.prompt, item=0, answer_key=self.key, stated=STATED,
                                                     skipped=None)])
        self.assertEqual(checked["code_check"], "passed")
        self.assertIs(checked["verifier"][0]["ok"], True)
        self.assertIs(checked["verifier"][0]["decoys"][0]["ok"], False)
        self.assertEqual(checked["verifier"], [dict(prompt=self.check, item=1, answer_key=self.check_key, ok=True,
                                                    reason="page 46 says so",
                                                    decoys=[dict(item=0, shown=dict(STATED, network="in"), ok=False,
                                                                 reason="wrong network")])])
        self.assertEqual(checked["reviewer"], {"status": trace.NOT_RECORDED, "note": trace.TRUSTED_WITHOUT_REVIEW})
        self.assertTrue(checked["kept"])

    def test_lists_a_rejected_answer_for_the_cells_plan_and_benefit(self):
        rejected = [r for r in self.records["fact_checks"]["rows"] if r["fact"] is None]
        self.assertEqual(rejected, [dict(fact=None, code_check="no quote shows $9", stated_by=[dict(
            prompt=self.prompt, item=1, answer_key=self.key, stated=dict(STATED, benefit="ambulance.air", amount="$9"),
            skipped=None)], verifier=[], reviewer={"status": trace.NONE}, kept=False)])

    def test_lists_an_answer_with_no_valid_plan_or_benefit_under_its_document(self):
        (eoc,) = [d for d in self.records["documents"]["documents"] if d["sha256"] == EOC]
        self.assertEqual([(r["item"], r["problem"]) for r in eoc["unlinked_answers"]["rows"]],
                         [(2, "plan_id: this document covers H1036-153-0"), (3, "not an object"),
                          (5, "benefit: ambulance.boat is not in ambulance")])

    def test_finds_a_fact_for_another_benefit_that_the_rule_considered(self):
        records = trace.cell(self.build(), "main", "H1036-323-0", "AA_opt_packages")
        (checked,) = [r for r in records["fact_checks"]["rows"] if r["fact"] == DENTAL_PACKAGE]
        self.assertEqual([s["item"] for s in checked["stated_by"]], [4])

    def test_a_considered_fact_no_answer_stated_has_no_recorded_check(self):
        (other,) = [r for r in self.records["fact_checks"]["rows"] if r["fact"] and r["fact"]["fact_id"] == "aab50a29be55fef4"]
        self.assertEqual((other["code_check"], other["stated_by"]), (trace.NOT_RECORDED, []))

    def test_a_work_dir_without_a_run_records_no_checks(self):
        empty = os.path.join(self.work, "empty")
        os.makedirs(empty)
        with mock.patch.dict(os.environ, {"SHIBA_DATA": self.root}):
            trace.build(years.LIVE, os.path.join(empty, "t.sqlite"), SHA, empty)
        db = sqlite3.connect(os.path.join(empty, "t.sqlite"))
        self.addCleanup(db.close)
        records = trace.cell(db, *AMBULANCE)
        self.assertEqual({records[k]["status"] for k in ("answers", "fact_checks")}, {trace.NOT_RECORDED})

    def read_outcomes(self, change):
        path = os.path.join(self.work, "facts/ambulance/read", extract.OUTCOMES)
        with open(path) as f:
            outcomes = json.load(f)
        change(outcomes)
        with open(path, "w") as f:
            json.dump(outcomes, f)

    def test_says_why_the_verifier_skipped_one_statement_of_a_fact(self):
        self.read_outcomes(lambda o: o.append(dict(o[0], item=6, skipped=document_facts.FOUND_BEFORE)))
        (checked,) = [r for r in trace.cell(self.build(), *AMBULANCE)["fact_checks"]["rows"] if r["fact"] == CHECKED]
        self.assertEqual([(s["item"], s["skipped"]) for s in checked["stated_by"]], [(0, None), (6, document_facts.FOUND_BEFORE)])

    def test_keeps_a_stated_plan_or_benefit_only_if_it_is_text(self):
        self.read_outcomes(lambda o: o.append(dict(o[0], item=6, stated=dict(STATED, plan_id=7, benefit=["ambulance"]),
                                                   problem="plan_id: not text", fact=None)))
        self.assertEqual(self.build().execute("SELECT plan_id, benefit FROM stated WHERE item = 6").fetchall(), [(None, None)])

    def test_a_work_dir_with_outcomes_but_no_ledger_records_no_checks(self):
        os.remove(os.path.join(self.work, blobs.LEDGER))
        self.assertEqual(trace.cell(self.build(), *AMBULANCE)["fact_checks"]["status"], trace.NOT_RECORDED)

    def test_checks_only_the_document_facts_a_rule_considered(self):
        records = trace.cell(self.build(), "main", "H1036-153-0", "L_xray_imaging")
        self.assertIn("pbp", {f["origin"] for f in records["rule"]["set_aside"] + records["rule"]["lines"][0]["facts"]})
        self.assertNotIn("PBP", {r["fact"]["source"] for r in records["fact_checks"]["rows"] if r["fact"]})

    def test_a_review_that_repeats_a_verifier_prompt_keeps_both_verdicts(self):
        review = os.path.join(self.work, "facts/review")
        with open(os.path.join(review, "v-0.md"), "w") as f:
            f.write("Check the facts.")
        review_key = ask.key(run.SECOND_VERIFIER, "Check the facts.", "high")
        ask.write(os.path.join(self.data, "answers", f"{review_key}.json"),
                  {"model": run.SECOND_VERIFIER, "effort": "high", "task": "v-0.md", "reply": "[]", "usage": {}})
        with mock.patch.dict(os.environ, {"SHIBA_DATA": self.root}):
            run.Answers(years.data_dir(), None, self.work)(review, run.SECOND_VERIFIER, "high")
        with open(os.path.join(review, extract.OUTCOMES), "w") as f:
            json.dump([dict(prompt=self.check, item=0, fact=CHECKED, ok=False, reason="too vague", earlier=False)], f)
        (checked,) = [r for r in trace.cell(self.build(), *AMBULANCE)["fact_checks"]["rows"] if r["fact"] == CHECKED]
        self.assertEqual([(v["answer_key"], [d["reason"] for d in v["decoys"]]) for v in checked["verifier"]],
                         [(self.check_key, ["wrong network"])])
        self.assertEqual((checked["reviewer"]["answer_key"], checked["reviewer"]["reason"]), (review_key, "too vague"))

    def test_a_fact_the_reviewer_checked_has_its_verdict(self):
        with open(os.path.join(self.work, "facts/review", extract.OUTCOMES), "w") as f:
            json.dump([dict(prompt="d" * 64, item=0, fact=CHECKED, ok=True, reason="fine", earlier=True)], f)
        (checked,) = [r for r in trace.cell(self.build(), *AMBULANCE)["fact_checks"]["rows"] if r["fact"] == CHECKED]
        self.assertEqual(checked["reviewer"], dict(status=trace.TRACED, prompt="d" * 64, answer_key=None, ok=True,
                                                   reason="fine", earlier=True))



class ModelAnswersTest(RunTest):
    """A run whose blanks step asked one reader task for the plan."""

    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.work, "blanks/read"))
        with open(os.path.join(self.work, "blanks/read/H1036-153-0.md"), "w") as f:
            f.write("Find the blanks.")
        self.blanks_key = ask.key(run.READER, "Find the blanks.")
        ask.write(os.path.join(self.data, "answers", f"{self.blanks_key}.json"),
                  {"model": run.READER, "task": "H1036-153-0.md", "reply": '[{"key": "main.U_naturopath"}]', "usage": {}})
        with mock.patch.dict(os.environ, {"SHIBA_DATA": self.root}):
            run.Answers(years.data_dir(), None, self.work)(os.path.join(self.work, "blanks/read"), run.READER)
        self.records = trace.cell(self.build(), "main", "H1036-153-0", "U_naturopath")

    def test_names_the_plans_retry_and_verifier_tasks_but_not_another_plans(self):
        tasks = {"blanks/read": {"H1036-153-0.retry.md": "Find them again."},
                 "blanks/check": {"v-H1036-153-0.md": "Check them.", "v-H1036-306-0.md": "Check another plan."}}
        for folder, texts in tasks.items():
            os.makedirs(os.path.join(self.work, folder), exist_ok=True)
            for name, text in texts.items():
                with open(os.path.join(self.work, folder, name), "w") as f:
                    f.write(text)
                ask.write(os.path.join(self.data, "answers", f"{ask.key(run.READER, text)}.json"),
                          {"model": run.READER, "task": name, "reply": "[]", "usage": {}})
            with mock.patch.dict(os.environ, {"SHIBA_DATA": self.root}):
                run.Answers(years.data_dir(), None, self.work)(os.path.join(self.work, folder), run.READER)
        (row,) = trace.cell(self.build(), "main", "H1036-153-0", "U_naturopath")["model_citations"]["rows"]
        self.assertEqual(sorted(t["task"] for t in row["answers"]["rows"]),
                         ["H1036-153-0.md", "H1036-153-0.retry.md", "v-H1036-153-0.md"])

    def test_names_the_answers_behind_each_model_citation(self):
        prompt = ask.sha("Find the blanks.")
        rows = self.records["model_citations"]["rows"]
        self.assertEqual([r["step"] for r in rows], ["blanks"])
        self.assertEqual(rows[0]["answers"], dict(status=trace.TRACED, rows=[dict(
            dir="blanks/read", task="H1036-153-0.md", prompt=prompt, answer_key=self.blanks_key,
            url=trace.PROMPT_URL.format(prompt))]))
        self.assertEqual([(a["key"], a["reply"]) for a in self.records["answers"]["rows"]],
                         [(self.blanks_key, '[{"key": "main.U_naturopath"}]')])


if __name__ == "__main__":
    unittest.main()
