"""Scores machine-written cells against a year's live data.

Usage: python3 -I pipeline/eval.py <year> [<machine.csv>]

The generated cells are the generated sheets with code-made cells, such as naturopathy dots.
Machine rows have the machine/eoc_citations.csv columns and cite whole cells.
A machine value that differs from the generated cell is a correction.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layers  # noqa: E402
import years  # noqa: E402


def cells(sheets):
    return {(sheet, r["plan_id"], col): r[col] for sheet, sheet_rows in sheets.items() for r in sheet_rows
            for col in r if col not in ("section", "plan_id", "plan_name")}


def measured(data):
    """(live cells, generated cells, cells that people or models cited). Code cites naturopathy dots itself."""
    live, kept, _ = layers.live(data)
    generated = layers.live(data, layers.LAYERS[:1])[0]
    cited = {(c["sheet"], c["plan_id"], c["column"]) for c in kept if c["layer"] != layers.LAYERS[0]}
    return cells(live), cells(generated), cited


def score(live, generated, cited, machine_rows):
    """Maps each measure to (hits, total, missed cells). Rows need a quote and must agree on a cell to count."""
    claims = collections.defaultdict(set)
    for r in machine_rows:
        c = (r["sheet"], r["plan_id"], r["column"])
        if c not in live:
            raise SystemExit(f"A machine row names no cell: {r}")
        if r["line"]:
            raise SystemExit(f"A machine row sets one line of a cell: {r}")
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
    print(report(score(*measured(years.data_dir(year)), layers.rows(machine_csv) if machine_csv else [])))


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
