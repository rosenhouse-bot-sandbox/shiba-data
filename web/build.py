"""Builds the static site from repro/data.

Usage: python3 -I web/build.py <out_dir> [--pdfs]
--pdfs downloads each plan document into <out_dir>/pdfs/.
"""
import csv
import datetime
import hashlib
import json
import pathlib
import shutil
import sys
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE.parent / "repro" / "data"

MAIN_LABELS = {
    "C_premium": "Premium",
    "D_premium_full_extra_help": "Premium w/ Full Extra Help",
    "E_moop": "MOOP In/Out of Network",
    "F_primary_care": "Primary Care",
    "G_specialist": "Specialist",
    "H_inpatient": "Inpatient Hospital $/Day",
    "I_outpatient_surgery": "Outpatient Surgery / ASC",
    "J_outpatient_rehab": "Outpatient Rehab OT, PT, ST",
    "K_tests_labs": "Diagnostic Tests / Labs",
    "L_xray_imaging": "X-Ray / Diag Radiology",
    "M_part_b_drugs": "Chemo / Part B Drugs",
    "N_pharmacy_deductible": "Pharmacy Deductible",
    "O_medical_deductible": "Medical Deductible",
    "P_vision": "Vision",
    "Q_hearing": "Hearing",
    "R_dental": "Dental",
    "S_acupuncture": "Acupuncture",
    "T_chiropractic": "Chiropractic",
    "U_naturopath": "Naturopath",
    "V_massage": "Massage",
    "W_fitness": "Fitness",
    "X_transportation": "Transportation",
    "Y_otc": "OTC",
    "Z_part_b_reduction": "Pt B Reduction",
    "AA_opt_packages": "Opt Packages",
}

DVHA_LABELS = {
    "C_premium": "Monthly Premium",
    "D_premium_full_extra_help": "Premium w/ Full Extra Help",
    "E_optional_packages": "Optional Packages",
    "F_dental": "Included Dental",
    "G_vision": "Vision",
    "H_hearing": "Hearing",
    "I_alt_care_otc_travel": "Alternative Care / OTC / Travel",
    "J_extra_benefits": "Extra Benefits",
}


def rows(name, data_dir):
    with open(data_dir / name, newline="") as f:
        return list(csv.DictReader(f))


def sheet(csv_rows, labels, cites, pbp):
    return {
        "columns": [{"key": k, "label": v} for k, v in labels.items()],
        "rows": [{
            "plan_id": r["plan_id"],
            "section": r["section"],
            "cells": {k: cell(r[k], cites.get((r["plan_id"], k), []), pbp.get((r["plan_id"], k)))
                      for k in labels},
        } for r in csv_rows],
    }


def cell(value, cites, pbp):
    c = {"value": value, "cites": cites}
    if pbp is not None:
        c["pbp"] = pbp
    return c


def site_data(data_dir=DATA):
    checked = rows("documents_checked.csv", data_dir)
    doc_by_url = {d["url"]: d["sha256"][:16] for d in checked}
    docs = {d["sha256"][:16]: {
        "kind": d["kind"],
        "url": d["url"],
        "sha256": d["sha256"],
        "pages": int(d["pages"]),
        "plan_ids": d["plan_ids"].split(";"),
    } for d in checked}

    cites = {}
    for c in rows("citations.csv", data_dir):
        cites.setdefault((c["plan_id"], c["column"]), []).append({
            "line": int(c["line"]) if c["line"] else None,
            "value": c["value"],
            "doc": doc_by_url[c["url"]],
            "page": int(c["pdf_page"]),
            "quote": c["quote"],
        })
    pbp = {(r["plan_id"], r["column"]): r["pbp"] for r in rows("pbp_vs_documents.csv", data_dir)}

    plans = rows("plans.csv", data_dir)
    for p in plans:
        p["docs"] = [i for i, d in docs.items() if p["plan_id"] in d["plan_ids"]]
    return {
        "plans": plans,
        "docs": docs,
        "main": sheet(rows("main_chart.csv", data_dir), MAIN_LABELS, cites, pbp),
        "dvha": sheet(rows("dvha.csv", data_dir), DVHA_LABELS, {}, {}),
    }


def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.read()
    except OSError as e:
        print(f"download failed: {url}: {e}", file=sys.stderr)
        return b""


def fetch_pdfs(docs, out_dir, today):
    (out_dir / "pdfs").mkdir(parents=True, exist_ok=True)
    for doc_id, doc in docs.items():
        raw = download(doc["url"])
        if not raw.startswith(b"%PDF"):
            doc.update(file=None, retrieved=None, changed=None)
            print(f"not a PDF: {doc['url']}", file=sys.stderr)
            continue
        doc["file"] = f"pdfs/{doc_id}.pdf"
        doc["retrieved"] = today
        doc["changed"] = hashlib.sha256(raw).hexdigest() != doc["sha256"]
        (out_dir / doc["file"]).write_bytes(raw)


def main(out, *flags):
    out_dir = pathlib.Path(out)
    shutil.copytree(HERE / "static", out_dir, dirs_exist_ok=True)
    site = site_data()
    if "--pdfs" in flags:
        fetch_pdfs(site["docs"], out_dir, datetime.date.today().isoformat())
    (out_dir / "data.json").write_text(json.dumps(site))


if __name__ == "__main__":
    main(*sys.argv[1:])
