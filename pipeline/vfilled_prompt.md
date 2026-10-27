# Task

Do not use any tools other than reading this file and writing your answer. Do not use any mcp__ tools and do not message anyone.

You check citations before they are published to Medicare counselors. A wrong citation is much worse than a missing one.
Plan: **{PLAN_NAME}** ({PLAN_ID}), plan year {YEAR}.

Each item is one cell of a plan comparison sheet: its field, what the field means, the cell's value, and quotes from the plan's Evidence of Coverage (EOC) with PDF page numbers. Judge each item on its own, even when several share a field.
The cited EOC pages follow the items in printed layout, each starting with `=====PAGE n=====`. Benefit tables have two columns: the service on the left, what you pay on the right.

For each item, decide whether a counselor who opens the cited page and reads the quote would see that the cell's value is correct for this plan.
Say `true` only if all of these hold:
- Each quote is about the service the field names, not a neighboring row, a different setting, or a different service.
- The amounts apply to this plan. Some EOCs list several plans side by side.
- The amounts are in-network unless the field says otherwise.
- Every number in the value is shown by the quotes, read in context. For a range, both ends belong to services the field covers.
- For a dot (● or ◐), the quote shows the plan covers that routine benefit. A Medicare-covered benefit, an exclusion, or a benefit that comes only with an optional paid package does not count. ◐ needs the benefit paid from a general allowance or wellness fund; ● needs it covered on its own.
- No part of the value contradicts the page.

If you have any doubt, say `false`.

## Output

Write a JSON array to `{ANSWER}`, one object per item, in order. Copy each item's `id`.

```json
[{"id": 0, "ok": true, "reason": "Page 74 specialist row: $40 copay."}]
```

## Items
