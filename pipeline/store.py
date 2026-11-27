"""Keeps the saved model answers in R2 as packs, which data/<year>/lock.json pins by sha256.

Usage: python3 -I pipeline/store.py pull|pack <year> <work_dir>
pull: unpacks each locked pack into data/<year>. It fails if a pack would change a file there.
pack: packs the saved answers that no locked pack holds, adds the pack to the lock, and prints "blobs/<sha256> <path>",
which a workflow on main uploads.
"""
import gzip
import hashlib
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tarfile

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__))]
import years  # noqa: E402

LOCK = "lock.json"
SAVED = ("answers/*", "evaluations/*/answers/*")
MEMBER = re.compile(r"(answers|evaluations/[\w-]+/answers)/[\w-]+(\.[\w-]+)*")


def url(digest):
    return f"https://pdxplans.org/docs/{digest}.pdf"


def get(source, path):
    subprocess.run(["curl", "-sSfL", "--retry", "5", "--retry-all-errors", "--max-time", "300", "-o", str(path), source],
                   check=True)


def locked(data):
    lock = pathlib.Path(data, LOCK)
    return json.loads(lock.read_text())["packs"] if lock.exists() else []


def fetch(work, digest):
    """The locked pack, downloaded to <work>/packs unless it is there."""
    path = pathlib.Path(work, "packs", f"{digest}.tar.gz")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        get(url(digest), path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        path.unlink()
        raise ValueError(f"The download of pack {digest} is not the locked pack.")
    return path


def members(path):
    """{name: bytes} of a pack's files."""
    with tarfile.open(path) as t:
        files = {}
        for m in t.getmembers():
            if not (m.isfile() and MEMBER.fullmatch(m.name)):
                raise ValueError(f"Pack {path.name} holds {m.name}, outside the answers folders.")
            files[m.name] = t.extractfile(m).read()
        return files


def pull(data, work):
    for digest in locked(data):
        for name, content in members(fetch(work, digest)).items():
            path = pathlib.Path(data, name)
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            elif path.read_bytes() != content:
                raise ValueError(f"{path} differs from pack {digest}.")


def pack(data, work):
    """(sha256, path) of a new pack of the answers that no locked pack holds, which the lock then names, or None."""
    data = pathlib.Path(data)
    packs = locked(data)
    held = {name for digest in packs for name in members(fetch(work, digest))}
    new = sorted(name for pattern in SAVED for p in data.glob(pattern)
                 if p.is_file() and (name := p.relative_to(data).as_posix()) not in held)
    if not new:
        return None
    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as t:
        for name in new:
            content = (data / name).read_bytes()
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(content), 0o644
            t.addfile(info, io.BytesIO(content))
    digest = hashlib.sha256(raw.getvalue()).hexdigest()
    path = pathlib.Path(work, "packs", f"{digest}.tar.gz")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw.getvalue())
    (data / LOCK).write_text(json.dumps({"packs": [*packs, digest]}, indent=1) + "\n")
    return digest, path


def main(command, year, work):
    data, work = years.data_dir(year), os.path.abspath(work)
    if command == "pull":
        pull(data, work)
    elif command == "pack":
        packed = pack(data, work)
        if packed:
            print(f"blobs/{packed[0]} {packed[1]}")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
