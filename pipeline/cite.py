"""Cites naturopathy, which the PBP lacks, from the SBs and EOCs that mention it.

Usage: python3 -I cite.py <documents_checked.csv> <text_dir> <out.csv>
The output is a layer (see layers.py).
"""
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layers  # noqa: E402

NOT_COVERED = re.compile(r"not covered under any condition", re.I)


def norm(s):
    return re.sub(r"\s+", " ", s.replace("￾", "")).strip()


def pages(text):
    parts = re.split(r"=====PAGE (\d+)=====\n", text)
    return {int(parts[i]): norm(parts[i + 1]) for i in range(1, len(parts) - 1, 2)}


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


def citations(docs, text):
    """Cites the first mention in each document for each of its plans."""
    found = []
    for doc in docs:
        mentions = naturopathy_mentions(text[doc["text_file"]])
        if mentions:
            page, ctx = mentions[0]
            found += [dict(sheet="main", plan_id=plan, column="U_naturopath", line="", value=naturopathy_dot(ctx),
                           url=doc["url"], pdf_page=page, quote=ctx) for plan in doc["plan_ids"].split(";")]
    return plan_dots(found)


def main(docs_csv, text_dir, out_csv):
    docs = [d for d in csv.DictReader(open(docs_csv)) if d["kind"] in ("SB", "EOC")]
    text = {d["text_file"]: pages(open(os.path.join(text_dir, d["text_file"])).read()) for d in docs}
    with open(out_csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=layers.COLUMNS)
        w.writeheader()
        w.writerows(citations(docs, text))


if __name__ == "__main__":
    main(*sys.argv[1:])
