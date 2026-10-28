"""Scores machine-written cells against a year's live data.

Usage: python3 -I pipeline/eval.py <year> [<machine.csv>]

The generated cells are the generated sheets with code-made cells, such as naturopathy dots.
Machine rows have the machine/eoc_citations.csv columns and cite whole cells.
A machine value that differs from the generated cell is a correction.
It also counts the edited cells whose value differs from the machine layer's, by column and carrier.
"""
import collections
import csv
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


def agreed_values(machine_rows):
    """Maps each cell to the value its whole-cell, quoted rows agree on. Cells whose rows disagree are left out."""
    claims = collections.defaultdict(set)
    for r in machine_rows:
        if not r["line"] and r["quote"].strip():
            claims[(r["sheet"], r["plan_id"], r["column"])].add(r["value"])
    return {c: values.pop() for c, values in claims.items() if len(values) == 1}


def score(live, generated, cited, machine_rows):
    """Maps each measure to (hits, total, missed cells). Rows need a quote and must agree on a cell to count."""
    for r in machine_rows:
        if (r["sheet"], r["plan_id"], r["column"]) not in live:
            raise SystemExit(f"A machine row names no cell: {r}")
        if r["line"]:
            raise SystemExit(f"A machine row sets one line of a cell: {r}")
    agreed = agreed_values(machine_rows)
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


def overrides(data):
    """Lists edited cells whose live value differs from the machine layer's value.
    That is the value the machine rows agree on, else the generated one."""
    live = cells(layers.live(data)[0])
    machine_rows = [r for name in layers.CITE_ONLY for r in layers.layer(data, name)]
    machine = {**cells(layers.live(data, layers.LAYERS[:1])[0]), **agreed_values(machine_rows)}
    edited = {(r["sheet"], r["plan_id"], r["column"]) for r in layers.layer(data, layers.EDITS)}
    return sorted(c for c in edited if live[c] != machine[c])


def override_report(data, cells_):
    with open(data / "generated/plans.csv") as f:
        carrier = {r["plan_id"]: r["organization"] for r in csv.DictReader(f)}
    columns = collections.Counter(f"{sheet}.{column}" for sheet, _, column in cells_)
    carriers = collections.Counter(carrier.get(plan_id, plan_id) for _, plan_id, _ in cells_)
    lines = [f"edits that override the machine layer: {len(cells_)}"]
    if cells_:
        lines += ["  by column: " + ", ".join(f"{c} {n}" for c, n in columns.most_common()),
                  "  by carrier: " + ", ".join(f"{c} {n}" for c, n in carriers.most_common())]
    return "\n".join(lines)


def report(result):
    lines = [f"{name}: {hits} of {total}" for name, (hits, total, _) in result.items()]
    missed = collections.Counter(f"{sheet}.{column}" for sheet, _, column in result["correction recall"][2])
    return "\n".join(lines + ["corrections missed, by column:"] + [f"  {c}: {n}" for c, n in missed.most_common()])


def main(year, machine_csv=None):
    data = years.data_dir(year)
    print(report(score(*measured(data), layers.rows(machine_csv) if machine_csv else [])))
    print(override_report(data, overrides(data)))


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
