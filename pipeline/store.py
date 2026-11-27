"""Keeps the saved model answers in R2 as packs, which data/<year>/lock.json pins by sha256.

Usage: python3 -I pipeline/store.py pull|pack|unpacked <year> <work_dir>
       python3 -I pipeline/store.py untrack <year>
pull: unpacks each locked pack into data/<year>. It fails if a pack would change a file there.
pack: packs the saved answers that no locked pack holds, adds the pack to the lock, and prints "blobs/<sha256> <path>",
which a workflow on main uploads.
unpacked: prints the path of each saved answer that no locked pack holds, which a workflow commits if its upload fails.
untrack: stops git tracking the saved answers.
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
SAVED = ("answers/*.json", "evaluations/*/answers/*.json")
MEMBER = re.compile(r"(answers|evaluations/[\w-]+/answers)/[\w-]+\.json")


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


def unpacked(data, work):
    """The names of the saved answers that no locked pack holds. Fails if one that a pack holds has other bytes."""
    data = pathlib.Path(data)
    held = {}
    for digest in locked(data):
        held |= members(fetch(work, digest))
    new = []
    for name in sorted(p.relative_to(data).as_posix() for pattern in SAVED for p in data.glob(pattern) if p.is_file()):
        if name not in held:
            new.append(name)
        elif (data / name).read_bytes() != held[name]:
            raise ValueError(f"{data / name} differs from its locked pack.")
    return new


def untrack(repo, data):
    rel = pathlib.Path(data).relative_to(repo).as_posix()
    subprocess.run(["git", "-C", str(repo), "rm", "-r", "-q", "--cached", "--ignore-unmatch", "--",
                    f"{rel}/answers", f"{rel}/evaluations/*/answers/*"], check=True)


def pack(data, work):
    """(sha256, path) of a new pack of the answers that no locked pack holds, which the lock then names, or None."""
    data = pathlib.Path(data)
    packs = locked(data)
    new = unpacked(data, work)
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


def main(command, year, work=None):
    data = years.data_dir(year)
    if command == "untrack" and work is None:
        untrack(years.REPO, data)
        return
    if work is None:
        raise SystemExit(__doc__)
    work = os.path.abspath(work)
    if command == "pull":
        pull(data, work)
    elif command == "pack":
        packed = pack(data, work)
        if packed:
            print(f"blobs/{packed[0]} {packed[1]}")
    elif command == "unpacked":
        for name in unpacked(data, work):
            print(data / name)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
