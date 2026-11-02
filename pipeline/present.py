"""Writes generated/presented.csv, a layer that presents sheet columns from facts and cites them.

Usage: python3 -I pipeline/present.py <year>
"""
import collections, csv, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import facts, layers, years

COLUMN = "L_xray_imaging"
RANK = {s: i for i, s in enumerate(facts.SOURCES_BEST_FIRST)}
OFFICES = ("office.pcp", "office.specialist", "freestanding")
ADVANCED = ("imaging.diagnostic.advanced.ct", "imaging.diagnostic.advanced.mri", "imaging.diagnostic.advanced.pet")
# These carriers' imaging keeps no $0 low end for a $0 diagnostic mammogram. fields.py omits Devoted (#127).
NO_MAMMOGRAM_ZERO = ("Kaiser", "Humana", "Devoted")


def usable(f):
    return (f["network"] in ("in", "any") and f["covered_by"] == "medicare" and f["cost_kind"] in ("copay", "coinsurance")
            and not (f["condition"] or f["provider_tier"] or f["package"]))


def best(found, leaf, setting):
    """The facts for leaf and setting from the best source, and within it the most specific."""
    fits = [f for f in found if usable(f) and facts.covers(f["benefit"], leaf) and facts.covers(f["setting"], setting)]
    if not fits:
        return []
    top = min(RANK[f["source"]] for f in fits)
    fits = [f for f in fits if RANK[f["source"]] == top]

    def depth(f):
        return f["benefit"].count("."), f["setting"] != "any", f["setting"].count(".")

    deepest = max(map(depth, fits))
    return [f for f in fits if depth(f) == deepest]


def winners(found, leaves, settings):
    """The best facts at the settings, or at an outpatient hospital if none of the settings has one."""
    got = [f for s in settings for leaf in leaves for f in best(found, leaf, s)]
    return got or [f for leaf in leaves for f in best(found, leaf, "outpatient_hospital")]


def amounts(found):
    return [n for f in found for alternative in f["amount"].split(" or ") for n in alternative.split("-")]


def money(n):
    return f"${n:,.0f}" if n == int(n) else f"${n:,.2f}"


def span(low, high):
    return low if low == high else f"{low}-{high}"


def show(found):
    """The range of the facts' amounts: dollars, percents, or the lowest dollar to the highest percent."""
    dollars = sorted(facts.number(a) for a in amounts(found) if a.startswith("$"))
    percents = sorted(facts.number(a) for a in amounts(found) if a.endswith("%"))
    if dollars and percents:
        return f"{money(dollars[0])}-{percents[-1]:g}%"
    if dollars:
        return span(money(dollars[0]), money(dollars[-1]))
    return span(f"{percents[0]:g}%", f"{percents[-1]:g}%") if percents else ""


def xray_imaging(organization, found):
    """Line 1 is X-rays and line 2 is CT, MRI and PET, each as (value, cited facts). See fields.py."""
    humana = "Humana" in organization
    xrays = winners(found, ["imaging.xray"], OFFICES[:2] if humana else OFFICES)
    advanced = winners(found, ADVANCED, OFFICES)
    line2 = show(advanced)
    mammograms = [f for f in winners(found, ["imaging.diagnostic.mammogram"], OFFICES)
                  if f["cost_kind"] == "copay" and f["amount"] == "$0"]
    if line2 and mammograms and not any(name in organization for name in NO_MAMMOGRAM_ZERO):
        line2 = show(advanced + mammograms)
        advanced += mammograms
    return [(show(xrays), unique(xrays)), (line2, unique(advanced))]


def unique(found):
    return list({id(f): f for f in found}.values())


def plan_facts(data):
    by_plan = collections.defaultdict(list)
    for name in ("machine/document_facts.csv", "generated/pbp_facts.csv"):
        for f in facts.read(data / name):
            by_plan[f["plan_id"]].append(f)
    return by_plan


def lines(data):
    """{plan_id: [(value, cited facts), ...]} for each plan on the main sheet."""
    organization = {r["plan_id"]: r["organization"] for r in layers.rows(data / "generated" / "plans.csv")}
    found = plan_facts(data)
    return {r["plan_id"]: xray_imaging(organization[r["plan_id"]], found[r["plan_id"]])
            for r in layers.generated(data)["main"]}


def layer_rows(data):
    """One row per line and cited document quote. A line with no document fact keeps its generated value."""
    url = {d["sha256"]: d["url"] for d in layers.rows(data / "generated" / "documents_checked.csv") if d["sha256"]}
    out = {}
    for plan_id, got in lines(data).items():
        for n, (value, cited) in enumerate(got, 1):
            for f in cited:
                if value and f["source"] in facts.DOCUMENTS:
                    for quote in json.loads(f["quotes"]):
                        row = dict(sheet="main", plan_id=plan_id, column=COLUMN, line=str(n), value=value,
                                   url=url[f["doc_sha"]], pdf_page=f["page"], quote=quote)
                        out[tuple(row.values())] = row
    return sorted(out.values(), key=lambda r: tuple(r.values()))


def write(data):
    with open(data / layers.PRESENTED, "w", newline="") as f:
        out = csv.DictWriter(f, layers.COLUMNS, lineterminator="\n")
        out.writeheader()
        out.writerows(layer_rows(data))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    write(years.data_dir(int(sys.argv[1])))
