# Reproduction from public sources

This folder rebuilds the 2027 Multnomah/Clackamas MA sheets without the volunteers' PDFs or summary tables.
It uses only the CMS Landscape and PBP Benefits files, carrier websites, and the plan documents those sites serve.
It follows `CLAUDE_ANALYSIS_METHODS.md` section 13.2 ("only this file and the internet").

Run `./run.sh <work_dir>` to download everything and regenerate `data/`. A fresh run on 2026-10-26 reproduced the committed files byte for byte.

## Results

| Step | Result |
|---|---|
| Plan universe | The Landscape file gives the same 39 plans as the methods doc, after dropping 2 D-SNPs and 4 I-SNPs. |
| Premium and Extra Help premium | All 39 premiums match the section 4 table. Extra Help premiums match wherever section 4 lists one. |
| Plan documents | All 73 SBs and EOCs were found. 71 are byte-identical to `SOURCES_MANIFEST.json`. |
| Main chart | 11 of the 13 Appendix B items are reproduced. The other 2 are not errors a generator can make or avoid. |
| DVHA sheet | 5 of the 7 significant DVHA findings are reproduced. |

`tests/test_reproduction.py` runs the generators on the PBP rows of the Appendix B plans (`tests/fixtures`) and asserts each reproduced correction. `run.sh` rewrites that fixture.

### Finding documents

Web search did not index any 2027 plan document. The documents were found as follows.

| Carriers | How |
|---|---|
| UHC/AARP (7 plans) | Plan detail pages on aarpmedicareplans.com, rendered in headless Chromium. These pages label each link SB or EOC. They also list Platinum Dental rider PDFs. |
| Wellcare (5), ATRIO (2) | The carrier's 2027 plan-materials page. |
| Humana (8), Devoted (7), Kaiser (3) | The URL templates in methods doc section 5.2. |
| Aetna (2), Regence (4), AgeRight (1) | Appendix A URLs. Their sites hide the links behind scripts or show none. |

Two UHC EOCs were re-issued on 2026-10-14 (`UHOR27HP0418842_001`, `AAOR27LP0418704_001`). Their dollar and percent amounts did not change.

### Main chart

`scripts/main_chart.py` builds columns C to AA from the PBP file. Some PBP fields are too coarse, so `data/sb_facts.csv` replaces those cells with values quoted from the SB. `scripts/cite.py` then finds each quote's PDF page. A quote that it cannot find stops the build.

- PBP "diagnostic radiology" ranges start at $0 because they include diagnostic mammograms. Column L line 2 therefore comes from the SB's CT/MRI/PET amounts for all 39 plans.
- The PBP has no naturopathy category. Column U is set when the SB or EOC mentions naturopathy outside the exclusions table. It is ◐ when a general wellness fund pays for it (Devoted 009).
- For five Devoted plans the PBP gives X-ray "$0-$75", but the SB and EOC give $25 to $75.
- UHC OR-1A inpatient care costs $0 or $1,980 per stay, depending on Medicaid status. The PBP gives only $0.

`data/pbp_vs_documents.csv` lists all 50 cells where the documents override the PBP.

Appendix B items that are reproduced: 1 (all four cells), 2, 3, 4, 5, 6, 7, 10, 11, 12, 13.
These items are not reproduced:

- Item 8 (Devoted CHOICE 002 X-ray) is a disagreement between the SB and the EOC. The generator follows the SB and PBP.
- Item 9 is a typo in the volunteers' sheet.

For items 2 and 13 the generator prints "Part B deductible" instead of a dollar amount, because CMS has not announced the 2027 amount yet.

### DVHA sheet

`scripts/dvha.py` writes short summaries of the mandatory supplemental benefits. Optional riders go in column E.
These DVHA items are reproduced: 1 (Wellcare comprehensive dental covers adjunctive services only), 2 (Kaiser Standard $100/2-year eyewear), 3 ($25,000 worldwide cap on all 7 Devoted rows), 6 (Regence routine podiatry, $0 for 6 visits a year, which the PBP files as a targeted benefit), and 7 (Humana MyOption $1,500 max).
These items are not reproduced: 4 (Devoted rewards) and 5 (Regence virtual urgent care out of network). Rewards programs are not in the PBP, and the generator does not cover virtual care.

## Limits

- The PBP is bid data, not a citable document. Only the cells in `data/citations.csv` and `data/eoc_citations.csv` carry SB/EOC page citations.
- `run.sh` does not produce `data/eoc_citations.csv`; see issue #8. A citation is kept only if the EOC value matches the cell, the quote highlights once on its page, and two models both confirm it.
- DVHA cells leave out vendor names, frequency limits and rewards. Shared allowances (Devoted, ATRIO) show only as the services they cover.
- Some PBP fields have no amount. DVHA then says "OTC covered", although the SB gives one (UHC $25/quarter, Humana 317 $175/month).
- PBP ranges can start at $0 where the SB gives only the upper amount (UHC specialist "$0-$55").
- The dot rules follow the methods doc's inferred policy R10 to R13: a dot means a mandatory supplemental benefit. SSBCI and targeted (UF/VBID) benefits are listed in DVHA column J. They do not get dots, except where the base PBP benefit sets one.
- No person has reviewed these outputs.
