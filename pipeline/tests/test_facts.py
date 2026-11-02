import csv, json, os, re, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import facts

SHA = "ab" * 32


def fact(**changes):
    row = dict(plan_id="H1036-306-0", benefit="imaging.xray", setting="office.specialist", network="in",
               provider_tier="", condition="", package="", pool="", cost_kind="copay", amount="$0-$40",
               unit="per visit", limit="", covered_by="medicare", source="EOC", doc_sha=SHA, page="61",
               quotes=json.dumps(["X-rays $0 to $40 copay"]), note="")
    row.update(changes)
    return dict(row, fact_id=facts.fact_id(row))


class FactIdTest(unittest.TestCase):
    def test_hashes_only_the_key(self):
        self.assertEqual(fact()["fact_id"], fact(amount="$5", source="SB", page="3", quotes='["x"]')["fact_id"])

    def test_every_key_column_changes_it(self):
        for k in facts.KEY:
            with self.subTest(k):
                self.assertNotEqual(fact()["fact_id"], fact(**{k: "changed"})["fact_id"])

    def test_columns_cannot_run_together(self):
        self.assertNotEqual(fact(provider_tier="a", condition="")["fact_id"],
                            fact(provider_tier="", condition="a")["fact_id"])


class CheckTest(unittest.TestCase):
    def assertProblem(self, row, words):
        self.assertTrue(any(words in p for p in facts.check(row)), facts.check(row))

    def test_accepts_a_good_fact(self):
        self.assertEqual(facts.check(fact()), [])

    def test_accepts_amount_shapes(self):
        for kind, amount in [("copay", "$0"), ("copay", "$1,250.50"), ("copay", "$100 or $200"),
                             ("copay", "$0-$100 or $200-$300"), ("coinsurance", "20%"), ("coinsurance", "20.5%"),
                             ("coinsurance", "0%-50%"), ("visit_limit", "24"),
                             ("covered", ""), ("not_covered", "")]:
            with self.subTest(amount):
                self.assertEqual(facts.check(fact(cost_kind=kind, amount=amount)), [])

    def test_rejects_amount_of_the_wrong_kind(self):
        for kind, amount in [("copay", "20%"), ("coinsurance", "$20"), ("copay", "$325 or 20%"),
                             ("copay", "about $5"), ("copay", ""), ("covered", "$0"), ("visit_limit", "$4"),
                             ("copay", "$1,25"), ("copay", "$1250"), ("copay", "$007"), ("copay", "$300-$0"),
                             ("copay", "$5-$5"), ("coinsurance", "150%"), ("copay", "$0-$5-$9")]:
            with self.subTest(amount):
                self.assertProblem(fact(cost_kind=kind, amount=amount), "amount")

    def test_rejects_words_outside_the_vocabulary(self):
        for column in ("benefit", "setting", "network", "cost_kind", "covered_by", "source", "plan_id"):
            with self.subTest(column):
                self.assertProblem(fact(**{column: "bogus"}), column)

    def test_rejects_a_stale_fact_id(self):
        self.assertProblem(dict(fact(), amount="$0", fact_id="0" * 16), "fact_id")

    def test_rejects_unknown_or_missing_columns(self):
        self.assertProblem(dict(fact(), extra="x"), "columns")
        row = fact()
        del row["note"]
        self.assertProblem(row, "columns")

    def test_document_fact_needs_doc_page_and_quotes(self):
        self.assertProblem(fact(doc_sha="ab"), "doc_sha")
        self.assertProblem(fact(page="0"), "page")
        self.assertProblem(fact(quotes="[]"), "quotes")
        self.assertProblem(fact(quotes='"one"'), "quotes")
        self.assertProblem(fact(quotes="not json"), "quotes")
        self.assertProblem(fact(quotes='[""]'), "quotes")
        self.assertProblem(fact(quotes="[1]"), "quotes")
        self.assertProblem(fact(source="RIDER", doc_sha=""), "doc_sha")
        self.assertProblem(dict(fact(), quotes=["x"]), "quotes")

    def test_cms_fact_names_fields_instead(self):
        self.assertEqual(facts.check(fact(source="PBP", doc_sha="", page="", quotes='["pbp_b8b_copay_mc_amt"]')), [])
        self.assertProblem(fact(source="PBP", doc_sha="", page="", quotes="[]"), "quotes")
        self.assertProblem(fact(source="PBP"), "doc_sha")
        self.assertProblem(fact(source="PBP", doc_sha="", quotes='["pbp_b8b_copay_mc_amt"]'), "page")


class FileTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "facts.csv")

    def test_write_sorts_and_reads_back(self):
        rows = [fact(plan_id="H9003-001-0", benefit="imaging.diagnostic"), fact(), fact()]
        facts.write(self.path, rows)
        again = facts.read(self.path)
        self.assertEqual(again, [fact(), fact(plan_id="H9003-001-0", benefit="imaging.diagnostic")])
        with open(self.path, newline="") as f:
            self.assertEqual(next(csv.reader(f)), list(facts.COLUMNS))

    def test_write_is_byte_stable(self):
        facts.write(self.path, [fact(), fact(page="62")])
        with open(self.path, "rb") as f:
            first = f.read()
        facts.write(self.path, [fact(page="62"), fact()])
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), first)

    def test_write_refuses_two_versions_of_one_identity(self):
        with self.assertRaisesRegex(ValueError, "two different rows"):
            facts.write(self.path, [fact(), fact(amount="$5")])
        facts.write(self.path, [fact(), fact(amount="$5", page="62")])
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["facts.csv"])

    def test_write_refuses_a_bad_fact(self):
        with self.assertRaisesRegex(ValueError, "amount"):
            facts.write(self.path, [fact(amount="free")])
        self.assertFalse(os.path.exists(self.path))


class VocabularyTest(unittest.TestCase):
    def test_every_benefit_has_its_parent(self):
        for b in facts.BENEFITS:
            if "." in b:
                self.assertIn(b.rsplit(".", 1)[0], facts.BENEFITS)

    def test_every_setting_has_its_parent(self):
        for s in facts.SETTINGS:
            if "." in s:
                self.assertIn(s.rsplit(".", 1)[0], facts.SETTINGS)

    def test_imaging_words_the_column_rules_need(self):
        for b in ("imaging.xray", "imaging.diagnostic.advanced.ct", "imaging.diagnostic.advanced.mri",
                  "imaging.diagnostic.advanced.pet", "imaging.diagnostic.ultrasound", "imaging.diagnostic.mammogram"):
            self.assertIn(b, facts.BENEFITS)
        for s in ("office.pcp", "office.specialist", "freestanding", "outpatient_hospital"):
            self.assertIn(s, facts.SETTINGS)

    def test_describe_lists_one_group(self):
        text = facts.describe("imaging")
        for b in facts.BENEFITS:
            self.assertEqual(f"`{b}`" in text, b == "imaging" or b.startswith("imaging."))
        for words in facts.VOCABULARIES.values():
            for word in words:
                if words is not facts.BENEFITS:
                    self.assertIn(f"`{word}`", text)
        self.assertIn(facts.AMOUNT_RULES, text)
        with self.assertRaises(KeyError):
            facts.describe("imagin")

    def test_amount_rules_examples_pass(self):
        for example in re.findall(r"`(\$[^`]*|\d+%?)`", facts.AMOUNT_RULES):
            kind = "coinsurance" if example.endswith("%") else "visit_limit" if example.isdigit() else "copay"
            with self.subTest(example):
                self.assertTrue(facts.amount_ok(kind, example))

    def test_covers(self):
        self.assertTrue(facts.covers("imaging.diagnostic", "imaging.diagnostic.advanced.mri"))
        self.assertTrue(facts.covers("imaging", "imaging"))
        self.assertFalse(facts.covers("imaging.diagnostic", "imaging.xray"))
        self.assertFalse(facts.covers("imaging.diag", "imaging.diagnostic"))
        self.assertFalse(facts.covers("imaging", "radiation_therapy"))
        self.assertTrue(facts.covers("office", "office.pcp"))
        self.assertTrue(facts.covers("any", "outpatient_hospital"))
        self.assertFalse(facts.covers("office", "freestanding"))

    def test_fact_id_is_16_hex(self):
        self.assertRegex(fact()["fact_id"], r"^[0-9a-f]{16}$")


if __name__ == "__main__":
    unittest.main()
