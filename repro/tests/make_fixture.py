"""Writes the PBP rows and dictionary codes for the Appendix B plans to fixtures/pbp_appendix_b.json.gz.

Usage: python3 -I make_fixture.py <pbp_dir>
"""
import gzip
import json
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [here, os.path.join(here, "..", "scripts")]
import pbp  # noqa: E402
from appendix_b import PLAN_IDS  # noqa: E402


def main(pbp_dir):
    plans = pbp.load(pbp_dir, PLAN_IDS)
    present = {(stem, field) for plan in plans.values() for stem, rows in plan.items() for r in rows for field in r}
    dictionary = pbp.load_dictionary(os.path.join(pbp_dir, "PBP_Benefits_2027_dictionary.xlsx"))
    codes = [[stem, field, entry["codes"]] for (stem, field), entry in sorted(dictionary.items())
             if (stem, field) in present and entry["codes"]]
    data = json.dumps({"plans": plans, "codes": codes}, sort_keys=True).encode()
    with open(os.path.join(here, "fixtures", "pbp_appendix_b.json.gz"), "wb") as f:
        f.write(gzip.compress(data, mtime=0))


if __name__ == "__main__":
    main(*sys.argv[1:])
