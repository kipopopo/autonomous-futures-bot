# Creator Qualification Detail — Page Override

## Scope

Extend the existing Creator qualification evidence card with a read-only,
on-demand detail disclosure. The disclosure is a view action only: it may fetch
one persisted artifact, but it must not mutate candidate state or expose any
promotion/order controls.

## Information architecture

1. Summary card remains the first scan: candidate, decision, source, evaluator,
   windows, policy, evaluated time.
2. `View full evidence` is a secondary outline control with `aria-expanded` and
   no mutation semantics.
3. Expanded detail is grouped into three evidence blocks:
   - Metrics: exact persisted Decimal strings.
   - Gates: pass/fail, observed, threshold, comparator, reason code.
   - Binding and provenance: candidate/bundle/dataset hashes, evaluator run and
     version, source, policy, OOS aggregation hash, qualification hash.
4. Safety rail remains visible at the bottom: evidence-only,
   `unpromoted`, execution authority off.

## Detail state behavior

- Collapsed: no detail request is made.
- Loading: show a compact non-blocking status inside the card.
- Verified: render the full typed artifact without recalculation or rounding.
- Missing (`404`): show `DETAIL UNAVAILABLE`; do not show invented metrics.
- Integrity failure (`503`): show `DETAIL INTEGRITY UNAVAILABLE`; render no
  artifact values.
- Network/unknown failure: same fail-closed state as integrity failure.

## Visual delta

Reuse the current dark OLED evidence card. Detail content uses a slightly raised
surface, 1px subtle border, compact two-column fact grid, and monospace values.
Passed gates use green plus explicit `PASS`; failed gates use red plus explicit
`FAIL`; color is never the only status indicator.

## Accessibility

- Disclosure control is keyboard reachable with visible focus.
- `aria-expanded` reflects the detail state.
- Detail region has a stable labelled heading.
- Gate status includes text, not color alone.
- `—` means a persisted optional value is null; `0` remains an actual value.
- Layout collapses to one column below 740px.
