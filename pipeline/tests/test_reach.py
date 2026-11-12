import os, pathlib, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ask, blobs, reach

DOC = {"id": "aaaaaaaaaaaaaaaa", "plan_ids": ["H1036-001-0", "H1036-002-0"]}
DOCS = {DOC["id"]: DOC}
VERSION = {"recheck": {"hearing": ("H1036-002-0",)}, "targets": {"hearing": ("H1036-002-0",)}}


def row(dir, task, prompt="p"):
    return dict(dir=dir, task=task, model="reader-model", effort="high", key="k", prompt=prompt)


def review(plan_id):
    return 'Judge this.\n\n{"id": 0, "plan_id": "%s", "benefit": "hearing.exam", "amount": "$0"}\n' % plan_id


class TouchedTest(unittest.TestCase):
    def test_a_first_read_is_about_every_plan_of_its_document(self):
        for dir, task in (("hearing/read", f"{DOC['id']}.md"), ("hearing/read", f"{DOC['id']}.retry.md"),
                          ("hearing/check", f"v-{DOC['id']}.md"), ("inherited/hearing/read", f"{DOC['id']}.md")):
            self.assertEqual(reach.touched(row(f"facts/{dir}", task), "", DOCS, VERSION),
                             {("hearing", "H1036-001-0"), ("hearing", "H1036-002-0")})

    def test_a_second_look_is_about_its_documents_rechecked_plans(self):
        decoy = '{"id": 1, "plan_id": "H1036-001-0", "benefit": "hearing.exam"}'
        for dir, task in (("reread", f"{DOC['id']}.md"), ("reread", f"{DOC['id']}.retry.md"), ("recheck", f"v-{DOC['id']}.md")):
            self.assertEqual(reach.touched(row(f"facts/hearing/{dir}", task), decoy, DOCS, VERSION), {("hearing", "H1036-002-0")})

    def test_a_review_is_about_the_plan_and_group_of_its_fact(self):
        self.assertEqual(reach.touched(row("facts/review", "v-0.md"), review("H9003-009-0"), DOCS, VERSION),
                         {("hearing", "H9003-009-0")})

    def test_a_task_about_no_plan_stops_the_check(self):
        with self.assertRaises(SystemExit):
            reach.touched(row("facts/review", "v-0.md"), "no items", DOCS, VERSION)


class OutsideTest(unittest.TestCase):
    def test_lists_what_falls_outside_the_targets(self):
        pairs = {("hearing", "H1036-001-0"), ("hearing", "H1036-002-0"), ("dental", "H1036-002-0")}
        self.assertEqual(reach.outside(pairs, {"hearing": ("H1036-002-0",)}, {"H1036-002-0", "H1036-003-0"}),
                         [("dental", "H1036-002-0"), ("hearing", "H1036-001-0"), ("presented", "H1036-003-0")])


class LedgerTest(unittest.TestCase):
    def test_reads_no_rows_before_a_run(self):
        with tempfile.TemporaryDirectory() as work:
            self.assertEqual(reach.ledger(work), [])
            pathlib.Path(work, blobs.LEDGER).write_text("dir,task,model,effort,key,prompt\nd,t,m,e,k,p\n")
            self.assertEqual(reach.ledger(work), [dict(dir="d", task="t", model="m", effort="e", key="k", prompt="p")])


class GuardTest(unittest.TestCase):
    def ask(self, text):
        """What the guarded asker returns for one review task."""
        with tempfile.TemporaryDirectory() as work:
            pathlib.Path(work, blobs.LEDGER).write_text(f"dir,task,model,effort,key,prompt\nfacts/review,v-0.md,m,e,k,{ask.sha(text)}\n")
            data = pathlib.Path(work, "generated")
            data.mkdir()
            (data / "documents_checked.csv").write_text("url,sha256,kind,plan_ids\n")

            def asker(model, effort, texts):
                return {k: ("[]", {}) for k in texts}
            asker.batch = True
            guard = reach.Guard(asker, work, work, VERSION)
            self.assertTrue(guard.batch)
            return guard("m", "e", {"k": text})

    def test_sends_batches_only_if_its_asker_does(self):
        self.assertFalse(reach.Guard(lambda *a: {}, "data", "work", VERSION).batch)

    def test_asks_about_the_targets(self):
        self.assertEqual(self.ask(review("H1036-002-0")), {"k": ("[]", {})})

    def test_stops_before_asking_about_another_plan(self):
        with self.assertRaises(SystemExit) as stop:
            self.ask(review("H1036-001-0"))
        self.assertIn("hearing H1036-001-0", str(stop.exception))


if __name__ == "__main__":
    unittest.main()
