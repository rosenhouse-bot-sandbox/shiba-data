"""Downloads documents.csv URLs, extracts page text, checks cover identity, compares to the baseline manifest.

Usage: python3 -I fetch_docs.py <documents.csv> <plans.csv> <cache_dir> <out.csv> <year> <county,county> [<baseline_manifest.json>]
Text goes to <cache_dir>/text/<sha256[:16]>.txt with "=====PAGE n=====" delimiters (1-based PDF pages).
"""
import csv
import hashlib
import json
import os
import re
import subprocess
import sys

EXTRACT = r'''
import sys, pypdfium2 as pdfium
d = pdfium.PdfDocument(sys.argv[1])
with open(sys.argv[2], "w") as f:
    for i in range(len(d)):
        f.write(f"=====PAGE {i+1}=====\n" + d[i].get_textpage().get_text_range() + "\n")
'''


def id_patterns(plan_id):
    """Regexes for the ways documents print a plan ID, e.g. H1036153000, H5439_015, H2923-001-000, H5439 | 015."""
    c, p, s = plan_id.split("-")
    seg = f"{int(s):03d}"
    return [rf"{c}\s*[-_|]?\s*(?:plan\s*)?{p}(?![0-9])", rf"{c}[-_ ]?{p}[-_ ]?{seg}"]


def doc_kind(text):
    head = text[:6000].lower()
    if "evidence of coverage" in head and "summary of benefits" not in head[:1500]:
        return "EOC"
    if "summary of benefits" in head:
        return "SB"
    return "OTHER"


def short_name(plan_name):
    return re.sub(r"\s*\(.*$", "", plan_name).strip()


def cover_check(text, plan_ids, kind, names, year, counties):
    head = re.sub(r"\s+", " ", text[:8000])
    whole = re.sub(r"\s+", " ", text)
    problems = []
    if str(year) not in head:
        problems.append(f"no {year} on first pages")
    for p in plan_ids:
        if not any(re.search(rx, whole, re.I) for rx in id_patterns(p)):
            if short_name(names[p]).lower() in whole.lower():
                problems.append(f"{p} printed only as plan name")
            else:
                problems.append(f"{p} not found")
    if kind in ("SB", "EOC") and doc_kind(text) != kind:
        problems.append(f"looks like {doc_kind(text)}")
    for county in counties:
        if county not in whole:
            problems.append(f"{county} not mentioned")
    return problems


def baseline_index(manifest):
    by_sha, by_url = {}, {}
    for f in manifest["files"]:
        by_sha[f["sha256"]] = f
        chk = f.get("url_check_2026_10_26") or {}
        if chk.get("sha256"):
            by_sha[chk["sha256"]] = f
        if f.get("url"):
            by_url[f["url"]] = f
    return by_sha, by_url


def compare(sha, url, by_sha, by_url):
    if sha in by_sha:
        return "same bytes as baseline", by_sha[sha]["path"]
    f = by_url.get(url) or by_url.get(re.sub(r"_00\d$", "_000", url))
    if f:
        return "different bytes from baseline (re-issued?)", f["path"]
    return "not in baseline", ""


def main(docs_csv, plans_csv, cache, out_csv, year, counties, manifest_path=None):
    names = {r["plan_id"]: r["plan_name"] for r in csv.DictReader(open(plans_csv))}
    counties = counties.split(",")
    by_sha, by_url = baseline_index(json.load(open(manifest_path))) if manifest_path else ({}, {})
    os.makedirs(os.path.join(cache, "pdf"), exist_ok=True)
    os.makedirs(os.path.join(cache, "text"), exist_ok=True)
    results = []
    for d in csv.DictReader(open(docs_csv)):
        tmp = os.path.join(cache, "pdf", hashlib.sha256(d["url"].encode()).hexdigest()[:16] + ".pdf")
        if not os.path.exists(tmp):
            subprocess.run(["curl", "-sS", "-L", "--max-time", "180", "-A", "Mozilla/5.0", "-o", tmp, d["url"]],
                           check=False)
        raw = open(tmp, "rb").read() if os.path.exists(tmp) else b""
        row = dict(d, sha256="", pages="", text_file="", cover_problems="", baseline="", baseline_file="")
        if not raw.startswith(b"%PDF"):
            row["cover_problems"] = "not a PDF"
            results.append(row)
            continue
        sha = hashlib.sha256(raw).hexdigest()
        txt = os.path.join(cache, "text", sha[:16] + ".txt")
        if not os.path.exists(txt):
            subprocess.run([sys.executable, "-I", "-c", EXTRACT, tmp, txt], check=False)
        text = open(txt).read() if os.path.exists(txt) else ""
        ids = d["plan_ids"].split(";")
        row.update(sha256=sha, pages=text.count("=====PAGE "), text_file=os.path.basename(txt),
                   cover_problems="; ".join(cover_check(text, ids, d["kind"], names, year, counties)))
        row["baseline"], row["baseline_file"] = compare(sha, d["url"], by_sha, by_url)
        row["plan_names"] = "; ".join(names[i] for i in ids)
        results.append(row)
    fields = list(results[0]) + (["plan_names"] if "plan_names" not in results[0] else [])
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(results)


if __name__ == "__main__":
    main(*sys.argv[1:])
