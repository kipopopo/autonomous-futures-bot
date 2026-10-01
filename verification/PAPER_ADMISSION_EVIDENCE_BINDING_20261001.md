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

## Post-publication findings and uncommitted follow-up

- Published checkpoint `427cc0f1d07c4264de49da11f277039c044aa751`, exact-head Actions run `36817609423`: **FAILED — 8 failed, 4,838 passed, 1 skipped**, in 743.23 seconds. Failures included an obsolete v1 publication expectation, implicit pinned-candidate indicator fixtures and obsolete partial reloader mocks. This is not a canonical pass.
- The fixture migration preserves v2 publication and no implicit production activation. Indicator tests explicitly inject archived test candidates; reloader tests now use the actual engine and scoped, persisted fixture-only qualification, including an engine-owned trade. None of these fixtures adjudicates history or grants production evaluator authority.
- The scheduler now has an explicit, bounded offline research path using paired rejected-OOS candidate/qualification seeds, explicit dataset scope hashes and demo mode only. It invokes the existing base CLI for one cycle, does not forward paper-ledger feedback or admission routing, and fails closed on a missing, blocked or mismatched typed base receipt. The real Learner/Planner/cycle adapter ran inside an in-process test harness: **123 focused tests passed** before the later entry-guard change. Synthetic windows are selected only by that harness; this is not genuine-market or actual-OS positive runtime evidence, and the normal provider scheduler path is not thereby proven learner-integrated.
- An additional entry-boundary defect was reproduced: raw constructor candidate mappings and missing, rejected, foreign or replaced qualification/admission state could still create local simulated positions. **Six RED regressions** recorded that defect. The shared entry gate now requires current bound qualification and admission state and reuses the admission decider; raw mappings remain indicator/recovery inputs, not qualified entry permission.
- The six safety regressions plus two real-engine reload cases and the v2 CLI publication case: **9 passed**. Broader entry-consumer inventory: **148 tests, 44 failures**; legacy unqualified entry fixtures and a timing-sensitive daemon frame-count mismatch remain to be migrated/investigated without reducing thresholds or weakening gates. This is not a current full-suite pass.
- Latest whole-tree Ruff/format, Windows and Linux mypy, lock and diff checks passed after the entry-guard change. Follow-up remains uncommitted; publication and deployment are withheld pending consumer migration, independent review and full quality verification. No provider, exchange, account, order, deploy, restart, testnet or live action was performed.

## Unresolved project gates

### Current local follow-up verification

- Frozen-tree full suite before the final normal-scheduler receipt change: **4,861 passed, 0 failed, 0 skipped**, two warnings, 1,014.16 seconds. JUnit count was independently parsed. This verifies the entry/close guards and fixture migrations, not the later receipt edit.
- The normal scheduler's exit-0 fallback was then reproduced with **9 failing receipt cases** and three valid controls. It now requires a bound typed cycle result with valid content hash and nonfailed outcome; optional paired audits must have valid integrity/bindings and consistent selected lineage. Audit-only success is restricted to the producer's `skipped_no_breaches` path without admission. Missing/malformed/foreign/failed/conflicting receipts enter backoff instead of resetting failure state. Paired result/audit files are legitimate producer output, not duplicate execution.
- Final scheduler/receipt/base focus: **83 passed** in 58.41 seconds. Whole-tree Ruff/format (**701 files**), Windows/Linux mypy (**355 sources** each), lock and diff checks passed after the receipt change. Independent receipt review and final exact-head CI remain pending; the older 4,861-pass run is not claimed for the final tree.

- Independent final receipt source review reported **no blocking findings**. This was read-only, without tests or external operations; final exact-head Actions is still the required post-publication gate.

- The scheduler zero-cycle receipt finding was reproduced RED and fixed by requiring exactly one cycle. Scheduler/base loop regressions: **71 passed**; the positive path remains an in-process CLI/core harness, not OS-subprocess or genuine-market proof.
- Entry-consumer fixture migrations now explicitly persist test-only qualification and call the real `engine.admit_candidate`; no manual admission-map installation or production guard relaxation. Nine affected modules: **100 passed** in 74.92 seconds, including six invalid-authority regressions and persistence/recovery failure drills.
- A real protective-close regression surfaced after restart with no new-entry authority. Close request scope now comes from the existing trade symbol, not the current entry-qualified set. Recovery verifies closure succeeds while `qualified_symbols` stays empty; this does not authorize a new entry.
- The hot-reload integration module passed separately: **7 passed** in 12.97 seconds with the original daemon timing/frame assertions unchanged. The earlier combined timing failure is not erased by this standalone result; the fresh full suite must adjudicate it.
- Whole-tree Ruff/format (**700 files**), Windows and Linux mypy (**355 sources** each), lock and diff checks passed. Fresh full-suite result and independent review are pending; no new publication or production-readiness claim is made.

The authoritative complete Creator history is still unavailable, with unresolved DOGE/ETH identifier collisions and prose-only accepted proposals. Real Creator calls remain fail-closed. Qualification hashes and these synthetic fixtures cannot adjudicate history or grant evaluator authority.

The scheduler's complete Learner/Planner integration and a genuine execution-to-learning lifecycle still require runtime proof. Existing research cycle-to-registry-to-daemon source routing is not that proof. Legal/venue/account/capital approval, secret-manager readiness, kill-switch and current reconciliation gates remain outside this offline checkpoint.
