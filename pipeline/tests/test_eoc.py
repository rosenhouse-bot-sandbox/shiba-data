import json, os, pathlib, sys, tempfile, threading, time, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import eoc

PAGE = {"strs": ["Specialist $40 copay. Specialist $40 copay. Lab $0 copay."], "lefts": [0]}


def items(tmp):
    pathlib.Path(tmp, "items").mkdir()
    pathlib.Path(tmp, "items", "d.json").write_text(json.dumps({"2": PAGE}))
    return tmp


class HighlightsTest(unittest.TestCase):
    def test_says_whether_the_site_highlights_each_quote_at_one_place_or_any(self):
        cites = [dict(doc="d", page=2, quote=q) for q in ("Lab $0", "Specialist $40", "Dental $5")]
        with tempfile.TemporaryDirectory() as tmp:
            work = items(tmp)
            self.assertEqual(eoc.highlights(work, cites), [True, False, False])
            self.assertEqual(eoc.highlights(work, cites, "found"), [True, True, False])

    def test_checks_each_quote_once_with_one_node_process_per_items_dir(self):
        started, checked = [], []
        real = eoc.Matcher

        class Counting(real):
            def __init__(self, items):
                started.append(items)
                super().__init__(items)

            def __call__(self, cites):
                checked.extend(c["quote"] for c in cites)
                return super().__call__(cites)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(eoc, "Matcher", Counting):
            work = items(tmp)
            for quote in ("Lab $0", "Specialist $40", "Lab  $0", "Lab $0"):
                eoc.highlights(work, [dict(doc="d", page="2", quote=quote)])
            eoc.highlights(work, [dict(doc="d", page=2, quote="Lab $0 copay")] * 2)
            other = threading.Thread(target=eoc.highlights, args=(work, [dict(doc="d", page=2, quote="Dental $5")]))
            other.start()
            other.join()
        self.assertEqual(started, [f"{work}/items"])
        self.assertEqual(checked, ["Lab $0", "Specialist $40", "Lab $0 copay", "Dental $5"])

    def test_threads_get_their_own_answers(self):
        quotes = ["Lab $0 copay"[:n] for n in range(4, 13)] + [f"Dental ${n}" for n in range(9)]
        with tempfile.TemporaryDirectory() as tmp:
            work = items(tmp)
            start, got = threading.Barrier(len(quotes)), {}

            def check(quote):
                start.wait()
                got[quote] = eoc.highlights(work, [dict(doc="d", page=2, quote=quote)])
            threads = [threading.Thread(target=check, args=(q,), daemon=True) for q in quotes]
            for t in threads:
                t.start()
            deadline = time.monotonic() + 10
            for t in threads:
                t.join(deadline - time.monotonic())
        self.assertEqual(got, {q: [q.startswith("Lab")] for q in quotes})

    def test_checks_a_quote_again_in_another_items_dir(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            items(one)
            items(two)
            pathlib.Path(two, "items", "d.json").write_text(json.dumps({"2": {"strs": ["Dental $5"], "lefts": [0]}}))
            cite = [dict(doc="d", page=2, quote="Dental $5")]
            self.assertEqual((eoc.highlights(one, cite), eoc.highlights(two, cite)), ([False], [True]))

    def test_fails_and_starts_again_when_node_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = items(tmp)
            with self.assertRaisesRegex(RuntimeError, "match.mjs stopped: (?s:.*)missing.json"):
                eoc.highlights(work, [dict(doc="missing", page=2, quote="Lab $0")])
            self.assertEqual(eoc.highlights(work, [dict(doc="d", page=2, quote="Lab $0")]), [True])


class FlowTest(unittest.TestCase):
    def test_reads_a_documents_flow_text_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            pathlib.Path(tmp, "text").mkdir()
            pathlib.Path(tmp, "text", "d.txt").write_text("=====PAGE 2=====\nLab  $0 copay\n")
            with mock.patch.object(eoc, "load_pages", wraps=eoc.load_pages) as load:
                flows = [eoc.Doc(tmp, "d").flow for _ in range(3)]
        self.assertEqual((flows[0], load.call_count), ({2: "Lab $0 copay"}, 1))


if __name__ == "__main__":
    unittest.main()
