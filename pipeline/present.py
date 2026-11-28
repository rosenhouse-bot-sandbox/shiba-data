"""Writes the generated sheets from facts, and generated/presented.csv, which cites them.

Usage: python3 -I pipeline/present.py <year>
"""
import collections, contextvars, csv, itertools, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import facts, fields, sheets, steps, years

RANK = {s: i for i, s in enumerate(facts.SOURCES_BEST_FIRST)}
OFFICES = ("office.pcp", "office.specialist", "freestanding")
ADVANCED = ("imaging.diagnostic.advanced.ct", "imaging.diagnostic.advanced.mri", "imaging.diagnostic.advanced.pet")
# Before present 18, these carriers' imaging kept no $0 low end for a $0 diagnostic mammogram (#127).
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


def every_price(found, leaves, settings=None, ok=usable):
    """Every ok price for the leaves at the settings, or at every setting if settings is (). A leaf with no price of its
    own or of a narrower benefit takes its broader benefits' prices. A source counts only where no better one has a
    price."""
    settings = ANY_SETTING if settings is None else settings
    got = []
    for f in screen([f for f in found if any(kin(f["benefit"], leaf) for leaf in leaves)], ok):
        if not settings or any(facts.covers(f["setting"], s) for s in settings):
            got.append(f)
        else:
            note(f, f"setting {f['setting']!r} is not {' or '.join(map(repr, settings))}")
    got = keep(got, lambda f: not shadow(f, got), lambda f: f"{shadow(f, got)} prices this benefit at this setting")
    priced_leaves = {leaf for leaf in leaves for f in got if facts.covers(leaf, f["benefit"])}
    return keep(got, lambda f: not any(facts.covers(f["benefit"], leaf) and f["benefit"] != leaf for leaf in priced_leaves),
                lambda f: "a narrower benefit has a price")


def shadow(f, found):
    """The best source above f's that prices f's benefit or a broader one at a setting that covers f's or that f's covers."""
    return next((g["source"] for g in sorted(found, key=lambda g: RANK[g["source"]])
                 if RANK[g["source"]] < RANK[f["source"]] and facts.covers(g["benefit"], f["benefit"])
                 and (facts.covers(g["setting"], f["setting"]) or facts.covers(f["setting"], g["setting"]))), None)


def kin(benefit, leaf):
    return facts.covers(benefit, leaf) or facts.covers(leaf, benefit)


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


def show_every(found):
    """Like show, but "$0-$35 or 20%" when a dollar amount above $0 sits beside a percent."""
    dollars = sorted(facts.number(a) for a in amounts(found) if a.startswith("$"))
    percents = sorted(facts.number(a) for a in amounts(found) if a.endswith("%"))
    if dollars and percents and dollars[-1]:
        return f"{span(money(dollars[0]), money(dollars[-1]))} or {span(f'{percents[0]:g}%', f'{percents[-1]:g}%')}"
    return show(found)


def xray_imaging(organization, found, mammograms=True):
    """Line 1 is X-rays and line 2 is CT, MRI and PET, each as (value, cited facts). See fields.py.
    Without mammograms, no $0 mammogram counts and Humana X-rays take every office price."""
    humana = "Humana" in organization and mammograms
    xrays = winners(found, ["imaging.xray"], OFFICES[:2] if humana else OFFICES)
    advanced = winners(found, ADVANCED, OFFICES)
    line2 = show(advanced)
    if not mammograms:
        keep([f for f in found if f["benefit"] == "imaging.diagnostic.mammogram"], lambda f: False,
             lambda f: "the final chart counts no mammogram")
        return [(show(xrays), unique(xrays)), (line2, unique(advanced))]
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


def every_xray_and_imaging(organization, found):
    """Line 1 is every in-network X-ray price and line 2 every CT, MRI, PET and $0 mammogram price, at an office,
    freestanding facility or outpatient hospital."""
    xrays = every_price(found, ("imaging.xray",))
    mammograms = keep(every_price(found, ("imaging.diagnostic.mammogram",)), lambda f: f["amount"] == "$0",
                      lambda f: "only a $0 mammogram counts")
    advanced = every_price(found, ("imaging.diagnostic.advanced",)) + mammograms
    return [(show_every(xrays), xrays), (show_every(advanced), advanced)]


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
    here = unique([f for leaf in TRIPS for f in best([f for f in found if f["setting"] != "outside_us"], leaf, "any", trip_here)])
    trips = [f for f in found if f["setting"] == "outside_us"]
    abroad = unique([f for leaf in TRIPS for f in best(trips, leaf, "outside_us", trip_abroad)])
    priced = [f for f in abroad if f["cost_kind"] in PRICED]
    covered = [f for f in abroad if f["cost_kind"] == "covered"]
    excluded = [f for f in abroad if f["cost_kind"] == "not_covered"]
    if priced:
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


def outpatient_surgery(organization, found, zero_low_ends=True):
    """Line 1 is outpatient hospital surgery and line 2 is surgical center surgery, each as (value, cited facts).
    Unless zero_low_ends is False, a $0 diagnostic colonoscopy or skin biopsy priced in that setting starts its line at $0.
    So does a $0 low end that any source gives surgery in that setting, even one for other services (the expert's rule in #99)."""
    def line(setting):
        cost = best(found, "surgery", setting)
        exact = keep([f for f in found if f["benefit"] in ZERO_SURGERIES], lambda f: f["setting"] == setting,
                     lambda f: f"the {setting!r} line counts only a price at {setting!r} itself")
        if not cost or not zero_low_ends:
            keep(exact, lambda f: False, lambda f: f"the {setting!r} line has no surgery price" if not cost
                 else "the final chart counts no $0 colonoscopy or skin biopsy")
            return show(cost), cost
        zeros = keep([f for leaf in ZERO_SURGERIES for f in best([g for g in exact if g["benefit"] == leaf], leaf, setting)],
                     lambda f: f["amount"] == "$0", lambda f: "only a $0 colonoscopy or skin biopsy counts")
        low_ends = [f for f in found if usable(f) and f["benefit"] == "surgery" and f["setting"] == setting
                    and f["amount"].startswith("$0-")]
        return show(cost + zeros + [dict(f, amount="$0") for f in low_ends]), unique(cost + zeros + low_ends)
    return [line("outpatient_hospital"), line("asc")]


ZERO_TESTS = ("AgeRight", "Regence")
# Rules before present 29 count this plan's $140 sleep study, though only outpatient hospitals offer it (expert).
HOSPITAL_SLEEP_STUDY = ("H1036-306-0",)


ELIGIBILITY = re.compile(r"medicaid|\bQMB|extra help|eligib", re.I)


def any_test(f):
    """A price for some of the tests, such as "certain lab services", but not one for some members only."""
    return priced(f) and not (f["provider_tier"] or ELIGIBILITY.search(f["condition"]))


def every_test_and_lab(organization, found):
    """Shows "tests/labs" from every in-network test, lab and genetic test price at an office, freestanding facility or
    outpatient hospital, plus AgeRight's $0 mammogram or colonoscopy."""
    tests = every_price(found, ("tests.diagnostic",), ok=any_test)
    if tests and "AgeRight" in organization:
        zeros = winners(found, ["imaging.diagnostic.mammogram"], OFFICES) + [
            f for s in ("outpatient_hospital", "asc") for f in best(found, "surgery.colonoscopy", s)]
        tests += [f for f in zeros if f["amount"] == "$0"]
    tests, labs = unique(tests), every_price(found, ("tests.lab", "tests.genetic"), ok=any_test)
    return [(f"{show_every(tests)}/{show_every(labs)}" if tests or labs else "", tests + labs)]


def tests_labs(organization, found, zero_tests=ZERO_TESTS, lab_settings=OFFICES):
    """Shows "tests/labs". Tests use office and freestanding prices and labs use lab_settings, or else outpatient
    hospital prices."""
    tests = winners(found, ["tests.diagnostic"], OFFICES, any_test)
    if any(f["plan_id"] in HOSPITAL_SLEEP_STUDY for f in found):
        keep([f for f in found if f["benefit"] == "tests.diagnostic.sleep_study"],
             lambda f: facts.covers(f["setting"], "outpatient_hospital"), lambda f: "only a sleep study at an outpatient hospital counts")
        tests += best(found, "tests.diagnostic.sleep_study", "outpatient_hospital", settings_noted=False)
    else:
        keep([f for f in found if f["benefit"] == "tests.diagnostic.sleep_study"], lambda f: False,
             lambda f: "a sleep study counts only for " + ", ".join(HOSPITAL_SLEEP_STUDY))
    if tests and any(name in organization for name in zero_tests):
        zeros = winners(found, ["imaging.diagnostic.mammogram"], OFFICES) + [
            f for s in ("outpatient_hospital", "asc") for f in best(found, "surgery.colonoscopy", s)]
        tests += [f for f in zeros if f["amount"] == "$0"]
    tests, labs = unique(tests), winners(found, ["tests.lab"], lab_settings, any_test)
    return [(f"{show_every(tests)}/{show_every(labs)}" if tests or labs else "", tests + labs)]


def visit_line(found, setting, network):
    def ok(f):
        return priced(f, network)

    got = best([f for f in found if f["network"] in (network, "any")], "visits", setting, ok)
    got = prefer(got, lambda f: f["network"] == network, lambda f: f"a price for network {network!r} won")
    got = prefer(got, lambda f: not f["condition"], lambda f: "a price without a condition won")
    return show(got), got


VISIT_KINDS = {"office.pcp": re.compile(r"\bPCP\b|primary care", re.I), "office.specialist": re.compile(r"specialist", re.I)}


def virtual_kind(f):
    """The visit setting a telehealth price is for: "" for any visit, or None for something else."""
    words = f"{f['condition']} {f['provider_tier']}".strip()
    if not words:
        return ""
    kinds = [kind for kind, pattern in VISIT_KINDS.items() if pattern.search(words)]
    return kinds[0] if len(kinds) == 1 else None


def visits(setting, telehealth=False):
    """Line 1 is in network and line 2 out of network, if the plan prices any visit out of network. With telehealth,
    line 1 also counts the in-network telehealth visit price."""
    def rule(organization, found):
        out = any(f["benefit"] == "visits" and f["network"] == "out" and priced(f, "out") for f in found)
        if not out:
            keep([f for f in found if facts.covers(f["benefit"], "visits") and f["network"] == "out"], lambda f: False,
                 lambda f: "the plan has no out-of-network visit price")
        line = visit_line(found, setting, "in")
        if telehealth and line[1]:
            virtual = keep([f for f in found if f["setting"] == "telehealth" and f["benefit"] == "visits"],
                           lambda f: priced(f) and virtual_kind(f) in ("", setting),
                           lambda f: f"it is not a {setting} telehealth price")
            line = (show_every(line[1] + top(virtual)), line[1] + top(virtual))
        return [line, visit_line(found, setting, "out") if out else ("", [])]
    return rule


THERAPIES = ("rehab.physical", "rehab.occupational", "rehab.speech")


def outpatient_rehab(organization, found, settings=OFFICES):
    """Shows therapy visit prices at settings, or at outpatient hospitals if there are none."""
    got = unique(winners(found, THERAPIES, settings))
    return [(show(got), got)]


def days(f):
    """(first, last) days of a per-day cost, last None for "days 6+", or None."""
    m = re.fullmatch(r"days ([1-9]\d*)(?:-([1-9]\d*)|\+)", f["limit"]) if f["unit"] == "per day" else None
    return m and (int(m[1]), m[2] and int(m[2]))


def stay_ok(f):
    return usable(dict(f, condition="")) and f["condition"] in ("", f["limit"])


def inpatient(organization, found, per_stay="per admission"):
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
        return [(f"{show(stays)} {per_stay}", stays), ("", [])]
    return [(show(got), got), ("", [])]


def unique(found):
    return list({id(f): f for f in found}.values())


def giveback(organization, found, dot_only=False):
    """Shows the monthly Part B premium reduction, or a dot."""
    @unless("it is not a Part B premium reduction")
    def ok(f):
        return f["cost_kind"] in ("part_b_reduction", "covered") and not (f["package"] or f["provider_tier"])

    got = prefer(best(found, "giveback", "any", ok), lambda f: not f["condition"],
                 lambda f: "a reduction without a condition won")
    paid = [f for f in got if f["cost_kind"] == "part_b_reduction"]
    for f in got:
        if paid and f not in paid:
            note(f, "a reduction amount won")
    return [("●" if dot_only else show(paid), paid)] if paid else [("●", got)] if got else [("", [])]


@unless("it is not a coinsurance or $0 copay for a Part B drug")
def drug_price(f):
    return (priced(f) and not f["provider_tier"] and facts.covers("part_b_drugs", f["benefit"])
            and (f["cost_kind"] == "coinsurance" or f["amount"] == "$0"))


def part_b_drugs(organization, found, highest=False):
    """Shows the range of Part B drug coinsurance, from each kind of drug's best source.
    A $0 copay, such as for vaccines, counts as 0%."""
    ok = screen([f for f in found if facts.covers("part_b_drugs", f["benefit"])], drug_price)
    got = [f for leaf in sorted({f["benefit"] for f in ok}) for f in top([g for g in ok if g["benefit"] == leaf])]
    percents = sorted(facts.number(n) for n in amounts(got))
    if not got:
        return [("", got)]
    low = percents[-1] if highest else percents[0]
    return [(span(f"{low:g}%", f"{percents[-1]:g}%"), got)]


@unless("it is not a Part B drug price for every member")
def any_drug_price(f):
    """A price for some of the drugs, such as "flu vaccines", but not one for some members only."""
    return facts.covers("part_b_drugs", f["benefit"]) and any_test(f)


def every_drug_price(organization, found):
    """Shows every Part B drug price, such as "$0-20%" or "$0-$35 or 20%"."""
    got = every_price(found, ("part_b_drugs",), (), any_drug_price)
    return [(show_every(got), got)]


def deductible_ok(f):
    return (f["cost_kind"] == "deductible" and f["covered_by"] == "medicare"
            and not (f["condition"] or f["provider_tier"] or f["package"]))


def medical_deductible(organization, found, chart_wording=False):
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
    if part_b and chart_wording:
        return [("Same as 2027 Pt B Deductible", unique(got + some + part_b))]
    value = "Part B deductible" if part_b else show(got)
    if networks == ("out",):
        value += (" some OON" if chart_wording else " some out-of-network services") if some else " out-of-network only"
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
    rule.dot = True
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
    return f"/{periods.pop()}" if len(periods) == 1 and "" not in periods else ""


def routine(f):
    return (f["network"] in ("in", "any") and f["covered_by"] == "supplemental"
            and not (f["condition"] or f["package"] or f["pool"]))


@unless("it is not a routine exam copay")
def exam_ok(f):
    return routine(f) and f["cost_kind"] == "copay" and not f["provider_tier"]


def details_of(found, benefit, condition):
    """The best source's supplemental in-network facts, outside packages, that give a detail of benefit."""
    return top([f for f in found if f["benefit"] == benefit and f["condition"] == condition
                and f["covered_by"] == "supplemental" and f["network"] in ("in", "any") and not f["package"]])


def provider_network(benefit):
    """A detail naming the company or network whose providers the plan uses for benefit."""
    def network(found):
        got = [f for f in details_of(found, benefit, "provider network") if f["cost_kind"] == "covered" and f["limit"]]
        if not got:
            return "", []
        name = min((f["limit"] for f in got), key=len)
        short = re.sub(r"^.*\((\w+)\)$", r"\1", name)
        return (short if re.search(r"network$", short, re.I) else f"{short} network"), [f for f in got if f["limit"] == name]
    return network


YEAR_END = re.compile(r"end of the (?:plan |calendar )?year", re.I)


def rollover(found, benefit):
    """"no rollover" or "rolls over until year-end" when the best source says, and the facts it cites."""
    got = details_of(found, benefit, "rollover")
    kinds = {f["cost_kind"] for f in got}
    if kinds == {"not_covered"}:
        return "no rollover", got
    if kinds == {"covered"} and all(YEAR_END.search(f["limit"]) for f in got):
        return "rolls over until year-end", got
    return "", []


def eyewear_pairs(found):
    """"1 pair/year" from glasses limits that agree, and whether an unused eyewear allowance rolls over."""
    got = [f for f in details_of(found, "vision.eyewear", "glasses") if f["cost_kind"] == "visit_limit"]
    counts = {f["amount"] for f in got}
    parts, cited = [], []
    if len(counts) == 1 and per(got):
        count = counts.pop()
        parts.append(f"{count} pair{'' if count == '1' else 's'}{per(got)}")
        cited += got
    if any(f["benefit"] == "vision.eyewear" and routine(f) and f["cost_kind"] in ("allowance", "max") for f in found):
        text, says = rollover(found, "vision.eyewear")
        if text:
            parts.append(text)
            cited += says
    return "; ".join(parts), cited


@unless("it is not a routine exam maximum")
def exam_max_ok(f):
    return routine(f) and f["cost_kind"] == "max" and not f["provider_tier"]


def exam_max(found):
    """"exam max $75/year" from the best source's routine in-network eye exam maximum."""
    got = best(found, "vision.exam", "any", exam_max_ok)
    return (f"exam max {show(got)}{per(got)}", got) if got and per(got) else ("", [])


def dental_exclusions(found, summary_first=False):
    """A detail: "excludes implants, cosmetic procedures" from the best source's dental exclusions. With summary_first,
    the Summary of Benefits' shorter list comes first."""
    def listed(facts_):
        return [f for f in details_of(facts_, "dental", "excludes") if f["cost_kind"] == "not_covered" and f["limit"]]
    got = (listed([f for f in found if f["source"] == "SB"]) if summary_first else []) or listed(found)
    return (f"excludes {', '.join(dict.fromkeys(f['limit'] for f in got))}", got) if got else ("", [])


def dental_reimbursement(found):
    """A detail: "pay up front, then reimbursed" when the best source says the plan pays dental care by reimbursement."""
    got = [f for f in details_of(found, "dental", "reimbursement") if f["cost_kind"] == "covered"]
    return ("pay up front, then reimbursed", got) if got else ("", [])


def dental_rollover(found):
    """A detail: whether an unused dental allowance or maximum rolls over, when every member has one."""
    if any(f["benefit"].split(".")[0] == "dental" and f["cost_kind"] in ("allowance", "max") and everyone(f)
           and not f["package"] for f in found):
        return rollover(found, "dental")
    return "", []


def no_maximum(found):
    """"no annual max" when the best source says the plan's dental coverage has none and no fact gives one."""
    got = [f for f in details_of(found, "dental", "no annual maximum") if f["cost_kind"] == "covered"]
    capped = any(facts.covers("dental", f["benefit"]) and f["cost_kind"] == "max" and everyone(f) for f in found)
    return ("no annual max", got) if got and not capped else ("", [])


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


PER_AID = re.compile(r"^per (?:hearing )?(?:aid|ear)$", re.I)


def each_per_aid(found):
    """"$399 or $699 per aid" from dollar copays that each price one aid, or "" if they do not."""
    options = {facts.number(a) for f in found for a in f["amount"].split(" or ")
               if re.fullmatch(r"\$[\d,.]+", a.strip())} if all(PER_AID.match(f["unit"]) for f in found) else set()
    if len(options) < 2 or len(options) != len({a for f in found for a in f["amount"].split(" or ")}):
        return ""
    return " or ".join(money(n) for n in sorted(options)) + " per aid"


def hearing(organization, found, each_price=False, exam_renews=False):
    """Shows the routine hearing exam copay, then a hearing aid allowance or else copays, and how many aids.
    The count comes from a visit limit, doubled when it is per ear, or is 2 when the best source prices or limits aids
    per ear. With each_price, it lists each aid copay instead of their range. With exam_renews, the exam says how
    often it renews when its best source says so."""
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
    exam_renewals = renewal(found, "hearing.exam") if exams and exam_renews else []
    parts = [f"exam {show(exams)}{per(exam_renewals)}"] if exams else []
    if allowance:
        ear = " per ear" if any(f["unit"] == "per ear" for f in allowance) else ""
        parts.append(f"aids allowance {show(allowance)}{ear}{per(renews)}")
    elif copays and each_price and each_per_aid(copays):
        parts.append(f"aids {each_per_aid(copays)}")
    elif copays:
        parts.append(f"aids {show(copays)}")
    limits = top([f for f in found if f["benefit"] == "hearing.aids" and routine(f) and not f["provider_tier"]
                  and f["cost_kind"] == "visit_limit"]) if priced else []
    pairs = [f for f in priced + renews if PAIR.search(f["unit"] + " " + f["limit"])]
    counted = limits or pairs
    if counted:
        aids = min(int(f["amount"]) * (2 if f["unit"] == "per ear" else 1) for f in limits) if limits else 2
        parts.append(f"{aids} aids{per(renews)}")
    return [("; ".join(parts), unique(exams + exam_renewals + priced + renews + counted))]


VISITS = (("fitting", re.compile(r"fitting", re.I)), ("follow-ups", re.compile(r"follow.?up", re.I)))
FIRST_YEAR = re.compile(r"\bfirst (?:year|12 months)\b", re.I)
UNLIMITED = re.compile(r"\bunlimited\b", re.I)
AID_EXTRAS = (("trial period", ((r"^(\d+) days?$", "{}-day trial"),)),
              ("warranty", ((r"^(\d+) years?$", "{}-year warranty"),)),
              ("batteries", ((r"\b(\d+ batteries per aid)\b", "{}"), (r"^(\d+) years?\b", "{} years of batteries"),
                             (r"", "batteries"))))


def visit_count(f):
    """"1 visit/year", "3 visits in the first year after buying an aid", "unlimited visits" or the like from a visit
    limit, or "" if it gives no count."""
    count = f["amount"] if f["cost_kind"] == "visit_limit" else "unlimited" if UNLIMITED.search(f["limit"]) else ""
    when = per([f]) or (" in the first year after buying an aid" if FIRST_YEAR.search(f["limit"]) else "")
    return f"{count} visit{'' if count == '1' else 's'}{when}" if count else ""


def aid_extra(item, patterns, got):
    """How the facts describe the item, by the first pattern every fact's limit matches the same way, or ""."""
    for pattern, label in patterns:
        shown = {label.format(*m.groups()) for f in got for m in [re.search(pattern, f["limit"], re.I)] if m}
        if len(shown) == 1 and all(re.search(pattern, f["limit"], re.I) for f in got):
            return shown.pop()
    return ""


def hearing_details(found, rechargeable=False):
    """A detail: the best source's price and count of hearing aid fittings and follow-up visits, then the trial period,
    warranty and batteries that come with an aid. With rechargeable, it adds the extra price of a rechargeable aid."""
    mine = [f for f in found if f["benefit"] in ("hearing.exam", "hearing.aids") and extra(f)]
    parts, cited = [], []
    for name, words in VISITS:
        visits = [f for f in mine if f["benefit"] == "hearing.exam" and words.search(f["condition"])]
        prices = top([f for f in visits if f["cost_kind"] in PRICED])
        counts = top([f for f in visits if f["cost_kind"] in ("visit_limit", "covered") and visit_count(f)])
        if len({visit_count(f) for f in counts}) > 1:
            counts = []
        shown = " ".join(p for p in (show(prices), visit_count(counts[0]) if counts else "") if p)
        if shown:
            parts.append(f"{name} {shown}")
            cited += prices + counts
    extras = []
    for item, patterns in AID_EXTRAS:
        got = top([f for f in mine if f["benefit"] == "hearing.aids" and f["cost_kind"] == "covered"
                   and f["condition"].lower() == item])
        shown = aid_extra(item, patterns, got) if got else ""
        if shown:
            extras.append(shown)
            cited += got
    upgrade = top([f for f in mine if f["benefit"] == "hearing.aids" and f["cost_kind"] in PRICED
                   and f["condition"].lower() == "rechargeable"]) if rechargeable else []
    if upgrade:
        extras.append(f"{show(upgrade)} more {upgrade[0]['unit'] or 'per aid'} for rechargeable")
        cited += upgrade
    return "; ".join(parts + ([", ".join(extras)] if extras else [])), cited


def dvha_hearing(exam_renews=False, details=(), oon=None):
    """The DVHA hearing rule: the plan's hearing, each package's, the details, and out-of-network prices."""
    return or_none(with_lacking(with_packages(with_details(
        lambda o, found: hearing(o, found, each_price=True, exam_renews=exam_renews), *details, oon or HEARING_OON)),
        ("no hearing aid allowance", "hearing.aids")), "hearing")


@unless("it is not a monthly package premium")
def package_premium(f):
    return f["cost_kind"] == "premium" and f["unit"] in ("per month", "")


@unless("it is not a yearly maximum")
def yearly_max(f):
    return f["cost_kind"] == "max" and period(f) == "year" and not f["pool"]


@unless("it is not an allowance for every member of the package")
def allowance(f):
    return f["cost_kind"] == "allowance" and not (f["provider_tier"] or f["pool"])


def optional_packages(organization, found, allowances=True, details=True):
    """Shows each optional package's monthly premium. With details, it also shows its yearly dental maximum, and with
    allowances its eyewear and hearing aid allowances. A package that also covers other benefits says "dental max".
    A document that says the plan sells none cites a blank."""
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
        if not details:
            parts.append(part)
            cited += premium
            continue
        if dental_max:
            others = any(not facts.covers("dental", f["benefit"]) and not facts.covers("packages", f["benefit"])
                         for f in package)
            part += f", {'dental max' if others else 'max'} {show(dental_max)}"
        eyewear = best(package, "vision.eyewear", "any", allowance) if allowances else []
        if eyewear:
            part += f", eyewear {show(eyewear)}{per(eyewear)}"
        aids = best(package, "hearing.aids", "any", allowance) if allowances else []
        if aids:
            ear = " per ear" if any(f["unit"] == "per ear" for f in aids) else ""
            part += f", hearing aids {show(aids)}{ear}{per(aids)}"
        parts.append(part)
        cited += premium + dental_max + eyewear + aids
    keep([f for f in named if f["package"] and f["package"] not in priced], lambda f: False,
         lambda f: "its package has no monthly premium")
    none = keep([f for f in named if f["cost_kind"] == "not_covered"], lambda f: not parts,
                lambda f: "a package for sale won")
    return [("; ".join(parts), unique(cited))] if parts else [("", top(none) if none else [])]


def with_details(rule, *details):
    """The rule, with each detail's part added to a cell that shows something. A detail returns (part, cited)."""
    def detailed(organization, found):
        (value, cited), = rule(organization, found)
        for detail in details if value else ():
            part, used = detail(found)
            if part:
                value, cited = f"{value}; {part}", cited + used
        return [(value, unique(cited))]
    detailed.__name__, detailed.__qualname__ = rule.__name__, rule.__qualname__
    return detailed


def out_of_network(*services):
    """A detail: "OON <label> <price>, ..." from each (label, benefit[, condition pattern])'s out-of-network price for
    every member. A service with a pattern takes only prices whose condition matches it."""
    def ok(condition):
        @unless("it is not an out-of-network supplemental price for every member that pays part of the cost")
        def priced(f):
            return (f["network"] == "out" and f["covered_by"] == "supplemental" and f["cost_kind"] in PRICED
                    and f["amount"] != "100%" and not (f["package"] or f["pool"] or f["provider_tier"])
                    and (condition.search(f["condition"]) if condition else not f["condition"]))
        return priced

    def detail(found):
        parts, cited = [], []
        for label, leaf, *condition in services:
            test = ok(condition[0] if condition else None)
            prices = top(exactly(found, (leaf,), test, test.unless))
            if prices:
                parts.append(f"{label} {show(prices)}")
                cited += prices
        return ("OON " + ", ".join(parts) if parts else "", cited)
    return detail


def dental_deductible(found):
    """A detail: the yearly deductible for routine dental care, or "no deductible"."""
    deductibles = top(exactly(found, ("dental", "dental.preventive", "dental.comprehensive"),
                              lambda f: everyone(f) and f["cost_kind"] == "deductible" and period(f) == "year",
                              "it is not a yearly dental deductible for every member"))
    if not deductibles:
        return "", []
    shown_ = show(deductibles)
    return ("no deductible" if shown_ == "$0" else f"deductible {shown_}/year"), deductibles


COUNTS = {"two": "2", "three": "3", "four": "4", "five": "5", "six": "6"}
HOW_OFTEN = re.compile(r"\b(?:every|per|each)\s+(?:(\d+|two|three|four|five|six)\s+)?(?:calendar\s+|benefit\s+|plan\s+)?"
                       r"(year|month)s?\b", re.I)
PER_PART = re.compile(r"\bper (?:tooth|quadrant|surface|arch)\b", re.I)


def how_often(f):
    """"year", "5 years" or "6 months" from the fact's limit, or ""."""
    match = HOW_OFTEN.search(f["limit"])
    if not match:
        return ""
    count, unit = COUNTS.get((match[1] or "").lower(), match[1]), match[2].lower()
    return f"{count} {unit}s" if count and count != "1" else unit


def preventive_limits(found):
    """Shows how often the best source says the plan covers each preventive dental service."""
    limits = top(exactly(found, ("dental.preventive",),
                         lambda f: extra(f) and f["condition"] and f["cost_kind"] == "visit_limit" and how_often(f)
                         and not PER_PART.search(f["unit"] + " " + f["limit"]),
                         "it is not a limit on how often the plan covers one preventive service"))
    parts = []
    for f in limits:
        often = how_often(f)
        parts.append(f"{f['condition']} {f['amount']}" + (f"/{often}" if often == "year" else f" every {often}"))
    return ("PREV limits: " + " · ".join(parts) if parts else ""), limits


def with_packages(rule):
    """The rule, followed by "With <package>: ..." for the parts that the rule shows from each priced package's own
    facts and not from the plan's."""
    def packaged(organization, found):
        (value, cited), = rule(organization, found)
        for name in sorted({f["package"] for f in best(found, "packages", "any", package_premium)}):
            originals = [f for f in found if f["package"] == name]
            copies = [dict(f, package="", packaged=name) for f in originals]
            original = {id(c): f for c, f in zip(copies, originals)} | {facts.identity(c): f for c, f in zip(copies, originals)}
            (added, used), = rule(organization, copies)
            added = "; ".join(part for part in added.split("; ") if part and part not in value.split("; "))
            if added and presents(used):
                cited = (cited if value else []) + [original.get(id(f)) or original[facts.identity(f)] for f in used]
                value = f"{value}. With {name}: {added}" if value else f"With {name}: {added}"
        return [(value, unique(cited))]
    packaged.__name__, packaged.__qualname__ = rule.__name__, rule.__qualname__
    return packaged


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


# Conditions that describe a benefit rather than limit who gets it.
DETAIL = re.compile(r"^(rollover|also pays for|provider network|no annual maximum|excludes|reimbursement)")


def lacks(found, leaf):
    """Says if a plan's documents give no supplemental leaf benefit in any network, at any tier or for any member, and
    gives the best source's facts that say the plan does not cover leaf itself for every member."""
    related_ = [f for f in found if (facts.covers(leaf, f["benefit"]) or facts.covers(f["benefit"], leaf))
                and f["covered_by"] == "supplemental" and not f["package"] and not DETAIL.match(f["condition"])]
    if not any(f["source"] in facts.DOCUMENTS for f in found) or any(f["cost_kind"] != "not_covered" for f in related_):
        return False, []
    return True, top([f for f in related_ if f["benefit"] == leaf and extra(f) and not f["condition"]])


def or_none(rule, leaf):
    """The rule, starting with "None" when the plan lacks leaf. A package's part may follow. "None" alone cites only
    facts that say the plan does not cover leaf."""
    def none(organization, found):
        (value, cited), = rule(organization, found)
        lacking, says = lacks(found, leaf)
        if lacking:
            value, cited = (f"None. {value}" if value else "None"), unique(says + (cited if value else []))
        return [(value, cited)]
    none.__name__, none.__qualname__ = rule.__name__, rule.__qualname__
    return none


def with_lacking(rule, *parts):
    """The rule, with each (label, leaf) part the plan lacks added to the plan's own value, before any package's."""
    def lacking(organization, found):
        (value, cited), = rule(organization, found)
        own, packaged = (value.split(". With ", 1) + [""])[:2]
        for label, leaf in parts if own and not own.startswith("With ") else ():
            missing, says = lacks(found, leaf)
            if missing:
                own, cited = f"{own}; {label}", cited + says
        return [(f"{own}. With {packaged}" if packaged else own, unique(cited))]
    lacking.__name__, lacking.__qualname__ = rule.__name__, rule.__qualname__
    return lacking


def limit_text(limits):
    """" 12 visits/year" from visit limits that agree on how often they renew, or ""."""
    return f" {min(int(f['amount']) for f in limits)} visits/{renews(limits)}" if limits and renews(limits) else ""


# Each service's short name, its name beside a dental maximum, and its benefit.
ALT_CARE = (("Acup", "acupuncture", "extras.acupuncture"), ("Chiro", "chiropractic", "extras.chiropractic"),
            ("Massage", "massage", "extras.massage"), ("Naturopath", "naturopath", "extras.naturopathy"))
COMBINED = re.compile(r"combined", re.I)


def alt_care(found, rates=False):
    """("Acup $0 24 visits/year", ...) parts and their facts. A service paid from a shared allowance names it.
    Copays whose visit limits are shared show the limit once. With rates, an allowance shared with dental shows its
    amount, and services that pay one price from a shared allowance show it."""
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
            pool = shared[0]["pool"]
            prices = top([f for f in facts_ if f["pool"] == pool and f["cost_kind"] in PRICED]) if rates else []
            pooled.setdefault(pool, []).append((name, shared + prices))
    parts, cited = [], []
    for pool, services in pooled.items():
        fs = [f for _, got in services for f in got]
        allowance = [f for f in fs if f["cost_kind"] == "allowance"]
        prices = [[f for f in got if f["cost_kind"] in PRICED] for _, got in services]
        price = f" {show(prices[0])}" if all(prices) and len({show(p) for p in prices}) == 1 else ""
        if not price:
            drop([f for p in prices for f in p], "the services that share the allowance do not all give one price")
            fs = [f for f in fs if f["cost_kind"] not in PRICED]
        if re.search(r"dental", pool, re.I) and rates and renews(allowance):
            source = f"{show(allowance)}/{renews(allowance)} allowance shared with dental"
        elif re.search(r"dental", pool, re.I):
            source = "dental allowance"
        elif renews(allowance):
            kind = "Wellness Bucks" if re.search(r"wellness bucks", pool, re.I) else "allowance"
            source = f"{show(allowance)}/{renews(allowance)} {kind}"
        else:
            drop([f for got in pooled.values() for _, fs_ in got for f in fs_] + [f for _, c, lim in own for f in c + lim],
                 "the facts do not say how often the shared allowance renews")
            return None
        parts.append(f"{', '.join(name for name, _ in services)}{price} from {source}")
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


FOOD = re.compile(r"food|grocer", re.I)


def also_pays_for(found, sharers=()):
    """What the best source says the OTC allowance also pays for, for every member and then for some members, leaving
    out things that name a sharer."""
    def things(condition, shown=()):
        names = {}
        for f in details_of(found, "otc", condition):
            if (f["cost_kind"] == "covered" and f["limit"] and f["limit"].casefold() not in shown
                    and not any(re.search(rf"\b{name}", f["limit"], re.I) for name in sharers)):
                names.setdefault(f["limit"].casefold(), (f["limit"], []))[1].append(f)
        return names
    every_member = things("also pays for")
    some = {}
    for condition in {f["condition"] for f in found if f["condition"].startswith("also pays for ")}:
        for key, (name, got) in things(condition, every_member).items():
            some.setdefault(key, (name, []))[1].extend(got)
    parts = [f"also for {', '.join(n for n, _ in every_member.values())}"] if every_member else []
    parts += [f"also for {', '.join(n for n, _ in some.values())} for some members"] if some else []
    return parts, [f for _, got in (*every_member.values(), *some.values()) for f in got]


def over_the_counter(found, food=False, none=False, details=False):
    """The OTC allowance, and the benefits that share it when the same allowance pays for them.
    With food, it says when any source says the allowance also pays for food. With none, it says when the plan lacks OTC.
    With details, it says whether the allowance rolls over and what else it pays for, instead of saying food."""
    allowances = keep(exactly(found, ("otc",), everyone, "it is not a supplemental in-network benefit for every member"),
                      lambda f: f["cost_kind"] == "allowance", lambda f: "it is not an allowance")
    got = top(allowances)
    lacking, says = lacks(found, "otc") if none else (False, [])
    if lacking:
        return ["OTC none"], says
    if not got:
        return [], []
    for_food = [f for f in allowances if FOOD.search(f["pool"] + f["quotes"])][:1] if food else []
    for_food = [] if details and any(FOOD.search(f["limit"]) for f in also_pays_for(found)[1]) else for_food
    label = "OTC and food" if for_food else "OTC"
    got += [f for f in for_food if f not in got]
    period_ = renews(got)
    if not period_:
        drop(got, "the facts do not say how often the OTC allowance renews")
        return None
    pools = {f["pool"] for f in got if f["pool"]}
    amount = {facts.number(a) for a in amounts(got)}
    sharers = top([f for f in found if f["pool"] in pools and f["benefit"] != "otc" and everyone(f)
                   and f["cost_kind"] == "allowance" and {facts.number(a) for a in amounts([f])} == amount
                   and every(f) == period_])
    names = [n for n in SHARERS if any(facts.covers(n, f["benefit"]) for f in sharers)]
    text, says = rollover(found, "otc") if details else ("", [])
    also, also_cited = also_pays_for(found, names) if details else ([], [])
    note = f" ({'; '.join(([text] if text else []) + also)})" if text or also else ""
    if not sharers:
        return [f"{label} {show(got)}/{period_}{note}"], got + says + also_cited
    return ([f"{label} from {show(got)}/{period_} card shared with {', '.join(names)}{note}"],
            got + sharers + says + also_cited)


def urgent(f):
    return all(re.search(r"urgent", q, re.I) and not re.search(r"emergenc", q, re.I) for q in json.loads(f["quotes"]))


URGENT = re.compile(r"urgent", re.I)


def abroad_urgent_care(found):
    """The best source's copays for urgently needed care outside the U.S."""
    return top([f for f in found if f["benefit"] == "emergency" and f["setting"] == "outside_us"
                and f["network"] in ("in", "any") and not (f["package"] or f["provider_tier"])
                and f["cost_kind"] in PRICED and (URGENT.search(f["condition"]) or urgent(f))])


def worldwide(found, urgent_care=False):
    """The copay for emergency care outside the U.S. and the most the plan pays. Several copays that no quote tells
    apart leave the part unknown. A document that says the plan covers none cites a blank.
    With urgent_care, it also shows the best source's one copay for urgently needed care outside the U.S."""
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
    label, urgent_part = "Worldwide ER", ""
    urgents = abroad_urgent_care(found) if urgent_care else []
    if len({f["amount"] for f in urgents}) != 1:
        urgents = []
    elif urgents[0]["amount"] == copays[0]["amount"]:
        label = "Worldwide ER/urgent"
    else:
        urgent_part = f", urgent care {show(urgents)}"
    return [f"{label} {show(copays)}{urgent_part}" + (f", {show(maxes)} max" if maxes else "")], copays + urgents + maxes


NURSING_HOME = re.compile(r"nursing home|skilled nursing", re.I)


def virtual_visits(found):
    """["Telehealth $0-$40"] from in-network virtual visit prices, other than in a nursing home, and their facts."""
    @unless("it is not an in-network virtual visit price outside a nursing home")
    def ok(f):
        return (f["network"] in ("in", "any") and f["setting"] == "telehealth" and f["cost_kind"] in PRICED
                and not (f["package"] or f["provider_tier"] or NURSING_HOME.search(f["condition"])))
    prices = top(exactly(found, ("visits",), ok, ok.unless))
    return ([f"Telehealth {show(prices)}"] if prices else []), prices


def alt_care_otc_travel(organization, found, telehealth=False, food=False, rates=False, none=False, urgent_care=False,
                        details=False, fitness=False, fitness_allowance=False):
    """Shows routine acupuncture, chiropractic, massage and naturopathy, the OTC allowance, and worldwide emergency
    care, and with telehealth, virtual visit prices. With food, it says when the OTC allowance also pays for food.
    See alt_care for rates, over_the_counter for none and details and worldwide for urgent_care. With fitness, it starts
    with the fitness program and Wellness Bucks. With fitness_allowance, it shows a fitness allowance that no other
    benefit shares. A part the facts do not fully give leaves the cell blank."""
    parts, cited = [], []
    if fitness:
        for got in (named_extras(found, ("fitness",), prices=True, programs=True, allowances=fitness_allowance),
                    wellness_bucks(found)):
            parts += got[0]
            cited += got[1]
    for name, part in (("alt care", lambda found: alt_care(found, rates)),
                       ("over the counter", lambda found: over_the_counter(found, food, none, details)),
                       ("worldwide", lambda found: worldwide(found, urgent_care))) + (
                           (("virtual visits", virtual_visits),) if telehealth else ()):
        got = part(found)
        if got is None:
            drop(cited, f"the facts do not fully give the {name} part")
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


FITNESS_PROGRAMS = tuple((re.compile(pattern, re.I), name) for pattern, name in (
    (r"silver ?sneakers", "SilverSneakers"), (r"silver ?& ?fit", "Silver&Fit"), (r"\bone pass\b", "One Pass"),
    (r"renew active", "Renew Active")))


def fitness_program(got):
    """The fitness program the best source names, and the fact that names it."""
    for f in sorted(got, key=lambda f: RANK[f["source"]]):
        for pattern, name in FITNESS_PROGRAMS:
            if pattern.search(f["quotes"]):
                return name, [f]
    return None, []


def part_b_giveback(found):
    """["Part B giveback $70/month"] from the monthly Part B premium reduction, and its facts."""
    (value, cited), = giveback("", found)
    paid = [f for f in cited if f["cost_kind"] == "part_b_reduction"]
    if not paid:
        drop(cited, "it gives no amount")
        return [], []
    return [f"Part B giveback {value}" + (f"/{renews(paid)}" if renews(paid) else "")], paid


def wellness_bucks(found):
    """Shows a Wellness Bucks allowance that pays for fitness alone."""
    alt_care_pools = {f["pool"] for f in found if f["benefit"].startswith("extras.") and f["pool"]}
    bucks = top(exactly(found, ("fitness",), lambda f: everyone(f) and f["cost_kind"] == "allowance"
                        and re.search(r"wellness bucks", f["pool"], re.I) and f["pool"] not in alt_care_pools and every(f),
                        "it is not Wellness Bucks for fitness alone"))
    return ([f"Wellness Bucks {show(bucks)}/{renews(bucks)}"], bucks) if bucks and renews(bucks) else ([], [])


def named_extras(found, leaves, prices=False, programs=False, allowances=False):
    """Names each of fitness, meals and transportation in leaves that every member has. See extra_benefits for
    prices and programs. With allowances, a benefit without a copay shows its own allowance and how often it renews."""
    parts, cited = [], []
    for name, leaf in (("Fitness", "fitness"), ("Meals", "meals"), ("Transportation", "extras.transportation")):
        if leaf not in leaves:
            continue
        got = top(exactly(found, (leaf,), lambda f: extra(f) and offers(f),
                       "it is not a supplemental in-network benefit for every member"))
        if not got:
            continue
        program, naming = (fitness_program([f for f in found if f["benefit"] == leaf and extra(f) and offers(f)])
                           if programs and leaf == "fitness" else (None, []))
        if program:
            name = f"{name} {program}"
        copays = [f for f in got if f["cost_kind"] == "copay"]
        if prices and leaf != "extras.transportation" and copays:
            meals = top([f for f in found if f["benefit"] == leaf and extra(f) and offers(f)
                         and f["cost_kind"] == "visit_limit" and re.search(r"meal", f["unit"], re.I)])
            count = f", {min(int(f['amount']) for f in meals)} meals" if meals else ""
            parts.append(f"{name} {show(copays)}{count}")
            cited += copays + meals
        elif allowances and renews(own := [f for f in got if f["cost_kind"] == "allowance" and not f["pool"]]):
            parts.append(f"{name} {show(own)}/{renews(own)}")
            cited += own
        else:
            parts.append(name)
            cited += got
        cited += naming
    return parts, cited


def extra_benefits(organization, found, prices=False, programs=False, alike=False, part_b=False, anywhere=False,
                   part_d=False, fitness=True, steps=False):
    """Names fitness, meals and transportation for every member, then shows routine foot care, a fitness allowance,
    a card for members with chronic conditions, and the programs after a heart-failure hospital stay.
    With prices, it shows the fitness and meals copays and how many meals. With programs, it names the fitness program
    and then each other program for every member. With alike, it merges programs as other_programs does.
    With part_b, it starts with the Part B giveback. With part_d, it ends by saying when the plan has no Part D.
    Without fitness, it leaves fitness and Wellness Bucks to alt_care_otc_travel. See other_programs for anywhere and
    steps."""
    parts, cited = part_b_giveback(found) if part_b else ([], [])
    got = named_extras(found, ("fitness", "meals", "extras.transportation") if fitness else ("meals", "extras.transportation"),
                       prices, programs)
    parts += got[0]
    cited += got[1]
    if programs:
        got = other_programs(found, alike, anywhere, steps)
        parts += got[0]
        cited += got[1]
    got = foot_care(found)
    parts += got[0]
    cited += got[1]
    if fitness:
        got = wellness_bucks(found)
        parts += got[0]
        cited += got[1]
    else:
        drop([f for f in found if f["benefit"] == "fitness"], "Alternative Care / OTC / Travel shows fitness")
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
    without = exactly(found, ("part_d_deductible",), lambda f: f["cost_kind"] == "not_covered",
                      "it does not say the plan has no Part D") if part_d else []
    [(deductible, without)] = drug_deductible(organization, without) if without else [("", [])]
    if deductible == "n/a":
        parts.append("No Part D coverage")
        cited += without
    return [("; ".join(parts), unique(cited))]


HOURS = re.compile(r"\b24\W?hours?\b")


def program_name(pool):
    """The program's name without its kind, case, "24-hour" or a trailing "program", so two sources' names compare."""
    words = re.sub(r"\W+", " ", HOURS.sub("", pool.split(":")[-1].lower())).split()
    return " ".join(words[:-1] if words[-1:] == ["program"] else words)


def rewards(found, pools):
    """" ($50 for a check-up, $20 for a flu shot)" from the rewards the best source says a program pays for each step."""
    got = top([f for f in found if f["benefit"] == "other_supplemental" and f["pool"] in pools and extra(f)
               and f["cost_kind"] == "allowance" and f["condition"] and not CHRONIC.search(f["condition"])])
    steps = ", ".join(f"{show([f])} for {f['condition']}" for f in sorted(
        got, key=lambda f: (-max(map(facts.number, re.findall(r"\$[\d,.]+", f["amount"])), default=0), f["condition"])))
    return (f" ({steps})", got) if got else ("", [])


def other_programs(found, alike=False, anywhere=False, steps=False):
    """Names each other program for every member, with its price and how often an allowance renews. Each program's
    best source gives it, since a page may name only some programs. With alike, programs whose names match
    (program_name) are one program, shown by its best source's shortest name. With anywhere, it also names programs
    that only pay out of network, such as a travel benefit, with a yearly maximum when nothing else gives a price.
    With steps, a program without a price shows the rewards it pays for each step."""
    def ok(f):
        return everyone(dict(f, network="in") if anywhere else f) and f["pool"] and f["cost_kind"] in DOT_KINDS
    programs = exactly(found, ("other_supplemental",), ok, "it is not a named program that every member has")
    key = program_name if alike else (lambda pool: pool)
    shown = []
    for name in {key(f["pool"]) for f in programs}:
        named = [f for f in programs if key(f["pool"]) == name]
        named = [f for f in named if f["network"] != "out"] or named
        got = top(named)
        allowances = [f for f in got if f["cost_kind"] == "allowance"]
        priced = allowances or [f for f in got if f["cost_kind"] in PRICED]
        caps = top([f for f in named if f["cost_kind"] == "max" and renews([f])]) if anywhere and not priced else []
        price = f" {show(priced)}" if priced else f" max {show(caps)}" if caps else ""
        period = f"/{renews(allowances or caps)}" if (allowances or caps) and renews(allowances or caps) else ""
        priced = priced or caps
        label = min((f["pool"] for f in got), key=lambda pool: (len(pool), pool)).replace(chr(0x2011), "-")
        paid, earned = rewards(found, {f["pool"] for f in got}) if steps and not priced else ("", [])
        shown.append((label, f"{label}{price}{period}{paid}", (priced or got) + earned))
    shown.sort(key=lambda shown_: shown_[:2])
    return [part for _, part, _ in shown], [f for _, _, used in shown for f in used]


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


def narrow_limit(found, leaf, name):
    """The yearly limit that the best source's facts agree on for a narrow service, such as " 4/year", and its facts."""
    words = dict(NARROW)[name]
    limits = top([f for f in found if f["benefit"] == leaf and f["cost_kind"] == "visit_limit"
                  and extra(f) and words.search(f["condition"]) and how_often(f) == "year" and not PER_PART.search(f["limit"])])
    return (f" {limits[0]['amount']}/year", limits) if len({f["amount"] for f in limits}) == 1 else ("", [])


def dental_price(found, leaf, services=False, broad_services=False, limits=False):
    """The best source's prices, and how the cell shows them. It names the narrow services that all sources' prices
    name, without saying they are the only ones, since readers may miss some. With broad_services, it names none
    when the plan's own in-network price names a broader service. With limits, each narrow service shows its yearly
    limit. With services, a plan's own prices for several named services give the range when no price covers every
    service."""
    prices = exactly(found, (leaf,), lambda f: everyone(f) and f["cost_kind"] in PRICED,
                     "it is not a supplemental in-network price for every member")
    if services and not prices:
        each = top([f for f in found if f["benefit"] == leaf and f["cost_kind"] in PRICED and f["condition"]
                    and extra(f) and not f.get("packaged") and not re.search(r"\bmembers?\b", f["condition"], re.I)])
        if len({f["condition"] for f in each}) > 1:
            return each, "$0" if show(each) == "0%" else show(each).replace("0%-", "$0-")
    got = top(prices)
    shown = show(got)
    shown = "$0" if shown == "0%" else shown.replace("0%-", "$0-") if got else ""
    only = [] if broad_services and prices_broader(found, leaf) else narrow(prices)
    if not only:
        return got, shown
    named = [(name, *narrow_limit(found, leaf, name)) if limits else (name, "", []) for name in only]
    return got + [f for *_, used in named for f in used], f"{shown} for {', '.join(n + text for n, text, _ in named)}"


def prices_broader(found, leaf):
    """Whether one of the plan's own in-network prices for leaf, for every member, names a broader service."""
    return any(f["benefit"] == leaf and extra(f) and f["cost_kind"] in PRICED
               and not re.search(r"\bmembers?\b", f["condition"], re.I)
               and BROAD.search(f"{f['condition']} {f['quotes']}") for f in found)


def dental(organization, found, services=True, broad_services=False, limits=False):
    """Shows routine preventive and comprehensive dental prices and the maximum, naming the services that share it.
    A plan with only an allowance shows it. An allowance on a card shared with other benefits is not a maximum.
    Without routine dental, it cites a blank as the main sheet's dental column does. See dental_price for services."""
    prev, prev_shown = dental_price(found, "dental.preventive", services, broad_services, limits)
    comp, comp_shown = dental_price(found, "dental.comprehensive", services, broad_services, limits)
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


def plan_facts(data, document=None):
    """Each plan's facts. document replaces machine/document_facts.csv if given."""
    if document is None:
        document = facts.read(data / "machine/document_facts.csv")
    by_plan = collections.defaultdict(list)
    for f in document + facts.read(data / "generated/pbp_facts.csv"):
        by_plan[f["plan_id"]].append(f)
    return by_plan


def once(rule):
    """The rule, but two identical lines show once."""
    def one(organization, found):
        got = rule(organization, found)
        if len(got) == 2 and got[0][0] == got[1][0]:
            return [(got[0][0], unique(got[0][1] + got[1][1]))]
        return got
    return one


ANY_SETTING = OFFICES + ("outpatient_hospital",)


# Version 18 presents E-O and Z as SHIBA's final 2027 chart does. Version 29 shows every in-network price the documents
# give for these columns.
CHART_18 = {"L_xray_imaging": once(lambda o, found: xray_imaging(o, found, mammograms=False)),
            "I_outpatient_surgery": once(lambda o, found: outpatient_surgery(o, found, zero_low_ends=False)),
            "F_primary_care": once(visits("office.pcp")), "G_specialist": once(visits("office.specialist")),
            "K_tests_labs": lambda o, found: tests_labs(o, found, zero_tests=("AgeRight",), lab_settings=ANY_SETTING),
            "M_part_b_drugs": lambda o, found: part_b_drugs(o, found, highest=True)}
# A rule returns the lines of its column.
COLUMNS = {"L_xray_imaging": once(every_xray_and_imaging), "AB_ambulance": ambulance,
           "I_outpatient_surgery": once(outpatient_surgery),
           "F_primary_care": once(visits("office.pcp", telehealth=True)),
           "G_specialist": once(visits("office.specialist", telehealth=True)),
           "H_inpatient": lambda o, found: inpatient(o, found, per_stay="per admit"),
           "J_outpatient_rehab": lambda o, found: outpatient_rehab(o, found, settings=ANY_SETTING),
           "K_tests_labs": every_test_and_lab,
           "Z_part_b_reduction": lambda o, found: giveback(o, found, dot_only=True),
           "M_part_b_drugs": every_drug_price,
           "O_medical_deductible": lambda o, found: medical_deductible(o, found, chart_wording=True),
           "S_acupuncture": dot("extras.acupuncture"), "T_chiropractic": dot("extras.chiropractic"),
           "V_massage": dot("extras.massage"), "X_transportation": dot("extras.transportation"),
           "R_dental": dot("dental.preventive", "dental.comprehensive"), "U_naturopath": dot("extras.naturopathy"),
           "P_vision": dot("vision.exam", "vision.eyewear"), "Q_hearing": dot("hearing.exam", "hearing.aids"),
           "W_fitness": dot("fitness"), "Y_otc": dot("otc"), "AA_opt_packages": packages, "C_premium": plan_premium,
           "D_premium_full_extra_help": extra_help_premium, "E_moop": once(moop), "N_pharmacy_deductible": drug_deductible}


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


DENTAL_OON = out_of_network(("PREV", "dental.preventive"), ("COMP", "dental.comprehensive"))
VISION_OON = out_of_network(("exam", "vision.exam"), ("eyewear", "vision.eyewear"))
HEARING_OON = out_of_network(("exam", "hearing.exam"), ("aids", "hearing.aids"))
HEARING_OON_31 = out_of_network(("exam", "hearing.exam"), ("fitting", "hearing.exam", VISITS[0][1]), ("aids", "hearing.aids"))
DVHA = {"C_premium": plan_premium, "D_premium_full_extra_help": extra_help_premium,
        "E_optional_packages": lambda o, found: optional_packages(o, found, details=False),
        "F_dental": or_none(with_lacking(with_packages(with_details(
            lambda o, found: dental(o, found, broad_services=True, limits=True),
            no_maximum, dental_deductible, dental_rollover, dental_reimbursement,
            lambda found: dental_exclusions(found, summary_first=True), DENTAL_OON, preventive_limits,
            provider_network("dental"))), ("no COMP", "dental.comprehensive")), "dental"),
        "G_vision": or_none(with_lacking(with_packages(with_details(
            vision, exam_max, eyewear_pairs, VISION_OON, provider_network("vision"))),
            ("no eyewear allowance", "vision.eyewear")), "vision"),
        "H_hearing": dvha_hearing(exam_renews=True, details=(lambda found: hearing_details(found, rechargeable=True),),
                                  oon=HEARING_OON_31),
        "I_alt_care_otc_travel": lambda o, found: alt_care_otc_travel(o, found, telehealth=True, food=True, rates=True,
                                                                      none=True, urgent_care=True, details=True,
                                                                      fitness=True, fitness_allowance=True),
        "J_extra_benefits": lambda o, found: extra_benefits(o, found, prices=True, programs=True, alike=True,
                                                            part_b=True, anywhere=True, part_d=True, fitness=False,
                                                            steps=True)}
DVHA_LEAVES = {"C_premium": ("plan_premium",), "D_premium_full_extra_help": ("plan_premium", "part_d_deductible"),
               "E_optional_packages": ("packages",), "F_dental": ("dental",),
               "G_vision": ("vision",), "H_hearing": ("hearing",),
               "I_alt_care_otc_travel": ("extras.acupuncture", "extras.chiropractic", "extras.massage",
                                         "extras.naturopathy", "otc", "emergency", "fitness"),
               "J_extra_benefits": ("giveback", "fitness", "meals", "foot_care", "extras.transportation",
                                    "other_supplemental", "part_d_deductible")}
SHEETS = {"main": (COLUMNS, LEAVES), "dvha": (DVHA, DVHA_LEAVES)}


def cell(sheet, column, plan_id):
    """A cell's key in a version's held cells."""
    return (column if sheet == "main" else f"{sheet}.{column}", plan_id)


def related(f, leaves):
    return any(facts.covers(f["benefit"], leaf) or facts.covers(leaf, f["benefit"]) for leaf in leaves)


# A reason explain() gives only if a filter set a fact aside without noting why. A test keeps it from happening.
UNNOTED = "no filter recorded a reason"


def explain(organization, found, column, sheet="main", version=None):
    """(lines, set_aside): the rule's lines, and {identity: reasons} for each fact for a benefit in LEAVES that the
    rule did not use."""
    token = _reasons.set({})
    try:
        got = rule(sheet, column, version or max(VERSIONS))(organization, found)
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
    """Whether a line's cited facts give it a citation."""
    return any(f["source"] in facts.DOCUMENTS for f in cited)


def plans(data):
    return sheets.rows(data / "generated" / "plans.csv")


def dental_before_25(organization, found):
    return dental(organization, found, services=False)


# Each column's earlier rules, by the version that replaced each.
EARLIER_RULES = {
    ("dvha", "E_optional_packages"): ((17, lambda o, found: optional_packages(o, found, allowances=False)),
                                      (19, optional_packages)),
    ("dvha", "F_dental"): ((19, dental_before_25), (21, with_packages(with_details(dental_before_25, dental_deductible, DENTAL_OON))),
                           (22, with_packages(with_details(dental_before_25, dental_deductible, DENTAL_OON, preventive_limits))),
                           (24, or_none(with_lacking(with_packages(with_details(
                               dental_before_25, dental_deductible, DENTAL_OON, preventive_limits)),
                               ("no COMP", "dental.comprehensive")), "dental")),
                           (25, or_none(with_lacking(with_packages(with_details(
                               dental_before_25, no_maximum, dental_deductible, DENTAL_OON, preventive_limits)),
                               ("no COMP", "dental.comprehensive")), "dental")),
                           (26, or_none(with_lacking(with_packages(with_details(
                               dental, no_maximum, dental_deductible, DENTAL_OON, preventive_limits)),
                               ("no COMP", "dental.comprehensive")), "dental")),
                           (31, or_none(with_lacking(with_packages(with_details(
                               dental, no_maximum, dental_deductible, DENTAL_OON, preventive_limits,
                               provider_network("dental"))), ("no COMP", "dental.comprehensive")), "dental")),
                           (32, or_none(with_lacking(with_packages(with_details(
                               dental, no_maximum, dental_deductible, dental_rollover, dental_reimbursement,
                               dental_exclusions, DENTAL_OON, preventive_limits, provider_network("dental"))),
                               ("no COMP", "dental.comprehensive")), "dental")),
                           (34, or_none(with_lacking(with_packages(with_details(
                               dental, no_maximum, dental_deductible, dental_rollover, dental_reimbursement,
                               lambda found: dental_exclusions(found, summary_first=True), DENTAL_OON, preventive_limits,
                               provider_network("dental"))),
                               ("no COMP", "dental.comprehensive")), "dental")),
                           (35, or_none(with_lacking(with_packages(with_details(
                               lambda o, found: dental(o, found, broad_services=True),
                               no_maximum, dental_deductible, dental_rollover, dental_reimbursement,
                               lambda found: dental_exclusions(found, summary_first=True), DENTAL_OON, preventive_limits,
                               provider_network("dental"))), ("no COMP", "dental.comprehensive")), "dental"))),
    ("dvha", "G_vision"): ((19, vision), (22, with_packages(with_details(vision, VISION_OON))),
                           (24, or_none(with_lacking(with_packages(with_details(vision, VISION_OON)),
                                                     ("no eyewear allowance", "vision.eyewear")), "vision")),
                           (27, or_none(with_lacking(with_packages(with_details(
                               vision, eyewear_pairs, VISION_OON, provider_network("vision"))),
                               ("no eyewear allowance", "vision.eyewear")), "vision"))),
    ("dvha", "H_hearing"): (
        (19, hearing), (22, with_packages(with_details(lambda o, found: hearing(o, found, each_price=True), HEARING_OON))),
        (23, dvha_hearing()), (31, dvha_hearing(exam_renews=True, details=(hearing_details,)))),
    ("dvha", "I_alt_care_otc_travel"): (
        (19, alt_care_otc_travel), (20, lambda o, found: alt_care_otc_travel(o, found, telehealth=True)),
        (22, lambda o, found: alt_care_otc_travel(o, found, telehealth=True, food=True)),
        (23, lambda o, found: alt_care_otc_travel(o, found, telehealth=True, food=True, rates=True, none=True)),
        (24, lambda o, found: alt_care_otc_travel(o, found, telehealth=True, food=True, rates=True, none=True,
                                                  urgent_care=True)),
        (28, lambda o, found: alt_care_otc_travel(o, found, telehealth=True, food=True, rates=True, none=True,
                                                  urgent_care=True, details=True)),
        (30, lambda o, found: alt_care_otc_travel(o, found, telehealth=True, food=True, rates=True, none=True,
                                                  urgent_care=True, details=True, fitness=True))),
    ("dvha", "J_extra_benefits"): (
        (19, extra_benefits), (20, lambda o, found: extra_benefits(o, found, prices=True)),
        (21, lambda o, found: extra_benefits(o, found, prices=True, programs=True)),
        (22, lambda o, found: extra_benefits(o, found, prices=True, programs=True, alike=True)),
        (27, lambda o, found: extra_benefits(o, found, prices=True, programs=True, alike=True, part_b=True)),
        (28, lambda o, found: extra_benefits(o, found, prices=True, programs=True, alike=True, part_b=True,
                                             anywhere=True, part_d=True)),
        (31, lambda o, found: extra_benefits(o, found, prices=True, programs=True, alike=True, part_b=True,
                                             anywhere=True, part_d=True, fitness=False)))} | {
    ("main", column): ((18, rule),) + (((29, CHART_18[column]),) if column in CHART_18 else ()) for column, rule in {
        "E_moop": moop, "F_primary_care": visits("office.pcp"), "G_specialist": visits("office.specialist"),
        "H_inpatient": inpatient, "I_outpatient_surgery": outpatient_surgery, "J_outpatient_rehab": outpatient_rehab,
        "K_tests_labs": tests_labs, "L_xray_imaging": xray_imaging, "M_part_b_drugs": part_b_drugs,
        "O_medical_deductible": medical_deductible, "Z_part_b_reduction": giveback}.items()}


def rule(sheet, column, version):
    for since, earlier in EARLIER_RULES.get((sheet, column), ()):
        if version < since:
            return earlier
    return SHEETS[sheet][0][column]


def lines(data, column, document=None, sheet="main", version=None):
    """{plan_id: [(value, cited facts), ...]} for each plan. See plan_facts for document."""
    found, column_rule = plan_facts(data, document), rule(sheet, column, version or current(data))
    return {p["plan_id"]: column_rule(p["organization"], found[p["plan_id"]]) for p in plans(data)}


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
# Version 16 holds no cell.
VERSIONS[16] = {}
# Version 17 holds no cell. It shows an optional package's eyewear and hearing aid allowances.
VERSIONS[17] = {}
# Version 18 holds no cell. It presents main columns as the final chart does.
VERSIONS[18] = {}
# Version 19 holds no cell. It shows what a package gives in each benefit's own column, lists each hearing aid copay,
# and adds out-of-network prices, the dental deductible, fitness and meals prices, and virtual visit prices.
VERSIONS[19] = {}
# Version 20 holds no cell. It names the fitness program and each other program for every member, and says when the
# OTC allowance also pays for food.
VERSIONS[20] = {}
# Version 21 holds no cell. It shows how often the plan covers each preventive dental service, and shows a program
# once when two sources name it differently.
VERSIONS[21] = {}
# Version 22 holds no cell. It says when a plan has none of a benefit, adds the Part B giveback to extra benefits, and
# shows an allowance that alternative care shares with dental and the services' price.
VERSIONS[22] = {}
# Version 23 holds no cell. It shows worldwide urgent care, how often the hearing exam renews, hearing aid fittings and
# follow-ups, and the trial, warranty and batteries that come with an aid.
VERSIONS[23] = {}
# Version 24 shows allowance rollover, what the OTC card also pays for, eyewear pairs, the vision network and "no annual
# max" on the DVHA sheet.
VERSIONS[24] = {}
# Version 25 shows a DVHA dental price range from per-service prices when no price covers every service.
VERSIONS[25] = {}
# Version 26 names the DVHA dental network.
VERSIONS[26] = {}
# Version 27 shows a DVHA eye exam maximum, out-of-network travel programs such as Medicare Explorer, and
# "No Part D coverage".
VERSIONS[27] = {}
# Version 28 moves DVHA fitness from Extra Benefits to Alternative Care / OTC / Travel, as the volunteer sheet has it.
VERSIONS[28] = {}
# Version 29 shows every in-network price for main columns F, G, I, K, L and M.
VERSIONS[29] = {}
# Version 30 shows a DVHA fitness allowance, such as ATRIO's gym reimbursement.
VERSIONS[30] = {}
# Version 31 shows a program's rewards per step, rechargeable hearing aids, out-of-network hearing aid fittings, and
# dental rollover, reimbursement and exclusions.
VERSIONS[31] = {}
# Version 32 takes dental exclusions from the Summary of Benefits when it lists them.
VERSIONS[32] = {}
# Version 33 writes caveats.
VERSIONS[33] = {}
CAVEATS_SINCE = 33
# Version 34 names no narrow DVHA comprehensive dental services when the plan's own in-network price names a broader one.
VERSIONS[34] = {}
# Version 35 shows a narrow DVHA comprehensive dental service's yearly limit.
VERSIONS[35] = {}
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


PRICE = re.compile(r"\$[\d,]+(?:\.\d+)?|\d+(?:\.\d+)?%")


def prices(found):
    return {(a.startswith("$"), facts.number(a)) for a in amounts(found) if PRICE.fullmatch(a)}


def where_stated(f):
    return f"{f['source']} page {f['page']}"


def genetic_labs(value, cited):
    """Names the prices in the labs range that only genetic tests give."""
    genetic = [f for f in cited if facts.covers("tests.genetic", f["benefit"]) and presents([f])]
    labs = prices([f for f in cited if kin(f["benefit"], "tests.lab") and not facts.covers("tests.genetic", f["benefit"])])
    named = [(price, givers[0]) for price in PRICE.findall(value.partition("/")[2])
             if (key := (price.startswith("$"), facts.number(price))) not in labs
             and (givers := [f for f in genetic if key in prices([f])])]
    if not named:
        return None
    priced_ = " and ".join(price for price, _ in named)
    verb = "are" if len(named) > 1 else "is"
    return f"In the labs range, the {priced_} {verb} for genetic testing ({where_stated(named[0][1])}).", named[0][1]


# A condition that reads as the end of "covers this only ...".
WHEN = re.compile(r"(?:immediately )?(?:after|following|when|if|while|during|within|upon|before)\b")


def conditional(value, cited):
    """Names the condition that keeps a blank dot cell's benefit from a dot."""
    for f in cited if not value else []:
        if WHEN.match(f["condition"]) and offers(dict(f, condition="")) and presents([f]):
            price = f" at {f['amount']}" if f["cost_kind"] in PRICED else ""
            return f"{where_stated(f)} covers this{price} only {f['condition']}.", f
    return None


CAVEATS = {("main", "K_tests_labs"): genetic_labs} | {("main", c): conditional for c, r in COLUMNS.items() if getattr(r, "dot", False)}


def caveats(sheet, column, value, cited, version):
    """(text, fact) explaining a line from the facts it cites, or None."""
    template = CAVEATS.get((sheet, column)) if version >= CAVEATS_SINCE else None
    return template(value, cited) if template else None


def presented_lines(data, version=None):
    """Yields (sheet, plan_id, column, line, value, facts) for each line a presented cell shows.
    A one-line cell's line is blank."""
    version = version or current(data)
    held_cells = held(data, version)
    for sheet, (rules, _) in SHEETS.items():
        for column in rules:
            for plan_id, got in lines(data, column, sheet=sheet, version=version).items():
                if cell(sheet, column, plan_id) in held_cells:
                    continue
                value = shown(got)
                got, one_line = got[:value.count(" | ") + 1], " | " not in value
                for n, (value, cited) in enumerate(got, 1):
                    yield sheet, plan_id, column, "" if one_line else str(n), value, cited


def cited_lines(data, version=None):
    """Like presented_lines, with only the document facts."""
    for *line, cited in presented_lines(data, version):
        yield *line, [f for f in cited if presents([f])]


def citation_rows(data, version=None):
    """Returns one row per line and cited document quote. A line that cites no document fact gets no row."""
    url = {d["sha256"]: d["url"] for d in sheets.rows(data / "generated" / "documents_checked.csv") if d["sha256"]}
    out = {}
    for sheet, plan_id, column, line, value, cited in cited_lines(data, version):
        row = dict(sheet=sheet, plan_id=plan_id, column=column, line=line, value=value)
        for f in cited:
            for quote in json.loads(f["quotes"]):
                full = dict(row, url=url[f["doc_sha"]], pdf_page=f["page"], quote=quote)
                out[tuple(full.values())] = full
    return sorted(out.values(), key=lambda r: tuple(r.values()))


def caveat_rows(data, version=None):
    """One note row per cell that a caveat explains, its lines' caveats joined."""
    version = version or current(data)
    url = {d["sha256"]: d["url"] for d in sheets.rows(data / "generated" / "documents_checked.csv") if d["sha256"]}
    out = {}
    for sheet, plan_id, column, _, value, cited in presented_lines(data, version):
        if got := caveats(sheet, column, value, cited, version):
            text, f = got
            if (sheet, plan_id, column) in out:
                out[sheet, plan_id, column]["comment"] += " " + text
                continue
            out[sheet, plan_id, column] = dict(sheet=sheet, plan_id=plan_id, column=column, kind="caveat", comment=text,
                                               url=url[f["doc_sha"]], pdf_page=f["page"], quote=json.loads(f["quotes"])[0])
    return list(out.values())


def cited_facts(data, version=None):
    """{(sheet, plan_id, column): fact_ids} of the document facts that each presented cell cites."""
    out = collections.defaultdict(set)
    for sheet, plan_id, column, _, _, cited in cited_lines(data, version):
        out[sheet, plan_id, column] |= {f["fact_id"] for f in cited}
    return out


def wrong_note_facts(tags, notes, cited):
    """The note_facts.csv rows that name no note, or a fact that the note's cell does not cite."""
    noted = {(n["sheet"], n["plan_id"], n["column"]) for n in notes}
    return [t for t in tags if (key := (t["sheet"], t["plan_id"], t["column"])) not in noted
            or t["fact_id"] not in cited.get(key, ())]


def write(data, version=None):
    """Writes the generated sheets and their citations."""
    for sheet, name in sheets.SHEETS.items():
        with open(data / "generated" / name, "w", newline="") as f:
            out = csv.DictWriter(f, ["section", "plan_id", "plan_name"] + list(fields.labels(sheet)))
            out.writeheader()
            out.writerows(sheet_rows(data, sheet, version))
    with open(data / sheets.PRESENTED, "w", newline="") as f:
        out = csv.DictWriter(f, sheets.COLUMNS, lineterminator="\n")
        out.writeheader()
        out.writerows(citation_rows(data, version))
    with open(data / sheets.CAVEATS, "w", newline="") as f:
        out = csv.DictWriter(f, sheets.NOTE_COLUMNS, lineterminator="\n")
        out.writeheader()
        out.writerows(caveat_rows(data, version))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    write(years.data_dir(int(sys.argv[1])))
