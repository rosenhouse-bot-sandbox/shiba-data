# Task

Do not use any tools other than reading this file and writing your answer. Do not use any mcp__ tools and do not message anyone.

You help Medicare counselors check a plan comparison sheet against the plan's Evidence of Coverage (EOC). A wrong citation is much worse than a missing one.
Plan: **{PLAN_NAME}** ({PLAN_ID}), plan year {YEAR}.

Each cell below gives the field's meaning, the cell's value on the sheet, and the EOC passages that mention the benefit and show one of the value's amounts, in printed layout. `=====PAGE n=====` marks PDF page n. Benefit tables have two columns: the service on the left, what you pay on the right. Some add a third column for out-of-network costs.

For each cell choose one result:

- `cite`: the passages show the cell's whole value for this plan.
  - Every dollar amount and percentage in the value must appear in a quote. "$0" needs a quote too.
  - A range often comes from several services in the same benefit, on different rows or pages. Quote each end where it appears. Both ends must be services the field covers. Do not use a service from another benefit, such as a mammogram for surgery.
  - Amounts must be in-network unless the field says out-of-network.
  - For a dot (● or ◐), quote text that names the benefit and shows the plan covers it as a routine (supplemental) benefit. Medicare-covered-only benefits, exclusions and optional paid packages do not count. ● is right when the plan covers the benefit itself, including from an allowance that names it. ◐ is right when only a general wellness fund pays.
  - For a medical deductible of "$0", a quote saying the plan has no deductible for medical services works.
- `skip`: anything else, including when the EOC disagrees with the cell or you are unsure.

A quote is text copied exactly from one passage: part of one table row, one sentence, or one table column read straight down and joined with single spaces. Never mix words from two columns. Keep the EOC's spelling, but leave out footnote marks such as ††.
Code checks that each quote occurs exactly once on its page. A short quote such as "$40 copay" often repeats, so add neighboring words from the same row or sentence, usually the service name.
Some cells show earlier quotes and why they failed that check. Fix them or skip the cell.

## Output

Write a JSON array to `{ANSWER}`, one object per cell, in order:

```json
[{"key": "main.I_outpatient_surgery", "result": "cite", "citations": [{"page": 86, "quote": "$0 copay for a colonoscopy"}, {"page": 86, "quote": "$835 copay for outpatient surgery"}]},
 {"key": "main.K_tests_labs", "result": "skip"}]
```

Then reply with one line: how many cells got each result.

## Cells
