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


def presented_cells(data):
    return {p: [value for value, _ in got] for p, got in present.lines(data).items()}


def shown(lines, line):
    return " | ".join(lines) if not line else lines[int(line) - 1]


class WriteTest(unittest.TestCase):
    def test_writes_the_layer_rows(self):
        row = dict.fromkeys(layers.COLUMNS, "x")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(present, "layer_rows", lambda data: [row]):
            os.makedirs(f"{tmp}/generated")
            present.write(pathlib.Path(tmp))
            self.assertEqual(layers.rows(pathlib.Path(tmp, layers.PRESENTED)), [row])


# Lines where the rule and an edit disagree, and why the rule wins. Issue #127 has the evidence.
TRIAGED = {
    ("H2056-003-0", "2"): "the expert's $0 mammogram rule covers Aetna",
    ("H2056-018-0", "2"): "the expert's $0 mammogram rule covers Aetna",
    ("H7199-002-0", ""): "the EOC prices X-rays at $25; the SB's $0 is for ultrasounds",
}


class ExpectedTest(unittest.TestCase):
    def test_the_committed_layer_is_current(self):
        data = years.data_dir(YEAR)
        self.assertEqual(layers.rows(data / layers.PRESENTED), present.layer_rows(data))

    def test_presents_every_expected_line(self):
        data = years.data_dir(YEAR)
        cells = presented_cells(data)
        wanted = [w for w in expected.load() if w["column"] == present.COLUMN]
        missed = [(w["plan_id"], w["line"], w["value"], cells.get(w["plan_id"])) for w in wanted
                  if (w["plan_id"], w["line"]) not in TRIAGED
                  and shown(cells.get(w["plan_id"], ["", ""]), w["line"]) != w["value"]]
        self.assertEqual(missed, [])
        self.assertTrue(all(shown(cells[p], line) != wanted_value(wanted, p, line) for p, line in TRIAGED))

    def test_every_nonblank_line_cites_a_document(self):
        data = years.data_dir(YEAR)
        rows, cells = present.layer_rows(data), presented_cells(data)
        self.assertTrue(rows and all(r["url"] and r["quote"] for r in rows))
        self.assertEqual({(r["plan_id"], r["line"]) for r in rows},
                         {(p, str(n)) for p, lines in cells.items() for n, v in enumerate(lines, 1) if v})


def wanted_value(wanted, plan_id, line):
    return next(w["value"] for w in wanted if (w["plan_id"], w["line"]) == (plan_id, line))


if __name__ == "__main__":
    unittest.main()
