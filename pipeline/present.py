"""Writes generated/presented.csv, a layer that presents sheet columns from facts and cites them.

Usage: python3 -I pipeline/present.py <year>
"""
import collections, csv, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import facts, layers, years

RANK = {s: i for i, s in enumerate(facts.SOURCES_BEST_FIRST)}
OFFICES = ("office.pcp", "office.specialist", "freestanding")
ADVANCED = ("imaging.diagnostic.advanced.ct", "imaging.diagnostic.advanced.mri", "imaging.diagnostic.advanced.pet")
# These carriers' imaging keeps no $0 low end for a $0 diagnostic mammogram. fields.py omits Devoted (#127).
NO_MAMMOGRAM_ZERO = ("Kaiser", "Humana", "Devoted")


def top(found):
    """The facts from the best source among them."""
    return [f for f in found if RANK[f["source"]] == min(RANK[g["source"]] for g in found)]


def usable(f):
    return (f["network"] in ("in", "any") and f["covered_by"] == "medicare" and f["cost_kind"] in ("copay", "coinsurance")
            and not (f["condition"] or f["provider_tier"] or f["package"]))


def best(found, leaf, setting, ok=usable):
    """The ok facts for leaf and setting from the best source, and within it the most specific."""
    fits = [f for f in found if ok(f) and facts.covers(f["benefit"], leaf) and facts.covers(f["setting"], setting)]
    if not fits:
        return []
    fits = top(fits)

    def depth(f):
        return f["benefit"].count("."), f["setting"] != "any", f["setting"].count(".")

    deepest = max(map(depth, fits))
    return [f for f in fits if depth(f) == deepest]


def winners(found, leaves, settings, ok=usable):
    """The best ok facts at the settings, or at an outpatient hospital if none of the settings has one."""
    got = [f for s in settings for leaf in leaves for f in best(found, leaf, s, ok)]
    return got or [f for leaf in leaves for f in best(found, leaf, "outpatient_hospital", ok)]


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


def priced(f, network="in"):
    return (f["network"] in (network, "any") and f["covered_by"] == "medicare" and f["cost_kind"] in PRICED
            and not f["package"])


def trip_here(f):
    return priced(f) and not f["provider_tier"]


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
                 if f["amount"] == "$0"]
        cited = cost + zeros if cost else []
        return show(cited), cited
    return [line("outpatient_hospital"), line("asc")]


ZERO_TESTS = ("AgeRight", "Regence")
# This plan's $140 sleep study counts, though only outpatient hospitals offer it (fields.py).
HOSPITAL_SLEEP_STUDY = ("H1036-306-0",)


ELIGIBILITY = re.compile(r"medicaid|\bQMB|extra help|eligib", re.I)


def any_test(f):
    """A price for some of the tests, such as "certain lab services", but not one for some members only."""
    return priced(f) and not (f["provider_tier"] or ELIGIBILITY.search(f["condition"]))


def tests_labs(organization, found):
    """Shows "tests/labs". Each side uses office and freestanding prices, or outpatient hospital ones if there are none."""
    tests = winners(found, ["tests.diagnostic"], OFFICES, any_test)
    if any(f["plan_id"] in HOSPITAL_SLEEP_STUDY for f in found):
        tests += best(found, "tests.diagnostic.sleep_study", "outpatient_hospital")
    if tests and any(name in organization for name in ZERO_TESTS):
        zeros = winners(found, ["imaging.diagnostic.mammogram"], OFFICES) + [
            f for s in ("outpatient_hospital", "asc") for f in best(found, "surgery.colonoscopy", s)]
        tests += [f for f in zeros if f["amount"] == "$0"]
    tests, labs = unique(tests), winners(found, ["tests.lab"], OFFICES, any_test)
    return [(f"{show(tests)}/{show(labs)}" if tests or labs else "", tests + labs)]


def visit_line(found, setting, network):
    got = best(found, "visits", setting, lambda f: priced(f, network))
    got = [f for f in got if f["network"] == network] or got
    got = [f for f in got if not f["condition"]] or got
    return show(got), got


def visits(setting):
    """Line 1 is in network and line 2 out of network, if the plan prices any visit out of network."""
    def rule(organization, found):
        out = any(f["benefit"] == "visits" and f["network"] == "out" and priced(f, "out") for f in found)
        return [visit_line(found, setting, "in"), visit_line(found, setting, "out") if out else ("", [])]
    return rule


THERAPIES = ("rehab.physical", "rehab.occupational", "rehab.speech")


def outpatient_rehab(organization, found):
    """Shows therapy visit prices at offices and freestanding facilities, or at outpatient hospitals if there are none."""
    got = unique(winners(found, THERAPIES, OFFICES))
    return [(show(got), got)]


def days(f):
    """(first, last) days of a per-day cost, last None for "days 6+", or None."""
    m = re.fullmatch(r"days ([1-9]\d*)(?:-([1-9]\d*)|\+)", f["limit"]) if f["unit"] == "per day" else None
    return m and (int(m[1]), m[2] and int(m[2]))


def stay_ok(f):
    return usable(dict(f, condition="")) and f["condition"] in ("", f["limit"])


def inpatient(organization, found):
    """Line 1 is the cost and line 2 the days it applies, as "$395 | 1-5". A cost per stay is "per admission"."""
    got = best(found, "inpatient.acute", "any", stay_ok)
    daily = [f for f in got if days(f)]
    paid = [f for f in daily if any(facts.number(a) > 0 for a in amounts([f]))]
    if paid:
        first = min(days(f)[0] for f in paid)
        last = [days(f)[1] for f in paid]
        return [(show(paid), paid), (span(str(first), str(max(last))) if all(last) else f"{first}+", paid)]
    stays = [f for f in got if f["unit"] == "per stay"]
    if stays:
        return [(f"{show(stays)} per admission", stays), ("", [])]
    return [(show(got), got), ("", [])]


def unique(found):
    return list({id(f): f for f in found}.values())


def giveback(organization, found):
    """Shows the monthly Part B premium reduction."""
    got = best(found, "giveback", "any", lambda f: f["cost_kind"] in ("part_b_reduction", "covered")
               and not (f["package"] or f["provider_tier"]))
    got = [f for f in got if not f["condition"]] or got
    paid = [f for f in got if f["cost_kind"] == "part_b_reduction"]
    return [(show(paid), paid)] if paid else [("●", got)] if got else [("", [])]


def drug_price(f):
    return (priced(f) and not f["provider_tier"] and facts.covers("part_b_drugs", f["benefit"])
            and (f["cost_kind"] == "coinsurance" or f["amount"] == "$0"))


def part_b_drugs(organization, found):
    """Shows the range of Part B drug coinsurance, from each kind of drug's best source.
    A $0 copay, such as for vaccines, counts as 0%."""
    ok = [f for f in found if drug_price(f)]
    got = [f for leaf in sorted({f["benefit"] for f in ok}) for f in top([g for g in ok if g["benefit"] == leaf])]
    percents = sorted(facts.number(n) for n in amounts(got))
    return [(span(f"{percents[0]:g}%", f"{percents[-1]:g}%") if got else "", got)]


def deductible_ok(f):
    return (f["cost_kind"] == "deductible" and f["covered_by"] == "medicare"
            and not (f["condition"] or f["provider_tier"] or f["package"]))


def medical_deductible(organization, found):
    """Shows the in-network deductible, or else the out-of-network one, and says if it applies to some services only.
    A $0 in-network deductible shows as $0, whatever the out-of-network one is."""
    for networks in (("in", "any"), ("out",)):
        def ok(f):
            return deductible_ok(f) and f["network"] in networks
        got = best(found, "medical_deductible.some", "any", ok)
        if got:
            break
    else:
        return [("", [])]
    if show(got) == "$0":
        return [("$0", got)]
    some = [f for f in found if f["benefit"] == "medical_deductible.some" and ok(f)]
    part_b = [f for f in found if f["benefit"] == "medical_deductible.part_b" and f["cost_kind"] == "covered"]
    value = "Part B deductible" if part_b else show(got)
    if networks == ("out",):
        value += " some out-of-network services" if some else " out-of-network only"
    elif some:
        value += " some"
    return [(value, unique(got + some + part_b))]


DOT_KINDS = ("copay", "coinsurance", "allowance", "max", "visit_limit", "covered")


def offers(f):
    """Says if the fact is a routine benefit for every member, with no package to buy."""
    return (f["covered_by"] == "supplemental" and f["cost_kind"] in DOT_KINDS
            and not (f["package"] or f["condition"] or f["provider_tier"]))


def dot(*leaves):
    """Shows ● for a routine benefit. Facts for only a Medicare, package, conditional or uncovered benefit cite a blank."""
    def rule(organization, found):
        mine = [f for f in found if any(facts.covers(f["benefit"], leaf) for leaf in leaves) and f["network"] in ("in", "any")]
        yes = [f for f in mine if offers(f)]
        return [("●", top(yes))] if yes else [("", top(mine) if mine else [])]
    return rule


def plan_facts(data):
    by_plan = collections.defaultdict(list)
    for name in ("machine/document_facts.csv", "generated/pbp_facts.csv"):
        for f in facts.read(data / name):
            by_plan[f["plan_id"]].append(f)
    return by_plan


# A rule returns the lines of its column.
COLUMNS = {"L_xray_imaging": xray_imaging, "AB_ambulance": ambulance, "I_outpatient_surgery": outpatient_surgery,
           "F_primary_care": visits("office.pcp"), "G_specialist": visits("office.specialist"), "H_inpatient": inpatient,
           "J_outpatient_rehab": outpatient_rehab, "K_tests_labs": tests_labs, "Z_part_b_reduction": giveback,
           "M_part_b_drugs": part_b_drugs, "O_medical_deductible": medical_deductible,
           "S_acupuncture": dot("extras.acupuncture"), "T_chiropractic": dot("extras.chiropractic"),
           "V_massage": dot("extras.massage"), "X_transportation": dot("extras.transportation"),
           "R_dental": dot("dental.preventive", "dental.comprehensive"), "U_naturopath": dot("extras.naturopathy")}


def lines(data, column):
    """{plan_id: [(value, cited facts), ...]} for each plan on the main sheet."""
    organization = {r["plan_id"]: r["organization"] for r in layers.rows(data / "generated" / "plans.csv")}
    found = plan_facts(data)
    return {r["plan_id"]: COLUMNS[column](organization[r["plan_id"]], found[r["plan_id"]])
            for r in layers.generated(data)["main"]}


# Plans whose cell keeps its other layers' value, because the facts miss part of it.
HELD = {
    ("K_tests_labs", "H2406-070-0"): "readers found no diagnostic test price",
    ("K_tests_labs", "H2923-009-0"): "readers found a 50% lab price but no 0%",
    ("K_tests_labs", "H3817-008-1"): "readers missed the $0 HbA1c lab price",
    ("K_tests_labs", "H5439-010-0"): "readers missed the 0% and $0 test prices",
    ("K_tests_labs", "H5439-011-0"): "readers missed the 0% and $0 test prices",
    ("K_tests_labs", "H5439-015-0"): "readers missed the 0% and $0 test prices",
    ("K_tests_labs", "H5439-019-0"): "readers missed the 0% and $0 test prices",
    ("K_tests_labs", "H6815-038-0"): "readers took a $200 price for tests that is not a diagnostic test",
    ("K_tests_labs", "H7006-021-0"): "readers found no diagnostic test price",
    ("M_part_b_drugs", "H9003-001-0"): "readers missed the 20% for Part B drugs",
    ("M_part_b_drugs", "H9003-006-0"): "readers missed the 20% for Part B drugs",
    ("M_part_b_drugs", "H9003-009-0"): "readers missed the 20% for Part B drugs",
    ("O_medical_deductible", "H1036-317-0"): "readers missed that the $283 is Original Medicare's Part B deductible",
}


def layer_rows(data):
    """Writes one row per line and cited document quote. A blank line with no cited fact writes no row, so the line keeps
    its other layers' value.
    Rows for a cell that the generated sheet gives one line name no line."""
    url = {d["sha256"]: d["url"] for d in layers.rows(data / "generated" / "documents_checked.csv") if d["sha256"]}
    generated = {r["plan_id"]: r for r in layers.generated(data)["main"]}
    out = {}
    for column in COLUMNS:
        for plan_id, got in lines(data, column).items():
            if (column, plan_id) in HELD:
                continue
            one_line = " | " not in generated[plan_id][column]
            if one_line and any(value for value, _ in got[1:]):
                raise ValueError(f"{plan_id} {column} has one line, not {[value for value, _ in got]}")
            for n, (value, cited) in enumerate(got, 1):
                row = dict(sheet="main", plan_id=plan_id, column=column, line="" if one_line else str(n), value=value)
                cites = [(url[f["doc_sha"]], f["page"], q) for f in cited if f["source"] in facts.DOCUMENTS
                         for q in json.loads(f["quotes"])]
                for cite in cites:
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
