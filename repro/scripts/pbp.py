"""Loads CMS PBP Benefits files for selected plans and decodes coded fields."""
import csv
import glob
import os

import openpyxl

KEY = ("pbp_a_hnumber", "pbp_a_plan_identifier", "segment_id")


def plan_key(plan_id):
    contract, plan, segment = plan_id.split("-")
    return contract, plan.zfill(3), str(int(segment))


def load(pbp_dir, plan_ids):
    """Returns {plan_id: {file_stem: [row, ...]}} keeping only non-empty fields."""
    wanted = {plan_key(p): p for p in plan_ids}
    out = {p: {} for p in plan_ids}
    csv.field_size_limit(10**8)
    for path in sorted(glob.glob(os.path.join(pbp_dir, "*.txt"))):
        stem = os.path.basename(path)[:-4]
        with open(path, encoding="latin-1", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if not reader.fieldnames or KEY[0] not in reader.fieldnames:
                continue
            for row in reader:
                key = (row[KEY[0]], row[KEY[1]].zfill(3), str(int(row[KEY[2]] or 0)))
                if key in wanted:
                    out[wanted[key]].setdefault(stem, []).append(
                        {k: v.strip() for k, v in row.items() if k and v and v.strip()})
    return out


def load_dictionary(xlsx_path):
    """Returns {(file, field): {"title": ..., "codes": {code: meaning}}}."""
    ws = openpyxl.load_workbook(xlsx_path, read_only=True).worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = next(rows)
    col = {h: i for i, h in enumerate(header)}
    out = {}
    for r in rows:
        key = (r[col["FILE"]], r[col["NAME"]])
        entry = out.setdefault(key, {"title": r[col["TITLE"]] or r[col["FIELD_TITLE"]], "codes": {}})
        if r[col["CODES"]] is not None:
            entry["codes"][str(r[col["CODES"]])] = r[col["CODE_VALUES"]]
    return out
