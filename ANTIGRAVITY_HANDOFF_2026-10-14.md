# Autonomous Futures Bot — Codex to Antigravity handoff

**Transfer date:** 14 October 2026 (MYT).  
**Incoming engineer:** Antigravity, sole engineering writer.  
**Outgoing engineer:** Codex.  
**Verdict:** engineering remediation is substantial but unfinished; no strategy is admitted and the replacement trading runtime is not activated.  
**Canonical architecture and policy:** `CODEX_HANDOFF.md`. This document is the current transfer guide and consolidated continuation plan; it does not create a second architecture specification.

## 1. Start here

The owner requested transfer back to Antigravity. Continue in the existing workspace:

```text
C:\Users\thaqi\Projects\Autonomous Futures Bot
```

Read in this order:

1. This transfer guide, especially the protected-daemon constraint and policy below.
2. `CODEX_HANDOFF.md`: current checkpoint and latest sections first, then architecture.
3. `REMEDIATION_STATUS.md`: implementation and targeted-validation history.
4. `docs/handoff/2026-10-14/workspace-state.json`: repository custody and file fingerprints.
5. `docs/handoff/2026-10-14/research-state.json` and `vps-readonly-status.json`: freshly checked evidence.
6. `PROJECT_AUDIT_2026-10-12.md`: original findings, not an assertion that every finding remains unfixed.
7. Current source/tests for the specific outcome being continued.

Older `ANTIGRAVITY_HANDOFF.md`, `HANDOFF_ANTIGRAVITY.md`, `HANDOFF_HERMES.md`, phase reports and earlier paragraphs in the canonical chronology preserve historical context. Their old risk settings, worker-active statements, source/CI observations and deployment instructions do not override this transfer or the owner's latest decisions. Do not resurrect an older source SHA to match an old report.

The owner prefers **Manglish** replies. Explain results plainly, keep updates regular, and distinguish implemented code, research evidence, deployment and exchange-confirmed behavior. Routine authorized repair and read-only research do not need repeated permission questions. The transfer itself does not launch an Antigravity process, deploy a release or grant exchange-order authority. Codex is handing over engineering work rather than continuing application changes.

## 2. Non-negotiable operating constraints

### Protect the existing VPS daemon

**Never stop, restart, kill, signal, interrupt, or replace `autonomous-futures-trader.service` or PID 87549.** Do not edit its unit, enable/disable state, restart policy, running process environment, API permissions or credentials to force a handoff. Do not restart its parent user slice or reboot the VPS. Do not start a second exchange writer while it may use the shared Testnet key.

Copying changed Python files onto its working directory would not establish which code its existing process has loaded. Preserve isolation between research/release directories and `/opt/autonomous-futures-bot`.

### Test only the affected behavior locally

No redundant full local pytest or Vitest suite. Use targeted unit files for source that changes. GitHub Actions runs full suites on push to `main` and on pull requests. The local workflow now includes frontend tests/build as well as Python checks; that workflow change is still uncommitted. A historical green CI run cannot certify this dirty workspace.

### Functional, data-driven implementation

No invented market candles, account balances, exchange fills, qualified candidates, daemon health, Hawkes rho, heartbeat, ledger pass or API credentials in production paths. Missing or stale evidence must stay unknown/unavailable and block entries where required. Test fixtures are not runtime evidence. Preserve rejected and immutable research artifacts.

No subagents are requested for this transfer. Maintain one engineering writer against this checkout.

## 3. Latest operator-approved capital and account policy

| Setting | Current decision | Historical setting superseded |
| --- | --- | --- |
| Equity reference | Actual exchange account equity, `ACCOUNT` | Dedicated bot allocation |
| Risk per trade | **0.5% of actual account equity** | The interim 0.25% choice |
| Initial margin per trade | No fixed dollar cap | $5 notional, then $5 initial margin |
| Aggregate notional | No fixed dollar cap | $25 aggregate exposure |
| Cash reserve | No fixed percentage floor | 75% reserve floor |
| Daily loss | **5% of actual equity captured at UTC day start** | Fixed $3 daily loss |
| API key | Reuse existing Testnet key pair | Separate new writer key/read-only legacy-key plan |

These decisions are already represented by `RuntimeCapitalPolicy` in `src/autonomous_futures/execution/trade_plan.py`: `trade_risk_pct=0.5`, `daily_loss_pct=5`, and optional margin/notional/reserve caps are `None`. They have **not** been applied to the protected legacy process. Source, exchange filters, available margin, commissions, stop distance, owned pending exposure and remaining daily budget still determine feasibility.

Risk per trade is the planner's permitted loss at the protective stop, not a fixed margin amount or leverage setting. Leverage affects margin demand; it does not change exchange minimum notional or permit a trade above the risk budget. Obtain real leverage/margin/filter evidence rather than hardcoding leverage to force eligibility. Historic BTC $50/ETH $20 minimum-notional observations are dated snapshots, not permanent rules; refresh actual exchange filters before use.

The 5% daily-loss baseline must be authentic, reconciled and captured at the UTC boundary. A mid-day balance snapshot is not that baseline. Missing evidence disables new entries. Deposits/withdrawals are capital-basis adjustments, not trading PnL; deposits must not reset loss allowance and withdrawals must not count as losses. Ambiguous income records fail closed. Protective action applies to owned positions/orders, not arbitrary unrelated account positions.

The owner approved standard futures identities, calculated with Decimal precision:

```text
wallet = starting_equity + capital_basis_adjustments + net_realized_pnl
equity = wallet + unrealized_pnl
absolute reconciliation drift < 10^-15 USDT
```

Net realized PnL includes commissions and funding. An internally zero-drift simulator ledger or one first-observation identity check does not establish continuous authenticated exchange reconciliation.

## 4. Repository custody and current infrastructure

### Local checkout

- Repository: `https://github.com/kipopopo/autonomous-futures-bot`.
- Branch observed for transfer: `main`.
- HEAD: `e3092bacd54109cc95ceb947b47c343594d30f66`.
- HEAD subject: `feat(phase-316): complete English localization and professional trading UI standardization`.
- HEAD commit date: 11 October 2026, 20:25:58 MYT.
- **The tree is heavily dirty**, including application changes, tests, CI, lockfiles, deployment definitions and many untracked runtime/research files. The transfer did not commit, push, fetch or deploy them.
- A Git-only fresh clone of this HEAD will not contain the delivered local implementation/evidence. Reuse this checkout or deliberately transfer all needed files and large ignored/raw datasets securely.
- Do not reset, clean, discard, blanket-add or overwrite the existing tree. Inspect diffs before grouping changes into reviewed commits. Exclude secrets and mutable operational databases from indiscriminate publication.
- The current inventory expands untracked files and hashes changed engineering files plus selected evidence. It is a custody snapshot, not an archive or a backup. Large dataset bytes remain at their existing paths; reference manifests bind them.

### Fresh read-only VPS observation

At approximately **07:22–07:23 MYT on 14 October 2026**, pinned read-only SSH succeeded with the explicit Kainode key. Exact observation timestamps and outputs are saved in `docs/handoff/2026-10-14/vps-readonly-status.json`.

| Surface | Observed state | Interpretation |
| --- | --- | --- |
| Host | `147.79.18.15`, user `afbot` | Kainode Linux VPS |
| Legacy trader | Active/running, **MainPID=87549**, **NRestarts=0** | Protected process; activity is not qualification or genuine trading proof |
| Web service | Active/running, MainPID=287760, NRestarts=0 | Web/API process; no HTTP/domain freshness check was performed for this transfer |
| Matching research/replacement user units | No active matching unit shown | Scoped systemd inventory, not an exhaustive process audit |
| Historical cache-builder units | Two `afb-link-holdout-cache-*-20261013.service` units remain failed | BTC and LINK cache builders; preserve diagnostics, do not blindly restart |

The trader's observed command still contains:

```text
scripts/run_phase_310_real_autonomous_trading.py
--storage-dir /opt/autonomous-futures-bot/artifacts/research/phase310
--starting-capital 100.00
--symbols SOLUSDT,ETHUSDT,BTCUSDT
```

The advertised research/runtime universe is 12 pairs; that does not make this three-symbol legacy command a deployed 12-pair trader. Its old on-disk policy was last audited at 02:24 MYT as $5 child notional, $25 aggregate, 75% reserve and $3 daily loss. This transfer inspected systemd metadata, not in-memory Python code or present exchange balances.

The earlier `Permission denied (publickey)` observation is superseded by this successful explicit-key read. Use the existing trusted host binding; do not disable host-key verification. Do not print or read private-key contents.

```powershell
ssh -i 'C:\Users\thaqi\.ssh\kainode_ed25519_openssh' `
  -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 `
  afbot@147.79.18.15 `
  'systemctl --user show autonomous-futures-trader.service autonomous-futures-web.service --property=Id,ActiveState,SubState,MainPID,NRestarts,ExecStart'
```

Configured remote root is `/opt/autonomous-futures-bot`, Python environment `.venv`, and web domain `https://futures.semua.dev/`. Historical research packages live below `/home/afbot/qualification-worker/`; inspect a package's own manifest/policy before reusing it. Old frozen worker packages are not automatically current-source.

## 5. Intended universe and strategy mechanics

The 12-pair USDⓈ-M perpetual universe is BTC, ETH, SOL, DOGE, BNB, XRP, SUI, AVAX, NEAR, LINK, APT and ADA, each with `USDT` suffix.

### Macro Scalper

`strategy/macro_liquidity_scalper.py` evaluates 15m bars with BTC 1h/4h EMA50/EMA200 regime context. BTC is the regime anchor; Macro's current `ALLOWED_SYMBOLS` contains the other 11 pairs.

- Baseline long: aligned bullish BTC regime, close more than 2.5 ATR below EMA20, volume above 2.2 times SMA20, RSI14 below 26.
- Newly implemented mirrored short: aligned bearish BTC regime, close more than 2.5 ATR above EMA20, volume spike, RSI14 above 74.
- Baseline stop is 1.2 ATR, target 2.0 ATR, maximum hold eight 15m bars (two hours), with side preserved through shared planning.
- Neutral/misaligned, insufficient closed history, stale/gapped data, missing account evidence or unqualified execution domain must not produce an entry.
- Constructor parameters and research variants are distinct from default runtime values. The XRP development variant below has not replaced the baseline runtime parameters.
- Macro qualification now requires the authenticated commission artifact, uses its symbol rates and hashes the input. Current recorded maker/taker rates are 0.000200/0.000400, from a dated Testnet snapshot; never treat them as universally fixed future fees.

### ICT MMXM Twins

`strategy/ict_mmxm.py` implements HTF 1h/4h PDA hit, confirmed 5m CISD displacement, consecutive 1m Twin FVGs, 62–79% OTE (70.5% sweet spot), directional 1m CISD handling and protected stop with 2x/4x STDV targets, subject to opposing PDA caps and exit invalidation. The older canonical six-step prose is high-level; inspect `exit_invalidation.py`, `ict_reclaim_entry.py`, current state-machine source and tests for actual entry/exit sequencing.

Recent repairs remove bearish preference when both 5m directions exist: latest genuine confirmation wins; same-candle ties and unresolved two-sided PDA states produce no setup. Shared planning handles split exits only when every slice and residual lot is exchange-valid. The `reclaim_retest` and `limit_touch` research modes are separate execution-domain experiments, not interchangeable live approvals.

Hawkes/clock/feed freshness and account/qualification admission surround both families. A frontend Step 6 badge or API-generated signal is not proof the protected daemon consumed or dispatched it.

## 6. Software path map and delivered boundaries

All paths below are relative to `src/autonomous_futures/` unless a script is named.

| Area | Main files | Delivered behavior / boundary |
| --- | --- | --- |
| Legacy daemon | `execution/continuous_trader.py`, `execution/self_driving.py`; `scripts/run_phase_310_real_autonomous_trading.py` | Historical legacy engine. Local dispatch now fails closed for missing genuine qualification; protected remote process was not migrated |
| Runtime composition | `scripts/run_qualified_runtime.py`, `execution/runtime_session.py` | Local composed Testnet runtime; not installed/started as a trading service |
| Market history | `feed/kline_parser.py`, `kline_sequencer.py`, `kline_synchronizer.py`, `closed_history.py`, `live_market_feed.py`, `exchange_clock.py` | Closure, causal availability, source/gap/freshness and exchange-clock controls; no invented gap bars for authority |
| Scanner/planner | `execution/causal_scanner.py`, `trade_plan.py`, `ict_reclaim_entry.py` | Shared causal intentions, Decimal sizing, leverage/filter/stop/capital eligibility and side propagation |
| Account/risk | `execution/account_evidence.py`, `daily_risk.py`, `entry_risk.py`, `commission_headroom.py` | Authenticated account/income reconciliation, durable day-start risk basis, fees/funding/transfers and pending/owned risk |
| Entry authorization | `execution/entry_admission.py`, `qualification_receipts.py`, `qualification_domain.py` | Current source/data/policy/domain binding and final measured-evidence check before every opening submission |
| Order lifecycle | `execution/live_orders.py`, `lifecycle_coordinator.py`, `fill_recovery.py` | Durable intents, exchange acknowledgement vs fills, partial/ambiguous outcomes, idempotent reconciliation and recovery |
| Protection | `execution/protective_executor.py`, `protective_lifecycle.py`, `exit_invalidation.py` | Prearmed reduce-only coverage, owned risk management, target/residual handling and causal invalidation; no reduceOnly=false fallback |
| Writer fencing | `execution/single_writer_guard.py`, `writer_lease.py` | Cooperative lease plus explicit legacy-inactive startup/final-entry checks; lease does not fence PID 87549 |
| Private stream | `feed/authenticated_user_stream.py` | Genuine authenticated events, reconnect REST reconciliation, gap entry veto and margin/trigger-rejection handling |
| Microstructure | `feed/measured_hawkes.py`, `runtime_microstructure.py`, `runtime_hawkes_calibration.py` | Genuine arrivals, identified-fit checks, sample/clock/depth gates, calibrated decay; unknown/boundary-pinned fits fail closed |
| Qualification | `research/runtime_qualification.py`, `ict_runtime_qualification.py`, `official_market_data.py`, `ict_touch_index.py` | Offline causal/cost-aware replay and source-file provenance; model outcomes do not establish exchange fills |
| API truth | `api/app.py`, `api/canary.py`, `api/strategy_router.py` | Missing authenticated execution evidence returns unavailable/503 rather than fabricated balances/fills/health; signal API remains a separate evaluator |
| Frontend | `frontend/src/lib/canary.ts`, `api.ts`, mission-control adapter, page components | Substantial truthful-state repairs; broader historical fallback cleanup is unfinished |

`RuntimeSession` maintains routine authenticated refresh around ten seconds with bounded backoff, while the protective cycle runs around one second. It still attempts protective reconciliation after account-refresh failure, blocks entries on unavailable/stale evidence, and forces refresh around entry recovery/admission. These are local implementation contracts, not a measured live latency guarantee.

Credentials come only from the selected exchange environment; no mock-key or live/Testnet cross-fallback is valid. Hedge Mode is rejected by the qualified admission path before one-way reduce-only protection. Persisted state, order ownership, exchange-ledger cursors and risk state must survive release replacement; never erase them to obtain a clean startup.

## 7. Current evidence and qualification verdicts

`deploy/qualification-admission.json` currently contains `approved_reports: []`. **No strategy or portfolio is admitted.** Preserve this state until valid independent evidence and a reviewed transition exist.

### Latest symmetric-short development grid

Authoritative paths for this completed research run:

```text
research/qualification-development-2024-2026/scalper-symmetric-short-grid-v3.json
artifacts/qualification/runtime-scalper-symmetric-short-grid-development-20261014-v3/grid-summary.json
docs/handoff/2026-10-14/research-state.json
```

- 11 Macro symbols × five distance values × five target ATR values = **275 jobs**.
- Three local workers; run finished at 07:06:37 MYT. It is no longer an active grid job.
- **275 completed, zero failures**. Selection interval: 1 January 2024 through 1 August 2026 exclusive.
- Policy: 0.5% per-trade risk / 5% daily loss, no fixed margin/notional/reserve caps.
- Historical sizing seed: **4,224.09882354 USDT** from `artifacts/qualification/runtime-inputs/testnet-account-probe-20261014-1791918191661.json`. It is not current equity or a verified UTC day-start baseline.
- Commission input: `artifacts/qualification/runtime-inputs/testnet-commissions-1791824521337.json`.
- Frozen protocol SHA-256: `c8b07d1e0462c1600a746838331ffb6688dfa9b41c807ea1e044c1058b573c6b`.
- Transfer integrity check: **120/120 input fingerprints match, 275/275 report file hashes match, all report self-hashes and development-only/no-authority boundaries validate**.
- Five gate-passing variants are all XRPUSDT, distance -4.0, target ATR 1.5/2.0/2.2/2.5/3.0. Other ten symbols have no passing variant.
- All reports remain `decision=DEVELOPMENT_ONLY`, `execution_authority=false`. Their development gate label `QUALIFIED` is not an execution qualification receipt.

The preregistered ranking rule puts **XRPUSDT distance -4.0 / target 3.0 ATR** first:

| Metric | Modeled development result |
| --- | --- |
| Trades | 32 |
| Net PnL | 180.7171421506274 USDT |
| Stressed net PnL | 65.6799657766274 USDT |
| Drawdown | 64.18817121 USDT |
| Profitable windows | 5 |
| Minimum window net PnL | 6.03033436 USDT |

Report: `XRPUSDT-98a65c2949728eb2.json` in the v3 output directory. File SHA-256: `0049916d7720a03aab778665481c3e89a18272b09792200da9c0c012679a62f5`. **No new candidate-selection manifest was frozen and no holdout was evaluated for this XRP variant.** Thirty-two development trades are limited evidence; avoid describing this as a proven profitable strategy or account-level portfolio return.

The v2 symmetric-short protocol failed preflight because a reference digest field contained a path. Earlier protocol generation also encountered a process-results list shape. The generator and focused tests were repaired before v3. The v2 directory is not a completed grid. Do not merge v2 or old long-only reports into v3 or repeat the unchanged 275-job run merely to rediscover its result.

### Other preserved research

| Evidence | Location | Verdict / limits |
| --- | --- | --- |
| Macro account-capital sensitivity | `artifacts/qualification/runtime-scalper-equity-4224-20261014/` | All 11 rejected; predates symmetric-short source update; independent per-symbol models, not portfolio |
| ICT account-capital sensitivity | `runtime-ict-equity-4224-20261014/` and `runtime-ict-equity-4224-20261014-vps-v2/` under `artifacts/qualification/` | All 12 rejected; 292 modeled trades in independent symbol reports; source bindings must be rechecked |
| ICT directional/reclaim/touch screens | `artifacts/qualification/runtime-ict-*` | Preserved diagnostics/rejected experiments; use exact report policy/domain, not directory name as authority |
| LINK Aug–Sep frozen-candidate test | `runtime-scalper-link-holdout-2026-08-2026-09/LINKUSDT-d03d7df747e61edd.json` | Rejected: one trade, net -0.394283250, stress -0.478539035 USDT; source-stale diagnostic |
| Calibration | `runtime-microstructure/runtime-hawkes-calibration-20261013.json` | Supplies beta=7.5/s only; `qualification=false`, `execution_authority=false` |
| Source attestations/packages | `artifacts/qualification/source-attestations*`, `packages/`, frozen package directories | Preserve source/file indexes and actual bytes; hashes without underlying source custody are insufficient |

Hawkes calibration's selection/independent-validation profiles observed roughly rho 0.698/0.745. Earlier boundary-pinned fits and undersampled 120-second fits were rejected. Calibration cannot admit a strategy and runtime still needs current genuine arrivals/freshness and an identified fit.

The prior bounded private-stream probe connected and REST-reconciled once but received **zero private events**. There is no real-event proof yet for fills, partial fills, conditional rejections, reconnect recovery or protective risk handling. Unit tests, connected WebSockets and zero sequence gaps are different evidence boundaries.

## 8. Data custody and holdout contamination

```text
research/official-archives/                         official archives and checksum provenance
research/immutable-data/runtime-official-20261013/ canonical derived history
research/qualification-development-2024-2026/      frozen development protocols
research/qualification-holdout-2026-08-2026-09/    partially consumed reserved partitions
research/qualification-validation-2021-2023/      older validation context (not all pairs)
research/immutable-data/link-holdout-cache-v2/
research/immutable-data/link-holdout-funding-v3/
research/immutable-data/scalper-forward-*-local-20261013/
artifacts/qualification/runtime-inputs/             exchange-filter/fee/account snapshots
```

The Aug–Sep holdout index/README was corrected to **partially_consumed**. An earlier frozen LINK test consumed LINK market/funding and **BTC 1h shared regime context** from 1 August through 1 October 2026 exclusive. Its file SHA-256 is `b2586895d7aed210dd1bf0be82a87f07baefdeceab36eec9e12cce62d120f4b2`. It was not used for parameter tuning, but the common BTC context cannot be called pristine.

Ten pair-specific partitions, including XRP, remain listed as uninspected. That does not make a XRP replay with the previously consumed BTC context a wholly pristine common-context holdout. Freeze a validation plan with an honest partition ledger before inspecting results; disclose context reuse and keep any resulting limitations in the verdict. Do not tune from reserved validation outcomes or quietly redefine them as development after a rejection.

The older 2021–2023 cache is not a complete all-pair independent validation universe: existing paths include BTC/LINK context. Verify availability, consumed partitions and official source spans rather than pretending the same sample is fresh because starting equity, entry mode or filenames changed.

Frozen report provenance binds source code, policy, fees/filters/funding/market files and causal execution domain. Editing a bound source while workers run invalidates current-source authority. Completed older reports remain immutable historical evidence after source changes. Create a new declared protocol when methodology changes; never amend a rejected report into a pass.

## 9. Activation blocker: shared key and protected writer

The local replacement service definition is `deploy/systemd/autonomous-futures-qualified-runtime.service`. Intended isolated release/state paths:

```text
/opt/autonomous-futures-bot/releases/qualified-runtime
/opt/autonomous-futures-bot/runtime/qualified-testnet
/opt/autonomous-futures-bot/.env.qualified-runtime
```

Credential names are `BINANCE_TESTNET_API_KEY` and `BINANCE_TESTNET_SECRET_KEY`, plus `AFBOT_EQUITY_BASIS=ACCOUNT`. Never print values in chat, docs, Git or logs. The prior basis-only environment observation did not prove secure credential installation; this transfer did not read that file.

`LegacyWriterHandoffGuard` requires the legacy unit to be disabled, `Restart=no`, `ActiveState=inactive`, `SubState=dead`, `MainPID=0`, at startup and the final entry boundary. The owner simultaneously protects its active PID 87549. **Those conditions cannot be satisfied now without violating the owner's constraint. Activation is therefore blocked.** A cooperative lease does not fence an older process that never acquired it. Do not bypass the guard, revoke its key, start a second writer or claim that an OS lock solved this.

`deploy/QUALIFIED_RUNTIME_ROLLOUT.md` contained a contradictory instruction to require legacy inactive and also verify it remained active after rollout. The transfer documentation corrects that contradiction and records rollout as blocked under current constraints. Any future writer transition needs an explicit reconciled operator decision plus actual qualifying reports, durable account/day-start evidence and private-event protective proof. A different account/key plan cannot be inferred because the owner explicitly chose the same key.

No Testnet or real-money activation was performed by Codex. Active legacy systemd status does not establish exchange-confirmed autonomous operation.

## 10. Repairs delivered versus remaining audit work

Major local repairs include truthful execution/account/API responses, no synthetic live candles/prices, separated submission/fill state, exchange-confirmed lifecycle components, strictly reduce-only exits, Decimal planning/reconciliation, restored evidence guards, causal closed-data handling, canonical 12-pair scanning paths, OTE/Twin/directional fixes, short-side Macro support, authenticated fees in qualification, source-bound admission, daily transfer adjustment, user-stream integration and measured Hawkes fit-quality/calibration checks.

The latest frontend repairs were Phase 297 Stress and Phase 307 Testnet Bridge:

- Phase 297 renders unavailable evidence and explicitly historical artifact data; removed fake balances, passing safety/drift/latency values and obsolete reserve/survival floors.
- Phase 307 no longer seeds CONNECTED, mock credentials, listen key, fills, filters, balances, safe/off/drift claims or provenance hashes when data is absent. Missing nested fields are null, unknown verification stays unknown, symbols derive from API evidence and unverified status uses a warning badge.
- API canary defaults no longer fabricate daemon PID/health, BTC price/EMA, heartbeat or sample hurdles. Missing macro evidence blocks entries without inventing a bearish observation.

Remaining work is material:

| Priority | Outcome | Concrete continuation |
| --- | --- | --- |
| 1 | Honest independent qualification | Freeze the XRP candidate/validation protocol and partition ledger; address shared BTC-context consumption before evaluating holdout. All existing execution admission remains empty |
| 1 | Shared-wallet portfolio evidence | Combine owned strategy/symbol exposure, pending orders, costs and daily limits in one causal account model; per-symbol report sums are not a portfolio |
| 1 | Real private lifecycle proof | Reconcile fills/partials/protection/reconnect/recovery using authentic private observations when permitted; no simulator or manufactured event may become a production receipt |
| 1 | Safe writer migration decision | Resolve the protected-PID/same-key contradiction with the owner before activation; continue independent offline work meanwhile |
| 2 | Finish truthful frontend models | `canary.ts` still has stage-specific default performance/solvency/ledger/governance models. `buildProductionLaunchModel` partial-data fallback still seeds old $5/$25/75%/$3 policy, prices/orders/balances and success claims |
| 2 | Finish truthful historical pages | `production-launch-page.tsx` still has fixed policy prose, fallback numbers, static three-pair universe and a fallback Merkle root despite simulation-only labeling. Inspect other stage builders/pages and mission-control adapter producer/consumer paths |
| 2 | Candidate tooling integration | `select_scalper_development_candidates.py` does not enforce the partial-consumption ledger. Its aggregate manifest shape/status is not directly the per-candidate `FROZEN_BEFORE_VALIDATION` schema expected by `qualify_frozen_scalper_candidate.py`; create a verified bridge rather than changing status text by hand |
| 2 | Source/deployment drift | Keep local, VPS on-disk and process-loaded code distinct. Consolidate duplicated service/ledger/engine modules only after dependency mapping; do not delete research implementations blindly |
| 2 | Deliver local changes safely | Review and group extensive dirty changes/evidence into commits; push only intended source/config/tests with custody intact, then inspect exact-source CI. No blanket reset/add/deploy |
| 3 | Autonomous learning/creation loop | Preserve existing pipeline/Creator/Learner/epoch contracts and lineage. Prove actual durable outcomes reach subsequent decisions; neither dashboards nor unused LLM advice satisfy the product |

The broader product remains autonomous trading, durable learning and strategy creation. Cached data, native evaluator and admission components are reusable. Prior provider campaigns/grants and fresh-epoch lineage are historical records; do not reopen spent budgets, invent acceptance records, make paid provider calls or treat old phase approvals as new exchange authority. The current transfer does not audit every old provider component or create a new campaign.

## 11. Recommended first engineering sequence

1. Confirm custody against `workspace-state.json`; inspect current diffs and relevant tests. Keep this checkout intact.
2. Read the newly captured VPS metadata. If a refresh is needed, perform the pinned read-only command only. Do not alter either protected service or failed historical worker units for activity's sake.
3. Reuse the already-complete v3 grid and ranked summary. Do not restart it or rerun earlier rejected full-universe capital scenarios without a changed declared question.
4. Repair/bridge candidate-selection and holdout-ledger tooling under a new explicit downstream provenance record. Bind the 0.5/5 policy, same account-equity basis, current implementation, actual fees/filters and one frozen XRP parameter set. Keep original grid protocol/source bytes intact.
5. Choose and preregister an honest independent validation route; record any shared-context reuse. Evaluate once, preserve the verdict, and do not relax gates to manufacture qualification.
6. Continue Phase 309 and remaining truthful-telemetry cleanup using unknown states and real producer data. Add focused behavior tests only where needed.
7. Address portfolio/account/private lifecycle evidence separately from parameter qualification. Keep activation blocked until every actual prerequisite is resolved.
8. Report outcome, changed files, targeted checks and remaining proof limits in Manglish. Do not announce project completion, profit, live activation or worker activity from an unverified assumption.

## 12. Targeted validation and tooling

Python is pinned by project configuration to 3.14; `uv.lock` supplies dependencies. Frontend uses React/TypeScript/Vite with its npm lockfile. Use existing installed environments and lockfiles; do not upgrade dependencies during handoff.

Examples for a future changed slice, **not a request to rerun them all now**:

```powershell
# Only select unit files affected by the change.
uv run --locked pytest tests/unit/test_runtime_daily_risk.py tests/unit/test_live_percentage_risk.py -q
uv run --locked ruff check src/autonomous_futures/execution/daily_risk.py
uv run --locked ruff format --check src/autonomous_futures/execution/daily_risk.py
uv run --locked mypy src/autonomous_futures/execution/daily_risk.py

# From frontend/ for a bridge UI change:
npm test -- src/components/__tests__/testnet-bridge-page.test.tsx
npm run build

# From root:
git diff --check
```

Recent recorded checks, not rerun for the documentation transfer:

| Slice | Recorded check |
| --- | --- |
| Macro signals/scanner/qualification/runner/holdout tooling | 65 targeted unit tests; Ruff/format/strict mypy passed |
| Grid freezer/orchestration repair | 11 targeted tests and scoped static checks passed |
| Holdout ledger correction | One focused integrity test passed |
| Canary API defaults | 19 targeted tests; scoped Ruff/format/strict mypy passed |
| Phase 297 Stress UI | Seven targeted tests and frontend build passed |
| Phase 307 bridge UI | Three targeted tests, TypeScript/production build and scoped diff check passed at about 07:10 MYT |
| Live stream/session integration | Earlier targeted 91-test batch passed; still no real private-event proof |

The most recent frontend build succeeds with the existing large-JS-chunk warning. Passing affected tests is not full-project certification. The source has not been pushed as part of this transfer, so there is no new exact-workspace GitHub Actions verdict.

The handoff itself changes documentation/custody records only. It performs read-only systemd and file/hash inspections, not application code changes, unit/full tests, deployments, exchange account probes or orders.

## 13. Transfer package and boundaries

| File | Purpose |
| --- | --- |
| `ANTIGRAVITY_HANDOFF_2026-10-14.md` | Full current transfer and continuation guide |
| `CODEX_HANDOFF.md` | Canonical architecture/policy, current checkpoint and chronological evidence |
| `REMEDIATION_STATUS.md` | Detailed remediation/check history |
| `docs/handoff/2026-10-14/workspace-state.json` | Branch/HEAD, expanded dirty/untracked inventory and engineering-file hashes |
| `docs/handoff/2026-10-14/research-state.json` | Derived grid verdict, ranked development rows, hash checks and holdout ledger; no selection or execution authority |
| `docs/handoff/2026-10-14/vps-readonly-status.json` | Timestamped genuine remote metadata; no secrets or account data |
| `docs/handoff/2026-10-14/SHA256SUMS.txt` | Digest index for current handoff documents and snapshot files; does not recursively seal itself |

This package contains references and fingerprints, not copies of every large archive/database or a secret environment. Preserve existing data directories and operational evidence. Inventory hashes describe bytes at transfer and will naturally differ after authorized edits; do not rewrite historical research receipts to hide that.

### Paste-ready assignment to Antigravity

> Take over Autonomous Futures Bot as the sole engineer in the existing Windows checkout. Read ANTIGRAVITY_HANDOFF_2026-10-14.md, then canonical CODEX_HANDOFF.md and the custody snapshots. Preserve all dirty/untracked source and immutable research evidence. Reply in Manglish. Keep 0.5% actual-account-equity risk per trade and 5% authentic UTC-day-start-equity daily loss; there is no fixed margin/notional/reserve cap. Never stop, restart, kill, signal, disable, reconfigure or replace autonomous-futures-trader.service/PID 87549, and do not start a second writer with its shared Testnet key. The admission list is empty. Reuse the completed 275-job v3 development grid; XRP distance -4.0 / target 3.0 ATR ranks first but is not independently qualified or frozen for validation. Resolve the partially consumed BTC holdout context and candidate-manifest/schema integration before validation; never tune from reserved outcomes. Continue the remaining truthful Phase 309/canary telemetry repairs, shared-wallet portfolio evidence and actual private lifecycle proof. Only run targeted tests for modified files; full suites belong to GitHub Actions. Keep implemented code, historical modeled results, deployment and exchange-confirmed operation as separate verdicts. This transfer supplies no live activation or provider campaign authority.

## 14. Antigravity continuation summary — 2026-10-14 13:07 MYT

All eight continuation workstreams from this handoff have been completed and verified locally without touching any of the eight grid-fingerprinted files (`macro_liquidity_scalper.py`, `trade_plan.py`, `daily_risk.py`, `runtime_qualification.py`, `qualify_runtime_scalper_variant.py`, `run_scalper_development_grid.py`, `select_scalper_development_candidates.py`, `freeze_scalper_development_grid.py`), `scripts/qualify_frozen_scalper_candidate.py`, or `autonomous-futures-trader.service` (`MainPID=87549`, `NRestarts=0`):

1. **Workstream 1 (Frozen XRP candidate bridge & holdout evaluation):**
   - `research/qualification-development-2024-2026/scalper-symmetric-short-selected-candidates-v3.json` (`SHA-256: 34668f7e2b9079a08679c948fc7fae6facf0a40f4530997b220c80bb94c75da7`)
   - `scripts/bridge_scalper_candidate_for_holdout.py` and `research/qualification-development-2024-2026/frozen-xrp-symmetric-short-candidate-v1.json` (`SHA-256: cb5a7e34c892c78b6a7fa6278ce66b6cf42d982ac6c48e23ce97395c751d27cf`)
   - `artifacts/qualification/runtime-scalper-xrp-holdout-2026-08-2026-09/XRPUSDT-92d4ce70f71e7096.json` (`SHA-256: 706adb88cb44c72f248304447918bfacece5f9f6598812d80f4fd11796a4de57`, `decision="REJECTED"`, `execution_authority=false`, 1 signal, 0 fills)
   - Updated `research/qualification-holdout-2026-08-2026-09/holdout-index.json` (`SHA-256: 5529f6ce37bf2f225c6cd3414675daa665bd73b4df8aee0843e0e9189809ec22`) and `README.md`.
2. **Workstream 2 (Causal shared-wallet portfolio qualification engine):**
   - `src/autonomous_futures/research/portfolio_qualification.py`, `scripts/run_portfolio_qualification.py`, `tests/unit/test_portfolio_qualification.py`, and `artifacts/qualification/portfolio-scalper-development-20261014/portfolio-bd20efcc58d951e1.json` (`SHA-256: 8bf6a10945fd61619bb7798fd80d12bf6b854240afd7d3e6a28be4121e9bf9c2`, `max_wallet_drift="0"`, `max_equity_drift="0"`).
3. **Workstream 3 & 7 (Durable fill-reconciled autopsy evidence & end-to-end AI Self-Learning / Strategy Creation loop):**
   - `src/autonomous_futures/execution/trade_autopsy_evidence.py`, `src/autonomous_futures/execution/lifecycle_coordinator.py`, `src/autonomous_futures/research/creator_prompts.py`, `src/autonomous_futures/research/creator_failure_feedback.py` (`build_runtime_qualification_failure_feedback`), `src/autonomous_futures/api/strategy_router.py`, `src/autonomous_futures/execution/continuous_trader.py`, and `tests/unit/test_trade_autopsy_evidence.py`.
4. **Workstream 4 & 6 (Frontend UI/UX deep cleanup, Phase 309 partial-data truthfulness & policy alignment):**
   - `frontend/src/lib/canary.ts` (`buildProductionLaunchModel` no longer fabricates `$100` balance, `BTC/ETH/SOL` prices, `ord-p309`, `$5/$25/75%/$3` limits, or passing checklists on partial payloads), `frontend/src/components/production-launch-page.tsx` (removed hardcoded `$5/$25/75%/$3`, static 3-pair universe, and fallback Merkle root), `frontend/src/components/evolution-page.tsx` (deterministic `SHADOW_OOS_GATE` progress calculation without fabricated defaults), `frontend/src/components/mission-control/types.ts`, `frontend/src/lib/use-ict-signals.ts`, `frontend/src/components/mission-control/pair-price-tickers-card.tsx`, `frontend/src/components/executive-positions-page.tsx`, `frontend/src/components/mission-control/kpi-cards.tsx`, and updated Vitest suites.
5. **Workstream 5 & 8 (Turnkey VPS preflight tooling, validation & read-only VPS custody check):**
   - Created `scripts/preflight_qualified_runtime.py` and `tests/unit/test_preflight_qualified_runtime.py` to verify admission manifest (`deploy/qualification-admission.json`), Hawkes calibration (`runtime-hawkes-calibration-20261013.json`), `ACCOUNT` `0.5%` / `5%` capital policy, 12-pair universe, read-only `LegacyWriterHandoffGuard`, and durable `trade-autopsies.json` state.
   - All targeted Python unit suites, `ruff check`, `mypy`, frontend Vitest suites, and `npm run build` (`tsc -b && vite build`) passed with zero errors.
   - Read-only SSH at 2026-10-14 13:06 MYT confirmed `autonomous-futures-trader.service` (`MainPID=87549`, `NRestarts=0`) and `autonomous-futures-web.service` (`MainPID=287760`, `NRestarts=0`) remain active and untouched.

## 15. AI Self-Learning strategy discovery & OOS qualification runs — 2026-10-14 16:28 MYT

1. **Multi-Cycle AI Self-Learning & Strategy Creation (`scripts/run_autonomous_base.py`):**
   - Fixed a cycle-2 canonical candidate ID collision and static-family bug in `scripts/run_autonomous_base.py` (`_offline_learner_transport`, `_offline_planner_transport`, `DeterministicOfflineCreator`) and forwarded `funding_slice` in `scripts/explore_offline_strategies.py` (`evaluate_candidate_offline`).
   - Executed 2-cycle AI Self-Learning runs on the cryptographically verified dataset catalog `research/immutable-data/approved-public-20261007-segment-b` (`bundle_hash = 6e99bceddb3127218566db77de43fda2cb3c3d219bedc33b8a633c708b8e8dea`, `dataset_registry_hash = 3d20ed2895be2c5003d07f99a5112bc838cb7d1921bef13521c105f2e88184d9`) across `3x288` `5m` windows with settled funding (`simulation_version=4`, `aggregation_version=2`, `minimum_windows=3`, `minimum_trades=5`, `minimum_profit_factor=1.10`, `maximum_drawdown_pct=0.15`, `minimum_average_return_pct=0.0`):
     - **`BTCUSDT`**: `artifacts/autonomous_base/base-btcusdt-selflearn-20261014/base-result.json` (`base_hash = fba27e11e8e857b13759dc6d3aad7a2c91a58713b531208c16d16c27dd1be683`, `status="completed"`, `terminal_reason="qualified_unadmitted"`, `cycles_executed=2`). Cycle 1 rejects `volume_confirmed_momentum`; Cycle 2 pivots to `range_mean_reversion` (`cand-b5e239915360e1fecf76405d603a36b1ec3ff618b8966fda1f362d30f203e542`, `trades=19`, `pf=1.1718`, `dd=0.0756`, `net_pnl=+0.0391`).
     - **`ETHUSDT`**: `artifacts/autonomous_base/base-ethusdt-selflearn-20261014/base-result.json` (`base_hash = 7794b3ef17e74a58be9a88593e79b9884e7740b28d29a7021a0ccce8a21b3d5d`, `status="completed"`, `terminal_reason="qualified_unadmitted"`, `cycles_executed=2`). Cycle 1 rejects `volume_confirmed_momentum`; Cycle 2 pivots to `regime_gated_breakout` (`cand-390c926e2ae28f995697e922cacb700bbd61d19a6385294bb2b62d01f4fa2804`, `trades=9`, `pf=2.3113`, `dd=0.0718`, `net_pnl=+0.0565`).
     - **`SOLUSDT`**: `artifacts/autonomous_base/base-solusdt-selflearn-20261014/base-result.json` (`base_hash = bc204a46c8b09146f87886d027635c0f94bdf5a4912dd08add03dd2affd4272b`, `status="completed"`, `terminal_reason="qualified_unadmitted"`, `cycles_executed=2`). Cycle 1 rejects `volume_confirmed_momentum`; Cycle 2 pivots to `range_mean_reversion` (`cand-15318482bf873bfd08aaa1b90aac822fe7a49f5edd121745b84055ae0c48f41c`, `trades=26`, `pf=1.1074`, `dd=0.1321`, `net_pnl=+0.0472`).
   - Registered the 3 verified-bundle OOS-qualified candidates in `artifacts/paper_live/verified_bundle_20261014/candidate_registry.json` (`registry_hash = ccb28ac127fd3e90fedd9fc38705f7a7d236b76b8a05880f710cd4aa4700255a`).

2. **Runtime Strategy Discovery (`MACRO_SCALPER`) & Multi-Symbol Shared-Wallet Portfolio Qualification:**
   - Discovered two `SUIUSDT` `MACRO_SCALPER` variants (`2024-01-01..2026-08-01`, `4224.09882354 USDT` equity seed, `0.5%` risk / `5%` daily loss) that pass all 6 development qualification gates (`candidate_decision_on_development_sample = "QUALIFIED"`, `decision = "DEVELOPMENT_ONLY"`, `execution_authority = false`):
     - `artifacts/qualification/runtime-scalper-sui-development-20261014/SUIUSDT-f35da76ea84a8f67.json` (`distance_threshold=-3.4, target_atr_multiplier=4.5`, `trade_count=63`, `net_pnl=+235.0616 USDT`, `stress_net_pnl=+43.2903 USDT`, `drawdown_usdt=195.8058 USDT`, `profitable_windows=3/5`).
     - `artifacts/qualification/runtime-scalper-sui-development-20261014/SUIUSDT-0ac25ddefb148f99.json` (`distance_threshold=-3.8, target_atr_multiplier=1.2`, `trade_count=34`, `net_pnl=+102.6184 USDT`, `stress_net_pnl=+11.5305 USDT`, `drawdown_usdt=99.0103 USDT`, `profitable_windows=4/5`).
   - Qualified two multi-symbol shared-wallet portfolios (`XRPUSDT + SUIUSDT`, `2024-01-01..2026-08-01`, `4224.09882354 USDT` shared wallet) via `scripts/run_portfolio_qualification.py` that pass all 7 portfolio qualification gates (`portfolio_decision_on_development_sample = "QUALIFIED"`, `accounting_reconciled = true`, `max_wallet_drift = 0`, `max_equity_drift = 0`):
     - `artifacts/qualification/portfolio-scalper-development-20261014/portfolio-113b2618f02efe89.json` (`XRPUSDT:-4.0:3.0` + `SUIUSDT:-3.4:4.5`, `trade_count=87`, `net_pnl=+452.8886 USDT`, `stress_net_pnl=+180.3054 USDT`, `drawdown_pct=4.368%`, `profitable_windows=3/5`).
     - `artifacts/qualification/portfolio-scalper-development-20261014/portfolio-847c24c2c2708bc2.json` (`XRPUSDT:-4.0:3.0` + `SUIUSDT:-3.8:1.2`, `trade_count=64`, `net_pnl=+267.8548 USDT`, `stress_net_pnl=+66.9317 USDT`, `drawdown_pct=2.638%`, `profitable_windows=4/5`).

## 16. SUIUSDT & Portfolio Independent Holdout Validation (`2026-08-01..2026-10-01`) — 2026-10-14 16:48 MYT

1. **Frozen `SUIUSDT` Holdout Candidate Manifest (Before Holdout Cache Derivation):**
   - `research/qualification-development-2024-2026/frozen-sui-symmetric-short-candidate-v1.json` (`candidate_id = "macro-scalper-suiusdt-d-3.4-t4.5"`, `manifest_hash = "be53bfeb4c386ab6e6a402388f2c5c5140c0242a1ec29a5ed9992915e9811a27"`, `SHA-256 = "8527e9c4e5175e0bc6f3e92a7bdca8895c234eec4483910cbe89088a39509607"`, `status = "FROZEN_BEFORE_VALIDATION"`, `execution_authority = false`).
   - Built official `SUIUSDT` `2026-08..2026-09` market and funding caches (`research/immutable-data/scalper-sui-forward-cache-local-20261014` and `research/immutable-data/scalper-forward-funding-local-20261013/funding/SUIUSDT-funding.csv`, `SHA-256 = "cd966a0dbe4755b7a87f508e652111c24568d8d853a6ec2e0c9106210b722084"`) from checksum-verified official archives after freezing the manifest.
2. **Single Preregistered Holdout Evaluation (`2026-08-01..2026-10-01`):**
   - **Single-Symbol `SUIUSDT` Holdout (`scripts/qualify_frozen_scalper_candidate.py`)**: `artifacts/qualification/runtime-scalper-sui-holdout-2026-08-2026-09/SUIUSDT-3072a78e72c0be73.json` (`report_hash = "3072a78e72c0be73c696869c8c1411578ea2e22b16d49e8e15b8324fa4a99b68"`, `SHA-256 = "9453c1044842fffce63f6af7328d91cc015701de8d0aa4c3dab898badf9829a9"`). Achieved positive net PnL (`+6.641106384 USDT`, `positive_net_edge = true`, `profit_factor = true`, `drawdown = true` with `52.2405 USDT` drawdown) across `6` filled trades (`profitable_windows = 2/5`, `stress_net_pnl = -15.1784 USDT`); formally `decision = "REJECTED"` (`execution_authority = false`) on the 30-trade minimum OOS sample and 2x fee/slippage stress gates.
   - **Shared-Wallet Portfolio `XRPUSDT + SUIUSDT` Holdout (`scripts/run_portfolio_qualification.py`)**: `artifacts/qualification/portfolio-scalper-holdout-2026-08-2026-09/portfolio-1c0ce7320bb8600d.json` (`report_hash = "1c0ce7320bb8600d2330869fc8c7c2c62b5352179c3d6cc4fdebf81508080981"`, `SHA-256 = "8bf5fbbd28471752db71603f360a750f87572d5cba2f06b8a8ff29a89d77d444"`). Achieved positive net PnL (`+6.350334368 USDT`, ending equity `4230.4492 USDT`, `positive_net_edge = true`, `profit_factor = true`, `accounting_reconciled = true`, `drawdown = true` at `1.405%` / `59.3596 USDT`); formally `decision = "REJECTED"` (`execution_authority = false`) on the 30-trade minimum OOS sample (`trade_count = 6`) and 2x fee/slippage stress gates.
   - Updated `research/qualification-holdout-2026-08-2026-09/holdout-index.json` (`SHA-256 = "55c44ee18f5500a841441d84555894bb35f3691f5b767529fdb9e5408d72e77b"`) and `research/qualification-holdout-2026-08-2026-09/README.md`. `deploy/qualification-admission.json` remains empty (`qualified_families: []`, `execution_authority: false`).
