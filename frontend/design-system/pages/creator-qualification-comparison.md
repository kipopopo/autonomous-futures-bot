# Creator Qualification Cohort Comparison — Page Override

## Purpose

Add a small descriptive comparison panel for up to three persisted
qualification summary rows already present in the verified evidence matrix.

The panel is an inspection aid only. It must not rank candidates, name a
winner, infer profitability, recommend promotion, or alter any persisted state.

## Interaction contract

- Each matrix row has a labelled local checkbox: `Select <candidate> for cohort comparison`.
- At most three rows can be selected at once.
- Missing evidence can be selected so its unavailable fields remain explicit.
- Selecting/unselecting only changes React view state.
- The comparison must not fetch detail artifacts or create new API requests.
- No selection may trigger a backend mutation.

## Comparison content

For each selected row show side-by-side descriptive facts:

- candidate ID
- evidence outcome
- source
- evaluator version
- OOS windows
- policy ID
- evaluated timestamp in MYT
- qualification hash (short display with full value on hover)
- promotion state
- execution authority

Use the heading `Cohort comparison` and the notice:

```text
DESCRIPTIVE EVIDENCE ONLY — NO RANKING OR PROMOTION SIGNAL
```

Do not show aggregate scores, winner labels, arrows, badges such as `best`, or
charts that could imply an ordering decision.

## Visual direction

- Reuse the Evidence Matrix quiet raised surface and OLED fintech tokens.
- Comparison columns should be readable at desktop and stack into cards below
  720px.
- Use monospace identifiers and hash values.
- Keep missing fields as `—`; never convert missing evidence to zero.
- Use semantic status text in addition to color.

## Accessibility and safety

- Native checkbox input with visible label and keyboard focus ring.
- Disabled unchecked checkboxes communicate the three-row limit with an
  adjacent text note; do not hide the fourth candidate.
- `aria-live` may announce selection count, but must not claim qualification
  changes.
- Preserve visible `Evidence only`, `Promotion: unpromoted`, and
  `Execution authority: off` text in the comparison panel.
