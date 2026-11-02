"""Freezes each edited cell line of edits.csv into fixtures/expected_cells.csv, so tests outlive edits.csv (#99).

Usage: python3 -I freeze_expected.py <data_dir>
"""
import collections
import csv
import os
import pathlib
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
import layers  # noqa: E402

COLUMNS = ["sheet", "plan_id", "column", "line", "value", "eoc_url", "eoc_pages"]
FIXTURE = os.path.join(here, "fixtures", "expected_cells.csv")


def freeze(data):
    """Lists each edited cell line with its live value and the EOC pages that the edits showing it cite."""
    eocs = {r["url"] for r in layers.rows(data / "generated/documents.csv") if r["kind"] == "EOC"}
    sheets, kept, _ = layers.live(data)
    live = {(sheet, r["plan_id"]): r for sheet, sheet_rows in sheets.items() for r in sheet_rows}
    pages = collections.defaultdict(set)
    for c in kept:
        if c["layer"] == layers.EDITS and c["url"] in eocs:
            pages[(c["sheet"], c["plan_id"], c["column"], c["line"])].add((c["url"], int(c["pdf_page"])))
    keys = sorted({(r["sheet"], r["plan_id"], r["column"], r["line"]) for r in layers.layer(data, layers.EDITS)})
    frozen = []
    for sheet, plan_id, column, line in keys:
        cited = pages[(sheet, plan_id, column, line)]
        (url,) = {u for u, _ in cited} or {""}
        frozen.append(dict(sheet=sheet, plan_id=plan_id, column=column, line=line,
                           value=layers.shown(live[(sheet, plan_id)][column], line),
                           eoc_url=url, eoc_pages=" ".join(str(p) for _, p in sorted(cited))))
    return frozen


def write(path, frozen):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(frozen)


if __name__ == "__main__":
    write(FIXTURE, freeze(pathlib.Path(sys.argv[1])))
