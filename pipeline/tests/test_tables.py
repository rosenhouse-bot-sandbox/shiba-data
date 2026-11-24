import contextlib, hashlib, io, os, pathlib, subprocess, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import blobs, built, tables, years

ZIP = b"zip bytes"
SHA = hashlib.sha256(ZIP).hexdigest()


class FetchTest(unittest.TestCase):
    def fetch(self, have=None, served=ZIP):
        got = []

        def get(url, path):
            """Like run.get, keeps a file that exists."""
            got.append(url)
            if not pathlib.Path(path).exists():
                pathlib.Path(path).write_bytes(served)
        with tempfile.TemporaryDirectory() as tmp:
            gen = pathlib.Path(tmp, "generated")
            gen.mkdir()
            (gen / blobs.CMS_FILES).write_text(f"name,sha256\npbp,{SHA}\n")
            if have is not None:
                blobs.cms_path(tmp, "pbp").write_bytes(have)
            with mock.patch.object(tables.run, "get", get):
                tables.fetch(gen, tmp)
            return got, blobs.cms_path(tmp, "pbp").read_bytes()

    def test_downloads_each_pinned_cms_file_from_the_site(self):
        self.assertEqual(self.fetch(), ([f"https://pdxplans.org/docs/{SHA}.pdf"], ZIP))

    def test_keeps_a_pinned_file_the_work_dir_has(self):
        self.assertEqual(self.fetch(have=ZIP), ([], ZIP))

    def test_replaces_a_file_that_is_not_the_pinned_one(self):
        self.assertEqual(self.fetch(have=b"other")[1], ZIP)

    def test_downloads_each_recorded_text(self):
        served = {hashlib.sha256(b).hexdigest(): b for b in (b"text", b"layout", b"items")}
        got = {}

        def get(url, path):
            got[pathlib.Path(path).relative_to(tmp).as_posix()] = served[url.split("/")[-1].removesuffix(".pdf")]
            pathlib.Path(path).write_bytes(got[pathlib.Path(path).relative_to(tmp).as_posix()])
        with tempfile.TemporaryDirectory() as tmp:
            gen = pathlib.Path(tmp, "generated")
            gen.mkdir()
            (gen / blobs.CMS_FILES).write_text("name,sha256\n")
            (gen / blobs.TEXTS).write_text("pdf,text,layout,items\n" + ",".join(["f" * 64, *served]) + "\n")
            with mock.patch.object(tables.run, "get", get):
                tables.fetch(gen, tmp)
        self.assertEqual(got, {"texts/text/ffffffffffffffff.txt": b"text", "texts/layout/ffffffffffffffff.txt": b"layout",
                               "texts/items/ffffffffffffffff.json": b"items"})

    def test_fails_when_the_download_is_not_the_pinned_file(self):
        with self.assertRaisesRegex(ValueError, "pbp"):
            self.fetch(served=b"other")


class MainTest(unittest.TestCase):
    def test_writes_the_cms_tables_then_replays_the_model_steps(self):
        order = []

        def model_steps(data, texts, work, answer, versions):
            print("progress")
            order.append(("model_steps", os.path.isabs(work), texts == f"{work}/texts", answer.asker, versions))
        out = io.StringIO()
        with mock.patch.object(tables, "fetch", lambda gen, work: order.append("fetch")), \
             mock.patch.object(tables.run, "cms_tables", lambda data, config, work: order.append("cms_tables")), \
             mock.patch.object(tables.run, "model_steps", model_steps), contextlib.redirect_stdout(out):
            with tempfile.TemporaryDirectory() as tmp, contextlib.chdir(tmp):
                tables.main(str(years.LIVE), "work")
        pinned = tables.steps.versions(years.data_dir(), tables.run.STEPS)
        self.assertEqual(order, ["fetch", "cms_tables", ("model_steps", True, True, None, pinned)])
        self.assertEqual(out.getvalue(), "")

    def test_prints_the_model_steps_output_when_they_stop(self):
        def model_steps(*args):
            print("2 of 9 tasks have no answer")
            raise SystemExit(1)
        out = io.StringIO()
        with mock.patch.object(tables, "fetch", lambda gen, work: None), \
             mock.patch.object(tables.run, "cms_tables", lambda *a: None), \
             mock.patch.object(tables.run, "model_steps", model_steps), contextlib.redirect_stdout(out), \
             self.assertRaises(SystemExit), tempfile.TemporaryDirectory() as work:
            tables.main(str(years.LIVE), work)
        self.assertIn("2 of 9 tasks", out.getvalue())


class GitTest(unittest.TestCase):
    def test_git_ignores_what_it_writes(self):
        paths = [f"data/{years.LIVE}/{name}" for name in tables.WRITES]

        def git(*args):
            return subprocess.run(["git", "-C", str(years.REPO), *args, *paths], capture_output=True, text=True).stdout
        self.assertEqual(git("ls-files"), "")
        self.assertEqual(git("check-ignore", "--no-index").split(), paths)

    def test_code_tests_run_without_what_it_writes(self):
        self.assertLessEqual(set(tables.WRITES), set(built.OUTPUTS))


if __name__ == "__main__":
    unittest.main()
