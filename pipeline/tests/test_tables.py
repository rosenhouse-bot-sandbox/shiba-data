import hashlib, os, pathlib, subprocess, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import blobs, built, tables, years

ZIP = b"zip bytes"
SHA = hashlib.sha256(ZIP).hexdigest()


class FetchTest(unittest.TestCase):
    def fetch(self, have=None, served=ZIP):
        got = []

        def get(url, path):
            got.append(url)
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

    def test_fails_when_the_download_is_not_the_pinned_file(self):
        with self.assertRaisesRegex(ValueError, "pbp"):
            self.fetch(served=b"other")


class MainTest(unittest.TestCase):
    def test_writes_the_cms_tables_then_the_sheets(self):
        order = []
        with mock.patch.object(tables, "fetch", lambda gen, work: order.append("fetch")), \
             mock.patch.object(tables.run, "cms_tables", lambda data, config, work: order.append("cms_tables")), \
             mock.patch.object(tables.present, "write", lambda data: order.append("present")):
            tables.main(str(years.LIVE), "work")
        self.assertEqual(order, ["fetch", "cms_tables", "present"])


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
