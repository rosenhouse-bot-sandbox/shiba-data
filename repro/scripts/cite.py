"""Finds the PDF page of each quote in sb_facts.csv and adds naturopathy facts found by text search.

Usage: python3 -I cite.py <sb_facts.csv> <documents_checked.csv> <text_dir> <out_citations.csv>
A quote matches when it appears on one page after whitespace is collapsed.
"""
import csv
import os
import re
import sys

NOT_COVERED = re.compile(r"not covered under any condition", re.I)


def norm(s):
    return re.sub(r"\s+", " ", s.replace("￾", "")).strip()


def pages(text):
    parts = re.split(r"=====PAGE (\d+)=====\n", text)
    return {int(parts[i]): norm(parts[i + 1]) for i in range(1, len(parts) - 1, 2)}


def find_page(doc_pages, quote):
    q = norm(quote)
    return next((n for n, t in doc_pages.items() if q in t), None)


def naturopathy_dot(context):
    """A naturopathy benefit paid from a general wellness fund is a judgment call (◐)."""
    return "◐" if re.search(r"wellness", context, re.I) else "●"


def plan_dots(rows):
    """A plan's naturopathy dot is ◐ when any of its documents makes it a judgment call."""
    judged = {r["plan_id"] for r in rows if r["value"] == "◐"}
    return [dict(r, value="◐" if r["plan_id"] in judged else r["value"]) for r in rows]


def naturopathy_mentions(doc_pages):
    """Pages that mention naturopathy other than in an exclusions-table "not covered" entry."""
    found = []
    for n, t in doc_pages.items():
        for m in re.finditer(r"naturopath\w*", t, re.I):
            if not NOT_COVERED.search(t[m.end():m.end() + 120]):
                found.append((n, t[max(0, m.start() - 100):m.end() + 100]))
    return found


def main(facts_csv, docs_csv, text_dir, out_csv):
    docs = [d for d in csv.DictReader(open(docs_csv)) if d["kind"] in ("SB", "EOC")]
    text = {d["text_file"]: pages(open(os.path.join(text_dir, d["text_file"])).read()) for d in docs}
    out, missing = [], []
    for f in csv.DictReader(open(facts_csv)):
        for plan in f["plan_ids"].split(";"):
            doc = next(d for d in docs if plan in d["plan_ids"].split(";") and d["kind"] == f["kind"])
            page = find_page(text[doc["text_file"]], f["quote"])
            if page is None:
                missing.append((plan, f["column"], f["quote"]))
                continue
            out.append(dict(plan_id=plan, column=f["column"], line=f["line"], value=f["value"],
                            kind=f["kind"], url=doc["url"], pdf_page=page, quote=norm(f["quote"])))
    naturopathy = []
    for doc in docs:
        mentions = naturopathy_mentions(text[doc["text_file"]])
        if mentions:
            page, ctx = mentions[0]
            value = naturopathy_dot(ctx)
            for plan in doc["plan_ids"].split(";"):
                naturopathy.append(dict(plan_id=plan, column="U_naturopath", line="", value=value, kind=doc["kind"],
                                        url=doc["url"], pdf_page=page, quote=ctx))
    out += plan_dots(naturopathy)
    with open(out_csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    for m in missing:
        print("QUOTE NOT FOUND:", *m)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
