"""Reads data/<year>/steps.json, which pins the live version of each versioned model step.

A version fixes which tasks its step writes. A new version is merged unpinned, answered by a candidate run of
the Pipeline workflow on main, then pinned.
"""
import json


def versions(data, known, candidate=""):
    """{step: version} as pinned, with a candidate such as "filled@2" in place of its step's pin.
    known maps each step to its versions."""
    with open(f"{data}/steps.json") as f:
        out = json.load(f)
    if candidate:
        step, _, version = candidate.partition("@")
        out[step] = int(version) if version.isdigit() else version
    bad = {s: out.get(s) for s in set(out) | set(known) if out.get(s) not in known.get(s, {})}
    if bad:
        raise SystemExit(f"No such step versions: {bad}")
    return out
