"""Lists a run's raw inputs for the R2 bucket, which keeps each one as blobs/<sha256>.

Usage: python3 -I pipeline/blobs.py <data_dir> <work_dir>
Prints "<key> <path>" for each fetched PDF and CMS file. The Pipeline workflow uploads each line.
"""
import csv
import hashlib
import pathlib
import sys

CMS_FILES = "cms_files.csv"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pdf_path(work, digest):
    return pathlib.Path(work, "pdfs", f"{digest[:16]}.pdf")


def cms_path(work, name):
    return pathlib.Path(work, f"{name}.zip")


def record_cms(names, work, out):
    """Writes the hash of each CMS file run.py downloaded."""
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "sha256"])
        for name in names:
            w.writerow([name, sha256(cms_path(work, name))])


def listed(data, work):
    data, work = pathlib.Path(data), pathlib.Path(work)
    with open(data / "generated" / "documents_checked.csv", newline="") as f:
        files = [(d["sha256"], pdf_path(work, d["sha256"])) for d in csv.DictReader(f) if d["sha256"]]
    with open(data / "generated" / CMS_FILES, newline="") as f:
        files += [(c["sha256"], cms_path(work, c["name"])) for c in csv.DictReader(f)]
    for digest, path in files:
        if sha256(path) != digest:
            raise ValueError(f"{path} does not hash to {digest}")
    return files


def main(data, work):
    for digest, path in listed(data, work):
        print(f"blobs/{digest} {path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
