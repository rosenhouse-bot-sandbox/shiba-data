"""Builds the static site from the live year's data, or lists the hashes of the PDFs it links.

Usage:
  (cd web && npm ci) && python3 -I web/build.py site <out_dir>
  python3 -I web/build.py docs

The pdxplans Worker serves each PDF from R2 as docs/<sha256>.pdf.
"""
import contextlib
import csv
import datetime
import html
import json
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "pipeline")]
import cms_sources  # noqa: E402
import fields  # noqa: E402
import layers  # noqa: E402
import terms  # noqa: E402
import trace  # noqa: E402
import years  # noqa: E402

DATA = years.data_dir()
# The site serves pdf.js itself, from web/node_modules after `npm ci`.
PDFJS = HERE / "node_modules" / "pdfjs-dist"

# Keep in sync with PAGE_REF in web/static/app.js.
PAGE_REF = re.compile(r"\b(EOC|SB|rider) pages? (\d+)", re.IGNORECASE)
SECTIONS = {
    "MA-PD": "Medicare Advantage with drug coverage",
    "NO-PART-D": "Medicare Advantage without drug coverage",
    "C-SNP": "Chronic condition special needs plans",
}


def rows(name, data_dir):
    with open(data_dir / name, newline="") as f:
        return list(csv.DictReader(f))


def sheet(csv_rows, labels, cites, changed, comments, cms):
    return {
        "columns": [column(k, v) for k, v in labels.items()],
        "rows": [{
            "plan_id": r["plan_id"],
            "section": r["section"],
            "cells": {k: cell(r[k], cites.get((r["plan_id"], k), []), comments.get((r["plan_id"], k)),
                              None if (r["plan_id"], k) in changed else cms.get((r["plan_id"], k)))
                      for k in labels},
        } for r in csv_rows],
    }


def column(key, label):
    c = {"key": key, "id": re.sub(r"^[A-Z]+_", "", key), "label": label}
    if key in cms_sources.MEDICARE_GOV:
        c["medicare_gov"] = cms_sources.MEDICARE_GOV[key]
    return c


def cell(value, cites, comment, cms):
    c = {"value": value, "cites": cites}
    if cms and not cites:
        c["cms"] = cms
    if comment:
        c["comment"] = comment
    return c


def site_data(data_dir=DATA, layer_names=layers.LAYERS, ignore=None):
    config = years.config(data_dir)
    year = config["year"]
    checked = rows("generated/documents_checked.csv", data_dir)
    doc_by_url = {d["url"]: d["sha256"][:16] for d in checked}
    docs = {d["sha256"][:16]: {
        "kind": d["kind"],
        "url": d["url"],
        "sha256": d["sha256"],
        "file": f"docs/{d['sha256']}.pdf",
        "pages": int(d["pages"]),
        "plan_ids": d["plan_ids"].split(";"),
    } for d in checked}

    live, cited = layers.citations(data_dir, {d["url"]: d["kind"] for d in checked}, layer_names, ignore)
    cites = {"main": {}, "dvha": {}}
    for c in cited:
        if c["hidden"] == layers.UNKNOWN_DOCUMENT:
            # An unknown document must not stop the build. The edit still sets its cell.
            print(f"::warning::An edit cites a document not in documents_checked.csv: {layers.where(c)} {c['url']}")
        if c["hidden"]:
            continue
        cites[c["sheet"]].setdefault((c["plan_id"], c["column"]), []).append({
            "line": int(c["line"]) if c["line"] else None,
            "value": c["value"],
            "doc": doc_by_url[c["url"]],
            "page": int(c["pdf_page"]),
            "quote": c["quote"],
        })

    changed = {name: {(g["plan_id"], k) for g, r in zip(generated, live[name]) for k, v in g.items() if r[k] != v}
               for name, generated in layers.generated(data_dir).items()}
    plans = rows("generated/plans.csv", data_dir)
    cms = {}
    for r in rows("generated/cms_sources.csv", data_dir):
        cms.setdefault((r["plan_id"], r["column"]), []).append(
            {k: r[k] for k in ("file", "field", "title", "value", "meaning")})
    for p in plans:
        p["docs"] = [i for i, d in docs.items() if p["plan_id"] in d["plan_ids"]]
        p["plan_finder_url"] = f"https://www.medicare.gov/plan-compare/#/plan-details/{year}-{p['plan_id']}?year={year}&lang=en"
    sheets = {name: (live[name], fields.labels(name)) for name in ("main", "dvha")}
    comments = {"main": {}, "dvha": {}}
    for c in rows("comments.csv", data_dir):
        csv_rows, labels = sheets[c["sheet"]]
        if c["column"] not in labels or c["plan_id"] not in {r["plan_id"] for r in csv_rows}:
            raise ValueError(f"comments.csv names no cell: {c['sheet']} {c['plan_id']} {c['column']}")
        if (c["plan_id"], c["column"]) in comments[c["sheet"]]:
            raise ValueError(f"comments.csv names a cell twice: {c['sheet']} {c['plan_id']} {c['column']}")
        if c["kind"] not in ("question", "caveat", "added"):
            raise ValueError(f"comments.csv {c['plan_id']} {c['column']}: unknown kind {c['kind']}")
        for ref in PAGE_REF.finditer(c["comment"]):
            kind, page = ref[1].upper(), int(ref[2])
            matches = [d for d in docs.values() if d["kind"] == kind and c["plan_id"] in d["plan_ids"]]
            if len(matches) != 1 or page > matches[0]["pages"]:
                raise ValueError(f"comments.csv {c['plan_id']} {c['column']}: {ref[0]} names no single document page")
        comments[c["sheet"]][(c["plan_id"], c["column"])] = {
            "kind": c["kind"], "text": c["comment"], "doc": doc_by_url[c["url"]], "page": int(c["pdf_page"]), "quote": c["quote"]}
    return {
        "year": year,
        "sheet_id": config.get("sheet_id"),
        "area": " & ".join(config["counties"]),
        "sections": SECTIONS,
        "plans": plans,
        "docs": docs,
        "cms_files": {"Landscape": config["landscape_zip"], "PBP": config["pbp_zip"]},
        **{name: sheet(csv_rows, labels, cites[name], changed[name], comments[name], cms)
           for name, (csv_rows, labels) in sheets.items()},
    }


def titled(index_html, site):
    title = f"pdxplans.org – {site['year']} Medicare Advantage plans"
    area = html.escape(site["area"])
    return (index_html.replace("<title>Medicare Advantage plans</title>", f"<title>{title}</title>")
            .replace("<h1>Medicare Advantage plans</h1>", f"<h1>{title} <span>for {area}</span></h1>"))


def commit():
    return os.environ.get("GITHUB_SHA") or subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=HERE, capture_output=True, text=True, check=True).stdout.strip()


def write_traces(out_dir, sha):
    """Writes each cell's trace where the Worker serves it."""
    year = years.config(DATA)["year"]
    with tempfile.TemporaryDirectory() as tmp:
        trace.build(year, f"{tmp}/trace.sqlite", sha)
        with contextlib.closing(sqlite3.connect(f"{tmp}/trace.sqlite")) as db:
            for sheet, plan_id, col in db.execute("SELECT sheet, plan_id, col FROM draft_cell").fetchall():
                path = out_dir / "trace" / str(year) / sheet / plan_id / f"{col}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(trace.cell(db, sheet, plan_id, col)))


def main(command, out=None):
    site = site_data()
    if command == "docs":
        print("\n".join(d["sha256"] for d in site["docs"].values()))
        return
    out_dir = pathlib.Path(out)
    _, kept, dropped = layers.live(DATA)
    for c in dropped:
        print(f"::warning::Dropped a citation whose value is not the live cell's: {layers.where(c)} {c['value']}")
    for c in kept + dropped:
        if "beneath" in c:
            print(f"::warning::An edit's author saw {c['saw']}, but the cell beneath it is now {c['beneath']}: {layers.where(c)}")
    shutil.copytree(HERE / "static", out_dir, dirs_exist_ok=True)
    (out_dir / "pdfjs").mkdir(exist_ok=True)
    for name in ["build/pdf.min.mjs", "build/pdf.worker.min.mjs", "web/pdf_viewer.css"]:
        shutil.copy(PDFJS / name, out_dir / "pdfjs")
    (out_dir / "index.html").write_text(titled((HERE / "static" / "index.html").read_text(), site))
    site["built"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    site["terms"] = terms.resolve(HERE.parent, commit(), site["year"])
    write_traces(out_dir, commit())
    (out_dir / "data.json").write_text(json.dumps(site))


if __name__ == "__main__":
    main(*sys.argv[1:])
