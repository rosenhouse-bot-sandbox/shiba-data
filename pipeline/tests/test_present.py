import os, pathlib, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import expected, facts, layers, present, years

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


def presented_cells(data, column):
    return {p: [value for value, _ in got] for p, got in present.lines(data, column).items()}


def shown(lines, line):
    return " | ".join(lines).removesuffix(" | ") if not line else lines[int(line) - 1]


class WriteTest(unittest.TestCase):
    def test_writes_the_layer_rows(self):
        row = dict.fromkeys(layers.COLUMNS, "x")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(present, "layer_rows", lambda data: [row]):
            os.makedirs(f"{tmp}/generated")
            present.write(pathlib.Path(tmp))
            self.assertEqual(layers.rows(pathlib.Path(tmp, layers.PRESENTED)), [row])

    def test_a_blank_with_cited_facts_writes_rows(self):
        data = years.data_dir(YEAR)
        f = facts.read(data / "machine/document_facts.csv")[0]
        plan = f["plan_id"]
        with mock.patch.object(present, "lines", lambda data, column: {plan: [("", [f])]}), \
                mock.patch.object(present, "COLUMNS", {"S_acupuncture": None}):
            rows = present.layer_rows(data)
        self.assertEqual({(r["plan_id"], r["column"], r["value"]) for r in rows}, {(plan, "S_acupuncture", "")})

    def test_refuses_a_second_line_for_a_one_line_cell(self):
        data = years.data_dir(YEAR)
        plan = layers.generated(data)["main"][0]["plan_id"]
        with mock.patch.object(present, "lines", lambda data, column: {plan: [("$1", []), ("$2", [])]}):
            with self.assertRaisesRegex(ValueError, f"{plan} .* has one line"):
                present.layer_rows(data)


# Lines where the rule and an edit disagree. The rule wins on X-ray lines (#127 has the evidence).
# Edits stay on the other lines until document facts support them.
TRIAGED = {
    ("L_xray_imaging", "H2056-003-0", "2"): "the expert's $0 mammogram rule covers Aetna",
    ("L_xray_imaging", "H2056-018-0", "2"): "the expert's $0 mammogram rule covers Aetna",
    ("L_xray_imaging", "H7199-002-0", ""): "the EOC prices X-rays at $25; the SB's $0 is for ultrasounds",
    ("AB_ambulance", "H1372-003-0", "2"): "the EOC excludes all care abroad without naming ambulances",
    ("AB_ambulance", "H5439-010-0", "2"): "the EOC covers emergencies abroad but never prices ambulances there",
    ("AB_ambulance", "H5439-011-0", "2"): "the EOC covers emergencies abroad but never prices ambulances there",
    ("AB_ambulance", "H5439-015-0", "2"): "the EOC covers emergencies abroad but never prices ambulances there",
    ("AB_ambulance", "H5439-019-0", "2"): "the EOC covers emergencies abroad but never prices ambulances there",
    ("AB_ambulance", "H6815-038-0", "2"): "the EOC covers emergencies abroad but never prices ambulances there",
    ("AB_ambulance", "H7006-018-0", "2"): "the EOC covers emergencies abroad but never prices ambulances there",
    ("AB_ambulance", "H7006-021-0", "2"): "the EOC covers emergencies abroad but never prices ambulances there",
    ("AB_ambulance", "H9003-001-0", "1"): "the $0 for a home treatment plan is on the page before the ambulance",
    ("AB_ambulance", "H9003-006-0", "1"): "the $0 for a home treatment plan is on the page before the ambulance",
    ("AB_ambulance", "H9003-009-0", "1"): "the $0 for a home treatment plan is on the page before the ambulance",
    ("I_outpatient_surgery", "H9003-001-0", "1"): "the reader missed the SB's $0 low end",
    ("I_outpatient_surgery", "H9003-001-0", "2"): "the EOC gives one outpatient surgery price, which readers file under outpatient hospitals",
    ("I_outpatient_surgery", "H9003-006-0", "1"): "the reader missed the SB's $0 low end",
    ("I_outpatient_surgery", "H9003-006-0", "2"): "the EOC gives one outpatient surgery price, which readers file under outpatient hospitals",
    ("I_outpatient_surgery", "H9003-009-0", "1"): "the reader missed the SB's $0 low end",
    ("I_outpatient_surgery", "H9003-009-0", "2"): "the EOC gives one outpatient surgery price, which readers file under outpatient hospitals",
    ("M_part_b_drugs", "H2056-003-0", ""): "the EOC prices vaccines at $0 in the words the expert cited for H2056-018-0's 0%",
}


class ExpectedTest(unittest.TestCase):
    def test_the_committed_layer_is_current(self):
        data = years.data_dir(YEAR)
        self.assertEqual(layers.rows(data / layers.PRESENTED), present.layer_rows(data))

    def test_presents_every_expected_line(self):
        data = years.data_dir(YEAR)
        for column in present.COLUMNS:
            cells = presented_cells(data, column)
            wanted = {(w["plan_id"], w["line"]): w["value"] for w in expected.load() if w["column"] == column}
            missed = [(p, line, value, cells.get(p)) for (p, line), value in wanted.items()
                      if (column, p, line) not in TRIAGED and (column, p) not in present.HELD
                      and shown(cells.get(p, ["", ""]), line) != value]
            self.assertEqual(missed, [], column)
            self.assertTrue(all(shown(cells[p], line) != wanted[p, line] for c, p, line in TRIAGED if c == column))

    def test_every_nonblank_or_cited_line_cites_a_document(self):
        data = years.data_dir(YEAR)
        rows = present.layer_rows(data)
        self.assertTrue(rows and all(r["url"] and r["quote"] for r in rows))
        generated = {r["plan_id"]: r for r in layers.generated(data)["main"]}
        for column in present.COLUMNS:
            self.assertEqual({(r["plan_id"], r["line"]) for r in rows if r["column"] == column},
                             {(p, str(n) if " | " in generated[p][column] else "")
                              for p, got in present.lines(data, column).items() if (column, p) not in present.HELD
                              for n, (v, cited) in enumerate(got, 1) if v or cited})


if __name__ == "__main__":
    unittest.main()
