"""Writes generated/presented.csv, a layer that presents sheet columns from facts and cites them.

Usage: python3 -I pipeline/present.py <year>
"""
import collections, contextvars, csv, itertools, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import facts, fields, layers, steps, years

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
    emergency = [f for f in found if f["benefit"] == "emergency"]
    if not abroad:
        return [(show_or(here), here), emergency_abroad(emergency)]
    for f in emergency:
        note(f, "a fact names trips abroad")
    return [(show_or(here), here), line2]


PLAIN_CARE = "line 2 uses only the EOC's plain emergency care abroad"


def emergency_abroad(emergency):
    """Line 2 from the EOC's emergency care abroad: "not covered" if it excludes that care, or "EOC unclear" if it
    covers it, since no fact names trips abroad."""
    care = keep(emergency, lambda f: f["setting"] == "outside_us" and f["source"] == "EOC"
                and not (f["provider_tier"] or f["package"] or f["condition"]), lambda f: PLAIN_CARE)
    covered = [f for f in care if f["cost_kind"] != "not_covered"]
    if covered:
        for f in care:
            note(f, None if f in covered else "line 2 says the EOC is unclear")
        return "EOC unclear", covered
    return ("not covered", care) if care else ("", [])


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
    A $0 in-network deductible shows as $0, whatever the out-of-network one is. When a fact says the deductible is
    Part B's, a covered deductible with no amount counts."""
    part_b_named = any(f["benefit"] == "medical_deductible.part_b" and f["cost_kind"] == "covered" for f in found)

    def amountless(f):
        return (part_b_named and f["cost_kind"] == "covered" and f["benefit"] != "medical_deductible.part_b"
                and deductible_ok(dict(f, cost_kind="deductible")))

    for networks in (("in", "any"), ("out",)):
        @unless(f"it is not a Medicare deductible in network {networks[0]!r}")
        def ok(f):
            return (deductible_ok(f) or amountless(f)) and f["network"] in networks
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


def bare(f):
    return not (f["package"] or f["provider_tier"])


def extra_help_premium(organization, found):
    """Shows the monthly plan premium with full Extra Help, or n/a for a plan without Part D."""
    @unless("it is not the monthly plan premium with full Extra Help")
    def ok(f):
        return f["cost_kind"] == "premium" and f["condition"] == "full Extra Help" and bare(f)

    @unless("it does not say that the plan has no Part D")
    def no_part_d(f):
        return f["cost_kind"] == "not_covered" and bare(f)

    got = best(found, "plan_premium", "any", ok)
    if got:
        return [(show(got), got)]
    none = best(found, "part_d_deductible", "any", no_part_d)
    return [("n/a" if none else "", none)]


def moop(organization, found):
    """Shows the in-network maximum out-of-pocket, then the combined in- and out-of-network maximum if there is one."""
    def ok(network):
        @unless("it is not a yearly maximum out-of-pocket")
        def test(f):
            return f["cost_kind"] == "out_of_pocket_max" and f["network"] == network and not f["condition"] and bare(f)
        return test

    got = [(show(cited), cited) for cited in (best(found, "moop", "any", ok(n)) for n in ("in", "any"))]
    return got if got[1][1] else got[:1]


def drug_deductible(organization, found):
    """Shows the yearly Part D deductible and the tiers it skips, or n/a for a plan without Part D."""
    @unless("it is not a yearly Part D deductible for every member")
    def ok(f):
        return f["cost_kind"] in ("deductible", "not_covered") and bare(f) and "extra help" not in f["condition"].lower()

    got = best(found, "part_d_deductible", "any", ok)
    if any(f["cost_kind"] == "not_covered" for f in got):
        return [("n/a", got)]
    skips = {f["condition"] for f in got}
    return [(f"{show(got)} {skips.pop()}".strip() if len(skips) == 1 else show(got), got)]


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


@unless("it is not a monthly package premium")
def package_premium(f):
    return f["cost_kind"] == "premium" and f["unit"] in ("per month", "")


@unless("it is not a yearly maximum")
def yearly_max(f):
    return f["cost_kind"] == "max" and period(f) == "year" and not f["pool"]


def optional_packages(organization, found):
    """Shows each optional package's monthly premium and its yearly dental maximum. A package that also covers other
    benefits says "dental max". A document that says the plan sells none cites a blank."""
    mine = keep([f for f in found if f["package"] or facts.covers("packages", f["benefit"])],
                lambda f: f["covered_by"] == "supplemental" and f["network"] in ("in", "any") and not f["condition"],
                lambda f: "it is not a supplemental in-network benefit for every member")
    named = keep(mine, lambda f: f["package"] or f["cost_kind"] == "not_covered", lambda f: "it names no package")
    priced = {f["package"] for f in best(named, "packages", "any", package_premium)}
    parts, cited = [], []
    for name in sorted(priced):
        package = [f for f in named if f["package"] == name]
        premium = best(package, "packages", "any", package_premium)
        dental_max = best(package, "dental", "any", yearly_max)
        part = f"{name} {show(premium)}/mo"
        if dental_max:
            others = any(not facts.covers("dental", f["benefit"]) and not facts.covers("packages", f["benefit"])
                         for f in package)
            part += f", {'dental max' if others else 'max'} {show(dental_max)}"
        parts.append(part)
        cited += premium + dental_max
    keep([f for f in named if f["package"] and f["package"] not in priced], lambda f: False,
         lambda f: "its package has no monthly premium")
    none = keep([f for f in named if f["cost_kind"] == "not_covered"], lambda f: not parts,
                lambda f: "a package for sale won")
    return [("; ".join(parts), unique(cited))] if parts else [("", top(none) if none else [])]


MONTHS = re.compile(r"\b(?:every|per|each)\s+(month|quarter|three months|six months)\b", re.I)


def every(f):
    """How often an allowance or limit renews, such as "month" or "two years", or "" if the fact does not say."""
    months = MONTHS.search(f["limit"] + " " + f["unit"])
    if period(f) or not months:
        return period(f)
    return "three months" if months[1].lower() == "quarter" else months[1].lower()


def renews(found):
    """How often all the facts renew, or "" if they do not agree or do not say."""
    periods = {every(f) for f in found}
    return periods.pop() if len(periods) == 1 else ""


def extra(f):
    """Says if the fact is an in-network supplemental benefit with no package or provider tier."""
    return f["network"] in ("in", "any") and f["covered_by"] == "supplemental" and not (f["package"] or f["provider_tier"])


def exactly(found, leaves, test, reason):
    """The facts whose benefit is one of leaves, not a broader or narrower one, that test accepts. Notes reason for the
    others."""
    return keep([f for f in found if f["benefit"] in leaves], test, lambda f: reason)


@unless("it is not a supplemental in-network benefit for every member")
def everyone(f):
    return extra(f) and not f["condition"]


def limit_text(limits):
    """" 12 visits/year" from visit limits that agree on how often they renew, or ""."""
    return f" {min(int(f['amount']) for f in limits)} visits/{renews(limits)}" if limits and renews(limits) else ""


# Each service's short name, its name beside a dental maximum, and its benefit.
ALT_CARE = (("Acup", "acupuncture", "extras.acupuncture"), ("Chiro", "chiropractic", "extras.chiropractic"),
            ("Massage", "massage", "extras.massage"), ("Naturopath", "naturopath", "extras.naturopathy"))
COMBINED = re.compile(r"combined", re.I)


def alt_care(found):
    """("Acup $0 24 visits/year", ...) parts and their facts. A service paid from a shared allowance names it.
    Copays whose visit limits are shared show the limit once."""
    pooled, own = {}, []
    for name, _, leaf in ALT_CARE:
        facts_ = exactly(found, (leaf,), lambda f: extra(f) and (not f["condition"] or COMBINED.search(f["condition"])),
                      "it is not a supplemental in-network benefit for every member")
        copays = top(keep(facts_, lambda f: f["cost_kind"] == "copay" and not f["pool"] and not f["condition"],
                          lambda f: "it is not the service's own copay"))
        if copays:
            limits = top([f for f in facts_ if f["cost_kind"] == "visit_limit" and not f["pool"]])
            own.append((name, copays, limits))
            continue
        shared = top(keep(facts_, lambda f: f["pool"] and f["cost_kind"] in ("allowance", "covered", "max"),
                          lambda f: "it is neither a copay nor a shared allowance"))
        if shared:
            pooled.setdefault(shared[0]["pool"], []).append((name, shared))
    parts, cited = [], []
    for pool, services in pooled.items():
        fs = [f for _, got in services for f in got]
        allowance = [f for f in fs if f["cost_kind"] == "allowance"]
        if re.search(r"dental", pool, re.I):
            source = "dental allowance"
        elif renews(allowance):
            kind = "Wellness Bucks" if re.search(r"wellness bucks", pool, re.I) else "allowance"
            source = f"{show(allowance)}/{renews(allowance)} {kind}"
        else:
            drop([f for got in pooled.values() for _, fs_ in got for f in fs_] + [f for _, c, lim in own for f in c + lim],
                 "the facts do not say how often the shared allowance renews")
            return None
        parts.append(f"{', '.join(name for name, _ in services)} from {source}")
        cited += fs
    shared_limit = (len(own) > 1 and all(limits for *_, limits in own)
                    and all(COMBINED.search(f["condition"]) for *_, limits in own for f in limits)
                    and len({(f["amount"], every(f)) for *_, limits in own for f in limits}) == 1)
    for name, copays, limits in own:
        parts.append(f"{name} {show(copays)}{'' if shared_limit else limit_text(limits)}")
        cited += copays + limits
    if shared_limit:
        parts.append(f"{limit_text(own[0][2]).strip()} combined")
    return parts, cited


# The benefits a shared card or allowance names, in sheet order.
SHARERS = ("dental", "vision", "hearing", "fitness")


def over_the_counter(found):
    """The OTC allowance, and the benefits that share it when the same allowance pays for them."""
    got = top(keep(exactly(found, ("otc",), everyone, "it is not a supplemental in-network benefit for every member"),
                   lambda f: f["cost_kind"] == "allowance", lambda f: "it is not an allowance"))
    if not got:
        return [], []
    period_ = renews(got)
    if not period_:
        drop(got, "the facts do not say how often the OTC allowance renews")
        return None
    pools = {f["pool"] for f in got if f["pool"]}
    amount = {facts.number(a) for a in amounts(got)}
    sharers = top([f for f in found if f["pool"] in pools and f["benefit"] != "otc" and everyone(f)
                   and f["cost_kind"] == "allowance" and {facts.number(a) for a in amounts([f])} == amount
                   and every(f) == period_])
    if not sharers:
        return [f"OTC {show(got)}/{period_}"], got
    names = [n for n in SHARERS if any(facts.covers(n, f["benefit"]) for f in sharers)]
    return [f"OTC from {show(got)}/{period_} card shared with {', '.join(names)}"], got + sharers


def urgent(f):
    return all(re.search(r"urgent", q, re.I) and not re.search(r"emergenc", q, re.I) for q in json.loads(f["quotes"]))


def worldwide(found):
    """The copay for emergency care outside the U.S. and the most the plan pays. Several copays that no quote tells
    apart leave the part unknown. A document that says the plan covers none cites a blank."""
    abroad = keep(exactly(found, ("emergency",), lambda f: f["setting"] == "outside_us", "it is not care outside the U.S."),
                  lambda f: not (f["condition"] or f["package"]), lambda f: "it has a condition or package")
    priced = keep(abroad, lambda f: f["cost_kind"] in PRICED and not urgent(f), lambda f: "it is not an emergency copay")
    copays = top(priced)
    tiebreak = top([f for f in priced if f not in copays])
    if (len({f["amount"] for f in copays}) > 1 and len({f["amount"] for f in tiebreak}) == 1
            and tiebreak[0]["amount"] in {f["amount"] for f in copays}):
        copays = keep(copays, lambda f: f["amount"] == tiebreak[0]["amount"],
                      lambda f: f"{tiebreak[0]['source']} gives another copay") + tiebreak
    if not copays:
        none = [f for f in abroad if f["cost_kind"] == "not_covered"]
        if none or not abroad:
            return [], top(none)
        drop(abroad, "the facts give no copay for emergency care outside the U.S.")
        return None
    if len({f["amount"] for f in copays}) > 1:
        drop(abroad, "the facts do not say which copay is the ER's")
        return None
    maxes = top([f for f in abroad if f["cost_kind"] == "max"])
    return [f"Worldwide ER {show(copays)}" + (f", {show(maxes)} max" if maxes else "")], copays + maxes


def alt_care_otc_travel(organization, found):
    """Shows routine acupuncture, chiropractic, massage and naturopathy, the OTC allowance, and worldwide emergency
    care. A part the facts do not fully give leaves the cell blank."""
    parts, cited = [], []
    for part in (alt_care, over_the_counter, worldwide):
        got = part(found)
        if got is None:
            drop(cited, f"the facts do not fully give the {part.__name__.replace('_', ' ')} part")
            return [("", [])]
        parts += got[0]
        cited += got[1]
    return [("; ".join(parts), unique(cited))]


def drop(found, reason):
    """Notes reason for each fact, which the rule does not cite."""
    keep(found, lambda f: False, lambda f: reason)


def foot_care(found):
    """Routine foot care's price and visit limit, for every member or else for members with diabetes."""
    routine_care = keep(exactly(found, ("foot_care",), lambda f: extra(f) and not f["pool"],
                             "it is not supplemental in-network foot care"),
                        lambda f: f["cost_kind"] in PRICED + ("visit_limit",), lambda f: "it is neither a price nor a limit")
    routine_care = keep(routine_care, lambda f: not f["condition"] or DIABETES.search(f["condition"]),
                        lambda f: "its condition is not diabetes")
    groups = [[f for f in routine_care if not f["condition"]], [f for f in routine_care if f["condition"]]]
    for diabetic, group in enumerate(groups):
        prices = top([f for f in group if f["cost_kind"] in PRICED])
        if prices:
            if not diabetic:
                drop(groups[1], "foot care for every member won")
            limits = top([f for f in group if f["cost_kind"] == "visit_limit"])
            visits = limit_text(limits).replace(" visits", "")
            if not visits:
                drop(limits, "the limits do not agree on how often they renew")
            return [f"Routine foot care {show(prices)}{visits}{' for members with diabetes' if diabetic else ''}"], (
                prices + (limits if visits else []))
        drop(group, "it gives no price")
    return [], []


DIABETES = re.compile(r"diabet", re.I)
CHRONIC = re.compile(r"chronic", re.I)
HEART = re.compile(r"heart", re.I)


def extra_benefits(organization, found):
    """Names fitness, meals and transportation for every member, then shows routine foot care, a fitness allowance,
    a card for members with chronic conditions, and the programs after a heart-failure hospital stay."""
    parts, cited = [], []
    for name, leaf in (("Fitness", "fitness"), ("Meals", "meals"), ("Transportation", "extras.transportation")):
        got = top(exactly(found, (leaf,), lambda f: extra(f) and offers(f),
                       "it is not a supplemental in-network benefit for every member"))
        if got:
            parts.append(name)
            cited += got
    got = foot_care(found)
    parts += got[0]
    cited += got[1]
    alt_care_pools = {f["pool"] for f in found if f["benefit"].startswith("extras.") and f["pool"]}
    bucks = top(exactly(found, ("fitness",), lambda f: everyone(f) and f["cost_kind"] == "allowance"
                        and re.search(r"wellness bucks", f["pool"], re.I) and f["pool"] not in alt_care_pools and every(f),
                        "it is not Wellness Bucks for fitness alone"))
    if bucks and renews(bucks):
        parts.append(f"Wellness Bucks {show(bucks)}/{renews(bucks)}")
        cited += bucks
    cards = top(exactly(found, ("other_supplemental",),
                     lambda f: extra(f) and CHRONIC.search(f["condition"]) and f["cost_kind"] == "allowance" and every(f),
                     "it is not an allowance for members with chronic conditions"))
    for pool in sorted({f["pool"] for f in cards}):
        card = [f for f in cards if f["pool"] == pool]
        parts.append(f"For members with certain chronic conditions: {pool} {show(card)}/{renews(card)}")
        cited += card
    heart = top(exactly(found, ("other_supplemental", "meals"),
                     lambda f: extra(f) and HEART.search(f["condition"]) and f["cost_kind"] in PRICED + ("covered",),
                     "it is not a benefit after a heart-failure hospital stay"))
    if heart:
        names = sorted({f["pool"] for f in heart if f["benefit"] == "other_supplemental" and f["pool"]})
        names += ["home-delivered meals"] if any(f["benefit"] == "meals" for f in heart) else []
        parts.append(f"After a heart-failure hospital stay: {', '.join(names)}")
        cited += heart
    return [("; ".join(parts), unique(cited))]


# Comprehensive services that some plans cover alone, by how their quotes name them.
NARROW = (("adjunctive services", re.compile(r"adjunctive general", re.I)),
          ("periodontal maintenance", re.compile(r"periodontal maintenance", re.I)),
          ("nitrous oxide", re.compile(r"nitrous oxide", re.I)))
BROAD = re.compile(r"filling|amalgam|resin|crown|denture|bridge|implant|root canal|extraction|oral surgery|restorative|"
                   r"endodontic|periodontic|root planing|comprehensive (?:dental )?services", re.I)


def narrow(prices):
    """The narrow services that prices name, or [] if a price names none of them or names another service."""
    quotes = [json.loads(f["quotes"]) for f in prices]
    named = [[name for name, words in NARROW if any(words.search(q) for q in qs)] for qs in quotes]
    if not all(named) or any(BROAD.search(q) for qs in quotes for q in qs):
        return []
    return [name for name, _ in NARROW if any(name in n for n in named)]


def dental_price(found, leaf):
    """The best source's prices, and how the cell shows them. It names the narrow services that all sources' prices
    name, without saying they are the only ones, since readers may miss some."""
    prices = exactly(found, (leaf,), lambda f: everyone(f) and f["cost_kind"] in PRICED,
                     "it is not a supplemental in-network price for every member")
    got = top(prices)
    shown = show(got)
    shown = "$0" if shown == "0%" else shown.replace("0%-", "$0-") if got else ""
    only = narrow(prices)
    return got, f"{shown} for {', '.join(only)}" if only else shown


def dental(organization, found):
    """Shows routine preventive and comprehensive dental prices and the maximum, naming the services that share it.
    A plan with only an allowance shows it. An allowance on a card shared with other benefits is not a maximum.
    Without routine dental, it cites a blank as the main sheet's dental column does."""
    prev, prev_shown = dental_price(found, "dental.preventive")
    comp, comp_shown = dental_price(found, "dental.comprehensive")
    others = {f["pool"] for f in found if f["pool"] and not facts.covers("dental", f["benefit"])
              and not f["benefit"].startswith("extras.")}
    eligible = exactly(found, ("dental", "dental.preventive", "dental.comprehensive"),
                       lambda f: everyone(f) and f["cost_kind"] in ("max", "allowance") and f["pool"] not in others,
                       "it is not a dental maximum for every member")
    caps = top(eligible)
    parts = ([f"PREV {prev_shown}"] if prev else []) + ([f"COMP {comp_shown}"] if comp else [])
    cited = prev + comp
    if caps:
        timed = caps if renews(caps) else top([f for f in eligible if every(f) and show([f]) == show(caps)])
        if not renews(timed):
            drop(cited + caps, "the facts do not say how often the dental maximum renews")
            return [("", [])]
        amount = f"{show(caps)}/{renews(timed)}"
        caps = unique(caps + timed)
        pools = {f["pool"] for f in caps if f["pool"]}
        sharing = [name for _, name, leaf in ALT_CARE if any(g["benefit"] == leaf and g["pool"] in pools for g in found)]
        if not parts:
            parts.append(f"PREV+COMP from {amount} allowance" + (f" shared with {', '.join(sharing)}" if sharing else ""))
        elif sharing:
            parts.append(f"max {amount} shared by PREV+COMP, {', '.join(sharing)}")
        elif all(f["benefit"] == "dental.comprehensive" for f in caps):
            parts.append(f"COMP max {amount}")
        else:
            parts.append(f"max {amount} PREV+COMP")
        cited += caps
    if not parts:
        blank = COLUMNS["R_dental"](organization, found)
        return blank if not blank[0][0] else [("", [])]
    return [("; ".join(parts), unique(cited))]


# Added facts fill in what readers miss, and each note says why. Only they use cost kind "unclear".
ADDED = "added_facts.csv"
# Versions from this one on use no added facts.
WITHOUT_ADDED = 16


def plan_facts(data, document=None, version=None):
    """Each plan's facts. document replaces machine/document_facts.csv if given."""
    if document is None:
        document = facts.read(data / "machine/document_facts.csv")
    added = facts.read(data / ADDED) if (version or current(data)) < WITHOUT_ADDED else []
    by_plan = collections.defaultdict(list)
    for f in document + facts.read(data / "generated/pbp_facts.csv") + added:
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
           "W_fitness": dot("fitness"), "Y_otc": dot("otc"), "AA_opt_packages": packages, "C_premium": plan_premium,
           "D_premium_full_extra_help": extra_help_premium, "E_moop": moop, "N_pharmacy_deductible": drug_deductible}


# The benefits each rule reads. A fact for a broader or narrower benefit is one the rule considers.
LEAVES = {"L_xray_imaging": ("imaging",), "AB_ambulance": ("ambulance", "emergency"), "I_outpatient_surgery": ("surgery",),
          "F_primary_care": ("visits",), "G_specialist": ("visits",), "H_inpatient": ("inpatient",),
          "J_outpatient_rehab": ("rehab",), "K_tests_labs": ("tests",), "Z_part_b_reduction": ("giveback",),
          "M_part_b_drugs": ("part_b_drugs",), "O_medical_deductible": ("medical_deductible",),
          "S_acupuncture": ("extras.acupuncture",), "T_chiropractic": ("extras.chiropractic",),
          "V_massage": ("extras.massage",), "X_transportation": ("extras.transportation",),
          "R_dental": ("dental",), "U_naturopath": ("extras.naturopathy",), "P_vision": ("vision",),
          "Q_hearing": ("hearing",), "W_fitness": ("fitness",), "Y_otc": ("otc",), "AA_opt_packages": ("packages",),
          "C_premium": ("plan_premium",), "D_premium_full_extra_help": ("plan_premium", "part_d_deductible"),
          "E_moop": ("moop",), "N_pharmacy_deductible": ("part_d_deductible",)}


DVHA = {"C_premium": plan_premium, "D_premium_full_extra_help": extra_help_premium,
        "E_optional_packages": optional_packages, "F_dental": dental, "G_vision": vision, "H_hearing": hearing,
        "I_alt_care_otc_travel": alt_care_otc_travel, "J_extra_benefits": extra_benefits}
DVHA_LEAVES = {"C_premium": ("plan_premium",), "D_premium_full_extra_help": ("plan_premium", "part_d_deductible"),
               "E_optional_packages": ("packages",), "F_dental": ("dental",),
               "G_vision": ("vision",), "H_hearing": ("hearing",),
               "I_alt_care_otc_travel": ("extras.acupuncture", "extras.chiropractic", "extras.massage",
                                         "extras.naturopathy", "otc", "emergency"),
               "J_extra_benefits": ("fitness", "meals", "foot_care", "extras.transportation", "other_supplemental")}
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


def plans(data):
    return layers.rows(data / "generated" / "plans.csv")


def lines(data, column, document=None, sheet="main", version=None):
    """{plan_id: [(value, cited facts), ...]} for each plan. See plan_facts for document and version."""
    found = plan_facts(data, document, version)
    return {p["plan_id"]: SHEETS[sheet][0][column](p["organization"], found[p["plan_id"]]) for p in plans(data)}


def shown(got):
    """A cell's value: its lines, without trailing blank ones."""
    values = [value for value, _ in got]
    while values and not values[-1]:
        values.pop()
    return " | ".join(values)


def sheet_rows(data, sheet, version=None):
    """A row per plan, with each column the rule's lines. A held cell is blank."""
    version = version or current(data)
    held_cells = held(data, version)
    columns = {column: lines(data, column, sheet=sheet, version=version) for column in fields.labels(sheet)}
    return [{"section": p["section"], "plan_id": p["plan_id"], "plan_name": p["plan_name"]}
            | {column: "" if cell(sheet, column, p["plan_id"]) in held_cells else shown(got[p["plan_id"]])
               for column, got in columns.items()} for p in plans(data)]


# Each version names the cells it holds, because the facts miss part of them. A held cell is blank and cites nothing.
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
VERSIONS[5] = VERSIONS[4] | {
    ("dvha.E_optional_packages", p): "the facts do not say that the rider replaces the plan's dental, and they name it "
                                     "Platinum Dental Rider"
    for p in ("H3805-048-0", "H2406-070-0", "H3805-040-0")} | {
    ("dvha.E_optional_packages", p): "the facts give no yearly maximum for the package"
    for p in ("H5216-048-0", "H1036-323-0", "H5216-428-2")}
KAISER = ("H9003-001-0", "H9003-006-0", "H9003-009-0")
VERSIONS[6] = VERSIONS[5] | {
    ("dvha.F_dental", p): "the rule does not show that comprehensive care covers only periodontal maintenance"
    for p in ("H1036-323-0", "H5216-428-2", "H5216-048-0")} | {
    ("dvha.F_dental", p): "the rule does not show that comprehensive care covers only adjunctive general services"
    for p in ("H6815-038-0", "H5439-015-0", "H5439-019-0", "H5439-010-0", "H5439-011-0")} | {
    ("dvha.F_dental", p): "the facts do not say that the plan has no annual maximum"
    for p in ("H2406-070-0", "H2056-003-0", "H3805-040-0")} | {
    ("dvha.J_extra_benefits", p): "the facts do not say what Wellness Bucks pay for"
    for p in ("H7199-002-0", "H2923-001-0", "H2923-028-3", "H2923-025-0", "H2923-005-0", "H2923-019-0")} | {
    ("dvha.I_alt_care_otc_travel", p): "the facts do not say what else the OTC allowance pays for"
    for p in ("H1036-317-0", "H3805-040-0", "H2001-045-0", "H1372-003-0")} | {
    ("dvha.I_alt_care_otc_travel", p): "the rule does not show care while traveling in the U.S." for p in KAISER} | {
    ("dvha.J_extra_benefits", p): "the rule does not show when transportation and hospital care at home apply"
    for p in KAISER} | {
    ("dvha.F_dental", p): "the facts give no routine preventive dental price" for p in ("H7199-002-0",)} | {
    ("dvha.F_dental", p): "the facts give no routine preventive or comprehensive dental price"
    for p in ("H2923-025-0", "H1036-317-0")} | {
    ("dvha.F_dental", p): "the facts give no routine comprehensive dental price"
    for p in ("H1036-153-0", "H1036-306-0", "H5216-427-2", "H5216-455-0")} | {
    ("dvha.I_alt_care_otc_travel", p): "the facts give no worldwide emergency maximum" for p in ("H7006-018-0", "H7006-021-0")} | {
    ("dvha.J_extra_benefits", p): "the facts miss the Virtual Cardiac Recovery Program"
    for p in ("H1036-323-0", "H1036-317-0", "H5216-455-0")} | {
    ("dvha.J_extra_benefits", "H1036-306-0"): "the facts miss the meals for every member"} | {
    ("dvha.J_extra_benefits", p): "the reviewer found that the facts understate who qualifies for the Virtual Cardiac "
                                  "Recovery Program"
    for p in ("H1036-153-0", "H5216-428-2", "H5216-048-0", "H5216-427-2")}
# Version 7 presents DVHA cells whose rule only leaves details out. Cells whose rule would mislead stay held.
RELEASED_7 = {("dvha.H_hearing", p) for p, in (c[1:] for c in VERSIONS[6] if c[0] == "dvha.H_hearing")} | {
    ("dvha.E_optional_packages", p) for p in ("H2406-070-0", "H3805-040-0", "H3805-048-0")} | {
    ("dvha.F_dental", p) for p in ("H1036-153-0", "H5439-010-0", "H5439-011-0", "H2056-003-0", "H2406-070-0", "H3805-040-0",
                                   "H5216-427-2", "H5216-455-0", "H7199-002-0")} | {
    ("dvha.I_alt_care_otc_travel", p) for p in ("H2001-045-0", "H3805-040-0", "H1372-003-0", "H7006-018-0", "H7006-021-0")} | {
    ("dvha.J_extra_benefits", p) for p in ("H1036-306-0", "H1036-317-0", "H1036-323-0", "H5216-455-0", "H7199-002-0",
                                           "H2923-001-0", "H2923-028-3", "H2923-025-0", "H2923-005-0", "H2923-019-0")}
VERSIONS[7] = {c: why for c, why in VERSIONS[6].items() if c not in RELEASED_7}
# Version 8 presents main cells whose rule only leaves a detail out or names the Part B deductible's amount.
VERSIONS[8] = {c: why for c, why in VERSIONS[7].items() if c[0] not in ("K_tests_labs", "O_medical_deductible")
               or c[1] in ("H6815-038-0", "H5439-019-0")}
VERSIONS[8][("K_tests_labs", "H5439-019-0")] = "the reviewer rejected the $10 price for most labs"
VERSIONS[9] = dict(VERSIONS[8])
# Version 10 holds cells whose new PBP facts make them cite document facts the reviewer has not checked. Version 11 does not.
VERSIONS[10] = VERSIONS[9] | {(c, p): "the reviewer has not checked the document facts it cites" for c, p in (
    ("O_medical_deductible", "H2001-045-0"), ("dvha.F_dental", "H1372-003-0"), ("dvha.F_dental", "H2406-042-0"),
    ("dvha.F_dental", "H3805-041-0"), ("dvha.I_alt_care_otc_travel", "H5216-048-0"),
    ("dvha.I_alt_care_otc_travel", "H5216-427-2"), ("dvha.I_alt_care_otc_travel", "H5216-455-0"))}
VERSIONS[11] = VERSIONS[9] | {("dvha.F_dental", "H1372-003-0"): "the facts give no routine comprehensive dental price"}
# Version 12 holds no cell. Caveat notes give what a rule leaves out.
VERSIONS[12] = {}
VERSIONS[13] = {
    ("K_tests_labs", "H5439-019-0"): "the reviewer rejected the $10 price for most labs",
    ("dvha.F_dental", "H1036-306-0"): "the facts give only the 0% crown recementation price for comprehensive care",
    ("dvha.F_dental", "H2923-025-0"): "the rule leaves out the 50% comprehensive price and what else the $2,000 pays for",
    ("dvha.I_alt_care_otc_travel", "H5216-048-0"): "the facts take the $50 worldwide urgent care copay for the emergency room's",
    ("dvha.I_alt_care_otc_travel", "H5216-455-0"): "the reviewer rejected the $130 worldwide emergency room copay",
}
# document_facts 17 reads the facts these cells lacked.
VERSIONS[14] = {k: v for k, v in VERSIONS[13].items() if k not in {
    ("dvha.F_dental", "H2923-025-0"), ("dvha.I_alt_care_otc_travel", "H5216-048-0"),
    ("dvha.I_alt_care_otc_travel", "H5216-455-0")}}
# Version 15 holds no cell. EOC page 90 gives H5439-019-0's $10 lab price, and H1036-306-0's dental rule only omits detail.
VERSIONS[15] = {}
# Version 16 holds no cell and uses no added facts.
VERSIONS[16] = {}
# The version that first presents each later column. Earlier versions hold its cells.
SINCE = {("dvha", "C_premium"): 3, ("dvha", "G_vision"): 4, ("dvha", "H_hearing"): 4, ("dvha", "E_optional_packages"): 5,
         ("dvha", "F_dental"): 6, ("dvha", "I_alt_care_otc_travel"): 6, ("dvha", "J_extra_benefits"): 6,
         ("dvha", "D_premium_full_extra_help"): 9, ("main", "C_premium"): 9, ("main", "D_premium_full_extra_help"): 9,
         ("main", "E_moop"): 9, ("main", "N_pharmacy_deductible"): 9}


def current(data, candidate=None):
    """The run's candidate version, or else the pinned one. candidate="" gives the pinned one."""
    if candidate is None:
        candidate = ",".join(c for c in os.environ.get(CANDIDATE, "").split(",") if c.strip().startswith("present@"))
    return steps.versions(data, {"present": VERSIONS}, candidate)["present"]


def held(data, version=None):
    """The cells that a version holds, by default the current one."""
    version = version or current(data)
    return VERSIONS[version] | {cell(sheet, column, r["plan_id"]): f"present {version} does not present this column"
                                for (sheet, column), since in SINCE.items() if version < since
                                for r in plans(data)}


def layer_rows(data, version=None):
    """Writes one row per line and cited document quote. A blank line with no cited fact writes no row, so the line keeps
    its other layers' value.
    Rows for a one-line cell name no line."""
    url = {d["sha256"]: d["url"] for d in layers.rows(data / "generated" / "documents_checked.csv") if d["sha256"]}
    version = version or current(data)
    out, held_cells = {}, held(data, version)
    for sheet, (rules, _) in SHEETS.items():
        for column in rules:
            for plan_id, got in lines(data, column, sheet=sheet, version=version).items():
                if cell(sheet, column, plan_id) in held_cells:
                    continue
                value = shown(got)
                got, one_line = got[:value.count(" | ") + 1], " | " not in value
                for n, (value, cited) in enumerate(got, 1):
                    row = dict(sheet=sheet, plan_id=plan_id, column=column, line="" if one_line else str(n), value=value)
                    cites = [(url[f["doc_sha"]], f["page"], q) for f in cited if presents([f])
                             for q in json.loads(f["quotes"])]
                    for cite in cites:
                        full = dict(row, **dict(zip(("url", "pdf_page", "quote"), cite)))
                        out[tuple(full.values())] = full
    return sorted(out.values(), key=lambda r: tuple(r.values()))


def write(data, version=None):
    """Writes the generated sheets and the presented layer."""
    for sheet, name in layers.SHEETS.items():
        with open(data / "generated" / name, "w", newline="") as f:
            out = csv.DictWriter(f, ["section", "plan_id", "plan_name"] + list(fields.labels(sheet)))
            out.writeheader()
            out.writerows(sheet_rows(data, sheet, version))
    with open(data / layers.PRESENTED, "w", newline="") as f:
        out = csv.DictWriter(f, layers.COLUMNS, lineterminator="\n")
        out.writeheader()
        out.writerows(layer_rows(data, version))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    write(years.data_dir(int(sys.argv[1])))
