import csv, hashlib, os, pathlib, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fetch_docs


class MainTest(unittest.TestCase):
    def test_keeps_a_download_it_already_has(self):
        with tempfile.TemporaryDirectory() as tmp:
            url = "https://x/sb.pdf"
            with open(f"{tmp}/documents.csv", "w") as f:
                f.write(f"plan_ids,kind,url,found_via\nH1036-306-0,SB,{url},browser\n")
            with open(f"{tmp}/plans.csv", "w") as f:
                f.write("plan_id,plan_name\nH1036-306-0,Gold\n")
            cached = pathlib.Path(fetch_docs.cached_pdf(f"{tmp}/cache", url))
            cached.parent.mkdir(parents=True)
            cached.write_bytes(b"%PDF-1.7")
            with mock.patch.object(fetch_docs.subprocess, "run") as run:
                fetch_docs.main(f"{tmp}/documents.csv", f"{tmp}/plans.csv", f"{tmp}/cache", f"{tmp}/out.csv", 2027, "Multnomah")
            self.assertEqual([c for c in run.call_args_list if c.args[0][0] == "curl"], [])
            with open(f"{tmp}/out.csv") as f:
                self.assertEqual(next(csv.DictReader(f))["sha256"], hashlib.sha256(b"%PDF-1.7").hexdigest())


if __name__ == "__main__":
    unittest.main()
