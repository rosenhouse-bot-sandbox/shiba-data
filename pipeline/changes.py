"""Lists, as a Markdown table, each live sheet cell whose value differs from the cell at a git ref.

Usage: python3 -I pipeline/changes.py <year> <ref>
"""
import io
import os
import pathlib
import subprocess
import sys
import tarfile
import tempfile

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__))]
import layers  # noqa: E402
import years  # noqa: E402


def cells(sheets):
    return {(sheet, r["plan_id"], c): v for sheet, rows in sheets.items() for r in rows
            for c, v in r.items() if c not in ("section", "plan_id", "plan_name")}


def changed(before, after):
    """[(sheet, plan, column, before, after)] for each cell whose value differs."""
    b, a = cells(before), cells(after)
    return [(*k, b.get(k, ""), a.get(k, "")) for k in sorted(b.keys() | a.keys()) if b.get(k, "") != a.get(k, "")]


def table(rows):
    if not rows:
        return "No sheet cell changes.\n"
    def cell(v):
        return "`" + v.replace("|", "\\|") + "`" if v else "(blank)"
    return "| Sheet | Plan | Column | Before | After |\n|---|---|---|---|---|\n" + "".join(
        f"| {s} | {p} | {c} | {cell(b)} | {cell(a)} |\n" for s, p, c, b, a in rows)


def at(ref, data, out):
    """data's live sheets at ref, read from a copy written under out."""
    rel = data.relative_to(years.REPO)
    paths = [str(rel / "generated" / name) for name in layers.SHEETS.values()] + [str(rel / name) for name in layers.LAYERS]
    tar = subprocess.run(["git", "-C", str(years.REPO), "archive", ref, *paths], check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(out, filter="data")
    return layers.live(pathlib.Path(out, rel))[0]


def main(year, ref):
    data = years.data_dir(year)
    with tempfile.TemporaryDirectory() as out:
        before = at(ref, data, out)
    print(table(changed(before, layers.live(data)[0])), end="")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
