"""Builds the plan documents release, or the static site from repro/data.

Usage:
  python3 -I web/build.py documents <out_dir>
  python3 -I web/build.py site <out_dir> [<documents_dir>]
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


def sheet(csv_rows, labels, cites, pbp, comments):
    return {
        "columns": [{"key": k, "label": v} for k, v in labels.items()],
        "rows": [{
            "plan_id": r["plan_id"],
            "section": r["section"],
            "cells": {k: cell(r[k], cites.get((r["plan_id"], k), []), pbp.get((r["plan_id"], k)),
                              comments.get((r["plan_id"], k)))
                      for k in labels},
        } for r in csv_rows],
    }


def cell(value, cites, pbp, comment):
    c = {"value": value, "cites": cites}
    if pbp is not None:
        c["pbp"] = pbp
    if comment:
        c["comment"] = comment
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

    cites = {"main": {}, "dvha": {}}
    documented = [dict(c, sheet="dvha", column=c["column"].removeprefix("dvha.")) if c["column"].startswith("dvha.")
                  else dict(c, sheet="main") for c in rows("citations.csv", data_dir)]
    for c in documented + rows("eoc_citations.csv", data_dir):
        cites[c["sheet"]].setdefault((c["plan_id"], c["column"]), []).append({
            "line": int(c["line"]) if c.get("line") else None,
            "value": c["value"],
            "doc": doc_by_url[c["url"]],
            "page": int(c["pdf_page"]),
            "quote": c["quote"],
        })
    pbp = {sheet: {(r["plan_id"], r["column"]): r["pbp"] for r in rows(name, data_dir)}
           for sheet, name in (("main", "pbp_vs_documents.csv"), ("dvha", "pbp_vs_documents_dvha.csv"))}

    plans = rows("plans.csv", data_dir)
    for p in plans:
        p["docs"] = [i for i, d in docs.items() if p["plan_id"] in d["plan_ids"]]
        p["plan_finder_url"] = f"https://www.medicare.gov/plan-compare/#/plan-details/2027-{p['plan_id']}?year=2027&lang=en"
    sheets = {"main": (rows("main_chart.csv", data_dir), MAIN_LABELS), "dvha": (rows("dvha.csv", data_dir), DVHA_LABELS)}
    comments = {"main": {}, "dvha": {}}
    for c in rows("comments.csv", data_dir):
        csv_rows, labels = sheets[c["sheet"]]
        if c["column"] not in labels or c["plan_id"] not in {r["plan_id"] for r in csv_rows}:
            raise ValueError(f"comments.csv names no cell: {c['sheet']} {c['plan_id']} {c['column']}")
        if (c["plan_id"], c["column"]) in comments[c["sheet"]]:
            raise ValueError(f"comments.csv names a cell twice: {c['sheet']} {c['plan_id']} {c['column']}")
        comments[c["sheet"]][(c["plan_id"], c["column"])] = {
            "text": c["comment"], "doc": doc_by_url[c["url"]], "page": int(c["pdf_page"]), "quote": c["quote"]}
    return {
        "plans": plans,
        "docs": docs,
        **{name: sheet(csv_rows, labels, cites[name], pbp[name], comments[name])
           for name, (csv_rows, labels) in sheets.items()},
    }


def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.read()
    except OSError:
        return b""


def fetch_pdfs(docs, out_dir, today):
    (out_dir / "pdfs").mkdir(parents=True, exist_ok=True)
    failed = []
    for doc_id, doc in docs.items():
        raw = download(doc["url"])
        if not raw.startswith(b"%PDF"):
            doc.update(file=None, retrieved=None, changed=None)
            failed.append(doc["url"])
            continue
        doc["file"] = f"pdfs/{doc_id}.pdf"
        doc["retrieved"] = today
        doc["changed"] = hashlib.sha256(raw).hexdigest() != doc["sha256"]
        (out_dir / doc["file"]).write_bytes(raw)
    return failed


def save_documents(docs, out_dir, today):
    failed = fetch_pdfs(docs, out_dir, today)
    manifest = {i: {k: d[k] for k in ("file", "retrieved", "changed")} for i, d in docs.items() if d["file"]}
    (out_dir / "documents.json").write_text(json.dumps(manifest, indent=1))
    return failed


def attach_documents(docs, release_dir, out_dir):
    manifest = json.loads((release_dir / "documents.json").read_text())
    (out_dir / "pdfs").mkdir(parents=True, exist_ok=True)
    for doc_id, doc in docs.items():
        doc.update(manifest.get(doc_id, {"file": None, "retrieved": None, "changed": None}))
        if doc["file"]:
            shutil.copyfile(release_dir / doc["file"], out_dir / doc["file"])
    return [i for i, d in docs.items() if not d["file"]]


def main(command, out, release=None):
    out_dir = pathlib.Path(out)
    site = site_data()
    if command == "documents":
        failed = save_documents(site["docs"], out_dir, datetime.date.today().isoformat())
        if failed:
            sys.exit("not a PDF:\n" + "\n".join(failed))
        return
    shutil.copytree(HERE / "static", out_dir, dirs_exist_ok=True)
    if release:
        missing = attach_documents(site["docs"], pathlib.Path(release), out_dir)
        for doc_id in missing:
            print(f"::warning::Not in the documents release, so the site links to the carrier: "
                  f"{site['docs'][doc_id]['url']}. Run the Documents workflow to add it.")
    (out_dir / "data.json").write_text(json.dumps(site))


if __name__ == "__main__":
    main(*sys.argv[1:])
