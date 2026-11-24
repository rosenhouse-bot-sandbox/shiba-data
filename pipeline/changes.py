"""Lists, as a Markdown table, each sheet cell whose value differs from the cell that a git ref's code and facts write.

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
import sheets  # noqa: E402
import years  # noqa: E402


def cells(by_sheet):
    return {(sheet, r["plan_id"], c): v for sheet, rows in by_sheet.items() for r in rows
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


def at(ref, year, out, repo=years.REPO):
    """The sheets that ref's present step writes from ref's facts, in a copy of ref under out."""
    tar = subprocess.run(["git", "-C", str(repo), "archive", ref, "pipeline", f"data/{year}"], check=True,
                         capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(out, filter="data")
    env = {k: v for k, v in os.environ.items() if not k.startswith("SHIBA_")}
    subprocess.run([sys.executable, "-I", f"{out}/pipeline/present.py", str(year)], check=True, env=env)
    return sheets.read(pathlib.Path(out, "data", str(year)))


def main(year, ref):
    data = years.data_dir(year)
    with tempfile.TemporaryDirectory() as out:
        before = at(ref, year, out)
    print(table(changed(before, sheets.read(data))), end="")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
