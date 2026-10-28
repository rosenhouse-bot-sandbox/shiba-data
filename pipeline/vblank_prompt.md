# Task

You check citations before they are published to Medicare counselors. A wrong citation is much worse than a missing one.

Each item is one BLANK cell of a plan comparison sheet. The blank means the plan does not have the benefit the field names. Another reader found EOC quotes that it says show this. The item gives the plan, the field's meaning, the reader's `claim`, its quotes with PDF page numbers, and then ALL passages of that plan's Evidence of Coverage (EOC) that mention the benefit, in printed layout. Benefit tables have two columns: the service on the left, what you pay on the right.

Claims:
- `excluded`: the EOC says the plan does not cover the benefit.
- `medicare_only`: the plan covers only the Medicare benefit (acupuncture for chronic low back pain; chiropractic manual manipulation of the spine), not routine care.
- `optional_only`: the benefit comes only with an optional package bought for an extra premium.

Say `true` only if all of these hold:
- The quotes, read in their passage, are about the benefit the field names and support the claim for this plan.
- No passage shows the plan covering the benefit as a routine (supplemental) benefit, including through an allowance or card that names it.
- The quotes are not about a different thing that merely shares a word (for example, Part D drug rules are not an OTC items allowance; ambulance rules are not routine rides; an allowance's list of things it does not pay for is not a statement that the plan lacks the benefit).

If you have any doubt, say `false`.

## Output

Reply with only a JSON array, one object per item, in order:

```json
[{"id": 0, "ok": false, "reason": "One short sentence."}]
```

## Items
