"""Lists a run's raw inputs for the R2 bucket, which keeps each one as blobs/<sha256>.

Usage: python3 -I pipeline/blobs.py upload|texts <data_dir> <work_dir>
upload: prints "<key> <path>" for each fetched PDF, CMS file and PDF text. The Pipeline workflow uploads each line.
texts: prints "<sha256> <path>" for each recorded PDF text. The workflow downloads each line before a run.
"""
import csv
import hashlib
import pathlib
import sys

CMS_FILES, TEXTS = "cms_files.csv", "texts.csv"
TEXT_KINDS = {"text": "txt", "layout": "txt", "items": "json"}


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


def text_path(work, kind, digest):
    """Where texts.py writes this kind of text for the PDF with this hash."""
    return pathlib.Path(work, "texts", kind, f"{digest[:16]}.{TEXT_KINDS[kind]}")


def checked_pdfs(gen):
    with open(pathlib.Path(gen, "documents_checked.csv"), newline="") as f:
        return list(dict.fromkeys(d["sha256"] for d in csv.DictReader(f) if d["sha256"]))


def record_texts(gen, work):
    """Writes the hash of each text texts.py has for each fetched PDF."""
    with open(pathlib.Path(gen, TEXTS), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pdf", *TEXT_KINDS])
        for pdf in checked_pdfs(gen):
            w.writerow([pdf, *(sha256(text_path(work, kind, pdf)) for kind in TEXT_KINDS)])


def recorded_texts(gen, work):
    path = pathlib.Path(gen, TEXTS)
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return [(t[kind], text_path(work, kind, t["pdf"])) for t in csv.DictReader(f) for kind in TEXT_KINDS]


def record_cms(names, work, out):
    """Writes the hash of each CMS file run.py downloaded."""
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "sha256"])
        for name in names:
            w.writerow([name, sha256(cms_path(work, name))])


def listed(data, work):
    gen, work = pathlib.Path(data, "generated"), pathlib.Path(work)
    files = [(digest, pdf_path(work, digest)) for digest in checked_pdfs(gen)]
    with open(gen / CMS_FILES, newline="") as f:
        files += [(c["sha256"], cms_path(work, c["name"])) for c in csv.DictReader(f)]
    texts = recorded_texts(gen, work)
    if texts and {path.stem for _, path in texts} != {digest[:16] for digest in checked_pdfs(gen)}:
        raise ValueError(f"{gen / TEXTS} records texts for other PDFs than documents_checked.csv")
    files += texts
    for digest, path in files:
        if sha256(path) != digest:
            raise ValueError(f"{path} does not hash to {digest}")
    return files


def main(command, data, work):
    if command == "upload":
        for digest, path in listed(data, work):
            print(f"blobs/{digest} {path}")
    elif command == "texts":
        for digest, path in recorded_texts(pathlib.Path(data, "generated"), work):
            print(f"{digest} {path}")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
