"""The sheet columns: what each means, how the site labels it, and how to find it in an EOC.
Also what carriers' EOCs tend to do.

The generators, the model prompts and the site all read this spec.
A rule's source, when known, is in parentheses: "#31 section n" is issue #31, and
"methods Rn" or "methods 6.5" is docs/2027-bootstrap/CLAUDE_ANALYSIS_METHODS.md.
"""
import collections

Column = collections.namedtuple("Column", "sheet key label meaning find", defaults=((),))

DOT = ("A dot means the plan covers the routine (supplemental) benefit, not only a Medicare-covered one (methods R10). "
       "A shared allowance or card that names the benefit counts (methods R11). "
       "◐ means only a general wellness fund pays for it (methods R12). "
       "A benefit only in an optional package gets the Opt Packages dot instead (methods R13). "
       "A benefit only for some members, such as SSBCI, gets no dot unless the plan also covers it for all members.")

COLUMNS = [
    Column("main", "C_premium", "Premium",
           "Monthly plan premium (not counting the Part B premium).",
           [r"monthly plan premium", r"plan premium"]),
    Column("main", "D_premium_full_extra_help", "Premium w/ Full Extra Help",
           "Premium with full Extra Help, from the CMS Landscape file. \"n/a\" for plans without Part D."),
    Column("main", "E_moop", "MOOP In/Out of Network",
           "Maximum out-of-pocket (MOOP). Line 1 = in-network MOOP. Line 2 (PPO only) = combined in- and out-of-network MOOP.",
           [r"maximum out.of.pocket", r"\bMOOP\b"]),
    Column("main", "F_primary_care", "Primary Care",
           "Primary care physician office visit copay. Line 1 in-network, line 2 out-of-network. A range covers several visit types.",
           [r"primary care", r"physician/practitioner services", r"PCP"]),
    Column("main", "G_specialist", "Specialist",
           "Specialist office visit copay. Line 1 in-network, line 2 out-of-network. "
           "Office visits only: leave out hearing exams, telehealth and nursing-home visits (#31 section 2.2).",
           [r"specialist"]),
    Column("main", "H_inpatient", "Inpatient Hospital $/Day",
           "Inpatient hospital (acute) cost. \"$395 | 1-5\" = $395 per day for days 1-5, then $0. \"per stay\" = per admission.",
           [r"inpatient hospital care", r"per day", r"days? \d+.\d+"]),
    Column("main", "I_outpatient_surgery", "Outpatient Surgery / ASC",
           "Line 1 = outpatient hospital surgery; line 2 = ambulatory surgical center (ASC). \"a/b\" inside a line = in/out-of-network. "
           "Give the surgery amount in each setting. Leave out colonoscopy, biopsies, wound care and other services "
           "billed in the same setting (#31 sections 1.3 and 2.1).",
           [r"ambulatory surgical", r"outpatient hospital", r"outpatient surgery"]),
    Column("main", "J_outpatient_rehab", "Outpatient Rehab OT, PT, ST",
           "Outpatient rehabilitation (occupational, physical, speech therapy) visit copay or range. "
           "Leave out re-evaluations (#31 section 2.3).",
           [r"outpatient rehabilitation", r"physical therapy", r"occupational therapy", r"speech"]),
    Column("main", "K_tests_labs", "Diagnostic Tests / Labs",
           "\"tests/labs\", e.g. \"$35/$0\". Tests = non-radiological diagnostic tests (EKG, sleep studies, stress tests). "
           "Labs = outpatient lab services. Leave out X-rays, imaging and genetic testing (#31 section 2.4).",
           [r"diagnostic (tests|procedures)", r"lab(oratory)? services", r"\blab\b"]),
    Column("main", "L_xray_imaging", "X-Ray / Diag Radiology",
           "Line 1 = X-rays. Line 2 = advanced imaging: CT, MRI and PET scans only (methods 6.5). "
           "Leave out mammograms, ultrasounds and other tests.",
           [r"x-ray", r"radiolog", r"\bMRI\b", r"\bCT\b", r"\bPET\b"]),
    Column("main", "M_part_b_drugs", "Chemo / Part B Drugs",
           "Medicare Part B prescription drugs (incl. chemotherapy) coinsurance range. "
           "A 0% low end needs a Part B drug that costs nothing, such as allergy shots (#31 section 1.7).",
           [r"part b (prescription )?drugs", r"chemotherapy"]),
    Column("main", "N_pharmacy_deductible", "Pharmacy Deductible",
           "Part D drug deductible. \"$685 not tiers 1,2\" = deductible that does not apply to tiers 1 and 2.",
           [r"deductible stage", r"part d deductible", r"drug deductible", r"tier"]),
    Column("main", "O_medical_deductible", "Medical Deductible",
           "Medical (Part A/B services) deductible. \"$750 some\" = applies to some services only (methods R4). "
           "\"$100 out-of-network only\" = applies only out of network. \"$0\" = no medical deductible.",
           [r"medical deductible", r"\bdeductible\b"]),
    Column("main", "P_vision", "Vision",
           f"Dot (●) if the plan covers routine vision: eye exam and/or eyewear. Blank if not. {DOT}",
           [r"routine eye exam", r"eyewear", r"eyeglasses", r"contact lenses"]),
    Column("main", "Q_hearing", "Hearing",
           f"Dot if the plan covers routine hearing exams and/or hearing aids. {DOT}",
           [r"hearing aid", r"routine hearing"]),
    Column("main", "R_dental", "Dental",
           f"Dot if the plan covers preventive and/or comprehensive dental. {DOT}",
           [r"dental", r"cleaning"]),
    Column("main", "S_acupuncture", "Acupuncture",
           f"Dot if acupuncture beyond the Medicare chronic-low-back-pain benefit is covered. {DOT}",
           [r"acupuncture"]),
    Column("main", "T_chiropractic", "Chiropractic",
           f"Dot if chiropractic care beyond Medicare manual manipulation of the spine is covered. {DOT}",
           [r"chiropract"]),
    Column("main", "U_naturopath", "Naturopath",
           f"Dot if naturopathic services are covered. {DOT}",
           [r"naturopath"]),
    Column("main", "V_massage", "Massage",
           f"Dot if massage therapy is covered. {DOT}",
           [r"massage"]),
    Column("main", "W_fitness", "Fitness",
           f"Dot if a fitness benefit (gym membership / program) is covered. {DOT}",
           [r"fitness", r"silversneakers", r"renew active", r"gym"]),
    Column("main", "X_transportation", "Transportation",
           f"Dot if non-emergency transportation is covered. {DOT}",
           [r"transportation", r"rides?\b", r"one-way trips?"]),
    Column("main", "Y_otc", "OTC",
           f"Dot if an over-the-counter (OTC) items allowance is covered. Rewards programs are not OTC (methods R12). {DOT}",
           [r"over.the.counter", r"\bOTC\b"]),
    Column("main", "Z_part_b_reduction", "Pt B Reduction",
           "The monthly amount the plan pays toward the Part B premium (Part B giveback), or a dot if no amount is given.",
           [r"part b premium reduction", r"reduc\w+ (in )?your (monthly )?part b premium", r"giveback"]),
    Column("main", "AA_opt_packages", "Opt Packages",
           "Dot if optional supplemental benefit packages can be bought for an extra monthly premium (methods R13).",
           [r"optional supplemental", r"additional premium", r"rider"]),
    Column("dvha", "C_premium", "Monthly Premium",
           "Monthly plan premium (not counting the Part B premium)."),
    Column("dvha", "D_premium_full_extra_help", "Premium w/ Full Extra Help",
           "Premium with full Extra Help, from the CMS Landscape file. \"n/a\" for plans without Part D."),
    Column("dvha", "E_optional_packages", "Optional Packages",
           "Optional supplemental packages bought for an extra monthly premium. Format: `Dental Plus $40/mo, max $2,000`. Empty if none.",
           [r"optional supplemental", r"additional premium", r"rider"]),
    Column("dvha", "F_dental", "Included Dental",
           "Dental included in the base premium. Format: `PREV $0; COMP 40%; max $2,500/year PREV+COMP`. "
           "Say when comprehensive covers only some service types, e.g. `COMP $0 (extractions only)` (methods R6). "
           "An allowance with no set copays is written as the allowance (#31 section 1.9). "
           "Write `no annual max` only if the EOC says there is none, and `annual max not stated` if it names one without an amount "
           "(#31 section 1.5). Empty if no included dental.",
           [r"preventive dental", r"comprehensive dental", r"dental", r"annual (benefit )?max"]),
    Column("dvha", "G_vision", "Vision",
           "Routine (supplemental) vision. Format: `exam $0/year; eyewear $200/two years`. "
           "When a higher amount needs a certain provider, give the standard amount first, e.g. `eyewear $50/year ($100 at PLUS providers)` "
           "(#31 section 1.1). Say `frames or contacts` when one allowance covers either (#31 section 1.2).",
           [r"routine eye exam", r"eyewear", r"eyeglasses"]),
    Column("dvha", "H_hearing", "Hearing",
           "Routine (supplemental) hearing. Format: `exam $0; aids $499-$999; 2 aids/year` (copay per aid) "
           "or `exam $0; aids allowance $800 per ear/year; 2 aids/year`.",
           [r"hearing aid", r"routine hearing"]),
    Column("dvha", "I_alt_care_otc_travel", "Alternative Care / OTC / Travel",
           "Routine alternative care, OTC and worldwide emergency. "
           "Format: `Acup $10 24 visits/year; Chiro $20; Naturopath; Massage; OTC $50/three months; Worldwide ER $110, $50,000 max`. "
           "Give the OTC allowance amount (#31 section 4). Leave out any item the plan lacks.",
           [r"acupuncture", r"chiropract", r"over.the.counter", r"\bOTC\b", r"worldwide", r"outside the united states"]),
    Column("dvha", "J_extra_benefits", "Extra Benefits",
           "Other supplemental benefits, as a list. "
           "Format: `Fitness; Meals; Routine foot care $30 4/year; SSBCI benefits for qualifying chronic conditions; For qualifying members: <name>`. "
           "Say in plain words who qualifies, not \"UF/VBID\" (#31 section 3). "
           "SSBCI and targeted benefits go here, or in column I when the OTC allowance pays for them.",
           [r"fitness", r"meals?\b", r"foot care", r"special supplemental benefits for the chronically ill", r"SSBCI", r"value.based"]),
]

# Habits seen in 2027 EOCs, by the organization named in plans.csv
CARRIERS = {
    "UnitedHealthcare": "Tables print in-network and out-of-network costs side by side, so one text line can mix both. "
                        "The text drops some f's, as in \"or services rom a specialist\". "
                        "Some plans give a cost as \"$0 copayment or 20% coinsurance\", depending on the member's Medicaid level.",
    "Humana": "A benefit row lists each setting's cost on its own line, as in \"$450 copayment – Outpatient Hospital\".",
    "Devoted Health": "Surgery center rows give a facility copay and a $0 professional copay; the facility copay is the center's cost. "
                      "The Dental & Alternative Therapy Allowance names dental, acupuncture, massage and naturopathy, "
                      "so it counts toward each of their dots (methods R11). Wellness Bucks is a general wellness fund (methods R12).",
    "Wellcare": "Outpatient hospital rows give $0 for skin biopsies and one copay for all other services.",
    "ATRIO Health Plans": "One Flex Card allowance names acupuncture, chiropractic and naturopathy, "
                          "so it counts toward each of their dots (methods R11).",
    "AgeRight Advantage": "The Healthy Living Allowance pays for OTC items and fitness, so it counts toward both dots (methods R11).",
    "Kaiser Permanente": "Dental comes only in the Advantage Plus package, so it earns the Opt Packages dot, not the Dental dot "
                         "(methods R13).",
    "Regence BlueCross BlueShield of Oregon": "FlexDollars is a rewards program, not an OTC allowance (methods R12).",
}

# {"sheet.key": (meaning, regexes that find passages about it)} for the columns an EOC can show
FIELDS = {f"{c.sheet}.{c.key}": (c.meaning, c.find) for c in COLUMNS if c.find}


def labels(sheet):
    return {c.key: c.label for c in COLUMNS if c.sheet == sheet}
