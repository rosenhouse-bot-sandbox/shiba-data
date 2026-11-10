import csv, json, os, pathlib, sys, tempfile, unittest
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

    def test_line_2_says_eoc_unclear_when_a_added_fact_says_so(self):
        self.assertEqual(ambulance(trip(), trip("ambulance", "", setting="outside_us", cost_kind="unclear"),
                                   trip("ambulance", "$500", setting="outside_us"))[1], "EOC unclear")

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

    def test_skips_a_package_deductible(self):
        ded = landscape("part_d_deductible", "deductible", "$100", package="Rider")
        self.assertEqual(column(present.drug_deductible, ded), [("", [])])

    def test_shows_na_without_part_d(self):
        none = landscape("part_d_deductible", "not_covered")
        self.assertEqual(column(present.drug_deductible, none), [("n/a", [none])])


def routine(benefit, cost_kind="copay", amount="$0", **more):
    return priced(benefit, covered_by="supplemental", cost_kind=cost_kind, amount=amount, **more)


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


class OptionalPackagesTest(unittest.TestCase):
    def test_each_package_shows_its_premium_and_yearly_dental_max(self):
        found = [routine("packages", "premium", "$50.90", package="MyOption DEN972", unit="per month"),
                 routine("dental", "max", "$1,500", package="MyOption DEN972", limit="per calendar year"),
                 routine("dental", "max", "$100", package="MyOption DEN972", unit="per incident")]
        self.assertEqual(column(present.optional_packages, *found), [("MyOption DEN972 $50.90/mo, max $1,500", found[:2])])

    def test_a_package_with_other_benefits_says_dental_max(self):
        found = [routine("packages", "premium", "$54", package="Advantage Plus"),
                 routine("dental", "max", "$1,500", package="Advantage Plus", limit="per year"),
                 routine("hearing.aids", "allowance", "$500", package="Advantage Plus")]
        self.assertEqual(column(present.optional_packages, *found)[0][0], "Advantage Plus $54/mo, dental max $1,500")

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


class DentalTest(unittest.TestCase):
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

    def test_worldwide_er_skips_urgent_care(self):
        found = [routine("emergency", setting="outside_us", amount="$130"),
                 routine("emergency", setting="outside_us", amount="$500", quotes='["Urgent care $500"]')]
        self.assertEqual(column(present.alt_care_otc_travel, *found), [("Worldwide ER $130", found[:1])])

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

    def test_names_cards_for_chronic_conditions_and_programs_after_heart_failure(self):
        found = [routine("other_supplemental", "allowance", "$30", pool="Food & Home Card", limit="per month",
                         condition="chronically ill members"),
                 routine("other_supplemental", pool="Virtual Cardiac Recovery Program", condition="recent heart failure"),
                 routine("meals", condition="After your inpatient stay for Congestive Heart Failure")]
        self.assertEqual(column(present.extra_benefits, *found)[0][0],
                         "For members with certain chronic conditions: Food & Home Card $30/month; "
                         "After a heart-failure hospital stay: Virtual Cardiac Recovery Program, home-delivered meals")


def presented_cells(data, column):
    return {p: [value for value, _ in got] for p, got in present.lines(data, column).items()}


def shown(lines, line):
    return " | ".join(lines).removesuffix(" | ") if not line else lines[int(line) - 1]


class AddedFactTest(unittest.TestCase):
    def test_plan_facts_include_added_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = pathlib.Path(tmp)
            for name in ("machine/document_facts.csv", "generated/pbp_facts.csv", present.ADDED):
                os.makedirs(data / os.path.dirname(name), exist_ok=True)
                with open(data / name, "w", newline="") as f:
                    out = csv.DictWriter(f, facts.COLUMNS)
                    out.writeheader()
                    if name == present.ADDED:
                        out.writerow(fact(amount="$1", note="added"))
            self.assertEqual([f["amount"] for f in present.plan_facts(data)["H1036-153-0"]], ["$1"])

    def test_added_facts_say_why_and_pass_the_fact_checks_but_for_cost_kind_unclear(self):
        rows = facts.read(years.data_dir(YEAR) / present.ADDED)
        self.assertTrue(rows and all(r["note"] and r["source"] in facts.DOCUMENTS for r in rows))
        self.assertEqual([(r["plan_id"], p) for r in rows for p in facts.check(r) if p != "cost_kind: 'unclear'"], [])
        self.assertLessEqual({r["cost_kind"] for r in rows} - set(facts.COST_KINDS), {"unclear"})


    def test_a_cell_has_a_added_fact_note_exactly_when_it_cites_a_added_fact(self):
        data = years.data_dir(YEAR)
        url = {d["sha256"]: d["url"] for d in layers.rows(data / "generated" / "documents_checked.csv") if d["sha256"]}
        added = {(f["plan_id"], url[f["doc_sha"]], f["page"], q)
                        for f in facts.read(data / present.ADDED) for q in json.loads(f["quotes"])}
        citing = {(r["sheet"], r["plan_id"], r["column"]) for r in layers.rows(data / layers.PRESENTED)
                  if (r["plan_id"], r["url"], r["pdf_page"], r["quote"]) in added}
        noted = {(c["sheet"], c["plan_id"], c["column"]) for c in layers.rows(data / "comments.csv")
                 if c["kind"] == "added" and present.cell(c["sheet"], c["column"], c["plan_id"]) not in present.held(data)}
        self.assertTrue(citing)
        self.assertEqual(sorted(citing - noted), [], "cells that cite an added fact but have no note")
        self.assertEqual(sorted(noted - citing), [], "notes about an added fact that the cell no longer cites")

class WriteTest(unittest.TestCase):
    def test_writes_the_layer_rows(self):
        row = dict.fromkeys(layers.COLUMNS, "x")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(present, "layer_rows", lambda data, version: [row] * version):
            os.makedirs(f"{tmp}/generated")
            present.write(pathlib.Path(tmp), 1)
            self.assertEqual(layers.rows(pathlib.Path(tmp, layers.PRESENTED)), [row])

    def test_a_blank_with_cited_facts_writes_rows(self):
        data = years.data_dir(YEAR)
        f = facts.read(data / "machine/document_facts.csv")[0]
        plan = f["plan_id"]
        with mock.patch.object(present, "lines", lambda data, column, sheet: {plan: [("", [f])]}), \
                mock.patch.dict(present.SHEETS, {"main": ({"S_acupuncture": None}, {}), "dvha": ({}, {})}):
            rows = present.layer_rows(data)
        self.assertEqual({(r["plan_id"], r["column"], r["value"]) for r in rows}, {(plan, "S_acupuncture", "")})

    def test_a_version_skips_the_cells_it_holds(self):
        data = years.data_dir(YEAR)
        cell = ("K_tests_labs", "H2923-009-0")
        cells = {v: {(r["column"], r["plan_id"]) for r in present.layer_rows(data, v)} for v in (1, 2)}
        self.assertEqual(cells[2] - cells[1], {cell})

    def test_version_4_presents_dvha_vision_and_hearing_and_holds_some_hearing_cells(self):
        data = years.data_dir(YEAR)
        cells = {v: {(r["sheet"], r["column"], r["plan_id"]) for r in present.layer_rows(data, v)} for v in (3, 4)}
        self.assertEqual({c[:2] for c in cells[4] - cells[3]}, {("dvha", "G_vision"), ("dvha", "H_hearing")})
        self.assertNotIn(("dvha", "H_hearing", "H6815-038-0"), cells[4])

    def test_version_5_presents_dvha_packages(self):
        data = years.data_dir(YEAR)
        cells = {v: {(r["sheet"], r["column"]) for r in present.layer_rows(data, v)} for v in (4, 5)}
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

    def test_version_9_presents_the_main_premium(self):
        data = years.data_dir(YEAR)
        cells = {v: {(r["sheet"], r["column"]) for r in present.layer_rows(data, v)} for v in (8, 9)}
        self.assertEqual(cells[9] - cells[8], {("main", "C_premium")})

    def test_version_11_presents_the_cell_version_10_holds_for_review(self):
        self.assertIn(("O_medical_deductible", "H2001-045-0"), set(present.VERSIONS[10]) - set(present.VERSIONS[11]))
        self.assertIn(("dvha.I_alt_care_otc_travel", "H5216-048-0"), set(present.VERSIONS[10]) - set(present.VERSIONS[11]))
        self.assertLessEqual(set(present.VERSIONS[11]), set(present.VERSIONS[10]))

    def test_a_held_main_cell_does_not_hold_the_dvha_cell_of_the_same_name(self):
        self.assertNotEqual(present.cell("main", "C_premium", "H1"), present.cell("dvha", "C_premium", "H1"))

    def test_version_3_presents_the_dvha_premium(self):
        data = years.data_dir(YEAR)
        cells = {v: {(r["sheet"], r["column"]) for r in present.layer_rows(data, v)} for v in (2, 3)}
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

    def test_refuses_a_second_line_for_a_one_line_cell(self):
        data = years.data_dir(YEAR)
        plan = layers.generated(data)["main"][0]["plan_id"]
        with mock.patch.object(present, "lines", lambda data, column, sheet: {plan: [("$1", []), ("$2", [])]}):
            with self.assertRaisesRegex(ValueError, f"{plan} .* has one line"):
                present.layer_rows(data)


# Lines where the rule and an edit disagree. The rule wins on X-ray lines (#127 has the evidence).
# Edits stay on the other lines until document facts support them.
TRIAGED = {
    ("L_xray_imaging", "H2056-003-0", "2"): "the expert's $0 mammogram rule covers Aetna",
    ("L_xray_imaging", "H2056-018-0", "2"): "the expert's $0 mammogram rule covers Aetna",
    ("L_xray_imaging", "H7199-002-0", ""): "the EOC prices X-rays at $25; the SB's $0 is for ultrasounds",
}


class ExpectedTest(unittest.TestCase):
    def test_the_committed_layer_is_current(self):
        data = years.data_dir(YEAR)
        pinned = json.loads((data / "steps.json").read_text())["present"]
        self.assertEqual(layers.rows(data / layers.PRESENTED), present.layer_rows(data, pinned))

    def test_presents_every_expected_line(self):
        data = years.data_dir(YEAR)
        for column in present.COLUMNS:
            cells = presented_cells(data, column)
            wanted = {(w["plan_id"], w["line"]): w["value"] for w in expected.load() if w["column"] == column}
            missed = [(p, line, value, cells.get(p)) for (p, line), value in wanted.items()
                      if (column, p, line) not in TRIAGED and (column, p) not in present.held(data)
                      and shown(cells.get(p, ["", ""]), line) != value]
            self.assertEqual(missed, [], column)
            self.assertTrue(all(shown(cells[p], line) != wanted[p, line] for c, p, line in TRIAGED if c == column))

    def test_every_nonblank_or_cited_line_cites_a_document(self):
        data = years.data_dir(YEAR)
        rows = present.layer_rows(data)
        self.assertTrue(rows and all(r["url"] and r["quote"] for r in rows))
        generated = {r["plan_id"]: r for r in layers.generated(data)["main"]}
        for column in present.COLUMNS:
            self.assertEqual({(r["plan_id"], r["line"]) for r in rows if (r["sheet"], r["column"]) == ("main", column)},
                             {(p, str(n) if " | " in generated[p][column] else "")
                              for p, got in present.lines(data, column).items() if (column, p) not in present.held(data)
                              for n, (v, cited) in enumerate(got, 1) if v and not cited or present.presents(cited)})


class DvhaTest(unittest.TestCase):
    def test_presents_the_live_value_of_each_cell_it_does_not_hold(self):
        data = years.data_dir(YEAR)
        live = {r["plan_id"]: r for r in layers.live(data)[0]["dvha"]}
        held = present.held(data, max(present.VERSIONS))
        for column in present.DVHA:
            got = {p: v for p, ((v, cited),) in present.lines(data, column, sheet="dvha").items()
                   if present.cell("dvha", column, p) not in held and cited}
            self.assertTrue(got, column)
            self.assertEqual({p: v for p, v in got.items() if v != live[p][column]}, {}, column)


class CmsColumnsTest(unittest.TestCase):
    def test_present_the_live_value_of_every_plan(self):
        data = years.data_dir(YEAR)
        live = layers.live(data)[0]
        for sheet, columns in (("main", ("C_premium", "D_premium_full_extra_help", "E_moop", "N_pharmacy_deductible",
                                         "O_medical_deductible")),
                               ("dvha", ("D_premium_full_extra_help",))):
            plans = {r["plan_id"]: r for r in live[sheet]}
            for column in columns:
                got = {p: " | ".join(v for v, _ in lines) for p, lines in present.lines(data, column, sheet=sheet).items()}
                self.assertEqual({p: (v, plans[p][column]) for p, v in got.items() if v != plans[p][column]}, {}, column)


class ExplainTest(unittest.TestCase):
    def set_aside(self, column, *found):
        found = [dict(f, fact_id=f["amount"]) for f in found]
        got, aside = present.explain("Humana", list(found), column)
        self.assertEqual(got, present.COLUMNS[column]("Humana", list(found)))
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
            ("AB_ambulance", "Aetna", [f("ambulance.ground", amount="$250"), f("ambulance", "outside_us", "$100"),
                                       f("ambulance", "outside_us", "", cost_kind="unclear")],
             {"$100": ["line 2 says the EOC is unclear"]}),
            ("AB_ambulance", "Aetna", [f("ambulance", "outside_us", "$100"), f("ambulance", "outside_us", "", cost_kind="covered")],
             {"": ["line 2 shows a price abroad"]}),
            ("AB_ambulance", "Aetna", [f("ambulance.ground", amount="$250"), f("ambulance", "outside_us", "", cost_kind="covered"),
                                       f("ambulance", "outside_us", "$0", cost_kind="not_covered")],
             {"$0": ["line 2 shows that trips abroad are covered"]}),
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
                _, aside = present.explain(organization, found, column)
                self.assertEqual({g["amount"]: aside[facts.identity(g)] for g in found if facts.identity(g) in aside}, reasons)

    def test_every_fact_a_rule_sets_aside_in_the_year_has_a_noted_reason_unless_the_column_skips_its_benefit(self):
        data = years.data_dir()
        organization = {p["plan_id"]: p["organization"] for p in layers.rows(data / "generated/plans.csv")}
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


if __name__ == "__main__":
    unittest.main()
