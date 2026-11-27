import hashlib, json, os, pathlib, subprocess, sys, tarfile, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import store


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class StoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data, self.work = pathlib.Path(tmp.name, "data"), pathlib.Path(tmp.name, "work")
        self.data.mkdir()
        self.served = {}
        get = mock.patch.object(store, "get", lambda url, path: pathlib.Path(path).write_bytes(self.served[url]))
        get.start()
        self.addCleanup(get.stop)

    def pack(self):
        """Packs as a workflow on main does, and uploads the pack."""
        packed = store.pack(self.data, self.work)
        if packed:
            digest, path = packed
            self.served[store.url(digest)] = path.read_bytes()
        return packed

    def files(self):
        return {str(p.relative_to(self.data)): p.read_text() for p in sorted(self.data.rglob("*")) if p.is_file()}

    def test_pull_restores_what_pack_packed(self):
        write(self.data / "answers/a.json", "A")
        write(self.data / "evaluations/imaging/answers/b.json", "B")
        write(self.data / "evaluations/imaging/all.md", "report")
        self.pack()
        before = self.files()
        for name in ("answers/a.json", "evaluations/imaging/answers/b.json"):
            (self.data / name).unlink()
        store.pull(self.data, self.work / "elsewhere")
        self.assertEqual(self.files(), before)

    def test_a_pack_holds_only_answers_that_no_locked_pack_holds(self):
        write(self.data / "answers/a.json", "A")
        first, _ = self.pack()
        self.assertIsNone(self.pack())
        write(self.data / "answers/b.json", "B")
        second, path = self.pack()
        with tarfile.open(path) as t:
            self.assertEqual(t.getnames(), ["answers/b.json"])
        self.assertEqual(json.loads((self.data / store.LOCK).read_text()), {"packs": [first, second]})

    def test_a_pack_skips_files_that_are_not_saved_answers(self):
        write(self.data / "answers/a.json", "A")
        write(self.data / "answers/b.json.tmp", "half written")
        _, path = self.pack()
        with tarfile.open(path) as t:
            self.assertEqual(t.getnames(), ["answers/a.json"])

    def test_unpacked_lists_the_answers_no_locked_pack_holds(self):
        write(self.data / "answers/a.json", "A")
        self.pack()
        write(self.data / "evaluations/reviewer/answers/b.json", "B")
        self.assertEqual(store.unpacked(self.data, self.work), ["evaluations/reviewer/answers/b.json"])

    def test_a_pack_fails_on_an_answer_that_differs_from_its_locked_copy(self):
        write(self.data / "answers/a.json", "A")
        self.pack()
        write(self.data / "answers/a.json", "changed")
        with self.assertRaisesRegex(ValueError, "answers/a.json"):
            store.pack(self.data, self.work)

    def test_a_pack_of_the_same_answers_has_the_same_hash(self):
        write(self.data / "answers/a.json", "A")
        digest, path = self.pack()
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        (self.data / store.LOCK).unlink()
        os.utime(self.data / "answers/a.json", (0, 0))
        self.assertEqual(store.pack(self.data, self.work / "again")[0], digest)

    def test_pull_keeps_a_file_with_the_packed_bytes_and_fails_on_other_bytes(self):
        write(self.data / "answers/a.json", "A")
        self.pack()
        store.pull(self.data, self.work)
        write(self.data / "answers/a.json", "changed")
        with self.assertRaisesRegex(ValueError, "answers/a.json"):
            store.pull(self.data, self.work)

    def test_pull_fails_on_a_download_that_is_not_the_locked_pack(self):
        write(self.data / "answers/a.json", "A")
        digest, path = self.pack()
        path.unlink()
        self.served[store.url(digest)] = b"other bytes"
        with self.assertRaisesRegex(ValueError, digest):
            store.pull(self.data, self.work)
        self.assertFalse(path.exists())

    def test_pull_refuses_a_pack_member_that_is_not_a_saved_answer_file(self):
        for name, kind in (("config.json", tarfile.REGTYPE), ("answers/../config.json", tarfile.REGTYPE),
                           ("evaluations/x/answers/sub/a.json", tarfile.REGTYPE), ("answers/a.json", tarfile.SYMTYPE)):
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                path = pathlib.Path(tmp, "p.tar.gz")
                with tarfile.open(path, "w:gz") as t:
                    info = tarfile.TarInfo(name)
                    info.type, info.linkname = kind, "../../config.json"
                    t.addfile(info)
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                self.served[store.url(digest)] = path.read_bytes()
                (self.data / store.LOCK).write_text(json.dumps({"packs": [digest]}))
                with self.assertRaisesRegex(ValueError, "outside"):
                    store.pull(self.data, self.work)

    def test_pull_without_a_lock_does_nothing(self):
        store.pull(self.data, self.work)
        self.assertEqual(self.files(), {})

    def test_untrack_leaves_git_tracking_no_saved_answer(self):
        repo = self.data.parent
        names = ["answers/a.json", "evaluations/imaging/answers/b.json", "evaluations/imaging/all.md", "config.json"]
        for name in names:
            write(self.data / name, name)
        git = lambda *args: subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout
        git("init", "-q")
        git("add", ".")
        store.untrack(repo, self.data)
        self.assertEqual(git("ls-files", "--cached").split(), ["data/config.json", "data/evaluations/imaging/all.md"])

    def test_git_ignores_saved_answers(self):
        repo = pathlib.Path(store.__file__).resolve().parent.parent
        paths = ["data/2027/answers/a.json", "data/2027/evaluations/imaging/answers/b.json"]
        done = subprocess.run(["git", "-C", repo, "check-ignore", "--no-index", *paths], capture_output=True, text=True)
        self.assertEqual(done.stdout.split(), paths)
