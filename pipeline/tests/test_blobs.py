import csv, hashlib, io, os, pathlib, sys, tempfile, unittest
from unittest import mock
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import blobs
import run

PDF, ZIP = b"%PDF-1.4 sb", b"PK landscape"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class BlobsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data, self.work = pathlib.Path(tmp.name, "2027"), pathlib.Path(tmp.name, "work")
        (self.data / "generated").mkdir(parents=True)
        (self.work / "pdfs").mkdir(parents=True)
        (self.work / "pdfs" / f"{sha(PDF)[:16]}.pdf").write_bytes(PDF)
        (self.work / "landscape.zip").write_bytes(ZIP)
        with open(self.data / "generated" / "documents_checked.csv", "w") as f:
            f.write(f"url,sha256\nhttps://example.org/sb.pdf,{sha(PDF)}\nhttps://example.org/sb-copy.pdf,{sha(PDF)}\n"
                    "https://example.org/gone.pdf,\n")

    def lines(self):
        out = io.StringIO()
        with redirect_stdout(out):
            blobs.main("upload", str(self.data), str(self.work))
        return out.getvalue().splitlines()

    def test_lists_each_fetched_pdf_and_recorded_cms_file_by_hash(self):
        blobs.record_cms(["landscape"], self.work, self.data / "generated" / blobs.CMS_FILES)
        self.assertEqual(self.lines(), [f"blobs/{sha(PDF)} {self.work / 'pdfs' / (sha(PDF)[:16] + '.pdf')}",
                                        f"blobs/{sha(ZIP)} {self.work / 'landscape.zip'}"])

    def test_refuses_a_file_whose_bytes_do_not_match_its_hash(self):
        blobs.record_cms(["landscape"], self.work, self.data / "generated" / blobs.CMS_FILES)
        (self.work / "landscape.zip").write_bytes(b"PK replaced")
        with self.assertRaisesRegex(ValueError, "landscape.zip"):
            self.lines()

    def write_texts(self):
        for kind in blobs.TEXT_KINDS:
            path = blobs.text_path(self.work, kind, sha(PDF))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{kind} of sb")
        blobs.record_texts(self.data / "generated", self.work)

    def test_records_each_pdf_texts_by_hash(self):
        self.write_texts()
        with open(self.data / "generated" / blobs.TEXTS) as f:
            self.assertEqual(list(csv.DictReader(f)), [{"pdf": sha(PDF), "text": sha(b"text of sb"),
                                                        "layout": sha(b"layout of sb"), "items": sha(b"items of sb")}])

    def expected(self):
        return [f"blobs/{sha(PDF)} {blobs.pdf_path(self.work, sha(PDF))}", f"blobs/{sha(ZIP)} {self.work / 'landscape.zip'}",
                *(f"blobs/{sha(f'{k} of sb'.encode())} {blobs.text_path(self.work, k, sha(PDF))}" for k in blobs.TEXT_KINDS)]

    def test_lists_texts_with_the_pdfs(self):
        blobs.record_cms(["landscape"], self.work, self.data / "generated" / blobs.CMS_FILES)
        self.write_texts()
        self.assertEqual(self.lines(), self.expected())

    def test_names_where_recorded_texts_go_before_a_run(self):
        self.write_texts()
        out = io.StringIO()
        with redirect_stdout(out):
            blobs.main("texts", str(self.data), str(self.work))
        self.assertEqual(out.getvalue().splitlines(), [f"{sha(f'{k} of sb'.encode())} {blobs.text_path(self.work, k, sha(PDF))}"
                                                       for k in blobs.TEXT_KINDS])

    def test_names_every_input_a_replay_reads(self):
        blobs.record_cms(["landscape"], self.work, self.data / "generated" / blobs.CMS_FILES)
        self.write_texts()
        (self.work / "landscape.zip").unlink()
        out = io.StringIO()
        with redirect_stdout(out):
            blobs.main("inputs", str(self.data), str(self.work))
        self.assertEqual(out.getvalue().splitlines(), [line.removeprefix("blobs/") for line in self.expected()])

    def test_names_no_texts_before_the_first_record(self):
        out = io.StringIO()
        with redirect_stdout(out):
            blobs.main("texts", str(self.data), str(self.work))
        self.assertEqual(out.getvalue(), "")

    def test_lists_no_texts_before_the_first_record(self):
        blobs.record_cms(["landscape"], self.work, self.data / "generated" / blobs.CMS_FILES)
        self.assertEqual(len(self.lines()), 2)

    def test_refuses_texts_recorded_for_other_pdfs(self):
        blobs.record_cms(["landscape"], self.work, self.data / "generated" / blobs.CMS_FILES)
        self.write_texts()
        (self.data / "generated" / "documents_checked.csv").write_text("url,sha256\n")
        with self.assertRaisesRegex(ValueError, "other PDFs"):
            self.lines()

    def test_needs_the_cms_hashes(self):
        with self.assertRaises(FileNotFoundError):
            self.lines()


class RunTest(unittest.TestCase):
    def test_run_links_each_fetched_pdf_where_blobs_lists_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            gen, work = pathlib.Path(tmp, "2027", "generated"), pathlib.Path(tmp, "work")
            gen.mkdir(parents=True)
            url = "https://example.org/sb.pdf"
            (work / "docs" / "pdf").mkdir(parents=True)
            (work / "docs" / "pdf" / f"{sha(url.encode())[:16]}.pdf").write_bytes(PDF)
            (gen / "documents_checked.csv").write_text(f"url,sha256\n{url},{sha(PDF)}\n")
            (gen / blobs.CMS_FILES).write_text("name,sha256\n")
            run.pdfs(gen, work)
            self.assertEqual(blobs.listed(gen.parent, work), [(sha(PDF), blobs.pdf_path(work, sha(PDF)))])


class ReplayTest(unittest.TestCase):
    def scripts(self, mode):
        config = {"year": 1999, "state": "OR", "counties": ["Multnomah"], "landscape_csv": "landscape.csv",
                  "landscape_zip": "https://example.org/l.zip", "pbp_zip": "https://example.org/p.zip",
                  "part_b_deductible": "$283"}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(run.years, "data_dir", return_value=pathlib.Path(tmp)), \
                mock.patch.object(run.years, "config", return_value=config), \
                mock.patch.object(run, "get") as get, mock.patch.object(run, "py") as py, \
                mock.patch.object(run, "pdfs"), mock.patch.object(run, "lost_quotes", return_value=[]), \
                mock.patch.object(run.subprocess, "run"), \
                mock.patch.object(run.blobs, "record_cms"), mock.patch.object(run.blobs, "record_texts"):
            run.main("1999", os.path.join(tmp, "work"), mode)
        return get.call_count, [c.args[0] for c in py.call_args_list]

    def test_a_run_reads_the_web(self):
        downloads, scripts = self.scripts("")
        self.assertEqual(downloads, 2)
        self.assertIn("fetch_docs.py", scripts)

    def test_a_replay_reads_nothing_from_the_web(self):
        downloads, scripts = self.scripts("replay")
        self.assertEqual(downloads, 0)
        self.assertFalse({"find_docs.py", "fetch_docs.py"} & set(scripts))
        self.assertIn("cite.py", scripts)


if __name__ == "__main__":
    unittest.main()
