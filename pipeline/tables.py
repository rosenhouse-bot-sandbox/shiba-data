"""Writes the tables that the pinned CMS files, found.csv and links.csv give, then the sheets and their citations.

Usage: python3 -I pipeline/tables.py <year> <work_dir>

Git does not keep these tables. This downloads each CMS zip that generated/cms_files.csv pins, unless <work_dir> has it.
"""
import csv
import os
import sys

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__))]
import blobs  # noqa: E402
import present  # noqa: E402
import run  # noqa: E402
import sheets  # noqa: E402
import years  # noqa: E402

WRITES = ("generated/plans.csv", "generated/landscape_reads.csv", "generated/documents.csv", "generated/pbp_facts.csv",
          "generated/cms_sources.csv", *(f"generated/{name}" for name in sheets.SHEETS.values()), sheets.PRESENTED)


def fetch(gen, work):
    with open(gen / blobs.CMS_FILES, newline="") as f:
        pins = list(csv.DictReader(f))
    for pin in pins:
        path = blobs.cms_path(work, pin["name"])
        if path.exists() and blobs.sha256(path) == pin["sha256"]:
            continue
        path.unlink(missing_ok=True)
        run.get(f"https://pdxplans.org/docs/{pin['sha256']}.pdf", path)
        if blobs.sha256(path) != pin["sha256"]:
            raise ValueError(f"The download of {pin['name']} is not the pinned file.")


def main(year, work):
    data = years.data_dir(year)
    os.makedirs(work, exist_ok=True)
    fetch(data / "generated", work)
    run.cms_tables(data, years.config(data), work)
    present.write(data)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
