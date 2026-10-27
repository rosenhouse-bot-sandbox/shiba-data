"""Scores machine-written cells against a year's live data.

Usage: python3 -I pipeline/eval.py <year> [<machine.csv>]

The generated layer is the live data with every sb_facts.csv row undone. Code-made cells, such as naturopathy dots, stay.
Machine rows have the eoc_citations.csv columns. A machine value that differs from the generated cell is a correction.
"""
import collections
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import years  # noqa: E402

SHEETS = {"main": ("main_chart.csv", "pbp_vs_documents.csv"), "dvha": ("dvha.csv", "pbp_vs_documents_dvha.csv")}


def rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def citation_cell(plan_id, column):
    """Citation files name DVHA columns as "dvha.<column>"."""
    return ("dvha", plan_id, column[5:]) if column.startswith("dvha.") else ("main", plan_id, column)


def live_cells(data):
    return {(sheet, r["plan_id"], col): r[col] for sheet, (name, _) in SHEETS.items() for r in rows(data / name)
            for col in r if col not in ("section", "plan_id", "plan_name")}


def hand_written(data):
    return {citation_cell(plan_id, f["column"]) for f in rows(data / "sb_facts.csv") for plan_id in f["plan_ids"].split(";")}


def generated_cells(data, live):
    hand = hand_written(data)
    pbp = {(sheet, d["plan_id"], d["column"]): d["pbp"] for sheet, (_, diffs) in SHEETS.items() for d in rows(data / diffs)}
    return {c: pbp[c] if c in hand and c in pbp else value for c, value in live.items()}


def cited_cells(data):
    """Cells that people or models cited. Code cites naturopathy dots itself."""
    hand = hand_written(data)
    return ({c for c in (citation_cell(r["plan_id"], r["column"]) for r in rows(data / "citations.csv")) if c in hand}
            | {(r["sheet"], r["plan_id"], r["column"]) for r in rows(data / "eoc_citations.csv")})


def score(live, generated, cited, machine_rows):
    """Maps each measure to (hits, total, missed cells). Rows need a quote and must agree on a cell to count."""
    claims = collections.defaultdict(set)
    for r in machine_rows:
        c = (r["sheet"], r["plan_id"], r["column"])
        if c not in live:
            raise SystemExit(f"A machine row names no cell: {r}")
        if r["quote"].strip():
            claims[c].add(r["value"])
    agreed = {c: values.pop() for c, values in claims.items() if len(values) == 1}
    machine = {**generated, **agreed}
    right = {c for c in live if machine[c] == live[c]}
    needed = {c for c in live if generated[c] != live[c]}
    changed = {c for c in agreed if machine[c] != generated[c]}
    cited_right = right & set(agreed)
    return {
        "correction recall": (len(needed & right), len(needed), sorted(needed - right)),
        "correction precision": (len(changed & right), len(changed), sorted(changed - right)),
        "citations": (len(cited & cited_right), len(cited), sorted(cited - cited_right)),
    }


def report(result):
    lines = [f"{name}: {hits} of {total}" for name, (hits, total, _) in result.items()]
    missed = collections.Counter(f"{sheet}.{column}" for sheet, _, column in result["correction recall"][2])
    return "\n".join(lines + ["corrections missed, by column:"] + [f"  {c}: {n}" for c, n in missed.most_common()])


def main(year, machine_csv=None):
    data = years.data_dir(year)
    live = live_cells(data)
    print(report(score(live, generated_cells(data, live), cited_cells(data), rows(machine_csv) if machine_csv else [])))


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
