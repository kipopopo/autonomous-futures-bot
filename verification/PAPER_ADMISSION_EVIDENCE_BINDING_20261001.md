# Evidence-bound paper admission checkpoint — 2026-10-01

## Scope and status

**Offline safety checkpoint; NOT PRODUCTION READY.** This records local verification before publication. A full-suite pass for the publication SHA is not claimed here; the exact-head GitHub Actions quality gate remains required. Nothing in this checkpoint authorizes deployment, a restart, provider spending, signed exchange requests, testnet/live activation, or orders.

## Changes

- Hash-only admission now produces a blocked decision. Admission requires a typed qualification artifact bound to the actual candidate ID, candidate content, market-data bundle, dataset registry, and expected qualification hash.
- Startup, discovery and hot reload use one persisted qualification resolver, including the research cycle's sibling hash-addressed qualification directory. A candidate JSON file is not treated as its own qualification.
- New registry publication uses schema version 2, matching authoritative startup's qualification requirements. Existing historical registry files are not rewritten or adjudicated.
- Registry candidates, qualifications and decisions are validated before publishing runtime state. Invalid later entries preserve the previous registry, candidates, qualifications, symbols, account state and trade-owned strategies.
- Removed implicit activation of historical Phase252 pinned candidates. Without an explicitly supplied candidate mapping or a validated registry, startup remains idle. Explicit Python candidate mappings remain an injection seam; this change does not claim that they independently prove persisted evaluator authority.
- Migrated successful admission fixtures to a shared synthetic persisted qualification helper. Their evaluator/policy identifiers are explicitly fixture-only. They test consumers, not OOS market performance or promotion authority.
- Added teardown for the churn test's global tracemalloc state, including assertion-failure paths.

## Observed local verification

- RED regressions reproduced missing qualification, invalid qualification binding, inconsistent registry publication/startup layout, partial registry mutation, and implicit historical startup activation before the fixes.
- Eleven focused modules: **158 passed, 0 failed, 0 skipped**, JUnit time **72.338 seconds**. This run preceded the final test-only tracemalloc teardown addition; that modified memory-churn test was separately rerun and passed.
- Final-tree Ruff, formatting, Windows and Linux mypy, dependency lock, AST compilation and `git diff --check`: passed. Mypy checked 355 source files on each platform; AST parsing covered 699 Python files.
- The earlier diagnostic full run was stopped after fixture failures. It is not a full-suite pass.
- One combined run used a generated Windows path of 266 characters and failed while creating an artifact. The same regression passed using a short basename inside Hermes scratch. Use short scratch basetemps; do not change artifact identifiers or production history to shorten paths.
- A combined run also exposed fixed-duration daemon frame-count sensitivity under concurrent local checks. The standalone case and the sequential focused suite passed with the original duration and frame assertions unchanged. No Hawkes, daemon-duration or other performance threshold was relaxed.

## Unresolved project gates

The authoritative complete Creator history is still unavailable, with unresolved DOGE/ETH identifier collisions and prose-only accepted proposals. Real Creator calls remain fail-closed. Qualification hashes and these synthetic fixtures cannot adjudicate history or grant evaluator authority.

The scheduler's complete Learner/Planner integration and a genuine execution-to-learning lifecycle still require runtime proof. Existing research cycle-to-registry-to-daemon source routing is not that proof. Legal/venue/account/capital approval, secret-manager readiness, kill-switch and current reconciliation gates remain outside this offline checkpoint.
