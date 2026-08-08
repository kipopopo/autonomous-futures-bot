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
