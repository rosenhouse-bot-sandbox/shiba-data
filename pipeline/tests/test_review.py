import contextlib, io, json, os, pathlib, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ask, document_facts, extract, facts, layers, present, review, years

DATA = years.data_dir(years.LIVE)
COMMITTED = facts.read(DATA / "machine/document_facts.csv")
PLAN = "H2923-001-0"


def fact(plan_id=PLAN, source="EOC", **more):
    """A fact the X-ray rule cites for PLAN, or an uncited one with benefit radiation_therapy."""
    doc = next(d for d in layers.rows(DATA / "generated/documents_checked.csv")
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


HELD = present.held(DATA, 1)
TRUSTED = review.cited(DATA, COMMITTED, HELD)


class ToReviewTest(unittest.TestCase):
    def test_reviews_only_untrusted_facts_that_a_cell_cites(self):
        cited, uncited = fact(), fact(benefit="radiation_therapy", amount="$2")
        self.assertEqual(review.to_review(DATA, TRUSTED, COMMITTED + [cited, uncited], HELD), [cited])

    def test_reviews_a_duplicated_fact_once(self):
        self.assertEqual(review.to_review(DATA, TRUSTED, COMMITTED + [fact(), fact()], HELD), [fact()])

    def test_skips_facts_that_only_a_held_cell_cites(self):
        held = fact(plan_id="H6815-038-0", benefit="tests.diagnostic", setting="office.pcp", amount="$9")
        self.assertIn(("K_tests_labs", "H6815-038-0"), HELD)
        self.assertEqual(review.to_review(DATA, TRUSTED, COMMITTED + [held], HELD), [])

    def test_reviews_the_facts_that_a_released_cell_cites(self):
        released = review.to_review(DATA, TRUSTED, COMMITTED, present.held(DATA, 2))
        self.assertEqual({(f["plan_id"], f["benefit"].split(".")[0]) for f in released}, {("H2923-009-0", "tests")})

    def test_reviews_the_facts_that_a_dvha_cell_cites(self):
        released = review.to_review(DATA, review.cited(DATA, COMMITTED, present.held(DATA, 2)), COMMITTED,
                                    present.held(DATA, 3))
        self.assertEqual({f["benefit"] for f in released}, {"plan_premium"})

    def test_an_unchanged_fact_set_needs_no_review(self):
        self.assertEqual(review.to_review(DATA, TRUSTED, COMMITTED, HELD), [])


class TrustedTest(unittest.TestCase):
    def test_before_the_first_review_trusts_the_old_facts_that_a_cell_cites(self):
        with tempfile.TemporaryDirectory() as d:
            data = pathlib.Path(d)
            (data / "machine").mkdir()
            with mock.patch.object(review, "cited", lambda data, document, held: {review.row(document[0])} if held is HELD else set()):
                self.assertEqual(review.trusted(data, [fact(), fact(amount="$2")], HELD), {review.row(fact())})
            facts.write(str(data / review.REVIEWED), [fact(amount="$3")])
            self.assertEqual(review.trusted(data, [fact()], HELD), {review.row(fact(amount="$3"))})


class GateTest(unittest.TestCase):
    def setUp(self):
        self.printed = self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def gate(self, trusted, new, answer, cap=10, held=HELD):
        with tempfile.TemporaryDirectory() as work:
            return review.gate(DATA, None, work, answer, trusted, new, dict(reviewer=("m", "e"), review_cap=cap), held,
                               task_of=lambda f: json.dumps(f))

    def outcomes(self, new, answer, saved=lambda *_: False):
        with tempfile.TemporaryDirectory() as work, mock.patch.object(review, "saved", saved):
            review.gate(DATA, None, work, answer, TRUSTED, new, dict(reviewer=("m", "e"), review_cap=10), HELD,
                        task_of=lambda f: json.dumps(f))
            with open(f"{work}/review/{extract.OUTCOMES}") as f:
                return json.load(f)

    def test_records_each_verdict(self):
        good, bad = fact(), fact(amount="$3")
        self.assertEqual(self.outcomes(COMMITTED + [good, bad], answering(['"$3"'])), [
            dict(prompt=ask.sha(json.dumps(f)), item=0, fact=extract.named(f), ok=f is good, reason="test", earlier=False)
            for f in (good, bad)])

    def test_records_the_saved_verdicts_of_trusted_facts(self):
        old = next(f for f in COMMITTED if review.row(f) in TRUSTED)
        asked = []
        got = self.outcomes(COMMITTED, answering((), asked), saved=lambda data, model, text, effort: text == json.dumps(old))
        self.assertEqual(got, [dict(prompt=ask.sha(json.dumps(old)), item=0, fact=extract.named(old), ok=True, reason="test",
                                    earlier=True)])
        self.assertEqual(asked, ["v-0.md"])

    def test_gives_saved_verdicts_only_for_trusted_facts(self):
        uncited = fact(benefit="radiation_therapy", amount="$2")
        got = self.outcomes(COMMITTED + [uncited], answering(), saved=lambda data, model, text, effort: text == json.dumps(uncited))
        self.assertEqual(got, [])

    def test_drops_the_facts_the_reviewer_rejects_and_keeps_the_rest(self):
        good, bad, uncited = fact(), fact(amount="$3", setting="office.specialist"), fact(benefit="radiation_therapy")
        kept, trusted = self.gate(TRUSTED, COMMITTED + [good, bad, uncited], answering(["$3"]))
        self.assertIn(good, kept)
        self.assertIn(uncited, kept)
        self.assertNotIn(bad, kept)
        self.assertRegex(self.printed.getvalue(), r"Reviewer rejected \S+ \S+ \$3: test")
        self.assertIn(good, trusted)
        self.assertNotIn(uncited, trusted)

    def test_keeps_trusting_a_kept_fact_that_no_cell_cites(self):
        uncited = fact(benefit="radiation_therapy")
        _, trusted = self.gate(TRUSTED | {review.row(uncited)}, COMMITTED + [uncited], answering())
        self.assertIn(uncited, trusted)

    def test_trusts_the_facts_a_released_cell_cites_once_reviewed(self):
        asked = []
        _, trusted = self.gate(TRUSTED, COMMITTED, answering((), asked), held=present.held(DATA, 2))
        released = review.to_review(DATA, TRUSTED, COMMITTED, present.held(DATA, 2))
        self.assertEqual(len(asked), len(released))
        self.assertLessEqual({review.row(f) for f in released}, {review.row(f) for f in trusted})

    def test_gives_each_verdict_to_its_own_fact(self):
        a, b = fact(amount="$1"), fact(amount="$4")
        kept, _ = self.gate(TRUSTED, COMMITTED + [a, b], answering(["$4"]))
        self.assertIn(a, kept)
        self.assertNotIn(b, kept)

    def test_reviews_a_fact_once_a_cell_cites_it(self):
        fitness = dict(plan_id="H2406-070-0", benefit="fitness", setting="any", covered_by="supplemental",
                       cost_kind="covered", amount="")
        hiding, hidden = fact(**fitness, quotes='["bad"]'), fact(**fitness, source="SB")
        _, trusted = self.gate(TRUSTED, COMMITTED + [hidden, hiding], answering())
        asked = []
        self.gate({review.row(f) for f in trusted}, COMMITTED + [hidden], answering((), asked))
        self.assertEqual(len(asked), 1)

    def test_trusts_what_it_kept_so_a_rerun_asks_nothing(self):
        kept, trusted = self.gate(TRUSTED, COMMITTED + [fact()], answering())
        asked = []
        self.assertEqual(self.gate({review.row(f) for f in trusted}, kept, answering((), asked))[0], kept)
        self.assertEqual(asked, [])

    def test_reviews_a_fact_that_a_rejected_fact_hid(self):
        fitness = dict(plan_id="H2406-070-0", benefit="fitness", setting="any", covered_by="supplemental",
                       cost_kind="covered", amount="")
        hiding, hidden = fact(**fitness, quotes='["bad"]'), fact(**fitness, source="SB")
        asked = []
        kept, _ = self.gate(TRUSTED, COMMITTED + [hidden, hiding], answering(["bad"], asked))
        self.assertEqual(len(asked), 2)
        self.assertIn(hidden, kept)
        self.assertNotIn(hiding, kept)

    def test_the_cap_counts_every_pass(self):
        fitness = dict(plan_id="H2406-070-0", benefit="fitness", setting="any", covered_by="supplemental",
                       cost_kind="covered", amount="")
        hiding, hidden = fact(**fitness, quotes='["bad"]'), fact(**fitness, source="SB")
        with self.assertRaisesRegex(SystemExit, "needs 2 new answers"):
            self.gate(TRUSTED, COMMITTED + [hidden, hiding], answering(["bad"]), cap=1)

    def test_stops_when_more_new_facts_need_review_than_the_cap(self):
        new = [fact(amount=f"${n}", setting=s) for n, s in ((7, "office.pcp"), (8, "office.specialist"))]
        self.gate(TRUSTED, COMMITTED + new, answering(), cap=2)
        with self.assertRaisesRegex(SystemExit, "needs 2 new answers"):
            self.gate(TRUSTED, COMMITTED + new, answering(), cap=1)

    def test_the_cap_counts_only_answers_not_saved(self):
        new = [fact(amount="$7"), fact(amount="$8")]
        with mock.patch.object(review, "saved", lambda data, model, text, effort: "$7" in text):
            self.gate(TRUSTED, COMMITTED + new, answering(), cap=1)
            with self.assertRaisesRegex(SystemExit, "needs 1 new answers"):
                self.gate(TRUSTED, COMMITTED + new, answering(), cap=0)


class VersionTest(unittest.TestCase):
    def test_asks_with_the_versions_notes(self):
        notes = {"imaging": "Read this."}
        with tempfile.TemporaryDirectory() as work, mock.patch.object(review, "Doc") as doc, \
                mock.patch.object(extract, "verifier_task", return_value="task") as verifier_task:
            doc.return_value.pages.return_value = {}
            review.gate(DATA, None, work, answering(), TRUSTED, COMMITTED + [fact()],
                        dict(reviewer=("m", "e"), review_cap=10, notes=notes), HELD)
        self.assertEqual(verifier_task.call_args.args[-1], notes)

    def test_asks_with_the_versions_check_notes_too(self):
        version = dict(notes={"imaging": "Read this.", "dental": "Teeth."}, check_notes={"imaging": "Check this."})
        self.assertEqual(review.checker_notes(version), {"imaging": "Read this. Check this.", "dental": "Teeth."})
        with tempfile.TemporaryDirectory() as work, mock.patch.object(review, "Doc") as doc, \
                mock.patch.object(extract, "verifier_task", return_value="task") as verifier_task:
            doc.return_value.pages.return_value = {}
            review.gate(DATA, None, work, answering(), TRUSTED, COMMITTED + [fact()],
                        dict(version, reviewer=("m", "e"), review_cap=10), HELD)
        self.assertEqual(verifier_task.call_args.args[-1], review.checker_notes(version))

    def test_asks_with_the_second_looks_notes_and_pages_before(self):
        version = dict(notes={"imaging": "Read this."}, check_notes={"imaging": "Check this."},
                       recheck_notes={"imaging": "Look again.", "dental": "Teeth."}, check_before={"imaging": 1})
        self.assertEqual(review.second_notes(version), {"imaging": "Read this. Check this. Look again.", "dental": "Teeth."})
        with tempfile.TemporaryDirectory() as work, mock.patch.object(review, "Doc") as doc, \
                mock.patch.object(extract, "verifier_task", return_value="task") as verifier_task:
            doc.return_value.pages.return_value = {}
            review.gate(DATA, None, work, answering(), TRUSTED, COMMITTED + [fact()],
                        dict(version, reviewer=("m", "e"), review_cap=10), HELD)
        self.assertEqual(verifier_task.call_args.args[-1], review.second_notes(version))
        self.assertEqual(verifier_task.call_args.kwargs["before"], {"imaging": 1})

    def test_shows_the_pages_after_that_the_version_asks_for(self):
        with tempfile.TemporaryDirectory() as work, mock.patch.object(review, "Doc") as doc, \
                mock.patch.object(extract, "verifier_task", return_value="task") as verifier_task:
            doc.return_value.pages.return_value = {}
            review.gate(DATA, None, work, answering(), TRUSTED, COMMITTED + [fact()],
                        dict(reviewer=("m", "e"), review_cap=10, check_after={"imaging": 1}), HELD)
        self.assertEqual(verifier_task.call_args.kwargs["after"], {"imaging": 1})

    def test_version_11_is_10_with_a_reviewer(self):
        v = document_facts.VERSIONS[11]
        self.assertEqual(dict(v, reviewer=None, review_cap=None), dict(document_facts.VERSIONS[10], reviewer=None,
                                                                         review_cap=None))
        self.assertEqual(v["reviewer"], ("claude-opus-5-5", "high"))


if __name__ == "__main__":
    unittest.main()
