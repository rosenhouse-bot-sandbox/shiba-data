"""Writes the PBP rows and dictionary codes and titles for the Appendix B plans to fixtures/pbp_appendix_b.json.gz.

Usage: python3 -I make_fixture.py <pbp_dir>
"""
import gzip
import json
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [here, os.path.join(here, "..")]
import pbp  # noqa: E402
from appendix_b import PLAN_IDS  # noqa: E402


def write(path, data):
    """Keeps a file whose JSON is unchanged, because zlib versions compress the same JSON differently."""
    if os.path.exists(path) and gzip.decompress(open(path, "rb").read()) == data:
        return
    with open(path, "wb") as f:
        f.write(gzip.compress(data, mtime=0))


def main(pbp_dir):
    plans = pbp.load(pbp_dir, PLAN_IDS)
    present = {(stem, field) for plan in plans.values() for stem, rows in plan.items() for r in rows for field in r}
    dictionary = pbp.load_dictionary(pbp_dir)
    codes = [[stem, field, entry["codes"]] for (stem, field), entry in sorted(dictionary.items())
             if (stem, field) in present and entry["codes"]]
    titles = [[stem, field, entry["title"]] for (stem, field), entry in sorted(dictionary.items()) if (stem, field) in present]
    data = json.dumps({"plans": plans, "codes": codes, "titles": titles}, sort_keys=True).encode()
    write(os.path.join(here, "fixtures", "pbp_appendix_b.json.gz"), data)


if __name__ == "__main__":
    main(*sys.argv[1:])
