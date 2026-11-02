# Task

You help Medicare counselors compare plans. Read the pages below from a plan's {KIND} for plan year {YEAR}, and list every benefit fact they state about the benefits named below. A wrong fact is much worse than a missing one.

The document covers these plans:
{PLANS}
{NOTES}

A fact is one cost or coverage term for one plan: one benefit, setting, network and cost kind. When a row gives costs for several settings, networks or plans, state one fact for each. When one cost covers several services, use a broader benefit only if the document lists exactly the services it covers, as "CT, MRI and PET" is `imaging.diagnostic.advanced`. Otherwise state one fact for each service, with the same quotes. Leave out a cost whose setting is not in the list.
Costs are in network unless the document says otherwise. An HMO chart without network columns gives in-network costs.
Use `covered_by` `medicare` unless the document says the benefit is routine or supplemental.

{VOCABULARY}

`=====PAGE n=====` marks PDF page n. Pages are in printed layout. Benefit tables have the service on the left and what you pay on the right. Some add columns for out-of-network costs or for other plans.

A quote is text copied exactly from one page: part of one table row, one sentence, or one table column read straight down and joined with single spaces. Never mix words from two columns. Keep the document's spelling, but leave out footnote marks such as ††.
Code checks that each quote occurs exactly once on its page, and that the quotes show every number in the amount. A short quote such as "$40 copay" often repeats, so add neighboring words from the same row or sentence, usually the service name.
Some documents show earlier answers that failed a check. Fix them or leave them out.

## Output

Reply with only a JSON array, one object per fact:

```json
[{"plan_id": "H1036-306-0", "benefit": "imaging.diagnostic", "setting": "outpatient_hospital", "network": "in",
  "covered_by": "medicare", "cost_kind": "copay", "amount": "$0-$300", "unit": "per day", "limit": "", "page": 61,
  "quotes": ["Diagnostic radiology services (such as MRIs, CT scans) $0 - $300 copay"], "note": ""}]
```

`provider_tier`, `condition`, `package`, `pool`, `amount`, `unit`, `limit` and `note` may be left out. Give every field as text, except `page` and `quotes`. Use `note` only when you are unsure, and say why.
