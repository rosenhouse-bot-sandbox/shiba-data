"""Builds the plan documents release, its zip, or the static site from the live year's data.

Usage:
  python3 -I web/build.py documents <out_dir>
  python3 -I web/build.py site <out_dir> [<documents_dir>]
  python3 -I web/build.py zip <documents_dir> <zip_file>
"""
import csv
import datetime
import hashlib
import html
import json
import pathlib
import re
import shutil
import sys
import urllib.request
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
import fields  # noqa: E402
import layers  # noqa: E402
import years  # noqa: E402

DATA = years.data_dir()

# Keep in sync with PAGE_REF in web/static/app.js.
PAGE_REF = re.compile(r"\b(EOC|SB|rider) pages? (\d+)", re.IGNORECASE)


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


def site_data(data_dir=DATA, layer_names=layers.LAYERS):
    config = years.config(data_dir)
    year = config["year"]
    checked = rows("generated/documents_checked.csv", data_dir)
    doc_by_url = {d["url"]: d["sha256"][:16] for d in checked}
    docs = {d["sha256"][:16]: {
        "kind": d["kind"],
        "url": d["url"],
        "sha256": d["sha256"],
        "pages": int(d["pages"]),
        "plan_ids": d["plan_ids"].split(";"),
    } for d in checked}

    live, kept, _ = layers.live(data_dir, layer_names)
    cites = {"main": {}, "dvha": {}}
    for c in kept:
        if c["layer"] == layers.EDITS and c["url"] not in doc_by_url:
            # An unknown document must not stop the build. The edit still sets its cell.
            if c["url"]:
                print(f"::warning::An edit cites a document not in documents_checked.csv: {layers.where(c)} {c['url']}")
            continue
        if c["url"] not in doc_by_url:
            raise ValueError(f"A citation names a document not in documents_checked.csv: {layers.where(c)} {c['url']}")
        cites[c["sheet"]].setdefault((c["plan_id"], c["column"]), []).append({
            "line": int(c["line"]) if c["line"] else None,
            "value": c["value"],
            "doc": doc_by_url[c["url"]],
            "page": int(c["pdf_page"]),
            "quote": c["quote"],
        })
    for sheet_cites in cites.values():
        for key, cell_cites in sheet_cites.items():
            if any(docs[c["doc"]]["kind"] != "SB" for c in cell_cites):
                sheet_cites[key] = [c for c in cell_cites if docs[c["doc"]]["kind"] != "SB"]
    pbp = {name: {(g["plan_id"], k): v for g, r in zip(generated, live[name]) for k, v in g.items() if r[k] != v}
           for name, generated in layers.generated(data_dir).items()}

    plans = rows("generated/plans.csv", data_dir)
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
        if c["kind"] not in ("contradicts", "note"):
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
        "area": " & ".join(config["counties"]),
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


def plan_names(doc):
    return zip(doc["plan_ids"].split(";"), doc["plan_names"].split("; "), strict=True)


def zip_name(plan_id, plan_name, kind):
    return f"{plan_name} ({plan_id}) {kind}.pdf"


def zip_documents(release_dir, zip_path, data_dir=DATA):
    manifest = json.loads((release_dir / "documents.json").read_text())
    checked = {d["sha256"][:16]: d for d in rows("generated/documents_checked.csv", data_dir)}
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for doc_id, entry in manifest.items():
            pdf = release_dir / entry["file"]
            if doc_id not in checked:
                z.write(pdf, entry["file"])
                continue
            for plan_id, name in plan_names(checked[doc_id]):
                z.write(pdf, zip_name(plan_id, name, checked[doc_id]["kind"]))


def titled(index_html, site):
    title = f"shibasheets.org – {site['year']} Medicare Advantage plans"
    area = html.escape(site["area"])
    return (index_html.replace("<title>Medicare Advantage plans</title>", f"<title>{title}</title>")
            .replace("<h1>Medicare Advantage plans</h1>", f"<h1>{title} <span>for {area}</span></h1>"))


def main(command, out, release=None):
    if command == "zip":
        zip_documents(pathlib.Path(out), pathlib.Path(release))
        return
    out_dir = pathlib.Path(out)
    site = site_data()
    _, kept, dropped = layers.live(DATA)
    for c in dropped:
        print(f"::warning::Dropped a citation whose value is not the live cell's: {layers.where(c)} {c['value']}")
    for s in layers.stale_strikes(DATA):
        print(f"::warning::A strike matches no machine quote: {s['sheet']} {s['plan_id']} {s['column']} {s['quote']}")
    for c in kept + dropped:
        if "beneath" in c:
            print(f"::warning::An edit's author saw {c['saw']}, but the cell beneath it is now {c['beneath']}: {layers.where(c)}")
    if command == "documents":
        failed = save_documents(site["docs"], out_dir, datetime.date.today().isoformat())
        if failed:
            sys.exit("not a PDF:\n" + "\n".join(failed))
        return
    shutil.copytree(HERE / "static", out_dir, dirs_exist_ok=True)
    (out_dir / "index.html").write_text(titled((HERE / "static" / "index.html").read_text(), site))
    if release:
        missing = attach_documents(site["docs"], pathlib.Path(release), out_dir)
        for doc_id in missing:
            print(f"::warning::Not in the documents release, so the site links to the carrier: "
                  f"{site['docs'][doc_id]['url']}. Run the Documents workflow to add it.")
    site["built"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (out_dir / "data.json").write_text(json.dumps(site))


if __name__ == "__main__":
    main(*sys.argv[1:])
