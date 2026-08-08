# Creator Qualification Evidence Matrix — Page Override

## Purpose

Add a deterministic read-only index over the verified qualification summaries
already returned by `GET /api/v1/creator/qualifications`.

This is a navigation and inspection surface, not a qualification engine. It
must never recompute metrics, infer gates, change candidate state, or expose
promotion/execution controls.

## Information architecture

1. Existing persisted evidence summary remains the entry point.
2. Evidence Matrix appears below the summary and above the global safety rail.
3. Detail remains on-demand through the existing `View full evidence` control.
4. Missing candidate IDs are shown as unavailable evidence, never as rejected.

## Controls

Controls are local view state only:

- outcome: `All`, `Qualified`, `Rejected`, `Missing`
- source: `All`, `Walk-forward OOS`, `Creator evaluator`
- sort: `Candidate`, `Outcome`, `Windows`, `Evaluated`

Use native labelled `select` elements or equivalent keyboard-complete controls.
No control may call a mutation endpoint.

## Matrix rows

Each verified row shows:

- candidate ID
- evidence outcome
- source
- evaluator version
- OOS windows
- policy ID
- evaluated timestamp in MYT
- promotion state (`unpromoted`)
- execution authority (`off`)

Missing IDs use an explicit `MISSING EVIDENCE` state and show no invented
metrics, windows, or evaluator values.

## Visual direction

- Keep the existing OLED fintech analytics system and HSL tokens.
- Use a quiet raised surface, thin borders, monospace IDs, and restrained
  semantic green/amber/red status text.
- Do not use neon gradients, gamification, ranking language, or profit-colored
  charts.
- Keep the matrix scannable at 320px: stack controls, turn rows into compact
  cards, and preserve candidate/status visibility.
- State must be communicated by text as well as color.

## Accessibility and safety

- Semantic `section`, heading, labelled controls, and table caption where a
  table is used.
- Every select has a visible label or `aria-label`.
- Focus rings remain visible.
- Counts use `0` only when the verified response actually contains zero; use
  `—` for unavailable values.
- Filtered empty state says the current verified response has no matching rows.
- The panel must visibly repeat `Evidence only`, `Promotion: unpromoted`, and
  `Execution authority: off`.
