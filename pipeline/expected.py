"""Scores candidate cells against the expected cells frozen from people's edits."""
import csv
import os

import layers

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "fixtures", "expected_cells.csv")


def load(path=FIXTURE):
    with open(path, newline="") as f:
        return [dict(r, eoc_pages=[int(p) for p in r["eoc_pages"].split()]) for r in csv.DictReader(f)]


def miss(want, got):
    """Says why a candidate cell fails an expected cell line, or returns None."""
    if got is None:
        return "no cell"
    value = layers.shown(got["value"], want["line"])
    if value is None:
        return f"no line {want['line']}"
    if value != want["value"]:
        return f"value {value}, not {want['value']}"
    cites = {(url, int(page)) for url, page in got["cites"]}
    uncited = [p for p in want["eoc_pages"] if (want["eoc_url"], p) not in cites]
    if uncited:
        return f"cites no {want['eoc_url']} page " + " ".join(map(str, uncited))


def score(cells, columns, expected=None):
    """Maps each (sheet, column) to its matched lines and (line, reason) misses.
    cells maps (sheet, plan_id, column) to a dict of its value and the (url, page) pairs it cites.
    Any line of a cell may satisfy a page that the cell cites."""
    expected = load() if expected is None else expected
    unknown = set(columns) - {(want["sheet"], want["column"]) for want in expected}
    if unknown:
        raise ValueError(f"No expected cells for {sorted(unknown)}")
    result = {column: dict(matches=[], misses=[]) for column in columns}
    for want in expected:
        scored = result.get((want["sheet"], want["column"]))
        if scored is None:
            continue
        key = (want["sheet"], want["plan_id"], want["column"])
        why = miss(want, cells.get(key))
        if why:
            scored["misses"].append((key + (want["line"],), why))
        else:
            scored["matches"].append(key + (want["line"],))
    return result
