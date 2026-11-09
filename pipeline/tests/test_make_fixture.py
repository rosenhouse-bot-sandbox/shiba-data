import gzip, os, pathlib, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_fixture


class WriteTest(unittest.TestCase):
    def test_keeps_a_file_whose_json_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f.json.gz")
            old = gzip.compress(b'{"a": 1}', compresslevel=1, mtime=0)
            with open(path, "wb") as f:
                f.write(old)
            make_fixture.write(path, b'{"a": 1}')
            self.assertEqual(pathlib.Path(path).read_bytes(), old)

    def test_rewrites_a_file_whose_json_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f.json.gz")
            make_fixture.write(path, b'{"a": 1}')
            make_fixture.write(path, b'{"a": 2}')
            self.assertEqual(gzip.decompress(pathlib.Path(path).read_bytes()), b'{"a": 2}')


if __name__ == "__main__":
    unittest.main()
