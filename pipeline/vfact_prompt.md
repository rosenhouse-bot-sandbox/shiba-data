# Task

You check benefit facts before they are published to Medicare counselors. A wrong fact is much worse than a missing one.
Each item states one fact from a plan's {KIND} for plan year {YEAR}, with quotes and their PDF page.

The document covers these plans:
{PLANS}
{NOTES}

The cited pages follow the items in printed layout, each starting with `=====PAGE n=====`. Benefit tables have the service on the left and what you pay on the right. Judge each item on its own.

Say `true` only if a counselor who reads the quotes on their page would agree with every field:
- The plan: some documents list several plans side by side.
- The benefit and setting: not a neighboring row, another setting, or another service.
- The network: in-network unless the item says otherwise.
- The cost kind and amount, each end of a range, and any condition, provider tier, package, unit and limit.

The fields use this vocabulary. Costs are in network unless the document says otherwise.

{VOCABULARY}

If you have any doubt, say `false`.

## Output

Reply with only a JSON array, one object per item, in order. Copy each item's `id`.

```json
[{"id": 0, "ok": true, "reason": "Page 61 X-ray row: $0 to $40 copay in network."}]
```

## Items
