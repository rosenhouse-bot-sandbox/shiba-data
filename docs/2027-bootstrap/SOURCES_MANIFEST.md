# Source document manifest (baseline, 2026-10-26)

This file and `SOURCES_MANIFEST.json` record every PDF the 2027 verification work relied on, so that the PDFs themselves (about 200 MB) don't need to be kept with the project. For each file they record where it can be downloaded today, its SHA-256, and text fingerprints that still match after a PDF has been re-saved or re-rendered. With these, a separate agent can download the documents again and tell whether it has the same thing we analyzed, and if not, which pages changed.

`SOURCES_MANIFEST.json` is the complete record. It also holds per-page text hashes for every document. The table below is a summary generated from it.

## How the baseline was made

1. Every URL on the volunteers' Links sheet (16-Oct-26), plus the URLs in `sources/tentative/README.md`, was downloaded on 2026-10-26 (74 URLs). 73 returned a PDF. `https://www.uhc.com/medicare/alphadog/UHOR27LP0412518_000` returned HTTP 403 to curl; the same document ID on `www.aarpmedicareplans.com` serves the file.
2. Every local PDF (48 in `sources/`, 27 in `sources/tentative/`, 8 in `analysis/`) and every download was fingerprinted with the recipe below.
3. Each local file was paired with the URL that serves the same document, by byte hash, then by text hash, then by hand for 13 files (each confirmed by plan ID, document code and page count). The pairing result is stored as `url_check_2026_10_26`.

## What we found

- **Each URL still serves the document we analyzed.** On every page that has extractable text in both copies, no dollar or percent figure differs between a local file and its URL today.
- **None of the volunteers' 48 files is byte-identical to its URL, and that is expected.** Every one was re-saved by a browser: 44 by Chrome's PDF viewer (PDF metadata "PDFium") and 4 by Firefox print-to-PDF ("cairo"). That rewrites the bytes. Compare their text fingerprints, not their SHA-256.
  - 34 have identical text.
  - 3 AARP Summaries of Benefits have the same words in a different reading order (the Firefox re-prints).
  - 1 AARP Summary of Benefits (Extras OR-6) has identical numbers and differs only in how a few words split. Same cause.
  - 8 EOCs (7 AARP/UHC, 1 Humana Choice) match on every page except 2 back-matter notice pages, which have no extractable text in today's download.
  - **1 was re-issued by the carrier:** "Atrio Freedom (PPO) No Rx Evidece of Coverage 2027.pdf". The volunteer saved it on 2026-10-09; the file served today was created on 2026-10-14. Every number is identical, but some wording changed, e.g. page 50 "Fitness program Benefit allowance loaded to your Flex Card" became "Fitness program Benefit can be used". If a finding ever depends on that file's wording, re-check it against the current file.
- **All 27 tentative downloads are byte-identical** to what their URLs serve today.
- The truncated Regence Valiance EOC link on the Links sheet (`https://beonbrand.getbynder.com/asset/5b106892-e6c7-4c40-864b-6477ed6bd1b7/`) works as-is. It serves the Valiance EOC.
- `AARP-UHC Optional Dental Rider $1500 Max.pdf` has no known URL. It is a 2-page excerpt saved from a browser.
- The 8 `analysis/` PDFs are printouts of the volunteers' private Google Sheets. They are recorded by hash only.

## How to compare a fresh download against this baseline

1. Download the `url`. If its SHA-256 equals `url_check_2026_10_26.sha256` (or the file's own `sha256` when the result was `bytes_identical`), it is the same file that was served on 2026-10-26. Done.
2. Otherwise compute the fingerprints below with the same tool and version, and compare against the file's own values (what we analyzed) in this order: `text_seq_sha256` (same text) → `word_bag_sha256` (same words) → `numbers_sha256` (same numbers).
3. If they differ, compare `page_text_sha256_16` page by page to list the changed pages. Then check whether any finding in `DVHA_VERIFICATION.md` or `MAIN_CHART_ISSUES_TO_REVIEW.md` cites those pages. Page counts can shift when a document is re-issued, so match moved pages by hash, not by position.
4. Text hashes depend on the extractor. A different PDF library, or a different pypdfium2 version, may order or split text differently. If you can't use pypdfium2 5.14.0, rely on SHA-256, page count, `numbers_sha256` (the least sensitive) and the document codes printed on the cover.

## Fingerprint recipe (exact)

```python
# pypdfium2 5.14.0; one PDF per process (protects the batch if a PDF crashes the library)
import re, hashlib, unicodedata, collections, pypdfium2 as pdfium
def fingerprints(path):
    raw = open(path, "rb").read()
    d = pdfium.PdfDocument(path)
    pages = [d[i].get_textpage().get_text_range() for i in range(len(d))]
    H = lambda s: hashlib.sha256(s.encode()).hexdigest()
    low = lambda s: unicodedata.normalize("NFKC", s).lower()
    seq = lambda s: re.sub(r"[^a-z0-9$%]", "", low(s))
    t = low("\n".join(pages))
    bag = collections.Counter(re.findall(r"[a-z]+|\d+", t))
    nums = collections.Counter(n.replace(",", "") for n in re.findall(r"\$?\d+(?:[.,]\d+)*%?", t))
    return dict(
        sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), pages=len(d),
        pages_with_text=sum(1 for x in pages if x.strip()),
        text_seq_sha256=H("".join(seq(x) for x in pages)),
        word_bag_sha256=H("\n".join(f"{k} {v}" for k, v in sorted(bag.items()))),
        numbers_sha256=H("\n".join(f"{k} {v}" for k, v in sorted(nums.items()))),
        page_text_sha256_16=[H(seq(x))[:16] for x in pages],
    )
```

The JSON also records PDF metadata (title, creator, producer, creation date). The creation date is the quickest sign that a carrier has re-issued a document.

## Files

### Volunteer-supplied files (`sources/`)

| File | Doc | Plan ID(s) | Sheet rows | URL | URL check 2026-10-26 | SHA-256 (first 16) |
|---|---|---|---|---|---|---|
| AARP Complete Care OR-5 (HMO C-SNP) SummBens.pdf | SB | H3805-040 | C-SNP#6 | https://www.aarpmedicareplans.com/alphadog/UHOR27HP0412772_000 | same words, reordered | `476db1bd4df7f912` |
| AARP Essentials OR-7 (HMO-POS) SummBens.pdf | SB | H3805-048 | MA-PD#1 | https://www.aarpmedicareplans.com/alphadog/AAOR27HP0412776_000 | same words, reordered | `76cc1b96914fbd80` |
| AARP Extras OR-6 (HMO-POS) SummBens.pdf | SB | H3805-041 | MA-PD#2 | https://www.aarpmedicareplans.com/alphadog/AAOR27HP0412773_000 | numbers identical, wording differs | `69504fc3b7c0a47a` |
| AARP Medicare Advantage Essentials OR-007 (HN+MO-POS) EOC 2027.pdf | EOC | H3805-048 | MA-PD#1 | https://www.aarpmedicareplans.com/alphadog/AAOR27HP0418846_000 | same except 2 pages without text | `410282e2e23ebde7` |
| AARP Patriot No Rx (PPO) EOC 2027.pdf | EOC | H2406-073 | NO-PART-D#1 | https://www.aarpmedicareplans.com/alphadog/AAOR27LP0418704_000 | same except 2 pages without text | `405f18683a585dc4` |
| AARP Patriot No Rx OR-MA01 PPO Summ Bens.pdf | SB | H2406-073 | NO-PART-D#1 | https://www.aarpmedicareplans.com/alphadog/AAOR27LP0412634_000 | same words, reordered | `1e06a681598a7a23` |
| AARP from UHC Extras (HMO-POS) OR-006 EOC 2027.pdf | EOC | H3805-041 | MA-PD#2 | https://www.aarpmedicareplans.com/alphadog/AAOR27HP0418843_000 | same except 2 pages without text | `c11bc83816edc15b` |
| AARP from UHC OR-001 (PPO) EOC 2027.pdf | EOC | H2406-042 | MA-PD#3 | https://www.aarpmedicareplans.com/alphadog/AAOR27LP0418684_000 | same except 2 pages without text | `1b745a8569eb60e6` |
| AARP from UHC OR-002 (PPO) EOC 2027.pdf | EOC | H2406-070 | MA-PD#4 | https://www.aarpmedicareplans.com/alphadog/AAOR27LP0418701_000 | same except 2 pages without text | `f692fe1333d80558` |
| AARP-UHC Optional Dental Rider $1500 Max.pdf | RIDER | - | - | none | no URL | `2feed238da7ae75c` |
| Aetna Medicare Eagle No Rx EOC (HMO) 2027.pdf | EOC | H2056-018 | NO-PART-D#2 | https://www.aetna.com/medicare/documents/individual/2027/eoc/en/Y0001_H2056_018_NS45_EOC2027_C.pdf | text identical | `976dab67db458fc7` |
| Aetna Medicare Eagle No Rx SummBens 2027.pdf | SB | H2056-018 | NO-PART-D#2 | https://www.aetna.com/medicare/documents/individual/2027/sb/en/Y0001_H2056_018_NS45_SB2027_M.pdf | text identical | `1dfa073784371a7d` |
| Aetna Medicare Elite EOC (HMO) EOC.pdf | EOC | H2056-003 | MA-PD#5 | https://www.aetna.com/medicare/documents/individual/2027/eoc/en/Y0001_H2056_003_HR01_EOC2027_C.pdf | text identical | `155557920b4393bf` |
| Atrio Freedom (PPO) No Rx Evidece of Coverage 2027.pdf | EOC | H7006-021 | NO-PART-D#3 | https://atriohp.com/media/qyfpfa50/h7006_021_eoc_2027_atrio-freedom-ppo-portland.pdf | numbers identical, wording differs | `d08b5348ff0b1951` |
| Atrio both Choice and Freedom Summ of Benefits 2027.pdf | SB | H7006-018, H7006-021 | MA-PD#6, NO-PART-D#3 | https://atriohp.com/media/254ghvxu/2027-portland-sb_final-v2.pdf | text identical | `7fb6b43c6bb5b10d` |
| Devoted (HMO-C-SNP) Plus 009 SummBens2027.pdf | SB | H2923-009 | C-SNP#3 | https://assets.devoted.com/plan-documents/2027/2027-DEVOTED-C-SNP-PLUS-009-OR-%28HMO-C-SNP%29-SB-H2923-009-ENG.pdf | text identical | `0bad1fc00d54a543` |
| Devoted C-SNP Plus 009 (HMO) EOC 2027.pdf | EOC | H2923-009 | C-SNP#3 | https://assets.devoted.com/plan-documents/2027/2027-DEVOTED-C-SNP-PLUS-009-OR-%28HMO-C-SNP%29-EOC-H2923-009-ENG.pdf | text identical | `257afeecc8f20b42` |
| Devoted Choice Premium 002 OR (PPO) Summ Bens 2027.pdf | SB | H7199-002 | MA-PD#11 | https://assets.devoted.com/plan-documents/2027/2027-DEVOTED-CHOICE-PREMIUM-002-OR-%28PPO%29-SB-H7199-002-ENG.pdf | text identical | `a2736cb23a1d9bec` |
| Devoted Choice Premium002 (PPO) EOC 2027.pdf | EOC | H7199-002 | MA-PD#11 | https://assets.devoted.com/plan-documents/2027/2027-DEVOTED-CHOICE-PREMIUM-002-OR-%28PPO%29-EOC-H7199-002-ENG.pdf | text identical | `3b0620af2ba8285b` |
| Devoted Core 001 OR (HMO) EOC 2027.pdf | EOC | H2923-001 | MA-PD#7 | https://assets.devoted.com/plan-documents/2027/2027-DEVOTED-CORE-001-OR-%28HMO%29-EOC-H2923-001-ENG.pdf | text identical | `95b26443aed61607` |
| Devoted Giveback 028 (HMO) EOC 2027.pdf | EOC | H2923-028 | MA-PD#8 | https://assets.devoted.com/plan-documents/2027/2027-DEVOTED-GIVEBACK-028-OR-%28HMO%29-EOC-H2923-028-003-ENG.pdf | text identical | `81f0fd8c870ab8bf` |
| Devoted Giveback 028 (HMO) SummBens 2027.pdf | SB | H2923-028 | MA-PD#8 | https://assets.devoted.com/plan-documents/2027/2027-DEVOTED-GIVEBACK-028-OR-%28HMO%29-SB-H2923-028-003-ENG.pdf | text identical | `f51d6213b2dbb030` |
| Devoted Giveback Extras (HMO) Summ Bens 2027.pdf | SB | H2923-019 | C-SNP#2 | https://assets.devoted.com/plan-documents/2027/2027-DEVOTED-C-SNP-GIVEBACK-EXTRAS-019-OR-%28HMO-C-SNP%29-SB-H2923-019-ENG.pdf | text identical | `0fc4056a8fb06b81` |
| Devoted Giveback Extras 025 (HMO) EOC 2027.pdf | EOC | H2923-025 | MA-PD#9 | https://assets.devoted.com/plan-documents/2027/2027-DEVOTED-GIVEBACK-EXTRAS-025-OR-%28HMO%29-EOC-H2923-025-ENG.pdf | text identical | `e3736125a0843b7c` |
| Devoted HMO C-SNP Giveback Extras 019 EOC 2027.pdf | EOC | H2923-019 | C-SNP#2 | https://assets.devoted.com/plan-documents/2027/2027-DEVOTED-C-SNP-GIVEBACK-EXTRAS-019-OR-%28HMO-C-SNP%29-EOC-H2923-019-ENG.pdf | text identical | `58070574d0e9c063` |
| Devoted Health Giveback Extras 025 (HMO) Summ Bens.pdf | SB | H2923-025 | MA-PD#9 | https://assets.devoted.com/plan-documents/2027/2027-DEVOTED-GIVEBACK-EXTRAS-025-OR-%28HMO%29-SB-H2923-025-ENG.pdf | text identical | `1bb63224f467fa8d` |
| Devoted Premium 005 OR (HMO) EOC 2027.pdf | EOC | H2923-005 | MA-PD#10 | https://assets.devoted.com/plan-documents/2027/2027-DEVOTED-PREMIUM-005-OR-%28HMO%29-EOC-H2923-005-ENG.pdf | text identical | `103b49466e3f1e96` |
| Devoted Premium 005 OR (HMO) Summ Bens 2027.pdf | SB | H2923-005 | MA-PD#10 | https://assets.devoted.com/plan-documents/2027/2027-DEVOTED-PREMIUM-005-OR-%28HMO%29-SB-H2923-005-ENG.pdf | text identical | `3e11c706552a2faf` |
| Humana Choice H5216-048 (PPO) EOC 2027.pdf | EOC | H5216-048 | MA-PD#15 | https://assets.humana.com/is/content/humana/H5216048000EOC27pdf | same except 2 pages without text | `82bdd388191b061b` |
| Humana Essentials Plus Giveback (HMO) - H1036323 Summ Bens 2027.pdf | SB | H1036-323 | MA-PD#13 | https://assets.humana.com/is/content/humana/H1036323000SB27pdf | text identical | `f60b53a53d3d6732` |
| Humana Essentials Plus Giveback (HMO) H1036 323 EOC 2027.pdf | EOC | H1036-323 | MA-PD#13 | https://assets.humana.com/is/content/humana/H1036323000EOC27pdf | text identical | `42e27517c707dd8f` |
| Humana Value Choice H5216 428 EOC 2027.pdf | EOC | H5216-428 | MA-PD#14 | https://assets.humana.com/is/content/humana/H5216428002EOC27pdf | text identical | `b5b461c8df9c485c` |
| Kaiser All plans Summ Bens 2027.pdf | SB | H9003-001, H9003-006, H9003-009 | MA-PD#16, MA-PD#17, MA-PD#18 | https://healthy.kaiserpermanente.org/content/dam/kporg/final/documents/health-plan-documents/summary-of-benefits/medicare/2027/summary-of-benefits-nw.pdf | text identical | `9a01133fc133d261` |
| Kaiser Senior Advantage Enhanced Standard and Value EOC 2027.pdf | EOC | H9003-001, H9003-006, H9003-009 | MA-PD#16, MA-PD#17, MA-PD#18 | https://healthy.kaiserpermanente.org/content/dam/kporg/final/documents/health-plan-documents/eoc/medicare/2027/evidence-of-coverage-nw.pdf | text identical | `e7806ba5933c07b1` |
| Regence MedAdv + Rx Primary SummBens 2027.pdf | SB | H3817-011 | MA-PD#21 | https://beonbrand.getbynder.com/asset/e02efc92-b5dc-44f5-97ed-68489555c3df/Summary-of-Benefits-Medicare-MedAdvantage-Rx-Primary-2027-OR-Metro.pdf | text identical | `5fcadb193590d55a` |
| Regence MedAdvantage + Rx Classic PPO EOC 2027.pdf | EOC | H3817-008 | MA-PD#19 | https://beonbrand.getbynder.com/asset/85039f9f-9466-4c0f-9edc-0016f91d698f/Evidence-of-Coverage-Medicare-MedAdvantage-Rx-Classic-2027-OR-Metro.pdf | text identical | `87718d90c48d258c` |
| Regence MedAdvantage + Rx Classic PPO SummBens 2027.pdf | SB | H3817-008 | MA-PD#19 | https://beonbrand.getbynder.com/asset/509b7b1f-c03e-498d-9107-158cc9783b71/Summary-of-Benefits-Medicare-MedAdvantage-Rx-Classic-2027-OR-Metro.pdf | text identical | `38119ce8649c4ce1` |
| Regence MedAdvantage + Rx ENHANCED PPO EOC 2027.pdf | EOC | H3817-009 | MA-PD#20 | https://beonbrand.getbynder.com/asset/84960024-c25d-4f1d-acd1-d3f30ab21ac1/Evidence-of-Coverage-Medicare-MedAdvantage-Rx-Enhanced-2027-OR-Metro.pdf | text identical | `f9a6ed9904734f4a` |
| Regence MedAdvantage + Rx Enhanced (PPO) SummBens 2027.pdf | SB | H3817-009 | MA-PD#20 | https://beonbrand.getbynder.com/asset/0231d9b3-b90f-4080-82e8-9213fa8a7464/Summary-of-Benefits-Medicare-MedAdvantage-Rx-Enhanced-2027-OR-Metro.pdf | text identical | `dd29f97ee3b958b3` |
| Regence MedAdvantage + Rx PRIMARY PPO EOC 2027.pdf | EOC | H3817-011 | MA-PD#21 | https://beonbrand.getbynder.com/asset/78bdf8d9-4f73-4ab9-858f-ab6466e7e5c7/Evidence-of-Coverage-Medicare-MedAdvantage-Rx-Primary-2027-OR-Metro.pdf | text identical | `e59ee22ef3d797f6` |
| Regence VALIANCE PPO No Rx EOC 2027.pdf | EOC | H3817-010 | NO-PART-D#6 | https://beonbrand.getbynder.com/asset/5b106892-e6c7-4c40-864b-6477ed6bd1b7/ | text identical | `0ed4fa1865be6272` |
| UHC Complete Care OR-5 (HMO C-SNP EOC 2027.pdf | EOC | H3805-040 | C-SNP#6 | https://www.aarpmedicareplans.com/alphadog/UHOR27HP0418842_000 | same except 2 pages without text | `1140f6b800726087` |
| UHC Complete Care Support OR-1A (C-SNP) EOC 2027.pdf | EOC | H2001-045 | C-SNP#7 | https://www.aarpmedicareplans.com/alphadog/UHOR27LP0418588_000 | same except 2 pages without text | `70af5c23f0d45264` |
| Wellcare Low Premium (HMO-POS) EOC 2027.pdf | EOC | H6815-038 | MA-PD#22 | https://contentserver.destinationrx.com/ContentServer/DRxProductContent/PDFs/149_0/2027/H6815_038_2027_OR_EOC_HMAPD_7001734ENG_C.pdf | text identical | `8c72f2fdd902925d` |
| Wellcare Low Premium Open (PPO)  EOC 207.pdf | EOC | H5439-015 | MA-PD#23 | https://contentserver.destinationrx.com/ContentServer/DRxProductContent/PDFs/149_0/2027/H5439_015_2027_OR_EOC_PPO_7001681ENG_C.pdf | text identical | `e3185a0e89541402` |
| Wellcare Patriot Giveback Open no Rx (PPO) EOC 2027.pdf | EOC | H5439-010 | NO-PART-D#7 | https://contentserver.destinationrx.com/ContentServer/DRxProductContent/PDFs/149_0/2027/H5439_010_2027_OR_EOC_PMAO_7001732ENG_C.pdf | text identical | `607cdd9027020f31` |
| Wellcare Premium Enhanced Open (PPO) EOC 2027.pdf | EOC | H5439-019 | MA-PD#24 | https://contentserver.destinationrx.com/ContentServer/DRxProductContent/PDFs/149_0/2027/H5439_019_2027_OR_EOC_PPO_7001682ENG_C.pdf | text identical | `6134a078826b971c` |
| Wellcare Premium Ultra Open (PPO) EOC 2027.pdf | EOC | H5439-011 | MA-PD#25 | https://contentserver.destinationrx.com/ContentServer/DRxProductContent/PDFs/149_0/2027/H5439_011_2027_OR_EOC_PPO_7001680ENG_C.pdf | text identical | `81f1ab4d7a36484c` |

### Claude-downloaded files (`sources/tentative/`)

| File | Doc | Plan ID(s) | Sheet rows | URL | URL check 2026-10-26 | SHA-256 (first 16) |
|---|---|---|---|---|---|---|
| AARP from UHC OR-001 H2406-042 (PPO) SB 2027.pdf | SB | H2406-042 | MA-PD#3 | https://www.aarpmedicareplans.com/alphadog/AAOR27LP0412614_000 | bytes identical | `cd39f32cdbd73e52` |
| AARP from UHC OR-002 H2406-070 (PPO) SB 2027.pdf | SB | H2406-070 | MA-PD#4 | https://www.aarpmedicareplans.com/alphadog/AAOR27LP0412631_000 | bytes identical | `d4758cd5b94a2266` |
| Aetna Medicare Elite H2056-003 SB 2027.pdf | SB | H2056-003 | MA-PD#5 | https://www.aetna.com/medicare/documents/individual/2027/sb/en/Y0001_H2056_003_HR01_SB2027_M.pdf | bytes identical | `05d56d5f782708e7` |
| AgeRight Advantage Premier Health Plan H1372-003-0 EOC 2027.pdf | EOC | H1372-003 | C-SNP#1 | https://agerightadvantage.com/wp-content/uploads/2026/10/H1372_003_0_EOC_v03_508.pdf | bytes identical | `4ec81cd0d2695486` |
| AgeRight Advantage Premier Health Plan H1372-003-0 SB 2027.pdf | SB | H1372-003 | C-SNP#1 | https://agerightadvantage.com/wp-content/uploads/2026/09/H1372_003_0_SB_v07.pdf | bytes identical | `61de2101267140ce` |
| Atrio Choice Rx H7006-018 EOC 2027.pdf | EOC | H7006-018 | MA-PD#6 | https://atriohp.com/media/qzyffvwm/h7006_018_eoc_2027_atrio-choice-rx-ppo-portland.pdf | bytes identical | `bee1858e7e963c62` |
| Devoted C-SNP Giveback Extras 019 H2923-019 SB 2027.pdf | SB | H2923-019 | C-SNP#2 | https://assets.devoted.com/plan-documents/2027/2027-DEVOTED-C-SNP-GIVEBACK-EXTRAS-019-OR-%28HMO-C-SNP%29-SB-H2923-019-ENG.pdf | bytes identical | `2a970381e331a34a` |
| Devoted CORE 001 H2923-001 SB 2027.pdf | SB | H2923-001 | MA-PD#7 | https://assets.devoted.com/plan-documents/2027/2027-DEVOTED-CORE-001-OR-%28HMO%29-SB-H2923-001-ENG.pdf | bytes identical | `bf93677641b9fa6f` |
| Humana Choice H5216-048 SB 2027.pdf | SB | H5216-048 | MA-PD#15 | https://assets.humana.com/is/content/humana/H5216048000SB27pdf | bytes identical | `faebfcb17c1abba1` |
| Humana Gold Plus Diabetes and Heart H1036-306-0 EOC 2027.pdf | EOC | H1036-306 | C-SNP#4 | https://assets.humana.com/is/content/humana/H1036306000EOC27pdf | bytes identical | `a744eaa24232bb11` |
| Humana Gold Plus Diabetes and Heart H1036-306-0 SB 2027.pdf | SB | H1036-306 | C-SNP#4 | https://assets.humana.com/is/content/humana/H1036306000SB27pdf | bytes identical | `4a0ee31be3437c35` |
| Humana Gold Plus Diabetes and Heart H1036-317-0 EOC 2027.pdf | EOC | H1036-317 | C-SNP#5 | https://assets.humana.com/is/content/humana/H1036317000EOC27pdf | bytes identical | `630e49b10e7ad131` |
| Humana Gold Plus Diabetes and Heart H1036-317-0 SB 2027.pdf | SB | H1036-317 | C-SNP#5 | https://assets.humana.com/is/content/humana/H1036317000SB27pdf | bytes identical | `29166053e638f7e6` |
| Humana Total Complete H1036-153 EOC 2027.pdf | EOC | H1036-153 | MA-PD#12 | https://assets.humana.com/is/content/humana/H1036153000EOC27pdf | bytes identical | `64e05773e847b56e` |
| Humana Total Complete H1036-153 SB 2027.pdf | SB | H1036-153 | MA-PD#12 | https://assets.humana.com/is/content/humana/H1036153000SB27pdf | bytes identical | `ce13e925c0384896` |
| Humana USAA Honor Giveback H5216-427-2 EOC 2027.pdf | EOC | H5216-427 | NO-PART-D#5 | https://assets.humana.com/is/content/humana/H5216427002EOC27pdf | bytes identical | `0bd982dc589e8cba` |
| Humana USAA Honor Giveback H5216-427-2 SB 2027.pdf | SB | H5216-427 | NO-PART-D#5 | https://assets.humana.com/is/content/humana/H5216427002SB27pdf | bytes identical | `b4be2a8a3e57d86a` |
| Humana USAA Honor Giveback H5216-455-0 EOC 2027.pdf | EOC | H5216-455 | NO-PART-D#4 | https://assets.humana.com/is/content/humana/H5216455000EOC27pdf | bytes identical | `aca9d3510177adcd` |
| Humana USAA Honor Giveback H5216-455-0 SB 2027.pdf | SB | H5216-455 | NO-PART-D#4 | https://assets.humana.com/is/content/humana/H5216455000SB27pdf | bytes identical | `2af2a9f1fd104b7f` |
| Humana Value Choice H5216-428-2 SB 2027.pdf | SB | H5216-428 | MA-PD#14 | https://assets.humana.com/is/content/humana/H5216428002SB27pdf | bytes identical | `e41fce2e65cf35f2` |
| Regence Valiance PPO No Rx H3817-010 SB 2027.pdf | SB | H3817-010 | NO-PART-D#6 | https://beonbrand.getbynder.com/asset/04a8c0a0-9d0b-4085-a9c5-657b68a53d5a/Summary-of-Benefits-Medicare-Regence-Valiance-PPO-no-Rx-2027-OR.pdf | bytes identical | `6c89db5198e7a3b2` |
| UHC Complete Care Support OR-1A H2001-045 (PPO C-SNP) SB 2027.pdf | SB | H2001-045 | C-SNP#7 | https://www.uhc.com/medicare/alphadog/UHOR27LP0412518_000 | bytes identical | `362ee075ea5896d4` |
| Wellcare Low Premium H6815-038 SB 2027.pdf | SB | H6815-038 | MA-PD#22 | https://contentserver.destinationrx.com/ContentServer/DRxProductContent/PDFs/149_0/2027/H6815_038_2027_OR_SB_HMAPD_7017558ENG_M.pdf | bytes identical | `614d6949480ad32c` |
| Wellcare Low Premium Open H5439-015 SB 2027.pdf | SB | H5439-015 | MA-PD#23 | https://contentserver.destinationrx.com/ContentServer/DRxProductContent/PDFs/149_0/2027/H5439_015_2027_OR_SB_PPO_7017569ENG_M.pdf | bytes identical | `284bdb89ac745620` |
| Wellcare Patriot Giveback Open H5439-010 SB 2027.pdf | SB | H5439-010 | NO-PART-D#7 | https://contentserver.destinationrx.com/ContentServer/DRxProductContent/PDFs/149_0/2027/H5439_010_2027_OR_SB_PMAO_7017600ENG_M.pdf | bytes identical | `b50c8a1aad018d9f` |
| Wellcare Premium Enhanced Open H5439-019 SB 2027.pdf | SB | H5439-019 | MA-PD#24 | https://contentserver.destinationrx.com/ContentServer/DRxProductContent/PDFs/149_0/2027/H5439_019_2027_OR_SB_PPO_7017570ENG_M.pdf | bytes identical | `133e24a6e285ac26` |
| Wellcare Premium Ultra Open H5439-011 SB 2027.pdf | SB | H5439-011 | MA-PD#25 | https://contentserver.destinationrx.com/ContentServer/DRxProductContent/PDFs/149_0/2027/H5439_011_2027_OR_SB_PPO_7017601ENG_M.pdf | bytes identical | `c601279fdce42898` |

### Volunteer sheets (`analysis/`, no public URL)

| File | Pages | SHA-256 (first 16) |
|---|---|---|
| 2026 SHIBA GUIDE Excerpts-Compare among Plans,  compare to Med Advntg.pdf | 4 | `3fa88645d9080ed7` |
| 2027 Edit and Comparison 10-11-2026 MAPD- Ed,Compr,Orig.pdf | 4 | `00384f92ed0f0dba` |
| 2027 Main MA Chart 2027  10.16.26.xlsx - Google Sheets.pdf | 3 | `edaa2fe5e25211cd` |
| 2027_DVHA Edit and Comparison 10-11-2026 - Google Sheets - 2027_DVHA Edit and Comparison 10-11-2026 - Google Sheets PDF.pdf | 4 | `a2e244dc1b83b18d` |
| 2027_DVHA Edit and Comparison 10-11-2026 - Google Sheets.pdf | 4 | `ef2337719ab29d13` |
| 2027_Links to Summ Bens & EOCs csc 16-Oct-26.xlsx - Google Sheets.pdf | 3 | `0869e126d32e33f4` |
| 2027_Links to Summary of Benefits & EOCs csc 13-Oct-26.xlsx - Google Sheets.pdf | 3 | `00cc9f5db519edf1` |
| MA 2027 - Edit and Comparison 10-11-2026 - Google Sheets.pdf | 4 | `3007c71cdf56ffcd` |
