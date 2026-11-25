"""Lists, as a Markdown table, each sheet cell whose value differs from the cell that a git ref's code and facts write.

Usage: python3 -I pipeline/changes.py <year> <ref> [<work_dir>]

A work_dir that tables.py used before saves downloading the pinned files again.
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


def at(ref, year, out, repo=years.REPO, work=None):
    """The sheets that ref's code writes from ref's inputs, in a copy of ref under out."""
    if subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{ref}:data/{year}"], stderr=subprocess.DEVNULL).returncode:
        return {}
    tar = subprocess.run(["git", "-C", str(repo), "archive", ref, "pipeline", "web/static", f"data/{year}"], check=True,
                         stdout=subprocess.PIPE).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(out, filter="data")
    env = {k: v for k, v in os.environ.items() if not k.startswith("SHIBA_")}
    # Refs from before tables.py kept the tables that present.py reads in git.
    tables = pathlib.Path(out, "pipeline", "tables.py")
    step = [tables, str(year), work or f"{out}/work"] if tables.exists() else [f"{out}/pipeline/present.py", str(year)]
    done = subprocess.run([sys.executable, "-I", *map(str, step)], env=env, capture_output=True, text=True)
    if done.returncode:
        sys.stderr.write(done.stdout + done.stderr)
        done.check_returncode()
    return sheets.read(pathlib.Path(out, "data", str(year)))


def main(year, ref, work=None):
    data = years.data_dir(year)
    with tempfile.TemporaryDirectory() as out:
        before = at(ref, year, out, work=work)
    print(table(changed(before, sheets.read(data))), end="")


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
