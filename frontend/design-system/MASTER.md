# Autonomous Futures Bot — Master UI System

## Product type

Finance / crypto research analytics dashboard. The interface is an observational
research plane, not a brokerage terminal.

## Visual direction

Dark OLED with restrained glass/flat panels. Use cyan for verified data identity,
green only for evidence that actually passed, amber for testing/unavailable, and
muted red for integrity/error states. Avoid neon gradients, gamification,
celebratory success language, and speculative charts.

## Tokens

The canonical implementation lives in `src/index.css` as HSL variables:

```text
background: 222 24% 7%
surface: 222 22% 10%
surface-raised: 222 20% 13%
border: 217 18% 24%
foreground: 210 25% 94%
text-secondary: 214 14% 70%
text-muted: 214 12% 52%
primary: 190 82% 55%
positive: 151 58% 48%
warning: 40 92% 62%
negative: 4 72% 62%
```

Typography is Inter for body/UI and JetBrains Mono for hashes, IDs, evaluator
versions, and machine-readable states.

## Information architecture

Creator page order:

1. Safety rail — PAPER-SAFE / READ-ONLY / EXECUTION AUTHORITY: OFF
2. Creator readiness — foundation facts only
3. Persisted candidate registry — testing candidates only
4. Qualification evidence — verified summaries or explicit unavailable/error
5. Footer — observational/read-only boundary and fetch time

## Qualification evidence component

Use a panel with a compact evidence summary grid and candidate evidence cards.
Each card shows candidate ID, decision, source, evaluator version, window count,
policy ID, and evaluated timestamp in MYT/GMT+8. `qualified` is labelled
`EVIDENCE PASSED`, never `PROMOTED` or `LIVE`.

The list endpoint is summary-only. Do not invent metrics or render missing
artifacts as zero. Use `—` for unavailable values and `0` only for verified
actual counts.

## States and copy

- Loading: `Verifying persisted qualification evidence`
- Verified: `QUALIFICATION EVIDENCE VERIFIED`
- Empty/missing: `UNAVAILABLE — no persisted qualification evidence`
- Error/tampered: `UNAVAILABLE — qualification evidence could not be verified`
- Safety copy: `Evidence only. No promotion, paper activation, or execution authority.`

## Interaction and accessibility

The page has no mutation controls. Candidate cards are not buttons unless a
verified detail interaction is implemented later. Keep heading order h1 → h2 →
h3, status text alongside color, visible 3px focus rings, minimum 44px controls,
responsive layouts at 320px/768px/1440px, and reduced-motion support.

## Avoid

- fake counts or hardcoded qualification results;
- `promoted`, `paper-live`, `profitable`, `ready to trade`, or `execute` labels;
- approve/reject buttons, generate buttons, order controls, leverage/margin fields;
- raw filesystem paths or exception traces in UI;
- rendering a tampered response as an empty success state.
