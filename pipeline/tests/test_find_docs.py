import contextlib, csv, io, os, pathlib, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import find_docs
import years


def plan(plan_id, organization, plan_name="P"):
    return dict(plan_id=plan_id, plan_name=plan_name, organization=organization)


def doc(plan_ids, kind, url, found_via="browser"):
    return dict(plan_ids=plan_ids, kind=kind, url=url, found_via=found_via)


class TemplatesTest(unittest.TestCase):
    def urls(self, *plans):
        return [(d["plan_ids"], d["kind"], d["url"]) for d in find_docs.templated(list(plans), "2027")]

    def test_humana_pads_plan_and_segment(self):
        self.assertEqual(self.urls(plan("H5216-427-2", "Humana")), [
            ("H5216-427-2", "SB", "https://assets.humana.com/is/content/humana/H5216427002SB27pdf"),
            ("H5216-427-2", "EOC", "https://assets.humana.com/is/content/humana/H5216427002EOC27pdf")])

    def test_devoted_spells_the_plan_name_and_a_segment_other_than_zero(self):
        got = self.urls(plan("H2923-028-3", "Devoted Health", "DEVOTED GIVEBACK 028 OR (HMO)"),
                        plan("H2923-019-0", "Devoted Health", "DEVOTED C-SNP GIVEBACK EXTRAS 019 OR (HMO C-SNP)"))
        base = "https://assets.devoted.com/plan-documents/2027/2027-DEVOTED-"
        self.assertEqual([u for _, _, u in got], [
            base + "GIVEBACK-028-OR-%28HMO%29-SB-H2923-028-003-ENG.pdf",
            base + "GIVEBACK-028-OR-%28HMO%29-EOC-H2923-028-003-ENG.pdf",
            base + "C-SNP-GIVEBACK-EXTRAS-019-OR-%28HMO-C-SNP%29-SB-H2923-019-ENG.pdf",
            base + "C-SNP-GIVEBACK-EXTRAS-019-OR-%28HMO-C-SNP%29-EOC-H2923-019-ENG.pdf"])

    def test_kaiser_shares_one_document_per_kind_and_comes_last(self):
        got = self.urls(plan("H9003-001-0", "Kaiser Permanente"), plan("H5216-048-0", "Humana"),
                        plan("H9003-006-0", "Kaiser Permanente"))
        self.assertEqual([(i, k) for i, k, _ in got], [
            ("H5216-048-0", "SB"), ("H5216-048-0", "EOC"), ("H9003-001-0;H9003-006-0", "SB"), ("H9003-001-0;H9003-006-0", "EOC")])
        self.assertTrue(got[-1][2].endswith("/eoc/medicare/2027/evidence-of-coverage-nw.pdf"))

    def test_other_carriers_have_no_template(self):
        self.assertEqual(self.urls(plan("H2056-003-0", "Aetna Medicare")), [])


class DocumentsTest(unittest.TestCase):
    plans = [plan("H1036-153-0", "Humana"), plan("H2056-003-0", "Aetna Medicare"), plan("H7006-018-0", "ATRIO"),
             plan("H7006-021-0", "ATRIO")]

    def documents(self, found, links):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            docs = find_docs.documents(self.plans, found, links, "2027")
        return [(d["plan_ids"], d["kind"], d["url"]) for d in docs], out.getvalue()

    def test_browser_finds_beat_the_links_sheet_which_beats_templates(self):
        found = [doc("H1036-153-0", "SB", "found-sb"), doc("H1036-153-0", "RIDER", "found-rider")]
        links = [doc("H1036-153-0", "SB", "link-sb"),
                 doc("H2056-003-0", "SB", "aetna-sb"), doc("H2056-003-0", "EOC", "aetna-eoc"),
                 doc("H7006-018-0;H7006-021-0", "SB", "atrio-sb"), doc("H7006-018-0", "EOC", "atrio-eoc-018"),
                 doc("H7006-021-0", "EOC", "atrio-eoc-021")]
        docs, warned = self.documents(found, links)
        self.assertEqual([u for _, _, u in docs], [
            "found-sb", "found-rider", "aetna-sb", "aetna-eoc", "atrio-sb", "atrio-eoc-018", "atrio-eoc-021",
            "https://assets.humana.com/is/content/humana/H1036153000EOC27pdf"])
        self.assertEqual(warned, "")
        docs, _ = self.documents([], [doc("H1036-153-0", "EOC", "link-eoc")])
        self.assertIn(("H1036-153-0", "EOC", "link-eoc"), docs)
        self.assertNotIn("H1036153000EOC27pdf", str(docs))

    def test_rejects_a_row_with_an_unknown_kind_or_plan(self):
        for row in (doc("H1036-153-0", "Eoc", "u"), doc("H1036-153-0;H0000-000-0", "SB", "u")):
            with self.subTest(row=row), self.assertRaisesRegex(SystemExit, "unknown kind or plan"):
                self.documents([], [row])

    def test_a_shared_link_keeps_only_the_plans_still_missing_that_kind(self):
        found = [doc("H7006-018-0", "SB", "found-sb")]
        docs, _ = self.documents(found, [doc("H7006-018-0;H7006-021-0", "SB", "atrio-sb")])
        self.assertIn(("H7006-021-0", "SB", "atrio-sb"), docs)

    def test_warns_about_each_plan_missing_an_sb_or_eoc(self):
        _, warned = self.documents([], [doc("H2056-003-0", "SB", "aetna-sb")])
        self.assertEqual(warned.splitlines(), [
            "::warning::No EOC for H2056-003-0", "::warning::No SB for H7006-018-0", "::warning::No EOC for H7006-018-0",
            "::warning::No SB for H7006-021-0", "::warning::No EOC for H7006-021-0"])


class Rebuild2027Test(unittest.TestCase):
    def test_rebuilds_the_committed_documents_list(self):
        data = years.data_dir(2027)
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp, "documents.csv")
            find_docs.main(data / "generated/plans.csv", data / "found.csv", data / "links.csv", out, "2027")
            self.assertEqual(out.read_text(), (data / "generated/documents.csv").read_text())


if __name__ == "__main__":
    unittest.main()
