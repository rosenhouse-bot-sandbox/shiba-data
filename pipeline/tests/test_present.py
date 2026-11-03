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


def presented_cells(data, column):
    return {p: [value for value, _ in got] for p, got in present.lines(data, column).items()}


def shown(lines, line):
    return " | ".join(lines) if not line else lines[int(line) - 1]


class WriteTest(unittest.TestCase):
    def test_writes_the_layer_rows(self):
        row = dict.fromkeys(layers.COLUMNS, "x")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(present, "layer_rows", lambda data: [row]):
            os.makedirs(f"{tmp}/generated")
            present.write(pathlib.Path(tmp))
            self.assertEqual(layers.rows(pathlib.Path(tmp, layers.PRESENTED)), [row])


# Lines where the rule and an edit disagree. The rule wins on X-ray lines (#127 has the evidence).
# Edits stay on the Ambulance lines until document facts support them.
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
                      if (column, p, line) not in TRIAGED and shown(cells.get(p, ["", ""]), line) != value]
            self.assertEqual(missed, [], column)
            self.assertTrue(all(shown(cells[p], line) != wanted[p, line] for c, p, line in TRIAGED if c == column))

    def test_every_nonblank_line_cites_a_document(self):
        data = years.data_dir(YEAR)
        rows = present.layer_rows(data)
        self.assertTrue(rows and all(r["url"] and r["quote"] for r in rows))
        for column in present.COLUMNS:
            self.assertEqual({(r["plan_id"], r["line"]) for r in rows if r["column"] == column},
                             {(p, str(n)) for p, lines in presented_cells(data, column).items()
                              for n, v in enumerate(lines, 1) if v})


if __name__ == "__main__":
    unittest.main()
