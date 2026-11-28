"""Writes the tables that the pinned files, found.csv, links.csv and the saved answers give: the CMS tables, the
documents list, the document facts, and the sheets and their citations.

Usage: python3 -I pipeline/tables.py <year> <work_dir>

Git does not keep these tables. This downloads each CMS zip and PDF text that generated/ pins, unless <work_dir> has it,
and pulls the saved answers that lock.json pins.
It replays the model steps, so it calls no API, and stops if a task has no saved answer.
"""
import concurrent.futures
import contextlib
import csv
import io
import os
import sys

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__))]
import blobs  # noqa: E402
import run  # noqa: E402
import sheets  # noqa: E402
import steps  # noqa: E402
import store  # noqa: E402
import years  # noqa: E402

WRITES = ("generated/plans.csv", "generated/landscape_reads.csv", "generated/documents.csv", "generated/pbp_facts.csv",
          "generated/cms_sources.csv", run.FACTS, *(f"generated/{name}" for name in sheets.SHEETS.values()),
          sheets.PRESENTED, sheets.CAVEATS)


def pins(gen, work):
    """(sha256, path) of each file that generated/ pins."""
    with open(gen / blobs.CMS_FILES, newline="") as f:
        cms = [(pin["sha256"], blobs.cms_path(work, pin["name"])) for pin in csv.DictReader(f)]
    return cms + blobs.recorded_texts(gen, work)


def download(digest, path):
    if path.exists() and blobs.sha256(path) == digest:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    run.get(f"https://pdxplans.org/docs/{digest}.pdf", path)
    if blobs.sha256(path) != digest:
        raise ValueError(f"The download of {path} is not the pinned file.")


def fetch(gen, work):
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda pin: download(*pin), pins(gen, work)))


def main(year, work):
    data, work = years.data_dir(year), os.path.abspath(work)
    os.makedirs(work, exist_ok=True)
    fetch(data / "generated", work)
    run.cms_tables(data, years.config(data), work)
    store.pull(data, work)
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            run.model_steps(data, f"{work}/texts", work, run.Answers(data, None, work), steps.versions(data, run.STEPS))
    except BaseException:
        print(out.getvalue(), end="")
        raise


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
