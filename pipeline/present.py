"""Writes generated/presented.csv, a layer that presents sheet columns from facts and cites them.

Usage: python3 -I pipeline/present.py <year>
"""
import collections, csv, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import facts, layers, years

RANK = {s: i for i, s in enumerate(facts.SOURCES_BEST_FIRST)}
OFFICES = ("office.pcp", "office.specialist", "freestanding")
ADVANCED = ("imaging.diagnostic.advanced.ct", "imaging.diagnostic.advanced.mri", "imaging.diagnostic.advanced.pet")
# These carriers' imaging keeps no $0 low end for a $0 diagnostic mammogram. fields.py omits Devoted (#127).
NO_MAMMOGRAM_ZERO = ("Kaiser", "Humana", "Devoted")


def usable(f):
    return (f["network"] in ("in", "any") and f["covered_by"] == "medicare" and f["cost_kind"] in ("copay", "coinsurance")
            and not (f["condition"] or f["provider_tier"] or f["package"]))


def best(found, leaf, setting, ok=usable):
    """The ok facts for leaf and setting from the best source, and within it the most specific."""
    fits = [f for f in found if ok(f) and facts.covers(f["benefit"], leaf) and facts.covers(f["setting"], setting)]
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


TRIPS = ("ambulance.ground", "ambulance.air")
PRICED = ("copay", "coinsurance")


def trip_here(f):
    return (f["network"] in ("in", "any") and f["covered_by"] == "medicare" and f["cost_kind"] in PRICED
            and not (f["provider_tier"] or f["package"]))


def trip_abroad(f):
    return (f["setting"] == "outside_us" and f["cost_kind"] in PRICED + ("covered", "not_covered")
            and not (f["provider_tier"] or f["package"]))


def show_or(found):
    """The dollar range, or the percent range, or both joined by "or"."""
    dollars = sorted(facts.number(a) for a in amounts(found) if a.startswith("$"))
    percents = sorted(facts.number(a) for a in amounts(found) if a.endswith("%"))
    shown = [span(money(dollars[0]), money(dollars[-1]))] if dollars else []
    shown += [span(f"{percents[0]:g}%", f"{percents[-1]:g}%")] if percents else []
    return " or ".join(shown)


def ambulance(organization, found):
    """Line 1 is trips within the U.S. and line 2 is emergency trips abroad, each as (value, cited facts).
    See the expert's rules in #99."""
    here = unique([f for leaf in TRIPS for f in best(found, leaf, "any", trip_here)])
    abroad = unique([f for leaf in TRIPS for f in best(found, leaf, "outside_us", trip_abroad)])
    priced = [f for f in abroad if f["cost_kind"] in PRICED]
    covered = [f for f in abroad if f["cost_kind"] == "covered"]
    excluded = [f for f in abroad if f["cost_kind"] == "not_covered"]
    if priced:
        line2 = (show_or(priced), priced)
    elif covered:
        plain = [f for f in here if not f["condition"]]
        line2 = (show_or(plain), covered + plain)
    elif excluded:
        line2 = ("not covered", excluded)
    else:
        line2 = ("", [])
    return [(show_or(here), here), line2]


def outpatient_surgery(organization, found):
    """Line 1 is outpatient hospital surgery and line 2 is surgical center surgery, each as (value, cited facts).
    A $0 diagnostic colonoscopy or skin biopsy priced in that setting starts its line at $0 (fields.py)."""
    def line(setting):
        cost = best(found, "surgery", setting)
        zeros = [f for leaf in ("surgery.colonoscopy", "surgery.skin_biopsy")
                 for f in best(found, leaf, setting, lambda f: usable(f) and f["benefit"] == leaf and f["setting"] == setting)
                 if f["cost_kind"] == "copay" and f["amount"] == "$0"]
        cited = unique(cost + zeros) if cost else []
        return show(cited), cited
    return [line("outpatient_hospital"), line("asc")]


def unique(found):
    return list({id(f): f for f in found}.values())


def plan_facts(data):
    by_plan = collections.defaultdict(list)
    for name in ("machine/document_facts.csv", "generated/pbp_facts.csv"):
        for f in facts.read(data / name):
            by_plan[f["plan_id"]].append(f)
    return by_plan


# A rule returns the lines of its column.
COLUMNS = {"L_xray_imaging": xray_imaging, "AB_ambulance": ambulance, "I_outpatient_surgery": outpatient_surgery}


def lines(data, column):
    """{plan_id: [(value, cited facts), ...]} for each plan on the main sheet."""
    organization = {r["plan_id"]: r["organization"] for r in layers.rows(data / "generated" / "plans.csv")}
    found = plan_facts(data)
    return {r["plan_id"]: COLUMNS[column](organization[r["plan_id"]], found[r["plan_id"]])
            for r in layers.generated(data)["main"]}


def layer_rows(data):
    """One row per line and cited document quote."""
    url = {d["sha256"]: d["url"] for d in layers.rows(data / "generated" / "documents_checked.csv") if d["sha256"]}
    out = {}
    for column in COLUMNS:
        for plan_id, got in lines(data, column).items():
            for n, (value, cited) in enumerate(got, 1):
                row = dict(sheet="main", plan_id=plan_id, column=column, line=str(n), value=value)
                cites = [(url[f["doc_sha"]], f["page"], q) for f in cited if f["source"] in facts.DOCUMENTS
                         for q in json.loads(f["quotes"])]
                for cite in cites if value else []:
                    full = dict(row, **dict(zip(("url", "pdf_page", "quote"), cite)))
                    out[tuple(full.values())] = full
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
