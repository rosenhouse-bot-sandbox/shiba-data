import csv, hashlib, io, os, pathlib, sys, tempfile, unittest
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

    def test_lists_texts_with_the_pdfs(self):
        blobs.record_cms(["landscape"], self.work, self.data / "generated" / blobs.CMS_FILES)
        self.write_texts()
        self.assertEqual(self.lines()[2:], [f"blobs/{sha(f'{k} of sb'.encode())} {blobs.text_path(self.work, k, sha(PDF))}"
                                            for k in blobs.TEXT_KINDS])

    def test_names_where_recorded_texts_go_before_a_run(self):
        self.write_texts()
        out = io.StringIO()
        with redirect_stdout(out):
            blobs.main("texts", str(self.data), str(self.work))
        self.assertEqual(out.getvalue().splitlines(), [f"{sha(f'{k} of sb'.encode())} {blobs.text_path(self.work, k, sha(PDF))}"
                                                       for k in blobs.TEXT_KINDS])

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


if __name__ == "__main__":
    unittest.main()
