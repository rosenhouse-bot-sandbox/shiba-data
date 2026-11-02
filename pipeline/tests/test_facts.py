import csv, json, os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import facts

SHA = "ab" * 32


def fact(**changes):
    row = dict(plan_id="H1036-306-0", benefit="imaging.xray", setting="specialist_office", network="in",
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
                             ("coinsurance", "20%"), ("coinsurance", "0%-50%"), ("visit_limit", "24"),
                             ("covered", ""), ("not_covered", "")]:
            with self.subTest(amount):
                self.assertEqual(facts.check(fact(cost_kind=kind, amount=amount)), [])

    def test_rejects_amount_of_the_wrong_kind(self):
        for kind, amount in [("copay", "20%"), ("coinsurance", "$20"), ("copay", "$325 or 20%"),
                             ("copay", "about $5"), ("copay", ""), ("covered", "$0"), ("visit_limit", "$4")]:
            with self.subTest(amount):
                self.assertProblem(fact(cost_kind=kind, amount=amount), "amount")

    def test_rejects_words_outside_the_vocabulary(self):
        for column in ("benefit", "setting", "network", "cost_kind", "covered_by", "source"):
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

    def test_cms_fact_names_fields_instead(self):
        self.assertEqual(facts.check(fact(source="PBP", doc_sha="", page="", quotes='["pbp_b8b_copay_mc_amt"]')), [])
        self.assertProblem(fact(source="PBP", doc_sha="", page="", quotes="[]"), "quotes")
        self.assertProblem(fact(source="PBP"), "doc_sha")


class FileTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "facts.csv")

    def test_write_sorts_and_reads_back(self):
        rows = [fact(plan_id="H9", benefit="imaging.advanced"), fact(), fact()]
        facts.write(self.path, rows)
        again = facts.read(self.path)
        self.assertEqual(again, [fact(), fact(plan_id="H9", benefit="imaging.advanced")])
        with open(self.path, newline="") as f:
            self.assertEqual(next(csv.reader(f)), list(facts.COLUMNS))

    def test_write_is_byte_stable(self):
        facts.write(self.path, [fact(), fact(page="62")])
        with open(self.path, "rb") as f:
            first = f.read()
        facts.write(self.path, [fact(page="62"), fact()])
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), first)

    def test_write_refuses_a_bad_fact(self):
        with self.assertRaisesRegex(ValueError, "amount"):
            facts.write(self.path, [fact(amount="free")])
        self.assertFalse(os.path.exists(self.path))


class VocabularyTest(unittest.TestCase):
    def test_every_benefit_has_its_parent(self):
        for b in facts.BENEFITS:
            if "." in b:
                self.assertIn(b.rsplit(".", 1)[0], facts.BENEFITS)

    def test_describe_lists_one_group(self):
        text = facts.describe("imaging")
        for b in facts.BENEFITS:
            self.assertEqual(f"`{b}`" in text, b == "imaging" or b.startswith("imaging."))
        for word in (*facts.SETTINGS, *facts.COST_KINDS):
            self.assertIn(f"`{word}`", text)

    def test_covers(self):
        self.assertTrue(facts.covers("imaging.advanced", "imaging.advanced.mri"))
        self.assertTrue(facts.covers("imaging", "imaging"))
        self.assertFalse(facts.covers("imaging.advanced", "imaging.xray"))
        self.assertFalse(facts.covers("imaging.adv", "imaging.advanced"))


if __name__ == "__main__":
    unittest.main()
