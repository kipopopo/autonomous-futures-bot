# Learner Research Readiness — Page Override

## Purpose

Add the next read-only research-plane page after the Creator qualification
surface. This page reports whether the verified causal data foundation is ready
for a future learner artifact; it does not implement learning, model training,
metric calculation, or execution.

## Information architecture

1. Existing global safety rail remains above the page.
2. The page heading is `Learner research readiness`.
3. The verified foundation identity is shown only when the existing overview
   verification contract passes.
4. Learner artifact, learning run, model metrics, feature importance, and paper
   activation remain explicit `UNAVAILABLE` states because no verified learner
   API/artifact is connected.
5. No Creator qualification data is copied or inferred into Learner.
6. Verified persisted learner artifact and prepared-run evidence are shown only
   when their dedicated read-only endpoints pass integrity and binding checks.

## Visible states

Verified foundation:

```text
DATA FOUNDATION VERIFIED
Learner artifact: UNAVAILABLE
Learning run: UNAVAILABLE
Paper activation: OFF
Execution authority: OFF
```

Unavailable foundation:

```text
UNAVAILABLE — no verified learner foundation connected
```

Never use `0` for a missing learner artifact, run, metric, or model count.

## Phase 3g evidence surfaces

When `/api/v1/learner/artifact` is verified, show a compact evidence card with:

- learner ID, version, and model family;
- model artifact SHA-256;
- learner artifact SHA-256;
- training window;
- `testing` / `unpromoted` safety state.

When `/api/v1/learner/run` is verified, show a separate provenance card with:

- run ID and run hash;
- `prepared` status;
- input window count and symbols;
- training window;
- explicit `output_artifact_hash: null` and `training_metrics: null` semantics.

If either endpoint returns 404, render `UNAVAILABLE`. If it returns an integrity
failure, render `INTEGRITY UNAVAILABLE`; do not collapse that into a successful
empty state. Never show model bytes, fake progress, metrics, loss, accuracy,
feature importance, promotion, paper activation, or execution controls.

## Facts

When the foundation is verified, show only persisted bundle facts already
available from the existing read-only overview contract:

- symbols;
- primary/context intervals;
- causal context policy;
- bundle hash;
- registry hash.

Do not add hardcoded training progress, loss, accuracy, model version,
feature importance, candidate count, or performance values.

## Safety and accessibility

- Preserve `PAPER-SAFE`, `READ-ONLY`, and `EXECUTION AUTHORITY: OFF` in the
  global rail.
- Use semantic headings and labelled readiness sections.
- Use visible text in addition to color for every state.
- Keep focus rings and 44px refresh/navigation targets.
- No Start learning, Train, Promote, Activate, Live, or Order control.
- Keep the existing OLED fintech design system and responsive card layout.
