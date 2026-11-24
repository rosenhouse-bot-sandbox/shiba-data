import json, os, pathlib, sys, tempfile, threading, unittest
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

    def test_checks_each_quote_once_with_one_node_process_per_thread(self):
        started, checked = [], []
        real = eoc.Matcher

        class Counting(real):
            def __init__(self, items):
                started.append(threading.get_ident())
                super().__init__(items)

            def __call__(self, cites):
                checked.extend(c["quote"] for c in cites)
                return super().__call__(cites)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(eoc, "Matcher", Counting):
            work = items(tmp)
            for quote in ("Lab $0", "Specialist $40", "Lab  $0", "Lab $0"):
                eoc.highlights(work, [dict(doc="d", page="2", quote=quote)])
            other = threading.Thread(target=eoc.highlights, args=(work, [dict(doc="d", page=2, quote="Dental $5")]))
            other.start()
            other.join()
        self.assertEqual(len(started), 2)
        self.assertEqual(checked, ["Lab $0", "Specialist $40", "Dental $5"])


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
