# 2027 data from public sources

This folder holds the 2027 Multnomah/Clackamas MA sheets, built without the volunteers' PDFs or summary tables.
They come only from the CMS Landscape and PBP Benefits files, carrier websites, and the plan documents those sites serve.
The methods doc, `docs/2027-bootstrap/CLAUDE_ANALYSIS_METHODS.md`, and its Appendix B are the 2027 bootstrap's, which git history keeps.

`python3 -I pipeline/run.py 2027 <work_dir>` lists plan documents from `found.csv` and `links.csv`, downloads them and the sources named in `config.json`, and regenerates `generated/`.
It then reads facts into `machine/document_facts.csv` from the answers saved in `answers/`, and writes the sheets, `generated/main_chart.csv` and `generated/dvha.csv`, and their citations, `generated/presented.csv`.

## Results

| Step | Result |
|---|---|
| Plan universe | The Landscape file gives the same 39 plans as the methods doc, after dropping 2 D-SNPs and 4 I-SNPs. |
| Premium and Extra Help premium | All 39 premiums match the section 4 table. Extra Help premiums match wherever section 4 lists one. |
| Plan documents | All 73 SBs and EOCs were found. |

`pipeline/present.py` writes both sheets and their citations. Git keeps neither them nor the CMS tables, documents.csv and document_facts.csv, so run `python3 -I pipeline/tables.py 2027 <work_dir>` after a checkout. It needs openpyxl and node, and replays the saved answers in about 2 minutes. Each main build loads these tables into D1. `pipeline/fields.py` says what each column means.
`pipeline/tests/test_appendix_b.py` checks them against each Appendix B correction, and lists the ones they miss.

### Finding documents

Web search did not index any 2027 plan document. The documents were found as follows.
`found.csv` records the browser finds. `links.csv` transcribes the Links sheet from methods doc Appendix A.

| Carriers | How |
|---|---|
| UHC/AARP (7 plans), Devoted (7), Aetna (2) | `pipeline/find_by_plan_page.py` renders each plan's page in headless Chromium. These pages label each link SB or EOC. UHC pages also list Platinum Dental rider PDFs. |
| Wellcare (5), ATRIO (2), AgeRight (1) | `pipeline/find_on_carrier_pages.py` reads each carrier's plan-materials page, rendered in headless Chromium. |
| Humana (8), Kaiser (3) | The URL templates in `pipeline/find_docs.py`. The Links sheet has the same URLs, so `documents.csv` credits it. |
| Regence (4) | `pipeline/find_regence.py` reads each SB link from the plan details pages on regence1.destinationrx.com. No page links the EOCs, so it swaps `summary-` for `eoc-` and checks the cover. |

Two UHC EOCs were re-issued on 2026-10-14 (`UHOR27HP0418842_001`, `AAOR27LP0418704_001`). Their dollar and percent amounts did not change.

## Limits

- The PBP is bid data, not a citable document. A value that only CMS facts back has no citation.
- `pipeline/cms_sources.py` lists the CMS fields behind columns D, K, M, N and O in `generated/cms_sources.csv`. The site shows them for a cell with no citation.
- Rules marked `methods` in `pipeline/fields.py` follow the methods doc's inferred policy, not rules from the SHIBA team.
- Rules marked `expert` or `final chart` in `pipeline/fields.py` come from SHIBA's review.
