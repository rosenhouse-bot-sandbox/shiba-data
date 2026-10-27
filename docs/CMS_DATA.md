# CMS data for the MA sheets

CMS has no query API for plan benefits, and Medicare Plan Finder has no official public API.
CMS does publish two bulk files each contract year that cover most of both sheets.
We checked the 2027 files against the 2027 sheets on 2026-10-26.

These files are not citable the way an SB or EOC page is.
Use them for automated cross-checks and to seed extraction.
Treat a disagreement between CMS data and the SB/EOC as a finding.

## MA Landscape file

- Index: https://www.cms.gov/medicare/coverage/prescription-drug-coverage
- 2027: https://www.cms.gov/files/zip/cy2027-landscape-202610.zip (CSV and XLSB, dated 2026-10-20)

The file has one row per plan per county.

| Sheet column | Landscape column(s) |
|---|---|
| C Premium | Monthly Consolidated Premium (Part C + D); Part C Premium for plans without Part D |
| D Premium w/ Full Extra Help | Part C Premium **+** Part D Low Income Beneficiary Premium Amount |
| E MOOP, line 1 | In-Network Maximum Out-of-Pocket (MOOP) Amount |
| N Pharmacy Deductible | Annual Part D Deductible Amount; Offers Drug Tier with No Part D Deductible |

Column C matches the sheet for all 39 plans.
The column D formula matches every sheet value we compared, e.g. Wellcare Premium Ultra $159.40 + $40.30 = $199.70.
The SB and EOC do not state column D.

The file also gives SNP type, C-SNP qualifying conditions and star ratings.
For all 39 plans, premium, MOOP and Part D deductible are the same in Multnomah and Clackamas.

## PBP Benefits file

- Index: https://www.cms.gov/data-research/statistics-trends-and-reports/medicare-advantagepart-d-contract-and-enrollment-data/benefits-data
- 2027: https://www.cms.gov/files/zip/pbp-benefits-2027.zip (dated 2026-10-01)
- 2027 JSON: https://www.cms.gov/files/zip/pbp-benefits-json-2027-zip.zip-0 (dated 2026-10-13, not inspected)

This is the approved bid data that plans file with CMS, updated quarterly.
Files are tab-delimited with a header row.
Join them on `pbp_a_hnumber`, `pbp_a_plan_identifier`, `segment_id`.
Many fields are codes; `PBP_Benefits_2027_dictionary.xlsx` decodes them.
Some fields are free text, e.g. "Plan covers up to two basic cleanings per year."

### Plan universe

`PlanArea.txt` lists each plan's counties.
Filter to Multnomah and Clackamas, OR, then drop employer plans (plan IDs 800 and up), D-SNPs, I-SNPs and PACE.
The result is exactly the 39 plans on the 2027 sheets.
Filtering on `eghp_flag` does not remove the employer plans.

The dropped types are offered in these counties: 2 D-SNPs, 4 I-SNPs and 2 PACE plans.
Leaving them off is a team choice.

CMS gives Devoted Giveback 028 as H2923-028-3, matching its documents. The sheet shows H2923-028-0.

### Where each sheet column lives

Rows marked ✓ were checked against the sheet. The rest come from the data dictionary only.

| Sheet column | PBP file | Category or field |
|---|---|---|
| C Premium (Part C only) | `pbp_Section_D` | `pbp_d_mplusc_premium` |
| E MOOP | `pbp_Section_D` | `pbp_d_out_pocket_amt`, `pbp_d_comb_max_enr_amt` ✓ |
| O Medical Deductible | `pbp_Section_D` | `pbp_d_ann_deduct_amt` ✓ |
| Z Pt B Reduction | `pbp_Section_D` | `pbp_d_mco_pay_reduct_amt` |
| AA Opt Packages, DVHA E | `pbp_Section_D_opt` | optional supplemental packages |
| F Primary Care, G Specialist | `pbp_b7_health_prof` | 7a, 7d |
| J Outpatient Rehab | `pbp_b7_health_prof` | 7c OT, 7i PT and speech |
| T Chiropractic | `pbp_b7_health_prof` | 7b |
| H Inpatient | `pbp_b1a_inpat_hosp` | 1a |
| I Outpatient surgery / ASC | `pbp_b9_outpat_hosp` | 9a, 9b |
| K Tests / Labs, L X-Ray / Imaging | `pbp_b8_clin_diag_ther` | 8a, 8b |
| M Part B Drugs | `pbp_b15_partb_rx_drugs` | 15 |
| X Transportation | `pbp_b10_amb_trans` | 10b |
| S Acupuncture | `pbp_b13_other_services` | 13a |
| Y OTC | `pbp_b13_other_services` | 13b |
| W Fitness, V Massage | `pbp_b14_preventive` | 14c4, 14c18 |
| Worldwide emergency (DVHA I) | `pbp_b4_emerg_urgent` | 4c |
| R Dental, DVHA F | `pbp_b16_dental` | 16b preventive, 16c comprehensive |
| P Vision, DVHA G | `pbp_b17_eye_exams_wear` | 17a, 17b |
| Q Hearing, DVHA H | `pbp_b18_hearing_exams_aids` | 18a, 18b, 18c |
| N Pharmacy Deductible | `pbp_mrx`, `pbp_mrx_tier` | Part D |

Naturopathy (column U) has no category of its own.
Vendor and network names such as "Delta Dental" or "SilverSneakers" are probably absent.
