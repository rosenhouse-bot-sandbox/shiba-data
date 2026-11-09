"""Writes generated/presented.csv, a layer that presents sheet columns from facts and cites them.

Usage: python3 -I pipeline/present.py <year>
"""
import collections, contextvars, csv, itertools, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import facts, layers, steps, years

RANK = {s: i for i, s in enumerate(facts.SOURCES_BEST_FIRST)}
OFFICES = ("office.pcp", "office.specialist", "freestanding")
ADVANCED = ("imaging.diagnostic.advanced.ct", "imaging.diagnostic.advanced.mri", "imaging.diagnostic.advanced.pet")
# These carriers' imaging keeps no $0 low end for a $0 diagnostic mammogram. fields.py omits Devoted (#127).
NO_MAMMOGRAM_ZERO = ("Kaiser", "Humana", "Devoted")


# While explain() runs a rule, this maps the identity of each fact a filter examined to why filters set it aside.
_reasons = contextvars.ContextVar("reasons", default=None)


def note(f, reason=None):
    """Records that a filter examined f, and why it set f aside, if it did."""
    reasons = _reasons.get()
    if reasons is not None:
        reasons.setdefault(facts.identity(f), []).extend([reason] if reason else [])


def keep(found, test, reason):
    """The facts test accepts. Notes reason(f) for the others."""
    kept, tracing = [], _reasons.get() is not None
    for f in found:
        ok = test(f)
        if tracing:
            note(f, None if ok else reason(f))
        if ok:
            kept.append(f)
    return kept


def prefer(found, test, reason):
    """The facts test accepts, or all the facts if it accepts none."""
    return keep(found, test if any(map(test, found)) else lambda f: True, reason)


def unless(reason):
    """Names, for a reader, why the decorated filter rejects a fact when no FILTERED field explains it."""
    def named(ok):
        ok.unless = reason
        return ok
    return named


# The fields a filter may reject a fact for, and a value that the usual filters accept.
FILTERED = (("network", "in"), ("covered_by", "medicare"), ("covered_by", "supplemental"), ("cost_kind", "copay"),
            ("condition", ""), ("provider_tier", ""), ("package", ""))


def why_not(f, ok):
    """Names the fewest fields whose values made ok reject f, or else ok's own reason."""
    for n in range(1, len(FILTERED) + 1):
        for changes in itertools.combinations(FILTERED, n):
            if (len({field for field, _ in changes}) == n and all(f[field] != value for field, value in changes)
                    and ok(dict(f, **dict(changes)))):
                return " and ".join(f"{field} is {f[field]!r}" for field, _ in changes)
    return ok.unless


def screen(found, ok):
    """The facts ok accepts. Notes why it rejects the others."""
    return keep(found, ok, lambda f: why_not(f, ok))


def top(found):
    """The facts from the best source among them."""
    best_rank = min((RANK[g["source"]] for g in found), default=None)
    for f in found:
        if RANK[f["source"]] != best_rank:
            note(f, f"{f['source']} ranks below {facts.SOURCES_BEST_FIRST[best_rank]}")
    return [f for f in found if RANK[f["source"]] == best_rank]


def usable(f):
    return (f["network"] in ("in", "any") and f["covered_by"] == "medicare" and f["cost_kind"] in ("copay", "coinsurance")
            and not (f["condition"] or f["provider_tier"] or f["package"]))


def best(found, leaf, setting, ok=usable, settings_noted=True):
    """The ok facts for leaf and setting from the best source, and within it the most specific."""
    fits = []
    for f in screen([f for f in found if facts.covers(f["benefit"], leaf)], ok):
        if facts.covers(f["setting"], setting):
            fits.append(f)
        elif settings_noted:
            note(f, f"setting {f['setting']!r} is not {setting!r}")
    if not fits:
        return []
    fits = top(fits)

    def depth(f):
        return f["benefit"].count("."), f["setting"] != "any", f["setting"].count(".")

    deepest = max(map(depth, fits))
    for f in fits:
        if depth(f) != deepest:
            note(f, "a more specific fact won")
    return [f for f in fits if depth(f) == deepest]


def winners(found, leaves, settings, ok=usable):
    """The best ok facts at the settings, or at an outpatient hospital if none of the settings has one."""
    got = [f for s in settings for leaf in leaves for f in best(found, leaf, s, ok, settings_noted=False)]
    if not got:
        settings = ("outpatient_hospital",)
        got = [f for leaf in leaves for f in best(found, leaf, settings[0], ok, settings_noted=False)]
    for f in found:
        if (any(facts.covers(f["benefit"], leaf) for leaf in leaves) and ok(f)
                and not any(facts.covers(f["setting"], s) for s in settings)):
            note(f, f"setting {f['setting']!r} is not {' or '.join(map(repr, settings))}")
    return got


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
    mammograms = keep(winners(found, ["imaging.diagnostic.mammogram"], OFFICES),
                      lambda f: f["cost_kind"] == "copay" and f["amount"] == "$0", lambda f: "only a $0 mammogram copay counts")
    if not line2:
        mammograms = keep(mammograms, lambda f: False, lambda f: "a $0 mammogram counts only with a CT, MRI or PET price")
    mammograms = keep(mammograms, lambda f: not any(name in organization for name in NO_MAMMOGRAM_ZERO),
                      lambda f: f"{organization} keeps no $0 low end for a mammogram")
    if mammograms:
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
    return (f["setting"] == "outside_us" and f["cost_kind"] in PRICED + ("covered", "not_covered", "unclear")
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
    here = unique([f for leaf in TRIPS for f in best([f for f in found if f["setting"] != "outside_us"], leaf, "any", trip_here)])
    trips = [f for f in found if f["setting"] == "outside_us"]
    abroad = unique([f for leaf in TRIPS for f in best(trips, leaf, "outside_us", trip_abroad)])
    priced = [f for f in abroad if f["cost_kind"] in PRICED]
    covered = [f for f in abroad if f["cost_kind"] == "covered"]
    excluded = [f for f in abroad if f["cost_kind"] == "not_covered"]
    unclear = [f for f in abroad if f["cost_kind"] == "unclear"]
    if unclear:
        line2 = ("EOC unclear", unclear)
        for f in priced + covered + excluded:
            note(f, "line 2 says the EOC is unclear")
    elif priced:
        line2 = (show_or(priced), priced)
        for f in covered + excluded:
            note(f, "line 2 shows a price abroad")
    elif covered:
        plain = [f for f in here if not f["condition"]]
        line2 = (show_or(plain), covered + plain)
        for f in excluded:
            note(f, "line 2 shows that trips abroad are covered")
    elif excluded:
        line2 = ("not covered", excluded)
    else:
        line2 = ("", [])
    return [(show_or(here), here), line2]


ZERO_SURGERIES = ("surgery.colonoscopy", "surgery.skin_biopsy")


def outpatient_surgery(organization, found):
    """Line 1 is outpatient hospital surgery and line 2 is surgical center surgery, each as (value, cited facts).
    A $0 diagnostic colonoscopy or skin biopsy priced in that setting starts its line at $0 (fields.py).
    So does a $0 low end that any source gives surgery in that setting, even one for other services (the expert's rule in #99)."""
    def line(setting):
        cost = best(found, "surgery", setting)
        exact = keep([f for f in found if f["benefit"] in ZERO_SURGERIES], lambda f: f["setting"] == setting,
                     lambda f: f"the {setting!r} line counts only a price at {setting!r} itself")
        if not cost:
            keep(exact, lambda f: False, lambda f: f"the {setting!r} line has no surgery price")
            return "", []
        zeros = keep([f for leaf in ZERO_SURGERIES for f in best([g for g in exact if g["benefit"] == leaf], leaf, setting)],
                     lambda f: f["amount"] == "$0", lambda f: "only a $0 colonoscopy or skin biopsy counts")
        low_ends = [f for f in found if usable(f) and f["benefit"] == "surgery" and f["setting"] == setting
                    and f["amount"].startswith("$0-")]
        return show(cost + zeros + [dict(f, amount="$0") for f in low_ends]), unique(cost + zeros + low_ends)
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
        keep([f for f in found if f["benefit"] == "tests.diagnostic.sleep_study"],
             lambda f: facts.covers(f["setting"], "outpatient_hospital"), lambda f: "only a sleep study at an outpatient hospital counts")
        tests += best(found, "tests.diagnostic.sleep_study", "outpatient_hospital", settings_noted=False)
    else:
        keep([f for f in found if f["benefit"] == "tests.diagnostic.sleep_study"], lambda f: False,
             lambda f: "a sleep study counts only for " + ", ".join(HOSPITAL_SLEEP_STUDY))
    if tests and any(name in organization for name in ZERO_TESTS):
        zeros = winners(found, ["imaging.diagnostic.mammogram"], OFFICES) + [
            f for s in ("outpatient_hospital", "asc") for f in best(found, "surgery.colonoscopy", s)]
        tests += [f for f in zeros if f["amount"] == "$0"]
    tests, labs = unique(tests), winners(found, ["tests.lab"], OFFICES, any_test)
    return [(f"{show(tests)}/{show(labs)}" if tests or labs else "", tests + labs)]


def visit_line(found, setting, network):
    def ok(f):
        return priced(f, network)

    got = best([f for f in found if f["network"] in (network, "any")], "visits", setting, ok)
    got = prefer(got, lambda f: f["network"] == network, lambda f: f"a price for network {network!r} won")
    got = prefer(got, lambda f: not f["condition"], lambda f: "a price without a condition won")
    return show(got), got


def visits(setting):
    """Line 1 is in network and line 2 out of network, if the plan prices any visit out of network."""
    def rule(organization, found):
        out = any(f["benefit"] == "visits" and f["network"] == "out" and priced(f, "out") for f in found)
        if not out:
            keep([f for f in found if facts.covers(f["benefit"], "visits") and f["network"] == "out"], lambda f: False,
                 lambda f: "the plan has no out-of-network visit price")
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
        for f in got:
            if f not in paid:
                note(f, "line 1 shows the days that cost more than $0" if days(f) else "a cost per day won")
        first = min(days(f)[0] for f in paid)
        last = [days(f)[1] for f in paid]
        return [(show(paid), paid), (span(str(first), str(max(last))) if all(last) else f"{first}+", paid)]
    stays = keep(got, lambda f: f["unit"] == "per stay", lambda f: "a cost per stay won") if any(
        f["unit"] == "per stay" for f in got) else []
    if stays:
        return [(f"{show(stays)} per admission", stays), ("", [])]
    return [(show(got), got), ("", [])]


def unique(found):
    return list({id(f): f for f in found}.values())


def giveback(organization, found):
    """Shows the monthly Part B premium reduction."""
    @unless("it is not a Part B premium reduction")
    def ok(f):
        return f["cost_kind"] in ("part_b_reduction", "covered") and not (f["package"] or f["provider_tier"])

    got = prefer(best(found, "giveback", "any", ok), lambda f: not f["condition"],
                 lambda f: "a reduction without a condition won")
    paid = [f for f in got if f["cost_kind"] == "part_b_reduction"]
    for f in got:
        if paid and f not in paid:
            note(f, "a reduction amount won")
    return [(show(paid), paid)] if paid else [("●", got)] if got else [("", [])]


@unless("it is not a coinsurance or $0 copay for a Part B drug")
def drug_price(f):
    return (priced(f) and not f["provider_tier"] and facts.covers("part_b_drugs", f["benefit"])
            and (f["cost_kind"] == "coinsurance" or f["amount"] == "$0"))


def part_b_drugs(organization, found):
    """Shows the range of Part B drug coinsurance, from each kind of drug's best source.
    A $0 copay, such as for vaccines, counts as 0%."""
    ok = screen([f for f in found if facts.covers("part_b_drugs", f["benefit"])], drug_price)
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
        @unless(f"it is not a Medicare deductible in network {networks[0]!r}")
        def ok(f):
            return deductible_ok(f) and f["network"] in networks
        got = best(found, "medical_deductible.some", "any", ok)
        if got:
            break
    else:
        keep([f for f in found if f["benefit"] == "medical_deductible.part_b"], lambda f: False,
             lambda f: "the column shows the Part B deductible only beside a plan deductible")
        return [("", [])]
    some = [f for f in found if f["benefit"] == "medical_deductible.some" and ok(f)]
    part_b = keep([f for f in found if f["benefit"] == "medical_deductible.part_b"], lambda f: f["cost_kind"] == "covered",
                  lambda f: "only a covered Part B deductible counts")
    if show(got) == "$0":
        for f in some + part_b:
            if f not in got:
                note(f, "a $0 deductible won")
        return [("$0", got)]
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
        mine = keep([f for f in found if any(facts.covers(f["benefit"], leaf) for leaf in leaves)],
                    lambda f: f["network"] in ("in", "any"), lambda f: f"network is {f['network']!r}")
        yes = screen(mine, offers)
        return [("●", top(yes))] if yes else [("", top(mine) if mine else [])]
    return rule


def packages(organization, found):
    """Shows ● when a member may buy an optional package. A document that says there is none cites a blank."""
    mine = keep(keep(found, lambda f: f["covered_by"] == "supplemental", lambda f: f"covered_by is {f['covered_by']!r}"),
                lambda f: f["network"] in ("in", "any"), lambda f: f"network is {f['network']!r}")
    sold = [f for f in mine if f["cost_kind"] == "premium" and f["package"]]
    none = keep([f for f in mine if facts.covers(f["benefit"], "packages") and f not in sold], lambda f: not sold,
                lambda f: "a package for sale won")
    return [("●", top(sold))] if sold else [("", top(none) if none else [])]


def plan_premium(organization, found):
    """Shows the monthly plan premium. Two premiums from the best source show nothing."""
    @unless("it is not a monthly plan premium")
    def ok(f):
        return f["cost_kind"] == "premium" and not (f["condition"] or f["package"] or f["provider_tier"])

    got = best(found, "plan_premium", "any", ok)
    one = len({facts.number(a) for a in amounts(got)}) == 1
    got = keep(got, lambda f: one, lambda f: "the best source gives more than one premium")
    return [(show(got), got)]


YEARS = {"2": "two", "two": "two", "3": "three", "three": "three"}
SEVERAL_YEARS = re.compile(r"\b(?:every|per|each|during an?)\s+(2|two|3|three)[ -](?:calendar[ -])?years?\b", re.I)
ONE_YEAR = re.compile(r"\b(?:every|per|each)\s+(?:calendar\s+)?year\b", re.I)


def period(f):
    """How often the fact's limit renews, such as "year" or "two years", or "" if it does not say."""
    several = SEVERAL_YEARS.search(f["limit"])
    return f"{YEARS[several[1].lower()]} years" if several else "year" if ONE_YEAR.search(f["limit"]) else ""


def renewal(found, leaf):
    """The best source's routine facts for leaf that say how often it renews."""
    return top([f for f in found if f["benefit"] == leaf and routine(f) and not f["provider_tier"] and period(f)])


def per(found):
    """"/year" or the like when the facts agree on how often they renew."""
    periods = {period(f) for f in found}
    return f"/{periods.pop()}" if len(periods) == 1 else ""


def routine(f):
    return (f["network"] in ("in", "any") and f["covered_by"] == "supplemental"
            and not (f["condition"] or f["package"] or f["pool"]))


@unless("it is not a routine exam copay")
def exam_ok(f):
    return routine(f) and f["cost_kind"] == "copay" and not f["provider_tier"]


# These carriers give one allowance for frames or contacts.
FRAMES_OR_CONTACTS = ("Regence",)


def vision(organization, found):
    """Shows the routine eye exam copay and the eyewear allowance, with a higher allowance at a named tier of providers.
    Each part says how often it renews when its best source says so."""
    @unless("it is not a routine eyewear allowance")
    def eyewear_ok(f):
        return routine(f) and f["cost_kind"] in ("allowance", "max")

    exams = best(found, "vision.exam", "any", exam_ok)
    eyewear = best(found, "vision.eyewear", "any", eyewear_ok)
    standard = [f for f in eyewear if not f["provider_tier"]]
    tiers = [f for f in eyewear if f["provider_tier"]]
    parts, cited = [], []
    if exams:
        renews = renewal(found, "vision.exam")
        parts.append(f"exam {show(exams)}{per(renews)}")
        cited += exams + renews
    if standard:
        regence = any(name in organization for name in FRAMES_OR_CONTACTS)
        renews = renewal(found, "vision.eyewear")
        part = f"{'frames or contacts' if regence else 'eyewear'} {show(standard)}{per(renews)}"
        cited += standard + renews
        if tiers:
            names = {re.sub(r"\W*providers?\W*$", "", f["provider_tier"], flags=re.I).strip("* ") for f in tiers}
            part += f" ({show(tiers)} at {' or '.join(sorted(names))} providers)"
            cited += tiers
        parts.append(part)
        lenses = [f for f in found if f["benefit"] == "vision.eyewear" and routine(f) and f["cost_kind"] == "copay"
                  and f["amount"] == "$0" and not f["provider_tier"]] if regence else []
        if lenses:
            parts.append("lenses $0")
            cited += top(lenses)
    else:
        keep(tiers, lambda f: False, lambda f: "a tier's allowance shows only beside the standard one")
    return [("; ".join(parts), unique(cited))]


PAIR = re.compile(r"per ear|\b(?:2|two) hearing aids?\b", re.I)


def hearing(organization, found):
    """Shows the routine hearing exam copay, then a hearing aid allowance or else copays, and how many aids.
    The count comes from a visit limit, or is 2 when the best source prices or limits aids per ear."""
    @unless("it is not a routine hearing aid allowance")
    def allowance_ok(f):
        return routine(f) and f["cost_kind"] in ("allowance", "max") and not f["provider_tier"]

    @unless("it is not a routine hearing aid copay")
    def copay_ok(f):
        return routine(f) and f["cost_kind"] == "copay" and not f["provider_tier"]

    exams = best(found, "hearing.exam", "any", exam_ok)
    allowance = best(found, "hearing.aids", "any", allowance_ok)
    copays = keep(best(found, "hearing.aids", "any", copay_ok), lambda f: not allowance, lambda f: "an allowance won")
    priced = allowance or copays
    renews = renewal(found, "hearing.aids") if priced else []
    parts = [f"exam {show(exams)}"] if exams else []
    if allowance:
        ear = " per ear" if any(f["unit"] == "per ear" for f in allowance) else ""
        parts.append(f"aids allowance {show(allowance)}{ear}{per(renews)}")
    elif copays:
        parts.append(f"aids {show(copays)}")
    limits = top([f for f in found if f["benefit"] == "hearing.aids" and routine(f) and not f["provider_tier"]
                  and f["cost_kind"] == "visit_limit"]) if priced else []
    pairs = [f for f in priced + renews if PAIR.search(f["unit"] + " " + f["limit"])]
    counted = limits or pairs
    if counted:
        parts.append(f"{min(int(f['amount']) for f in limits) if limits else 2} aids{per(renews)}")
    return [("; ".join(parts), unique(exams + priced + renews + counted))]


# Added facts fill in what readers miss, and each note says why. Only they use cost kind "unclear".
ADDED = "added_facts.csv"


def plan_facts(data, document=None):
    """Each plan's facts. document replaces machine/document_facts.csv if given."""
    if document is None:
        document = facts.read(data / "machine/document_facts.csv")
    by_plan = collections.defaultdict(list)
    for f in document + facts.read(data / "generated/pbp_facts.csv") + facts.read(data / ADDED):
        by_plan[f["plan_id"]].append(f)
    return by_plan


# A rule returns the lines of its column.
COLUMNS = {"L_xray_imaging": xray_imaging, "AB_ambulance": ambulance, "I_outpatient_surgery": outpatient_surgery,
           "F_primary_care": visits("office.pcp"), "G_specialist": visits("office.specialist"), "H_inpatient": inpatient,
           "J_outpatient_rehab": outpatient_rehab, "K_tests_labs": tests_labs, "Z_part_b_reduction": giveback,
           "M_part_b_drugs": part_b_drugs, "O_medical_deductible": medical_deductible,
           "S_acupuncture": dot("extras.acupuncture"), "T_chiropractic": dot("extras.chiropractic"),
           "V_massage": dot("extras.massage"), "X_transportation": dot("extras.transportation"),
           "R_dental": dot("dental.preventive", "dental.comprehensive"), "U_naturopath": dot("extras.naturopathy"),
           "P_vision": dot("vision.exam", "vision.eyewear"), "Q_hearing": dot("hearing.exam", "hearing.aids"),
           "W_fitness": dot("fitness"), "Y_otc": dot("otc"), "AA_opt_packages": packages}


# The benefits each rule reads. A fact for a broader or narrower benefit is one the rule considers.
LEAVES = {"L_xray_imaging": ("imaging",), "AB_ambulance": ("ambulance",), "I_outpatient_surgery": ("surgery",),
          "F_primary_care": ("visits",), "G_specialist": ("visits",), "H_inpatient": ("inpatient",),
          "J_outpatient_rehab": ("rehab",), "K_tests_labs": ("tests",), "Z_part_b_reduction": ("giveback",),
          "M_part_b_drugs": ("part_b_drugs",), "O_medical_deductible": ("medical_deductible",),
          "S_acupuncture": ("extras.acupuncture",), "T_chiropractic": ("extras.chiropractic",),
          "V_massage": ("extras.massage",), "X_transportation": ("extras.transportation",),
          "R_dental": ("dental",), "U_naturopath": ("extras.naturopathy",), "P_vision": ("vision",),
          "Q_hearing": ("hearing",), "W_fitness": ("fitness",), "Y_otc": ("otc",), "AA_opt_packages": ("packages",)}


DVHA = {"C_premium": plan_premium, "G_vision": vision, "H_hearing": hearing}
DVHA_LEAVES = {"C_premium": ("plan_premium",), "G_vision": ("vision",), "H_hearing": ("hearing",)}
SHEETS = {"main": (COLUMNS, LEAVES), "dvha": (DVHA, DVHA_LEAVES)}


def cell(sheet, column, plan_id):
    """A cell's key in a version's held cells."""
    return (column if sheet == "main" else f"{sheet}.{column}", plan_id)


def related(f, leaves):
    return any(facts.covers(f["benefit"], leaf) or facts.covers(leaf, f["benefit"]) for leaf in leaves)


# A reason explain() gives only if a filter set a fact aside without noting why. A test keeps it from happening.
UNNOTED = "no filter recorded a reason"


def explain(organization, found, column, sheet="main"):
    """(lines, set_aside): the rule's lines, and {identity: reasons} for each fact for a benefit in LEAVES that the
    rule did not use."""
    token = _reasons.set({})
    try:
        got = SHEETS[sheet][0][column](organization, found)
        reasons = _reasons.get()
    finally:
        _reasons.reset(token)
    used = {facts.identity(f) for _, cited in got for f in cited}

    def why(f):
        if facts.identity(f) not in reasons:
            return [f"the column does not use {f['benefit']}"]
        return sorted(set(reasons[facts.identity(f)])) or [UNNOTED]
    return got, {facts.identity(f): why(f) for f in found
                 if related(f, SHEETS[sheet][1][column]) and facts.identity(f) not in used}


def presents(cited):
    """Whether a line's cited facts give it a presented row. A line without one keeps its other layers' value."""
    return any(f["source"] in facts.DOCUMENTS for f in cited)


def lines(data, column, document=None, sheet="main"):
    """{plan_id: [(value, cited facts), ...]} for each plan on the sheet. See plan_facts for document."""
    organization = {r["plan_id"]: r["organization"] for r in layers.rows(data / "generated" / "plans.csv")}
    found = plan_facts(data, document)
    return {r["plan_id"]: SHEETS[sheet][0][column](organization[r["plan_id"]], found[r["plan_id"]])
            for r in layers.generated(data)[sheet]}


# Each version names the cells that keep their other layers' value, because the facts miss part of them.
HELD_1 = {
    ("K_tests_labs", "H2923-009-0"): "the facts give a 50% lab price but no 0%",
    ("K_tests_labs", "H5439-010-0"): "the rule leaves out the SB's $0 tests and the $50 genetic test",
    ("K_tests_labs", "H5439-011-0"): "the rule leaves out the $50 genetic test",
    ("K_tests_labs", "H5439-015-0"): "the rule leaves out the SB's $0 tests and the $50 genetic test",
    ("K_tests_labs", "H5439-019-0"): "the rule leaves out the $50 genetic test",
    ("K_tests_labs", "H6815-038-0"): "the facts take a $200 price for tests that is not a diagnostic test",
    ("O_medical_deductible", "H1036-317-0"): "the facts miss that the $283 is Original Medicare's Part B deductible",
}
CANDIDATE = "SHIBA_CANDIDATE"
VERSIONS = {1: HELD_1, 2: {cell: why for cell, why in HELD_1.items() if cell != ("K_tests_labs", "H2923-009-0")}}
VERSIONS[3] = VERSIONS[2]
NO_EXAM = "the facts give no in-network routine hearing exam price"
NO_RENEWAL = "the facts do not say how often the hearing aids renew"
VERSIONS[4] = VERSIONS[3] | {("dvha.H_hearing", p): NO_EXAM for p in (
    "H7006-018-0", "H6815-038-0", "H5439-019-0", "H5439-011-0", "H1372-003-0", "H7006-021-0", "H5439-010-0")} | {
    ("dvha.H_hearing", p): f"{NO_EXAM}, and {NO_RENEWAL}" for p in (
        "H7199-002-0", "H2923-001-0", "H2923-028-3", "H2923-025-0", "H2923-005-0", "H2923-009-0")} | {
    ("dvha.H_hearing", "H2923-019-0"): NO_RENEWAL}
# The version that first presents each DVHA column. Earlier versions hold its cells.
DVHA_SINCE = {"C_premium": 3, "G_vision": 4, "H_hearing": 4}


def held(data, version=None):
    """The cells that a version holds, by default the run's candidate or else the pinned one."""
    candidate = ",".join(c for c in os.environ.get(CANDIDATE, "").split(",") if c.strip().startswith("present@"))
    version = version or steps.versions(data, {"present": VERSIONS}, candidate)["present"]
    return VERSIONS[version] | {cell("dvha", column, r["plan_id"]): f"present {version} does not present this column"
                                for column, since in DVHA_SINCE.items() if version < since
                                for r in layers.generated(data)["dvha"]}


def layer_rows(data, version=None):
    """Writes one row per line and cited document quote. A blank line with no cited fact writes no row, so the line keeps
    its other layers' value.
    Rows for a cell that the generated sheet gives one line name no line."""
    url = {d["sha256"]: d["url"] for d in layers.rows(data / "generated" / "documents_checked.csv") if d["sha256"]}
    out, held_cells = {}, held(data, version)
    for sheet, (rules, _) in SHEETS.items():
        generated = {r["plan_id"]: r for r in layers.generated(data)[sheet]}
        for column in rules:
            for plan_id, got in lines(data, column, sheet=sheet).items():
                if cell(sheet, column, plan_id) in held_cells:
                    continue
                one_line = " | " not in generated[plan_id][column]
                if one_line and any(value for value, _ in got[1:]):
                    raise ValueError(f"{plan_id} {column} has one line, not {[value for value, _ in got]}")
                for n, (value, cited) in enumerate(got, 1):
                    row = dict(sheet=sheet, plan_id=plan_id, column=column, line="" if one_line else str(n), value=value)
                    cites = [(url[f["doc_sha"]], f["page"], q) for f in cited if presents([f])
                             for q in json.loads(f["quotes"])]
                    for cite in cites:
                        full = dict(row, **dict(zip(("url", "pdf_page", "quote"), cite)))
                        out[tuple(full.values())] = full
    return sorted(out.values(), key=lambda r: tuple(r.values()))


def write(data, version=None):
    with open(data / layers.PRESENTED, "w", newline="") as f:
        out = csv.DictWriter(f, layers.COLUMNS, lineterminator="\n")
        out.writeheader()
        out.writerows(layer_rows(data, version))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    write(years.data_dir(int(sys.argv[1])))
