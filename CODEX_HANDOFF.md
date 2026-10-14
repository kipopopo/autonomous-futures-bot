# Autonomous Futures Bot — Codex Handoff & Architecture Blueprint

**Canonical Full-Project Architecture, Policy and Engineering Handoff.**  
**Document Timestamp:** 2026-10-14T07:27:00+08:00 (MYT)  
**Author:** Antigravity (Google DeepMind)  
**Latest Custodian:** Codex; transfer back to Antigravity requested by the owner  
**Target:** Antigravity / Next Engineering Agent  
**Repository:** https://github.com/kipopopo/autonomous-futures-bot  
**Branch:** `main`  
**Live Production URL:** https://futures.semua.dev/  

---

## Workspace remediation status — 2026-10-12

The original production snapshot below is historical handoff evidence, not a current exchange reconciliation. Local remediation is documented in `REMEDIATION_STATUS.md`; changes have not been deployed. The running trader must remain untouched. Local live dispatch now fails closed instead of using simulated matching. Fresh authenticated exchange account evidence is required by the revised execution API. Missing evidence returns HTTP 503. Genuine runtime strategy qualification and live microstructure/protective lifecycle integration remain prerequisites for activating the revised trader; registered placeholder candidates must not grant authority.

### Active engineering decision — 14 October 2026 (MYT)

The user reaffirmed **0.5% of actual exchange account equity as risk per trade** at
2026-10-14 06:17 MYT, superseding historical 0.25% notes below. The runtime planner,
qualification freeze, and frozen replay sidecars already use 0.5%, so this decision is
aligned with existing evidence and requires no replay restart or policy mutation. The
separate 5% UTC-day-start-equity daily-loss cutoff remains in force. This does not grant
qualification or execution authority.

### Current checkpoint — 14 October 2026, 07:27 MYT: transfer to Antigravity

The owner requested a full engineering handoff back to Antigravity. Read
`ANTIGRAVITY_HANDOFF_2026-10-14.md` for the consolidated transfer, custody, evidence and
continuation plan. This file remains the canonical architecture/policy record. Older
handoff snapshots and worker-active chronology below are historical.

Fresh pinned read-only SSH at approximately 07:22–07:23 MYT, using the explicit Kainode key,
confirmed the protected trader active/running at PID 87549 with `NRestarts=0`; web service
active/running at PID 287760 with `NRestarts=0`. No active matching `afb*` or qualified-runtime
research/replacement user unit was shown. Two historical BTC/LINK cache-builder units
remain failed. Exact outputs/timestamps are in
`docs/handoff/2026-10-14/vps-readonly-status.json`. This supersedes the earlier public-key
failure; it is a scoped metadata observation, not an exchange-account reconciliation.
No protected service or process was controlled.

The local symmetric-short development grid completed 275/275 jobs with zero failures.
All 120 frozen input hashes and 275 report file/self-hashes validated again for transfer.
Five XRP variants pass development gates; distance -4.0 / target 3.0 ATR ranks first.
All remain development-only and execution authority is false; no new candidate manifest
or independent XRP validation was created. The reserved Aug–Sep ledger is partially
consumed through LINK market/funding and BTC 1h shared context. Admission remains empty.

Canary API defaults were hardened so an unpopulated model reports unverified/unknown
state, null runtime telemetry, and fail-closed macro gating instead of asserting a fixed
daemon PID, online status, BTC prices/EMAs, heartbeat, sample count, or Sharpe hurdle. The
unused macro loader that seeded constants and fell back to stale historical data was
removed. Artifact-derived solvency values now use fields already required by validation;
missing timestamps remain absent instead of being replaced with the current wall clock.
The Phase 297 Stress page now renders unavailable evidence as unavailable, and labels loaded
values as historical artifact results. It no longer invents a $100 account, zero drift,
green safety outcomes, a $7 loss ceiling, or 40%/93% reserve/survival floors. Targeted
canary tests passed (19); the targeted Stress page tests passed (7); frontend production
build, Ruff, formatting, strict mypy, and the scoped diff check passed. No full suite,
replay, deployment, credential, account, or order action occurred.

The Phase 307 Testnet Bridge mapper/page was also hardened at 07:10 MYT: missing evidence
no longer creates a connected gateway, mock key, fills, filters, balance or safe/off/drift
claims. Three targeted tests and the TypeScript/production frontend build passed.
The broader frontend `canary.ts` still contains stage-specific fallback models with fixed
account, reserve, or safety values outside the repaired Phase 297/307 flows. Those remain in the
project audit queue and must not be treated as current telemetry. This checkpoint does not
claim project-wide mock-state cleanup.

The transfer changes documentation/custody records only. It does not rerun tests, qualify
a strategy, deploy, commit/push, probe the exchange account or submit an order. Extensive
dirty and untracked local files must be preserved; Git HEAD alone does not contain this work.

Remaining blockers are unchanged: no genuinely qualifying strategy or shared-wallet
portfolio report exists; current UTC-day-start account equity is not verified; live
microstructure/protective behavior has not been proven with real private events; and the
same Testnet writer key remains shared with PID 87549. Do not start a second writer or
change the protected service.

### Current checkpoint — 14 October 2026, 11:50 MYT: Antigravity continuation completed

Following the handoff back to Antigravity, all five continuation workstreams were executed and verified locally while preserving all eight grid-fingerprinted files and keeping the protected VPS daemon (`autonomous-futures-trader.service`, MainPID `87549`, `NRestarts=0`) untouched:

- **Frozen XRP candidate bridge & single preregistered Aug–Sep 2026 holdout evaluation:** Selected `XRPUSDT` (`distance_threshold=-4.0`, `target_atr_multiplier=3.0`) via `scalper-symmetric-short-selected-candidates-v3.json` (`SHA-256: 34668f7e2b9079a08679c948fc7fae6facf0a40f4530997b220c80bb94c75da7`), bridged to `frozen-xrp-symmetric-short-candidate-v1.json` (`SHA-256: cb5a7e34c892c78b6a7fa6278ce66b6cf42d982ac6c48e23ce97395c751d27cf`) via `scripts/bridge_scalper_candidate_for_holdout.py`, and evaluated once on the Aug–Sep 2026 holdout (`artifacts/qualification/runtime-scalper-xrp-holdout-2026-08-2026-09/XRPUSDT-92d4ce70f71e7096.json`, `SHA-256: 706adb88cb44c72f248304447918bfacece5f9f6598812d80f4fd11796a4de57`): 1 signal, 0 fills, `decision="REJECTED"`, `execution_authority=false`. Updated `research/qualification-holdout-2026-08-2026-09/holdout-index.json` (`SHA-256: 5529f6ce37bf2f225c6cd3414675daa665bd73b4df8aee0843e0e9189809ec22`). `deploy/qualification-admission.json` remains empty.
- **Causal shared-wallet portfolio qualification engine:** Added `src/autonomous_futures/research/portfolio_qualification.py` and `scripts/run_portfolio_qualification.py`, enforcing shared Decimal wallet accounting (`max_wallet_drift="0"`, `max_equity_drift="0"`) across concurrent multi-symbol pending entries, open positions, fees, funding, and the 5% UTC-day-start daily-loss circuit (`artifacts/qualification/portfolio-scalper-development-20261014/portfolio-bd20efcc58d951e1.json`, `SHA-256: 8bf6a10945fd61619bb7798fd80d12bf6b854240afd7d3e6a28be4121e9bf9c2`).
- **Durable fill-reconciled autopsy evidence & Creator self-learning loop:** Added `src/autonomous_futures/execution/trade_autopsy_evidence.py` and wired `_record_closed_autopsy` into `LifecycleCoordinator` (`owned-trades.json` + `trade-autopsies.json`), injected `RUNTIME_RISK_POLICY_GUIDELINES` and `autopsy_feedback` into `creator_prompts.py`, and merged fill-reconciled autopsies into `strategy_router.py`.
- **Frontend UI/UX truthfulness & policy alignment:** Updated `use-ict-signals.ts` (`getFallbackIctSignals()` returns `verified: false`), `types.ts`, `pair-price-tickers-card.tsx`, `executive-positions-page.tsx`, and `kpi-cards.tsx`. Targeted Vitest suites (84 passed) and `npm run build` passed cleanly.

### Active engineering evidence - 13 October 2026 (MYT)

**Risk-policy decision reaffirmed at 2026-10-13 21:48 MYT:** retain 0.5% of actual
account equity as risk per trade. This supersedes the later 0.25% selection recorded in
historical notes below. The shared runtime planner (`trade_plan.py`), ICT freeze script,
and frozen replay sidecars use 0.5%, so their risk setting is aligned; this decision does
not change or restart any worker. The separate 5% daily-loss cutoff
still uses genuine actual-account equity captured at UTC day start. Rejected OHLCV replay
reports remain modeled evidence, not exchange fills or live execution authority.

The daily-risk evidence pipeline now accounts for authenticated USDT `TRANSFER` records as
capital-basis adjustments after the UTC day-start snapshot. Deposits cannot erase trading
losses and withdrawals are not counted as trading losses; ambiguous or unclassified income
fails closed. Both strategy-family qualification receipts now require the current
`daily_risk.py` source hash. At the 22:50 MYT pinned, read-only SSH check, the protected
trader remained active at PID 87549 with NRestarts=0; both credential-free replay units
also remained active with NRestarts=0 (PIDs 639755 and 645096). Those VPS workers predate
the current source update and cannot be admitted under the current implementation. No
service was changed.

Local stream integration is now implemented: the qualified runtime consumes authenticated
user events, REST-resynchronizes after reconnect, blocks entries across a stream gap, and
routes margin-call/conditional-trigger-reject events into protective handling. Testnet
public `/market` and `/public` routes were checked read-only. A bounded 20-second Testnet
private-stream probe using the existing shared API key connected successfully, completed
one initial REST reconciliation, received zero private events, and reported no error. The
probe called no order endpoint and grants no execution authority. Event handling, event-gap
recovery, and risk-trigger behavior remain unverified against live private events. The
integration passed 91 targeted tests plus Ruff, formatting, and strict mypy; it remains
undeployed.

The 11 Macro Scalper universe reports are historical **REJECTED** diagnostics. Their
report hashes validate, but their `runtime_qualification.py` implementation digest does not
match current source and they omit the current `daily_risk.py` binding; do not use them as
current-source qualification receipts until replayed. The earlier
`directional_fix` ICT screen had eight completed pair reports, all **REJECTED**; it is
superseded by the current-source `reclaim_retest` screen in §§20–22 below. At 23:45 MYT,
all 12 current-source pair reports are complete and all 12 are **REJECTED**. No strategy
qualifies, actual activation remains unproven, and the deployment admission list is empty.

The frozen LINK Macro Scalper development candidate was evaluated once on the reserved
2026-08-01 through 2026-10-01 forward window and **REJECTED** (one trade, net PnL
-0.394283250 USDT, stressed net PnL -0.478539035 USDT). That window has been consumed
for LINK Macro Scalper and BTC 1h context; do not tune from it. Other pair/strategy
holdout observations remain reserved until their own candidate and policy are frozen.

The earlier `directional_fix` ICT diagnostics covered BTC, ETH, SOL, DOGE, BNB, XRP, SUI
and AVAX; all eight now have source attestations. Across them, 185 CISD invalidation exit events
were recorded in 189 trades; 182 trades ended only by that exit, with a median one-minute
hold and 105 closing within one minute. A diagnostic that omitted that exit and retained
the original stop, targets and time limit covered those 182 follow-throughs and produced
-10.63228 USDT gross before fees/funding; it is diagnostic only and provides no basis to
weaken the live exit. The four missing pairs are NEAR, LINK, APT and ADA. Their earlier
Windows workers did not produce reports. A hash-recorded, credential-free source package
has been verified in an isolated Kainode research directory. The low-priority transient
unit `afb-ict-resume-archives-20261013.service` completed successfully after acquiring
and checksum-verifying all 128 official 1m archives for those four symbols, Dec 2023
through Jul 2026. Every one of the 710 packaged source, configuration, archive and
provenance inputs matches the local SHA-256 manifest. The canonical 5m/1h/funding cache
ends at 2026-08-01 00:00 UTC. The reserved August–September holdout is excluded.

The frozen four-pair replay is running as two detached, credential-free batches.
`afb-ict-resume-qualification-20261013.service` runs NEAR and LINK in the original
output directory with two workers, CPUQuota=200%, MemoryMax=4G, Nice=19 and idle I/O.
`afb-ict-resume-qualification-apt-ada-20261013.service` runs APT and ADA with two
workers, CPUQuota=200%, MemoryMax=2G, Nice=19 and idle I/O, writing to a separate
output directory so reports cannot collide. The workers use four CPU cores total
when available; all 12 frozen inputs and the reserved holdout boundary are unchanged.
At 2026-10-13 19:41 MYT, all four pair workers were active at about one core each.
The protected trader was still active at PID 87549 with NRestarts=0. No final reports
are available yet. Both qualification environments are cleared and contain no API
credentials.

The latest isolated read-only VPS probe demonstrated zero sequence gaps, zero stale
ingress frames and 2,234 genuine arrivals. The original fit reported rho=0.99763996158228,
but a post-probe audit found all 12 fitted baseline rates exactly at the optimizer's 1e-9
lower bound. That fit is not sufficiently identified for admission. Microstructure
evidence now fails closed on any boundary-pinned baseline. Earlier BNB, XRP, NEAR, LINK
and ADA instantaneous passes are invalidated by that fit-quality finding.

The actual 120-second trace was also replayed against the per-coefficient sample gate.
After burn-in, observed per-symbol counts ranged from 102 to 221, below the 390 required
for 13 fitted coefficients per output dimension. The fitter now preserves the observed
counts in its rejection diagnostic; this trace yields no fit and grants no admission.

An ICT audit found the Step 1 resolver preferred bearish setups when both directional
5m CISD candidates existed and also defaulted bearish when both PDA directions were
present without a confirmed displacement. The resolver now compares the actual 5m
confirmation timestamps and returns no setup for a same-candle tie or unresolved
two-sided PDA state. The focused ICT unit file passes (43 tests), and Ruff is clean.

The composed qualified Testnet runtime and its separate service definition exist locally;
they have not been installed or started as a trading service. The operator selected actual exchange ACCOUNT equity
and has now requested reuse of the existing Testnet API key, superseding the earlier distinct-key plan. The local
bootstrap now reads the existing `BINANCE_TESTNET_API_KEY` and `BINANCE_TESTNET_SECRET_KEY` pair. Before startup
or any new entry, it requires systemd to prove the legacy unit is disabled, configured with `Restart=no`, and fully
inactive (`ActiveState=inactive`, `SubState=dead`, `MainPID=0`). This handoff is not established while the legacy
daemon may still be active. The environment file still contains only AFBOT_EQUITY_BASIS=ACCOUNT. A fresh pinned
read-only SSH preflight on 2026-10-13 verified the actual user-level trader unit active at PID 87549 with
NRestarts=0. PID 87549 must remain untouched. No systemd, API-key, or exchange-order changes have been made on the
VPS. The targeted single-writer and runtime tests pass (23 tests);
Ruff and strict mypy pass. See
`REMEDIATION_STATUS.md` and immutable evidence under `artifacts/qualification/`.

The qualified order book now requires its final genuine entry-admission guard on every
opening submission; a caller-supplied qualification boolean and rho value cannot authorize
an opening order by themselves.

At 2026-10-13 20:20 MYT, a fresh pinned read-only SSH check confirmed both credential-free
VPS replay units remained active with zero restarts and all four symbol workers consuming
about one CPU each. NEAR, LINK and ADA had checkpointed through 2024-06-29 UTC; APT through
2024-05-30 UTC. No final reports were present. The
production trader remained active at PID 87549 with NRestarts=0. The user selected a
0.25% actual-account-equity risk budget per trade. The running frozen ICT sidecar still
records 0.5%, so its eventual reports are diagnostic only for the newly selected risk
policy and cannot be admitted as execution evidence. Preserve those reports and source
attestations first; then bind 0.25% in the runtime planner and newly frozen qualification
policy. Do not edit `trade_plan.py` while the current reports are in flight because that
file is implementation-hash-bound. No replay inputs, VPS services, account settings, API
keys, or exchange orders were changed during this check.

At 2026-10-13 20:25 MYT, a fresh pinned, read-only SSH check confirmed both replay units
still active with `NRestarts=0`. NEAR and LINK checkpointed through 2024-07-29 UTC
(wallets 99.69289040 and 99.890925178 USDT); APT and ADA checkpointed through 2024-06-29
UTC (wallets 100 and 99.3009999928300 USDT). No final reports or source attestations are
present yet. The production trader remains active at PID 87549 with `NRestarts=0`, and it
was not signaled or controlled. The frozen replay remains at 0.5% per-trade risk, so its
results remain diagnostic against the selected 0.25% policy. No source, admission, service,
API-key, account setting, or exchange-order changes were made during this checkpoint.

At 2026-10-13 20:31 MYT, both credential-free replay units were still active with
`NRestarts=0`. NEAR and LINK had advanced through 2024-08-28 UTC (wallets 99.60069260 and
99.780166722 USDT); APT and ADA had advanced through 2024-07-29 UTC (wallets 100 and
99.3009999928300 USDT). The worker directories contained checkpoint logs only, with no
final reports or source attestations. The production daemon remained active at PID 87549
with `NRestarts=0`; it was not signaled or controlled.

The local offline `execution/self_driving.py` path now rejects entries when measured
Hawkes/heartbeat evidence is absent or invalid. It also skips generic and ICT autopsy
feedback when the required observed market-quality or price-excursion inputs are missing,
and rejects incomplete queued ICT evidence instead of substituting entry/exit prices.
Three targeted unit tests passed; Ruff and strict mypy passed. This local data-integrity
fix was not deployed and does not change the in-flight frozen qualification package or
its 0.5% risk setting.

The local qualified admission path now reads Binance's authenticated `/fapi/v1/positionSide/dual`
evidence and rejects Hedge Mode before preparing prearmed exits or submitting an entry.
The gateway now resolves credentials only from the selected environment and rejects signed
requests without that environment's key pair; it has no mock-key fallback or Testnet/live
cross-fallback. The targeted gateway and admission tests pass (39); Ruff and strict mypy
pass for the modified Python sources. These are local guards only; they are not installed
on the VPS.

At 2026-10-13 20:39 MYT, a fresh pinned, read-only SSH check confirmed both frozen
credential-free replay units active with `NRestarts=0`. NEAR checkpointed through
2024-10-27 (wallet 99.60069260 USDT); LINK and ADA through 2024-09-27 (wallets
99.780166722 and 99.1353656728300 USDT); APT through 2024-08-28 (wallet
99.5150112400 USDT). Their output directories contain checkpoint logs and frozen policy
only; no final reports or source attestations are present. The production daemon remains
active at PID 87549 with `NRestarts=0` and was not signaled or controlled. The replay
policy remains 0.5% per trade, so these outputs are diagnostic against the selected 0.25%
policy.

A read-only feed-schema audit against [Binance USDⓈ-M WebSocket Market Streams](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/public)
confirmed the combined-stream `data` wrapper and the event fields consumed for aggregate
trades and depth updates are handled by the local parser. No source change was indicated.
This checked the schema and local parsing only; it did not probe the Testnet endpoint.

At 2026-10-13 20:46:32 MYT, an authenticated read-only Testnet account probe observed
equity and available balance of 4,224.09882354 USDT, with no open positions, ordinary
orders, or conditional orders. At this snapshot 0.25% equals 10.56024705885 USDT per
trade. The probe used a temporary first-observation ledger, so its `ledger_reconciled=true`
is only a point-in-time identity check, not continuous double-entry evidence. Its daily
risk result was unverified; do not use 5% of this snapshot as today's cutoff. Runtime
entries must wait for a verified UTC day-start equity observation. The temporary account
snapshot was deleted and no credential was persisted.

`RuntimeSession.cycle()` now still attempts lifecycle reconciliation after an authenticated
account refresh error; it admits no entry on that cycle, and the coordinator itself blocks
if cached account evidence is missing or stale. The targeted runtime-session test file
passes (6 tests); Ruff, formatting, and strict mypy pass. This local fix is not deployed.

At 2026-10-13 20:54 MYT, both frozen replay units remained active with `NRestarts=0`.
NEAR had advanced through 2024-12-26 (wallet 99.39627580 USDT), LINK and ADA through
2024-11-26 (wallets 99.276206990 and 99.0052604128300 USDT), and APT through 2024-10-27
(wallet 99.2038214800 USDT). No final reports or source attestations were present. The
production daemon remained active at PID 87549 with `NRestarts=0` and was not signaled.

At 2026-10-13 21:01 MYT, a local runtime audit found that the one-second protective
cycle was fetching the full authenticated account, positions, orders, symbol settings,
and income history on every pass. `RuntimeSession` now refreshes the routine account
snapshot every 10 seconds, uses bounded exponential retry backoff after REST failures,
and still forces authenticated refreshes before entry recovery and after recovery before
admission. The independent protective cycle continues every second and still blocks
entries on failed, missing, stale, or unreconciled evidence. Eight targeted runtime-session
tests pass; Ruff, formatting, and strict mypy pass. This change is local only: it has not
been deployed or used to start a second writer. No VPS workers, services, API keys, or
exchange orders were changed.

The same audit found that the qualified runtime does not consume authenticated Binance
user-stream events: its gateway helper only creates/renews a listen key, while the
coordinator REST-reconciles each nonterminal order every one-second pass. Binance's
[USDⓈ-M User Data Streams documentation](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/user-data-streams)
documents `ACCOUNT_UPDATE` and `ORDER_TRADE_UPDATE`, recommends prioritizing user-stream
messages for order/position/account state, and requires handling 60-minute listen-key
expiry and 24-hour connection renewal. This is a confirmed integration gap, not yet a
code change. Before integrating it, verify the current Testnet private-stream endpoint and
reconnect/snapshot recovery behavior; do not open/renew a shared account listen key while
the protected legacy writer is active. No live user stream was opened during this audit.

At 2026-10-13 21:04 MYT, a read-only SSH status check confirmed the production trader
still running at PID 87549 with `NRestarts=0`; both credential-free qualification services
also remained active (PIDs 639755 and 645096, each `NRestarts=0`). No worker checkpoint
logs were read in this status query. No VPS service was controlled or changed.

At 2026-10-13 21:05 MYT, direct read-only checkpoint inspection confirmed progress in all
four symbol workers: NEAR through 2025-02-24 (wallet 99.39627580 USDT), LINK through
2025-01-25 (100.514093660 USDT), and APT/ADA through 2024-12-26 (99.2038214800 and
98.7728345928300 USDT). No final reports or source attestations existed in either output
directory. All remain frozen at 0.5% per-trade risk; they are diagnostic against the
selected 0.25% policy. The two replay units remained active with zero restarts, and the
production trader remained active at PID 87549 with zero restarts.

`LifecycleCoordinator.advance()` now surfaces any protective command that remains
`UNKNOWN` after recovery, including an orphaned command not attached to a trade record, so
`RuntimeSession` blocks new entry admission until that uncertainty is resolved. The new
focused regression test passes; six targeted lifecycle-coordinator tests pass, as do Ruff,
formatting, and strict mypy. Local only; no frozen strategy source or VPS process changed.

The user-stream audit also confirmed Binance's current USDⓈ-M schema includes `ALGO_UPDATE`
for conditional orders and `CONDITIONAL_ORDER_TRIGGER_REJECT`; the runtime currently
consumes neither. Before wiring events, the Testnet private endpoint and reconnect recovery
must be verified. No listen key was opened while the shared-key legacy trader is active.

## 1. Executive Summary & Product Mandate

The **Autonomous Futures Bot** is a 24/7 institutional-grade, micro-capital self-driving algorithmic trading platform operating on Binance Futures USDⓈ-M perpetual markets. 

The bot pairs high-frequency statistical mechanics with qualitative price-delivery market models:
1. **15m Macro-Confluence Liquidity Dip Scalper**: Trend-aligned mean reversion triggered on extreme capitulation dips ($> 2.5\times$ ATR below 20 EMA, volume $> 2.2\times$ 20 SMA, RSI 14 $< 26$, gated by Bitcoin 1h/4h EMA 50 > 200 regime).
2. **ICT Market Maker Model (MMXM) & Twins Reversal**: Multi-timeframe institutional smart-money pattern recognition (4h/1h PD Arrays, 5m CISD, 1m Twin FVGs, 62%–79% OTE Fibonacci retracement, 1m CISD invalidation, and 2.0x/4.0x STDV extension targets).
3. **Multivariate Hawkes Microstructure Filter**: Real-time jump intensity ($\lambda$) and spectral radius ($\rho < 1.0$) monitoring to veto executions during predatory or supercritical orderbook conditions.
4. **Closed-Loop Strategy Autopsy & Auto-Evolution**: 5-stage Walk-Forward Out-of-Sample (OOS) qualification gates, parameter genome mutation, and automated trade attribution (timing error vs adverse selection vs net edge).
5. **Continuous Double-Entry Zero-Drift Bookkeeping**: Mathematical solvency invariant holds $|\Delta| = 0.00 < 10^{-15}\text{ USDT}$ at all state transitions.

---

## 2. Infrastructure & Live Service State

### A. Kainode Linux VPS
- **IP Address:** `147.79.18.15`
- **SSH User:** `afbot`
- **SSH Key Location (Local Windows):** `C:\Users\thaqi\.ssh\kainode_ed25519_openssh`
- **Remote Root Path:** `/opt/autonomous-futures-bot`
- **Python Virtualenv:** `/opt/autonomous-futures-bot/.venv`
- **Production Web Domain:** `https://futures.semua.dev/` (Cloudflare CDN + Nginx reverse proxy)

### B. Active Systemd Services (User Slice)

| Service Name | Description | Current Status | Command Line |
|---|---|---|---|
| `autonomous-futures-trader.service` | 24/7 Continuous Self-Driving Trader Daemon | Fresh read-only SSH check: **ACTIVE (MainPID=87549, SubState=running)**, `NRestarts=0`; PID 87549 was not signaled or controlled | `/opt/autonomous-futures-bot/.venv/bin/python scripts/run_phase_310_real_autonomous_trading.py --storage-dir /opt/autonomous-futures-bot/artifacts/research/phase310 --starting-capital 100.00 --symbols SOLUSDT,ETHUSDT,BTCUSDT` |
| `autonomous-futures-web.service` | FastAPI Backend & Vite Static Web Server | **ACTIVE**, runs on `127.0.0.1:8000` | `/opt/autonomous-futures-bot/.venv/bin/uvicorn autonomous_futures.api.app:app --host 127.0.0.1 --port 8000 --proxy-headers` |

---

## 3. Critical Invariants & Rules of Engagement

> [!CAUTION]
> **RULE 1 — NEVER RESTART OR KILL THE TRADER DAEMON (PID 87549)**  
> The background trader daemon (`autonomous-futures-trader.service`) on Kainode VPS has been running continuously without restart. **Do NOT kill, restart, or interrupt PID 87549**. When deploying web or frontend changes, restart `autonomous-futures-web.service` ONLY.

> [!IMPORTANT]
> **RULE 2 — DO NOT RUN REDUNDANT FULL-SUITE TESTS LOCALLY**  
> GitHub Actions automatically runs the full 5,000+ pytest test suite on every commit to GitHub (`.github/workflows/`). Running full-suite tests locally takes over 15 minutes and is strictly redundant. Only run targeted unit tests for files you touch.

> [!IMPORTANT]
> **RULE 3 — MICRO-CAPITAL CONFINEMENT & SOLVENCY**  
> All live/testnet orders and simulation slices must strictly satisfy:
> - No fixed initial-margin-per-trade limit (user removed the $5 limit).
> - No fixed aggregate-notional cap (user removed the $25 limit).
> - No fixed cash-reserve floor (user removed the 75% floor). Exchange available-margin sufficiency remains mandatory.
> - Dynamic daily loss limit: **5% of actual exchange account equity captured at UTC day start**, replacing the fixed $3 limit. Cancel new entries and protectively flatten owned positions when breached. Missing or unreconciled day-start equity blocks new entries.
> - Double-entry zero-drift balance invariant:  
>   $$\text{Wallet} = \text{Starting Equity} + \text{Net Realized PnL}, \qquad \text{Equity} = \text{Wallet} + \text{Unrealized PnL}$$
>   Both identities must reconcile with Decimal precision and absolute drift below $10^{-15}$ USDT. Net realized PnL includes commissions and funding. Wallet movements require a separate basis adjustment and must not be classified as trading profit. This correction was explicitly approved by the user on 2026-10-12.

> [!NOTE]
> **RULE 4 — DATA-DRIVEN & FUNCTIONAL (NO HARDCODING)**  
> Everything across the UI and backend must be genuinely dynamic, pulling from live FastAPI endpoints, Binance WebSocket/REST streams, or the SQLite database. Never hardcode mock states into production components.

---

## 4. Repository Directory Map

```text
Autonomous Futures Bot/
├── .github/workflows/            # GitHub Actions CI (Automated test runner)
├── artifacts/
│   ├── paper_live/
│   │   ├── candidate_registry.json # Phase 295 paper-only registry (3 legacy candidates)
│   │   └── candidates/           # Candidate artifacts; not runtime admission evidence
│   └── research/
│       ├── phase310/             # Production telemetry, SQLite db, event logs
│       └── phase311/             # Execution drill logs and audit reports
├── frontend/                     # React 19 + TypeScript + Vite + Tailwind CSS + DaisyUI 5.7.42
│   ├── dist/                     # Compiled production bundle served by Nginx / FastAPI
│   └── src/
│       ├── App.tsx               # Primary layout, hash router & data hydration
│       ├── components/
│       │   ├── pair-detail-page.tsx  # Dedicated Pair Deep-Dive Terminal (#/pair/:symbol)
│       │   ├── evolution-page.tsx    # Strategy Evolution & Autopsy (#/evolution)
│       │   ├── executive-positions-page.tsx # Live Positions & Markets (#/positions)
│       │   ├── executive-trades-page.tsx    # Trade Log & Executions (#/trades)
│       │   ├── executive-safety-page.tsx    # Risk Controls & Solvency (#/safety)
│       │   └── mission-control/
│       │       ├── executive-dashboard.tsx  # Simplified Executive Overview (#/overview)
│       │       ├── pair-price-tickers-card.tsx # 12-Pair Matrix with Entry Badges
│       │       ├── pair-candlestick-chart.tsx  # TradingView Lightweight Charts + Overlays
│       │       ├── strategy-confluence-radar.tsx # Dual Scalper + ICT Confluence UI
│       │       ├── kpi-cards.tsx               # 4 KPI Cards (Balance, PnL, Exposure, Health)
│       │       ├── order-feed-table.tsx        # Recent Fills & Executions Table
│       │       └── types.ts                    # TypeScript domain interfaces
│       └── lib/
│           ├── navigation.ts     # Hash routing parser (supports #/pair/:symbol)
│           ├── pair-entry-status.ts # Pure evaluator: DUAL, ICT, SCALPER, FORMING, STANDBY
│           ├── use-ict-signals.ts   # Live polling hook for /api/v1/strategy/ict-signals
│           ├── api.ts            # REST API client
│           └── canary.ts         # Canary research telemetry adapters
├── src/autonomous_futures/       # Core Python Engine
│   ├── api/
│   │   ├── app.py                # FastAPI ASGI application & route mounts
│   │   ├── canary.py             # Canary endpoints (/api/v1/canary/...)
│   │   └── strategy_router.py    # ICT & Scalper API endpoints (/api/v1/strategy/...)
│   ├── execution/
│   │   ├── binance_gateway.py    # Binance Futures REST & WebSocket gateway
│   │   ├── continuous_trader.py  # 24/7 background trading daemon core
│   │   └── self_driving.py       # Order slicing & execution state machine
│   ├── strategy/
│   │   ├── macro_liquidity_scalper.py # 15m Liquidity Dip Scalper + BTC Trend Filter
│   │   └── ict_mmxm.py           # ICT Market Maker & 6-Step Twins Reversal Engine
│   └── feed/
│       ├── kline_sequencer.py    # Multi-timeframe kline sequencer (1m, 5m, 15m, 1h, 4h)
│       ├── auto_evolution.py     # Parameter mutation & OOS evaluation
│       └── strategy_mining.py    # Quantitative hypothesis generator
├── scripts/
│   ├── run_phase_310_real_autonomous_trading.py # Live/Testnet 24/7 daemon entry point
│   ├── run_testnet_execution_drill.py           # Non-disruptive execution drill CLI
│   └── run_telegram_notifier.py                 # Real-time Telegram alerting bot
└── tests/
    ├── unit/                     # Targeted unit tests
    └── adversarial/              # Adversarial stress & solvency challenge tests
```

---

## 5. Active Universe & Dual-Strategy Mechanics

### A. The 12 Perpetual Trading Pairs
The universe consists of 12 highly liquid Binance USDⓈ-M perpetual contracts:
1. `BTCUSDT` (Macro regime anchor)
2. `ETHUSDT`
3. `SOLUSDT`
4. `DOGEUSDT`
5. `BNBUSDT`
6. `XRPUSDT`
7. `SUIUSDT`
8. `AVAXUSDT`
9. `NEARUSDT`
10. `LINKUSDT`
11. `APTUSDT`
12. `ADAUSDT`

### B. Strategy 1: 15m Macro-Confluence Liquidity Scalper
- **Filter**: Bitcoin Macro Trend. Evaluates 1h and 4h EMA 50 vs EMA 200. Long entries are permitted only when `regime === 'BULLISH ALIGNED'`.
- **Trigger**:
  - Distance: Price $> 2.5\times$ ATR below the 20-period EMA.
  - Volume: Bar volume $> 2.2\times$ 20-period SMA.
  - RSI: 14-period RSI $< 26.0$ (oversold capitulation).
- **Execution**: Maker Limit Order at sweep price (0.02% maker fee). Stop Loss at $-1.2\times$ ATR, Take Profit at $+2.0\times$ ATR (Risk:Reward 1.66:1). Time stop decays after 8 bars (2 hours).

### C. Strategy 2: ICT Market Maker Model (MMXM) & Twins Reversal
Encapsulated in `src/autonomous_futures/strategy/ict_mmxm.py`. Evaluates the mechanical 6-step setup:
1. **Step 1 — HTF PDA Hit**: Price touches a 1h/4h Order Block (OB), Fair Value Gap (FVG/SIBI/BISI), Breaker Block, or Old High/Low.
2. **Step 2 — 5m CISD**: 5-minute Change in State of Delivery confirms displacement into the PDA.
3. **Step 3 — Twins FVG**: Two consecutive 1-minute Fair Value Gaps form inside the displacement leg.
4. **Step 4 — OTE Retracement**: Price retraces into the 62.0% – 79.0% Fibonacci Optimal Trade Entry zone (Sweet Spot: 70.5%).
5. **Step 5 — 1m CISD Invalidation**: 1-minute candle invalidates intermediate structure, confirming order flow transition.
6. **Step 6 — Ready / Execution**: Order parameters locked:
   - Stop Loss: Above/below 79% Fib or protected swing high/low.
   - TP 1: 2.0x Standard Deviation extension.
   - TP 2: 4.0x Standard Deviation extension (Terminus).

---

## 6. Frontend Architecture & Routing

The frontend is built with React 19, TypeScript, Tailwind CSS, and DaisyUI 5.7.42.

### A. Navigation & Hash Routes
Defined in `frontend/src/lib/navigation.ts`:
- `#/overview` or `/`: **Executive Overview** (Simplified: 4 KPIs, 12 Pair Tickers Card, Recent Orders Feed).
- `#/pair/:symbol`: **Dedicated Pair Terminal** (e.g. `#/pair/BNBUSDT` or `#/pair/SOLUSDT`). Displays live position, TradingView candlestick chart with overlays, dual confluence checklist, pair genome evolution, and filtered order history.
- `#/positions`: Detailed position & orderbook telemetry.
- `#/trades`: Full execution history & trade autopsies.
- `#/safety`: Circuit breakers, kill switches, and double-entry solvency proof.
- `#/evolution`: 5-Stage strategy evolution state machine & OOS qualification scorecards.
- `#/mining`, `#/stress`, etc.: Historical research canary tabs (Phases 250–309) collapsed inside the secondary Research Archive drawer.

### B. Dynamic Entry Status Evaluator
In `frontend/src/lib/pair-entry-status.ts`:
- **`🔥 DUAL ENTRY (POSITION)` / `🔥 DUAL ENTRY (SIGNAL)`**: Both 15m Scalper & ICT Step 6 ready.
- **`🎯 ICT ENTRY (POSITION)` / `🎯 ICT ENTRY (SIGNAL)`**: ICT Twins Step 6 ready or active ICT trade.
- **`⚡ SCALPER ENTRY (POSITION)` / `⚡ SCALPER ENTRY (SIGNAL)`**: 15m Dip criteria met or active Scalper trade.
- **`⏳ ICT M1 CISD (5/6)` / `⏳ ICT OTE FIB (4/6)`**: Sub-structure forming.
- **`STANDBY / SCANNING`**: Neutral monitoring state.

---

## 7. Key REST & WebSocket API Endpoints

The FastAPI backend serves both live market and internal strategy endpoints:

| Endpoint | Method | Purpose | Sample Response Keys |
|---|---|---|---|
| `/api/v1/market/prices` | GET | Live ticker & mark prices for all 12 pairs + BTC Macro Trend | `prices`, `btc_macro`, `timestamp_ms` |
| `/api/v1/market/klines` | GET | Candlestick OHLCV data for TradingView charts (`?symbol=SOLUSDT&interval=15m`) | Array of `[time, open, high, low, close, volume]` |
| `/api/v1/strategy/ict-signals` | GET | Real-time ICT MMXM Twins state & PD arrays across all 12 pairs | `signals.BNBUSDT.twins_state`, `signals.BNBUSDT.pd_arrays` |
| `/api/v1/execution/status` | GET | Truthful live account state: positions, exposure, recent orders, balance drift | `positions`, `aggregate_exposure_usdt`, `recent_orders`, `total_orders` |
| `/api/v1/canary/summary` | GET | Executive canary overview & system health | `verified`, `health`, `metrics` |
| `/api/v1/canary/evolution` | GET | Live 5-stage evolution progress & trade sample count | `status`, `completed_trades`, `active_stage` |
| `/ws/telemetry` | WS | Real-time Hawkes microstructure streaming & hazard alerts | `spectral_radius`, `jump_intensity`, `regime` |

---

## 8. Common Developer Workflows

### A. Running Targeted Tests (DO NOT RUN FULL SUITE)
```bash
# 1. Targeted Frontend Vitest Tests (Fast, < 1 second)
cd frontend
npm test -- src/lib/pair-entry-status.test.ts src/lib/navigation.test.ts src/components/__tests__/executive-dashboard.test.tsx src/components/__tests__/pair-detail-page.test.tsx

# 2. Targeted Backend Pytest Tests (Fast, < 2 seconds)
cd "C:\Users\thaqi\Projects\Autonomous Futures Bot"
.venv\Scripts\pytest tests/unit/test_phase_317_ict_signals_api.py -q
```

### B. Building Frontend
```bash
cd frontend
npm run build
# Expected: tsc -b && vite build exits with code 0 into dist/
```

### C. Deploying Frontend to Kainode VPS (Zero Downtime)
```powershell
# In PowerShell at project root:
cd "C:\Users\thaqi\Projects\Autonomous Futures Bot"
tar -czf dist.tar.gz -C frontend/dist .
scp -i C:\Users\thaqi\.ssh\kainode_ed25519_openssh -o StrictHostKeyChecking=no dist.tar.gz afbot@147.79.18.15:/tmp/dist.tar.gz
ssh -i C:\Users\thaqi\.ssh\kainode_ed25519_openssh -o StrictHostKeyChecking=no afbot@147.79.18.15 "rm -rf /opt/autonomous-futures-bot/frontend/dist/* && tar -xzf /tmp/dist.tar.gz -C /opt/autonomous-futures-bot/frontend/dist && rm -f /tmp/dist.tar.gz && systemctl --user restart autonomous-futures-web.service"
Remove-Item dist.tar.gz -Force
```

### D. Verifying VPS Services After Deployment
```bash
# Check trader daemon is untouched (Main PID must remain 87549)
ssh -i C:\Users\thaqi\.ssh\kainode_ed25519_openssh afbot@147.79.18.15 "systemctl --user status autonomous-futures-trader.service --no-pager"

# Check web service status
ssh -i C:\Users\thaqi\.ssh\kainode_ed25519_openssh afbot@147.79.18.15 "systemctl --user status autonomous-futures-web.service --no-pager"

# Verify live website HTTP 200
curl -I https://futures.semua.dev/
```

---

## 9. Archived Qualification and Runtime Snapshots (through 13 October 2026; superseded by Active Engineering Evidence above)

The static account, exposure, fill, and signal values previously recorded here are historical and are not current telemetry. The separate qualified runtime is not active, `deploy/qualification-admission.json` has no approved reports, and no current account snapshot should be inferred from this document.

The frozen ICT directional-fix replay is running locally against immutable inputs. BTC, ETH, SOL, DOGE, XRP, and BNB have completed and are rejected. The first four produced 97 trades, net PnL -6.6030977091096 USDT, and 94 trades exited solely on a post-fill one-minute close through the CISD/entry level. XRP produced 17 trades, net PnL -0.6541218700000 USDT, stress net PnL -2.5170041620000 USDT; BNB produced 17 trades, net PnL -1.300346340 USDT, stress net PnL -3.118868080 USDT. Both XRP and BNB passed only drawdown and closed-at-end gates. All six reports' implementation hashes match current source. At the 2026-10-13 16:11 MYT check, SUI had advanced through 2024-12-26 (checkpoint wallet 98.586497286 USDT) and AVAX through 2024-10-27 (wallet 99.53937380 USDT); both workers were active and four symbols remained queued. The batch had not produced `process-results.json`, so these are not final results. No active implementation-hash file or frozen policy changed during the run. The currently inspected 2024+ replay data is diagnostic feedback and must not be reused as an untouched holdout for further tuning.

An isolated untouched holdout was acquired on 2026-10-13 under `research/qualification-holdout-2026-08-2026-09/`: 48 official Binance USD-M monthly archives (1m klines and funding rates for all 12 active pairs, August and September 2026). Every archive SHA-256 was checked against its published checksum and recorded in `holdout-index.json`. Raw observations have not been used for tuning or qualification. This is reserved input only; higher-timeframe cache/context and a frozen-candidate evaluation have not yet been built.

The four finalized reports each bind seven implementation files whose current SHA-256 hashes match the report; all four record `decision=REJECTED` and `execution_authority=false`.

A trade-level audit of those four reports found that the 94 invalidation-only trades had a median hold of one minute (the longest was 132 minutes). The replay exits on the first post-fill one-minute close crossing the CISD/entry level, and the live causal exit guard uses the same rule. No replay/runtime exit-rule divergence was found; this is a weakness in the frozen candidate's observed outcomes, not authority to loosen the current run's exit rule. Any redesigned candidate requires fresh independent qualification evidence.

A diagnostic-only 5m counterfactual was run on those same 94 CISD-only trades using the original stop, targets, and time/window deadline after the actual 1m exit. It produced gross PnL of -0.912480 USDT versus -5.246770 USDT for those same trades under the immediate CISD exit; 64 later hit the stop, 10 reached both TP1 and TP2, and 20 ended at the time/window proxy (including partial TP1 exits). This improves gross results by 4.334290 USDT but remains negative before costs. It omits fees, slippage, funding, daily-loss and portfolio interactions, and uses only subsequent full 5m bars, so it is not evidence to relax the live exit or a qualification result. Reproduction is in `scripts/diagnose_runtime_ict_exit_counterfactual.py`; `artifacts/qualification/ict-cisd-exit-counterfactual-v2-20261013.json` is authoritative. The initial v1 output is superseded because it misclassified time deadlines between 5m closes as data-end proxies.

Replay performance analysis found that the ICT evaluator repeatedly checks each higher-timeframe PD array against up to 250 five-minute candles. The exact interval index now lives in `src/autonomous_futures/strategy/pd_array_touch_index.py`; `research/ict_touch_index.py` remains a compatibility re-export. Its five targeted tests pass, as do Ruff, formatting, and strict mypy. A real-data differential check matched brute force on 48 snapshots across all 12 pairs and 6,494 PD arrays. On one BTC snapshot (148 PD arrays and 250 five-minute candles), median query time was 0.442 ms indexed versus 1.839 ms brute force (4.2x for this lookup only). A BNB October 2025 profile across 10 consecutive one-minute snapshots found 153 PD arrays and 250 five-minute candles; the exact indexed query matched brute force and took 0.436 ms versus 2.281 ms (5.23x for this lookup only). An in-memory indexed evaluator was then compared against the original on one actual STEP_6_READY signal timestamp from each of BTC, DOGE, ETH, SOL, and XRP: all five complete setup states matched exactly, and median setup-call time improved 2.29x (about 5.1 ms to 2.2 ms). This is not a full replay speedup measurement. The index remains unwired while the frozen batch is live; after completion, integrate it only after full differential replay confirms identical setups and report metrics.

The 30-minute read-only Testnet market trace contains 34,338 trade arrivals across all 12 pairs. A decay-profile diagnostic at beta=7.5/s had no boundary-pinned baseline estimates and spectral radius 0.7447951376677655. Together with the earlier independent selection trace, this supports a hash-bound runtime model parameter only; the calibration explicitly grants neither qualification nor execution authority. The runtime and read-only probes now load this calibration artifact instead of relying on the estimator's beta=1/s fallback. A separate 30-minute live runtime validation on 2026-10-13 recorded 14,673 arrivals, zero sequence gaps, zero duplicates, 4,544 stale frames, beta=7.5/s, no boundary-pinned baselines, and rho=0.7486297286978606. Only BTCUSDT, SOLUSDT, and APTUSDT passed the final freshness guard; the report has `execution_authority=false` and does not qualify the live feed. The hash-bound report is `artifacts/qualification/runtime-microstructure/live-runtime-validation-20261013/persistent-feed-1791878260109068400.json` (SHA-256 `9a5089b3adbc06876ef03ed0c74217a86985bd425bb395a9a0fc3c48e979864b`).

The existing Testnet key is shared with the still-protected legacy writer. PID 87549 must remain untouched. No qualified runtime has been started or deployed, and no VPS writer handoff has been verified. At 2026-10-13 16:32 MYT, a fresh pinned read-only preflight confirmed the actual user-level unit active with PID 87549 and NRestarts=0; the system-level unit query was inactive, so only the user unit is authoritative. Host capacity was 6 CPUs, 10.5 GiB available memory, 0.36 load, with PID 87549 at 0.6% CPU and about 140 MiB RSS. A transient systemd quota probe succeeded. Two isolated archive fetch jobs initially ran under CPUQuota=100% each, CPUWeight=10, MemoryMax=1G, Nice=19, and idle I/O priority. Worker environments were cleared of inherited credentials. No production file, service, API key, or exchange-order state was changed.

### Isolated Kainode qualification result — 2026-10-13

After the user switched to an allowed network route, a fresh pinned SSH preflight confirmed the protected user-level trader service remained active at PID 87549 with NRestarts=0. The VPS reported 6 CPUs, about 10.9 GiB available memory, and low system load. Qualification ran only under `/home/afbot/qualification-worker/ict-link-2021-2023`; the worker used cleared environments with no `.env` files or exchange credentials. All compute was low priority: BTCUSDT and LINKUSDT cache builders each had CPUQuota=100% (one core), CPUWeight=10, MemoryMax=2G, Nice=19, and idle I/O; the single frozen-candidate evaluation used the same caps. The funding cache/archive tasks used lower CPU quotas. The production service was not controlled or modified.

The isolated worker acquired 78 official Binance 1m archives (39 each for BTCUSDT and LINKUSDT) and 37 LINKUSDT funding archives covering December 2020 through December 2023. Published archive checksums were verified. It built immutable 5m, 15m, and 1h BTC/LINK caches and a 3,378-row LINK funding cache. Legacy 12-column headerless kline CSVs required a compatibility update, applied only in `research/qualification-validation-2021-2023/worker-patches/official_market_data.py`; the active local ICT replay's shared parser was left untouched. The local cache files and manifests were copied into `research/immutable-data/link-holdout-cache-v2/` and `research/immutable-data/link-holdout-funding-v3/`.

The first evaluation attempt stopped at the exact coverage guard because the first January 2021 funding observation is timestamped 2 ms after midnight. It produced no qualification report. The official December 2020 funding archive was then added and verified, a new immutable funding cache was built, and the same frozen candidate was evaluated once on the disjoint 2021-01-01 through 2024-01-01 holdout. Candidate `macro-scalper-link-dist-3.5-tp-2.2-v1` retained distance threshold -3.5 and TP ATR multiplier 2.2. The five-window report records `decision=REJECTED`, `execution_authority=false`, 23 trades, net PnL -1.9616015911488 USDT, stressed net PnL -3.5131676881488 USDT, drawdown 4.2408282831488 USDT, and 2 profitable windows. Positive net edge, stress-positive, sample sufficiency, and window consistency gates failed. No parameters were tuned on the holdout. The report is `artifacts/qualification/runtime-scalper-link-holdout-2021-2023-v2/LINKUSDT-33f759853403e130.json` (file SHA-256 `e9808e5f2b05539c724bb4e22d623bc404113e299879dbcfd6bdc8651e5e0d3f`); its report hash, input manifests, parquet hashes, funding provenance, selection-report hashes, and implementation hashes were verified locally.

At the latest local process check, the frozen ICT directional-fix replay was still running on SUIUSDT and AVAXUSDT; `process-results.json` was not present. Do not change its shared implementation or kill its workers before completion. The VPS trader remained active at PID 87549 with NRestarts=0 after qualification.

Targeted validation of the integrated runtime and protective lifecycle passed on 2026-10-13: 122 tests across risk, final admission, fill recovery, protective execution, lifecycle coordination, runtime startup, Hawkes calibration, microstructure, live feed and causal scanning. Ruff and formatting checks passed for the changed integration files. This verifies local code behavior only, not exchange execution. The latest pinned read-only SSH check confirmed the legacy user service active at PID 87549; the admission manifest remains empty and no deployment, service, API-key, or exchange-order changes were made.

---

## 10. Active Qualification and Rollout Requirements

1. **Genuine strategy qualification:** Diagnose the repeated ICT invalidation exits on development data, freeze each resulting candidate, and qualify it against untouched prospective or otherwise independent evidence. Preserve every rejected report and all policy gates. Qualification is per strategy and pair; no report is approved by a diagnostic Hawkes profile.
2. **Runtime microstructure:** The selected beta is loaded from `artifacts/qualification/runtime-microstructure/runtime-hawkes-calibration-20261013.json`; its profile hashes, implementation hash, trace identities, 12-pair universe, and diagnostic-only authority are verified at startup. Continue measuring fresh live fits and retain the rho, baseline-boundary, event-age, clock, and sequence-gap vetoes.
3. **Protective lifecycle:** Continue validating authenticated fill reconciliation, partial-fill coverage, two-stage exits, cancellation races, restart recovery, daily-loss flattening, and owned-position closure through targeted tests and non-opening Testnet evidence. Do not equate unit tests with proven exchange behavior.
4. **Safe activation:** The report admission manifest remains empty. The same Testnet key is still available to the protected legacy process, and the user's instruction forbids stopping, restarting, killing, or signaling PID 87549. Do not start a second writer or claim deployment until an independently verified single-writer handoff can be established without violating that instruction.

## 11. VPS implementation and worker checkpoint — 2026-10-13 21:14 MYT

A read-only SSH check confirmed `autonomous-futures-trader.service` remains active at PID
87549 with `NRestarts=0`. Both credential-free qualification workers remain active: NEAR/LINK
through 2025-03-26 (checkpoint wallets 100.55555180 and 100.222819814 USDT), and APT/ADA
through 2025-02-24 (99.2038214800 and 98.7406577128300 USDT). Their output directories still
contain only frozen policy and process checkpoints; no final reports or source attestations
were present. The workers remain frozen at 0.5% per-trade risk, so these partial results
cannot qualify the selected 0.25% policy.

The remote trader process started at 2026-10-09 02:30:43 UTC. Its current on-disk source
files were modified on 2026-10-12, after that process start, and the VPS worktree is dirty
at commit `ac8a2dfec89536c8bc647067f4136a84c8ed2be3`, which differs from the local checkout.
Therefore current disk contents do not prove which Python implementation PID 87549 loaded
in memory; do not claim current live behavior from source inspection alone.

Read-only inspection of the current VPS source found that `continuous_trader.py` dispatches
strategy intentions to `SelfDrivingTradingEngine`; its `self_driving.py` fills them through
an internal `_execute_fill` ledger update. Neither file calls the gateway's exchange order
creation or cancellation methods. The on-disk path also contains hardcoded BTC price/EMA
fallbacks. This is strong evidence that the current disk implementation records simulated
fills as production telemetry, but it is not proof of PID 87549's loaded code because of the
post-start source edits. Resolve code provenance and distinguish simulated from exchange-
confirmed execution before treating daemon artifacts, alerts, or entries as live trading.
No VPS file, service, credential, account, or order was modified during these checks.

### Phase 310 evidence-semantics repair — 2026-10-13 21:22 MYT

The local Phase 310 verifier now reports artifact integrity separately from execution
authenticity; it no longer prints that “real autonomous trading” was verified. The synthetic
hardcoded-candle batch runner and its `--test-run` entry point were removed. Phase 310 engine
exports now state `execution_authority=false`, `total_exchange_confirmed_fills=0`, and an
explicit simulation/non-executable mode; their old cap metadata is scoped as legacy
simulation-only, and the summary status is `RESEARCH_SIMULATION_ONLY` with `verified=false`.
These changes affect local source only and have not been deployed to the VPS.

Validation was limited to `tests/unit/test_phase_310_vps_solvency.py` (12 passed), Ruff,
formatting, and strict mypy on the two modified source files. The existing test that read the
live-mutated workspace Phase 310 bundle was replaced with a missing-bundle check, so tests no
longer depend on artifacts that an active daemon may rewrite. No full-suite test was run.

## 12. Current implementation and qualification checkpoint — 2026-10-13 22:03 MYT

The user reconfirmed that per-trade risk remains **0.5% of actual exchange account equity**.
This supersedes earlier 0.25% references in the chronological history above. The runtime
planner, qualification domain, and frozen replay policies already bind 0.5%; no code or
worker policy change was needed for this confirmation.

A read-only pinned SSH check confirmed the protected autonomous-futures-trader.service
remains active at PID 87549 with NRestarts=0. Both credential-free replay services also
remain active with NRestarts=0 (PIDs 639755 and 645096). Their latest JSONL checkpoints
are NEAR through 2025-11-21 (wallet 99.69621800 USDT), LINK through 2025-10-22
(99.712660616 USDT), APT through 2025-10-22 (100.79284200000000 USDT), and ADA through
2025-09-22 (98.2635464728300 USDT). These are progress checkpoints only; no final reports
were observed. No service, process, credential, account setting, or exchange order was
changed.

The ICT engine now uses strategy/pd_array_touch_index.py for the exact PDA/candle overlap
query instead of scanning up to 250 candles separately for every PDA. Differential checks
on real immutable data covered 48 snapshots across all 12 pairs and 9,371 PD arrays; indexed
and brute-force results matched exactly. Median lookup time was 0.537 ms indexed versus
2.828 ms brute force (5.27x for this lookup only, not a claim of whole-replay speedup).
The strategy and qualification report now bind the index helper's source hash, and receipt
verification rejects an ICT report that omits that dependency. Earlier reports and the
currently running remote workers were frozen before this source-manifest change; even if
their behavior is equivalent, their evidence does not bind the current implementation and
must not be admitted. After those workers finish, run fresh qualification against the
current source hash before considering any admission.

Focused validation after integration: 67 targeted unit tests passed; Ruff, formatting, and
strict mypy checks passed for the touched implementation and receipt files. No full-suite
test was run. The admission manifest remains empty; nothing was deployed, and PID 87549 was
not signaled or controlled.

## 13. Daily-risk transfer accounting and source-binding repair — 2026-10-13 22:16 MYT

A risk audit found that the daily-loss tracker compared current equity directly to the day-start
snapshot but did not adjust for later authenticated transfers. This could let a deposit mask
trading losses or count a withdrawal as a trading loss. The local evidence pipeline now treats
USDT TRANSFER income as a separate basis adjustment, validates unique transaction IDs and
timestamps, and includes only flows after the captured day-start equity. The wallet identity
now reconciles starting equity plus trading income plus external basis adjustments; equity
continues to reconcile as wallet balance plus unrealized PnL. Unclassified income types,
non-USDT income, duplicate flow identities, and a transfer timestamp equal to the baseline
timestamp fail closed. The 5% cutoff remains anchored to actual exchange equity captured at
UTC day start.

Binance's official [USDⓈ-M Get Income History reference](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account)
documents the /fapi/v1/income rows, TRANSFER type, amount, asset, timestamp, and transaction
identity. Macro Scalper qualification now hashes daily_risk.py, and historical receipt
verification requires that dependency for both strategy families. Existing reports that do
not bind the current daily-risk implementation must not be admitted; the current admission
manifest remains empty.

Focused validation passed: 85 tests across daily-risk, account evidence, runtime, qualification
receipts/domain, lifecycle, and causal scanning; Ruff, formatting, and strict mypy passed for
the touched source. No full-suite test was run.

At the 22:16 MYT read-only VPS check, autonomous-futures-trader.service remained ACTIVE,
SubState=running, MainPID 87549, NRestarts=0. Both credential-free replay services remained
active with NRestarts=0 and CPUQuota=200% each (two cores per unit, four total). Latest
progress: NEAR through 2026-01-20 (wallet 99.69621800 USDT), LINK through 2025-12-21
(99.712660616 USDT), APT through 2025-12-21 (100.71009336000000 USDT), and ADA through
2025-11-21 (98.2635464728300 USDT). Their output folders contained only frozen policy and
process checkpoints; no final reports were present. No VPS service, credential, account
setting, or exchange order was changed; PID 87549 was not signaled or controlled. The active
worker source predates the daily-risk and source-binding edits, so current implementation
requalification is required after those jobs finish.

## 14. ICT development outcome diagnosis — 2026-10-13 22:19 MYT

An exploratory aggregation of the eight completed current-code ICT pair reports
(BTC, ETH, SOL, DOGE, BNB, XRP, SUI, AVAX) found 189 trades through 2026-08-01,
with net PnL -12.3067081659896 USDT, gross PnL -5.27634 USDT, and stressed net PnL
-31.1613179459896 USDT. 182 trades exited on CISD invalidation; 105 closed within
one minute. Both sides lost: 87 BUY trades net -7.06435 USDT and 102 SELL trades
net -5.242358 USDT.

Only UTC hours 13 and 22 had positive aggregate net PnL, from three and four trades
respectively. That sample is too small to support a session filter; no pair-side or
time-of-day filter is qualified. This diagnostic reads existing development reports
only and does not use the reserved August–September 2026 holdout. It grants no
qualification or execution authority. The next strategy study must test a causal,
executable alternate entry/retest model on development data and retain full fee,
slippage, funding, daily-loss, and per-trade risk accounting before any candidate is
frozen for holdout evaluation.

## 15. Per-trade risk reconfirmation — 2026-10-13 22:24 MYT

The user reconfirmed that per-trade risk remains **0.5% of actual exchange account equity**.
This matches the runtime planner, qualification domain, and frozen worker policies; no
risk-setting code or worker policy change is needed. The diagnostic artifact
`artifacts/qualification/diagnostics/ict-confirmation-displacement-20261013.json` still
contains an obsolete limitation sentence referring to a selected 0.25% live policy. Its
research sizing used 0.5%; the sentence is superseded by this section. The artifact remains
unchanged so its recorded hash and historical evidence stay intact. The diagnostic remains
non-qualifying and negative across tested thresholds with sufficient sample size.

## 16. Current-source reclaim-retest checkpoint — 2026-10-13 22:50 MYT

The user reaffirmed **0.5% of actual exchange account equity per trade**. The planner,
qualification policy, and active local replay policies already agree; no risk-setting or
worker change was needed.

Three local current-source `reclaim_retest` development runs remain active. Latest
checkpoints: SUI through 2025-03-26, wallet 98.789342616 USDT; DOGE through 2025-03-26,
wallet 100.67500640977040 USDT; SOL through 2025-02-24, wallet 100.4873627360 USDT.
Each output folder contains only `frozen-policy.json`; no final qualification report exists.
These runs use the development period and have no execution authority. The Aug-Sep 2026
holdout remains unused. Do not change the hash-bound qualification implementation until
these processes finish.

Pinned, read-only SSH at 22:50 MYT confirmed `autonomous-futures-trader.service` active at
PID 87549 with NRestarts=0. Both existing credential-free VPS replay units remained active
at PIDs 639755 and 645096 with NRestarts=0. No VPS service, credential, account setting, or
exchange order was changed; PID 87549 was not signaled or controlled.

## 17. Testnet private-stream connectivity probe — 2026-10-13 22:55 MYT

The user directed us to reuse the existing Testnet API key. A bounded probe using that key
connected to the authenticated user-data stream for 20 seconds, completed one initial REST
account reconciliation, and observed zero private events with no reported error. It
recorded only event-type counts and status; temporary account evidence was removed with
its temporary directory. The diagnostic is `scripts/probe_runtime_user_stream.py`.

This verifies Testnet private-stream connectivity and initial REST recovery only. No
private event arrived, so live event ordering, event-triggered recovery, and protective
handling remain unverified. The diagnostic has `execution_authority=false`; it did not
start a trading runtime or change the protected service. The probe script passes Ruff,
formatting, and strict mypy; the targeted stream/runtime unit tests pass (14). No full suite
was run. PID 87549 remains protected.

## 18. ICT live-entry integration gate — 2026-10-13 22:58 MYT

Code review confirmed an execution-model mismatch: `CausalScanner` converts
`setup.step_6_ready` directly into `ict_plan`, whose entry is the M1 CISD price. The current
development candidate uses `reclaim_retest`: it requires a completed one-minute
touch-and-reclaim candle, then a distinct later trade-through before a maker fill. The
live scanner has no persistent state for those stages, so a positive research report in
this mode must not be admitted or routed to execution until the matching stateful live
entry flow is implemented and tested.

The deployment admission manifest is still empty, and `run_qualified_runtime.py` blocks
startup while the legacy writer is active. Thus neither the research candidate nor the
new runtime can activate under current evidence/state. The protected PID 87549 remains
untouched; finish the current hash-bound replays before changing qualification source.

## 19. Reclaim-retest screen results — 2026-10-13 23:02 MYT

The first three current-source development reports are hash-valid and source-attested, but
all are **REJECTED** with `execution_authority=false`:

- SUI: 21 trades, net -2.026136880 USDT, stressed net -3.861931265 USDT, zero profitable
  windows; samples, net edge, stress, profit factor, and window gates fail. Source
  attestation covers 47 files.
- DOGE: 12 trades, net +0.182333902 USDT, stressed net -0.830602238 USDT, one profitable
  window; samples, stress, and window gates fail. Source attestation covers 51 files.
- SOL: 9 trades, net +0.235968916 USDT, stressed net -0.825465173 USDT, one profitable
  window; samples, stress, and window gates fail. Source attestation covers 51 files.

The frozen policy uses 0.5% per-trade risk, 5% daily loss, five windows, and a 30-trade
minimum. The remaining-nine batch is active with a four-worker cap, explicit symbol
inclusion, and `reclaim_retest` propagation through the repaired universe runner. Queued
symbols start as slots free. Once complete, these will finish the 12-pair development
screen without using the reserved holdout. No individual result is admissible, and no
portfolio-level qualification has been established.

The universe runner now forwards the frozen ICT entry mode to each child process. Its
targeted unit file passes (9 tests); Ruff, formatting, and strict mypy pass. No full test
suite was run.

## 20. Reclaim-retest full-universe progress — 2026-10-13 23:18 MYT

Seven of the 12 current-source per-pair development reports are now complete, hash-valid,
and source-attested. All seven are **REJECTED** with `execution_authority=false`; each is
below the 30-trade minimum and has negative stressed net PnL:

- SUI: 21 trades, net -2.026136880 USDT, stressed -3.861931265 USDT.
- DOGE: 12 trades, net +0.182333902 USDT, stressed -0.830602238 USDT.
- SOL: 9 trades, net +0.235968916 USDT, stressed -0.825465173 USDT.
- XRP: 6 trades, net -0.463924148 USDT, stressed -1.157791011 USDT.
- BNB: 9 trades, net -0.658401720 USDT, stressed -1.648531990 USDT.
- BTC: 6 trades, net -0.557835198 USDT, stressed -1.239640806 USDT.
- ETH: 11 trades, net -0.740839110 USDT, stressed -1.733254130 USDT.

The remaining AVAX, NEAR, LINK, APT, and ADA reports are still in the four-worker batch
(four running, one queued at this checkpoint). The 0.5% trade-risk and 5% daily-loss
policy is unchanged, and reserved Aug-Sep 2026 data remains untouched. No candidate is
admissible; these independent per-pair results do not establish shared-wallet portfolio
qualification.

## 21. Stateful ICT reclaim-entry integration — 2026-10-13 23:40 MYT

The live scanner previously rejected current ICT reports because it omitted the report's
`entry_mode` from its expected configuration, and it had no persistent state for the
`reclaim_retest` sequence. `IctReclaimEntryStore` now persists each pair's plan, report
identity, expiry, candle cursor, and one-time dispatch state. It uses the same completed
M1 close-reclaim predicate as the research implementation, then dispatches the maker
intention only after that candle closes. The actual later fill remains exchange-owned.

The intention carries its verified report hash and causal readiness time through
`RuntimeSession` to `EntryAdmission`. Admission re-verifies the reviewed report pin, binds
the staged entry to `reclaim_retest`, checks readiness freshness and the original
five-minute expiry, and refuses to dispatch if the report or policy differs. Qualification
receipt verification is cached during scans for runtime efficiency; it is independently
repeated at admission before exchange writes. Corrupt or gapped persisted state fails
closed. Targeted tests pass (26); Ruff, formatting, and strict mypy pass. No full suite was
run.

The current reclaim-retest batch is active for ADA only; the newly completed AVAX, NEAR,
LINK and APT reports are source-attested and rejected. This code change touches neither
hash-bound research implementation files nor running qualification inputs. Per-trade risk
remains 0.5% of actual account equity. No exchange order, VPS service, credential or
account setting was changed; PID 87549 remains protected. Admission is empty and runtime
activation remains gated on a qualified report, shared-wallet evidence, live private-event
validation and a safe single-writer handoff.

## 22. Reclaim-retest 12-pair screen completed — 2026-10-13 23:45 MYT

The frozen current-source `reclaim_retest` screen completed for all 12 active-universe
pairs using 0.5% per-trade risk, 5% UTC-day-start-equity loss limit, five windows, and a
30-trade minimum. All 12 reports are **REJECTED**, all report hashes are source-attested,
and every attestation records `execution_authority=false`. Each pair generated fewer than
30 trades (range 5–21); only DOGE and SOL had positive unstressed net PnL, and all 12 had
negative stressed net PnL and fewer than three profitable windows. The report set contains
112 trades total. Across the independent $100 research runs, the arithmetic sum is
-7.33884668110960 USDT net and -17.98222028010960 USDT stressed; these are diagnostic
totals only, not a shared-wallet or portfolio result.

ADA's final report is `artifacts/qualification/runtime-ict-reclaim-retest-dev-remaining-20261013/ADAUSDT-6d106b234a8fd25a.json` and its source attestation is
`ADAUSDT-source-attestation-b4292adbbf135b77.json`. It records 12 trades, -1.194076300
USDT net, -2.108607450 USDT stressed, and zero profitable windows. The nine reports in
the remaining-pair batch all exited successfully; the three earlier SUI, DOGE and SOL
reports are also hash-valid and attested. No candidate passes qualification, the
deployment admission list remains empty, and no live order or exchange configuration was
changed. The 0.5% risk decision is retained. Further research must use development data
and preserve the reserved holdout; activation still requires portfolio evidence, live
private-event validation, and a safe single-writer handoff.

## 23. Expected stale setup handling in live scanner — 2026-10-13 23:49 MYT

The 12-pair reports recorded 1,202,082 repeated `ict_plan` rejections for confirmations
older than the immediately closed minute, across 1,252,537 minute-by-minute `STEP_6_READY`
observations. These are repeated observations of a persistent setup state, not 1.2 million
independent signals. The strategy intentionally pins the initial confirmation time so an
old setup cannot refresh its entry TTL or be re-armed indefinitely.

Before this repair, `CausalScanner` let expected `IneligibleTrade` outcomes escape to the
runtime supervisor, which marked routine stale setups and unfillable risk/minimum-size
plans as scan errors. ICT and Macro planning now treat only `IneligibleTrade` as a normal
no-intention result; configuration, feed, account and other unexpected errors still
surface. A targeted stale-confirmation scanner test passes (4 tests in the file); Ruff,
formatting and strict mypy pass. No full suite was run. Hash-bound strategy and research
files were not modified, so the 12 rejected source-attested reports remain unchanged.
No VPS service, credentials, account settings or orders were touched.

## 24. Reclaim signal-candle displacement diagnostic — 2026-10-13 23:55 MYT

The 112 modeled trades in the rejected current-source `reclaim_retest` reports produced
109 `CISD_INVALIDATION` exit events; the median exit event was 60 seconds after its
modeled fill. A post-hoc screen measured favorable close-to-entry displacement on each
trade's exact one-minute signal candle, verified against official archived bars and report
source attestations. It reads the frozen risk percentage and sidecar SHA dynamically;
all four diagnostic outputs bind to 0.5% risk and explicitly grant no qualification or
execution authority. The reserved Aug 1, 2026 holdout was excluded.

No tested displacement threshold made the aggregate of the already-filled trades positive.
At 0.30 ATR, the screen retained 53 trades with -2.37232381510960 USDT net and
-7.43328203810960 USDT stressed; at 1.00 ATR, only six remained, with -0.498272308 USDT
net and -1.002893626 USDT stressed. This is only a post-hoc screen of existing fills, not
a candidate replay. It does not justify threshold selection or weakening exits; the next
strategy experiment must change a causal, pre-entry hypothesis and pass a full chronological
replay before any holdout evaluation.

## 25. Protective response identity verification — 2026-10-14 00:04 MYT

The local `ProtectiveExecutor` previously accepted a matching symbol, client ID, side,
reduce-only flag and quantity without binding the exchange-acknowledged order type or
protective trigger/limit price back to the persisted intent. It now checks those values;
conditional algo responses use the parent `orderType` and `triggerPrice`, including after
triggering when the exchange returns a child order. Missing or mismatched values fail
closed. The existing triggered-child fixture now includes the parent fields required by
that exchange response contract.

Targeted protective lifecycle, executor, coordinator and fill-recovery tests pass (43
tests); Ruff, formatting and strict mypy pass. No full suite or live order was run. This
validates local reconciliation logic only; private-stream event behavior and a live
exchange protective-order lifecycle remain unproven. No VPS service, credential, account
setting or exchange order was touched.

## 26. Current-source public Testnet feed probe — 2026-10-14 00:32 MYT

The 30-minute public Testnet probe completed with exit code 0. Its report and raw-trace
SHA-256 match, and all six implementation hashes recorded by the run match the current
probe/feed/clock/Hawkes source files. At completion both feed channels were connected;
the run recorded 34,352 aggregate trades, 47,478 depth updates, 428 stale-frame
observations, zero sequence gaps and zero duplicates. The measured Hawkes spectral
radius was 0.6463075 with no lower-bound baseline symbols and no feed or fit error. The
report has no qualification or execution authority.

At the final snapshot, only BTCUSDT and SOLUSDT passed the current 500 ms trade/depth
freshness gate; the other ten were rejected as stale. A raw-trace diagnostic sampled
both timestamps every 100 ms over 1,798,292 ms, using the maximum observed 72 ms clock
uncertainty conservatively. With the current 500 ms maximum age, pair availability ranged
from 22.26% to 41.18% of sampled time. A 2,000 ms diagnostic threshold raised this to
83.92%–97.53%. These are feed-availability sensitivities, not strategy-performance
evidence; the 500 ms production gate was not changed. Any wider freshness policy needs a
causal replay and another current-source host validation first.

The run report's legacy `source` field records the aggTrade URL only. Its hash-bound
`LiveMarketFeed` source also opened the separate public depth URL, and the raw trace
contains the 47,478 depth updates; future report metadata should name both endpoints.
The probe ran locally against public Testnet, made no authenticated calls or orders, and
does not verify the VPS route. PID 87549 and its service remain untouched.

## 27. Telemetry provenance, feed route attribution, and current qualification — 2026-10-14 00:56 MYT

The Evolution dashboard no longer invents active-daemon state, generated live events,
heartbeat, ledger/zero-drift claims, candidate counts, solvency, cash, or an obsolete $5
child-order cap when source telemetry is absent. It presents unavailable evidence as
unavailable and only labels the daemon active when an explicit live field says so. The
focused component test passes (13 tests), TypeScript project check passes, and targeted
Oxlint exits successfully with one existing `Date.now()`-during-render warning.

The persistent public feed probe now records both independent WebSocket routes under
`sources.market` and `sources.public_depth`; the historical `source` market-route field
remains for compatibility. The regression test passes; Ruff, formatting and strict mypy
pass for the changed probe. Prior probe artifacts remain immutable and still document
the omitted depth URL; only future run reports include the complete route inventory.

A current-source 12-pair ICT `limit_touch` development qualification is running locally
from 2024-01-01 through the reserved-holdout boundary at 2026-08-01 00:00 UTC, using the
frozen 0.5% per-trade risk and four local workers. At this observation the four pair
processes are still consuming CPU and no pair report has completed. No report has been
qualified or admitted; the Aug-Sep 2026 holdout remains untouched. The earlier run using
global Python failed before replay because `pydantic` was unavailable; that output is
preserved separately and the active run uses the repository virtual environment. No
VPS service, key, account setting or exchange order was changed; PID 87549 was not
controlled.

## 28. `limit_touch` qualification interim results — 2026-10-14 00:57 MYT

Four of the 12 current-source development replays have completed and passed source-index
attestation. All four are **REJECTED**, with `execution_authority=false`: BTCUSDT had 10
trades, net -0.90222265000000 USDT, stressed net -2.07246230000000 USDT, and zero
profitable windows; ETHUSDT had 25 trades, net -1.938910714 USDT, stressed net
-4.474138908 USDT, and zero profitable windows; SOLUSDT had 30 trades, net
-2.07345854488000 USDT, stressed net -5.34929594888000 USDT, and one profitable window;
DOGEUSDT had 32 trades, net -1.68850580022960 USDT, stressed net -4.44987896722960
USDT, and one profitable window. Each report fails net edge, stress and window gates;
BTC and ETH also fail the 30-trade minimum. These are independent $100 modeled replays,
not a shared-wallet result. Other universe pairs remain in the same four-worker batch.

No candidate is qualified or admitted. Risk remains 0.5% per trade, the daily cutoff
remains 5%, and the Aug-Sep 2026 holdout remains reserved.

## 29. Read-only VPS worker and protected-daemon checkpoint — 2026-10-14 01:00 MYT

A fresh read-only SSH check confirmed `autonomous-futures-trader.service` is active and
running with MainPID 87549 and NRestarts=0. The PID was not signaled or controlled. The
six-vCPU host has about 9.4 GiB memory available. The already-running credential-free
APTUSDT and ADAUSDT replay workers each consume about one core; their latest checkpoint
advanced through `through_ms=1755907200000`. They remain on their older frozen
`directional_fix` source and are separate from the current local `limit_touch` batch.
No worker or service was started, stopped, or changed in this checkpoint.

## 30. Evolution clock and cycle telemetry follow-up — 2026-10-14 01:03 MYT

The Evolution page's render-time clock warning is removed. Current time now begins only
after the browser timer fires, so server rendering shows `Unavailable` instead of an
invented epoch timestamp. The cycle card displays only runtime-reported seconds, formatted
as minutes and seconds; the fixed 15-second client countdown and inferred progress bar
were removed. The focused test covers a telemetry value of 90 seconds; all 13 component
tests pass, TypeScript project check passes, and targeted Oxlint is clean.

## 31. Authenticated-stream to protective-cycle regression — 2026-10-14 01:05 MYT

Added a focused RuntimeSession integration test that sends a genuine-shaped
`MARGIN_CALL` payload through the authenticated stream decoder and the callback installed
by RuntimeSession. It verifies the event blocks entry, sets the forced-flatten reason,
and causes the next coordinator cycle to request external-risk protection; after the
stream disconnects, the event gap remains set so entry cannot resume. All 11 targeted
RuntimeSession tests pass; Ruff and formatting pass. This uses a mocked transport and
account snapshot; live exchange event/protective-order behavior remains unverified.

## 32. Eight-pair `limit_touch` interim results — 2026-10-14 01:13 MYT

The current-source, frozen-policy ICT replay has completed eight of 12 symbols. The new
AVAXUSDT report is **REJECTED** (25 trades, net -1.649098078880 USDT, stressed
-4.109609678880 USDT, zero profitable windows); BNBUSDT is **REJECTED** (17, net
-1.300346340, stressed -3.118868080, zero windows); SUIUSDT is **REJECTED** (33, net
-2.100044168000000, stressed -5.070059901000000, zero windows); and XRPUSDT is
**REJECTED** (17, net -0.6541218700000, stressed -2.5170041620000, one profitable
window). Across all eight completed pairs, every report fails net-edge and stressed-net
gates; all eight source attestations and independent Decimal metric/gate/window checks
pass. The four remaining local jobs are LINK, NEAR, APT and ADA. No candidate is admitted.

## 33. Kainode public microstructure probe started — 2026-10-14 01:13 MYT

An isolated source package was copied to
`/home/afbot/qualification-worker/runtime-microstructure-probe-20261014`; archive SHA-256
is `3300250b73d6e377402d13aead8fd06a5b68ec97f62bc4df765b12f9bc51b556`. It contains
source, the diagnostic calibration and its two profiles only; no credential files. The
remote calibration loader verified beta 7.5, all 12 symbols, and calibration digest
`264b161b12a88a53017069ff1a80af29f3a7dc47cb92b9f1f8291bca99d15907`. A 30-minute,
public Testnet probe is active as transient user unit
`afb-microstructure-probe-20261014-0108.service` (MainPID 812622, CPUQuota=100%, Nice=19,
MemoryMax=1G, RuntimeMaxSec=1860), with an empty process environment. It calls only public
market/depth streams and server time. The raw trace is receiving frames; no final
measurement exists yet. The protected trader remains MainPID 87549, active, NRestarts=0;
it was not controlled. Existing APT/ADA credential-free qualification workers remain
separate and active.

## 34. Eight-pair exit-reason diagnostic — 2026-10-14 01:14 MYT

Across the eight completed independent $100 ICT `limit_touch` reports, 189 modeled trades
closed: 185 by `CISD_INVALIDATION`, with aggregate diagnostic net -15.475896573760000
USDT and stressed net -33.899216797760000 USDT; three `TIME_OR_WINDOW` exits and one
`TP2` summed to +3.16918840777040 net and +2.73789885177040 stressed. These are sums of
separate per-symbol research accounts, not portfolio performance. This diagnostic points
the next development question toward entry quality; it does not support weakening the
invalidation exit. Median modeled hold time for the invalidations is 60 seconds. No filter
was selected or tuned from this summary.

## 35. Legacy kline schema repair and live worker checkpoint — 2026-10-14 01:21 MYT

Read-only Kainode journal inspection found two failed October 13 BTC/LINK official-cache
builds: the archived 2020 BTC kline CSV has 12 data columns but no header, while the parser
accepted only headered CSV. The local parser now recognizes both 12-column forms and
retains checksum, Decimal, timestamp, continuity, and candle checks. The headerless
regression plus the three existing focused tests pass; Ruff and formatting checks pass.
The fixed parser validates the real headerless Kainode BTCUSDT 2020-10 archive and the
real local headered BTCUSDT 2023-01 archive (44,640 rows each). The 2020 archive and
manifest were copied through pinned read-only SSH to a temporary local directory, parsed,
then removed. The old Kainode cache units were not restarted or changed.

At 01:21 MYT, the frozen local ICT `limit_touch` batch remains 8/12 complete; all eight
reports are source-attested and rejected by net-edge/stressed-net gates. LINK, NEAR, APT
and ADA remain active. Frozen per-trade risk remains 0.5% and daily loss remains 5%; no
policy or running batch changed. A pinned read-only VPS check confirmed the production
trader active at PID 87549 with NRestarts=0, the separate APT/ADA credential-free
qualification unit active, and the public microstructure probe active at PID 812622 with
about 9 minutes elapsed and a 13.7 MB trace. VPS load was 2.31 across six CPUs with 9.3
GiB available memory. The historical BTC/LINK cache jobs remain failed pending a separate
evidence-based decision; no live order or production service action occurred.

## 36. Qualification replay fingerprint incident — 2026-10-14 01:25 MYT

After the 01:21 checkpoint, NEARUSDT exited with `Qualification implementation changed
during replay`: I edited the official-market-data parser while the hash-attested batch was
still running. This is a valid fail-closed rejection; NEAR has no admissible report. The
eight reports completed before that edit retain their data-source attestations and
rejected decisions, but their implementation hashes bind the pre-fix parser. The runtime
receipt verifier therefore will not accept them as current-source admission evidence;
they are diagnostic results only. LINK, APT and ADA were still running at 01:25 and may hit
the same guard. Keep the source tree unchanged until they end, then rerun failed symbols
into a fresh output directory. Do not treat partial logs as qualification evidence. Risk
remains 0.5% per trade and daily loss 5%. The pinned VPS check still showed production
PID 87549 active, NRestarts=0; no VPS service or exchange order was touched.

## 37. Stable-source retries and microstructure probe results — 2026-10-14 01:47 MYT

After the original batch ended, LINK, NEAR, APT and ADA were rerun from the unchanged
current source into `artifacts/qualification/runtime-ict-limit-touch-stable-source-20261014`.
All four completed with exit code 0; each report's implementation hashes match current
files, its data inputs pass source-index verification, its report hash and Decimal trade,
stress, window and gate reconciliation pass, and an input-source attestation is saved
beside it. At frozen 0.5% per-trade risk and 5% daily loss, all four are **REJECTED**:
LINK (25 trades, net -0.625323328 USDT, stressed -3.362545416, one profitable window),
NEAR (17, -0.58929320, -1.95476240, one), APT (23, -0.40196090800000,
-2.69677139300000, one), and ADA (28, -1.8254403871700, -4.0710501371700, zero).
All four fail net-edge, stressed-net, minimum-sample, profit-factor and profitable-window
gates. The eight completed before the parser fix remain rejected historical diagnostics;
their implementation hashes bind the prior parser and cannot be admitted against current
source. No candidate qualified, so no deployment admission was added.

The 30-minute public Testnet microstructure probe completed normally (1800 seconds,
MainPID 0 afterward, NRestarts=0, exit status 0). Its report and raw trace are preserved
at `artifacts/qualification/runtime-microstructure-probe-20261014-final/`; report SHA-256
is `4b5f9f428eb4779ef6566b10a158d75a8676f9dea34ea6fdf07289863995a0c0` and trace SHA-256
is `e9e27cd69e434e8f8316b7c071523e1c6c24aa7328c96ecebe047b61d9256255`. All six probe
implementation hashes and the calibration digest match local files. The stream stayed
connected with 34,526 trade arrivals, 46,088 depth frames, zero sequence gaps, zero
duplicates, 13 stale frames, no fit error, beta 7.5/s, and subcritical spectral radius
0.6996643786. At the final snapshot the 500 ms evidence gate accepted DOGE, BNB, SUI and
AVAX; the other eight pairs were stale. Keep the gate unchanged pending repeated-window
evidence; this single capture grants no execution authority.

Fresh pinned status at 01:47 MYT confirms production trader PID 87549 active with
NRestarts=0. The public probe unit is inactive after successful completion. The separate
credential-free APT/ADA qualification worker remains active, using about two VPS cores;
the six-core host has 9.4 GiB available. No production service, key, or order was changed.

## 38. Confirmation-displacement screen and path repair — 2026-10-14 01:54 MYT

The development-only displacement diagnostic failed when `--minute-root` was a relative
path: it parsed verified archives, then attempted to relativize a relative archive path
against the absolute repository root. The diagnostic now expands and resolves its input
root before attesting archives. The focused regression builds a checksummed official-format
ZIP with a valid 12-column kline row and runs it through the real archive parser. The
targeted test passes (1 test), and Ruff check/format pass for both changed files.

Ran the diagnostic against the four current-source, source-attested `limit_touch` reports
for LINK, NEAR, APT and ADA. It screens their existing 93 filled trades against the exact
1-minute signal-candle close-to-entry displacement divided by trailing 14-bar ATR, using
verified official archives and keeping the 2026-08-01 UTC holdout reserved. At frozen
0.5% per-trade risk, the unfiltered set totals -3.44201782317 USDT net and -12.08512934617
under stress. A 0.5 ATR screen retains 27 trades and still loses -0.94442052117 net and
-3.37822569017 stressed. A 1.0 ATR screen shows +0.746503794 net / +0.291928213 stressed,
but only six trades (four early-window trades net +1.17184865; two later-window trades net
-0.425344856). NEAR's 0.5 ATR subset is positive on only five trades; the other three
symbols' subsets remain negative. This is a post-hoc filled-trade screen, not a causal
replay, and the sparse positive subsets fail sample requirements. It does not establish a
candidate, authorize tuning, or grant execution authority.

Diagnostic source SHA-256 is
`c0cca485fde717e8385cbe55c27f7de99acf3aa30a07616e45bf2dc39fab7a1f`; output is
`artifacts/qualification/diagnostics/ict-confirmation-displacement-limit-touch-stable-20261014.json`
(file SHA-256 `60b3538ba2aca4720ab2b792643ad796cd7a3a13a0c4296a5b02af870f8914d3`,
diagnostic hash `0a18a716e6be564705d9036fca49ed4dda24fc07c5564c7f33ae841715ce1a6f`).

Fresh pinned read-only VPS checks at 01:54 MYT confirm production PID 87549 active with
NRestarts=0. The separate credential-free qualification unit is active with MainPID 639755;
APT and ADA child workers (PIDs 744029 and 747836) each use about one core. These workers
and the production daemon were left untouched. No API key, account state, or exchange
order changed.

## 39. Paper candidate registry integrity and repeated feed capture — 2026-10-14 02:00 MYT

The working-tree `artifacts/paper_live/candidate_registry.json` had been replaced with a
12-symbol placeholder registry. Four entries used non-hex `candidate_artifact_hash` strings,
and the registry parser rejected the whole file; the focused Phase 295 manifest tests
failed 4 cases. The exact invalid bytes were preserved at
`artifacts/research/phase317/candidate_registry-invalid-placeholder-20261014.json`
(SHA-256 `e4bcb0810b248b071c9cd9b303973a4b7c6d49db904336f834dfc96fce9e15d1`). The active
file was restored to the verified repository registry: three Phase 295 paper-only legacy
candidates (BTC/ETH/SOL), each bound to existing candidate and qualification artifacts.
The loader now returns all three; the targeted manifest/OOS test selection passes 10 tests.
The deployment admission file `deploy/qualification-admission.json` remains empty. These
legacy paper records are distinct from current Macro Scalper/ICT runtime qualification and
grant no live execution authority. The project tree above now describes that distinction.

A second 30-minute public Testnet market/depth capture was started locally at 02:00 MYT
under `artifacts/qualification/runtime-microstructure-probe-20261014-window2`, using the
unchanged six-file probe implementation and the existing 12-symbol Hawkes calibration.
It makes no authenticated requests or orders. Its process/session handle is still active;
no report or acceptance result is available until it exits. The prior single-window 500 ms
gate remains unchanged. The protected VPS trader and credential-free APT/ADA worker remain
separate and untouched; PID 87549 must not be stopped, restarted, signaled, or killed.

## 40. Macro source-binding audit and current-source replay requirement — 2026-10-14 02:05 MYT

Independently recomputed report hashes for all 11 `runtime-scalper-universe` reports; all
11 self-hashes are valid and all decisions are REJECTED. Their implementation maps each
pin `src/autonomous_futures/research/runtime_qualification.py` to the old digest
`76eb016b886b6498b0c9a05393b0528dc2533415e51899ff25c6e4a66fcdef92`, while current source
has since added `daily_risk.py` to Macro qualification's implementation binding. The 11
reports therefore remain historical diagnostics, not current-source qualification receipts.
The separate LINK development and Aug–Sep holdout reports have the same runtime-source
mismatch; that LINK holdout is already consumed and must not be used for retuning.

The Macro Scalper universe contains 11 traded symbols because `MacroLiquidityDipScalper`
uses BTC as 1h/4h regime context and excludes BTC from its tradeable symbols. Current
official 15m/5m/1h caches and funding inputs exist for all 11 pairs through the reserved
2026-08-01 UTC boundary. Once the active second public feed capture completes, rerun the 11
Macro reports against current source, retaining 0.5% trade risk, the 5% day-start equity
loss limit, and the holdout exclusion. No current strategy has been admitted.

## 41. Risk reaffirmation and Macro runner input alignment — 2026-10-14 02:11 MYT

The user reaffirmed **0.5% of actual exchange account equity per trade**. This matches the
runtime planner and frozen replay sidecars; no risk-policy edit or worker restart is needed.
Older 0.25% entries in the chronological record are superseded. The separate 5% UTC
day-start-equity loss limit remains unchanged.

The canonical Macro qualification CLI now defaults to the pinned official snapshot at
`research/immutable-data/runtime-official-20261013`; absent an explicit `--funding` path, it
resolves funding beneath the selected cache. The development variant runner now follows its
selected cache the same way. Canonical reports bind the CLI source digest in `implementation`
and recompute the report identity, so changes to CLI policy/input selection are visible to
source verification. Focused validation passed: 4 runner tests; Ruff check and formatting
passed. No full suite was run. No replay was started while the public feed capture is active;
the capture has not yet produced a result. Production PID 87549 and the existing VPS workers
remain untouched, and the runtime admission manifest remains empty.

## 42. Universe runner family-specific input cleanup — 2026-10-14 02:12 MYT

The bounded qualification orchestrator no longer requires `--commissions` for Macro Scalper;
the argument is required and passed through only for ICT, which consumes that input. Direct
runner calls now reject unknown families and reject ICT runs without commissions. The cache
remains pinned to the official snapshot, and the per-family symbol rules are unchanged.
Fifteen targeted qualification-runner tests passed across the orchestrator and Macro runner
files; Ruff and formatting checks passed. No full suite, replay, VPS change, or order action
was performed. Per-trade risk remains 0.5%.

## 43. Explicit qualification risk binding and parser typing — 2026-10-14 02:17 MYT

The qualification policy now declares `trade_risk_pct=0.5` alongside the 5% daily-loss
percentage, deriving both defaults directly from `DEFAULT_CAPITAL_POLICY` to avoid duplicated
constants. Both Macro and ICT replay paths pass those policy values into the shared trade
planner. ICT's frozen sidecar derives its risk percentage from that policy. Admission receipt
verification rejects an otherwise passing report that omits or changes either approved
percentage, preventing a stale or mismatched replay from qualifying. The live planner remains
at 0.5% and 5%; PID 87549 and the remote replay workers were not touched.

Strict mypy also exposed a local annotation issue where the official kline parser assigned a
CSV reader and a chained iterator to one inferred variable. The reader is now explicitly typed
as `Iterator[list[str]]`; parsing behavior is unchanged. Validation across the modified paths:
79 targeted tests passed, Ruff and format checks passed, and strict mypy passed for five source
files. No full-suite tests or qualification replay were run; the public feed capture is still
active and the deployment admission manifest remains empty.

## 44. Read-only Kainode worker status — 2026-10-14 02:20 MYT

Pinned, read-only SSH confirms `autonomous-futures-trader.service` is active/running at
MainPID 87549 with `NRestarts=0`; no signal or service action was performed. The previously
recorded qualification/replay PIDs (639755, 744029, 747836) are absent, and no qualification,
replay, or probe service is active in the current user-unit listing. The visible long-lived
Python processes belong to the scheduler, Telegram, a user session, and paper-live service.

Two old BTC/LINK holdout-cache builder units remain failed with exit status 1. Their logs show
the older isolated worker checkout rejected headerless Binance kline CSVs as an unrecognized
schema. They relate to the already-consumed LINK holdout and were not restarted; the current
local parser supports that archive format. No production, account, API-key, or order state was
changed. The local 30-minute public feed capture remains active, so the current-source Macro
replay batch is still queued until it finishes.

## 45. Completed Kainode ICT replay artifacts — 2026-10-14 02:23 MYT

Read-only journals show both credential-free ICT resume batches completed successfully and
are now inactive. Their output directories were copied from the isolated worker into the
matching local artifact paths. The four distinct reports have valid self-hashes and all are
REJECTED: LINK 25 trades (-0.625323328 USDT net, -3.362545416 stressed), NEAR 17
(-0.58929320, -1.95476240), APT 23 (-0.40196090800000, -2.69677139300000), and ADA 28
(-1.8254403871700, -4.0710501371700). Each fails sample, net-edge, stress, profit-factor,
and profitable-window gates. Their frozen sidecars say 0.5% risk, but the reports predate
explicit policy binding and their implementation hashes differ from current source; they are
diagnostics only. They do not qualify any pair and cannot be admitted. Duplicate APT/ADA
reports remain in each batch's original output directory for provenance. Production PID
87549 remains active with `NRestarts=0`; no VPS worker was restarted or signaled.

## 46. Live legacy policy differs from the qualified planner — 2026-10-14 02:24 MYT

The live user service runs from `/opt/autonomous-futures-bot` and its entrypoint routes through
`run_phase_310_real_autonomous_trading.py` → `ContinuousSelfDrivingTrader` →
`SelfDrivingTradingEngine`. The on-disk VPS legacy engine still configures a $5 child-notional
cap, $25 aggregate exposure cap, 75% cash reserve floor, and fixed $3 daily loss ceiling.
Its remote source hashes are `903a655d0dcc5e30edb88af5c2413ac7e4b877eaffda88c1114cc0054813842f`
(`self_driving.py`) and `c0816713e6b8dc7cfff642daec0677b87b6d54cc838f3be8813bc5828f473c9d`
(`continuous_trader.py`). The new shared qualification planner instead binds 0.5% risk per
trade, 5% day-start loss, and no per-trade margin, aggregate-notional, or reserve cap. These
are separate code paths; the new policy has **not** been applied to the live service.

No release was deployed and PID 87549 was not touched. The admission manifest is empty and no
current-source strategy qualifies, so the legacy service must remain in place pending a valid
replacement path. Any final migration must preserve the user's no-restart constraint for this
PID and use the reviewed single-writer handoff.

## 47. Qualification reports now carry portable source indexes — 2026-10-14 02:30 MYT

A receipt audit found the Macro and ICT report builders omitted the `source_files` index that
`verify_historical_report` requires, and ICT stored several input hashes without their paths.
New reports now embed a complete path/hash index: Macro includes 15m/5m/1h datasets and
manifests, funding and exchange filters; ICT includes 5m/1h datasets and manifests, funding
and its manifest, commissions, filters, and official minute archive manifests. Report source
paths are repository-relative for cross-machine verification. External inputs outside the
repository fail closed. Each builder rechecks the full index after replay so a changed input
cannot be certified by a run that read earlier bytes.

Focused validation passed: 40 unit tests across qualification receipts, source attestation,
both runner families and archive parsing; Ruff and formatting passed; strict mypy passed for
the two replay engines. No replay was started while the second public feed capture was still
writing its trace. Admission remains empty; the live legacy-policy mismatch in §46 remains
unresolved until a qualified replacement can be reviewed and safely handed off.

## 48. Fresh feed evidence and current-source Macro replay — 2026-10-14 02:43 MYT

The second public Testnet feed probe completed its full 1,800-second window. Its 43,342,453-byte
trace hash, all six implementation hashes, and the calibration artifact hash match their
recorded values. The capture saw 33,578 arrivals, zero gaps, zero duplicates, 75 stale frames,
and a Hawkes spectral radius of 0.671672565. Only BTC, DOGE, NEAR, and LINK had fresh accepted
evidence at the final snapshot; ETH, SOL, BNB, XRP, SUI, AVAX, APT, and ADA were stale. This
public-feed diagnostic grants no qualification or execution authority and does not establish
freshness for the full 12-pair universe.

The current-source 11-pair Macro Scalper replay is now running separately as the credential-free
user unit `afb-runtime-macro-current-20261014.service` (MainPID 858807). The isolated worker is
capped at two CPU cores and 4 GiB memory, with low CPU and idle I/O priority. Its 328-file source
package hash is `ff3f30b6f7a511ab48dbee58e01d495f91a996409dc7b2b6410a0c17d2e5560f`; all 96 files in
the official cache match the local SHA-256 manifest. The remote CLI smoke check passed, and the
frozen replay policy records 0.5% trade risk and 5% daily loss. The report output directory is
`/home/afbot/qualification-worker/runtime-macro-current-20261014/artifacts/qualification/runtime-macro-current-20261014`.
Two pair reports have appeared but are not yet validated; do not use them for admission.

A fresh service check confirms the protected trader remains active at PID 87549 with
`NRestarts=0`. No trading service, credential, account setting, or exchange order was changed.
The admission manifest remains empty, and the legacy live-policy mismatch in §46 remains
unresolved pending a fully validated replacement and reviewed single-writer handoff.

## 49. Current-source Macro batch rejected on edge gates — 2026-10-14 02:47 MYT

The isolated two-core Macro batch completed successfully for all 11 tradeable pairs. All 11
report self-hashes, implementation digests, source-file indexes, frozen-policy hashes, and
Decimal trade-ledger metrics verify against the local source and the exact official cache.
Each report binds 0.5% per-trade risk and 5% daily loss. The decision is **REJECTED for all
11 pairs**: all 11 pass minimum sample count, only 2 have positive net PnL, none have positive
stressed PnL, none pass the 1.10 profit-factor gate, 5 pass drawdown, and only 1 passes the
profitable-window consistency gate. Total modeled trades across the separate symbol reports:
1,183. This sum is diagnostic and is not a portfolio return.

An exit-reason audit counted 627 `STOP_LOSS` exits (combined net -235.945 USDT; stressed
-289.092), 293 `TAKE_PROFIT` exits (+165.403; stressed +145.138), and 263 `TIME_STOP` exits
(+38.492; stressed +18.574). These sums also combine separate per-symbol reports and are not
portfolio performance. They point to stop-loss losses dominating the model outcome; this is
diagnostic evidence, not authority to retune on the same OOS sample.

The reports are verified evidence of rejection, not admission receipts. Do not tune the
strategy on this evaluated OOS batch or weaken the 0.5% risk decision to change these results.
No report was added to `deploy/qualification-admission.json`. The qualification unit completed
with systemd `Result=success` and is inactive. The protected trader is still active at PID
87549 with `NRestarts=0`; no production service, API credential, account setting, or order was
changed. Local copies are under `artifacts/qualification/runtime-macro-current-20261014/`.

## 50. Actual-account-capital Macro sensitivity replay — 2026-10-14 03:16 MYT

The user reaffirmed retaining **0.5% of actual exchange account equity per trade**. The
qualification policy and every report in this replay record 0.5% trade risk and a separate
5% UTC day-start-equity loss cutoff; the user decision is reflected without changing either
value.

A fresh authenticated, read-only Testnet snapshot observed equity of 4,224.09882354 USDT,
with wallet/equity reconciled at zero drift, a flat account, and no open orders. The snapshot
was used only as a historical sizing seed for research. Its daily-risk evidence is explicitly
unverified because no genuine UTC day-start baseline was configured, and it grants no
execution authority. Only the sanitized probe summary is stored at
`artifacts/qualification/runtime-inputs/testnet-account-probe-20261014-1791918191661.json`.

The 11-pair current-source Macro replay was repeated against the same pinned historical
market sample at that capital level. It ran offline in the isolated credential-free VPS
worker `afb-runtime-scalper-equity-20261014.service`, bounded to two CPU cores and 4 GiB;
it completed successfully in 2m10s with 1.2 GiB peak memory. All 11 report hashes, policy
bindings, repository source-file indexes, and underlying source bytes were independently
verified locally. All reports retain `execution_authority=false`.

All 11 symbols are **REJECTED**: 11/11 pass minimum sample count; 3/11 pass positive net
edge; 0/11 pass profit factor; 5/11 pass drawdown; 2/11 pass profitable-window consistency;
and 0/11 pass stressed net edge. The 1,216 modeled trades are in separate per-symbol
research accounts and are not a shared-portfolio return. No report was admitted or used to
retune this already evaluated market sample. Reports are preserved under
`artifacts/qualification/runtime-scalper-equity-4224-20261014/`.

Post-run read-only SSH again showed `autonomous-futures-trader.service` active at PID 87549
with `NRestarts=0`; the qualification unit is inactive after success. No live service, API
key, account setting, or order was changed. Macro has no qualified candidate, the daily
baseline remains unverified, and the legacy shared-writer/deployment gap remains unresolved.

## 51. Actual-account-capital ICT sensitivity replay — 2026-10-14 06:09 MYT

The user reaffirmed **0.5% of account equity risk per trade**. The ICT replay policy and all
12 reports bind that value, a separate 5% daily-loss cutoff, and the 4,224.09882354 USDT
Testnet snapshot as a historical sizing seed. The snapshot is not a verified UTC day-start
baseline (`utc_day_start_baseline_verified=false`), and every report has
`execution_authority=false`.

The same pinned historical ICT `limit_touch` sample was replayed at this capital level. Six
pair jobs ran locally and the other six ran on Kainode in the isolated credential-free
`afb-runtime-ict-equity-20261014-vps-v2.service`, limited to two CPU cores and 4 GiB. The VPS
batch completed with `Result=success`, 1.1 GiB peak memory, and all six subprocesses exiting
zero. Local validation confirmed the report hashes, all eight implementation hashes per
report, each source-file index and underlying source bytes, policy fields, and disabled
execution authority for all 12 reports. The six VPS reports are preserved in
`artifacts/qualification/runtime-ict-equity-4224-20261014-vps-v2/`; the six local reports are
in `artifacts/qualification/runtime-ict-equity-4224-20261014/`.

All 12 symbols are **REJECTED**: 4/12 meet minimum sample count; 0/12 pass positive net edge,
stressed net edge, profit factor, or profitable-window consistency; 12/12 pass drawdown.
The 292 modeled trades are sums across independent per-symbol reports, not a shared-wallet
portfolio result. This repeats the same historical sample at a new sizing seed; it is capital
sensitivity evidence, not a fresh holdout and not a basis for retuning. No candidate was
admitted.

Post-run read-only SSH confirmed the qualification unit inactive after success and the
protected `autonomous-futures-trader.service` active at PID 87549 with `NRestarts=0`. The
worker had no exchange credentials or order methods and placed no orders. No production
service, API key, account setting, or admission entry changed. The daily baseline remains
unverified and the legacy shared-writer/deployment gap remains unresolved.

## 52. Macro short-side and authenticated commission provenance — 2026-10-14 06:43 MYT

The user reconfirmed **0.5% of actual exchange account equity as risk per trade**. This is
already the planner, qualification, and worker setting; older 0.25% notes in this handoff
remain superseded. The 5% UTC day-start-equity loss limit is unchanged.

Macro Scalper can now evaluate the mirrored short setup when BTC 1h/4h regime is bearish;
the execution plan preserves the signal side instead of forcing every setup long. The
causal scanner and development replay use the same regime classification. This changes
strategy behavior and invalidates earlier source-bound qualification reports for admission;
it does not qualify a strategy. Existing rejection reports remain historical evidence only.

Every Macro qualification entry point now requires the authenticated Testnet commission
snapshot, binds each symbol's maker/taker rates and the snapshot hash into report provenance,
and rejects policy rates that differ from the snapshot. The bounded development-grid runner
passes this input explicitly. The validated snapshot currently records 0.000200 maker and
0.000400 taker rates for the 12-pair universe. No new grid or validation replay was started
in this checkpoint.

Targeted validation passed: 65 unit tests across Macro signal logic, causal scanning,
qualification, runner inputs, development-grid orchestration, and holdout tooling. Ruff,
format checks, strict mypy, and scoped whitespace checks passed. The development-grid
protocol now also fails closed unless the selected commission artifact is fingerprinted.
No full-suite test was run.
No qualification/admission report was created, and this checkpoint made no VPS, credential,
account, order, or production-service change. Genuine strategy qualification, verified
UTC-day-start equity, and a safe single-writer transition remain outstanding.

## 53. Correct partially consumed holdout ledger — 2026-10-14 06:46 MYT

Current-state inspection found that the Aug–Sep 2026 holdout README and index still called
the entire dataset uninspected even though a frozen LINK Macro candidate had already been
evaluated on 2026-08-01 through 2026-10-01. The preserved report is rejected, has
`execution_authority=false`, and its runtime implementation hash is stale; it is diagnostic
only. It used LINKUSDT market/funding observations and BTCUSDT 1h shared regime context. It
did not tune parameters. The report file SHA-256 is
`b2586895d7aed210dd1bf0be82a87f07baefdeceab36eec9e12cce62d120f4b2`.

The holdout index and README now mark the archive set `partially_consumed`, record the exact
report/hash and consumed BTC context, and list the ten other target-symbol partitions as
uninspected. A focused integrity test checks those claims against the report bytes; it passed
(1 test). The report itself and its source artifacts were not modified. The fresh VPS SSH
attempt returned `Permission denied (publickey)`; no current remote worker state could be
confirmed, and no process was started or signaled. No qualification report was created and
the admission manifest remains empty.

## 54. Symmetric-short Macro development grid — 2026-10-14 07:07 MYT

Per-trade risk remains **0.5% of actual account equity**, as reconfirmed by the user; the
separate daily-loss cutoff remains 5% of UTC day-start equity. The available Testnet equity
snapshot remains only a historical sizing seed, not a verified current day-start baseline.

The frozen, development-only symmetric-short grid completed all 275 parameter jobs across
11 Macro symbols with zero failed jobs. Its final protocol/source integrity checks passed,
all 275 report file hashes match the summary, and every report has
`execution_authority=false`. The run used three local workers; no VPS or trading service was
started, touched, or signaled. Summary:
`artifacts/qualification/runtime-scalper-symmetric-short-grid-development-20261014-v3/grid-summary.json`
(SHA-256 `c8b07d1e0462c1600a746838331ffb6688dfa9b41c807ea1e044c1058b573c6b` for the frozen
protocol).

Five XRPUSDT parameter combinations pass the development gates; all other 10 symbols have
zero passing combinations. The frozen ranking rule puts XRPUSDT distance `-4.0`, target
`3.0 ATR` first (32 trades, net PnL 180.7171421506274 USDT, stress net PnL 65.6799657766274
USDT, 5 profitable windows). This is a development-screen result only. No candidate
selection or qualification/admission artifact was created. Although XRP's pair-specific
Aug–Sep 2026 partition is listed as uninspected, BTC 1h shared regime context from that
interval was already used in a rejected LINK diagnostic. Any use of this partition must
retain that partial-consumption disclosure; it cannot be called a fully pristine common-
context holdout. No tuning was done on the reserved interval.

The grid did not establish genuine qualification, actual day-start equity, live authority,
or a deployable portfolio result. The admission manifest remains empty. The protected
`autonomous-futures-trader.service` must remain untouched at PID 87549; fresh SSH access was
not available at the preceding check, so current remote worker state is unverified.

## 55. Remove fabricated Testnet bridge telemetry — 2026-10-14 07:10 MYT

The Phase 307 bridge mapper no longer substitutes a connected gateway, masked mock key,
active listen key, 12 filled orders, exchange filters, $100.12 ledger, or verified zero drift
when evidence is absent. Missing connection, performance, financial, and verification data
now remains unavailable; partial responses do not inherit verification or execution-off
claims. The page displays unknown values, dynamically lists symbols present in API evidence,
and uses a warning state while the bridge response is unverified.

Validation passed: 3 targeted bridge-page Vitest tests, TypeScript plus production frontend
build, and scoped `git diff --check`. The full test suite was not run. Other stage-specific
builders in `frontend/src/lib/canary.ts` and the production-launch model still contain
fabricated fallback telemetry and stale capital-policy defaults; frontend cleanup is not
complete. No VPS, credential, exchange, account, order, or production-service state changed.

## 56. Full transfer back to Antigravity — 2026-10-14 07:27 MYT

The owner requested return of sole engineering ownership to Antigravity. The complete
consolidated guide is `ANTIGRAVITY_HANDOFF_2026-10-14.md`; this file remains canonical for
architecture and policy. Older Antigravity handoffs now point to the current transfer and
retain their original chronology as historical evidence.

Fresh explicit-key pinned SSH confirmed trader PID 87549 active with zero restarts and web
PID 287760 active with zero restarts. The scoped research/replacement user-unit inventory
shows no active unit and two historical failed BTC/LINK cache builders. Metadata and
timestamps are saved under `docs/handoff/2026-10-14/`. No remote mutation occurred.

The completed v3 grid was independently rechecked: 120 frozen input fingerprints, 275
report file hashes and all development-only report self-hashes match. The handoff research
summary retains five XRP development passes, partial holdout consumption and no execution
authority. No new candidate selection or qualification was performed. All existing
application changes and immutable evidence remain in the dirty local checkout; the custody
inventory and digest index identify transfer bytes rather than pretending HEAD is a release.

The rollout guide now explicitly records that same-key activation is blocked while the
protected legacy daemon is active. It no longer demands legacy inactivity and simultaneous
legacy-active post-rollout status. This correction authorizes no service transition.
No application code, tests, trading/account state, credentials, deployment, Git commit or
push was changed/performed for this documentation transfer. Antigravity should continue
independent engineering/research from the recorded priorities without bypassing admission.

## 57. Antigravity continuation: XRP holdout evaluation, shared-wallet portfolio qualification, autopsy-to-Learner/Creator feedback, Phase 309 frontend hardening, and VPS preflight tooling — 2026-10-14 13:07 MYT

Antigravity completed the continuation priorities without modifying any of the eight grid-fingerprinted files or `scripts/qualify_frozen_scalper_candidate.py`, and without touching `autonomous-futures-trader.service` (`MainPID=87549`, `NRestarts=0`):

- **Frozen XRP candidate bridge & Aug–Sep 2026 holdout evaluation:** Selected `XRPUSDT` (`dist_atr_threshold=-4.0`, `tp_atr_mult=3.0`) in `research/qualification-development-2024-2026/scalper-symmetric-short-selected-candidates-v3.json` (`SHA-256: 34668f7e2b9079a08679c948fc7fae6facf0a40f4530997b220c80bb94c75da7`), bridged it via `scripts/bridge_scalper_candidate_for_holdout.py` into `research/qualification-development-2024-2026/frozen-xrp-symmetric-short-candidate-v1.json` (`SHA-256: cb5a7e34c892c78b6a7fa6278ce66b6cf42d982ac6c48e23ce97395c751d27cf`), and evaluated the Aug–Sep 2026 holdout (`artifacts/qualification/runtime-scalper-xrp-holdout-2026-08-2026-09/XRPUSDT-92d4ce70f71e7096.json`, `SHA-256: 706adb88cb44c72f248304447918bfacece5f9f6598812d80f4fd11796a4de57`): `decision="REJECTED"`, `execution_authority=false`, 1 signal, 0 fills (`unfilled=1`). Updated `research/qualification-holdout-2026-08-2026-09/holdout-index.json` (`SHA-256: 5529f6ce37bf2f225c6cd3414675daa665bd73b4df8aee0843e0e9189809ec22`). `deploy/qualification-admission.json` remains `approved_reports: []`.
- **Causal shared-wallet portfolio qualification:** Implemented `src/autonomous_futures/research/portfolio_qualification.py` and `scripts/run_portfolio_qualification.py`, producing `artifacts/qualification/portfolio-scalper-development-20261014/portfolio-bd20efcc58d951e1.json` (`SHA-256: 8bf6a10945fd61619bb7798fd80d12bf6b854240afd7d3e6a28be4121e9bf9c2`, `max_wallet_drift="0"`, `max_equity_drift="0"`).
- **Durable fill-reconciled trade autopsies & AI Self-Learning feedback bridge:** Implemented `src/autonomous_futures/execution/trade_autopsy_evidence.py`, wired `_record_closed_autopsy` into `LifecycleCoordinator` (`trade-autopsies.json`), updated `creator_prompts.py` and `strategy_router.py`, and added `build_runtime_qualification_failure_feedback` in `src/autonomous_futures/research/creator_failure_feedback.py` to project rejected runtime/holdout reports and durable trade autopsies into `CreatorQualificationFailureFeedback`.
- **Frontend truthful telemetry & policy cleanup:** Hardened `buildProductionLaunchModel` in `frontend/src/lib/canary.ts` and `frontend/src/components/production-launch-page.tsx` against partial-data fabrication (`$100`, `BTC/ETH/SOL`, `ord-p309`, `$5/$25/75%/$3`, fallback Merkle roots), updated `evolution-page.tsx`, and aligned mission-control/executive surfaces with the `0.5%` risk / `5%` daily-loss policy.
- **Turnkey VPS preflight verification:** Added `scripts/preflight_qualified_runtime.py` and `tests/unit/test_preflight_qualified_runtime.py`. Read-only SSH at 2026-10-14 13:06 MYT confirmed `autonomous-futures-trader.service` (`MainPID=87549`, `NRestarts=0`) and `autonomous-futures-web.service` (`MainPID=287760`, `NRestarts=0`) remain active and untouched.
