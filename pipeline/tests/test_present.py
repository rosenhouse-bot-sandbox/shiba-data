import csv, json, os, pathlib, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import built, expected, facts, fields, sheets, present, years

YEAR = 2027


def fact(benefit="imaging.xray", setting="any", amount="$25", source="EOC", **more):
    row = dict.fromkeys(facts.COLUMNS, "") | dict(plan_id="H1036-153-0", benefit=benefit, setting=setting, network="in",
                                                  covered_by="medicare", cost_kind="copay", amount=amount, source=source,
                                                  page="60", quotes='["q"]') | more
    if source == "PBP":
        row["page"] = ""
    return row


def values(organization, *found):
    return [value for value, _ in present.xray_imaging(organization, list(found))]


class BestTest(unittest.TestCase):
    def test_the_best_source_wins_then_the_most_specific_fact(self):
        eoc, sb = fact(amount="$10"), fact(amount="$20", source="SB")
        advanced = fact("imaging.diagnostic.advanced", amount="$300")
        mri = fact("imaging.diagnostic.advanced.mri", amount="$400")
        self.assertEqual(present.best([sb, eoc], "imaging.xray", "office.pcp"), [eoc])
        self.assertEqual(present.best([advanced, mri], "imaging.diagnostic.advanced.mri", "freestanding"), [mri])
        self.assertEqual(present.best([advanced, mri], "imaging.diagnostic.advanced.ct", "freestanding"), [advanced])

    def test_a_named_setting_beats_any_and_a_narrower_one_beats_both(self):
        office, pcp = fact(setting="office", amount="$5"), fact(setting="office.pcp", amount="$6")
        self.assertEqual(present.best([fact(), office], "imaging.xray", "office.pcp"), [office])
        self.assertEqual(present.best([fact(), office, pcp], "imaging.xray", "office.pcp"), [pcp])

    def test_skips_out_of_network_conditional_and_supplemental_facts(self):
        skipped = [fact(network="out"), fact(condition="QMB"), fact(covered_by="supplemental"),
                   fact(provider_tier="PLUS"), fact(package="Rider"), fact(cost_kind="covered", amount="")]
        self.assertEqual(present.best(skipped, "imaging.xray", "office.pcp"), [])


class RuleTest(unittest.TestCase):
    def test_uses_office_and_freestanding_prices(self):
        self.assertEqual(values("Devoted Health", fact(setting="office", amount="$25"),
                                fact(setting="outpatient_hospital", amount="$75"),
                                fact("imaging.diagnostic.advanced", "freestanding", "$100"),
                                fact("imaging.diagnostic.advanced", "office", "$200")), ["$25", "$100-$200"])

    def test_falls_back_to_outpatient_hospital(self):
        self.assertEqual(values("Aetna", fact(setting="outpatient_hospital", amount="$15")), ["$15", ""])

    def test_humana_x_rays_use_office_prices_only(self):
        self.assertEqual(values("Humana", fact(setting="office.pcp", amount="$0"),
                                fact(setting="office.specialist", amount="$30"),
                                fact(setting="freestanding", amount="$40"))[0], "$0-$30")

    def test_leaves_out_ultrasounds_nuclear_and_other_advanced_imaging(self):
        left_out = [fact(f"imaging.diagnostic.{leaf}", amount="$9") for leaf in ("ultrasound", "nuclear", "advanced.other")]
        self.assertEqual(values("Aetna", fact("imaging.diagnostic.advanced.ct", amount="$100"), *left_out)[1], "$100")

    def test_a_0_diagnostic_mammogram_starts_line_2_at_0_except_for_some_carriers(self):
        found = [fact("imaging.diagnostic.advanced", amount="$350"), fact("imaging.diagnostic.mammogram", amount="$0")]
        self.assertEqual(values("Aetna Medicare", *found)[1], "$0-$350")
        for organization in ("Kaiser Permanente", "Humana", "Devoted Health"):
            self.assertEqual(values(organization, *found)[1], "$350")

    def test_only_a_0_copay_mammogram_and_only_with_advanced_imaging(self):
        advanced = fact("imaging.diagnostic.advanced", amount="$350")
        for mammogram in (fact("imaging.diagnostic.mammogram", amount="0%", cost_kind="coinsurance"),
                          fact("imaging.diagnostic.mammogram", amount="$0-$50")):
            self.assertEqual(values("Aetna", advanced, mammogram)[1], "$350")
        self.assertEqual(values("Aetna", fact("imaging.diagnostic.mammogram", amount="$0"))[1], "")

    def test_formats_copays_coinsurance_and_alternatives(self):
        cases = [(["$0-$300"], "$0-$300"), (["20%"], "20%"), (["$0", "20%"], "$0-20%"), (["$0-$300", "20%"], "$0-20%"), (["$0 or $25"], "$0-$25"),
                 (["$1,250.50"], "$1,250.50"), (["10%", "20%"], "10%-20%")]
        for amounts, want in cases:
            with self.subTest(amounts):
                found = [fact(setting=s, amount=a, cost_kind="coinsurance" if a.endswith("%") else "copay")
                         for s, a in zip(("office", "freestanding"), amounts)]
                self.assertEqual(values("Aetna", *found)[0], want)

    def test_cites_the_winning_facts(self):
        winner = fact(setting="office", amount="$25")
        (_, cited), _ = present.xray_imaging("Aetna", [winner, fact(setting="office", source="SB")])
        self.assertEqual(cited, [winner])


def ambulance(*found):
    return [value for value, _ in present.ambulance("Aetna", list(found))]


def trip(benefit="ambulance.ground", amount="$300", **more):
    return fact(benefit, amount=amount, **{"cost_kind": "coinsurance" if amount.endswith("%") else "copay", **more})


class AmbulanceTest(unittest.TestCase):
    def test_line_1_spans_ground_and_air_trips_of_every_kind(self):
        self.assertEqual(ambulance(trip(amount="$250", condition="Emergency"), trip(amount="$0", condition="home treatment"),
                                   trip("ambulance.air", "20%"))[0], "$0-$250 or 20%")

    def test_line_1_skips_other_networks_supplemental_benefits_tiers_packages_and_deductibles(self):
        skipped = [trip(amount="$500", network="out"), trip(amount="$400", covered_by="supplemental"),
                   trip(amount="$0", provider_tier="PLUS"), trip(amount="$0", package="Rider"),
                   trip(amount="$990", cost_kind="deductible")]
        self.assertEqual(ambulance(trip(), *skipped)[0], "$300")

    def test_line_1_leaves_trips_abroad_to_line_2(self):
        self.assertEqual(ambulance(trip(), trip(amount="$500", setting="outside_us")), ["$300", "$500"])

    def test_the_best_source_wins_for_each_kind_of_trip(self):
        self.assertEqual(ambulance(trip(), trip(amount="$100", source="SB"), trip("ambulance.air", "$400", source="SB"))[0],
                         "$300-$400")

    def test_line_2_prices_trips_abroad_in_or_out_of_network(self):
        self.assertEqual(ambulance(trip(), trip("ambulance", "$325", setting="outside_us", network="out"))[1], "$325")

    def test_line_2_covered_abroad_costs_what_unconditional_trips_cost_here(self):
        self.assertEqual(ambulance(trip(), trip(amount="$0", condition="home treatment"),
                                   trip("ambulance", "", setting="outside_us", cost_kind="covered")), ["$0-$300", "$300"])

    def test_line_2_says_not_covered_when_the_document_excludes_care_abroad(self):
        self.assertEqual(ambulance(trip(), trip("ambulance", "", setting="outside_us", cost_kind="not_covered"))[1],
                         "not covered")

    def test_line_2_follows_the_eocs_word_on_emergency_care_abroad_when_no_fact_names_trips(self):
        excluded = trip("emergency", "", setting="outside_us", cost_kind="not_covered")
        covered = trip("emergency", "$90", setting="outside_us", covered_by="supplemental")
        self.assertEqual(ambulance(trip(), excluded)[1], "not covered")
        self.assertEqual(ambulance(trip(), covered)[1], "EOC unclear")
        self.assertEqual(ambulance(trip(), dict(covered, source="SB"))[1], "")
        self.assertEqual(ambulance(trip(), covered, trip("ambulance", "$500", setting="outside_us"))[1], "$500")
        self.assertEqual(present.ambulance("Aetna", [trip(), covered])[1], ("EOC unclear", [covered]))
        for aside in (dict(covered, condition="urgently needed services"), dict(covered, provider_tier="preferred"),
                      dict(covered, package="Travel"), dict(covered, setting="any"), dict(covered, benefit="urgent_care")):
            self.assertEqual(ambulance(trip(), aside)[1], "", aside)

    def test_line_2_takes_the_best_source_whatever_it_says(self):
        self.assertEqual(ambulance(trip(), trip("ambulance", "", setting="outside_us", cost_kind="not_covered"),
                                   trip("ambulance", "$500", setting="outside_us", source="SB"))[1], "not covered")

    def test_no_fact_leaves_a_line_blank(self):
        self.assertEqual(ambulance(trip()), ["$300", ""])
        self.assertEqual(ambulance(), ["", ""])

    def test_cites_the_facts_behind_each_line(self):
        here, abroad = trip(), trip("ambulance", "", setting="outside_us", cost_kind="covered")
        (_, line1), (_, line2) = present.ambulance("Aetna", [here, abroad])
        self.assertEqual((line1, line2), ([here], [abroad, here]))


def surgery(*found):
    return [value for value, _ in present.outpatient_surgery("Aetna", list(found))]


def op(benefit="surgery", setting="outpatient_hospital", amount="$500", **more):
    return fact(benefit, setting, amount, **{"cost_kind": "coinsurance" if amount.endswith("%") else "copay", **more})


class OutpatientSurgeryTest(unittest.TestCase):
    def test_line_1_is_the_outpatient_hospital_and_line_2_the_surgical_center(self):
        self.assertEqual(surgery(op(), op(setting="asc", amount="20%")), ["$500", "20%"])

    def test_a_cost_for_any_setting_fills_both_lines(self):
        self.assertEqual(surgery(op(setting="any")), ["$500", "$500"])

    def test_a_0_diagnostic_colonoscopy_or_skin_biopsy_starts_its_settings_line_at_0(self):
        self.assertEqual(surgery(op(), op(setting="asc", amount="$400"), op("surgery.colonoscopy", "asc", "$0")),
                         ["$500", "$0-$400"])
        self.assertEqual(surgery(op(amount="20%"), op("surgery.skin_biopsy", amount="$0")), ["$0-20%", ""])

    def test_only_a_0_copay_starts_a_line_at_0_and_only_with_a_surgery_cost(self):
        self.assertEqual(surgery(op(), op("surgery.colonoscopy", amount="$100"), op("surgery.skin_biopsy", amount="0%")),
                         ["$500", ""])
        self.assertEqual(surgery(op("surgery.colonoscopy", amount="$0")), ["", ""])

    def test_a_0_colonoscopy_counts_only_where_the_document_prices_that_setting(self):
        self.assertEqual(surgery(op(), op(setting="asc", amount="$400"), op("surgery.colonoscopy", "any", "$0")),
                         ["$500", "$400"])

    def test_a_0_colonoscopy_from_a_lesser_source_still_counts(self):
        self.assertEqual(surgery(op(setting="asc", amount="20%"), op("surgery.colonoscopy", "asc", "$0", source="SB")),
                         ["", "$0-20%"])

    def test_a_lesser_sources_0_low_end_at_the_setting_starts_its_line_at_0(self):
        self.assertEqual(surgery(op(setting="any", amount="$250"), op(amount="$0-$300", source="SB")), ["$0-$250", "$250"])

    def test_only_a_0_low_end_at_that_very_setting_counts(self):
        self.assertEqual(surgery(op(setting="any", amount="$250"), op(amount="$50-$300", source="SB"),
                                 op(setting="any", amount="$0-$300", source="SB")), ["$250", "$250"])

    def test_a_flat_0_out_of_network_0_low_end_or_0_low_end_for_a_procedure_does_not_count(self):
        self.assertEqual(surgery(op(setting="any", amount="$250"), op(amount="$0", source="SB"),
                                 op(amount="$0-$300", source="SB", network="out"),
                                 op("surgery.colonoscopy", amount="$0-$300", source="SB")), ["$250", "$250"])

    def test_cites_a_low_end_once(self):
        cost = op(amount="$0-$250")
        self.assertEqual([cited for _, cited in present.outpatient_surgery("Aetna", [cost])], [[cost], []])

    def test_an_out_of_network_0_colonoscopy_does_not_count(self):
        self.assertEqual(surgery(op(), op("surgery.colonoscopy", amount="$0", network="out")), ["$500", ""])

    def test_a_better_sources_colonoscopy_price_beats_a_0(self):
        self.assertEqual(surgery(op(), op("surgery.colonoscopy", amount="$100"),
                                 op("surgery.colonoscopy", amount="$0", source="SB")), ["$500", ""])

    def test_skips_other_networks_supplemental_benefits_tiers_packages_conditions_and_deductibles(self):
        skipped = [op(amount="$900", network="out"), op(amount="$800", covered_by="supplemental"),
                   op(amount="$0", provider_tier="PLUS"), op(amount="$0", package="Rider"), op(amount="$0", condition="x"),
                   op(amount="$990", cost_kind="deductible")]
        self.assertEqual(surgery(op(), *skipped), ["$500", ""])

    def test_the_best_source_wins(self):
        self.assertEqual(surgery(op(), op(amount="$100", source="SB")), ["$500", ""])

    def test_cites_the_facts_behind_each_line(self):
        cost, zero = op(setting="asc"), op("surgery.colonoscopy", "asc", "$0")
        self.assertEqual([cited for _, cited in present.outpatient_surgery("Aetna", [cost, zero])], [[], [cost, zero]])


def priced(benefit, setting="any", amount="$0", **more):
    return fact(benefit, setting, amount, **{"cost_kind": "coinsurance" if amount.endswith("%") else "copay", **more})


def tests_labs(organization, *found):
    return present.tests_labs(organization, list(found))[0][0]


class TestsLabsTest(unittest.TestCase):
    def test_office_prices_only(self):
        found = [priced("tests.diagnostic", "office.pcp"), priced("tests.diagnostic", "office.specialist", "$30"),
                 priced("tests.diagnostic", "urgent_care", "$40"), priced("tests.diagnostic", "outpatient_hospital", "$100"),
                 priced("tests.lab", "freestanding")]
        self.assertEqual(tests_labs("Aetna", *found), "$0-$30/$0")

    def test_one_plan_keeps_its_hospital_sleep_study(self):
        found = [priced("tests.diagnostic", "office.pcp"), priced("tests.lab", "freestanding"),
                 priced("tests.diagnostic.sleep_study", "outpatient_hospital", "$140")]
        self.assertEqual(tests_labs("Humana", *found), "$0/$0")
        self.assertEqual(tests_labs("Humana", *[dict(f, plan_id="H1036-306-0") for f in found]), "$0-$140/$0")

    def test_a_0_colonoscopy_or_mammogram_counts_as_a_test_for_some_carriers(self):
        for zero in (priced("surgery.colonoscopy", "outpatient_hospital"), priced("imaging.diagnostic.mammogram")):
            found = [priced("tests.diagnostic", amount="20%"), zero, priced("tests.lab")]
            self.assertEqual(tests_labs("AgeRight Advantage", *found), "$0-20%/$0")
            self.assertEqual(tests_labs("UnitedHealthcare", *found), "20%/$0")
        self.assertEqual(tests_labs("Regence", priced("tests.diagnostic", amount="$10"),
                                    priced("imaging.diagnostic.mammogram", amount="$20")), "$10/")

    def test_a_price_for_some_tests_counts_but_one_for_some_members_does_not(self):
        found = [priced("tests.diagnostic", amount="$35"), priced("tests.diagnostic", condition="certain tests"),
                 priced("tests.lab", amount="20%"), priced("tests.lab", condition="QMB members")]
        self.assertEqual(tests_labs("Aetna", *found), "$0-$35/20%")
        for condition in ("full Medicaid", "Extra Help", "members who are eligible", "dual-eligible"):
            self.assertEqual(tests_labs("Aetna", priced("tests.lab", amount="20%"), priced("tests.lab", condition=condition)),
                             "/20%", condition)

    def test_skips_supplemental_tiered_and_packaged_prices(self):
        for more in (dict(covered_by="supplemental"), dict(provider_tier="preferred"), dict(package="Rider")):
            self.assertEqual(tests_labs("Aetna", priced("tests.lab", amount="20%"), priced("tests.lab", **more)), "/20%", more)

    def test_a_0_colonoscopy_adds_nothing_without_a_test_price(self):
        self.assertEqual(tests_labs("Regence", priced("imaging.diagnostic.mammogram"), priced("tests.lab", amount="$5")), "/$5")

    def test_leaves_out_genetic_testing(self):
        found = [priced("tests.lab"), priced("tests.lab", amount="$10", setting="freestanding"),
                 priced("tests.genetic", amount="$50"), priced("tests.diagnostic")]
        self.assertEqual(tests_labs("Wellcare", *found), "$0/$0-$10")

    def test_falls_back_to_outpatient_hospital_prices(self):
        self.assertEqual(tests_labs("Aetna", priced("tests.lab", "outpatient_hospital", "$0 or $40")), "/$0-$40")

    def test_no_facts_leave_the_line_blank(self):
        self.assertEqual(present.tests_labs("Aetna", []), [("", [])])


def visits(setting, *found):
    return [value for value, _ in present.visits(setting)("Aetna", list(found))]


class VisitsTest(unittest.TestCase):
    def test_line_2_is_out_of_network_when_the_plan_prices_it(self):
        self.assertEqual(visits("office.pcp", priced("visits", "office.pcp")), ["$0", ""])
        self.assertEqual(visits("office.pcp", priced("visits", "office.pcp"),
                                priced("visits", "office.pcp", "50%", network="out")), ["$0", "50%"])

    def test_each_column_takes_its_own_office(self):
        found = [priced("visits", "office.pcp", "$5"), priced("visits", "office.specialist", "$45")]
        self.assertEqual((visits("office.pcp", *found), visits("office.specialist", *found)), (["$5", ""], ["$45", ""]))
        self.assertEqual(visits("office.specialist", priced("visits", "office", "$35")), ["$35", ""])

    def test_telehealth_and_conditional_prices_give_way(self):
        found = [priced("visits", "office.specialist", "$65"), priced("visits", "telehealth", "$0-$65"),
                 priced("visits", "office.specialist", condition="received in a nursing home")]
        self.assertEqual(visits("office.specialist", *found), ["$65", ""])

    def test_a_cost_for_every_network_fills_both_lines(self):
        self.assertEqual(visits("office.specialist", priced("visits", amount="$45", network="any"),
                                priced("visits", "office.pcp", "$10", network="out")), ["$45", "$45"])

    def test_keeps_specialist_tiers_and_skips_packages(self):
        self.assertEqual(visits("office.specialist", priced("visits", "office.specialist", provider_tier="cardiologist"),
                                priced("visits", "office.specialist", "$20", provider_tier="all other")), ["$0-$20", ""])
        self.assertEqual(visits("office.specialist", priced("visits", "office.specialist", "$45", package="A")), ["", ""])

    def test_only_a_priced_out_of_network_visit_adds_line_2(self):
        for other in (priced("rehab.physical", "office.pcp", "50%", network="out"),
                      priced("visits", "office.pcp", "50%", network="out", package="A"),
                      priced("visits", "office.pcp", "", network="out", cost_kind="covered"),
                      priced("visits", "office.pcp", "50%", network="out", covered_by="supplemental")):
            self.assertEqual(visits("office.pcp", priced("visits", "office.pcp"), other), ["$0", ""], other)

    def test_each_line_prefers_its_own_network_over_any(self):
        found = [priced("visits", "office.pcp", "$10", network="any"), priced("visits", "office.pcp", "$5"),
                 priced("visits", "office.pcp", "40%", network="out")]
        self.assertEqual(visits("office.pcp", *found), ["$5", "40%"])


def rehab(*found):
    return present.outpatient_rehab("Aetna", list(found))[0][0]


class OutpatientRehabTest(unittest.TestCase):
    def test_office_and_freestanding_prices_over_ground_and_speech_therapy(self):
        self.assertEqual(rehab(priced("rehab.physical", "office.specialist", "$20"),
                               priced("rehab.physical", "outpatient_hospital", "$50"),
                               priced("rehab.occupational", "freestanding", "$40"),
                               priced("rehab.speech", "office.specialist", "$20")), "$20-$40")

    def test_leaves_out_reevaluations(self):
        self.assertEqual(rehab(priced("rehab.physical", amount="$40"), priced("rehab.reevaluation")), "$40")

    def test_falls_back_to_outpatient_hospital_prices(self):
        self.assertEqual(rehab(priced("rehab.physical", "outpatient_hospital", "$50")), "$50")

    def test_one_cost_for_all_therapy(self):
        self.assertEqual(rehab(priced("rehab", amount="30%"), priced("rehab", amount="$0", condition="QMB")), "30%")

    def test_cites_a_fact_once_however_many_settings_it_fills(self):
        therapy = priced("rehab.physical", amount="$40")
        self.assertEqual(present.outpatient_rehab("Aetna", [therapy]), [("$40", [therapy])])


def stay(amount, limit="", unit="per day", benefit="inpatient.acute", **more):
    return priced(benefit, amount=amount, unit=unit, limit=limit, **{"condition": limit, **more})


def inpatient(*found):
    return [value for value, _ in present.inpatient("Aetna", list(found))]


class InpatientTest(unittest.TestCase):
    def test_a_daily_cost_and_its_days(self):
        self.assertEqual(inpatient(stay("$465", "days 1-5"), stay("$0", "days 6+")), ["$465", "1-5"])
        self.assertEqual(inpatient(stay("$600", "days 1-4"), stay("$0", "days 5-90")), ["$600", "1-4"])
        self.assertEqual(inpatient(stay("$0-$100", "days 1-5")), ["$0-$100", "1-5"])

    def test_a_paid_tier_without_an_end_runs_on(self):
        self.assertEqual(inpatient(stay("$300", "days 1-3"), stay("$100", "days 4+")), ["$100-$300", "1+"])

    def test_days_need_a_daily_cost_and_a_whole_range(self):
        for more in (dict(unit="per stay"), dict(limit="days 0-5"), dict(limit="days 1"), dict(limit="up to days 1-5")):
            self.assertIsNone(present.days(stay("$300", **{"limit": "days 1-5", **more})), more)

    def test_two_paid_tiers_span_their_days(self):
        self.assertEqual(inpatient(stay("$300", "days 1-3"), stay("$100", "days 4-6"), stay("$0", "days 7+")),
                         ["$100-$300", "1-6"])

    def test_a_cost_per_stay_is_per_admission(self):
        self.assertEqual(inpatient(stay("$2,241", unit="per stay")), ["$2,241 per admission", ""])

    def test_skips_out_of_network_and_psychiatric_stays(self):
        self.assertEqual(inpatient(stay("$550", "days 1-5"), stay("$680", "days 1-16", network="out"),
                                   stay("$300", "days 1-3", benefit="inpatient.psychiatric")), ["$550", "1-5"])

    def test_skips_a_stay_for_some_members(self):
        self.assertEqual(inpatient(stay("$1,980", unit="per stay"), stay("$0", unit="per stay", condition="full Medicaid")),
                         ["$1,980 per admission", ""])

    def test_a_cost_without_days(self):
        self.assertEqual(inpatient(stay("$0", unit="per stay")), ["$0 per admission", ""])
        self.assertEqual(inpatient(stay("$250", unit="")), ["$250", ""])
        self.assertEqual(inpatient(), ["", ""])


def column(rule, *found):
    return rule("Aetna", list(found))


class GivebackTest(unittest.TestCase):
    def test_the_best_source_gives_the_reduction(self):
        eoc, sb = (priced("giveback", amount="$154.20", cost_kind="part_b_reduction", source=s) for s in ("EOC", "SB"))
        self.assertEqual(column(present.giveback, sb, eoc), [("$154.20", [eoc])])

    def test_an_unconditioned_reduction_wins(self):
        found = [priced("giveback", amount="$90", cost_kind="part_b_reduction"),
                 priced("giveback", amount="$0", cost_kind="part_b_reduction", condition="if Medicaid pays your premium")]
        self.assertEqual(column(present.giveback, *found)[0][0], "$90")

    def test_a_reduction_without_an_amount_is_a_dot(self):
        self.assertEqual(column(present.giveback, priced("giveback", amount="", cost_kind="covered"))[0][0], "●")

    def test_skips_packages_and_other_benefits(self):
        found = [priced("giveback", amount="$50", cost_kind="part_b_reduction", package="Rider"),
                 priced("giveback", amount="$50", cost_kind="part_b_reduction", provider_tier="preferred"), priced("visits")]
        self.assertEqual(column(present.giveback, *found), [("", [])])


class PartBDrugsTest(unittest.TestCase):
    def test_a_0_vaccine_starts_the_range_at_0(self):
        found = [priced("part_b_drugs.vaccine"), priced("part_b_drugs.chemotherapy", amount="20%"),
                 priced("part_b_drugs", amount="20%"), priced("part_b_drugs.insulin", amount="$35")]
        self.assertEqual(column(present.part_b_drugs, *found)[0][0], "0%-20%")
        self.assertEqual(column(present.part_b_drugs, *found[1:])[0][0], "20%")

    def test_each_kind_of_drug_takes_its_best_source(self):
        found = [priced("part_b_drugs", amount="20%"), priced("part_b_drugs", amount="30%", source="SB"),
                 priced("part_b_drugs.allergy", source="SB")]
        self.assertEqual(column(present.part_b_drugs, *found), [("0%-20%", [found[0], found[2]])])

    def test_keeps_conditions_but_skips_other_networks_tiers_and_supplements(self):
        found = [priced("part_b_drugs", amount="20%", condition="Depending on your level of Medicaid eligibility"),
                 priced("part_b_drugs", amount="50%", network="out"), priced("part_b_drugs", provider_tier="preferred"),
                 priced("part_b_drugs", covered_by="supplemental"), priced("part_b_drugs", amount="0%-20%", package="A")]
        self.assertEqual(column(present.part_b_drugs, *found)[0][0], "20%")

    def test_ranges_and_no_facts(self):
        self.assertEqual(column(present.part_b_drugs, priced("part_b_drugs", amount="0%-20%"))[0][0], "0%-20%")
        self.assertEqual(column(present.part_b_drugs, priced("part_b_drugs.insulin", amount="$35")), [("", [])])


def deductible(amount, benefit="medical_deductible", **more):
    return priced(benefit, amount=amount, cost_kind="deductible", **more)


class MedicalDeductibleTest(unittest.TestCase):
    def test_none_shows_0(self):
        self.assertEqual(column(present.medical_deductible, deductible("$0"),
                                deductible("$0", condition="If you receive Extra Help"))[0][0], "$0")

    def test_some_services_from_any_source(self):
        self.assertEqual(column(present.medical_deductible, deductible("$250", "medical_deductible.some"))[0][0], "$250 some")
        self.assertEqual(column(present.medical_deductible, deductible("$250"))[0][0], "$250")
        found = [deductible("$200"), deductible("$200", "medical_deductible.some", source="SB")]
        self.assertEqual(column(present.medical_deductible, *found), [("$200 some", found)])

    def test_original_medicares_part_b_deductible(self):
        found = [deductible("$283", "medical_deductible.some"),
                 priced("medical_deductible.part_b", amount="", cost_kind="covered", source="SB")]
        self.assertEqual(column(present.medical_deductible, *found), [("Part B deductible some", found)])
        uncovered = dict(found[1], cost_kind="not_covered")
        self.assertEqual(column(present.medical_deductible, found[0], uncovered), [("$283 some", [found[0]])])

    def test_a_part_b_deductible_needs_no_amount(self):
        part_b = priced("medical_deductible.part_b", amount="", cost_kind="covered", source="SB")
        applies = priced("medical_deductible.some", amount="", cost_kind="covered", source="PBP")
        self.assertEqual(column(present.medical_deductible, applies, part_b), [("Part B deductible some", [applies, part_b])])
        self.assertEqual(column(present.medical_deductible, applies), [("", [])])

    def test_out_of_network_only_when_none_in_network(self):
        self.assertEqual(column(present.medical_deductible, deductible("$100", "medical_deductible.some", network="out"))[0][0],
                         "$100 some out-of-network services")
        self.assertEqual(column(present.medical_deductible, deductible("$100", network="out"))[0][0], "$100 out-of-network only")
        self.assertEqual(column(present.medical_deductible, deductible("$700", "medical_deductible.some"),
                                deductible("$1,000", "medical_deductible.some", network="out"))[0][0], "$700 some")

    def test_0_in_network_hides_an_out_of_network_deductible(self):
        self.assertEqual(column(present.medical_deductible, deductible("$0"), deductible("$100", network="out"))[0][0], "$0")

    def test_skips_supplemental_conditional_tiered_and_packaged_deductibles(self):
        for more in (dict(covered_by="supplemental"), dict(condition="for Extra Help members"),
                     dict(provider_tier="preferred"), dict(package="Rider")):
            self.assertEqual(column(present.medical_deductible, deductible("$500", "medical_deductible.some", **more),
                                    deductible("$250"))[0][0], "$250", more)

    def test_other_benefits_deductibles_and_no_facts(self):
        self.assertEqual(column(present.medical_deductible, deductible("$200", "tests.diagnostic")), [("", [])])


def extra(benefit, covered_by="supplemental", cost_kind="covered", amount="", **more):
    return priced(benefit, amount=amount, covered_by=covered_by, cost_kind=cost_kind, **more)


class DotTest(unittest.TestCase):
    def test_a_routine_benefit_or_fund_gets_a_dot(self):
        for f in (extra("extras.acupuncture", cost_kind="copay", amount="$0"), extra("extras.acupuncture", pool="Wellness Bucks"),
                  extra("extras.acupuncture", cost_kind="allowance", amount="$150", pool="Flex Card"),
                  extra("extras", cost_kind="visit_limit", amount="12"),
                  extra("extras.acupuncture", cost_kind="max", amount="$500")):
            self.assertEqual(column(present.dot("extras.acupuncture"), f), [("●", [f])], f)

    def test_a_medicare_package_conditional_or_uncovered_benefit_cites_a_blank(self):
        for f in (extra("extras.acupuncture", "medicare", condition="chronic low back pain"),
                  extra("extras.acupuncture", package="Advantage Plus"),
                  extra("extras.transportation", condition="immediately following an inpatient hospitalization"),
                  extra("extras.chiropractic", cost_kind="not_covered", source="SB"),
                  extra("extras.chiropractic", cost_kind="copay", amount="$20", provider_tier="preferred")):
            self.assertEqual(column(present.dot(f["benefit"]), f), [("", [f])], f)

    def test_takes_the_best_source_and_its_own_benefit(self):
        eoc, sb = extra("extras.massage", "medicare"), extra("extras.massage", cost_kind="not_covered", source="SB")
        self.assertEqual(column(present.dot("extras.massage"), eoc, sb), [("", [eoc])])
        self.assertEqual(column(present.dot("extras.acupuncture"), extra("extras.massage")), [("", [])])
        self.assertEqual(column(present.dot("extras.chiropractic"), extra("extras.chiropractic", network="out")), [("", [])])

    def test_any_of_several_benefits_gets_a_dot(self):
        medicare, cleaning = extra("dental", "medicare", "copay", "$50"), extra("dental.preventive", cost_kind="copay", amount="$0")
        dental = present.dot("dental.preventive", "dental.comprehensive")
        self.assertEqual(column(dental, medicare, cleaning), [("●", [cleaning])])
        crown = extra("dental.comprehensive", cost_kind="coinsurance", amount="50%")
        self.assertEqual(column(dental, medicare, crown), [("●", [crown])])
        self.assertEqual(column(dental, medicare), [("", [medicare])])


class CaveatTest(unittest.TestCase):
    def test_names_the_lab_price_that_only_a_genetic_test_gives(self):
        lab, genetic = priced("tests.lab", amount="$10"), priced("tests.genetic", amount="20%", page="86")
        self.assertEqual(present.genetic_labs("$0/$10 or 20%", [lab, genetic]),
                         ("In the labs range, the 20% is for genetic testing (EOC page 86).", genetic))
        self.assertEqual(present.genetic_labs("$0/$0-$50", [priced("tests.lab"), priced("tests.genetic", amount="$50")])[0],
                         "In the labs range, the $50 is for genetic testing (EOC page 60).")

    def test_no_lab_caveat_when_a_lab_also_gives_the_price_or_it_is_a_test_price(self):
        genetic = priced("tests.genetic", amount="$50")
        self.assertIsNone(present.genetic_labs("$0/$50", [priced("tests.lab", amount="$50"), genetic]))
        self.assertIsNone(present.genetic_labs("$50/$0", [priced("tests.diagnostic", amount="$50"), priced("tests.lab"), genetic]))
        self.assertIsNone(present.genetic_labs("$0/$0", [priced("tests.lab")]))

    def test_no_lab_caveat_when_a_broader_test_or_a_cms_lab_fact_gives_the_price(self):
        genetic = priced("tests.genetic", amount="20%")
        self.assertIsNone(present.genetic_labs("$0/$0 or 20%", [priced("tests", amount="20%"), genetic]))
        self.assertIsNone(present.genetic_labs("$0/$0 or 20%", [priced("tests.lab", amount="20%", source="PBP"), genetic]))
        self.assertIsNone(present.genetic_labs("$0/$0 or 20%", [priced("tests.lab"), dict(genetic, source="PBP")]))

    def test_names_every_price_only_genetic_tests_give(self):
        self.assertEqual(present.genetic_labs("$0/$0-$50 or 20%", [priced("tests.lab"), priced("tests.genetic", amount="$50"),
                                                                    priced("tests.genetic", amount="20%")])[0],
                         "In the labs range, the $50 and 20% are for genetic testing (EOC page 60).")

    def test_names_the_condition_of_a_blank_dot_cells_benefit(self):
        ride = extra("extras.transportation", cost_kind="copay", amount="$0", page="99",
                     condition="immediately following an inpatient hospitalization")
        self.assertEqual(present.conditional("", [ride]),
                         ("EOC page 99 covers this at $0 only immediately following an inpatient hospitalization.", ride))
        covered = dict(ride, cost_kind="covered", amount="")
        self.assertEqual(present.conditional("", [covered])[0],
                         "EOC page 99 covers this only immediately following an inpatient hospitalization.")

    def test_no_condition_caveat_for_a_dot_or_a_benefit_members_cannot_get_for_a_condition_alone(self):
        ride = extra("extras.transportation", cost_kind="copay", amount="$0", condition="after a hospital stay")
        self.assertIsNone(present.conditional("●", [ride]))
        for f in (dict(ride, condition=""), dict(ride, covered_by="medicare"), dict(ride, package="Advantage Plus"),
                  dict(ride, cost_kind="not_covered", amount=""), dict(ride, condition="provider network"),
                  dict(ride, condition="Available for people with chronic low back pain"), dict(ride, source="PBP")):
            self.assertIsNone(present.conditional("", [f]), f)

    def test_a_cells_caveats_make_one_note_from_its_first_caveats_fact(self):
        ride = extra("extras.transportation", cost_kind="copay", amount="$0", condition="after a stay", doc_sha="d",
                     quotes='["Rides", "$0"]')
        lines = [("main", "H1-001-0", "X_transportation", "1", "", [ride]),
                 ("main", "H1-001-0", "X_transportation", "2", "", [dict(ride, condition="after surgery", page="7")])]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(present, "presented_lines", lambda data, version: lines):
            os.makedirs(f"{tmp}/generated")
            pathlib.Path(tmp, "generated/documents_checked.csv").write_text("sha256,url\nd,https://eoc\n")
            self.assertEqual(present.caveat_rows(pathlib.Path(tmp), 33), [dict(
                sheet="main", plan_id="H1-001-0", column="X_transportation", kind="caveat",
                comment="EOC page 60 covers this at $0 only after a stay. EOC page 7 covers this at $0 only after surgery.",
                url="https://eoc", pdf_page="60", quote="Rides")])

    @built.check
    def test_the_rules_write_the_caveats_that_replaced_notes(self):
        rows = {(r["plan_id"], r["column"]): r["comment"] for r in sheets.rows(years.data_dir(YEAR) / sheets.CAVEATS)}
        self.assertEqual(rows[("H2923-001-0", "K_tests_labs")], "In the labs range, the 20% is for genetic testing (EOC page 86).")
        self.assertRegex(rows[("H9003-006-0", "X_transportation")], r"^EOC page 99 covers this at \$0 only immediately following")

    def test_versions_before_33_write_no_caveats(self):
        ride = extra("extras.transportation", cost_kind="copay", amount="$0", condition="after a hospital stay")
        self.assertEqual(present.caveats("main", "X_transportation", "", [ride], 32), None)
        self.assertEqual(present.caveats("main", "X_transportation", "", [ride], 33)[1], ride)
        self.assertIsNone(present.caveats("dvha", "J_extra_benefits", "", [ride], 33))


class PackagesTest(unittest.TestCase):
    def test_a_package_premium_gets_a_dot(self):
        for benefit in ("packages", "dental"):
            sold = extra(benefit, cost_kind="premium", amount="$54", package="Advantage Plus")
            self.assertEqual(column(present.packages, sold, extra("packages", cost_kind="not_covered", source="SB")),
                             [("●", [sold])], benefit)

    def test_none_for_sale_cites_a_blank(self):
        none = extra("packages", cost_kind="not_covered")
        self.assertEqual(column(present.packages, none, extra("dental", cost_kind="premium", amount="$5")), [("", [none])])
        self.assertEqual(column(present.packages, extra("packages", cost_kind="premium", amount="$54", package="Plus",
                                                        network="out")), [("", [])])


class PlanPremiumTest(unittest.TestCase):
    def test_the_best_source_gives_the_premium_in_dollars(self):
        eoc, sb = (priced("plan_premium", amount="$69.00", cost_kind="premium", source=s) for s in ("EOC", "SB"))
        self.assertEqual(column(present.plan_premium, sb, eoc), [("$69", [eoc])])
        self.assertEqual(column(present.plan_premium, eoc, dict(eoc, amount="$69")), [("$69", [eoc, dict(eoc, amount="$69")])])

    def test_skips_conditional_package_tiered_and_other_kinds_of_premiums(self):
        found = [priced("plan_premium", amount="$5", cost_kind="copay"),
                 priced("plan_premium", amount="$7", cost_kind="premium", provider_tier="Tier 1"),
                 priced("plan_premium", amount="$0", cost_kind="premium", condition="with Extra Help"),
                 priced("plan_premium", amount="$9", cost_kind="premium", package="Rider")]
        self.assertEqual(column(present.plan_premium, *found), [("", [])])

    def test_two_premiums_from_the_best_source_present_nothing(self):
        found = [priced("plan_premium", amount=a, cost_kind="premium") for a in ("$10", "$20")]
        self.assertEqual(column(present.plan_premium, *found), [("", [])])


def landscape(benefit, cost_kind, amount="", **more):
    return fact(benefit, amount=amount, cost_kind=cost_kind, source="Landscape", network="any", page="", **more)


class ExtraHelpPremiumTest(unittest.TestCase):
    def test_shows_the_premium_with_full_extra_help(self):
        full = landscape("plan_premium", "premium", "$28.50", condition="full Extra Help")
        found = [landscape("plan_premium", "premium", "$69"), full]
        self.assertEqual(column(present.extra_help_premium, *found), [("$28.50", [full])])

    def test_shows_na_without_part_d(self):
        none = landscape("part_d_deductible", "not_covered")
        self.assertEqual(column(present.extra_help_premium, landscape("plan_premium", "premium", "$0"), none),
                         [("n/a", [none])])

    def test_skips_a_package_premium(self):
        rider = landscape("plan_premium", "premium", "$9", condition="full Extra Help", package="Rider")
        self.assertEqual(column(present.extra_help_premium, rider), [("", [])])


class MoopTest(unittest.TestCase):
    def test_shows_the_in_network_maximum(self):
        inn = fact("moop", amount="$6,700", cost_kind="out_of_pocket_max", source="PBP")
        self.assertEqual(column(present.moop, inn), [("$6,700", [inn])])

    def test_adds_the_combined_maximum_as_a_second_line(self):
        inn = fact("moop", amount="$6,700", cost_kind="out_of_pocket_max", source="PBP")
        both = dict(inn, network="any", amount="$10,100")
        self.assertEqual(column(present.moop, both, inn), [("$6,700", [inn]), ("$10,100", [both])])

    def test_keeps_an_empty_first_line_for_a_combined_maximum_alone(self):
        both = fact("moop", amount="$10,100", cost_kind="out_of_pocket_max", source="PBP", network="any")
        self.assertEqual(column(present.moop, both), [("", []), ("$10,100", [both])])

    def test_skips_a_conditional_or_tiered_maximum(self):
        for more in ({"condition": "dual eligible"}, {"provider_tier": "Tier 2"}):
            inn = fact("moop", amount="$3,000", cost_kind="out_of_pocket_max", source="PBP", **more)
            self.assertEqual(column(present.moop, inn), [("", [])])


class DrugDeductibleTest(unittest.TestCase):
    def test_names_the_tiers_the_deductible_skips(self):
        ded = landscape("part_d_deductible", "deductible", "$685", condition="not tiers 1,2")
        self.assertEqual(column(present.drug_deductible, ded), [("$685 not tiers 1,2", [ded])])

    def test_shows_a_deductible_without_tiers_alone(self):
        for amount in ("$0", "$590"):
            ded = landscape("part_d_deductible", "deductible", amount)
            self.assertEqual(column(present.drug_deductible, ded), [(amount, [ded])])

    def test_shows_no_tiers_when_facts_disagree_on_them(self):
        found = [landscape("part_d_deductible", "deductible", "$685", condition=c) for c in ("not tiers 1", "not tiers 1,2")]
        self.assertEqual(column(present.drug_deductible, *found), [("$685", found)])

    def test_skips_the_deductible_with_extra_help(self):
        ded = landscape("part_d_deductible", "deductible", "$700", condition="not tiers 1,2,3")
        helped = landscape("part_d_deductible", "deductible", "$0", condition="If you receive Extra Help")
        self.assertEqual(column(present.drug_deductible, ded, helped), [("$700 not tiers 1,2,3", [ded])])

    def test_skips_a_package_deductible(self):
        ded = landscape("part_d_deductible", "deductible", "$100", package="Rider")
        self.assertEqual(column(present.drug_deductible, ded), [("", [])])

    def test_shows_na_without_part_d(self):
        none = landscape("part_d_deductible", "not_covered")
        self.assertEqual(column(present.drug_deductible, none), [("n/a", [none])])


def routine(benefit, cost_kind="copay", amount="$0", **more):
    return priced(benefit, covered_by="supplemental", cost_kind=cost_kind, amount=amount, **more)


class AllowanceDetailsTest(unittest.TestCase):
    def test_names_the_vision_network_by_its_shortest_name_or_abbreviation(self):
        network = present.provider_network("vision")
        vsp = routine("vision", "covered", "", condition="provider network", limit="Vision Service Plan (VSP)")
        insight = routine("vision", "covered", "", condition="provider network", limit="Humana Medicare Insight Network")
        self.assertEqual(network([vsp]), ("VSP network", [vsp]))
        self.assertEqual(network([insight, dict(insight, limit="Humana Medicare Insight Network for vision")]),
                         ("Humana Medicare Insight Network", [insight]))
        for other in (dict(vsp, package="Plus"), dict(vsp, benefit="dental"), dict(vsp, condition=""),
                      dict(vsp, network="out"), dict(vsp, covered_by="medicare"), dict(vsp, cost_kind="not_covered")):
            self.assertEqual(network([other]), ("", []), other)
        eyemed = dict(vsp, limit="EyeMed", source="SB")
        self.assertEqual(network([insight, eyemed]), ("Humana Medicare Insight Network", [insight]))

    def test_says_whether_an_allowance_rolls_over_until_year_end(self):
        no = routine("otc", "not_covered", "", condition="rollover")
        yes = routine("otc", "covered", "", condition="rollover", limit="to the next month until the end of the plan year")
        self.assertEqual(present.rollover([no], "otc"), ("no rollover", [no]))
        self.assertEqual(present.rollover([yes], "otc"), ("rolls over until year-end", [yes]))
        for unclear in ([dict(yes, limit="after the initial point of sale")], [yes, no], [dict(no, package="Plus")]):
            self.assertEqual(present.rollover(unclear, "otc"), ("", []), unclear)

    def test_counts_pairs_of_glasses_and_says_whether_an_eyewear_allowance_rolls_over(self):
        allowance = routine("vision.eyewear", "allowance", "$150", limit="per year")
        pairs = routine("vision.eyewear", "visit_limit", "1", condition="glasses", limit="every 2 years")
        no = routine("vision.eyewear", "not_covered", "", condition="rollover")
        self.assertEqual(present.eyewear_pairs([allowance, pairs, no]), ("1 pair/two years; no rollover", [pairs, no]))
        self.assertEqual(present.eyewear_pairs([pairs, dict(pairs, amount="2", limit="per year")])[0], "")
        self.assertEqual(present.eyewear_pairs([dict(pairs, amount="2", limit="per year")])[0], "2 pairs/year")
        self.assertEqual(present.eyewear_pairs([no]), ("", []))

    def test_shows_a_routine_exam_maximum_that_renews(self):
        cap = routine("vision.exam", "max", "$75", limit="per year")
        self.assertEqual(present.exam_max([cap]), ("exam max $75/year", [cap]))
        for other in (dict(cap, limit=""), dict(cap, provider_tier="PLUS"), dict(cap, cost_kind="allowance"),
                      dict(cap, network="out"), dict(cap, benefit="vision.eyewear")):
            self.assertEqual(present.exam_max([other]), ("", []), other)

    def test_says_no_annual_maximum_only_without_a_maximum(self):
        none = routine("dental", "covered", "", condition="no annual maximum")
        self.assertEqual(present.no_maximum([none]), ("no annual max", [none]))
        self.assertEqual(present.no_maximum([none, routine("dental", "max", "$1,000", limit="per year")]), ("", []))
        self.assertEqual(present.no_maximum([none, routine("dental", "max", "$1,000", condition="diabetes")]),
                         ("no annual max", [none]))
        self.assertEqual(present.no_maximum([dict(none, cost_kind="not_covered")]), ("", []))

    def test_otc_says_rollover_and_what_else_the_card_pays_for(self):
        card = routine("otc", "allowance", "$175", limit="per month", quotes='["groceries"]')
        yes = routine("otc", "covered", "", condition="rollover", limit="to the next month until the end of the year")
        safety = routine("otc", "covered", "", condition="also pays for", limit="home and bath safety devices")
        food = routine("otc", "covered", "", condition="also pays for members with chronic conditions", limit="Food")
        self.assertEqual(present.over_the_counter([card], food=True, details=True), (["OTC and food $175/month"], [card]))
        self.assertEqual(present.over_the_counter([card, yes, safety, food, dict(food, limit="food")], food=True, details=True),
                         (["OTC $175/month (rolls over until year-end; also for home and bath safety devices; "
                           "also for Food for some members)"], [card, yes, safety, food, dict(food, limit="food")]))
        self.assertEqual(present.over_the_counter([card, yes, safety], food=True), (["OTC and food $175/month"], [card]))
        self.assertEqual(present.over_the_counter([card, safety], food=True, details=True)[0],
                         ["OTC and food $175/month (also for home and bath safety devices)"])
        self.assertEqual(present.over_the_counter([card, safety, dict(safety, condition="also pays for members")],
                                                  details=True)[0],
                         ["OTC $175/month (also for home and bath safety devices)"])
        self.assertEqual(present.over_the_counter([card, dict(safety, cost_kind="not_covered")], details=True)[0],
                         ["OTC $175/month"])

    def test_otc_leaves_out_uses_that_name_a_benefit_sharing_the_card(self):
        card = routine("otc", "allowance", "$20", limit="per month", pool="card")
        dental = routine("dental", "allowance", "$20", limit="per month", pool="card")
        uses = routine("otc", "covered", "", condition="also pays for", limit="dental, vision and hearing services")
        self.assertEqual(present.over_the_counter([card, dental, uses], details=True)[0],
                         ["OTC from $20/month card shared with dental"])
        self.assertEqual(present.over_the_counter([card, uses], details=True)[0],
                         ["OTC $20/month (also for dental, vision and hearing services)"])


class VisionTest(unittest.TestCase):
    def test_exam_and_eyewear_cite_the_facts_that_say_how_often_they_renew(self):
        found = [routine("vision.exam"), routine("vision.exam", "visit_limit", "1", limit="every year"),
                 routine("vision.eyewear", "allowance", "$150", limit="every 2 calendar years")]
        self.assertEqual(column(present.vision, *found), [("exam $0/year; eyewear $150/two years", found)])

    def test_renews_only_as_the_best_source_says(self):
        found = [routine("vision.exam"), routine("vision.exam", "visit_limit", "1", limit="every other year"),
                 routine("vision.eyewear", "allowance", "$90"),
                 routine("vision.eyewear", "visit_limit", "1", limit="every year", source="SB", page="2"),
                 routine("vision.eyewear", "visit_limit", "1", limit="every 2 years")]
        self.assertEqual(column(present.vision, *found)[0][0], "exam $0; eyewear $90/two years")

    def test_a_tier_of_providers_adds_its_allowance(self):
        found = [routine("vision.eyewear", "max", "$50"), routine("vision.eyewear", "max", "$100", provider_tier="PLUS** Provider")]
        self.assertEqual(column(present.vision, *found)[0][0], "eyewear $50 ($100 at PLUS providers)")
        self.assertEqual(column(present.vision, found[1]), [("", [])])

    def test_some_carriers_allow_frames_or_contacts_and_cite_a_0_lens_copay(self):
        found = [routine("vision.eyewear", "allowance", "$100"), routine("vision.eyewear")]
        self.assertEqual(present.vision("Regence BlueCross", found), [("frames or contacts $100; lenses $0", found)])
        self.assertEqual(present.vision("Regence BlueCross", found[:1])[0][0], "frames or contacts $100")

    def test_skips_medicare_conditional_tiered_package_and_pooled_benefits(self):
        found = [priced("vision.exam"), routine("vision.exam", condition="diabetes"),
                 routine("vision.exam", provider_tier="PLUS"),
                 routine("vision.eyewear", "allowance", "$175", package="Advantage Plus"),
                 routine("vision", "allowance", "$20", pool="Spendables")]
        self.assertEqual(column(present.vision, *found), [("", [])])


class HearingTest(unittest.TestCase):
    def test_exam_aid_copays_and_the_fewest_aids_a_limit_allows(self):
        found = [routine("hearing.exam"), routine("hearing.aids", amount="$499 or $699 or $999", unit="per aid"),
                 routine("hearing.aids", "visit_limit", "2", limit="per year"),
                 routine("hearing.aids", "visit_limit", "4", limit="")]
        self.assertEqual(column(present.hearing, *found), [("exam $0; aids $499-$999; 2 aids/year", found)])

    def test_a_limit_of_1_aid_per_ear_means_2_aids(self):
        found = [routine("hearing.aids", amount="$499", unit="per aid"),
                 routine("hearing.aids", "visit_limit", "1", unit="per ear", limit="per calendar year")]
        self.assertEqual(column(present.hearing, *found), [("aids $499; 2 aids/year", found)])

    def test_with_exam_renews_the_exam_says_how_often_its_best_source_renews_it(self):
        exam, yearly = routine("hearing.exam"), routine("hearing.exam", "visit_limit", "1", limit="every year")
        sb = routine("hearing.exam", "visit_limit", "1", limit="every 2 years", source="SB")
        rule = lambda o, found: present.hearing(o, found, exam_renews=True)
        self.assertEqual(column(rule, exam, yearly, sb), [("exam $0/year", [exam, yearly])])
        self.assertEqual(column(rule, exam), [("exam $0", [exam])])
        self.assertEqual(column(rule, yearly), [("", [])])
        self.assertEqual(column(present.hearing, exam, yearly), [("exam $0", [exam])])

    def test_hearing_details_show_fittings_follow_ups_and_what_comes_with_an_aid(self):
        fitting = routine("hearing.exam", condition="fitting/evaluation")
        fittings = routine("hearing.exam", "visit_limit", "1", condition="fitting/evaluation", limit="per year")
        follow_ups = routine("hearing.exam", condition="follow-up visits", source="SB")
        three = routine("hearing.exam", "visit_limit", "3", condition="follow-up visits",
                        limit="during the first year following a hearing aid purchase")
        trial = routine("hearing.aids", "covered", "", condition="trial period", limit="60 days")
        warranty = routine("hearing.aids", "covered", "", condition="warranty", limit="3 years")
        batteries = routine("hearing.aids", "covered", "", condition="batteries", limit="80 batteries per aid")
        found = [fitting, fittings, follow_ups, three, trial, warranty, batteries]
        self.assertEqual(present.hearing_details(found), (
            "fitting $0 1 visit/year; follow-ups $0 3 visits in the first year after buying an aid; "
            "60-day trial, 3-year warranty, 80 batteries per aid", found))

    def test_hearing_details_count_unlimited_visits_and_describe_batteries(self):
        unlimited = routine("hearing.exam", "covered", "", condition="fitting/evaluation",
                            limit="unlimited visits for the first 12 months")
        batteries = routine("hearing.aids", "covered", "", condition="batteries",
                            limit="3 years of batteries per non-rechargeable aid (up to 60 cells per ear per year)")
        self.assertEqual(present.hearing_details([unlimited, batteries]), (
            "fitting unlimited visits in the first year after buying an aid; 3 years of batteries", [unlimited, batteries]))
        models = dict(batteries, limit="80 batteries per aid for non-rechargeable models")
        self.assertEqual(present.hearing_details([models])[0], "80 batteries per aid")
        self.assertEqual(present.hearing_details([dict(batteries, limit="a supply of batteries")])[0], "batteries")
        self.assertEqual(present.hearing_details([dict(batteries, limit="3 years per non-rechargeable aid")])[0],
                         "3 years of batteries")

    def test_hearing_details_take_the_best_source_and_skip_what_it_does_not_agree_on(self):
        fitting = routine("hearing.exam", condition="fitting/evaluation")
        eoc = routine("hearing.exam", "visit_limit", "1", condition="fitting/evaluation", limit="per year")
        sb = dict(eoc, amount="2", source="SB")
        self.assertEqual(present.hearing_details([fitting, eoc, sb]), ("fitting $0 1 visit/year", [fitting, eoc]))
        self.assertEqual(present.hearing_details([fitting, eoc, dict(eoc, amount="2", page="61")]),
                         ("fitting $0", [fitting]))
        warranty = routine("hearing.aids", "covered", "", condition="warranty", limit="3 years")
        self.assertEqual(present.hearing_details([warranty, dict(warranty, limit="1 year", source="SB")])[0],
                         "3-year warranty")
        self.assertEqual(present.hearing_details([warranty, dict(warranty, limit="1 year", page="61")])[0], "")
        self.assertEqual(present.hearing_details([dict(warranty, limit="36 months")]), ("", []))

    def test_hearing_details_skip_other_networks_packages_and_services(self):
        fitting = routine("hearing.exam", condition="fitting/evaluation")
        trial = routine("hearing.aids", "covered", "", condition="trial period", limit="60 days")
        skipped = [dict(fitting, network="out", cost_kind="coinsurance", amount="80%"), dict(trial, package="Rider"),
                   routine("hearing.aids", "not_covered", "", condition="batteries"),
                   routine("hearing.exam", condition="balance evaluation", amount="$50"),
                   routine("hearing.aids", "covered", "", condition="warranty", limit="")]
        self.assertEqual(present.hearing_details(skipped), ("", []))

    def test_an_allowance_per_ear_wins_over_a_copay_and_means_2_aids(self):
        found = [routine("hearing.aids", "allowance", "$500", unit="per ear", limit="every 3 calendar years"),
                 routine("hearing.aids", unit="per ear")]
        self.assertEqual(column(present.hearing, *found),
                         [("aids allowance $500 per ear/three years; 2 aids/three years", [found[0]])])

    def test_a_price_per_aid_or_for_both_ears_counts_no_aids(self):
        found = [routine("hearing.aids", "allowance", "$1,600", unit="for both ears combined", limit="every 2 years")]
        self.assertEqual(column(present.hearing, *found)[0][0], "aids allowance $1,600/two years")
        self.assertEqual(column(present.hearing, routine("hearing.aids", amount="$499", unit="per aid"))[0][0], "aids $499")

    def test_counts_aids_only_beside_a_price(self):
        self.assertEqual(column(present.hearing, routine("hearing.aids", "visit_limit", "2", limit="per year")), [("", [])])

    def test_skips_medicare_tiered_and_pooled_benefits(self):
        found = [priced("hearing.exam", amount="$40"), routine("hearing.aids", "allowance", "$175", pool="Healthy Options"),
                 routine("hearing.aids", "allowance", "$900", provider_tier="Premier")]
        self.assertEqual(column(present.hearing, *found), [("", [])])


    def test_lists_each_aid_copay_per_aid(self):
        found = [routine("hearing.exam"), routine("hearing.aids", amount="$499 or $699 or $999", unit="per aid"),
                 routine("hearing.aids", "visit_limit", "2", limit="per year")]
        self.assertEqual(present.hearing("", found, each_price=True)[0][0],
                         "exam $0; aids $499 or $699 or $999 per aid; 2 aids/year")
        for amount, unit, want in (("$0", "", "aids $0"), ("$699 or $499", "per ear", "aids $499 or $699 per aid; 2 aids"),
                                   ("$399-$699", "per aid", "aids $399-$699"), ("$500 or $900", "per pair", "aids $500-$900"),
                                   ("$0 or 20%", "per aid", "aids $0-20%")):
            got = present.hearing("", [routine("hearing.aids", amount=amount, unit=unit)], each_price=True)[0][0]
            self.assertEqual(got, want)


class OptionalPackagesTest(unittest.TestCase):
    def test_each_package_shows_its_premium_and_yearly_dental_max(self):
        found = [routine("packages", "premium", "$50.90", package="MyOption DEN972", unit="per month"),
                 routine("dental", "max", "$1,500", package="MyOption DEN972", limit="per calendar year"),
                 routine("dental", "max", "$100", package="MyOption DEN972", unit="per incident")]
        self.assertEqual(column(present.optional_packages, *found), [("MyOption DEN972 $50.90/mo, max $1,500", found[:2])])

    def test_a_package_with_other_benefits_says_dental_max(self):
        found = [routine("packages", "premium", "$54", package="Advantage Plus"),
                 routine("dental", "max", "$1,500", package="Advantage Plus", limit="per year"),
                 routine("vision.exam", "copay", "$0", package="Advantage Plus")]
        self.assertEqual(column(present.optional_packages, *found)[0][0], "Advantage Plus $54/mo, dental max $1,500")

    def test_a_package_shows_its_eyewear_and_hearing_aid_allowances(self):
        found = [routine("packages", "premium", "$54", package="Advantage Plus"),
                 routine("dental", "max", "$1,500", package="Advantage Plus", limit="per year"),
                 routine("vision.eyewear", "allowance", "$175", package="Advantage Plus", limit="every 2 calendar-year period"),
                 routine("hearing.aids", "allowance", "$500", package="Advantage Plus", unit="per ear", limit="every 3 years"),
                 routine("hearing.aids", "copay", "$0", package="Advantage Plus")]
        self.assertEqual(column(present.optional_packages, *found), [(
            "Advantage Plus $54/mo, dental max $1,500, eyewear $175/two years, hearing aids $500 per ear/three years",
            found[:4])])
        self.assertEqual(present.optional_packages("", found, allowances=False)[0][0],
                         "Advantage Plus $54/mo, dental max $1,500")

    def test_the_best_source_gives_the_premium_and_the_max(self):
        found = [routine("packages", "premium", "$40", package="Rider", source="SB", page="2"),
                 routine("packages", "premium", "$45", package="Rider"),
                 routine("dental", "max", "$900", package="Rider", limit="per year", source="SB", page="2"),
                 routine("dental", "max", "$1,000", package="Rider", limit="per year")]
        self.assertEqual(column(present.optional_packages, *found), [("Rider $45/mo, max $1,000", [found[1], found[3]])])

    def test_skips_out_of_network_conditional_and_medicare_packages_and_one_without_a_premium(self):
        found = [routine("packages", "premium", "$9", package="Out", network="out"),
                 routine("packages", "premium", "$9", package="Some", condition="diabetes"),
                 priced("packages", amount="$9", cost_kind="premium", package="Medicare"),
                 routine("dental", "premium", "$9", package="Dental only")]
        self.assertEqual(column(present.optional_packages, *found), [("", [])])

    def test_a_document_that_says_none_are_sold_cites_a_blank_unless_one_is(self):
        none = routine("packages", "not_covered", "")
        self.assertEqual(column(present.optional_packages, none), [("", [none])])
        sold = routine("packages", "premium", "$9", package="Rider")
        self.assertEqual(column(present.optional_packages, none, sold), [("Rider $9/mo", [sold])])

    def test_several_packages_are_separated_by_semicolons(self):
        found = [routine("packages", "premium", a, package=n) for a, n in (("$9", "A"), ("$8", "B"))]
        self.assertEqual(column(present.optional_packages, *found)[0][0], "A $9/mo; B $8/mo")


    def test_names_only_each_package_and_its_premium(self):
        found = [routine("packages", "premium", "$54", package="Advantage Plus"),
                 routine("dental", "max", "$1,500", package="Advantage Plus", limit="per year")]
        self.assertEqual(present.optional_packages("", found, details=False), [("Advantage Plus $54/mo", found[:1])])


class WithPackagesTest(unittest.TestCase):
    PLUS = dict(package="Advantage Plus")

    def test_adds_what_each_package_gives_after_the_plan_own_benefit(self):
        found = [routine("vision.exam"), routine("vision.eyewear", "allowance", "$100", limit="every 2 years"),
                 routine("packages", "premium", "$54", **self.PLUS),
                 routine("vision.eyewear", "allowance", "$175", limit="every 2 years", **self.PLUS)]
        self.assertEqual(present.with_packages(present.vision)("", found), [(
            "exam $0; eyewear $100/two years. With Advantage Plus: eyewear $175/two years",
            [found[0], found[1], found[3]])])

    def test_a_plan_without_the_benefit_shows_only_the_package(self):
        found = [routine("packages", "premium", "$54", **self.PLUS),
                 routine("dental.preventive", **self.PLUS), routine("dental.comprehensive", "coinsurance", "50%", **self.PLUS)]
        self.assertEqual(present.with_packages(present.dental)("", found),
                         [("With Advantage Plus: PREV $0; COMP 50%", found[1:])])

    def test_shows_only_the_parts_the_package_adds(self):
        found = [routine("hearing.exam"), routine("packages", "premium", "$54", **self.PLUS),
                 routine("hearing.exam", **self.PLUS),
                 routine("hearing.aids", "allowance", "$500", unit="per ear", limit="every 3 years", **self.PLUS)]
        self.assertEqual(present.with_packages(present.hearing)("", found)[0][0],
                         "exam $0. With Advantage Plus: aids allowance $500 per ear/three years; 2 aids/three years")
        self.assertEqual(present.with_packages(present.hearing)("", found + [dict(found[3], package="")])[0][0],
                         "exam $0; aids allowance $500 per ear/three years; 2 aids/three years")

    def test_a_blank_cell_keeps_its_citations_unless_a_package_fills_it(self):
        none = routine("dental", "not_covered", "")
        self.assertEqual(present.with_packages(present.dental)("", [none]), [("", [none])])
        rider = [routine("packages", "premium", "$54", **self.PLUS), routine("dental.preventive", **self.PLUS)]
        self.assertEqual(present.with_packages(present.dental)("", [none] + rider), [("With Advantage Plus: PREV $0", rider[1:])])

    def test_a_package_from_a_plan_benefit_summary_alone_is_not_shown(self):
        found = [routine("packages", "premium", "$54", **self.PLUS), routine("dental.preventive", source="PBP", **self.PLUS)]
        self.assertEqual(present.with_packages(present.dental)("", found)[0][0], "")

    def test_skips_a_package_without_a_monthly_premium_or_without_the_benefit(self):
        found = [routine("vision.exam"), routine("vision.eyewear", "allowance", "$175", package="No premium"),
                 routine("packages", "premium", "$54", **self.PLUS), routine("dental.preventive", **self.PLUS)]
        self.assertEqual(present.with_packages(present.vision)("", found), [("exam $0", found[:1])])


class DetailsTest(unittest.TestCase):
    def test_adds_out_of_network_prices_for_each_service(self):
        found = [routine("dental.preventive"), routine("dental.preventive", "coinsurance", "50%", network="out"),
                 routine("dental.comprehensive", "coinsurance", "50%", network="out"),
                 routine("dental.comprehensive", "not_covered", "", network="out", source="SB")]
        rule = present.with_details(present.dental, present.out_of_network(("PREV", "dental.preventive"),
                                                                           ("COMP", "dental.comprehensive")))
        self.assertEqual(rule("", found), [("PREV $0; OON PREV 50%, COMP 50%", found[:3])])

    def test_skips_a_100_percent_coinsurance_which_pays_nothing(self):
        found = [routine("dental.preventive"), routine("dental.preventive", "coinsurance", "100%", network="out")]
        rule = present.with_details(present.dental, present.out_of_network(("PREV", "dental.preventive")))
        self.assertEqual(rule("", found), [("PREV $0", found[:1])])

    def test_skips_a_conditional_or_packaged_out_of_network_price(self):
        found = [routine("vision.exam"), routine("vision.exam", "copay", "$40", network="out", condition="diabetes"),
                 routine("vision.exam", "copay", "$40", network="out", package="Rider")]
        rule = present.with_details(present.vision, present.out_of_network(("exam", "vision.exam")))
        self.assertEqual(rule("", found), [("exam $0", found[:1])])

    def test_adds_a_yearly_dental_deductible(self):
        found = [routine("dental.preventive"), routine("dental.comprehensive", "deductible", "$50", limit="per year")]
        rule = present.with_details(present.dental, present.dental_deductible)
        self.assertEqual(rule("", found), [("PREV $0; deductible $50/year", found)])
        none = routine("dental", "deductible", "$0", limit="per calendar year")
        self.assertEqual(rule("", [found[0], none]), [("PREV $0; no deductible", [found[0], none])])

    def test_adds_how_often_the_best_source_covers_each_preventive_service(self):
        def limit(service, amount, every, **more):
            return routine("dental.preventive", "visit_limit", amount, condition=service, limit=every, **more)
        found = [routine("dental.preventive"), limit("Cleanings", "2", "per calendar year"),
                 limit("Panoramic X-rays", "1", "every 5 calendar years"), limit("Fluoride", "1", "every 6 months"),
                 limit("Bitewings", "1", "every year", source="SB"), limit("Exams", "2", ""),
                 limit("Space maintainers", "1", "per year", unit="per tooth"), limit("Crowns", "1", "every 5 years", package="P"),
                 limit("Sealants", "1", "per year", network="out"),
                 limit("Other services", "1", "per tooth per 6 months")]
        rule = present.with_details(present.dental, present.preventive_limits)
        self.assertEqual(rule("", found),
                         [("PREV $0; PREV limits: Cleanings 2/year · Panoramic X-rays 1 every 5 years · Fluoride 1 every 6 months",
                           found[:4])])
        self.assertEqual(rule("", found[:1] + found[4:5])[0][0], "PREV $0; PREV limits: Bitewings 1/year")
        self.assertEqual(rule("", found[:1] + found[5:])[0][0], "PREV $0")

    def test_reads_how_often_from_the_limit_and_skips_limits_per_part_of_the_mouth(self):
        for limit, often in (("Each Calendar Year", "year"), ("every 1 year", "year"), ("per benefit year", "year"),
                             ("every two years", "2 years"), ("Every Six Months", "6 months"), ("twice a year", ""),
                             ("everyyear", "")):
            self.assertEqual(present.how_often({"limit": limit}), often, limit)
        found = [routine("dental.preventive"),
                 routine("dental.preventive", "visit_limit", "1", condition="Bitewings", unit="set", limit="per year")]
        found += [routine("dental.preventive", "visit_limit", "1", condition="Sealants", limit=f"per {part} per year")
                  for part in ("Quadrant", "surface", "arch")]
        found += [routine("dental.preventive", "visit_limit", "2", limit="per year"),
                  routine("dental.preventive", "coinsurance", "0%", condition="Cleanings", limit="per year")]
        rule = present.with_details(present.dental, present.preventive_limits)
        self.assertEqual(rule("", found), [("PREV $0; PREV limits: Bitewings 1/year", found[:2])])

    def test_adds_nothing_to_a_blank_cell(self):
        found = [routine("dental.preventive", "coinsurance", "50%", network="out")]
        rule = present.with_details(present.dental, present.out_of_network(("PREV", "dental.preventive")))
        self.assertEqual(rule("", found)[0][0], "")


class NoneTest(unittest.TestCase):
    def test_a_plan_lacks_a_benefit_no_source_gives_in_any_way(self):
        exam = routine("vision.exam")
        says = routine("vision.eyewear", "not_covered", "")
        self.assertEqual(present.lacks([exam], "vision.eyewear"), (True, []))
        self.assertEqual(present.lacks([exam, says, dict(says, source="SB")], "vision.eyewear"), (True, [says]))
        for offered in (routine("vision.eyewear", "allowance", "$100"), routine("vision.eyewear", condition="diabetes"),
                        routine("vision.eyewear.contacts", "allowance", "$100"), routine("vision", "allowance", "$100"),
                        routine("vision.eyewear", "allowance", "$100", provider_tier="PLUS"),
                        routine("vision.eyewear", "allowance", "$100", network="out")):
            self.assertEqual(present.lacks([exam, offered], "vision.eyewear"), (False, []), offered)

    def test_medicare_and_package_benefits_do_not_count(self):
        exam = routine("vision.exam")
        for other in (priced("vision.eyewear", condition="after cataract surgery"),
                      routine("vision.eyewear", "allowance", "$175", package="Advantage Plus")):
            self.assertEqual(present.lacks([exam, other], "vision.eyewear"), (True, []), other)

    def test_details_of_a_benefit_do_not_offer_it(self):
        exam = routine("vision.exam")
        for detail in ("rollover", "also pays for members with diabetes", "provider network", "no annual maximum", "excludes",
                       "reimbursement"):
            self.assertEqual(present.lacks([exam, routine("vision", condition=detail)], "vision.eyewear"), (True, []))

    def test_cites_only_facts_that_exclude_the_benefit_itself(self):
        narrow = routine("dental.comprehensive", "not_covered", "", quotes='["Implants are not covered"]')
        self.assertEqual(present.lacks([routine("vision.exam"), narrow], "dental"), (True, []))

    def test_a_plan_without_document_facts_lacks_nothing(self):
        self.assertEqual(present.lacks([routine("vision.exam", source="PBP")], "vision.eyewear"), (False, []))

    def test_a_cell_says_none_before_what_a_package_adds(self):
        plus = dict(package="Advantage Plus")
        says = routine("dental", "not_covered", "")
        found = [routine("packages", "premium", "$54", **plus), routine("dental.preventive", **plus),
                 priced("dental", amount="$45")]
        rule = present.or_none(present.with_packages(present.dental), "dental")
        self.assertEqual(rule("", found), [("None. With Advantage Plus: PREV $0", found[1:2])])
        self.assertEqual(rule("", found + [says]), [("None. With Advantage Plus: PREV $0", [says, found[1]])])
        self.assertEqual(rule("", found[2:]), [("None", [])])
        self.assertEqual(rule("", found[2:] + [says]), [("None", [says])])
        self.assertEqual(rule("", [routine("dental.preventive")])[0][0], "PREV $0")

    def test_adds_what_the_plan_lacks_to_its_own_value_before_a_packages(self):
        plus = dict(package="Plus")
        says = routine("dental.comprehensive", "not_covered", "")
        rule = present.with_lacking(present.with_packages(present.dental), ("no COMP", "dental.comprehensive"))
        found = [routine("dental.preventive"), says]
        self.assertEqual(rule("", found), [("PREV $0; no COMP", found)])
        packaged = [routine("packages", "premium", "$20", **plus), routine("dental.comprehensive", "coinsurance", "50%", **plus)]
        self.assertEqual(rule("", found + packaged)[0][0], "PREV $0; no COMP. With Plus: COMP 50%")
        self.assertEqual(rule("", packaged)[0][0], "With Plus: COMP 50%")
        for offered in (routine("dental", "max", "$1,000", limit="per year"), routine("dental", "coinsurance", "50%"),
                        routine("dental.comprehensive", condition="diabetes")):
            self.assertNotIn("no COMP", rule("", [routine("dental.preventive"), offered])[0][0], offered)

    def test_a_package_part_never_says_what_the_package_lacks(self):
        plus = dict(package="Plus")
        found = [routine("vision.exam"), routine("vision.eyewear", "allowance", "$100", limit="per year"),
                 routine("packages", "premium", "$20", **plus), routine("vision.exam", amount="$5", **plus)]
        rule = present.with_lacking(present.with_packages(present.vision), ("no eyewear allowance", "vision.eyewear"))
        self.assertEqual(rule("", found)[0][0], "exam $0; eyewear $100/year. With Plus: exam $5")


class TelehealthTest(unittest.TestCase):
    def test_adds_the_range_of_virtual_visit_prices_after_the_other_parts(self):
        found = [routine("otc", "allowance", "$40", limit="per quarter"),
                 priced("visits", "telehealth", condition="PCP Virtual"), priced("visits", "telehealth", "$40"),
                 priced("visits", "telehealth", "$90", condition="services in a nursing home"),
                 priced("visits", "telehealth", "$45", network="out"), priced("visits", "office.pcp", "$5")]
        self.assertEqual(present.alt_care_otc_travel("", found, telehealth=True),
                         [("OTC $40/three months; Telehealth $0-$40", found[:3])])
        self.assertEqual(present.alt_care_otc_travel("", found[1:2], telehealth=True), [("Telehealth $0", found[1:2])])


class DentalTest(unittest.TestCase):
    def test_with_services_a_plans_own_per_service_prices_give_the_range(self):
        fillings = routine("dental.comprehensive", "coinsurance", "50%", condition="fillings")
        recement = routine("dental.comprehensive", "coinsurance", "0%", condition="crown recementation")
        found = [routine("dental.preventive"), fillings, recement]
        self.assertEqual(column(lambda o, f: present.dental(o, f, services=True), *found),
                         [("PREV $0; COMP $0-50%", found)])
        self.assertEqual(column(present.dental_before_25, *found)[0][0], "PREV $0")
        for other in (dict(recement, condition="members with diabetes"), dict(recement, network="out"), fillings):
            self.assertEqual(column(lambda o, f: present.dental(o, f, services=True), found[0], fillings, other)[0][0],
                             "PREV $0", other)
        everyone = routine("dental.comprehensive", "coinsurance", "20%")
        self.assertEqual(column(lambda o, f: present.dental(o, f, services=True), everyone, fillings)[0][0], "COMP 20%")

    def test_with_services_a_packages_per_service_prices_do_not_give_a_range(self):
        plus = dict(package="Plus")
        found = [routine("dental.preventive"), routine("packages", "premium", "$20", **plus),
                 routine("dental.comprehensive", "coinsurance", "50%", condition="fillings", **plus)]
        rule = present.with_packages(lambda o, f: present.dental(o, f, services=True))
        self.assertEqual(rule("", found)[0][0], "PREV $0")

    def test_shows_preventive_and_comprehensive_prices_and_the_yearly_max(self):
        found = [routine("dental.preventive", "coinsurance", "0%"), routine("dental.comprehensive", "coinsurance", "50%"),
                 routine("dental", "max", "$1,000", limit="per year"), routine("dental", "covered", "")]
        self.assertEqual(column(present.dental, *found), [("PREV $0; COMP 50%; max $1,000/year PREV+COMP", found[:3])])

    def test_a_max_for_comprehensive_care_says_so(self):
        found = [routine("dental.preventive"), routine("dental.comprehensive"),
                 routine("dental.comprehensive", "max", "$1,000", limit="every year")]
        self.assertEqual(column(present.dental, *found)[0][0], "PREV $0; COMP $0; COMP max $1,000/year")

    def test_names_the_alternative_care_that_shares_the_max(self):
        pool = dict(pool="Dental & Alternative Therapy Allowance")
        found = [routine("dental.preventive"), routine("dental.comprehensive", "coinsurance", "50%"),
                 routine("dental", "allowance", "$1,750", limit="per year", **pool),
                 routine("extras.massage", "allowance", "$1,750", limit="per year", **pool),
                 routine("extras.acupuncture", "allowance", "$1,750", limit="per year", **pool)]
        self.assertEqual(column(present.dental, *found)[0][0],
                         "PREV $0; COMP 50%; max $1,750/year shared by PREV+COMP, acupuncture, massage")

    def test_an_allowance_alone_pays_for_both(self):
        found = [routine("dental", "allowance", "$150", limit="every three months", pool="Flex Card")]
        self.assertEqual(column(present.dental, *found)[0][0], "PREV+COMP from $150/three months allowance")

    def test_an_allowance_alone_names_the_alternative_care_that_shares_it(self):
        pool = dict(pool="Dental & Alternative Therapy Allowance", limit="per year")
        found = [routine("dental", "allowance", "$2,250", **pool), routine("extras.massage", "allowance", "$2,250", **pool)]
        self.assertEqual(column(present.dental, *found)[0][0], "PREV+COMP from $2,250/year allowance shared with massage")

    def test_names_the_only_comprehensive_services_the_facts_price(self):
        adjunctive = routine("dental.comprehensive", quotes='["Adjunctive General Services In-Network $0 copay"]')
        perio = routine("dental.comprehensive", source="SB", quotes='["$0 copay for periodontal maintenance", '
                                                                     '"Administration of nitrous oxide 0%"]')
        self.assertEqual(column(present.dental, adjunctive)[0][0], "COMP $0 for adjunctive services")
        self.assertEqual(column(present.dental, adjunctive, perio)[0][0],
                         "COMP $0 for adjunctive services, periodontal maintenance, nitrous oxide")
        fillings = routine("dental.comprehensive", source="SB", quotes='["$0 copay for amalgam filling"]')
        self.assertEqual(column(present.dental, adjunctive, fillings)[0][0], "COMP $0")
        merged = routine("dental.comprehensive", source="SB", quotes='["$0 copay for amalgam filling", '
                                                                       '"$0 copay for periodontal maintenance"]')
        self.assertEqual(column(present.dental, adjunctive, merged)[0][0], "COMP $0")
        unnamed = routine("dental.comprehensive", source="SB", quotes='["What you pay: 0% coinsurance"]')
        self.assertEqual(column(present.dental, adjunctive, unnamed)[0][0], "COMP $0")

    def test_a_broader_service_priced_on_its_own_drops_the_narrow_names(self):
        adjunctive = routine("dental.comprehensive", quotes='["Adjunctive General Services In-Network $0 copay"]')
        restorative = routine("dental.comprehensive", condition="restorative services", quotes='["$0 copay"]')

        def comp(*found):
            return present.dental("Aetna", [adjunctive, *found], broad_services=True)[0][0]
        self.assertEqual(comp(restorative), "COMP $0")
        self.assertEqual(comp(dict(restorative, condition="", quotes='["$0 copay for each restorative service."]')),
                         "COMP $0")
        self.assertEqual(column(present.dental, adjunctive, restorative)[0][0], "COMP $0 for adjunctive services")
        for kept in (dict(restorative, network="out"), dict(restorative, package="Optional Dental"),
                     dict(restorative, condition="restorative services for members with diabetes"),
                     dict(restorative, cost_kind="max", amount="$1,000"),
                     dict(restorative, benefit="dental.preventive")):
            self.assertEqual(comp(kept), "COMP $0 for adjunctive services", kept)

    def test_names_a_yearly_limit_on_a_narrow_service(self):
        dental = present.DVHA["F_dental"]
        perio = routine("dental.comprehensive", quotes='["$0 copay for periodontal maintenance"]')
        limit = routine("dental.comprehensive", "visit_limit", "4", condition="periodontal maintenance", limit="per year")
        self.assertEqual(column(present.dental, perio, limit), [("COMP $0 for periodontal maintenance", [perio])])
        self.assertEqual(column(dental, perio, limit)[0][0], "COMP $0 for periodontal maintenance 4/year")
        limited = lambda o, found: present.dental(o, found, limits=True)  # noqa: E731
        self.assertEqual(column(limited, perio, limit), [("COMP $0 for periodontal maintenance 4/year", [perio, limit])])
        for other in (dict(limit, limit="every date of service"), dict(limit, condition="fillings"),
                      dict(limit, package="Plus"), dict(limit, cost_kind="copay"),
                      dict(limit, benefit="dental.preventive"), dict(limit, limit="per tooth per year")):
            self.assertEqual(column(limited, perio, other)[0][0], "COMP $0 for periodontal maintenance", other)
        self.assertEqual(column(limited, perio, limit, dict(limit, amount="2"))[0][0], "COMP $0 for periodontal maintenance")

    def test_dental_benefit_details_name_the_only_comprehensive_services(self):
        adjunctive = routine("dental.comprehensive", quotes='["Adjunctive General Services In-Network $0 copay"]')
        listed = routine("dental.comprehensive", "covered", "", condition="teledentistry", network="any", source="DENTAL",
                         quotes='["Adjunctive General Services"]')

        def comp(*found, listed_services=True):
            return present.dental("Wellcare", [adjunctive, *found], broad_services=True, listed_services=listed_services)[0]
        self.assertEqual(comp(listed), ("COMP $0 (teledentistry only)", [adjunctive, listed]))
        self.assertEqual(comp(listed, dict(listed, condition="nitrous oxide"))[0],
                         "COMP $0 (nitrous oxide, teledentistry only)")
        self.assertEqual(comp(listed, listed_services=False)[0], "COMP $0 for adjunctive services")
        self.assertEqual(comp(listed, dict(listed, plan_id="H0000-000-0"))[0], "COMP $0 (teledentistry only)")
        for ignored in (dict(listed, source="EOC"), dict(listed, cost_kind="not_covered"), dict(listed, condition=""),
                        dict(listed, benefit="dental.preventive"), dict(listed, package="Dental Plus"),
                        dict(listed, network="out"), dict(listed, condition="provider network"),
                        dict(listed, condition="members with diabetes")):
            self.assertEqual(comp(ignored)[0], "COMP $0 for adjunctive services", ignored)
        broad = routine("dental.comprehensive", quotes='["$0 copay for fillings, crowns and root canals"]')
        self.assertEqual(comp(listed, broad)[0], "COMP $0")
        exams = dict(listed, benefit="dental.preventive", condition="oral exams")
        self.assertEqual(present.dental("Wellcare", [routine("dental.preventive"), exams], listed_services=True)[0][0],
                         "PREV $0")

    def test_a_card_shared_with_other_benefits_is_not_a_max(self):
        card = dict(pool="Spendables", limit="per month")
        found = [routine("dental.preventive"), routine("dental", "allowance", "$20", **card),
                 routine("otc", "allowance", "$20", **card)]
        self.assertEqual(column(present.dental, *found), [("PREV $0", found[:1])])

    def test_a_max_that_does_not_say_how_often_it_renews_leaves_the_cell_blank(self):
        found = [routine("dental.preventive"), routine("dental", "max", "$1,250")]
        self.assertEqual(column(present.dental, *found), [("", [])])

    def test_a_lower_source_with_the_same_max_says_how_often_it_renews(self):
        found = [routine("dental.preventive"), routine("dental", "max", "$1,250"),
                 routine("dental", "max", "$1,250", limit="every year", source="PBP")]
        self.assertEqual(column(present.dental, *found), [("PREV $0; max $1,250/year PREV+COMP", found)])
        other = dict(found[2], amount="$1,000")
        self.assertEqual(column(present.dental, *found[:2], other), [("", [])])

    def test_medicare_conditional_and_package_dental_cite_a_blank(self):
        found = [priced("dental.preventive", amount="$30"), routine("dental.comprehensive", condition="diabetes"),
                 routine("dental.comprehensive", package="Rider"), routine("dental.comprehensive", network="out")]
        self.assertEqual(column(present.dental, *found), [("", found[:3])])


class EveryTest(unittest.TestCase):
    def test_names_how_often_a_fact_renews(self):
        for limit, want in (("per quarter", "three months"), ("every six months", "six months"), ("per month", "month"),
                            ("every 2 years", "two years"), ("per calendar year", "year"), ("for 12 months", ""),
                            ("annually", "")):
            self.assertEqual(present.every(routine("otc", "allowance", "$1", limit=limit)), want, limit)


class AltCareOtcTravelTest(unittest.TestCase):
    def test_shows_each_service_copay_and_visit_limit_then_otc_and_worldwide_er(self):
        found = [routine("extras.acupuncture"), routine("extras.acupuncture", "visit_limit", "24", limit="per year"),
                 routine("extras.chiropractic", amount="$15"), routine("otc", "allowance", "$40", limit="per quarter"),
                 routine("emergency", setting="outside_us", amount="$130"),
                 routine("emergency", "max", "$50,000", setting="outside_us", limit="per year")]
        self.assertEqual(column(present.alt_care_otc_travel, *found),
                         [("Acup $0 24 visits/year; Chiro $15; OTC $40/three months; Worldwide ER $130, $50,000 max",
                           found)])

    def test_services_with_one_shared_visit_limit_show_it_once(self):
        found = [f for leaf in ("extras.acupuncture", "extras.chiropractic")
                 for f in (routine(leaf, amount="$10"), routine(leaf, "visit_limit", "18", limit="per calendar year",
                                                                 condition="for all three services combined"))]
        self.assertEqual(column(present.alt_care_otc_travel, *found)[0][0], "Acup $10; Chiro $10; 18 visits/year combined")

    def test_services_paid_from_a_shared_allowance_name_it(self):
        dental = dict(pool="Dental & Alternative Therapy Allowance", limit="per year")
        flex = dict(pool="Flex Card", limit="every six months")
        self.assertEqual(column(present.alt_care_otc_travel, routine("extras.acupuncture", "allowance", "$1,750", **dental),
                                routine("extras.massage", "allowance", "$1,750", **dental))[0][0],
                         "Acup, Massage from dental allowance")
        self.assertEqual(column(present.alt_care_otc_travel, routine("extras.acupuncture", "allowance", "$50", **flex),
                                routine("extras.naturopathy", "allowance", "$50", **flex))[0][0],
                         "Acup, Naturopath from $50/six months allowance")
        bucks = routine("extras.massage", "allowance", "$150", pool="Wellness Bucks", limit="per year")
        self.assertEqual(column(present.alt_care_otc_travel, bucks)[0][0], "Massage from $150/year Wellness Bucks")

    def test_an_otc_allowance_that_pays_for_other_benefits_names_them(self):
        card = dict(pool="Spendables", limit="per month")
        found = [routine("otc", "allowance", "$20", **card), routine("hearing", "allowance", "$20", **card),
                 routine("dental", "allowance", "$20", **card), routine("vision", "allowance", "$90", **card)]
        self.assertEqual(column(present.alt_care_otc_travel, *found),
                         [("OTC from $20/month card shared with dental, hearing", found[:3])])

    def test_with_food_says_when_any_source_says_the_otc_allowance_also_pays_for_food(self):
        eoc = routine("otc", "allowance", "$196", limit="per month")
        sb = routine("otc", "allowance", "$196", limit="per month", source="SB", pool="OTC and food credit")
        self.assertEqual(present.alt_care_otc_travel("", [eoc, sb], food=True), [("OTC and food $196/month", [eoc, sb])])
        self.assertEqual(present.alt_care_otc_travel("", [eoc, sb])[0][0], "OTC $196/month")
        groceries = dict(eoc, quotes='["Use your allowance on groceries and OTC items"]')
        self.assertEqual(present.alt_care_otc_travel("", [groceries], food=True)[0][0], "OTC and food $196/month")
        self.assertEqual(present.alt_care_otc_travel("", [eoc], food=True)[0][0], "OTC $196/month")

    def test_with_fitness_starts_with_the_fitness_program_and_wellness_bucks(self):
        er = routine("emergency", setting="outside_us", amount="$130")
        gym = routine("fitness")
        named = routine("fitness", source="SB", quotes='["SilverSneakers®: $0 membership"]')
        bucks = routine("fitness", "allowance", "$150", pool="Wellness Bucks", limit="per year")
        self.assertEqual(present.alt_care_otc_travel("", [er, gym, named, bucks], fitness=True),
                         [("Fitness SilverSneakers $0; Wellness Bucks $150/year; Worldwide ER $130",
                           [gym, named, bucks, er])])
        self.assertEqual(present.alt_care_otc_travel("", [er, gym, named, bucks])[0][0], "Worldwide ER $130")
        unoffered = routine("fitness", "not_covered", "", page="9")
        _, aside = present.explain("", [er, gym, unoffered], "I_alt_care_otc_travel", "dvha")
        self.assertIn("it is not a supplemental in-network benefit for every member", aside[facts.identity(unoffered)])

    def test_with_none_says_when_the_plan_lacks_otc(self):
        er = routine("emergency", setting="outside_us", amount="$130")
        says = routine("otc", "not_covered", "")
        self.assertEqual(present.alt_care_otc_travel("", [er], none=True), [("OTC none; Worldwide ER $130", [er])])
        self.assertEqual(present.alt_care_otc_travel("", [er, says], none=True)[0][1], [says, er])
        self.assertEqual(present.alt_care_otc_travel("", [er])[0][0], "Worldwide ER $130")
        for otc in (routine("otc", "allowance", "$50", condition="chronically ill"), routine("otc", "allowance", "$50")):
            self.assertNotIn("OTC none", present.alt_care_otc_travel("", [er, otc], none=True)[0][0], otc)

    def test_with_rates_an_allowance_shared_with_dental_shows_its_amount_and_one_price(self):
        pool = dict(pool="Dental & Alternative Therapy Allowance")
        found = [routine(leaf, kind, amount, fact_id=f"{leaf} {kind}", **pool, **more)
                 for leaf in ("extras.acupuncture", "extras.massage")
                 for kind, amount, more in (("allowance", "$2,000", dict(limit="per year")), ("coinsurance", "50%", {}))]
        self.assertEqual(present.alt_care_otc_travel("", found, rates=True),
                         [("Acup, Massage 50% from $2,000/year allowance shared with dental", found)])
        self.assertEqual(present.alt_care_otc_travel("", found)[0][0], "Acup, Massage from dental allowance")
        allowances = [found[0], found[2]]
        self.assertEqual(present.alt_care_otc_travel("", found[:3], rates=True),
                         [("Acup, Massage from $2,000/year allowance shared with dental", allowances)])
        _, aside = present.explain("", found[:3], "I_alt_care_otc_travel", "dvha")
        self.assertIn("the services that share the allowance do not all give one price", aside[facts.identity(found[1])])
        unrenewed = [dict(f, limit="") for f in allowances]
        self.assertEqual(present.alt_care_otc_travel("", unrenewed, rates=True)[0][0], "Acup, Massage from dental allowance")
        flex = [routine("extras.acupuncture", kind, amount, pool="Flex Card", limit="every six months")
                for kind, amount in (("allowance", "$50"), ("copay", "$0"))]
        self.assertEqual(present.alt_care_otc_travel("", flex, rates=True)[0][0], "Acup $0 from $50/six months allowance")

    def test_worldwide_er_skips_urgent_care(self):
        found = [routine("emergency", setting="outside_us", amount="$130"),
                 routine("emergency", setting="outside_us", amount="$500", quotes='["Urgent care $500"]')]
        self.assertEqual(column(present.alt_care_otc_travel, *found), [("Worldwide ER $130", found[:1])])

    def test_with_urgent_care_shows_worldwide_urgent_care_beside_the_er(self):
        er = routine("emergency", setting="outside_us", amount="$130")
        same = routine("emergency", setting="outside_us", amount="$130", condition="urgently needed services")
        less = routine("emergency", setting="outside_us", amount="$50", quotes='["Urgent care $50"]')
        sb = dict(less, amount="$65", source="SB")
        cell = lambda *found: present.alt_care_otc_travel("", list(found), urgent_care=True)
        self.assertEqual(cell(er, same), [("Worldwide ER/urgent $130", [er, same])])
        self.assertEqual(cell(er, less, sb), [("Worldwide ER $130, urgent care $50", [er, less])])
        self.assertEqual(cell(er), [("Worldwide ER $130", [er])])
        self.assertEqual(cell(er, dict(same, package="Rider")), [("Worldwide ER $130", [er])])
        self.assertEqual(cell(er, dict(same, cost_kind="covered", amount="")), [("Worldwide ER $130", [er])])
        self.assertEqual(cell(er, same, dict(less, condition="urgent care")), [("Worldwide ER $130", [er])])
        self.assertEqual(present.alt_care_otc_travel("", [er, same])[0][0], "Worldwide ER $130")

    def test_worldwide_urgent_care_is_any_in_network_copay_outside_the_us(self):
        er = routine("emergency", setting="outside_us", amount="$130")
        medicare = priced("emergency", setting="outside_us", amount="$130", condition="urgently needed services")
        cell = lambda *found: present.alt_care_otc_travel("", list(found), urgent_care=True)[0][0]
        self.assertEqual(cell(er, medicare), "Worldwide ER/urgent $130")
        self.assertEqual(cell(er, dict(medicare, setting="any", amount="$40")), "Worldwide ER $130")
        self.assertEqual(cell(er, dict(medicare, network="out", amount="$40")), "Worldwide ER $130")
        self.assertEqual(cell(er, dict(medicare, provider_tier="PLUS", amount="$40")), "Worldwide ER $130")

    def test_copays_that_no_quote_tells_apart_leave_the_cell_blank(self):
        found = [routine("otc", "allowance", "$40", limit="per month"),
                 routine("emergency", setting="outside_us", amount="$130"),
                 routine("emergency", setting="outside_us", amount="$50")]
        self.assertEqual(column(present.alt_care_otc_travel, *found), [("", [])])
        found = [dict(f, fact_id=f["amount"]) for f in found]
        _, aside = present.explain("Humana", found, "I_alt_care_otc_travel", "dvha")
        self.assertEqual({f["amount"]: aside[facts.identity(f)] for f in found}, {
            "$40": ["the facts do not fully give the worldwide part"],
            "$130": ["the facts do not say which copay is the ER's"], "$50": ["the facts do not say which copay is the ER's"]})

    def test_a_lower_source_tells_the_documents_er_copay_apart(self):
        found = [routine("emergency", setting="outside_us", amount="$130"),
                 routine("emergency", setting="outside_us", amount="$50"),
                 routine("emergency", setting="outside_us", amount="$130", source="PBP")]
        self.assertEqual(column(present.alt_care_otc_travel, *found), [("Worldwide ER $130", [found[0], found[2]])])
        found = [dict(f, fact_id=f["amount"] + f["source"]) for f in found]
        _, aside = present.explain("Humana", found, "I_alt_care_otc_travel", "dvha")
        self.assertEqual(aside[facts.identity(found[1])], ["PBP gives another copay"])

    def test_a_lower_source_copay_no_document_gives_leaves_the_cell_blank(self):
        found = [routine("emergency", setting="outside_us", amount="$130"),
                 routine("emergency", setting="outside_us", amount="$50"),
                 routine("emergency", setting="outside_us", amount="$90", source="PBP")]
        self.assertEqual(column(present.alt_care_otc_travel, *found), [("", [])])

    def test_a_document_that_says_care_abroad_is_not_covered_cites_a_blank(self):
        none = priced("emergency", setting="outside_us", cost_kind="not_covered", amount="")
        self.assertEqual(column(present.alt_care_otc_travel, none), [("", [none])])

    def test_care_abroad_without_a_copay_leaves_the_cell_blank(self):
        found = [routine("extras.acupuncture"), priced("emergency", setting="outside_us", cost_kind="covered", amount="")]
        self.assertEqual(column(present.alt_care_otc_travel, *found), [("", [])])

    def test_skips_medicare_and_conditional_care(self):
        found = [priced("extras.acupuncture", amount="$20"), routine("extras.chiropractic", condition="diabetes"),
                 routine("emergency", amount="$90")]
        self.assertEqual(column(present.alt_care_otc_travel, *found), [("", [])])


class ExtraBenefitsTest(unittest.TestCase):
    def test_names_fitness_meals_and_transportation_and_shows_foot_care(self):
        found = [routine("fitness"), routine("meals"), routine("extras.transportation"), routine("foot_care", amount="$45"),
                 routine("foot_care", "visit_limit", "6", limit="per year")]
        self.assertEqual(column(present.extra_benefits, *found),
                         [("Fitness; Meals; Transportation; Routine foot care $45 6/year", found)])

    def test_with_prices_shows_the_fitness_and_meals_copays_and_how_many_meals(self):
        found = [routine("fitness"), routine("meals"), routine("meals", "visit_limit", "28", unit="meals"),
                 routine("meals", "visit_limit", "4", limit="per year"), routine("extras.transportation"),
                 routine("meals", "visit_limit", "14", unit="meals", source="SB")]
        self.assertEqual(present.extra_benefits("", found, prices=True),
                         [("Fitness $0; Meals $0, 28 meals; Transportation", found[:3] + found[4:5])])
        self.assertEqual(present.extra_benefits("", found[:2] + found[5:], prices=True)[0][0], "Fitness $0; Meals $0, 14 meals")

    def test_with_programs_names_the_fitness_program_from_the_best_source_that_names_it(self):
        eoc = routine("fitness", quotes='["$0 membership"]')
        sb = routine("fitness", source="SB", quotes='["SilverSneakers®: $0 membership"]')
        self.assertEqual(present.extra_benefits("", [eoc, sb], prices=True, programs=True),
                         [("Fitness SilverSneakers $0", [eoc, sb])])
        self.assertEqual(present.extra_benefits("", [eoc, sb], programs=True), [("Fitness SilverSneakers", [eoc, sb])])
        self.assertEqual(present.extra_benefits("", [eoc, sb], prices=True)[0][0], "Fitness $0")
        self.assertEqual(present.extra_benefits("", [eoc], prices=True, programs=True)[0][0], "Fitness $0")
        named_eoc = dict(eoc, quotes='["One Pass"]')
        self.assertEqual(present.extra_benefits("", [sb, named_eoc], prices=True, programs=True)[0][0], "Fitness One Pass $0")
        for quote, program in (("The Silver&Fit® Healthy Aging", "Silver&Fit"), ("Fitness benefit (One Pass®)", "One Pass"),
                               ("Renew Active® by UnitedHealthcare", "Renew Active"), ("Silver Sneakers", "SilverSneakers"),
                               ("Silver & Fit", "Silver&Fit")):
            named = routine("fitness", quotes=f'["{quote}"]')
            self.assertEqual(present.extra_benefits("", [named], prices=True, programs=True)[0][0], f"Fitness {program} $0")

    def test_with_programs_ignores_a_program_named_only_by_a_fact_it_does_not_show(self):
        for named in (routine("fitness", network="out", quotes='["SilverSneakers"]'),
                      routine("fitness", condition="diabetes", quotes='["SilverSneakers"]'),
                      routine("fitness", package="Rider", quotes='["SilverSneakers"]'),
                      routine("fitness", quotes='["One passenger may ride along"]')):
            self.assertEqual(present.extra_benefits("", [routine("fitness"), named], prices=True, programs=True)[0][0],
                             "Fitness $0")
        meals = routine("meals", quotes='["Meals for SilverSneakers members"]')
        self.assertEqual(present.extra_benefits("", [meals], prices=True, programs=True)[0][0], "Meals $0")

    def test_with_programs_names_each_other_program_for_every_member(self):
        nurse = routine("other_supplemental", pool="24-Hour Nurse Line", source="SB")
        travel = routine("other_supplemental", "covered", "", pool="Travel Advantage", source="SB")
        travel_eoc = dict(travel, source="EOC", pool="HMO Travel Benefit")
        rewards = routine("other_supplemental", "allowance", "$100", pool="Rewards", limit="per year")
        card = routine("other_supplemental", "allowance", "$30", pool="Food Card", condition="chronic", limit="per month")
        away = routine("other_supplemental", "max", "$1,200", pool="Explorer", network="out")
        nameless = routine("other_supplemental")
        dropped = routine("other_supplemental", "not_covered", "", pool="Dropped")
        self.assertEqual(present.extra_benefits("", [nurse, travel, travel_eoc, rewards, away, nameless, dropped],
                                                programs=True),
                         [("24-Hour Nurse Line $0; HMO Travel Benefit; Rewards $100/year; Travel Advantage",
                           [nurse, travel_eoc, rewards, travel])])
        self.assertEqual(present.extra_benefits("", [routine("foot_care"), card, nurse], programs=True)[0][0],
                         "24-Hour Nurse Line $0; Routine foot care $0; "
                         "For members with certain chronic conditions: Food Card $30/month")

    def test_a_program_named_differently_by_two_sources_shows_once_by_its_best_sources_name(self):
        eoc = routine("other_supplemental", pool="Nurse advice line")
        sb = dict(eoc, source="SB", pool="24\u2011Hour Nurse Advice Line")
        support = [routine("other_supplemental", pool="Social support platform"),
                   routine("other_supplemental", pool="Social Support Platform", source="SB")]
        travel = [routine("other_supplemental", "covered", "", pool="Travel Advantage", source="SB", page="9"),
                  routine("other_supplemental", "covered", "", pool="Visitor/traveler program: Travel Advantage",
                          source="SB")]
        self.assertEqual(present.other_programs([sb, eoc] + support + travel)[0],
                         ["24-Hour Nurse Advice Line $0", "Nurse advice line $0", "Social Support Platform $0",
                          "Social support platform $0", "Travel Advantage", "Visitor/traveler program: Travel Advantage"])
        self.assertEqual(present.other_programs([sb, eoc] + support + travel, alike=True),
                         (["Nurse advice line $0", "Social support platform $0", "Travel Advantage"],
                          [eoc, support[0]] + travel))
        self.assertEqual(present.other_programs([sb], alike=True)[0], ["24-Hour Nurse Advice Line $0"])
        for names in (["Healthy Rewards", "Healthy Rewards program"], ["24 hours nurse line", "Nurse Line"],
                      ["24hour nurse line", "Nurse line"], ["Nurse-line", "nurse line"]):
            got = [routine("other_supplemental", pool=name) for name in names]
            self.assertEqual(present.other_programs(got, alike=True)[0], [f"{min(names, key=len)} $0"], names)
        named = [routine("other_supplemental", pool=name) for name in ("Nurse Line", "Nurse  line")]
        self.assertEqual(present.other_programs(named, alike=True)[0], ["Nurse Line $0"])
        hyphens = [routine("other_supplemental", pool=name) for name in ("Nurse\u2011Line", "Nurse-Line")]
        self.assertEqual(present.other_programs(hyphens)[0], ["Nurse-Line $0", "Nurse-Line $0"])

    def test_a_program_shows_its_best_sources_allowance_and_cites_only_its_price(self):
        rewards = routine("other_supplemental", "allowance", "$100", pool="Rewards", limit="per year")
        named = routine("other_supplemental", "covered", "", pool="Rewards")
        sb = dict(rewards, source="SB", amount="$500")
        copay = routine("other_supplemental", pool="Rewards")
        self.assertEqual(present.other_programs([rewards, named, sb, copay]), (["Rewards $100/year"], [rewards]))
        self.assertEqual(present.other_programs([dict(rewards, limit="")]), (["Rewards $100"], [dict(rewards, limit="")]))
        self.assertEqual(present.other_programs([routine("other_supplemental", pool="24\u2011Hour Nurse Line")])[0],
                         ["24-Hour Nurse Line $0"])

    def test_anywhere_names_an_out_of_network_program_with_its_yearly_maximum(self):
        named = routine("other_supplemental", "covered", "", pool="Explorer", network="out")
        cap = dict(named, cost_kind="max", amount="$1,200", limit="per calendar year", source="SB")
        self.assertEqual(present.other_programs([named, cap]), ([], []))
        self.assertEqual(present.other_programs([named, cap], anywhere=True), (["Explorer max $1,200/year"], [cap]))
        self.assertEqual(present.other_programs([named, dict(cap, limit="")], anywhere=True), (["Explorer"], [named]))
        self.assertEqual(present.other_programs([named, dict(cap, source="EOC")], anywhere=True)[1], [dict(cap, source="EOC")])
        for other in ({"condition": "diabetes"}, {"package": "Plus"}, {"provider_tier": "1"}, {"covered_by": "medicare"}):
            self.assertEqual(present.other_programs([dict(named, **other)], anywhere=True), ([], []), other)
        inside = routine("other_supplemental", pool="Explorer")
        self.assertEqual(present.other_programs([inside, dict(inside, amount="$20", network="out"), cap], anywhere=True),
                         (["Explorer $0"], [inside]))
        copay = dict(inside, network="out", amount="$20")
        self.assertEqual(present.other_programs([copay, dict(cap, source="EOC")], anywhere=True)[0], ["Explorer $20"])

    def test_foot_care_for_members_with_diabetes_says_so_unless_every_member_has_some(self):
        diabetic = routine("foot_care", condition="diabetes")
        self.assertEqual(column(present.extra_benefits, diabetic)[0][0], "Routine foot care $0 for members with diabetes")
        self.assertEqual(column(present.extra_benefits, diabetic, routine("foot_care", amount="$15"))[0][0],
                         "Routine foot care $15")

    def test_skips_conditional_and_uncovered_benefits(self):
        found = [routine("meals", condition="after a hospital stay"), routine("fitness", cost_kind="not_covered", amount=""),
                 routine("extras.transportation", network="out")]
        self.assertEqual(column(present.extra_benefits, *found), [("", [])])

    def test_shows_wellness_bucks_unless_they_also_pay_for_alternative_care(self):
        bucks = routine("fitness", "allowance", "$150", pool="Devoted Health Wellness Bucks", limit="per year")
        self.assertEqual(column(present.extra_benefits, routine("fitness"), bucks, dict(bucks, source="SB", page="2"))[0][0],
                         "Fitness; Wellness Bucks $150/year")
        massage = routine("extras.massage", "allowance", "$150", pool=bucks["pool"], limit="per year")
        self.assertEqual(column(present.extra_benefits, routine("fitness"), bucks, massage)[0][0], "Fitness")

    def test_with_part_b_starts_with_the_monthly_giveback(self):
        eoc = priced("giveback", amount="$154.20", cost_kind="part_b_reduction", unit="per month")
        sb = dict(eoc, source="SB")
        self.assertEqual(present.extra_benefits("", [routine("fitness"), sb, eoc], part_b=True),
                         [("Part B giveback $154.20/month; Fitness", [eoc, routine("fitness")])])
        self.assertEqual(present.extra_benefits("", [dict(eoc, unit="")], part_b=True)[0][0], "Part B giveback $154.20")
        self.assertEqual(present.extra_benefits("", [routine("fitness"), eoc])[0][0], "Fitness")
        covered = priced("giveback", amount="", cost_kind="covered")
        self.assertEqual(present.extra_benefits("", [covered], part_b=True), [("", [])])
        _, aside = present.explain("", [covered], "J_extra_benefits", "dvha")
        self.assertEqual(aside[facts.identity(covered)], ["it gives no amount"])

    def test_without_fitness_leaves_it_to_alternative_care(self):
        gym, foot = routine("fitness"), routine("foot_care", page="9")
        bucks = routine("fitness", "allowance", "$150", pool="Wellness Bucks", limit="per year", page="8")
        self.assertEqual(present.extra_benefits("", [gym, bucks, foot], prices=True, programs=True, fitness=False),
                         [("Routine foot care $0", [foot])])
        _, aside = present.explain("", [gym, foot], "J_extra_benefits", "dvha")
        self.assertEqual(aside[facts.identity(gym)], ["Alternative Care / OTC / Travel shows fitness"])

    def test_with_part_d_ends_by_saying_when_a_plan_has_no_part_d(self):
        none = landscape("part_d_deductible", "not_covered")
        self.assertEqual(present.extra_benefits("", [routine("fitness"), none], part_d=True),
                         [("Fitness; No Part D coverage", [routine("fitness"), none])])
        self.assertEqual(present.extra_benefits("", [none]), [("", [])])
        self.assertEqual(present.extra_benefits("", [landscape("part_d_deductible", "deductible", "$0")], part_d=True),
                         [("", [])])

    def test_names_cards_for_chronic_conditions_and_programs_after_heart_failure(self):
        found = [routine("other_supplemental", "allowance", "$30", pool="Food & Home Card", limit="per month",
                         condition="chronically ill members"),
                 routine("other_supplemental", pool="Virtual Cardiac Recovery Program", condition="recent heart failure"),
                 routine("meals", condition="After your inpatient stay for Congestive Heart Failure")]
        self.assertEqual(column(present.extra_benefits, *found)[0][0],
                         "For members with certain chronic conditions: Food & Home Card $30/month; "
                         "After a heart-failure hospital stay: Virtual Cardiac Recovery Program, home-delivered meals")


def presented_cells(data, column, version):
    return {p: [value for value, _ in got] for p, got in present.lines(data, column, version=version).items()}


def pinned(data):
    """A candidate run tests the committed data, so these tests use the pinned version."""
    return present.current(data, candidate="")


def shown(lines, line):
    return " | ".join(lines).removesuffix(" | ") if not line else lines[int(line) - 1]


class WriteTest(unittest.TestCase):
    def test_writes_the_sheets_their_citations_and_caveats(self):
        row, caveat = dict.fromkeys(sheets.COLUMNS, "x"), dict.fromkeys(sheets.NOTE_COLUMNS, "c")

        def sheet_rows(data, sheet, version):
            return [dict.fromkeys(["section", "plan_id", "plan_name"] + list(fields.labels(sheet)), f"{sheet} {version}")]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(present, "citation_rows", lambda data, version: [row] * version), \
                mock.patch.object(present, "caveat_rows", lambda data, version: [caveat] * version), \
                mock.patch.object(present, "sheet_rows", sheet_rows):
            os.makedirs(f"{tmp}/generated")
            present.write(pathlib.Path(tmp), 1)
            self.assertEqual(sheets.rows(pathlib.Path(tmp, sheets.PRESENTED)), [row])
            self.assertEqual(sheets.rows(pathlib.Path(tmp, sheets.CAVEATS)), [caveat])
            self.assertEqual(sheets.read(pathlib.Path(tmp))["dvha"], sheet_rows(None, "dvha", 1))
            self.assertTrue(pathlib.Path(tmp, "generated", sheets.SHEETS["main"]).read_bytes().endswith(b"main 1\r\n"))

    @built.check
    def test_a_blank_with_cited_facts_writes_rows(self):
        data = years.data_dir(YEAR)
        f = facts.read(data / "machine/document_facts.csv")[0]
        plan = f["plan_id"]
        with mock.patch.object(present, "lines", lambda data, column, sheet, version: {plan: [("", [f])]}), \
                mock.patch.dict(present.SHEETS, {"main": ({"S_acupuncture": None}, {}), "dvha": ({}, {})}):
            rows = present.citation_rows(data)
        self.assertEqual({(r["plan_id"], r["column"], r["value"]) for r in rows}, {(plan, "S_acupuncture", "")})

    @built.check
    def test_a_version_skips_the_cells_it_holds(self):
        data = years.data_dir(YEAR)
        cell = ("K_tests_labs", "H2923-009-0")
        cells = {v: {(r["column"], r["plan_id"]) for r in present.citation_rows(data, v)} for v in (1, 2)}
        self.assertEqual(cells[2] - cells[1], {cell})

    @built.check
    def test_version_4_presents_dvha_vision_and_hearing_and_holds_some_hearing_cells(self):
        data = years.data_dir(YEAR)
        cells = {v: {(r["sheet"], r["column"], r["plan_id"]) for r in present.citation_rows(data, v)} for v in (3, 4)}
        self.assertEqual({c[:2] for c in cells[4] - cells[3]}, {("dvha", "G_vision"), ("dvha", "H_hearing")})
        self.assertNotIn(("dvha", "H_hearing", "H6815-038-0"), cells[4])

    @built.check
    def test_version_5_presents_dvha_packages(self):
        data = years.data_dir(YEAR)
        cells = {v: {(r["sheet"], r["column"]) for r in present.citation_rows(data, v)} for v in (4, 5)}
        self.assertEqual(cells[5] - cells[4], {("dvha", "E_optional_packages")})

    def test_version_7_releases_dvha_cells_whose_rule_only_leaves_details_out(self):
        released = set(present.VERSIONS[6]) - set(present.VERSIONS[7])
        self.assertIn(("dvha.H_hearing", "H6815-038-0"), released)
        self.assertIn(("dvha.J_extra_benefits", "H2923-001-0"), released)
        self.assertIn(("dvha.F_dental", "H2056-003-0"), released)
        self.assertIn(("dvha.F_dental", "H6815-038-0"), present.VERSIONS[7])
        self.assertIn(("dvha.I_alt_care_otc_travel", "H9003-001-0"), present.VERSIONS[7])
        self.assertLessEqual(set(present.VERSIONS[7]), set(present.VERSIONS[6]))

    def test_version_8_holds_only_main_cells_whose_facts_misread_a_price(self):
        held_main = {c for c in present.VERSIONS[8] if not c[0].startswith("dvha.")}
        self.assertEqual(held_main, {("K_tests_labs", "H6815-038-0"), ("K_tests_labs", "H5439-019-0")})
        self.assertLessEqual(set(present.VERSIONS[8]), set(present.VERSIONS[7]))

    @built.check
    def test_version_9_presents_the_main_premium_moop_and_drug_deductible(self):
        data = years.data_dir(YEAR)
        cells = {v: {(r["sheet"], r["column"]) for r in present.citation_rows(data, v)} for v in (8, 9)}
        self.assertEqual(cells[9] - cells[8], {("main", "C_premium"), ("main", "E_moop"), ("main", "N_pharmacy_deductible")})

    def test_version_11_presents_the_cell_version_10_holds_for_review(self):
        self.assertEqual(set(present.VERSIONS[10]) - set(present.VERSIONS[11]), {
            ("O_medical_deductible", "H2001-045-0"), ("dvha.F_dental", "H2406-042-0"), ("dvha.F_dental", "H3805-041-0"),
            ("dvha.I_alt_care_otc_travel", "H5216-048-0"), ("dvha.I_alt_care_otc_travel", "H5216-427-2"),
            ("dvha.I_alt_care_otc_travel", "H5216-455-0")})
        self.assertLessEqual(set(present.VERSIONS[11]), set(present.VERSIONS[10]))

    def test_version_14_presents_the_cells_whose_facts_document_facts_17_fixes(self):
        self.assertEqual(set(present.VERSIONS[13]) - set(present.VERSIONS[14]), {
            ("dvha.F_dental", "H2923-025-0"), ("dvha.I_alt_care_otc_travel", "H5216-048-0"),
            ("dvha.I_alt_care_otc_travel", "H5216-455-0")})
        self.assertLessEqual(set(present.VERSIONS[14]), set(present.VERSIONS[13]))

    def test_version_15_holds_no_cell(self):
        self.assertEqual(present.VERSIONS[15], {})

    def test_the_pinned_version_ignores_the_candidate(self):
        data = years.data_dir(YEAR)
        pinned_version = json.loads((data / "steps.json").read_text())["present"]
        with mock.patch.dict(os.environ, {present.CANDIDATE: "present@16"}):
            self.assertEqual(present.current(data), 16)
            self.assertEqual(present.current(data, candidate=""), pinned_version)

    def test_version_16_holds_no_cell(self):
        self.assertEqual(present.VERSIONS[16], {})

    @built.check
    def test_version_17_holds_no_cell_and_shows_package_allowances_only_from_17(self):
        self.assertEqual(present.VERSIONS[17], {})
        data = years.data_dir(YEAR)
        found = [routine("packages", "premium", "$9", package="P", plan_id=p["plan_id"]) for p in present.plans(data)[:1]]
        found.append(routine("vision.eyewear", "allowance", "$175", package="P", plan_id=found[0]["plan_id"]))
        got = {v: present.lines(data, "E_optional_packages", found, "dvha", v)[found[0]["plan_id"]][0][0] for v in (16, 17)}
        self.assertEqual(got, {16: "P $9/mo", 17: "P $9/mo, eyewear $175"})
        explained = {v: present.explain("", found, "E_optional_packages", "dvha", v)[0][0][0] for v in (16, 17)}
        self.assertEqual(explained, got)

    @built.check
    def test_version_17_changes_only_the_kaiser_package_cells(self):
        data = years.data_dir(YEAR)
        rows = {v: {(r["sheet"], r["column"], r["plan_id"], r["value"]) for r in present.citation_rows(data, v)} for v in (16, 17)}
        self.assertEqual({r[:3] for r in rows[16] ^ rows[17]},
                         {("dvha", "E_optional_packages", p) for p in ("H9003-001-0", "H9003-006-0", "H9003-009-0")})
        sheets = {v: present.sheet_rows(data, "dvha", v) for v in (16, 17)}
        self.assertEqual([r["plan_id"] for r, s in zip(*sheets.values()) if r != s], ["H9003-001-0", "H9003-006-0", "H9003-009-0"])

    @built.check
    def test_version_19_moves_package_benefits_to_their_columns_and_lists_hearing_aid_copays(self):
        self.assertEqual(present.VERSIONS[19], {})
        data = years.data_dir(YEAR)
        rows = {v: {(r["sheet"], r["column"], r["plan_id"], r["value"]) for r in present.citation_rows(data, v)} for v in (18, 19)}
        changed = {r[:3] for r in rows[18] ^ rows[19]}
        self.assertEqual({c for _, c, _ in changed},
                         {"E_optional_packages", "F_dental", "G_vision", "H_hearing", "I_alt_care_otc_travel",
                          "J_extra_benefits"})
        self.assertIn(("dvha", "F_dental", "H9003-009-0"), changed)
        self.assertIn(("dvha", "H_hearing", "H2923-001-0"), changed)
        got = {v: present.lines(data, "H_hearing", sheet="dvha", version=v)["H2923-001-0"][0][0] for v in (18, 19)}
        self.assertEqual(got, {18: "exam $0; aids $399-$699; 2 aids", 19: "exam $0; aids $399 or $699 per aid; 2 aids"})
        got = {v: present.lines(data, "E_optional_packages", sheet="dvha", version=v)["H9003-009-0"][0][0] for v in (16, 18, 19)}
        self.assertEqual(got[19], "Advantage Plus $54/mo")
        self.assertEqual(len(set(got.values())), 3)

    @built.check
    def test_version_20_names_programs_and_says_when_otc_pays_for_food(self):
        self.assertEqual(present.VERSIONS[20], {})
        data = years.data_dir(YEAR)
        rows = {v: {(r["sheet"], r["column"], r["plan_id"], r["value"]) for r in present.citation_rows(data, v)} for v in (19, 20)}
        self.assertEqual({r[1] for r in rows[19] ^ rows[20]}, {"I_alt_care_otc_travel", "J_extra_benefits"})
        got = {v: present.lines(data, "J_extra_benefits", sheet="dvha", version=v)["H9003-001-0"][0][0] for v in (19, 20)}
        self.assertEqual({v: g.split(";")[0] for v, g in got.items()}, {19: "Fitness $0", 20: "Fitness One Pass $0"})
        got = {v: present.lines(data, "I_alt_care_otc_travel", sheet="dvha", version=v)["H2001-045-0"][0][0] for v in (19, 20)}
        self.assertEqual([g.split(";")[0] for g in got.values()], ["OTC $196/month", "OTC and food $196/month"])

    @built.check
    def test_version_21_shows_preventive_dental_limits_and_each_program_once(self):
        self.assertEqual(present.VERSIONS[21], {})
        data = years.data_dir(YEAR)
        rows = {v: {(r["sheet"], r["column"], r["plan_id"], r["value"]) for r in present.citation_rows(data, v)} for v in (20, 21)}
        self.assertEqual({r[1] for r in rows[20] ^ rows[21]}, {"F_dental", "J_extra_benefits"})
        got = present.lines(data, "F_dental", sheet="dvha", version=21)["H5439-015-0"][0][0]
        self.assertIn("PREV limits: cleanings 2/year", got)

    @built.check
    def test_version_22_says_none_shows_the_giveback_and_shared_allowances(self):
        self.assertEqual(present.VERSIONS[22], {})
        data = years.data_dir(YEAR)
        rows = {v: {(r["sheet"], r["column"], r["plan_id"], r["value"]) for r in present.citation_rows(data, v)} for v in (21, 22)}
        self.assertEqual({r[1] for r in rows[21] ^ rows[22]},
                         {"F_dental", "G_vision", "H_hearing", "I_alt_care_otc_travel", "J_extra_benefits"})
        got = {c: present.lines(data, c, sheet="dvha", version=22)[p][0][0] for c, p in (
            ("F_dental", "H3805-048-0"), ("I_alt_care_otc_travel", "H2923-019-0"), ("J_extra_benefits", "H2923-025-0"))}
        self.assertTrue(got["F_dental"].startswith("None. With Platinum Dental Rider: "))
        self.assertTrue(got["I_alt_care_otc_travel"].startswith(
            "Acup, Massage, Naturopath 50% from $2,000/year allowance shared with dental; OTC $106/three months"))
        self.assertTrue(got["J_extra_benefits"].startswith("Part B giveback $70/month; "))

    @built.check
    def test_version_23_shows_worldwide_urgent_care_and_hearing_details(self):
        self.assertEqual(present.VERSIONS[23], {})
        data = years.data_dir(YEAR)
        rows = {v: {(r["sheet"], r["column"], r["plan_id"], r["value"]) for r in present.citation_rows(data, v)} for v in (22, 23)}
        self.assertEqual({r[1] for r in rows[22] ^ rows[23]}, {"H_hearing", "I_alt_care_otc_travel"})
        got = {(c, p): present.lines(data, c, sheet="dvha", version=23)[p][0][0] for c, p in (
            ("H_hearing", "H2056-003-0"), ("H_hearing", "H2923-001-0"), ("I_alt_care_otc_travel", "H2056-003-0"),
            ("I_alt_care_otc_travel", "H5216-455-0"))}
        self.assertTrue(got[("H_hearing", "H2056-003-0")].startswith("exam $0/year; "))
        self.assertIn("; fitting $0; 60-day trial, 3-year warranty, 80 batteries per aid", got[("H_hearing", "H2923-001-0")])
        self.assertIn("Worldwide ER/urgent $130, $250,000 max", got[("I_alt_care_otc_travel", "H2056-003-0")])
        self.assertIn("Worldwide ER $130, urgent care $50", got[("I_alt_care_otc_travel", "H5216-455-0")])

    @built.check
    def test_version_27_shows_exam_maximums_out_of_network_programs_and_no_part_d(self):
        self.assertEqual(present.VERSIONS[27], {})
        data = years.data_dir(YEAR)
        rows = {v: {(r["sheet"], r["column"], r["plan_id"], r["value"]) for r in present.citation_rows(data, v)} for v in (26, 27)}
        self.assertEqual({r[1] for r in rows[26] ^ rows[27]}, {"G_vision", "J_extra_benefits"})
        self.assertEqual(present.lines(data, "G_vision", sheet="dvha", version=27)["H5216-455-0"][0][0],
                         "exam $0/year; eyewear $75/year ($150 at PLUS providers); exam max $75/year; 1 pair/year; "
                         "no rollover; OON exam $0; Humana Medicare Insight Network")
        extras = present.lines(data, "J_extra_benefits", sheet="dvha", version=27)
        self.assertIn("; Medicare Explorer by Kaiser Permanente max $1,200/year; ", extras["H9003-001-0"][0][0])
        self.assertEqual({p for p, got in extras.items() if got[0][0].endswith("; No Part D coverage")},
                         {"H2406-073-0", "H5216-455-0", "H5216-427-2", "H3817-010-0", "H2056-018-0", "H5439-010-0",
                          "H7006-021-0"})

    @built.check
    def test_version_29_shows_every_in_network_price(self):
        self.assertEqual(present.VERSIONS[29], {})
        data = years.data_dir(YEAR)
        rows = {v: {(r["sheet"], r["column"], r["plan_id"], r["line"], r["value"]) for r in present.citation_rows(data, v)}
                for v in (28, 29)}
        self.assertEqual({r[1] for r in rows[28] ^ rows[29]},
                         {"F_primary_care", "G_specialist", "I_outpatient_surgery", "K_tests_labs", "L_xray_imaging",
                          "M_part_b_drugs"})
        got = present.lines(data, "M_part_b_drugs", sheet="main", version=29)["H2056-018-0"][0][0]
        self.assertEqual(got, "$0-$35 or 20%")

    def test_a_fitness_allowance_of_its_own_shows_with_its_renewal(self):
        def gym(amount, **more):
            return fact("fitness", covered_by="supplemental", cost_kind="allowance", amount=amount,
                        limit="every six months", **more)
        self.assertEqual(present.named_extras([gym("$120")], ("fitness",), prices=True, allowances=True)[0],
                         ["Fitness $120/six months"])
        self.assertEqual(present.named_extras([gym("$120")], ("fitness",), prices=True)[0], ["Fitness"])
        self.assertEqual(present.named_extras([gym("$150", pool="Wellness Bucks")], ("fitness",), prices=True,
                                              allowances=True)[0], ["Fitness"])

    @built.check
    def test_version_31_shows_rewards_hearing_and_dental_details(self):
        self.assertEqual(present.VERSIONS[31], {})
        data = years.data_dir(YEAR)
        rows = {v: {(r["sheet"], r["column"], r["plan_id"], r["value"]) for r in present.citation_rows(data, v)} for v in (30, 31)}
        self.assertEqual({r[:2] for r in rows[30] ^ rows[31]},
                         {("dvha", "F_dental"), ("dvha", "H_hearing"), ("dvha", "J_extra_benefits")})
        got = {c: present.lines(data, c, sheet="dvha", version=31)["H7199-002-0"][0][0] for c in ("F_dental", "H_hearing")}
        self.assertTrue(got["H_hearing"].endswith("; OON exam $35, fitting $35, aids 90%"))
        self.assertIn("; no rollover", got["F_dental"])

    def test_a_programs_rewards_show_per_step(self):
        def reward(amount, condition):
            return fact("other_supplemental", covered_by="supplemental", cost_kind="allowance", amount=amount,
                        pool="Devoted Dollars", condition=condition)
        program = fact("other_supplemental", covered_by="supplemental", cost_kind="covered", amount="", pool="Devoted Dollars")
        found = [program, reward("$20", "a flu shot"), reward("$50", "a check-up"), reward("$0-$10", "a survey"),
                 reward("$100", "members with chronic conditions")]
        self.assertEqual(present.other_programs(found, steps=True)[0],
                         ["Devoted Dollars ($50 for a check-up, $20 for a flu shot, $0-$10 for a survey)"])
        self.assertEqual(present.other_programs(found)[0], ["Devoted Dollars"])
        priced = dict(program, cost_kind="copay", amount="$5")
        self.assertEqual(present.other_programs([priced] + found[1:], steps=True)[0], ["Devoted Dollars $5"])

    def test_dental_details_show_reimbursement_and_exclusions(self):
        def detail(condition, cost_kind, limit=""):
            return fact("dental", covered_by="supplemental", cost_kind=cost_kind, amount="", condition=condition, limit=limit)
        self.assertEqual(present.dental_exclusions([detail("excludes", "not_covered", "implants, cosmetic procedures")])[0],
                         "excludes implants, cosmetic procedures")
        self.assertEqual(present.dental_exclusions([detail("excludes", "not_covered", "implants"),
                                                    dict(detail("excludes", "not_covered", "implants"), page="61")])[0],
                         "excludes implants")
        self.assertEqual(present.dental_exclusions([detail("excludes", "covered", "implants")])[0], "")
        self.assertEqual(present.dental_reimbursement([detail("reimbursement", "covered", "pay up front")])[0],
                         "pay up front, then reimbursed")
        self.assertEqual(present.dental_reimbursement([detail("rollover", "covered")])[0], "")

    def test_dental_exclusions_can_prefer_the_summary_of_benefits_short_list(self):
        def excludes(limit, source):
            return fact("dental", covered_by="supplemental", cost_kind="not_covered", amount="", condition="excludes",
                        limit=limit, source=source)
        found = [excludes("procedure codes not listed in the chart", "EOC"), excludes("implants, cosmetic procedures", "SB")]
        self.assertEqual(present.dental_exclusions(found, summary_first=True)[0], "excludes implants, cosmetic procedures")
        self.assertEqual(present.dental_exclusions(found)[0], "excludes procedure codes not listed in the chart")
        self.assertEqual(present.dental_exclusions(found[:1], summary_first=True)[0],
                         "excludes procedure codes not listed in the chart")

    @built.check
    def test_version_32_shows_devoted_dental_exclusions_from_the_summary_of_benefits(self):
        self.assertEqual(present.VERSIONS[32], {})
        data = years.data_dir(YEAR)
        got = {v: present.lines(data, "F_dental", sheet="dvha", version=v) for v in (31, 32)}
        changed = {p for p in got[32] if got[31][p] != got[32][p]}
        self.assertTrue(changed)
        self.assertTrue(all(p.startswith(("H2923-", "H7199-")) for p in changed), changed)
        self.assertIn("excludes Cosmetic procedures, dental implants, elective procedures", got[32]["H2923-001-0"][0][0])

    @built.check
    def test_version_34_names_no_narrow_dental_services_beside_a_broader_price(self):
        self.assertEqual(present.VERSIONS[34], {})
        data = years.data_dir(YEAR)
        got = {v: present.lines(data, "F_dental", sheet="dvha", version=v) for v in (33, 34)}
        changed = {p for p in got[34] if got[33][p] != got[34][p]}
        self.assertEqual(changed, {"H5439-011-0"})
        self.assertTrue(got[34]["H5439-011-0"][0][0].startswith("PREV $0; COMP $0; COMP max $1,000/year"))

    @built.check
    def test_version_36_names_the_only_comprehensive_dental_services_a_schedule_lists(self):
        self.assertEqual(present.VERSIONS[36], {})
        data = years.data_dir(YEAR)
        got = {v: present.lines(data, "F_dental", sheet="dvha", version=v) for v in (35, 36)}
        changed = {p for p in got[36] if got[35][p] != got[36][p]}
        self.assertEqual(changed, {"H5439-015-0", "H5439-019-0", "H6815-038-0"})
        self.assertEqual({got[36][p][0][0].split("; ")[1] for p in changed}, {"COMP $0 (teledentistry only)"})

    def test_dental_rollover_shows_only_with_an_allowance_or_maximum(self):
        never = fact("dental", covered_by="supplemental", cost_kind="not_covered", amount="", condition="rollover")
        maximum = fact("dental", covered_by="supplemental", cost_kind="max", amount="$1,000")
        self.assertEqual(present.dental_rollover([maximum, never])[0], "no rollover")
        self.assertEqual(present.dental_rollover([never])[0], "")
        self.assertEqual(present.dental_rollover([dict(maximum, package="Optional Dental"), never])[0], "")

    def test_hearing_details_can_show_a_rechargeable_aids_extra_price(self):
        upgrade = fact("hearing.aids", covered_by="supplemental", amount="$50", condition="rechargeable", unit="per aid")
        self.assertEqual(present.hearing_details([upgrade], rechargeable=True)[0], "$50 more per aid for rechargeable")
        self.assertEqual(present.hearing_details([upgrade])[0], "")

    def test_out_of_network_can_take_a_service_by_its_condition(self):
        fitting = fact("hearing.exam", network="out", covered_by="supplemental", amount="$35", condition="fitting/evaluation")
        self.assertEqual(present.HEARING_OON_31([fitting])[0], "OON fitting $35")
        self.assertEqual(present.HEARING_OON([fitting])[0], "")

    @built.check
    def test_version_30_shows_a_fitness_allowance(self):
        self.assertEqual(present.VERSIONS[30], {})
        data = years.data_dir(YEAR)
        got = {v: present.lines(data, "I_alt_care_otc_travel", sheet="dvha", version=v) for v in (29, 30)}
        self.assertEqual({p for p in got[30] if got[29][p] != got[30][p]}, {"H7006-018-0", "H7006-021-0"})
        self.assertTrue(got[30]["H7006-018-0"][0][0].startswith("Fitness $120/six months; "))
        self.assertTrue(got[30]["H7006-021-0"][0][0].startswith("Fitness $100/three months; "))

    @built.check
    def test_version_28_moves_fitness_to_alternative_care(self):
        self.assertEqual(present.VERSIONS[28], {})
        data = years.data_dir(YEAR)
        got = {c: present.lines(data, c, sheet="dvha", version=28)["H2923-001-0"][0][0]
               for c in ("I_alt_care_otc_travel", "J_extra_benefits")}
        self.assertTrue(got["I_alt_care_otc_travel"].startswith("Fitness SilverSneakers $0; Wellness Bucks $150/year; Acup"))
        self.assertEqual(got["J_extra_benefits"], "For members with certain chronic conditions: Food & Home Card $30/month")

    @built.check
    def test_version_26_names_the_dental_network(self):
        self.assertEqual(present.VERSIONS[26], {})
        data = years.data_dir(YEAR)
        rows = {v: {(r["sheet"], r["column"], r["plan_id"], r["value"]) for r in present.citation_rows(data, v)} for v in (25, 26)}
        self.assertEqual({r[1] for r in rows[25] ^ rows[26]}, {"F_dental"})
        got = present.lines(data, "F_dental", sheet="dvha", version=26)["H2056-003-0"][0][0]
        self.assertEqual(got, "PREV $0; no annual max; Aetna Dental PPO Network; no COMP")

    @built.check
    def test_version_25_shows_a_comprehensive_dental_range_from_per_service_prices(self):
        self.assertEqual(present.VERSIONS[25], {})
        data = years.data_dir(YEAR)
        rows = {v: {(r["sheet"], r["column"], r["plan_id"], r["value"]) for r in present.citation_rows(data, v)} for v in (24, 25)}
        self.assertEqual({(r[1], r[2]) for r in rows[24] ^ rows[25]}, {("F_dental", "H1036-306-0")})
        got = present.lines(data, "F_dental", sheet="dvha", version=25)["H1036-306-0"][0][0]
        self.assertTrue(got.startswith("PREV $0; COMP $0-50%; max $4,000/year"))

    @built.check
    def test_version_24_shows_rollover_otc_uses_eyewear_pairs_networks_and_no_dental_maximum(self):
        self.assertEqual(present.VERSIONS[24], {})
        data = years.data_dir(YEAR)
        rows = {v: {(r["sheet"], r["column"], r["plan_id"], r["value"]) for r in present.citation_rows(data, v)} for v in (23, 24)}
        self.assertEqual({r[1] for r in rows[23] ^ rows[24]}, {"F_dental", "G_vision", "I_alt_care_otc_travel"})
        got = {(c, p): present.lines(data, c, sheet="dvha", version=24)[p][0][0] for c, p in (
            ("F_dental", "H6815-038-0"), ("G_vision", "H5216-428-2"), ("I_alt_care_otc_travel", "H1036-317-0"))}
        self.assertIn("; no annual max;", got[("F_dental", "H6815-038-0")])
        self.assertIn("; 1 pair/year; no rollover;", got[("G_vision", "H5216-428-2")])
        self.assertIn("(rolls over until year-end; also for groceries, utilities and rent for some members)",
                      got[("I_alt_care_otc_travel", "H1036-317-0")])

    def test_version_12_holds_no_cell(self):
        self.assertEqual(present.held(years.data_dir(YEAR), 12), {})

    def test_a_held_main_cell_does_not_hold_the_dvha_cell_of_the_same_name(self):
        self.assertNotEqual(present.cell("main", "C_premium", "H1"), present.cell("dvha", "C_premium", "H1"))

    @built.check
    def test_version_3_presents_the_dvha_premium(self):
        data = years.data_dir(YEAR)
        cells = {v: {(r["sheet"], r["column"]) for r in present.citation_rows(data, v)} for v in (2, 3)}
        self.assertEqual(cells[3] - cells[2], {("dvha", "C_premium")})

    @mock.patch.dict(os.environ, {present.CANDIDATE: ""})
    def test_the_pinned_version_holds_its_cells(self):
        data = years.data_dir(YEAR)
        self.assertEqual(present.held(data), present.held(data, json.loads((data / "steps.json").read_text())["present"]))
        latest = max(present.VERSIONS)
        self.assertEqual(present.held(data, latest), present.VERSIONS[latest])
        with mock.patch.dict(os.environ, {present.CANDIDATE: f"document_facts@1, present@{latest}"}):
            self.assertEqual(present.held(data), present.VERSIONS[latest])

    def test_a_held_reason_does_not_imply_that_people_read_the_documents(self):
        for why in (why for held in present.VERSIONS.values() for why in held.values()):
            self.assertNotIn("reader", why)

    @built.check
    def test_a_trailing_blank_line_writes_no_row(self):
        data = years.data_dir(YEAR)
        f = facts.read(data / "machine/document_facts.csv")[0]
        with mock.patch.object(present, "lines", lambda data, column, sheet, version: {f["plan_id"]: [("$1", [f]), ("", [f])]}), \
                mock.patch.dict(present.SHEETS, {"main": ({"S_acupuncture": None}, {}), "dvha": ({}, {})}):
            rows = present.citation_rows(data)
        self.assertEqual({(r["line"], r["value"]) for r in rows}, {("", "$1")})


# Lines where the rule and an edit disagree. The rule wins on X-ray lines (#127 has the evidence).
# Edits stay on the other lines until document facts support them.
TRIAGED = {
    ("L_xray_imaging", "H2056-003-0", "2"): "the expert's $0 mammogram rule covers Aetna",
    ("L_xray_imaging", "H2056-018-0", "2"): "the expert's $0 mammogram rule covers Aetna",
    ("L_xray_imaging", "H7199-002-0", ""): "the EOC prices X-rays at $25; the SB's $0 is for ultrasounds",
    **{("AB_ambulance", p, "1"): "readers miss the $0 home treatment plan ambulance trip because the EOC states "
       "the $0 on the page before"
       for p in ("H9003-001-0", "H9003-006-0", "H9003-009-0")},
    **{("I_outpatient_surgery", p, line): "the EOC gives one price for every setting; the SB's $0 is for other services"
       for p in ("H9003-001-0", "H9003-006-0", "H9003-009-0") for line in ("1", "2")},
}


class SheetTest(unittest.TestCase):
    def test_a_cell_joins_its_lines_without_trailing_blank_ones(self):
        self.assertEqual(present.shown([("$0", []), ("", [])]), "$0")
        self.assertEqual(present.shown([("", []), ("$5", [])]), " | $5")
        self.assertEqual(present.shown([("", [])]), "")
        self.assertEqual(present.shown([]), "")

    @built.check
    def test_the_committed_sheets_are_current(self):
        data = years.data_dir(YEAR)
        pinned = json.loads((data / "steps.json").read_text())["present"]
        for sheet in sheets.SHEETS:
            self.assertEqual(sheets.read(data)[sheet], present.sheet_rows(data, sheet, pinned), sheet)

    @built.check
    def test_a_held_cell_is_blank(self):
        data = years.data_dir(YEAR)
        row = next(r for r in present.sheet_rows(data, "dvha", 10) if r["plan_id"] == "H5216-048-0")
        self.assertEqual(row["E_optional_packages"], "")
        self.assertTrue(row["G_vision"])

    @built.check
    def test_a_sheet_has_a_row_per_plan_and_the_columns_of_fields(self):
        data = years.data_dir(YEAR)
        rows = present.sheet_rows(data, "dvha")
        self.assertEqual([r["plan_id"] for r in rows], [p["plan_id"] for p in sheets.rows(data / "generated/plans.csv")])
        self.assertEqual(list(rows[0]), ["section", "plan_id", "plan_name"] + list(fields.labels("dvha")))


class ExpectedTest(unittest.TestCase):
    @built.check
    def test_the_committed_citations_are_current(self):
        data = years.data_dir(YEAR)
        pinned = json.loads((data / "steps.json").read_text())["present"]
        self.assertEqual(sheets.rows(data / sheets.PRESENTED), present.citation_rows(data, pinned))

    @built.check
    def test_present_17_presents_every_expected_line(self):
        """The expected cells follow the expert's provisional rules, which present 18 replaced with the final chart's."""
        data = years.data_dir(YEAR)
        for column in present.COLUMNS:
            cells = presented_cells(data, column, version=17)
            wanted = {(w["plan_id"], w["line"]): w["value"] for w in expected.load() if w["column"] == column}
            missed = [(p, line, value, cells.get(p)) for (p, line), value in wanted.items()
                      if (column, p, line) not in TRIAGED and (column, p) not in present.held(data, 17)
                      and shown(cells.get(p, ["", ""]), line) != value]
            self.assertEqual(missed, [], column)
            self.assertTrue(all(shown(cells[p], line) != wanted[p, line] for c, p, line in TRIAGED if c == column))

    @built.check
    def test_every_nonblank_or_cited_line_cites_a_document(self):
        data = years.data_dir(YEAR)
        rows, version = present.citation_rows(data, pinned(data)), pinned(data)
        self.assertTrue(rows and all(r["url"] and r["quote"] for r in rows))
        generated = {r["plan_id"]: r for r in sheets.read(data)["main"]}
        for column in present.COLUMNS:
            self.assertEqual({(r["plan_id"], r["line"]) for r in rows if (r["sheet"], r["column"]) == ("main", column)},
                             {(p, str(n) if " | " in generated[p][column] else "")
                              for p, got in present.lines(data, column, version=version).items()
                              if (column, p) not in present.held(data, version)
                              for n, (v, cited) in enumerate(got, 1) if v and not cited or present.presents(cited)})


class DvhaTest(unittest.TestCase):
    @built.check
    def test_every_column_cites_a_cell_it_does_not_hold(self):
        data = years.data_dir(YEAR)
        held = present.held(data, pinned(data))
        for column in present.DVHA:
            self.assertTrue([p for p, ((_, cited),) in present.lines(data, column, sheet="dvha", version=pinned(data)).items()
                             if present.cell("dvha", column, p) not in held and cited], column)


class ExplainTest(unittest.TestCase):
    def set_aside(self, column, *found):
        found = [dict(f, fact_id=f["amount"]) for f in found]
        got, aside = present.explain("Humana", list(found), column, version=17)
        self.assertEqual(got, present.rule("main", column, 17)("Humana", list(found)))
        return {f["amount"]: aside[facts.identity(f)] for f in found if facts.identity(f) in aside}

    def test_says_which_filter_set_each_fact_aside(self):
        eoc = fact(amount="$10")
        self.assertEqual(self.set_aside("L_xray_imaging", eoc, fact(amount="$20", source="SB", page="3"),
                                        fact(amount="$30", network="out"), fact(amount="$40", condition="QMB"),
                                        fact(amount="$50", setting="outpatient_hospital")), {
            "$20": ["SB ranks below EOC"], "$30": ["network is 'out'"], "$40": ["condition is 'QMB'"],
            "$50": ["setting 'outpatient_hospital' is not 'office.pcp' or 'office.specialist'"]})

    def test_names_every_field_that_made_a_filter_reject_a_fact(self):
        self.assertEqual(self.set_aside("L_xray_imaging", fact(amount="$5"), fact(amount="$9", network="out", condition="QMB")),
                         {"$9": ["network is 'out' and condition is 'QMB'"]})

    def test_a_trip_within_the_us_gets_no_reason_from_the_line_for_trips_abroad(self):
        self.assertEqual(self.set_aside("AB_ambulance", fact("ambulance.ground", amount="$250"),
                                        fact("ambulance.ground", amount="$300", source="SB", page="3")),
                         {"$300": ["SB ranks below EOC"]})

    def test_says_why_a_dot_column_skips_a_medicare_fact(self):
        self.assertEqual(self.set_aside("V_massage", fact("extras.massage", amount="$5"),
                                        fact("extras.massage", amount="$9", covered_by="supplemental")),
                         {"$5": ["covered_by is 'medicare'"]})

    def test_gives_the_filters_own_reason_when_no_field_explains_it(self):
        self.assertEqual(self.set_aside("M_part_b_drugs", fact("part_b_drugs.chemo", cost_kind="coinsurance", amount="20%"),
                                        fact("part_b_drugs.chemo", amount="$5")),
                         {"$5": ["it is not a coinsurance or $0 copay for a Part B drug"]})

    def test_says_why_the_rule_dropped_a_fact_after_its_filters(self):
        self.assertEqual(self.set_aside("H_inpatient", fact("inpatient.acute", amount="$300", unit="per day", limit="days 1-5"),
                                        fact("inpatient.acute", amount="$0", unit="per day", limit="days 6+")),
                         {"$0": ["line 1 shows the days that cost more than $0"]})

    def test_says_why_each_filter_set_a_fact_aside(self):
        def f(benefit, setting="any", amount="$25", **more):
            return fact(benefit, setting, amount, **more)
        supplemental = dict(covered_by="supplemental")
        cases = [
            ("I_outpatient_surgery", "Aetna", [f("surgery.colonoscopy", "outpatient_hospital", "$0")],
             {"$0": ["the 'asc' line counts only a price at 'asc' itself", "the 'outpatient_hospital' line has no surgery price"]}),
            ("I_outpatient_surgery", "Aetna", [f("surgery", "asc", "$50"), f("surgery.colonoscopy", "asc", "$20")],
             {"$20": ["only a $0 colonoscopy or skin biopsy counts",
                      "the 'outpatient_hospital' line counts only a price at 'outpatient_hospital' itself"]}),
            ("O_medical_deductible", "Aetna", [f("medical_deductible.part_b", cost_kind="covered", amount="")],
             {"": ["the column shows the Part B deductible only beside a plan deductible"]}),
            ("O_medical_deductible", "Aetna", [f("medical_deductible", cost_kind="deductible", amount="$0"),
                                               f("medical_deductible.part_b", cost_kind="deductible", amount="$257")],
             {"$257": ["only a covered Part B deductible counts"]}),
            ("O_medical_deductible", "Aetna", [f("medical_deductible", cost_kind="deductible", amount="$0"),
                                               f("medical_deductible.part_b", cost_kind="covered", amount="")],
             {"": ["a $0 deductible won"]}),
            ("AA_opt_packages", "Aetna", [f("packages", covered_by="medicare", cost_kind="not_covered", amount="")],
             {"": ["covered_by is 'medicare'"]}),
            ("AA_opt_packages", "Aetna", [f("packages", **supplemental, cost_kind="not_covered", amount="", network="out")],
             {"": ["network is 'out'"]}),
            ("AA_opt_packages", "Aetna", [f("dental", **supplemental, cost_kind="premium", amount="$20", package="Rider"),
                                          f("packages", **supplemental, cost_kind="not_covered", amount="")],
             {"": ["a package for sale won"]}),
            ("F_primary_care", "Aetna", [f("visits", "office.pcp", "$5"), f("visits", "office.pcp", "$9", network="out", **supplemental)],
             {"$9": ["the plan has no out-of-network visit price"]}),
            ("F_primary_care", "Aetna", [f("visits", "office.pcp", "$5"), f("visits", "office.pcp", "$7", network="any")],
             {"$7": ["a price for network 'in' won"]}),
            ("F_primary_care", "Aetna", [f("visits", "office.pcp", "$5"), f("visits", "office.pcp", "$0", condition="diabetes")],
             {"$0": ["a price without a condition won"]}),
            ("AB_ambulance", "Aetna", [f("ambulance", "outside_us", "$100"), f("ambulance", "outside_us", "", cost_kind="covered")],
             {"": ["line 2 shows a price abroad"]}),
            ("AB_ambulance", "Aetna", [f("ambulance.ground", amount="$250"), f("ambulance", "outside_us", "", cost_kind="covered"),
                                       f("ambulance", "outside_us", "$0", cost_kind="not_covered")],
             {"$0": ["line 2 shows that trips abroad are covered"]}),
            ("AB_ambulance", "Aetna", [f("ambulance.ground", amount="$250"), f("emergency", "outside_us", "$90"),
                                       f("emergency", "outside_us", "$80", source="SB", page="3"), f("emergency", amount="$70"),
                                       f("emergency", "outside_us", "$60", cost_kind="not_covered")],
             {"$80": [present.PLAIN_CARE], "$70": [present.PLAIN_CARE], "$60": ["line 2 says the EOC is unclear"]}),
            ("AB_ambulance", "Aetna", [f("ambulance", "outside_us", "$100"), f("emergency", "outside_us", "$90")],
             {"$90": ["a fact names trips abroad"]}),
            ("K_tests_labs", "Aetna", [f("tests.diagnostic", "office.pcp", "$5"),
                                       f("tests.diagnostic.sleep_study", "outpatient_hospital", "$140")],
             {"$140": ["a sleep study counts only for H1036-306-0"]}),
            ("K_tests_labs", "Aetna", [f("tests.diagnostic", "office.pcp", "$5", plan_id="H1036-306-0"),
                                       f("tests.diagnostic.sleep_study", "office.specialist", "$75", plan_id="H1036-306-0")],
             {"$75": ["only a sleep study at an outpatient hospital counts"]}),
            ("L_xray_imaging", "Aetna", [f("imaging.xray", "office", "$5"), f("imaging.diagnostic.mammogram", "office", "$0")],
             {"$0": ["a $0 mammogram counts only with a CT, MRI or PET price"]}),
            ("L_xray_imaging", "Humana", [f("imaging.diagnostic.advanced", "office", "$100"),
                                          f("imaging.diagnostic.mammogram", "office", "$0")],
             {"$0": ["Humana keeps no $0 low end for a mammogram"]}),
            ("L_xray_imaging", "Aetna", [f("imaging.diagnostic.advanced", "office", "$100"),
                                         f("imaging.diagnostic.mammogram", "office", "0%", cost_kind="coinsurance")],
             {"0%": ["only a $0 mammogram copay counts"]}),
            ("H_inpatient", "Aetna", [f("inpatient.acute", amount="$900", unit="per stay"), f("inpatient.acute", amount="$5")],
             {"$5": ["a cost per stay won"]}),
            ("H_inpatient", "Aetna", [f("inpatient.acute", amount="$300", unit="per day", limit="days 1-5"),
                                      f("inpatient.acute", amount="$900", unit="per stay")],
             {"$900": ["a cost per day won"]}),
            ("Z_part_b_reduction", "Aetna", [f("giveback", cost_kind="part_b_reduction", amount="$50"),
                                             f("giveback", cost_kind="covered", amount=""),
                                             f("giveback", cost_kind="part_b_reduction", amount="$20", condition="QMB")],
             {"": ["a reduction amount won"], "$20": ["a reduction without a condition won"]}),
            ("J_outpatient_rehab", "Aetna", [f("rehab.physical", "outpatient_hospital", "$9"), f("rehab.physical", "asc", "$7")],
             {"$7": ["setting 'asc' is not 'outpatient_hospital'"]}),
            ("W_fitness", "Aetna", [f("fitness", **supplemental, cost_kind="covered", amount=""),
                                    f("fitness", **supplemental, amount="$5", package="Rider")],
             {"$5": ["package is 'Rider'"]}),
            ("Z_part_b_reduction", "Aetna", [f("giveback", cost_kind="part_b_reduction", amount="$50"),
                                             f("giveback", cost_kind="copay", amount="$5")],
             {"$5": ["it is not a Part B premium reduction"]}),
            ("O_medical_deductible", "Aetna", [f("medical_deductible", cost_kind="deductible", amount="$500"),
                                               f("medical_deductible", cost_kind="copay", amount="$900")],
             {"$900": ["it is not a Medicare deductible in network 'in'"]}),
            ("I_outpatient_surgery", "Aetna", [f("surgery", "asc", "$50"), f("surgery", "office.pcp", "$40")],
             {"$40": ["setting 'office.pcp' is not 'asc'", "setting 'office.pcp' is not 'outpatient_hospital'"]}),
            ("L_xray_imaging", "Aetna", [f("imaging.xray", "office", "$5"),
                                         f("imaging.xray", "office", "$1", network="out", covered_by="supplemental", cost_kind="allowance")],
             {"$1": ["network is 'out' and covered_by is 'supplemental' and cost_kind is 'allowance'"]}),
            ("M_part_b_drugs", "Aetna", [f("part_b_drugs.chemo", cost_kind="coinsurance", amount="20%"),
                                         f("part_b_drugs.chemo", cost_kind="coinsurance", amount="10%", source="PBP")],
             {"10%": ["PBP ranks below EOC"]}),
        ]
        for column, organization, found, reasons in cases:
            with self.subTest(column=column, reasons=reasons):
                found = [dict(g, fact_id=g["amount"]) for g in found]
                _, aside = present.explain(organization, found, column, version=17)
                self.assertEqual({g["amount"]: aside[facts.identity(g)] for g in found if facts.identity(g) in aside}, reasons)

    def test_says_why_the_final_chart_sets_a_fact_aside(self):
        cases = [
            ("I_outpatient_surgery", [fact("surgery", "asc", "$50"), fact("surgery.colonoscopy", "asc", "$0")],
             {"$0": ["the 'outpatient_hospital' line counts only a price at 'outpatient_hospital' itself",
                     "the final chart counts no $0 colonoscopy or skin biopsy"]}),
            ("L_xray_imaging", [fact("imaging.diagnostic.advanced.ct", "office.pcp", "$100"),
                                fact("imaging.diagnostic.mammogram", "office.pcp", "$0")],
             {"$0": ["the final chart counts no mammogram"]}),
            ("J_outpatient_rehab", [fact("rehab.physical", "outpatient_hospital", "$9"), fact("rehab.physical", "asc", "$7")],
             {"$7": ["setting 'asc' is not 'office.pcp' or 'office.specialist' or 'freestanding' or 'outpatient_hospital'"]}),
        ]
        for column, found, reasons in cases:
            with self.subTest(column=column):
                found = [dict(g, fact_id=g["amount"]) for g in found]
                _, aside = present.explain("Aetna", found, column, version=18)
                self.assertEqual({g["amount"]: aside[facts.identity(g)] for g in found if facts.identity(g) in aside}, reasons)

    @built.check
    def test_every_fact_a_rule_sets_aside_in_the_year_has_a_noted_reason_unless_the_column_skips_its_benefit(self):
        data = years.data_dir()
        organization = {p["plan_id"]: p["organization"] for p in sheets.rows(data / "generated/plans.csv")}
        found = present.plan_facts(data)
        unused_benefits, noted_benefits = {}, {}
        for plan_id, name in organization.items():
            for sheet, column in ((s, c) for s, (rules, _) in present.SHEETS.items() for c in rules):
                with self.subTest(plan_id=plan_id, column=column):
                    for identity, reasons in present.explain(name, found[plan_id], column, sheet)[1].items():
                        self.assertNotIn(present.UNNOTED, reasons)
                        self.assertTrue(all(isinstance(r, str) and r for r in reasons), reasons)
                        benefit = next(f["benefit"] for f in found[plan_id] if facts.identity(f) == identity)
                        unused = reasons == [f"the column does not use {benefit}"]
                        (unused_benefits if unused else noted_benefits).setdefault(column, set()).add(benefit)
        for column, benefits in unused_benefits.items():
            with self.subTest(column=column):
                self.assertFalse(benefits & noted_benefits.get(column, set()))

    def test_says_when_a_more_specific_fact_won(self):
        self.assertEqual(self.set_aside("H_inpatient", fact("inpatient", amount="$5"), fact("inpatient.acute", amount="$10")),
                         {"$5": ["a more specific fact won"]})

    def test_says_the_column_does_not_use_a_related_fact_no_filter_examined(self):
        self.assertEqual(self.set_aside("L_xray_imaging", fact(amount="$10"), fact("imaging.diagnostic.ultrasound",
                                                                                      amount="$70")),
                         {"$70": ["the column does not use imaging.diagnostic.ultrasound"]})

    def test_leaves_unrelated_facts_out(self):
        self.assertEqual(self.set_aside("L_xray_imaging", fact(amount="$10"), fact("ambulance.ground", amount="$250")), {})

    def test_used_facts_are_not_set_aside(self):
        self.assertEqual(self.set_aside("S_acupuncture", fact("extras.acupuncture", covered_by="supplemental",
                                                              amount="$15")), {})

    def test_records_nothing_outside_explain(self):
        present.xray_imaging("Humana", [fact(network="out")])
        self.assertIsNone(present._reasons.get())

    def test_every_rule_names_its_benefits(self):
        for rules, leaves in present.SHEETS.values():
            self.assertEqual(set(leaves), set(rules))
            self.assertLessEqual({leaf for benefits in leaves.values() for leaf in benefits}, set(facts.BENEFITS))


def chart(column, *found, organization="Aetna", rules=present.SHEETS["main"][0]):
    return [value for value, _ in rules[column](organization, list(found))]


def chart_18(column, *found, organization="Aetna"):
    return chart(column, *found, organization=organization, rules=present.SHEETS["main"][0] | present.CHART_18)


class FinalChartTest(unittest.TestCase):
    def test_surgery_shows_each_settings_surgery_price_without_a_0_colonoscopy(self):
        found = [op(), op(setting="asc", amount="$400"), op("surgery.colonoscopy", "asc", "$0")]
        self.assertEqual(chart_18("I_outpatient_surgery", *found), ["$500", "$400"])
        self.assertEqual(chart_18("I_outpatient_surgery", op(amount="$0-$400")), ["$0-$400", ""])

    def test_identical_lines_show_once_and_cite_both(self):
        found = [op(), op(setting="asc")]
        self.assertEqual(present.SHEETS["main"][0]["I_outpatient_surgery"]("Aetna", found), [("$500", found)])
        self.assertEqual(chart("E_moop", priced("moop", amount="$5,900", cost_kind="out_of_pocket_max", network="any"),
                               priced("moop", amount="$5,900", cost_kind="out_of_pocket_max")), ["$5,900"])

    def test_rehab_and_labs_count_outpatient_hospital_prices(self):
        self.assertEqual(chart("J_outpatient_rehab", priced("rehab.physical", "office.pcp", "$20"),
                               priced("rehab.physical", "outpatient_hospital", "$50")), ["$20-$50"])
        found = [priced("tests.diagnostic", "office.pcp"), priced("tests.diagnostic", "outpatient_hospital", "$95"),
                 priced("tests.lab", "freestanding"), priced("tests.lab", "outpatient_hospital", "$40")]
        self.assertEqual(chart_18("K_tests_labs", *found), ["$0/$0-$40"])

    def test_only_agerights_0_colonoscopy_counts_as_a_test(self):
        found = [priced("tests.diagnostic", amount="20%"), priced("surgery.colonoscopy", "outpatient_hospital")]
        self.assertEqual(chart_18("K_tests_labs", *found, organization="AgeRight Advantage"), ["$0-20%/"])
        self.assertEqual(chart_18("K_tests_labs", *found, organization="Regence"), ["20%/"])

    def test_imaging_takes_every_office_x_ray_and_no_0_mammogram(self):
        found = [priced("imaging.xray", "office.pcp"), priced("imaging.xray", "freestanding", "$40"),
                 priced("imaging.diagnostic.advanced.ct", "freestanding", "$205"),
                 priced("imaging.diagnostic.mammogram", "freestanding")]
        self.assertEqual(chart_18("L_xray_imaging", *found, organization="Humana"), ["$0-$40", "$205"])

    def test_part_b_drugs_show_the_highest_coinsurance(self):
        found = [priced("part_b_drugs.vaccine"), priced("part_b_drugs", amount="20%")]
        self.assertEqual(chart_18("M_part_b_drugs", *found), ["20%"])
        self.assertEqual(chart_18("M_part_b_drugs"), [""])

    def test_a_cost_per_stay_is_per_admit(self):
        self.assertEqual(chart("H_inpatient", priced("inpatient.acute", amount="$2,241", unit="per stay")),
                         ["$2,241 per admit", ""])

    def test_a_giveback_is_a_dot(self):
        self.assertEqual(chart("Z_part_b_reduction", priced("giveback", amount="$90", cost_kind="part_b_reduction")), ["●"])
        self.assertEqual(chart("Z_part_b_reduction"), [""])

    def test_medical_deductible_wording(self):
        part_b = [deductible("$283", "medical_deductible.some"),
                  priced("medical_deductible.part_b", amount="", cost_kind="covered", source="SB")]
        self.assertEqual(chart("O_medical_deductible", *part_b), ["Same as 2027 Pt B Deductible"])
        oon = [deductible("$100", "medical_deductible.some", network="out")]
        self.assertEqual(chart("O_medical_deductible", *oon), ["$100 some OON"])
        self.assertEqual(chart("O_medical_deductible", deductible("$250", "medical_deductible.some")), ["$250 some"])

    def test_identical_office_visit_and_imaging_lines_show_once(self):
        for column, benefit in (("F_primary_care", "visits"), ("G_specialist", "visits"), ("L_xray_imaging", "imaging.xray")):
            in_and_out = [priced(benefit, "office.pcp", "$45"), priced(benefit, "office.specialist", "$45"),
                          priced(benefit, "office.pcp", "$45", network="out"),
                          priced(benefit, "office.specialist", "$45", network="out")]
            if benefit != "visits":
                in_and_out = [in_and_out[0], priced("imaging.diagnostic.advanced.ct", "office.pcp", "$45")]
            self.assertEqual(chart(column, *in_and_out), ["$45"], column)

    def test_the_latest_version_uses_these_rules_and_version_17_the_earlier_ones(self):
        stay = [priced("inpatient.acute", amount="$2,241", unit="per stay")]
        self.assertEqual(present.rule("main", "H_inpatient", max(present.VERSIONS))("Aetna", stay)[0][0], "$2,241 per admit")
        self.assertEqual(present.rule("main", "H_inpatient", 17)("Aetna", stay)[0][0], "$2,241 per admission")
        found = [op(), op("surgery.colonoscopy", amount="$0")]
        self.assertEqual(present.rule("main", "I_outpatient_surgery", 17)("Aetna", found)[0][0], "$0-$500")
        for column in ("E_moop", "F_primary_care", "G_specialist", "J_outpatient_rehab", "K_tests_labs", "L_xray_imaging",
                       "M_part_b_drugs", "O_medical_deductible", "Z_part_b_reduction"):
            self.assertIsNot(present.rule("main", column, 17), present.rule("main", column, 18), column)



class EveryPriceTest(unittest.TestCase):
    def test_takes_narrower_benefits_and_broader_ones_only_without_them(self):
        ct, broad = priced("imaging.diagnostic.advanced.ct", amount="$200"), priced("imaging.diagnostic", amount="$300")
        self.assertEqual(present.every_price([ct, broad], ("imaging.diagnostic.advanced",)), [ct])
        self.assertEqual(present.every_price([broad], ("imaging.diagnostic.advanced",)), [broad])

    def test_a_lesser_source_counts_where_no_better_one_gives_the_setting(self):
        eoc, sb_office = priced("tests.diagnostic", "freestanding", "$40"), priced("tests.diagnostic", "office", source="SB")
        self.assertEqual(present.every_price([eoc, sb_office], ("tests.diagnostic",)), [eoc, sb_office])
        for better in (priced("tests.diagnostic", "office.pcp", "$5"), priced("tests.diagnostic", amount="$5"),
                       priced("tests", "office", "$5")):
            self.assertEqual(present.every_price([better, sb_office], ("tests.diagnostic",)), [better])

    def test_skips_other_settings_unless_settings_is_empty(self):
        urgent = priced("tests.diagnostic", "urgent_care", "$45")
        self.assertEqual(present.every_price([urgent], ("tests.diagnostic",)), [])
        self.assertEqual(present.every_price([urgent], ("tests.diagnostic",), ()), [urgent])


class EveryPriceChartTest(unittest.TestCase):
    def test_surgery_keeps_a_0_colonoscopy(self):
        found = [op(), op(setting="asc", amount="$400"), op("surgery.colonoscopy", "asc", "$0")]
        self.assertEqual(chart("I_outpatient_surgery", *found), ["$500", "$0-$400"])

    def test_tests_count_every_setting_and_narrower_test(self):
        found = [priced("tests.diagnostic", "office.pcp"), priced("tests.diagnostic", "outpatient_hospital", "$95"),
                 priced("tests.diagnostic.sleep_study", "outpatient_hospital", "$140"),
                 priced("tests.diagnostic", "urgent_care", "$200"), priced("tests.lab", "freestanding"),
                 priced("tests.genetic", "office", "$60")]
        self.assertEqual(chart("K_tests_labs", *found), ["$0-$140/$0-$60"])
        self.assertEqual(chart("K_tests_labs", priced("tests.lab", amount="$40"), priced("tests.genetic", amount="20%")),
                         ["/$40 or 20%"])
        colonoscopy = [priced("tests.diagnostic", amount="20%"), priced("surgery.colonoscopy", "outpatient_hospital")]
        self.assertEqual(chart("K_tests_labs", *colonoscopy, organization="AgeRight Advantage"), ["$0-20%/"])
        self.assertEqual(chart("K_tests_labs", *colonoscopy, organization="Regence"), ["20%/"])

    def test_imaging_takes_every_x_ray_and_advanced_price_and_a_0_mammogram(self):
        found = [priced("imaging.xray", "office.pcp"), priced("imaging.xray", "outpatient_hospital", "$145"),
                 priced("imaging.diagnostic.advanced.ct", "freestanding", "$205"),
                 priced("imaging.diagnostic.advanced", "outpatient_hospital", "$345"),
                 priced("imaging.diagnostic.mammogram", "freestanding"),
                 priced("imaging.diagnostic.mammogram", "outpatient_hospital", "$20"),
                 priced("imaging.diagnostic.ultrasound", "freestanding", "$500")]
        self.assertEqual(chart("L_xray_imaging", *found, organization="Humana"), ["$0-$145", "$0-$345"])

    def test_part_b_drugs_show_every_drugs_price(self):
        found = [priced("part_b_drugs.vaccine", condition="flu and COVID-19"), priced("part_b_drugs", amount="20%")]
        self.assertEqual(chart("M_part_b_drugs", *found), ["$0-20%"])
        self.assertEqual(chart("M_part_b_drugs", *found, priced("part_b_drugs.insulin", amount="$35")), ["$0-$35 or 20%"])
        self.assertEqual(chart("M_part_b_drugs", priced("part_b_drugs.vaccine", condition="Extra Help members"),
                               found[1]), ["20%"])
        self.assertEqual(chart("M_part_b_drugs"), [""])

    def test_office_visits_count_that_kinds_telehealth_price(self):
        found = [priced("visits", "office.pcp", "$5"), priced("visits", "office.specialist", "$45"),
                 priced("visits", "telehealth", condition="Virtual specialist visits"),
                 priced("visits", "telehealth", "$3", condition="Primary care provider (PCP)"),
                 priced("visits", "telehealth", "$1", condition="services in a nursing home")]
        self.assertEqual(chart("F_primary_care", *found), ["$3-$5", ""])
        self.assertEqual(chart("G_specialist", *found), ["$0-$45", ""])
        self.assertEqual(chart("G_specialist", *found[1:2], priced("visits", "telehealth", "$10")), ["$10-$45", ""])
        self.assertEqual(chart("G_specialist", *found[1:2], priced("visits", "telehealth", "$10", provider_tier="PCP or specialist"),
                               priced("visits", "telehealth", "$9", cost_kind="covered"),
                               priced("visits", "telehealth", "$20"), priced("visits", "telehealth", "$8", source="SB")),
                         ["$20-$45", ""])
        self.assertEqual(chart("G_specialist", priced("visits", "telehealth", "$10")), [""])


# The main cells that lack a price the final chart shows, because the plan documents contradict it.
CHART_ERRORS = [("H5439-019-0", "K_tests_labs")]


class FinalChartPricesTest(unittest.TestCase):
    def test_lacks_a_price_outside_every_range(self):
        self.assertEqual(present.chart_lacks("$0-$145 | $345", "$40 $330 $345 0%"), ["$330"])
        self.assertEqual(present.chart_lacks("$0-20%", "$10 20%"), ["$10"])

    def test_a_contradiction_names_the_half_and_cites_a_fact_behind_it(self):
        test = extra("tests.diagnostic", cost_kind="coinsurance", amount="20%", page="92")
        lab = extra("tests.lab", cost_kind="copay", amount="$10", page="90")
        self.assertEqual(present.contradiction("K_tests_labs", "0%-20%/$0-$10", "$0/$0-20%", [test, lab]), (
            "The volunteer chart shows $0-20% for labs, where this cell shows $0-$10. "
            "The plan's documents give no in-network 20% for labs.", lab))
        self.assertEqual(present.contradiction("I_outpatient_surgery", "$0-$145 | $345", "$330 $345", [test])[0],
                         "The volunteer chart shows $330 $345, where this cell shows $0-$145 | $345. "
                         "The plan's documents give no in-network $330.")
        self.assertIsNone(present.contradiction("K_tests_labs", "$0/$0-$50", "$0/$0-$10", [lab]))

    def test_a_contradiction_comes_before_the_cells_caveat_and_needs_version_37(self):
        test = extra("tests.diagnostic", cost_kind="coinsurance", amount="20%", doc_sha="d", page="92", quotes='["20% x"]')
        lab = dict(test, benefit="tests.lab", cost_kind="copay", amount="$10", page="90", quotes='["$10 copay", "x"]')
        lines = [("main", "H1-001-0", "K_tests_labs", "", "0%-20%/$0-$10", [test, lab])]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(present, "presented_lines", lambda data, version: lines), \
                mock.patch.object(present, "caveats", lambda *a: ("Labs caveat.", test)):
            os.makedirs(f"{tmp}/generated")
            pathlib.Path(tmp, "generated/documents_checked.csv").write_text("sha256,url\nd,https://eoc\n")
            self.assertEqual([r["kind"] for r in present.caveat_rows(pathlib.Path(tmp), 37)], ["caveat"])
            pathlib.Path(tmp, sheets.FINAL_CHART).write_text("plan_id,column,chart\nH1-001-0,K_tests_labs,$0/$0-20%\n")
            self.assertEqual(present.caveat_rows(pathlib.Path(tmp), 37), [dict(
                sheet="main", plan_id="H1-001-0", column="K_tests_labs", kind="contradiction",
                comment="The volunteer chart shows $0-20% for labs, where this cell shows $0-$10. "
                        "The plan's documents give no in-network 20% for labs. Labs caveat.",
                url="https://eoc", pdf_page="90", quote="$10 copay")])
            self.assertEqual([r["kind"] for r in present.caveat_rows(pathlib.Path(tmp), 36)], ["caveat"])

    @built.check
    def test_only_the_charts_errors_get_contradictions(self):
        rows = present.caveat_rows(years.data_dir(YEAR), 37)
        self.assertEqual([(r["plan_id"], r["column"]) for r in rows if r["kind"] == "contradiction"], CHART_ERRORS)


def segments(value):
    """A value's lines, with "tests/labs" split into its halves."""
    return [half for line in value.split(" | ") for half in line.split("/")]


class LostPricesTest(unittest.TestCase):
    @built.check
    def test_version_29_keeps_every_price_version_28_showed(self):
        data = years.data_dir(YEAR)
        lost = []
        for column in ("F_primary_care", "G_specialist", "I_outpatient_surgery", "K_tests_labs", "L_xray_imaging",
                       "M_part_b_drugs"):
            old, new = (present.lines(data, column, sheet="main", version=v) for v in (28, 29))
            for plan, lines in old.items():
                for (before, _), (after, _) in zip(lines, new[plan]):
                    for a, b in zip(segments(before), segments(after)):
                        if present.chart_lacks(b, a):
                            lost.append((plan, column, a, b))
        self.assertEqual(lost, [])


class NoteFactsTest(unittest.TestCase):
    def test_a_tag_must_name_a_note_and_a_fact_its_cell_cites(self):
        cell = ("main", "H1036-153-0", "K_tests_labs")
        unnoted = cell[:2] + ("L_xray_imaging",)
        notes, cited = [dict(zip(("sheet", "plan_id", "column"), cell))], {cell: {"a"}, unnoted: {"a"}}
        tags = [dict(notes[0], fact_id=f) for f in ("a", "b")] + [dict(notes[0], column=unnoted[2], fact_id="a")]
        self.assertEqual(present.wrong_note_facts(tags, notes, cited), tags[1:])

    @built.check
    def test_each_note_fact_is_one_its_cell_cites(self):
        data = years.data_dir(YEAR)
        with (data / "comments.csv").open(newline="") as c, (data / "note_facts.csv").open(newline="") as t:
            notes, tags = list(csv.DictReader(c)), list(csv.DictReader(t))
        self.assertEqual(present.wrong_note_facts(tags, notes, present.cited_facts(data)), [])


if __name__ == "__main__":
    unittest.main()
