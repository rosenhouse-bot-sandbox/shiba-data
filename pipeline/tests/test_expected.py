import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import expected


class LoadTest(unittest.TestCase):
    def test_loads_every_expected_cell_line(self):
        cells = expected.load()
        self.assertEqual(len(cells), 358)
        self.assertEqual(sum(1 for c in cells if not c["eoc_pages"]), 129)
        self.assertEqual(sum(1 for c in cells if c["column"] == "L_xray_imaging"), 41)
        self.assertTrue(all(c["eoc_url"] for c in cells if c["eoc_pages"]))
        self.assertTrue(all(isinstance(p, int) for c in cells for p in c["eoc_pages"]))
        self.assertEqual(max(len(c["eoc_pages"]) for c in cells), 4)


if __name__ == "__main__":
    unittest.main()
