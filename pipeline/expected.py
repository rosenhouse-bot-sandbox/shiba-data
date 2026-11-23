"""Reads the expected cell lines in tests/fixtures/expected_cells.csv."""
import csv
import os

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "fixtures", "expected_cells.csv")


def load(path=FIXTURE):
    with open(path, newline="") as f:
        return [dict(r, eoc_pages=[int(p) for p in r["eoc_pages"].split()]) for r in csv.DictReader(f)]
