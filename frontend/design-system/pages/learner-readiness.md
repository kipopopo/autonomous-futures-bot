# Learner Research Readiness — Page Override

## Purpose

Add the next read-only research-plane page after the Creator qualification
surface. This page reports verified learner evidence in plain language. It can
show that an explicit training caller recorded a completed output, but it does
not claim that the model is good, profitable, promoted, paper-active, or live.

## Information architecture

1. Existing global safety rail remains above the page.
2. The page heading is `Learner research readiness`.
3. The verified foundation identity is shown only when the existing overview
   verification contract passes.
4. Learner artifact, prepared run, completed-training proof, model metrics,
   feature importance, and paper activation each have separate explicit states.
5. No Creator qualification data is copied or inferred into Learner.
6. Verified persisted learner artifact and prepared-run evidence are shown only
   when their dedicated read-only endpoints pass integrity and binding checks.
7. Completed-training proof is shown only when the persisted evidence envelope
   and all linked run/artifact/model hashes pass verification.

## Visible states

Verified foundation:

```text
DATA FOUNDATION VERIFIED
Learner artifact: UNAVAILABLE
Learning run: UNAVAILABLE
Training completion proof: UNAVAILABLE
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

## Phase 3l completed-training proof

When `/api/v1/learner/training-evidence` is verified, show a plain-language
card titled `Training completion proof` with:

- `COMPLETED — provenance only` status;
- output learner version and model family;
- output artifact SHA-256 and evidence SHA-256;
- recorded completion time in MYT/GMT+8;
- a clear note: this proves that an explicit caller produced and persisted
  model bytes; it does not prove accuracy, profitability, qualification,
  promotion, paper activation, or live readiness.

If the endpoint returns 404, render `UNAVAILABLE`. If it returns an integrity
failure, render `INTEGRITY UNAVAILABLE`. Never replace either state with a
fake completion percentage, loss, accuracy, or activity count.

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

Do not add hardcoded training progress, loss, accuracy, feature importance,
candidate count, performance values, or training activity.

## Safety and accessibility

- Preserve `PAPER-SAFE`, `READ-ONLY`, and `EXECUTION AUTHORITY: OFF` in the
  global rail.
- Use semantic headings and labelled readiness sections.
- Use visible text in addition to color for every state.
- Keep focus rings and 44px refresh/navigation targets.
- No Start learning, Train, Promote, Activate, Live, or Order control.
- Keep the existing OLED fintech design system and responsive card layout.
