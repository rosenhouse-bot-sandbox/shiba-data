import contextlib, io, os, pathlib, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import find_regence

DETAILS_URL = "https://regence1.destinationrx.com/PC/2027/Shopping/PlanDetails?id=0KDL9ZQ408"
DETAILS = pathlib.Path(__file__).with_name("fixtures").joinpath("regence_plan_details.html").read_text()
GO = "https://www.regence.com/go/or/ppo/2027/"
VALIANCE = dict(plan_id="H3817-010-0", plan_name="Regence Valiance (PPO)", organization="Regence BlueCross BlueShield of Oregon")
EOC_COVER = "Evidence of Coverage for 2027: Your Medicare Health Benefits and Services as a Member of Regence\nValiance (PPO)"


def fake_fetch(texts):
    return lambda url: ("bynder/" + url.rsplit("/", 1)[1], texts.get(url, ""))


class DetailsTest(unittest.TestCase):
    def test_reads_the_plan_id_and_the_summary_link(self):
        self.assertEqual(find_regence.details(DETAILS), ("H3817-010-0", GO + "summary-valiance.pdf"))


class FoundRowsTest(unittest.TestCase):
    def rows(self, eoc_text, known=()):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rows = find_regence.found_rows([(DETAILS_URL, DETAILS)], [VALIANCE],
                                           fake_fetch({GO + "eoc-valiance.pdf": eoc_text}), known)
        return [(r["plan_ids"], r["kind"], r["url"]) for r in rows], rows, out.getvalue()

    def test_records_the_redirect_targets_of_the_sb_and_a_checked_eoc(self):
        got, rows, warned = self.rows(EOC_COVER)
        self.assertEqual(got, [("H3817-010-0", "SB", "bynder/summary-valiance.pdf"),
                               ("H3817-010-0", "EOC", "bynder/eoc-valiance.pdf")])
        self.assertEqual(rows[0]["found_via"], f"carrier plan page ({DETAILS_URL})")
        self.assertEqual(warned, "")

    def test_keeps_a_known_url_that_the_found_one_extends(self):
        got, _, _ = self.rows(EOC_COVER, known=["bynder/eoc-", "bynder/summary-valiance.pdf/x"])
        self.assertEqual([u for _, _, u in got], ["bynder/summary-valiance.pdf", "bynder/eoc-"])

    def test_drops_a_guessed_eoc_that_does_not_name_the_plan_or_say_evidence_of_coverage(self):
        for text in (EOC_COVER.replace("Valiance", "Primary"), EOC_COVER.replace("Evidence", "Summary"), ""):
            with self.subTest(text=text):
                got, _, warned = self.rows(text)
                self.assertEqual([k for _, k, _ in got], ["SB"])
                self.assertEqual(warned, f"::warning::{GO}eoc-valiance.pdf is not the EOC of H3817-010-0\n")


class MergeTest(unittest.TestCase):
    def test_replaces_rows_naming_a_regence_plan_and_keeps_the_rest(self):
        kept = dict(plan_ids="H3805-048-0", kind="SB", url="uhc")
        old = dict(plan_ids="H3817-010-0", kind="SB", url="old")
        new = [dict(plan_ids="H3817-010-0", kind="SB", url="new")]
        self.assertEqual(find_regence.merge([kept, old], new, {"H3817-010-0"}), [kept] + new)


if __name__ == "__main__":
    unittest.main()
