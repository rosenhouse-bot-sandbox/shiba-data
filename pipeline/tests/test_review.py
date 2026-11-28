import contextlib, functools, io, json, os, pathlib, shutil, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ask, built, document_facts, extract, facts, sheets, present, review, years

DATA = years.data_dir(years.LIVE)
PLAN = "H2923-001-0"


def fact(plan_id=PLAN, source="EOC", **more):
    """A fact the X-ray rule cites for PLAN, or an uncited one with benefit radiation_therapy."""
    doc = next(d for d in sheets.rows(DATA / "generated/documents_checked.csv")
               if plan_id in d["plan_ids"].split(";") and d["kind"] == source)
    row = dict.fromkeys(facts.COLUMNS, "")
    row.update(dict(plan_id=plan_id, source=source, benefit="imaging.xray", setting="office.pcp", network="in", covered_by="medicare",
                    cost_kind="copay", amount="$1", doc_sha=doc["sha256"], page="1",
                    quotes=json.dumps(["x"])), **more)
    row["fact_id"] = facts.fact_id(row)
    return row


def answering(rejected=(), asked=None):
    """An answer function that accepts each fact unless its task has one of the rejected texts."""
    def answer(task_dir, model, effort):
        for name in os.listdir(task_dir):
            if name.endswith(".md"):
                text = pathlib.Path(task_dir, name).read_text()
                ok = not any(r in text for r in rejected)
                if asked is not None:
                    asked.append(name)
                with open(os.path.join(task_dir, name[:-3] + ".json"), "w") as f:
                    json.dump([{"id": 0, "ok": ok, "reason": "test"}], f)
    return answer


# The present version whose held cells and facts the reviewer sees.
HELD = 1


@functools.cache
def committed_facts():
    return facts.read(DATA / "machine/document_facts.csv")


@built.check
class ToReviewTest(unittest.TestCase):
    def test_reviews_only_facts_that_a_cell_cites(self):
        cited, uncited = fact(), fact(benefit="radiation_therapy", amount="$2")
        self.assertEqual(review.to_review(DATA, [cited, uncited], HELD), [cited])

    def test_reviews_a_duplicated_fact_once(self):
        self.assertEqual(review.to_review(DATA, [fact(), fact()], HELD), [fact()])

    def test_skips_facts_that_only_a_held_cell_cites(self):
        held = fact(plan_id="H6815-038-0", benefit="tests.diagnostic", setting="office.pcp", amount="$9")
        self.assertIn(("K_tests_labs", "H6815-038-0"), present.held(DATA, HELD))
        self.assertEqual(review.to_review(DATA, [held], HELD), [])

    def test_reviews_the_facts_that_a_released_cell_cites(self):
        released = {review.row(f) for f in review.to_review(DATA, committed_facts(), 2)} - review.cited(
            DATA, committed_facts(), HELD)
        self.assertEqual({(r[1], r[2].split(".")[0]) for r in released}, {("H2923-009-0", "tests")})


def kept_file(*rows):
    """A data dir like DATA whose KEPT lists rows."""
    d = tempfile.TemporaryDirectory()
    shutil.copytree(DATA, pathlib.Path(d.name, DATA.name), ignore=shutil.ignore_patterns("answers"))
    data = pathlib.Path(d.name, DATA.name)
    facts.write(str(data / review.KEPT), list(rows))
    return d, data


@built.check
class GateTest(unittest.TestCase):
    def setUp(self):
        self.printed = self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def gate(self, new, answer, cap=10, held=HELD, data=DATA):
        with tempfile.TemporaryDirectory() as work:
            return review.gate(data, None, work, answer, new, dict(reviewer=("m", "e"), review_cap=cap), held,
                               task_of=lambda f: json.dumps(f))

    def outcomes(self, new, answer):
        with tempfile.TemporaryDirectory() as work:
            review.gate(DATA, None, work, answer, new, dict(reviewer=("m", "e"), review_cap=10), HELD,
                        task_of=lambda f: json.dumps(f))
            with open(f"{work}/review/{extract.OUTCOMES}") as f:
                return json.load(f)

    def test_records_each_verdict(self):
        good, bad = fact(), fact(amount="$3", setting="office.specialist")
        self.assertEqual(self.outcomes([good, bad], answering(['"$3"'])), [
            dict(prompt=ask.sha(json.dumps(f)), item=0, fact=extract.named(f), ok=f is good, reason="test", step="reviewer")
            for f in (good, bad)])

    def test_drops_the_facts_the_reviewer_rejects_and_keeps_the_rest(self):
        good, bad, uncited = fact(), fact(amount="$3", setting="office.specialist"), fact(benefit="radiation_therapy")
        kept = self.gate([good, bad, uncited], answering(["$3"]))
        self.assertEqual(kept, [good, uncited])
        self.assertRegex(self.printed.getvalue(), r"Reviewer rejected \S+ \S+ \$3: test")

    def test_keeps_a_rejected_fact_that_the_kept_list_names(self):
        bad = fact(amount="$3")
        d, data = kept_file(bad)
        with d:
            self.assertEqual(self.gate([bad], answering(["$3"]), data=data), [bad])
        self.assertNotIn("Reviewer rejected", self.printed.getvalue())

    def test_asks_about_every_cited_fact(self):
        asked = []
        self.gate([fact(), fact(amount="$4", setting="office.specialist"), fact(benefit="radiation_therapy")],
                  answering((), asked))
        self.assertEqual(len(asked), 2)

    def test_reviews_a_fact_that_a_rejected_fact_hid(self):
        fitness = dict(plan_id="H2406-070-0", benefit="fitness", setting="any", covered_by="supplemental",
                       cost_kind="covered", amount="")
        hiding, hidden = fact(**fitness, quotes='["bad"]'), fact(**fitness, source="SB")
        asked = []
        kept = self.gate([hidden, hiding], answering(["bad"], asked))
        self.assertEqual(len(asked), 2)
        self.assertEqual(kept, [hidden])

    def test_the_cap_counts_every_pass(self):
        fitness = dict(plan_id="H2406-070-0", benefit="fitness", setting="any", covered_by="supplemental",
                       cost_kind="covered", amount="")
        hiding, hidden = fact(**fitness, quotes='["bad"]'), fact(**fitness, source="SB")
        with self.assertRaisesRegex(SystemExit, "needs 2 new answers"):
            self.gate([hidden, hiding], answering(["bad"]), cap=1)

    def test_the_cap_counts_only_answers_not_saved(self):
        new = [fact(amount="$7"), fact(amount="$8", setting="office.specialist")]
        with mock.patch.object(review, "saved", lambda data, model, text, effort: "$7" in text):
            self.gate(new, answering(), cap=1)
            with self.assertRaisesRegex(SystemExit, "needs 1 new answers"):
                self.gate(new, answering(), cap=0)

    def test_the_kept_list_names_only_facts_that_a_cell_cites(self):
        pinned = json.loads((DATA / "steps.json").read_text())["present"]
        self.assertLessEqual(review.kept(DATA), review.cited(DATA, committed_facts(), pinned))


class VersionTest(unittest.TestCase):
    @built.check
    def test_asks_with_the_versions_notes(self):
        notes = {"imaging": "Read this."}
        with tempfile.TemporaryDirectory() as work, mock.patch.object(review, "Doc") as doc, \
                mock.patch.object(extract, "verifier_task", return_value="task") as verifier_task:
            doc.return_value.pages.return_value = {}
            review.gate(DATA, None, work, answering(), [fact()],
                        dict(reviewer=("m", "e"), review_cap=10, notes=notes), HELD)
        self.assertEqual(verifier_task.call_args.args[-1], notes)

    @built.check
    def test_asks_with_the_versions_check_notes_too(self):
        version = dict(notes={"imaging": "Read this.", "dental": "Teeth."}, check_notes={"imaging": "Check this."})
        self.assertEqual(review.checker_notes(version), {"imaging": "Read this. Check this.", "dental": "Teeth."})
        with tempfile.TemporaryDirectory() as work, mock.patch.object(review, "Doc") as doc, \
                mock.patch.object(extract, "verifier_task", return_value="task") as verifier_task:
            doc.return_value.pages.return_value = {}
            review.gate(DATA, None, work, answering(), [fact()],
                        dict(version, reviewer=("m", "e"), review_cap=10), HELD)
        self.assertEqual(verifier_task.call_args.args[-1], review.checker_notes(version))

    @built.check
    def test_asks_with_the_second_looks_notes_and_pages_before(self):
        version = dict(notes={"imaging": "Read this."}, check_notes={"imaging": "Check this."},
                       recheck_notes={"imaging": "Look again.", "dental": "Teeth."}, check_before={"imaging": 1})
        self.assertEqual(review.second_notes(version), {"imaging": "Read this. Check this. Look again.", "dental": "Teeth."})
        with tempfile.TemporaryDirectory() as work, mock.patch.object(review, "Doc") as doc, \
                mock.patch.object(extract, "verifier_task", return_value="task") as verifier_task:
            doc.return_value.pages.return_value = {}
            review.gate(DATA, None, work, answering(), [fact()],
                        dict(version, reviewer=("m", "e"), review_cap=10), HELD)
        self.assertEqual(verifier_task.call_args.args[-1], review.second_notes(version))
        self.assertEqual(verifier_task.call_args.kwargs["before"], {"imaging": 1})

    @built.check
    def test_asks_with_the_plan_notes_of_the_facts_document(self):
        plan_notes = {"imaging": {fact()["plan_id"]: "This plan.", "H0000-000-0": "Not this."}}
        with tempfile.TemporaryDirectory() as work, mock.patch.object(review, "Doc") as doc, \
                mock.patch.object(extract, "verifier_task", return_value="task") as verifier_task:
            doc.return_value.pages.return_value = {}
            review.gate(DATA, None, work, answering(), [fact(), fact(plan_id="H1036-306-0")],
                        dict(reviewer=("m", "e"), review_cap=10, recheck_plan_notes=plan_notes), HELD)
        notes = {c.args[3][0]["plan_id"]: c.args[-1] for c in verifier_task.call_args_list}
        self.assertEqual(notes[fact()["plan_id"]], {"imaging": "This plan."})
        self.assertEqual(notes["H1036-306-0"], {})

    @built.check
    def test_asks_with_the_plan_notes_of_every_reader_then_of_second_readers(self):
        plan = fact()["plan_id"]
        with tempfile.TemporaryDirectory() as work, mock.patch.object(review, "Doc") as doc, \
                mock.patch.object(extract, "verifier_task", return_value="task") as verifier_task:
            doc.return_value.pages.return_value = {}
            review.gate(DATA, None, work, answering(), [fact()],
                        dict(reviewer=("m", "e"), review_cap=10, plan_notes={"imaging": {plan: "Every reader."}},
                             recheck_plan_notes={"imaging": {plan: "This plan."}}), HELD)
        notes = {c.args[3][0]["plan_id"]: c.args[-1] for c in verifier_task.call_args_list}
        self.assertEqual(notes[plan], {"imaging": "Every reader. This plan."})

    @built.check
    def test_asks_about_a_fact_of_a_kind_about_one_benefit_with_its_kind_note_if_the_version_says(self):
        dental = fact(plan_id="H5439-019-0", source="DENTAL", benefit="dental.comprehensive")
        eoc = fact(plan_id="H5439-019-0", benefit="dental.comprehensive")
        version = dict(notes={"dental": "Teeth."}, kinds={"dental": {"DENTAL": "Kind note."}},
                       plan_notes={"dental": {"H5439-019-0": "This plan.", "H5439-015-0": "Another plan."}})
        with mock.patch.object(review, "Doc"), \
                mock.patch.object(extract, "verifier_task", return_value="task") as verifier_task:
            sees = review.reviewer_task(DATA, None, dict(version, reviewer_sees_kinds=True))
            sees(dental), sees(eoc)
            review.reviewer_task(DATA, None, version)(dental)
        self.assertEqual([c.args[-1] for c in verifier_task.call_args_list],
                         [{"dental": "Kind note."}, {"dental": "Teeth. This plan."}, {"dental": "Teeth. This plan."}])

    def test_plan_notes_keep_the_order_the_version_gives_its_plans(self):
        plans = [f"H{n:04}-000-0" for n in range(20)]
        version = dict(plan_notes={"imaging": {p: p for p in plans}}, recheck_plan_notes={"imaging": {plans[0]: "Again."}})
        self.assertEqual(list(review.plan_notes(version)["imaging"]), plans)

    @built.check
    def test_shows_the_pages_after_that_the_version_asks_for(self):
        with tempfile.TemporaryDirectory() as work, mock.patch.object(review, "Doc") as doc, \
                mock.patch.object(extract, "verifier_task", return_value="task") as verifier_task:
            doc.return_value.pages.return_value = {}
            review.gate(DATA, None, work, answering(), [fact()],
                        dict(reviewer=("m", "e"), review_cap=10, check_after={"imaging": 1}), HELD)
        self.assertEqual(verifier_task.call_args.kwargs["after"], {"imaging": 1})

    def test_version_11_is_10_with_a_reviewer(self):
        v = document_facts.VERSIONS[11]
        self.assertEqual(dict(v, reviewer=None, review_cap=None), dict(document_facts.VERSIONS[10], reviewer=None,
                                                                         review_cap=None))
        self.assertEqual(v["reviewer"], ("claude-opus-5-5", "high"))


if __name__ == "__main__":
    unittest.main()
