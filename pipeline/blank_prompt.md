# Task

Do not use any mcp__ tools and do not message anyone. Work only with the files and commands below, then write your answer file.

You help Medicare counselors check a plan comparison sheet against the plan's Evidence of Coverage (EOC). A wrong citation is much worse than a missing one.
Plan: **{PLAN_NAME}** ({PLAN_ID}), plan year {YEAR}.

Each field below is BLANK on the sheet, which claims the plan does not have that benefit. Below each field are all EOC passages that mention it, in printed layout. Benefit tables have two columns: the service on the left, what you pay on the right. `=====PAGE n=====` marks the PDF page n.

For each field, read all of its passages and choose one result:

- `covered`: the plan itself covers the benefit, as the field defines it, in the base premium. The blank is wrong.
- `excluded`: a passage states the plan does not cover it, e.g. a line in a "not covered" or exclusions table, or "this plan does not offer ...". Nothing else shows coverage.
- `medicare_only`: only for acupuncture and chiropractic. The plan covers only the Medicare benefit (acupuncture for chronic low back pain; chiropractic manual manipulation of the spine), and nothing else shows routine coverage.
- `optional_only`: the benefit comes only with an optional package bought for an extra premium. Not for the optional-package fields themselves.
- `not_mentioned`: the passages are about something else (e.g. "rides" in an unrelated sentence).
- `unclear`: anything else, or you are unsure.

For `covered`, `excluded`, `medicare_only` and `optional_only`, give 1 to 3 quotes that show it. A quote is text copied exactly from one passage: one table row, one sentence, or one column of a table read straight down, joined with single spaces. Never mix words from two columns. Keep the EOC's spelling.

Check every quote before you answer:
`{CHECK} <page> '<quote>' ['<quote>' ...]`
It prints OK only when the PDF viewer can highlight the quote at exactly one place on that page. Use only quotes that print OK. If a quote fails, try a shorter part of the same line or row.

## Output

Write a JSON array to `{ANSWER}` with the Write tool, one object per field, in order:

```json
[{"key": "main.T_chiropractic", "result": "medicare_only", "citations": [{"page": 61, "quote": "Manual manipulation of the spine to correct subluxation"}], "reason": "Only Medicare spinal manipulation is listed."}]
```

`reason` is one short sentence. Then reply with one line: how many fields got each result.

## Fields
