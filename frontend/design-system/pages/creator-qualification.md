# Creator Qualification Evidence — Page Override

## Scope

Add a read-only evidence section below the existing candidate registry on the
Creator page. It consumes only `/api/v1/creator/qualifications`.

## Data contract

```text
verified response -> evidence summaries and missing IDs
404 -> unavailable / no persisted evidence
503 -> integrity error / no evidence rendered
```

The UI must preserve `promotion_state="unpromoted"` and
`execution_authority=false` in every verified card.

## Layout

- Header: `Persisted qualification evidence` plus verified/unavailable/error chip.
- Facts: candidates, persisted evidence, missing evidence.
- Cards: candidate ID, `EVIDENCE PASSED` or `EVIDENCE REJECTED`, source, evaluator,
  windows, policy, evaluated MYT timestamp.
- Boundary note: `Evidence only. No promotion, paper activation, or execution authority.`

No detail fetch, mutation, selection, or action button in this slice.
