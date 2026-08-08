# Phase 3a Verification — Learner Research Readiness

**Status:** GREEN.
**Scope:** Read-only Learner research-readiness page over the existing verified
causal dataset foundation.

## Contract

Phase 3a does not implement a learner engine. No learner artifact, learning run,
model metric, feature-importance output, paper activation, or execution control
exists in the current API contract, so the page fails closed and renders those
states as unavailable.

Only existing verified overview facts are reused:

- symbols;
- primary/context intervals;
- causal context policy;
- bundle hash;
- registry hash.

Visible safety states:

```text
PAPER-SAFE
READ-ONLY
EXECUTION AUTHORITY: OFF
DATA FOUNDATION VERIFIED
LEARNER ARTIFACT: UNAVAILABLE
LEARNING RUN: UNAVAILABLE
PAPER ACTIVATION: OFF
```

No Creator qualification evidence is copied or inferred into Learner.

## TDD

Added `frontend/src/lib/learner.test.ts`.

RED was confirmed before implementation:

```text
Cannot find module './learner'
```

After implementation:

```text
learner.test.ts: 3 passed
navigation.test.ts: 2 passed
```

Covered behavior:

1. verified foundation facts are copied and symbols are deterministic/sorted;
2. learner artifact and learning run remain `unavailable`;
3. paper activation and execution authority remain `false`;
4. missing/unverified foundation produces no learner facts or hashes;
5. `#/learner` and `#learner` route correctly;
6. unsupported `#/signals` still falls back to Overview.

## Implementation

Changed/added:

- `frontend/src/lib/learner.ts`
  - pure `buildLearnerModel(...)` boundary;
  - fail-closed readiness state;
  - no filesystem, network, model, or training access.
- `frontend/src/components/learner-page.tsx`
  - readiness summary;
  - verified causal foundation facts;
  - explicit unavailable learner states;
  - safety boundary text.
- `frontend/src/lib/navigation.ts`
  - added `learner` route.
- `frontend/src/lib/navigation.test.ts`
  - updated unsupported-route assertion.
- `frontend/src/App.tsx`
  - Learner navigation and page rendering;
  - correct Overview/Creator/Learner active-state handling;
  - Phase 3A sidebar label.
- `frontend/src/App.css`
  - OLED readiness cards;
  - responsive foundation grid;
  - unavailable-state presentation;
  - mobile stacking.
- `frontend/design-system/pages/learner-readiness.md`
  - page-specific design/safety override.

## Browser HTTP smoke

A temporary same-origin HTTP fixture served the production bundle and only
verified health/bundle/component responses. Creator qualification and learner
artifacts were not supplied, proving the Learner page does not fabricate them.
The fixture/server were removed after verification.

Final observed state:

```text
Route: /#/learner rendered
Active navigation: Learner only
Foundation: DATA FOUNDATION VERIFIED
Learner artifact: UNAVAILABLE
Learning run: UNAVAILABLE
Paper activation: OFF
Execution authority: OFF
Controls: Refresh verified data only
Browser console errors: 0
```

The first visual pass identified a real navigation issue where Overview and
Learner were both active. The active-state predicate was corrected to use the
explicit `page === 'overview'` check, then the production bundle was rebuilt
and reloaded on a fresh HTTP port. Final visual review confirmed readable cards,
explicit unavailable states, no fake metrics, and no training/live/promotion/order
controls.

## Gates

```text
Backend pytest: 172 passed in 6.51s
Frontend Vitest: 30 passed
Frontend lint: 0 warnings, 0 errors
Frontend production build: passed
uv lock --check: passed
Python compileall: passed
git diff --check: passed
Changed-file credential scan: 0 findings
Learner control-token scan: none
```

No backend files, candidate registry, qualification artifact, promotion state,
paper state, execution authority, or exchange data was changed.
