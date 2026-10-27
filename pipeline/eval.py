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


def cell(plan_id, column):
    """Citation files name DVHA columns as "dvha.<column>"."""
    return ("dvha", plan_id, column[5:]) if column.startswith("dvha.") else ("main", plan_id, column)


def live_cells(data):
    return {(sheet, r["plan_id"], col): r[col] for sheet, (name, _) in SHEETS.items() for r in rows(data / name)
            for col in r if col not in ("section", "plan_id", "plan_name")}


def generated_cells(data, live):
    hand_written = {cell(plan_id, f["column"]) for f in rows(data / "sb_facts.csv") for plan_id in f["plan_ids"].split(";")}
    pbp = {(sheet, d["plan_id"], d["column"]): d["pbp"] for sheet, (_, diffs) in SHEETS.items() for d in rows(data / diffs)}
    return {c: pbp[c] if c in hand_written and c in pbp else value for c, value in live.items()}


def cited_cells(data):
    return ({cell(c["plan_id"], c["column"]) for c in rows(data / "citations.csv")}
            | {(c["sheet"], c["plan_id"], c["column"]) for c in rows(data / "eoc_citations.csv")})


def score(live, generated, cited, machine_rows):
    """Maps each measure to (hits, total, missed cells). Cells whose machine rows disagree keep the generated value."""
    claims = collections.defaultdict(set)
    for r in machine_rows:
        claims[(r["sheet"], r["plan_id"], r["column"])].add(r["value"])
    machine = dict(generated)
    machine.update({c: next(iter(values)) for c, values in claims.items() if len(values) == 1})
    right = {c for c in live if machine[c] == live[c]}
    needed = {c for c in live if generated[c] != live[c]}
    made = {c for c in claims if machine[c] != generated[c]}
    cited_right = right & set(claims)
    return {
        "corrections": (len(needed & right), len(needed), sorted(needed - right)),
        "correction precision": (len(made & right), len(made), sorted(made - right)),
        "citations": (len(cited & cited_right), len(cited), sorted(cited - cited_right)),
    }


def report(result):
    lines = [f"{name}: {hits} of {total}" for name, (hits, total, _) in result.items()]
    missed = collections.Counter(f"{sheet}.{column}" for sheet, _, column in result["corrections"][2])
    return "\n".join(lines + ["corrections missed, by column:"] + [f"  {c}: {n}" for c, n in missed.most_common()])


def main(year, machine_csv=None):
    data = years.data_dir(year)
    live = live_cells(data)
    print(report(score(live, generated_cells(data, live), cited_cells(data), rows(machine_csv) if machine_csv else [])))


if __name__ == "__main__":
    main(*sys.argv[1:])
