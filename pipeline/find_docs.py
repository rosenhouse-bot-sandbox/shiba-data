"""Lists each plan's documents: browser finds, then the volunteers' Links sheet, then carrier URL templates.

Usage: python3 -I find_docs.py <plans.csv> <found.csv> <links.csv> <out.csv> <year>

An earlier source wins a plan's SB or EOC, so a recorded URL beats a guessed one. A row that covers several plans keeps the plans still missing its kind.
"""
import csv
import sys

COLUMNS = ["plan_ids", "kind", "url", "found_via"]
KINDS = ("SB", "EOC")
KAISER = ("https://healthy.kaiserpermanente.org/content/dam/kporg/final/documents/health-plan-documents/"
          "{folder}/medicare/{year}/{name}-nw.pdf")


def humana(p, year, kind):
    contract, plan, segment = p["plan_id"].split("-")
    return f"https://assets.humana.com/is/content/humana/{contract}{plan}{int(segment):03}{kind}{year[2:]}pdf"


def devoted(p, year, kind):
    name = p["plan_name"].replace(" ", "-").replace("(", "%28").replace(")", "%29")
    contract, plan, segment = p["plan_id"].split("-")
    number = f"{contract}-{plan}" + (f"-{int(segment):03}" if int(segment) else "")
    return f"https://assets.devoted.com/plan-documents/{year}/{year}-{name}-{kind}-{number}-ENG.pdf"


PER_PLAN = {"Humana": humana, "Devoted Health": devoted}


def templated(plans, year):
    """Returns rows for carriers with predictable URLs. Kaiser's region-wide documents come after per-plan ones."""
    rows = [dict(plan_ids=p["plan_id"], kind=kind, url=PER_PLAN[p["organization"]](p, year, kind))
            for p in plans if p["organization"] in PER_PLAN for kind in KINDS]
    kaiser = ";".join(p["plan_id"] for p in plans if p["organization"] == "Kaiser Permanente")
    if kaiser:
        rows += [dict(plan_ids=kaiser, kind="SB", url=KAISER.format(folder="summary-of-benefits", year=year,
                                                                     name="summary-of-benefits")),
                 dict(plan_ids=kaiser, kind="EOC", url=KAISER.format(folder="eoc", year=year, name="evidence-of-coverage"))]
    return [dict(r, found_via="URL template in pipeline/find_docs.py") for r in rows]


def offers(plans, found, links, year):
    """Each source's rows in the order tried, as (source, row, the plans whose document of that kind the row gives)."""
    sources = {"found.csv": found, "links.csv": [dict(r, found_via="volunteers' Links sheet") for r in links],
               "URL template": templated(plans, year)}
    have, out = set(), []
    for source, rows in sources.items():
        for r in rows:
            gives = [i for i in r["plan_ids"].split(";") if (i, r["kind"]) not in have]
            have.update((i, r["kind"]) for i in gives)
            out.append((source, r, gives))
    return out


def documents(plans, found, links, year):
    """Prints a warning for each plan left without an SB or EOC."""
    ids = {p["plan_id"] for p in plans}
    for r in found + links:
        if r["kind"] not in KINDS + ("RIDER", "DENTAL") or not set(r["plan_ids"].split(";")) <= ids:
            raise SystemExit(f"A row names an unknown kind or plan: {r}")
    offered = offers(plans, found, links, year)
    rows = [dict(r, plan_ids=";".join(gives)) for _, r, gives in offered if gives]
    have = {(i, r["kind"]) for _, r, gives in offered for i in gives}
    for p in plans:
        for kind in KINDS:
            if (p["plan_id"], kind) not in have:
                print(f"::warning::No {kind} for {p['plan_id']}")
    return rows


def read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def main(plans_csv, found_csv, links_csv, out_csv, year):
    rows = documents(read(plans_csv), read(found_csv), read(links_csv), str(year))
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main(*sys.argv[1:])
