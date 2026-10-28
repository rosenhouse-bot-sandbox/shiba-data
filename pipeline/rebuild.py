"""Rebuilds a year's model-step rows from scratch, with no saved answers or machine rows, and scores them.

Usage: python3 -I pipeline/rebuild.py <year> <work> <name> [api]
       python3 -I pipeline/rebuild.py compare <year> <name> <name>

<work> must hold the texts that run.py made. The rebuild reads a copy of data/<year> in <work>,
with the seeded errors in tests/fixtures/seeded_errors.json applied as uncited edits.
The filled step covers every filled cell. The run's answers, machine rows and report go to data/<year>/rebuilds/<name>.
"""
import collections
import csv
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ask  # noqa: E402
import eval  # noqa: E402
import layers  # noqa: E402
import run  # noqa: E402
import years  # noqa: E402

SEEDS = os.path.join(HERE, "tests", "fixtures", "seeded_errors.json")
STEPS = (layers.BLANKS, layers.FILLED)


def scratch_copy(data, work, seeds, answers):
    """Copies data without model work, then appends each seed as an uncited edit. Returns the copy.
    The copy saves its answers in `answers`, so they outlast a run that stops."""
    copy = pathlib.Path(work) / "data" / data.name
    shutil.rmtree(copy, ignore_errors=True)
    shutil.copytree(data, copy, ignore=lambda d, names: {"answers", "machine", "rebuilds"} if pathlib.Path(d) == data else set())
    (copy / "machine").mkdir()
    os.makedirs(answers, exist_ok=True)
    (copy / "answers").symlink_to(pathlib.Path(answers).resolve(), target_is_directory=True)
    with open(copy / layers.EDITS, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=layers.EDIT_COLUMNS)
        for plan, cells in seeds.items():
            for key, value in cells.items():
                sheet, column = key.split(".")
                w.writerow(dict(sheet=sheet, plan_id=plan, column=column, line="", value=value, url="", pdf_page="",
                                quote="", saw="", source="session", author="", note="seeded error"))
    return copy


def rows(directory):
    return [r for name in STEPS if (pathlib.Path(directory) / os.path.basename(name)).exists()
            for r in layers.rows(pathlib.Path(directory) / os.path.basename(name))]


def report(data, machine_rows, seeds):
    """eval.py's scores against the live data, and the seeded errors that machine rows cite."""
    agreed = eval.agreed_values(machine_rows)
    seeded = [(sheet, plan, column) for plan, cells in seeds.items() for key in cells for sheet, column in [key.split(".")]]
    cited = [c for c in seeded if agreed.get(c) == seeds[c[1]][f"{c[0]}.{c[2]}"]]
    return "\n".join([eval.report(eval.score(*eval.measured(data), machine_rows)),
                      f"seeded errors cited: {len(cited)} of {len(seeded)}"] + [f"  {' '.join(c)}" for c in cited]) + "\n"


def save(copy, out, data, seeds):
    for step in STEPS:
        if (copy / step).exists():
            shutil.copy(copy / step, out / os.path.basename(step))
    (out / "report.txt").write_text(report(data, rows(out), seeds))
    print((out / "report.txt").read_text())
    return out


def compare(data, a, b):
    runs = [eval.agreed_values(rows(data / "rebuilds" / name)) for name in (a, b)]
    both = runs[0].keys() & runs[1].keys()
    alike = sum(runs[0][c] == runs[1][c] for c in both)
    return "\n".join([f"cells both runs cite alike: {alike}", f"cells the runs cite differently: {len(both) - alike}",
                      f"cells only {a} cites: {len(runs[0].keys() - both)}", f"cells only {b} cites: {len(runs[1].keys() - both)}"])


def steps(work, mode):
    """Runs the model steps on the data root that SHIBA_DATA names."""
    answer = run.Answers(years.data_dir(years.LIVE), ask.api() if mode == "api" else None)
    texts, step_work = f"{work}/texts", f"{work}/rebuild"
    run.blanks_step(texts, step_work, answer)
    run.filled_step(texts, step_work, answer, every=True)


def main(year, work, name, mode=""):
    """Without `api`, saves the run in <work>/rebuilds, so a trial run leaves the repository as it was.
    A rebuild that stopped resumes under the same name, with the answers it saved."""
    if mode not in ("", "api") or not re.fullmatch(r"[\w-]+", name):
        raise SystemExit(__doc__)
    if int(year) != years.LIVE:  # blanks.py and filled.py read the live year
        raise SystemExit(f"Only {years.LIVE} can be rebuilt.")
    data, work = years.data_dir(year), os.path.abspath(work)
    out = (data if mode == "api" else pathlib.Path(work)) / "rebuilds" / name
    if (out / "report.txt").exists():
        raise SystemExit(f"{out} is done. Name the rebuild something else.")
    seeds = json.load(open(SEEDS))
    copy = scratch_copy(data, work, seeds, out / "answers")
    subprocess.run([sys.executable, "-I", __file__, "steps", work, mode], check=True,
                   env=dict(os.environ, SHIBA_DATA=str(copy.parent)))
    save(copy, out, data, seeds)


if __name__ == "__main__":
    if sys.argv[1:2] == ["steps"]:
        steps(*sys.argv[2:])
    elif sys.argv[1:2] == ["compare"] and len(sys.argv) == 5:
        print(compare(years.data_dir(sys.argv[2]), *sys.argv[3:]))
    elif len(sys.argv) in (4, 5):
        main(*sys.argv[1:])
    else:
        raise SystemExit(__doc__)
