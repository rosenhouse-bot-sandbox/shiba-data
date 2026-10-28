# 2027 data from public sources

This folder holds the 2027 Multnomah/Clackamas MA sheets, built without the volunteers' PDFs or summary tables.
They come only from the CMS Landscape and PBP Benefits files, carrier websites, and the plan documents those sites serve.
The method follows `docs/2027-bootstrap/CLAUDE_ANALYSIS_METHODS.md` section 13.2 ("only this file and the internet").

`python3 -I pipeline/run.py 2027 <work_dir>` downloads the sources named in `config.json` and `documents.csv` and regenerates `generated/`.
It then rebuilds `machine/blanks.csv` and `machine/filled.csv` from the model answers saved in `answers/`.

## Layers

The site shows the generated sheets with three layers applied in order. Each layer row cites the value of a cell, or of one line of it.

| File | Rows from | Sets the value |
|---|---|---|
| `generated/citations.csv` | `pipeline/cite.py`: naturopathy dots, which the PBP lacks | Yes |
| `machine/eoc_citations.csv` | Model steps run by earlier Claude sessions, with `step` xref | No, until people review model corrections (issue #48) |
| `machine/blanks.csv`, `machine/filled.csv` | `pipeline/blanks.py` and `pipeline/filled.py`. `prompt` hashes the step's prompts. | No |
| `edits.csv` | People, and Claude sessions they steer | Yes |

A later layer wins. The site drops a citation whose value is not the live cell's.

## Results

| Step | Result |
|---|---|
| Plan universe | The Landscape file gives the same 39 plans as the methods doc, after dropping 2 D-SNPs and 4 I-SNPs. |
| Premium and Extra Help premium | All 39 premiums match the section 4 table. Extra Help premiums match wherever section 4 lists one. |
| Plan documents | All 73 SBs and EOCs were found. 71 are byte-identical to `docs/2027-bootstrap/SOURCES_MANIFEST.json`. |
| Main chart | 11 of the 13 Appendix B items are reproduced. The other 2 are not errors a generator can make or avoid. |
| DVHA sheet | 5 of the 7 significant DVHA findings are reproduced. |

`pipeline/tests/test_reproduction.py` runs the generators on the PBP rows of the Appendix B plans (`pipeline/tests/fixtures`) and asserts each reproduced correction. `pipeline/tests/make_fixture.py <pbp_dir>` rewrites that fixture.

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

`pipeline/main_chart.py` builds columns C to AA from the PBP file. Some PBP fields are too coarse, so `edits.csv` replaces those cells with values quoted from the SB or EOC.
`pipeline/fields.py` gives each column's rules.

- PBP "diagnostic radiology" ranges start at $0 because they include diagnostic mammograms. Column L line 2 therefore comes from the SB's CT/MRI/PET amounts for all 39 plans.
- The PBP has no naturopathy category. Column U is set when the SB or EOC mentions naturopathy outside the exclusions table. It is ◐ when a general wellness fund pays for it (Devoted 009).
- For five Devoted plans the PBP gives X-ray "$0-$75", but the SB and EOC give $25 to $75.
- UHC OR-1A inpatient care costs $0 or $1,980 per stay, depending on Medicaid status. The PBP gives only $0.
- Six Humana plans cover acupuncture only for chronic low back pain, which Medicare covers. Column S is blank for them.
- Devoted 009 pays for acupuncture and massage only from its Wellness Bucks, so columns S and V are ◐.

The layers change 117 cells. The site shows the PBP value of each.

Appendix B items that are reproduced: 1 (all four cells), 2, 3, 4, 5, 6, 7, 10, 11, 12, 13.
These items are not reproduced:

- Item 8 (Devoted CHOICE 002 X-ray) is a disagreement between the SB and the EOC. The generator follows the SB and PBP.
- Item 9 is a typo in the volunteers' sheet.

For items 2 and 13 the generator prints "Part B deductible" instead of a dollar amount, because CMS has not announced the 2027 amount yet.

### DVHA sheet

`pipeline/dvha.py` writes short summaries of the mandatory supplemental benefits. Optional riders go in column E.
`edits.csv` replaces 79 whole DVHA cells with EOC values. Their PBP parts are copied by hand, so a PBP update needs a check of those cells.
These DVHA items are reproduced: 1 (Wellcare comprehensive dental covers adjunctive services only), 2 (Kaiser Standard $100/2-year eyewear), 3 ($25,000 worldwide cap on all 7 Devoted rows), 6 (Regence routine podiatry, $0 for 6 visits a year, which the PBP files as a targeted benefit), and 7 (Humana MyOption $1,500 max).
These items are not reproduced: 4 (Devoted rewards) and 5 (Regence virtual urgent care out of network). Rewards programs are not in the PBP, and the generator does not cover virtual care.

## Limits

- The PBP is bid data, not a citable document. Only the cells that a layer cites carry SB/EOC page citations.
- `run.py` does not run the model steps (issue #46). A model step publishes a citation only if the EOC value matches the cell, the quote highlights once on its page, and two models both confirm it.
- DVHA cells leave out vendor names, frequency limits and rewards. ATRIO's shared allowance shows only as the services it covers.
- PBP ranges can start at $0 for a service other than the one the column names. `edits.csv` corrects the cases issue #31 found.
- The dot rules in `pipeline/fields.py` follow the methods doc's inferred policy R10 to R13, not rules from the SHIBA team.
- No person has reviewed these outputs.
