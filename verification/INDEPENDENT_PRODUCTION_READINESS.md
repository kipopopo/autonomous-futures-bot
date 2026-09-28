# Independent production-readiness audit

## Scope and baseline

Audit of the Antigravity handoff, authorized by the user to inspect execution, learning, runners, canonical tests/CI, read-only deployment and repair proven offline defects. One separately approved anonymous public testnet `GET /fapi/v1/exchangeInfo` was performed; no provider request, private account request, exchange order, restart/resume, activation or deployment occurred.

Baseline source: `3408be60b1f084daa6875508856094fbcfc38754`; local main, origin/main and deployed VPS HEAD independently read back equal. Remote untracked release/data/evidence files exist and were preserved. Source identity does not prove the imported code of an already-running process.

## Readiness matrix (audit in progress)

| Requirement | Evidence | Status |
|---|---|---|
| Exact baseline SHA cloud quality | GitHub API run 35840946477 completed/success, matching baseline SHA | VERIFIED |
| Baseline local static checks | Ruff passed, 615 files formatted, mypy 273 source files passed, uv lock check passed | VERIFIED |
| Frontend | 27 test files / 163 tests passed; tsc + Vite build passed; large-chunk warning remains | VERIFIED |
| Full local backend regression | Baseline run stopped intentionally after source changed; no full-local pass claimed. Final exact-SHA cloud regression required | PENDING |
| Deployed web service | loaded/active/running, PID 463952, NRestarts=0; production artifact GET returned 200 | VERIFIED process/HTTP only |
| Paper/scheduler/Telegram processes | loaded/active/running; paper PID 529971 NRestarts=3, scheduler PID 9694 NRestarts=42, Telegram PID 11720 NRestarts=0 | VERIFIED process only; scheduler restart burst diagnosed as lock collision |
| Current account, ledger and strategy health | Not established by service state or HTTP response | UNVERIFIED |
| Phase 309 exchange execution | `self_driving.py:301-302` directly calls `_simulate_fill`; runner supplies hardcoded ticks | BLOCKED: simulation, not live execution |
| Hard child notional cap | Both Phase 307/309 now reject incompatible minimum/cap orders; Phase 309 explicitly rounds down; historical artifacts preserved | OFFLINE FIX VERIFIED |
| Phase 306 real feedback learning | Empty/below-minimum history now PROBATIONARY without fabricated positive metrics; simulator remains disconnected from real feedback/runtime | PARTIAL FIX; INTEGRATION BLOCKED |
| Phase 306 shadow promotion/performance | Offline runner has no synthetic promotion; hardcoded Sharpe/win-rate/Calmar/drawdown fields removed from artifact, API schema and frontend type | OFFLINE FIX VERIFIED; real performance qualification still unavailable |
| Runtime readiness API | `api/app.py:1144-1161` loads artifacts; no live account/runtime readiness assertion | Artifact integrity only |
| Phase 309 public status label | Endpoint/UI now call this a simulation artifact and state it does not prove exchange/live readiness | OFFLINE FIX VERIFIED |
| Phase 306 public status label | API forces SIMULATION_ARTIFACT_VERIFIED even for historical artifacts claiming EVOLUTION_VERIFIED | OFFLINE FIX VERIFIED |
| Frontend missing-artifact state | Null canary payload now renders UNAVAILABLE without demo orders, positions or Merkle claims | OFFLINE FIX VERIFIED |
| Phase 306 frontend missing-artifact state | Null payload now renders UNAVAILABLE with no candidate IDs, verified badge or paper-safe claim | OFFLINE FIX VERIFIED |
| Solvency artifact completeness | Loader requires all Phase 306 solvency fields and recomputes equity/drift from serialized Decimal inputs | OFFLINE FIX VERIFIED; semantic source provenance remains unproven |
| Phase 306 summary hash binding | API recomputes phase hash from performance, solvency, safety flags, candidate IDs and all traces; autopsy trace cross-checks SQLite and JSONL | OFFLINE FIX VERIFIED |
| Phase 306 safety flags | Loader rejects any non-paper-safe flag combination, including execution authority enabled, even with recomputed hashes | OFFLINE FIX VERIFIED |
| Testnet public exchange-info adapter | Injected transport and typed response; one user-approved anonymous smoke returned 741 symbols, 679 PERPETUAL | PUBLIC READ-ONLY VERIFIED; no account/order authority |
| Testnet account reconciliation contract | Offline parser/reconciler rejects duplicate expected or exchange position keys as drift | OFFLINE CONTRACT VERIFIED; no private account request authorized or performed |
| Signed read-only request handling | API-key headers and replayable signed queries excluded from request repr/serialization; testnet and production read-only transports reject redirects | OFFLINE SAFETY FIX VERIFIED; no account request performed |
| Live certification | No fresh authorized account/protection/reconciliation/first-live evidence established | BLOCKED |

## Independently inspected findings

1. `scripts/run_phase_309_production_launch.py:121-219` explicitly runs a simulation. Prices, signals and timestamp are constants; accepted fills are local simulation. Its hash chain verifies those artifacts, not exchange execution.
2. `src/autonomous_futures/production/self_driving.py:241-257` can step up quantity beyond the hard notional cap. `_round_step_size` at lines 403-411 omits explicit ROUND_DOWN. The runner and tests weaken the advertised cap to 5.75.
3. `src/autonomous_futures/feed/testnet_bridge.py:354-370` explicitly permits `max_micro_cap_usdt + price * step`. If min-notional and hard cap cannot both be satisfied, the correct outcome is rejection—not cap relaxation.
4. `src/autonomous_futures/feed/auto_evolution.py:308-319` classifies empty input as HEALTHY with fabricated positive metrics. This cannot be interpreted as observed strategy performance.
5. Phase 309 verifier defaults missing drift to zero (`run_phase_309_production_launch.py:95-98`, `run_phase_309_autonomous_launch.py:67-70`). Hash consistency is not semantic evidence completeness.

## Secondary audit leads requiring integration review

Independent read-only reviewers traced Phase 307 dispatch to synthetic fills and no network transport; Phase 309 has no bridge injection. Phase 307 ignores failed margin allocation. Phase 306 uses hardcoded scenarios, simulated shadow performance and summary metrics; no production caller connects its mutations to existing qualification/admission. Existing autonomous research contracts and Creator/OOS cycles are distinct from these demo modules. These findings guide fixes; reviewer test claims do not substitute for parent canonical verification.

## Runtime interpretation

Scheduler Result=success, ExecMainStatus=0, active since 2026-09-21 15:27:56 UTC. Its cumulative NRestarts=42 is not proof of a current restart loop; cause remains unverified. Paper service active since 2026-09-26 06:07:37 UTC. Web active since 2026-09-23 08:34:08 UTC. No services were changed. Neither process activity nor a simulator-backed API establishes live trading, real learning, economic qualification or account reconciliation.

## Completion boundary

## Integrated offline repairs

- Phase 307 rejects minimum-notional step-ups above the configured hard cap; report cap verification no longer permits 6 USDT.
- Phase 307 rejects failed margin allocation before simulated matching; regression asserts no fill, no ledger mutation and no user-data event.
- Phase 309 removes quantity step-up and explicitly uses ROUND_DOWN. Nonrepresentable minimum-notional/cap combinations are rejected.
- Valid simulation fixtures now use representable prices; these are synthetic test inputs, NOT market evidence. Same-price close scenarios do not prove profitability. Existing hashed artifacts were not regenerated.
- Parent reran combined Phase 307/309 canonical suite: **78 passed in 2.36s**, one existing Starlette/httpx deprecation warning. Ruff, format (615 files), mypy (273 source files), uv lock and diff checks passed.
- Parent corrected an aggregate-exposure test to assert the actual aggregate rejection event instead of passing on an earlier minimum-notional rejection.
- Phase 306 health evaluation now uses `min_sample_size`; empty history reports zero observed counts/metrics and PROBATIONARY, while any non-empty sample below the configured threshold is also PROBATIONARY and cannot trigger mutation. Parent observed the two new regressions fail before implementation; focused Phase 306 tests: **17 passed in 1.76s**, one existing warning; Ruff, format, targeted mypy passed.
- Phase 309 runner and test edits were performed in parallel with a background full-suite run. That run was stopped after reaching 49%; it is not final-tree evidence and no full local pass is claimed.
- A later frozen-tree full locked pytest run completed: **4,803 passed, 1 failed in 972.06s**. The sole failure was `tests/unit/test_phase_297_stress_fault_injection.py::TestOnlineStressEvaluationEngine::test_sub_millisecond_latency_compliance`, one observed call at 1,378.40 us vs 1,000 us threshold. The same exact targeted test passed 5/5 consecutive reruns. This remains a measured latency gate miss with a timing-sensitive test; do not report full pytest as green, do not relax the threshold, and do not infer CI/local equality.
- Phase 309 artifact loader now requires all serialized solvency/equity fields; absent drift can no longer default to zero and appear integrity-valid. RED confirmed the fixture (including a recomputed matching Merkle root) was previously accepted. Phase 309 API suite: **13 passed**, one existing warning; Ruff, format and targeted mypy passed.
- Loader now independently derives total equity and double-entry drift from the serialized cash, margin, unrealized P&L, starting equity, and realized P&L using `Decimal`, rejecting mismatches even if the declared drift is zero and hashes match. Regression was RED before the check; API suite now **13 passed** (combined Phase 306–309 suite **77 passed**). Final static checks rerun below before release.
- Phase 309 read API and dashboard no longer surface simulator evidence as `PRODUCTION_LAUNCH_VERIFIED`; response/UI now use `SIMULATION_ARTIFACT_VERIFIED` and explicitly say deterministic fills do not prove exchange connectivity, live execution, or production readiness. Backend endpoint suite **13 passed**, frontend component tests **2 passed**, TypeScript/Vite production build passed (large bundle warning persists).
- Frontend null-artifact handling now returns empty allocations/orders/candidates, false verification flags and blank hashes; the page stops at an accessible `UNAVAILABLE` state rather than rendering fabricated dashboard values. The new regression failed before the fix; frontend component suite **2 passed** and TypeScript/Vite build passed (large bundle warning persists).
- Phase 306 offline runner no longer fabricates successful shadow ticks/Sharpe to promote mutations; shadow ticks are zero and each candidate remains unpromoted pending independent observations. Hardcoded Sharpe/win-rate/Calmar/drawdown fields were removed from the generated artifact, API response model and frontend type instead of being replaced with misleading zeroes. Backend Phase 306 unit/API tests **17 passed**, frontend component tests **5 passed**, Ruff/format/mypy and TS/Vite build passed (bundle warning remains).
- Phase 306 artifacts/UI are now labeled `SIMULATION_ARTIFACT_VERIFIED`; the API overrides legacy `EVOLUTION_VERIFIED` artifact labels instead of trusting them. UI copy states hash integrity does not establish real learning, qualified performance or production readiness.
- Phase 306 frontend null-data model now returns `UNAVAILABLE`, `verified=false`, no candidate IDs or upstream hash, and the page renders only an accessible unavailable state. Regression failed before change; frontend tests **5 passed**, TypeScript/Vite build passed (large bundle warning remains).
- Phase 306 API now recomputes `phase_hash` from the actual phase/upstream/performance/solvency fields before checking the Merkle root; a regression mutating performance while retaining the old declared hash failed before the fix. Phase 306 API suite **10 passed**.
- Phase 306 loader now rejects missing solvency fields even when the phase hash and Merkle root are recomputed to match the incomplete payload; Decimal checks also reconcile declared equity and drift to their components. The regression failed before the fix; combined Phase 306 suite **19 passed**, Ruff/format/mypy passed.
- Phase 306 phase hash now commits safety flags, candidate IDs, autopsy/health/mutation/shadow traces as well as performance and solvency; the API recomputes the same commitment. A changed autopsy P&L with unchanged phase hash is rejected. Combined Phase 306 unit/API suite **20 passed**, Ruff/format/mypy passed.
- Phase 306 API now cross-checks every serialized autopsy record against both the SQLite table and JSONL events, rejecting mismatches even after source-artifact and Merkle hashes are recomputed. SQLite and JSONL tamper regressions pass; combined Phase 306 suite **22 passed**, Ruff/format/mypy passed.
- Phase 306 API now requires exact `phase_306`, `verified=true`, `paper_safe=true`, and `execution_authority=false`; a fully rehashed authority-enabled artifact is rejected. Combined Phase 306 suite **23 passed**, Ruff/format/mypy passed.
- Testnet public transport disables automatic redirects so the approved one-GET scope cannot silently follow to another host. Offline adapter/security regressions plus Stage A suite: **12 passed**; Ruff, format, mypy and diff checks passed. Separately approved anonymous `GET /fapi/v1/exchangeInfo` returned HTTP-successful typed metadata: 741 symbols, 679 PERPETUAL (sample BTCUSDT, ETHUSDT, BCHUSDT, XRPUSDT, EOSUSDT). No private account endpoint, credentials, order, or retry was used.
- Offline account reconciliation now rejects duplicate `(symbol, positionSide)` keys in either expected or exchange rows instead of silently collapsing them through a dict; RED regression reproduced false `reconciled` before fix. Private contract tests: **6 passed**; Ruff/format/mypy passed. No credential or network use.
- Testnet and production read-only request models no longer expose API-key headers or replayable signed queries through repr/model serialization. Both account reconcilers reject duplicate expected/exchange position keys, and the production read-only transport now blocks automatic redirects; regressions were RED before fixes. Combined private/live read-only contract tests: **11 passed**; Ruff/format/mypy passed. No credential or network use.

Fresh scheduler process readback: entrypoint `scripts/run_autonomous_scheduler.py`, **provider=demo**. Health readback: updated_at `2026-09-28T03:05:29.986157+00:00`, status IDLE, last_run_at `2026-09-22T16:33:08.933450+00:00`, total_cycles_executed=7, consecutive_failures=0, admitted_candidates_count=0. This is not provider-backed learning or qualified live trading evidence.

Read-only scheduler restart diagnosis: journal shows exit `4/NOPERMISSION`; filtering its logged JSON returned `lock_acquisition_failed` with active PID `826` for the repeated restart burst (restart counter observed through 42). Current process PID `9694` is alive and its lockfile PID also equals `9694`; prior PID `826` is no longer present. This supports a historical competing-instance lock collision, not an ongoing failure at observation time. No lock was removed and no service was restarted; prevention of duplicate unit/process launches remains an operational follow-up.

## Remaining implementation gaps (not approval-only blockers)

Real execution transport and reconciliation are absent from the audited Phase 307/309 paths. Phase 306 feedback/training/adoption integration is absent; historical simulator metrics remain unsuitable for production. Artifact loaders/verifiers still need strict missing-evidence rejection and honest simulation provenance. These require further bounded implementation and regressions; the safety fixes alone do not complete the product. Current VPS source remains the baseline; these repairs are not deployed.

## Release boundary

Safe local repairs may proceed with failing regressions first. Do not add an exchange transport just to satisfy a label. Preserve all historical hashed artifacts; do not regenerate them to manufacture passing evidence. Once repairs are integrated, run final-tree regressions and update this matrix. Real provider budgets, service changes, testnet/live and first-live lifecycle remain separate explicit gates. This report does NOT certify production readiness.
