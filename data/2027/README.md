# 2027 data from public sources

This folder holds the 2027 Multnomah/Clackamas MA sheets, built without the volunteers' PDFs or summary tables.
They come only from the CMS Landscape and PBP Benefits files, carrier websites, and the plan documents those sites serve.
The methods doc and Appendix B below are the 2027 bootstrap's, which git history keeps.

`python3 -I pipeline/run.py 2027 <work_dir>` lists plan documents from `found.csv` and `links.csv`, downloads them and the sources named in `config.json`, and regenerates `generated/`.
It then reads facts into `machine/document_facts.csv` from the answers saved in `answers/`, and presents them in `generated/presented.csv`.

## Layers

The site shows the generated sheets with these layers applied in order. Each layer row sets and cites the value of a cell, or of one line of it.

| File | Rows from |
|---|---|
| `generated/presented.csv` | `pipeline/present.py`: column rules applied to facts |
| `edits.csv` | People, and Claude sessions they steer |

A later layer wins, and within `edits.csv` a later row wins. The site drops a citation whose value is not the live cell's.

An edit row also records `saw`, the value its author saw. The site build warns when the cell beneath an edit is no longer `saw`, and when an edit cites an unknown document.

## Results

| Step | Result |
|---|---|
| Plan universe | The Landscape file gives the same 39 plans as the methods doc, after dropping 2 D-SNPs and 4 I-SNPs. |
| Premium and Extra Help premium | All 39 premiums match the section 4 table. Extra Help premiums match wherever section 4 lists one. |
| Plan documents | All 73 SBs and EOCs were found. 71 were byte-identical to the bootstrap's manifest. |
| Main chart | 10 of the 13 Appendix B items are reproduced. |
| DVHA sheet | 3 of the 7 significant DVHA findings are reproduced. |

`pipeline/tests/test_appendix_b.py` checks the live sheets against each Appendix B correction.

### Finding documents

Web search did not index any 2027 plan document. The documents were found as follows.
`found.csv` records the browser finds. `links.csv` transcribes the Links sheet from methods doc Appendix A. The documents themselves told which UHC links were SBs.

| Carriers | How |
|---|---|
| UHC/AARP (7 plans), Devoted (7), Aetna (2) | `pipeline/find_by_plan_page.py` renders each plan's page in headless Chromium. These pages label each link SB or EOC. UHC pages also list Platinum Dental rider PDFs. |
| Wellcare (5), ATRIO (2), AgeRight (1) | `pipeline/find_on_carrier_pages.py` reads each carrier's plan-materials page, rendered in headless Chromium. |
| Humana (8), Kaiser (3) | The URL templates in `pipeline/find_docs.py`. The Links sheet has the same URLs, so `documents.csv` credits it. |
| Regence (4) | `pipeline/find_regence.py` reads each SB link from the plan details pages on regence1.destinationrx.com. No page links the EOCs, so it swaps `summary-` for `eoc-` and checks the cover. |

Two UHC EOCs were re-issued on 2026-10-14 (`UHOR27HP0418842_001`, `AAOR27LP0418704_001`). Their dollar and percent amounts did not change.

### Sheets

`pipeline/present.py` writes both sheets, `generated/main_chart.csv` and `generated/dvha.csv`, from the column rules.
`pipeline/fields.py` gives each column's rules.

- The PBP has no naturopathy category. Column U is a dot when the facts include an `extras.naturopathy` benefit.
- UHC OR-1A charges $0 to members with QMB or full Medicaid. The sheet shows what other members pay.
- Six Humana plans cover acupuncture only for chronic low back pain, which Medicare covers. Column S is blank for them.
- Devoted 009 pays for acupuncture, massage and naturopathy only from its Wellness Bucks. A SHIBA expert counts that as a dot.

Main chart Appendix B items that the live sheet reproduces: 1 (all four cells), 2, 3, 4, 5, 6, 7, 11, 12, 13.
These items are not reproduced:

- Item 8 (Devoted CHOICE 002 X-ray) is a disagreement between the SB and the EOC.
- Item 9 is a typo in the volunteers' sheet.
- Item 10 (Wellcare EKG): the facts take a $200 price for tests that is not a diagnostic test. A note on the cell says so.

DVHA items that the live sheet reproduces: 2 (Kaiser Standard $100/2-year eyewear), 3 ($25,000 worldwide cap on all 7 Devoted rows) and 6 (Regence routine podiatry).
Item 1 (Wellcare comprehensive dental covers adjunctive services only) is not reproduced, but caveat notes give it.
Item 7 (Humana MyOption $1,500 max) is not reproduced: the facts give no yearly maximum for the package.
Items 4 (Devoted rewards) and 5 (Regence virtual urgent care out of network) are not reproduced either.

## Limits

- The PBP is bid data, not a citable document. Only the cells that a layer cites carry SB/EOC page citations.
- `pipeline/cms_sources.py` lists the CMS fields behind columns D, K, M, N and O in `generated/cms_sources.csv`. The site shows them for a cell no layer cites or changes.
- `run.py` does not run the model steps (issue #46). A model step publishes a citation only if the EOC value matches the cell, the quote highlights once on its page, and two models both confirm it.
- DVHA cells leave out vendor names, frequency limits and rewards. ATRIO's shared allowance shows only as the services it covers.
- The dot rules in `pipeline/fields.py` follow the methods doc's inferred policy R10 to R13, not rules from the SHIBA team.
- No person has reviewed these outputs.
