"""Reads data/<year>/steps.json, which pins the live version of each versioned model step.

A version fixes which tasks its step writes. A new version is merged unpinned, answered by a candidate run of
the Pipeline workflow on main, then pinned.
"""
import json


def versions(data, known, candidate=""):
    """{step: version} as pinned, with each candidate in place of its step's pin.
    candidate is like "filled@2", or several joined by commas. known maps each step to its versions."""
    with open(f"{data}/steps.json") as f:
        out = json.load(f)
    candidates = [c.strip().partition("@") for c in candidate.split(",")] if candidate else []
    for step, _, version in candidates:
        if step not in known:
            raise SystemExit(f"No versioned step {step}")
        out[step] = int(version) if version.isdigit() else version
    if len({step for step, _, _ in candidates}) < len(candidates):
        raise SystemExit(f"Two candidates for one step: {candidate}")
    bad = {s: out.get(s) for s in known if out.get(s) not in known[s]}
    if bad:
        raise SystemExit(f"No such step versions: {bad}")
    return out
