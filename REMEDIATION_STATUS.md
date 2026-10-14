# Remediation status — 12 October 2026 (MYT)

## Delivery boundary

Local safety and truthfulness changes have been implemented and checked. Nothing has been deployed, pushed, or committed. Existing unrelated modifications and artifacts were preserved. The trader was never stopped, restarted, signaled, or killed. A final read-only VPS check confirmed ActiveState=active, MainPID=87549, NRestarts=0.

This is **not a completed live-trading upgrade**. The revised daemon intentionally observes authenticated account state and blocks live strategy dispatch until genuine qualification and measured microstructure/protective execution integration are complete. Copying this code onto the VPS would not update the existing process's imported Python modules. Do not hot-patch or restart that process.

## Initial remediation batch (historical capital contract)

- Strict child sizing without the previous one-lot cap exception or invented BTC/testnet precision. Micro-capital configuration cannot relax the user's bounds.
- Gateway loading of exchange-specific filters and an additional strict $5 submission check. Protective quantities can be prevalidated and split into capped children; incompatible residual lots reject the plan.
- Removal of protective-order retries with reduceOnly=false.
- Explicit separation of simulation matching from live execution: live calls cannot manufacture fills or internally claim exchange flattening.
- A durable live order journal with IDs derived from signal identity, pending/partial/terminal exchange statuses, serialized submission, pending exposure reservation, fresh account checks, and reconciliation of uncertain acknowledgements. Timeout means UNKNOWN, not automatic resubmission or a fill. This component is not yet wired to grant strategy dispatch authority.
- Atomic authenticated account snapshots for the separate web process, with actual positions/open orders. The execution API preserves quantities/exposure, accepts all observed order-ID prefixes, and returns 503 if fresh evidence is missing. It no longer merges historical drills into a purported live account or forces flat positions/reserves.
- Persisted Decimal wallet reconciliation and income deduplication. Following explicit user approval, wallet = starting equity + net realized PnL and equity = wallet + unrealized PnL. Fees/funding count; unsupported transfers require explicit basis adjustment instead of becoming profit. Both reconciliation tolerances remain below 1e-15 USDT.
- Simulation ledger margin reservation/release now uses Decimal throughout. Simulation exits respect the child cap and preserve protection while a partial position remains.
- Daily exchange loss observations include commissions, funding and unrealized PnL, using UTC exchange-day boundaries.
- Closed-candle ingestion, 250-bar capacity for EMA warmup, freshness/gap quality gates, and exchange-environment-consistent REST fallback. Live evaluation must not interpret stale or interpolated data as eligible.
- Canonical 62% ICT OTE default, consecutive one-minute Twin FVG checks, BTC 4h data supplied to the scalper, and the 12-pair default service configuration. Existing service files were edited locally only.
- Removal of production synthetic price/chart generation, fabricated live evolution fallbacks in both UI and adapter, and the historical loader's fabricated live progress. Standalone ICT API analysis explicitly does not grant execution authority.
- Removal of synthetic bootstrap generation before continuous daemon startup and duplicate runtime scalper candle polling. Compatibility/research helpers were retained rather than deleted without a dependency migration.
- A frontend GitHub Actions job for tests/builds. The full local suite was not run.

## Validation

- 175 targeted backend tests passed across remediation, gateway, scalper, ICT, ingress, API and drill files.
- 24 targeted frontend tests passed for evolution rendering and canary adapters.
- Frontend TypeScript/Vite production build passed.
- Strict mypy passed for 10 changed production modules.
- Targeted Ruff checks passed. No assertion is made about the full CI result; no push was performed.
- Legacy fixtures were corrected to use actual milliseconds, the 12-pair configuration, explicit test-only exchange fill responses, strict cap rejection and unavailable telemetry expectations. They no longer require fabricated production behavior.

## Outstanding work

1. **Runtime qualification binding.** Existing ICT candidate examples contain placeholder dataset/bundle/qualification hashes and generic RSI rules. A candidate name or registry row is not qualification for the runtime ICT algorithm. Validate real OOS evidence against the actual strategy implementation and parameter genome; do not invent admission receipts.
2. **Measured microstructure integration.** Wire genuine trade/depth events, model warmup, event-age checks and Hawkes measurements into the live entry policy. The revised daemon currently blocks dispatch instead of supplying constant risk values.
3. **Complete protective lifecycle.** Connect strategy intentions to the durable live journal; handle partial fills, protected quantities, two-stage ICT exits, cancellations, emergency reduce-only closure and confirmed commissions/autopsies. The drill has capped reduce-only protection, but that is not a full autonomous lifecycle. Stop-market executions can move beyond their trigger-price estimate; strict realized-notional guarantees require a clearly specified execution policy, not an assumed tolerance.
4. **Recovery beyond observation.** Persist and recover strategy ownership, entry time, bracket IDs, remaining TP stages and candidate genomes. A flat/no-pending initial ledger baseline is required; an existing untracked position must not be silently adopted or declared safe.
5. **Production rollout without trader interruption.** Web/UI-only changes can be evaluated separately, but the revised API needs the authenticated observer evidence. No observer process/service has been deployed. The running trader cannot import the new engine automatically. Any activation approach must preserve the explicit PID/service constraint.
6. **Dependency cleanup and broader test migration.** Consolidate production ledger/service ownership only after mapping research consumers. Older challenge suites may encode removed fake telemetry or over-cap behavior and need targeted migration. Adding frontend CI does not prove all historical frontend challenges pass.

The earlier audit remains a record of the pre-remediation findings; its line references describe that earlier source state. This status document records what was actually changed and what remains.


## Goal work update — 13 October 2026 (MYT)

The user superseded the original capital restrictions: no fixed per-trade margin cap,
no $25 aggregate-notional cap, no 75% reserve floor, and a daily-loss circuit at 5%
of genuine day-start equity. The actual-account-versus-dedicated-allocation reference
is still awaiting clarification. Exchange available-margin and leverage-tier checks
remain necessary. Existing legacy simulation and unwired live-journal policies still
need migration; the earlier implemented list describes the first batch, not the new
production contract.

- Added a pure percentage-loss calculation, deposit/withdrawal treatment, and an
  authenticated day-boundary tracker with persistent breach latching. Missing genuine
  day-start evidence disables entries. This tracker currently supports an explicitly
  selected account basis; it is not wired to grant trading authority.
- Added a shared Decimal trade planner with equity/stop-distance sizing and protective
  exit geometry. Its current 0.5% per-trade risk fraction is an engineering default,
  not a user-selected amount or a new fixed initial-margin ceiling.
- Removed the obsolete $5 notional check from the gateway. Entries enforce exchange
  minimum notional; reduce-only protective exits may be below that minimum. Exit
  slicing now uses actual exchange maximum quantities.
- Captured authenticated leverage brackets for all 12 pairs, without changing any
  leverage setting or submitting orders.
- Ran frozen canonical scalper replay over existing real data, starting OOS on
  2024-01-01 and using an explicitly declared $100 single-symbol research account.
  SOL: 107 trades, net -7.747502670877073005 USDT, stress net
  -16.145661906877073005 USDT, one profitable window. ETH: 122 trades,
  net -2.0475564562712477734 USDT, stress net -13.7380118232712477734 USDT,
  two profitable windows. Both reports are REJECTED and execution_authority=false.
  These are model results, not exchange fills or portfolio qualification.
- Acquired 512 official monthly 1m archives with published SHA256 checksums across the
  12-pair universe. Streaming Decimal validation passed for all 22,425,600 candles,
  including inter-month continuity and candle geometry. No missing minute was filled.
  SUI coverage begins later than the other pairs. Higher-timeframe cache derivation
  completed for all 36 files in a separate immutable directory; their SHA256 hashes
  were verified and the qualification reader accepted the BTC 1h source. The earlier
  cache remains untouched.
- Added a measured exponential Hawkes likelihood fit and ingress gates. No preset
  branching matrix is accepted as measured risk. Warmup, stale evidence, crossed
  quotes and real sequence gaps veto entries. Delayed authentic arrivals are retained
  for calibration while their age still prevents fresh entry authority.
- A versioned read-only probe was staged under VPS artifacts. It has no order-writing
  capability. A real 120-second VPS trace had no missing aggregate-trade IDs. Its
  retrospective measured fit gave spectral radius 1.0037274832227716, which exceeds
  the rho<1 gate. The fit artifact grants no execution authority. Initial probe
  filtering incorrectly turned delayed frames into apparent gaps; the preserved raw
  trace exposed the error and the collector/ingress handling was corrected.
- Added observed exchange-clock alignment with bounded RTT uncertainty. The first
  local probe rejected all frames because the local clock lagged exchange time;
  calibration now uses public server-time evidence rather than relabeling old events.

Targeted gateway, risk, replay, Hawkes derivative/fit, ingress, clock and archive-reader
checks passed. Ruff and strict mypy passed on the new checked modules. No full local
suite, GitHub push, main runtime deployment, service restart or live strategy activation
has occurred. A read-only VPS check again confirmed MainPID=87549, NRestarts=0,
ActiveState=active. Full protective lifecycle, genuine ICT OOS qualification, runtime
certificate binding and continuous integration remain outstanding; the goal is active.


### Protective lifecycle implementation update

Added a pure lifecycle reducer that binds cumulative entry/exit fills to the observed
owned position, keeps acknowledged stops during partial fills, cancels entry remainders,
and derives exchange-lot-aligned ICT partial/final exits from actual filled quantity.
A minimum-lot partial fill that cannot split safely uses the final target. Daily-loss,
hold-time or failed-protection exits are reduce-only; pending/unknown market closures
are reconciled instead of duplicated. External or opposite positions are never adopted.
No-fill pending entries keep prearmed stops; confirmed flat positions clean up sibling
orders only after the entry remainder is terminal.

Added a durable protective command adapter that saves intentions before network I/O,
uses file/directory fsync on Linux, never opens positions, and preserves UNKNOWN on
uncertain acknowledgements. Exchange symbol/client identity and reduceOnly are checked.
Conditional reconciliation follows actualOrderId to the exchange child; FINISHED without
an actual child does not prove a fill. Both ordinary and migrated conditional stops
are handled. Six initial lifecycle tests and four initial adapter/API tests passed;
additional persistence-failure and triggered-child checks passed with the targeted
account-evidence remediation tests (33 tests). Strict mypy and Ruff passed.

This remains **unwired infrastructure**, not proof of a completed autonomous lifecycle.
Exclusive process fencing, first-fill/commission recovery, orchestration, live-journal
capital-policy migration, strategy certificate binding, genuine ICT replay and production
activation/deployment are still required. No protective orders were sent to the VPS;
all lifecycle I/O tests used explicitly supplied unit-test gateways/transports.


### Causal qualification and risk migration update

ICT arrays now carry a confirmation/knowledge timestamp rather than allowing lower-TF
taps before their formation was knowable. Order blocks bind displacement closes,
fractal levels bind right-hand confirmation candles, and FVG/inversion timestamps
bind the forming candle close. Exact immutable HTF inputs use a bounded pure cache.
The canonical OTE is exactly 62-79%; reported bounds and sweet spot match configuration.
One-minute CISD must retain its directional body close, and a stale confirmation cannot
be reused as a fresh trade intention. The shared planner enforces ICT first-target
reward/risk >=1.5. Unit fixtures were corrected to put HTF closes before LTF taps and
use actual millisecond spacing; their assertions were retained (82 targeted checks).

All 512 published funding archives were acquired and normalized into immutable CSVs
with checksum provenance. Actual Testnet commission rates were authenticated for all
12 pairs (maker 0.0002, taker 0.0004). The chronological ICT runner freezes policy before
replay, binds inputs/implementation hashes, models both TP stages, CISD invalidation,
funding, fees/stress and the 5% daily circuit. Sub-minute funding is handled with adverse
exposure bounds. Its $100/1x single-symbol account is declared research scope, never a
claim about authenticated balance. BTC's full run completed REJECTED: five modeled trades, net -0.48403544800000 USDT,
stress net -1.09758098600000 USDT, zero profitable windows. No ICT receipt
has been admitted as live authority. The same frozen checks are running across
the remaining pairs with bounded local subprocess concurrency.

The live journal no longer enforces the obsolete $5 child-notional, $25 aggregate or
75% reserve/$3 daily limits. Entry needs genuine current 5% daily baseline evidence and
authenticated matching leverage configuration; absent evidence rejects. Exchange
available-margin sufficiency remains mandatory. Already observed exchange orders are
not charged twice against availableBalance. Unobserved journal margin is reserved.
Account observations now collect authenticated symbol configuration and can attach a
selected genuine daily tracker; unconfigured daily equity reference remains unverified.
Reduce-only closure no longer depends on a healthy public ticker endpoint.

A real exit-only Testnet prearm probe verified that a reduceOnly STOP_MARKET can be
accepted and queried NEW while the account is flat. Its own order was canceled;
all positions/open orders remained zero and wallet drift was numerically zero. MainPID
87549, NRestarts=0 and ActiveState=active were unchanged. The original probe's overall
flag compared equivalent zero string spellings and was false; the preserved raw evidence
has a separate numerical assessment with all checks passing. This validates prearm
feasibility, not a triggered stop fill or strategy qualification.

Added an actual OS-held writer lease, with cross-process contention/release checks and
shared in-process I/O serialization. Protective I/O now requires a held lease. This
fences participating new writers only: it cannot fence the protected legacy process
that does not use the lease. Safe credential/writer separation remains an activation
requirement. No main trading service has been restarted or replaced, and no opening
order was submitted during this work.


The official-corpus scalper universe replay has now completed: all 11 tradable scalper
pairs are REJECTED. LINK and XRP had positive base-model net PnL but failed profit-factor
and/or window consistency, and every pair had negative stressed net PnL. BTC remains
macro context, not an eligible scalper pair. The preserved universe assessment lists
each gate and report hash. Remaining ICT per-pair runs are genuinely in progress.
No gate was weakened to produce a passing outcome.

### Entry clock integration — 2026-10-13

Entry admission now requires an observed ExchangeClock rather than caller-supplied frozen local/exchange timestamps. It samples current time after legacy-permission I/O and again after prearming stops, checks both trade and depth freshness including clock uncertainty, and passes the observation into LiveOrderBook for another check under the writer lock. Regression checks exercise a real timestamp offset in explicit mocked exchange I/O: fresh evidence proceeds; evidence whose worst-case age exceeds 500ms is rejected before journaling or POST. Six targeted percentage-risk/clock tests pass; strict mypy passes for both changed execution modules. No exchange order or VPS service action was performed. This closes a stale-clock admission gap; qualification and production integration remain incomplete.

ICT qualification session 89445 was confirmed live this turn. ETH and SOL progress logs reached September 2025; no new qualification authority has been claimed.

### Recovery failure isolation — 2026-10-13

LiveOrderBook reconciliation now returns unresolved client IDs and continues querying subsequent orders after a transport failure. LifecycleCoordinator rejects stale cached ownership for those unresolved entries while continuing independent owned lifecycles. Per-trade exchange/fill failures remain recorded and isolated; transport errors persist only their exception class rather than potentially sensitive signed URLs. Two new regression cases prove later order queries and independent prepared-lifecycle cleanup still execute after an earlier timeout, and the uncertain trade stays open for recovery. Thirteen targeted coordinator/order/protective-executor tests pass; strict mypy and Ruff pass for the changed execution modules. This does not prove protection of an unresolved entry or grant live authority. No VPS service action or exchange order was performed.

Qualification job 89445 remains live; ETH/SOL replay logs advanced to October 2025 during this turn. Full qualification and deployment remain pending.

### Conditional-order inventory — 2026-10-13

Authenticated account observations now include the separate GET /fapi/v1/openAlgoOrders inventory, as documented by Binance. A new ledger baseline requires both ordinary and conditional order inventories to be empty. Entry admission queries the symbol's current conditional inventory before preparing a new lifecycle and rejects preexisting orders. It also rechecks maker price against the refreshed book after bracket I/O. No conditional order is canceled by this inventory check. Tests verify the exact endpoint, requested-symbol validation, offline rejection, and refusal to initialize a flat-looking account that still has a pending conditional order. Twenty-nine targeted gateway/remediation checks pass; strict mypy passes for all three changed execution modules and Ruff passes. No VPS service mutation or exchange order occurred. Full runtime activation/deployment is still incomplete.

Reference: https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Current-All-Algo-Open-Orders

### Persistent measured feed component — 2026-10-13

Added feed/live_market_feed.py: real Testnet combined aggTrade/depth5 streams, observed public server clock refreshed independently, and background Hawkes calibration using the existing measured monitor. Disconnect, stale clock, stream closure, and task cancellation invalidate evidence; reconnect requires genuine warmup again. Combined-stream URLs strip the gateway single-stream /ws suffix. Mainnet/offline construction is rejected for this authorized rollout. Five targeted tests verify endpoint construction and invalidation paths, and strict mypy/Ruff pass for the new component. This component has not been deployed or connected to a complete trading daemon; no live activation is claimed. The qualification process remains live, with ETH/SOL replays through November 2025.

### Runtime account/protection/admission orchestration — 2026-10-13

Added execution/runtime_session.py to connect authenticated account observation, explicit daily-risk tracker, owned lifecycle recovery, persistent measured market feed, and qualified entry admission. It rejects mismatched shared components/gateways. Each entry cycle executes account observation, protective recovery, a second account observation after protective writes, daily-budget verification, and then admission. Protection-only cycles require no strategy signal or market-fit authority. An unresolved owned lifecycle blocks new entries. Strategy scanning has a one-second timeout so a stalled scanner cannot indefinitely defer the next protective cycle. Three targeted sequencing/recovery tests pass, as do strict mypy and Ruff for the new orchestration module. Tests explicitly mock exchange I/O; they are not evidence of live fills or deployment. A real causal strategy scanner, trusted qualification binding, operator equity/key decisions, and full daemon deployment still remain required. No VPS service action was performed.

### Causal runtime history reader — 2026-10-13

Added feed/closed_history.py to request actual exchange REST candle history for the five canonical strategy timeframes. It validates exact open/close interval boundaries, finite positive OHLC geometry, nonnegative volume, contiguous ordering, a minimum of 250 completed bars, and the latest expected completed candle. Forming bars are omitted before strategy evaluation. Offline synthetic gateway histories are rejected. Six targeted tests cover forming-bar exclusion and missing/duplicate/stale/malformed observations; strict mypy and Ruff pass. This is an input component for the still-unfinished causal runtime scanner, not evidence of qualification or deployment. The ICT job handle 89445 was confirmed live this turn; ETH progress reached December 2025. No VPS service mutation occurred.

### Canonical causal scanner and independent protective loop — 2026-10-13

Added execution/causal_scanner.py: round-robin report-bound canonical strategy evaluation, actual closed 4h/1h/5m/1m histories for ICT (no 15m PDA), actual symbol 15m plus BTC 1h/4h histories for scalper, authenticated equity/available margin/daily allowance/current leverage, and the shared trade planner. Engine defaults must match report configuration exactly. Rejected reports fail before candle acquisition and never become entry intentions. Qualification trust/domain completeness remains unresolved; this adapter does not claim a complete qualification certificate. RuntimeSession now runs scanning independently with a bounded one-item intention queue, replacing the one-second timeout that could starve genuine multi-request REST scans. Protection proceeds even when scanning stalls, and every queued intention passes fresh recovery/account/admission checks. Six targeted scanner/session tests pass, as do strict mypy and Ruff. Production daemon composition, portfolio policy binding, credential/equity choices, genuine passing qualification, and actual deployment remain incomplete. Qualification handle 89445 was confirmed live this turn. No VPS service action or exchange order was performed.

### Entry expiry and writer-lock market guard — 2026-10-13

EntryAdmission rejects future decisions and expired intentions (ICT confirmation minute: under 60 seconds; macro entry TTL: under five minutes). LiveOrderBook now supports a synchronous guard invoked inside its writer lock immediately before persisting a new opening intention. Admission uses it to revalidate causal age, observed clock freshness/uncertainty, current measured Hawkes evidence, feed generation, and noncrossing maker price after waiting for that lock. A failed guard leaves no entry journal or POST. Seven targeted percentage-policy/admission-time checks pass; strict mypy and Ruff pass for changed execution modules. Qualification job 89445 is still live; ETH/SOL logs reached February 2026. All previously rejected reports remain rejected. No VPS service action or exchange order occurred; full activation and deployment remain incomplete.

### Reviewed qualification admission pins — 2026-10-13

Runtime scanner and entry admission now use verify_runtime_report, requiring an independently reviewed family/symbol/exact report-byte SHA256 in deploy/qualification-admission.json as well as the historical implementation/data/metrics gates. The runtime never populates this manifest from uploaded reports or candidate labels. Historical analysis verification remains separate and grants no runtime admission. Raw report bytes are read once for pinned SHA and JSON verification, avoiding a report re-read race. The current admission list is empty because no genuine passing report has been accepted for this deployment. Tests demonstrate that editing QUALIFIED/gates and recomputing the report's own hash cannot replace pinned bytes, and that pinning a rejected genuine report still fails its research gates. Ten targeted receipt/scanner/session tests pass; strict mypy and Ruff pass for all three changed execution modules. This deployment trust pin does not replace remaining capital-domain/source-verification work or establish a genuine passing strategy. Full activation and deployment remain incomplete.

### Runtime qualification capital-domain binding — 2026-10-13

Scanner/admission now require an explicit researched execution_domain covered by the report's reviewed exact-byte pin: exchange environment, selected equity basis, researched equity range, percentage risk sizing, allowed leverages, and researched portfolio concurrency. Missing domain metadata is rejected rather than inferred from a declared $100 starting-equity replay. Existing reports do not contain an accepted runtime domain and remain insufficient for live activation; none have been upgraded or fabricated. Thirteen targeted domain/receipt/scanner tests pass. Domain tests use explicit isolated policy fixtures only. Strict mypy and Ruff pass for four changed execution modules. Actual capital/portfolio qualification and the pending operator equity/key decisions remain required. Job 89445 was confirmed live this turn. No VPS service action or exchange order occurred.

### Submission-time capital and pending-intention revalidation — 2026-10-13

The admission guard inside the writer lock now rereads authenticated account evidence, rechecks the report's researched capital/portfolio domain, and includes durable opening intentions not yet reflected in that account observation when evaluating concurrency. It recalculates the queued plan's stressed stop-risk requirement against current percentage trade risk and remaining daily allowance, preventing a plan sized before an equity loss from retaining an obsolete budget. Sixteen targeted domain/admission-time/order-policy checks pass; strict mypy and Ruff pass for the changed execution modules. The domain concurrency is evidence scope rather than a replacement fixed-dollar margin cap; qualifying the intended full portfolio still remains required. Qualification job 89445 was confirmed live this turn, with ETH/SOL logs through May 2026. No exchange order or VPS service action occurred. Full activation and deployment are incomplete.

### Triggered conditional child ownership binding — 2026-10-13

Gateway conditional recovery now validates the authenticated child order's exact orderId against actualOrderId, side against parent side, positionSide against parent positionSide, and reduceOnly=true on both parent and child before attributing its status or fills. Symbol-only matching was insufficient. Parametrized transport fixtures prove foreign child IDs, opposite-side children, position-mode mismatches, and lost reduce-only flags all fail closed, while valid NEW child state remains an unfilled acknowledgement. Seventeen targeted protective-executor/fill/coordinator tests pass, with strict mypy and Ruff on the changed gateway. Job 89445 remains live; ETH/SOL replay logs reached June 2026. No exchange order or VPS service action was performed. Genuine passing runtime qualification and actual deployment remain incomplete.

### Runtime health evidence separation — 2026-10-13

RuntimeSession now publishes atomic runtime-health.json observations with independent strategy-scan and protective-cycle error classes, actual market connection/generation/error state, and the last successful protective-cycle timestamp. A passing protective cycle cannot erase a rejected/failed scanner state. The success timestamp advances only after owned recovery completes without unresolved trades; it is not a deployment or entry-authority claim. Transport failures remain represented by sanitized exception classes. Five targeted session tests pass, including failed-recovery timestamp and scan-failure persistence checks; strict mypy and Ruff pass. Qualification handle 89445 remains live, with no accepted report observed this turn. No VPS service action or exchange order occurred. Genuine activation and deployment remain incomplete.

### Completed SOL ICT result and source-index completeness — 2026-10-13

SOL ICT official replay completed successfully as REJECTED, report SOLUSDT-adaa8118a7b399a0.json: 22 modeled trades, net -0.9146539720 USDT, stressed net -3.4253267090 USDT, drawdown 1.2673000280 USDT, one profitable window. Sample/net/stress/PF/window gates failed; drawdown and closed-at-end gates passed. Job 89445 remains live for other symbols. No threshold or rejected result was changed to force activation.

Qualification verification now requires source_files covering every claimed source digest in sources, including commissions/funding/minute-manifest hashes formerly named without resolvable paths. Indexed files must be inside the repository, unique, and match their exact byte hashes; omitted source hashes and changed bytes are rejected. This does not retroactively fabricate complete provenance for existing reports. Future accepted replay output must supply the complete actual index; current rejected reports stay rejected. Seven targeted receipt/scanner tests pass, with strict mypy and Ruff. No VPS service mutation or exchange order occurred. Full qualification, activation and deployment remain incomplete.

### ETH ICT result and composed Testnet runtime entry point — 2026-10-13

ETH ICT replay completed successfully as REJECTED: ETHUSDT-49e3fe2c6ff85b1c.json has 16 modeled trades, net -1.193408482 USDT, stressed net -3.104521339 USDT, drawdown 1.445735040 USDT, and one profitable window. Sample/net/stress/PF/window gates failed. The remaining batch continues; no qualification threshold or result was changed.

Added scripts/run_qualified_runtime.py composing the real gateway, shared account writer lease, owned lifecycle coordinator, measured persistent feed, explicit daily tracker, canonical scanner, entry admission, and runtime session. It requires genuinely admitted reports before credential/network access, explicit distinct writer/legacy Testnet credentials, a shared lease path, and an explicitly selected equity basis; no credential fallback is used. ACCOUNT is currently the only implemented basis and has not been selected by the operator. Current empty admission rejects startup before any network or lease mutation. Two targeted bootstrap tests and CLI --help pass; strict mypy and Ruff pass. This is composed local code, not a deployed or activated trader. Source/capital-domain completion, operator equity/key decisions, passing qualification, real runtime verification and deployment remain required. PID 87549 was not touched.

### Income evidence deduplication and immutability — 2026-10-13

Account observation now deduplicates both daily and ledger-query income records by incomeType/tranId before summation. A repeated transaction with a different amount, asset, or timestamp fails closed. A previously persisted transaction amount cannot silently be replaced by a later response. The authenticated daily-income loss display no longer doubles commissions because duplicate rows were returned; the canonical 5% circuit still uses DailyRiskTracker equity evidence. Twenty-two targeted remediation tests plus four income-evidence tests pass; strict mypy and Ruff pass for account_evidence.py. Qualification handle 89445 remains live; completed ETH/SOL ICT reports are genuine rejections. No exchange order or VPS service action occurred. Full qualification, activation and deployment remain incomplete.

### Late-fill cancellation and canceled-stop handling — 2026-10-13

ProtectiveExecutor cancellation identity now binds immutable target/plan/side/role fields while allowing the observed outstanding quantity or price context to change. A late fill during an UNKNOWN cancellation no longer creates a false identity collision, and the original command remains reconciled rather than reposted. PLACE identities still bind exact quantity/price. Protective lifecycle now treats a canceled stop with remaining verified owned exposure as failed protection and requests reduce-only flattening instead of attempting to reuse an old stop identity. Twenty targeted protective adapter/lifecycle tests pass, including timeout/late-fill and canceled-stop cases; strict mypy and Ruff pass for both changed modules. Job 89445 remains live; DOGE/BNB replays are progressing after genuine SOL/ETH rejections. No actual exchange order or VPS service action occurred. Full activation and deployment remain incomplete.

### Entry response ownership and cumulative-fill validation — 2026-10-13

LiveOrderBook now validates acknowledgements and order-query responses against the durable symbol, side, client ID, exact quantity/price and reduce-only intent, positive immutable exchange order ID, recognized status, and nondecreasing bounded cumulative fills before adopting exchange evidence. Invalid/missing responses become UNKNOWN for original-ID reconciliation rather than accepted ownership. Tests use complete explicit exchange-response fixtures. Thirty targeted order/remediation/coordinator tests and eight adversarial response-identity cases pass; strict mypy and Ruff pass for the changed module. Job 89445 remains live for remaining ICT symbols. No exchange order or VPS service action occurred; full activation and deployment remain incomplete.

### Clock-uncertainty-safe causal decision boundaries — 2026-10-13

CausalScanner now derives its completed-minute decision boundary from the earliest possible exchange time (aligned local time minus measured clock uncertainty), using ExchangeClock.completed_boundary. Midpoint time alone could falsely classify a scheduled REST close timestamp as completed just after a boundary while the exchange might still be in the prior minute. The observed uncertainty now delays evaluation until closure is provable; no forming candle is promoted by local-clock estimation. Eleven targeted clock/closed-history/scanner tests pass, with strict mypy and Ruff for both changed modules. Job 89445 remains live and remaining ICT replays are progressing. No exchange order or VPS service action occurred. Full qualification, activation and deployment remain incomplete.

### Confirmed protective cleanup propagation — 2026-10-13

ProtectiveExecutor now propagates an authenticated terminal cancellation response onto its original PLACE record, preserving the exchange's actual cumulative-fill response rather than leaving original protection marked active/unknown. Restart reconciliation skips that confirmed terminal record, so a later not-found query cannot erase confirmed cleanup or indefinitely occupy a prepared symbol. If a later cancellation resolves a record that was unresolved earlier in the same pass, it is removed from the final unresolved result. Fourteen targeted protective/coordinator tests pass, including real journal restart with mocked exchange-confirmed cancellation; strict mypy and Ruff pass. Qualification handle 89445 remains live. No actual exchange order or VPS service action occurred. Full qualification, activation and deployment remain incomplete.

### Protective response quantity/fill and trigger-state validation — 2026-10-13

ProtectiveExecutor now validates recognized actual status, positive exact PLACE quantity, bounded nondecreasing executed quantity, and zero fills for untriggered CONDITIONAL_NEW before replacing prior evidence. Invalid responses preserve the last valid exchange record. A triggered child retaining type STOP_MARKET is no longer normalized back to untriggered CONDITIONAL_NEW when its authenticated parent identifies actualOrderId, preventing false stop coverage. Sixteen targeted adapter tests pass, plus the earlier unchanged coordinator integration checks; strict mypy and Ruff pass. Qualification handle 89445 remains live for remaining pairs. No exchange order or VPS service action occurred. Full qualification, activation and deployment remain incomplete.

### Completed ICT rejection attribution — 2026-10-13

Created immutable completed-ict-rejection-assessment artifact from exact SHA-bound ETH/SOL/BTC reports and independently reconciled each sum of gross PnL minus fees/funding to reported net PnL. SOL gross +0.022470 USDT was overwhelmed by 0.9371239720 USDT fees. ETH gross -0.48029 USDT and BTC gross -0.253940 USDT were negative before fees. Exit-slice counts: ETH 16 CISD invalidations/one partial TP1; SOL 21 CISD invalidations/one time-or-window exit/one partial TP1; BTC five CISD invalidations. No modeled funding payment was recorded for these short-lived trades. Eligibility rejection counters are repeated engine evaluations, not distinct setups. Leverage feasibility rejected only 2 ETH, 2 SOL and 8 BTC evaluations, so those completed failures cannot be attributed solely to leverage eligibility. All three also fail stressed/net edge gates, independently of sample count. No gates, canonical mechanics, or rejection decisions were changed. Batch 89445 remains live for other symbols. This analysis is research evidence and grants no execution authority; full runtime qualification and deployment remain incomplete. No VPS service action occurred.

### Conditional migration acknowledgement truthfulness — 2026-10-13

Gateway migration to /fapi/v1/algoOrder now always carries the original/generated clientAlgoId and requires observed symbol, side, clientAlgoId, algoId, algoStatus, triggerPrice and quantity in a matching acknowledgement. It no longer supplies a requested ID, NEW status, or zero trigger price as missing response defaults. Normalized origQty/stopPrice/status are aliases of actual returned fields. Eleven targeted gateway tests pass, including missing-field responses and generated-ID migration; strict mypy and Ruff pass for the changed gateway. Official New Algo Order documentation was checked. Job 89445 remains live. No actual exchange order or VPS service action occurred. Full qualification, activation and deployment remain incomplete.

### Separate qualified-runtime deployment preparation — 2026-10-13

Read-only VPS inspection confirms autonomous-futures-trader.service active, MainPID 87549, NRestarts 0. Added a separate local systemd unit and rollout document for the composed qualified runtime, with a dedicated release path, durable state/account lease outside the release, restrictive umask and explicit credential/equity environment file. Neither file was installed, enabled or started on the VPS. The unit does not alter the original trader service. Rollout prerequisites preserve actual qualification/portfolio/source gates, operator equity and legacy-permission decisions, genuine UTC day-start evidence, measured feed readiness and exchange-confirmed protection. The admission manifest remains empty. Job 89445 remains live; DOGE/BNB progress logs reached August/July 2024 respectively. Full qualification, activation and deployment remain incomplete.

### Nonblocking admission provenance verification — 2026-10-13

EntryAdmission now performs historical report/source hashing in a worker thread instead of blocking the event loop that receives real market events. It samples actual current time again afterward and rechecks causal intention expiry before reading account evidence, so a slow verification cannot retain a pre-verification timestamp to bless stale balances or an expired signal. Four targeted admission-time tests pass, including concurrent event-loop progress during blocked verification and expiry after verification; strict mypy and Ruff pass. Job 89445 remains live for remaining ICT pairs. No exchange order or VPS service action occurred. Full qualification, activation and deployment remain incomplete.

### Persistent runtime-feed probe preparation — 2026-10-13

Added scripts/probe_persistent_market_feed.py, a bounded 90–150 second public Testnet probe of the actual LiveMarketFeed/RuntimeMicrostructure components. It records genuine trade/depth frames through an optional observer, observed clock/connection/gap/fit state, actual per-symbol acceptance or rejection, raw-trace SHA and implementation hashes. No order method is called, and the probe grants no execution authority. Code passes strict mypy/Ruff; existing targeted persistent-feed tests pass. This probe is prepared locally and has not yet been executed on the VPS; existing standalone microstructure evidence remains historical. Qualification handle 89445 remains live. No VPS service mutation occurred. Full qualification, activation and deployment remain incomplete.

### Actual persistent-feed VPS probe failure — 2026-10-13

Executed the read-only persistent feed probe in isolated VPS directory persistent-feed-probe-1075b2d788f0 after verifying 316 source file hashes. Probe session 97182 completed with exit 0 after 120 seconds. Its report and raw 5,021-frame trace were copied locally and trace SHA verified. Actual runtime outcome: connected, 56 resets/gaps, two remaining arrivals, no fit (insufficient warmup), and all 12 symbols rejected for missing genuine warmup. This is a failed runtime qualification, not live activation. Independent raw sequence checks found zero aggregate-trade or depth gaps; 4,519 frames were ahead of the midpoint clock estimate. This points to the ingress handling of observed clock uncertainty, requiring correction and another real probe before claiming feed readiness. Original trader read-only service verification after probe: active, MainPID 87549, NRestarts 0. No order method was called or service modified. Full qualification, activation and deployment remain incomplete.

### Measured clock uncertainty ingress correction — 2026-10-13

RuntimeMicrostructure ingress now accepts only future timestamps within explicitly observed clock uncertainty (bounded at 250ms), and LiveMarketFeed supplies each actual ExchangeClock uncertainty. Entry evidence remains conservative and continues its independent freshness/clock checks. Truly future or over-age frames remain rejected; no sequence IDs or prices are fabricated. Nine original targeted monitor/feed checks and the new bounded-future sequence regression pass; strict mypy/Ruff pass. Retrospective replay of the actual 5,021-frame VPS trace using its final recorded 143ms uncertainty produced zero gaps/resets and retained 2,084 arrivals, versus 56 resets before correction. This is explicitly a retrospective diagnostic, not a new live qualification. The next probe now records each frame's contemporaneous clock to support exact uncertainty replay. Another real VPS probe remains required. Qualification batch 89445 is still live; no service or order action was performed this turn. Full activation and deployment remain incomplete.

### Corrected persistent-feed actual VPS retest — 2026-10-13

Executed source-hash-verified isolated read-only probe persistent-feed-probe-3fba4cbf4abf (316 files), process session 43554, for 120 seconds. It completed with exit 0. Copied actual report/raw per-frame-clock trace to vps-persistent-feed-1791835118121952966.json/jsonl and verified trace SHA. Real results: connected, zero sequence gaps, zero stale ingress frames, 2,280 retained arrivals, completed fit without fit/feed error. Measured rho=1.0056405364602867 fails the mandatory rho<1 gate. No symbol was accepted: ETH/SOL/APT explicitly fail measured supercriticality; others failed the current evidence freshness gate. Continuity/warmup correction is demonstrated, but this is not entry authority or live activation. No order methods were called. Post-probe original service inspection: active, MainPID 87549, NRestarts 0. Main trader/web services were not modified. Genuine passing strategy/portfolio qualification, qualifying current microstructure, operator equity/key decisions and actual production rollout remain incomplete.

### Consistent observed-clock evidence validation — 2026-10-13

MicrostructureEvidence/RuntimeMicrostructure now use explicit bounded observed clock uncertainty for evidence freshness, matching ingress and ExchangeClock: timestamp age must be at least minus uncertainty and worst-case age at most 500ms (20 seconds for fit). EntryAdmission and the read-only probe supply actual clock uncertainty. This avoids falsely classifying a genuine slightly future midpoint timestamp as stale while preserving worst-case latency and mandatory rho<1. Fifteen targeted clock-bound/monitor/feed tests pass, with strict mypy for three affected modules. The previously measured live rho=1.0056405364602867 remains rejected; no entry authority was created by this correction. Qualification handle 89445 was confirmed live this turn. No VPS service or order action occurred. Full qualification, activation and deployment remain incomplete.

### Explicit authenticated account/order boolean evidence — 2026-10-13

Account observers/readers now require an explicit valid multiAssetsMargin boolean; missing margin-mode data cannot silently establish single-asset USDT reconciliation. Live pending-order checks parse reduceOnly explicitly, so textual false no longer becomes truthy and skips opening-order validation. Invalid booleans fail closed rather than supplying false mock defaults. Thirty-two targeted remediation/order/session tests plus ten boolean-evidence cases pass; strict mypy and Ruff pass for the changed modules. Qualification handle 89445 remains live, DOGE replay through April 2025 at this turn's inspection. No VPS service or order action occurred. Full qualification, activation and deployment remain incomplete.

### Archive-manifest source-chain validation — 2026-10-13

Qualification source verification now checks each indexed .zip.manifest.json against its actual sibling archive bytes and saved published .CHECKSUM filename/digest, rather than accepting matching manifest bytes alone. A source archive cannot change behind an unchanged indexed manifest. Six targeted receipt tests pass, including altered archive bytes; strict mypy and Ruff pass. The actual SOL January 2023 archive/manifest/published-checksum chain also passed the new verifier. Qualification handle 89445 remains live. No VPS service or order action occurred. Full qualification, activation and deployment remain incomplete.

### Reproducible source attestations for completed ICT reports — 2026-10-13

Added attest_runtime_report_sources.py to resolve report source digests to actual repository files, verify complete source coverage plus archive/checksum chains, and write immutable companion attestations referencing the exact original report SHA/decision. It never edits metrics, gates or original report bytes and grants no execution authority. Successfully attested actual completed BTC, ETH and SOL reports; their decisions remain REJECTED. Two targeted utility tests verify immutable rejection preservation/idempotence and refusal of changed source bytes. Strict mypy/Ruff pass for the script. Job 89445 remains live for the remaining universe. No VPS service or order action occurred. Full qualification, activation and deployment remain incomplete.

### Completed DOGE ICT qualification — 2026-10-13

DOGE ICT replay completed as REJECTED, immutable report DOGEUSDT-ceb4bb44db0827aa.json: 15 modeled trades, net -1.23462982800000 USDT, stressed net -2.49244888600000 USDT, drawdown 1.25649254800000 USDT, zero profitable windows. Sample/net/stress/PF/window gates failed; drawdown/closed-at-end gates passed. Verified its actual source files and archive/checksum chains into an immutable companion source attestation; original report/decision unchanged. Batch handle 89445 remains live for other pairs. No qualification gate, trading service or exchange order was changed. Full activation and deployment remain incomplete.

### Completed BNB ICT qualification — 2026-10-13

BNB ICT replay completed as REJECTED, report BNBUSDT-42064f1aee90f7b1.json: 10 modeled trades, net -0.720600720 USDT, stressed net -1.802950190 USDT, drawdown 0.761752920 USDT, zero profitable windows. Sample/net/stress/PF/window gates failed; drawdown/closed-at-end gates passed. Verified the actual source-file and archive/checksum chains into an immutable companion attestation without changing original report bytes or decision. Five completed ICT symbols (BTC/ETH/SOL/DOGE/BNB) are rejected; remaining universe jobs continue under handle 89445. No gate or trading service was changed; no exchange order was submitted. Full qualification, activation and deployment remain incomplete.

### Actual authenticated account observer VPS probe — 2026-10-13

Executed isolated source-hash-verified read-only account probe account-probe-5ce8fcda49fc (316 files). It completed successfully using real authenticated Testnet REST. Copied original account/ledger/result JSON and verified exact account observation SHA. Actual equity 4224.09882354 USDT; wallet and equity drifts both 0E-8; zero open ordinary/conditional orders; all 743 returned position records are flat (zero open positions). Daily risk correctly remains unverified because the equity reference is unconfigured; no day-start baseline or execution authority was invented. The original probe-result field positions counted raw records, so an explicitly derived numeric assessment records the zero open-position count; the original evidence is preserved. Future probe output labels records/open positions separately. Read-only post-probe trader verification: active, PID 87549, NRestarts 0. No order method or service action occurred. Probe script passes strict mypy/Ruff. Full qualification, activation and deployment remain incomplete.


### XRP ICT qualification completion

The running bounded universe batch completed XRPUSDT with exit code 0. Immutable report `artifacts/qualification/runtime-ict-universe/XRPUSDT-609ae5374df9d842.json` is REJECTED: 8 trades, net PnL 0.0775540160000 USDT, stress net PnL -0.7510149550000 USDT, drawdown 1.0357461540000 USDT, and only one profitable window. Samples, stress and window gates fail. Actual source hashes were verified into companion `artifacts/qualification/source-attestations/XRPUSDT-source-attestation-efb10d44e63131ab.json`; this does not grant execution authority. Batch session 89445 remains running; SUI has reached May 2026. No trading service control or orders were performed. The approved daily-loss policy remains 5% of genuine day-start equity.


### Closed-candle ICT live exit integration and SUI completion

Added `execution/exit_invalidation.py` and wired its real ClosedHistoryReader and measured ExchangeClock into the qualified runtime coordinator. The rule explicitly matches the frozen replay: completed 1m close <= planned entry for BUY, >= planned entry for SELL, only after the first authenticated fill. It is entry-level close invalidation, not a newly detected CISD threshold. Forming candles are excluded using clock uncertainty; each observed symbol/minute is cached. Missing clock/history or bounded read timeout requests protective flattening of reconciled owned exposure. The existing ownership check and UNKNOWN/triggered-close reconciliation remain authoritative, and prearmed stops remain until exchange fills prove flat. No research-bound source was edited during the batch.

Validation: 23 targeted tests initially passed across exit reader, protective lifecycle, coordinator and runtime bootstrap. Two coordinator cases were then added for genuine closed-price invalidation and unavailable history; 14 tests for the changed reader/coordinator tests passed. Strict mypy passed on all four changed source files; Ruff passed. Fixtures mock exchange I/O and are not live evidence. Nothing was installed or started as a trading service.

SUI replay completed with exit code 0 and REJECTED report `runtime-ict-universe/SUIUSDT-7d6bda9a3310222c.json`: 19 trades, net -0.538457906000000 USDT, stress -2.128611387000000 USDT, drawdown 0.960273504000000 USDT, one profitable window. Samples, net edge, stress, profit factor and windows fail. Source attestation was generated from real stored source bytes. Batch handle 89445 remains confirmed live, now processing AVAX and NEAR.


### ICT exit recovery and exchange terminal-state consistency

The closed-exit reader now checks every available completed 1m candle since the authenticated first fill, retaining the first invalidating close even if price later rebounds. Its cached history is re-evaluated for each trade fill time, preventing old-trade invalidation from leaking to a later trade on the same symbol. Incomplete fill-to-present history fails closed; the coordinator durably latches invalidation. Sixteen targeted reader/coordinator tests passed, with strict mypy and Ruff checks.

Unified lifecycle terminal handling with the exchange adapters: EXPIRED_IN_MATCH is terminal for entries and prepared stops, and any terminal stop with reconciled owned exposure requests reduce-only flattening instead of treating it as valid protection. Seventeen targeted protective/coordinator tests passed after this change; mypy and Ruff passed. No research-bound source changes, new orders, or service control occurred. Batch handle 89445 was polled and remains running.


### Available-margin admission audit

Current `LiveOrderBook.submit` reserves exchange-unobserved journal opening notional/leverage and checks authenticated availableBalance, but does not reserve entry commission headroom. Admission does not yet obtain a current authenticated per-symbol commission rate for this calculation. The historical actual Testnet commission snapshot is research evidence, not an indefinitely valid runtime fee assumption. This remains an unresolved live admission requirement; do not claim available-margin completeness or activate solely from the existing margin check. This audit did not change research sources, order state, credentials, or running services. Universe session 89445 remains live; AVAX reached May 2024 and NEAR January 2024 on the observed checkpoints.


### Authenticated commission headroom in qualified entry admission

Added `execution/commission_headroom.py` and wired it into EntryAdmission. It reads actual signed /fapi/v1/commissionRate responses bound to each required symbol, validates finite rates, and limits receipt age to 30 seconds. The final synchronous writer guard checks current availableBalance against proposed initial margin plus entry maker fee, exchange-observed pending-opening fees, and exchange-unobserved journal initial margin plus maker fee. Exchange-observed order margin is not reserved twice. Rebates cannot fund orders before a fill credits them. Missing fee evidence for a new pending symbol and unvalued opening conditional orders fail closed. The standalone low-level writer API has not gained this fee evidence requirement; the qualified deployment entry path always supplies the final guard.

Thirteen targeted tests passed for this helper and changed admission timing path, covering exact margin boundary, observed/unobserved order reservation, expiration/future timestamps, new-symbol races, rebates, authenticated response symbol binding and unvalued conditional exposure. Strict mypy and Ruff passed on both changed source files. Unit fixtures are mocked I/O, not live commission/lifecycle verification. Endpoint specification was checked against the official Binance connector and documentation. No research-bound source, trading service, or exchange order was changed.


### Pending fee-rate ordering check

Exchange-observed pending orders now reserve the higher of their actual authenticated maker and taker rates, because their execution role is not guaranteed and no hardcoded fee-tier ordering is assumed. Journal-only GTX intentions still use their authenticated maker rate. Ten targeted commission tests passed, including a maker-higher-than-taker case; mypy and Ruff passed. Qualification handle 89445 remains live: AVAX reached March 2025 and NEAR December 2024 at the observed checkpoints. No orders or service-control actions were performed.


### AVAX canonical ICT qualification completion

Batch handle 89445 completed AVAXUSDT with exit code 0. Immutable report `artifacts/qualification/runtime-ict-universe/AVAXUSDT-958a4287e61c5107.json` is REJECTED: 10 trades, net PnL -0.63350480 USDT, stressed net -1.70950710 USDT, drawdown 0.96589560 USDT, zero profitable windows. Samples, net edge, stress, profit factor and window gates fail; drawdown and closed-at-end gates pass. Actual source bytes were verified into a companion source attestation. No metrics or thresholds were changed to grant authority. NEAR remains in progress and the batch has moved to the next queued pair. No exchange orders or service-control actions were performed.


### NEAR canonical ICT qualification completion

Batch handle 89445 completed NEARUSDT with exit code 0. Immutable report `artifacts/qualification/runtime-ict-universe/NEARUSDT-1ecddae07844f84e.json` is REJECTED: 12 trades, net PnL -1.49970340 USDT, stressed net -2.49339130 USDT, drawdown 1.58859140 USDT, zero profitable windows. Samples, net edge, stress, profit factor and window gates fail. Actual source bytes were verified into a companion source attestation. No metrics or thresholds were changed to grant authority. Remaining LINK, APT and ADA replays are still handled by the confirmed running batch. No exchange orders or trading-service changes were performed.


### Fresh VPS measured feed probe with current clock-bound freshness

Staged 318 source files in new isolated `/opt/autonomous-futures-bot/artifacts/qualification/persistent-feed-probe-fd1cd2aac91d`; all source hashes verified before execution. Finite public Testnet feed probe session 98972 completed exit code 0 after the 120-second measurement. Local original result and trace: `artifacts/qualification/runtime-microstructure/persistent-feed-1791845150676454692.{json,jsonl}`. Trace SHA and all five declared implementation SHA values matched actual bytes. Measured connected=true, 0 gaps, 0 stale ingress frames, 2234 arrivals, no feed or fit error, rho=0.99763996158228. BNB, XRP, NEAR, LINK and ADA passed instantaneous market evidence; the other seven failed trade/depth freshness. This is an expiring read-only microstructure snapshot, not a qualifying strategy report, sustained regime guarantee, order fill, or execution authority. No gating thresholds were altered.

After the probe, a real read-only systemctl query confirmed original trader ActiveState=active, MainPID=87549, NRestarts=0. No trading service was stopped, restarted, signaled or replaced, and no exchange orders were submitted by this probe. Historical qualification batch handle 89445 remains running.


### Measured report source-verification latency

Measured the actual NEAR report source index through the production verifier against 51 real indexed files and archive/checksum chains. Local elapsed time was 0.11726130000170087 seconds with recently read files; evidence is `artifacts/qualification/runtime-inputs/near-source-verification-timing.json`. This does not measure cold-cache or VPS latency and grants no execution authority. No cache or stat-only substitution was added: current cryptographic source verification remains intact. Batch 89445 remains confirmed live; LINK reached April 2024 and APT February 2024 at the observed checkpoints.


### Operator capital basis and same-account Testnet key-fencing selection

The human selected actual exchange account equity for the 5% genuine day-start daily-loss budget, and selected making the legacy key read-only plus provisioning a distinct trading key on the same Testnet account while leaving PID 87549 running. These decisions supersede earlier unresolved-choice notes. A read-only VPS inspection found no qualified environment or release; created only `/opt/autonomous-futures-bot/.env.qualified-runtime` with AFBOT_EQUITY_BASIS=ACCOUNT using exclusive creation and mode 0600, fsync. It contains no credentials. No legacy environment, service unit, exchange permission or order was changed. Credential provisioning and actual permission verification remain incomplete; selection alone is not evidence of read-only fencing. Qualification handle 89445 remains live: LINK reached September 2025 and APT July 2025 at the observed checkpoints.


### Operator reverted to reuse of the existing Testnet API key

The operator now requests reuse of the existing Testnet API key, superseding the distinct-key/read-only-key plan above. This choice does not remove the active-writer conflict: the key remains available to the protected legacy daemon, exchange permissions are key-wide, the qualified bootstrap rejects identical writer and legacy credentials, and entry admission requires the legacy key to be read-only. PID 87549 must not be stopped, restarted, killed, or signaled. The qualified service must remain unstarted until a verified single-writer handoff path exists. The basis-only qualified environment still contains only AFBOT_EQUITY_BASIS=ACCOUNT; the requested credentials and any permission change have not been applied. The interrupted qualification process is no longer present; LINK/APT/ADA are being rerun in a separate output directory from frozen inputs.


### Hawkes fit boundary audit and fail-closed admission

Re-examined the actual 120-second Testnet feed fit stored in `artifacts/qualification/runtime-microstructure/persistent-feed-1791845150676454692.json`. Although the point estimate was rho=0.99763996158228 with 2,234 arrivals and no sequence gaps, every one of its 12 baseline rates was exactly 1e-9, the optimizer's hard lower bound. The earlier symbol-level passes are therefore not valid fit evidence. `HawkesFit` now records symbols whose fitted baseline is within 0.1% of that bound; the runtime preserves the fit for diagnostics but reports the boundary condition and refuses microstructure entry evidence whenever any dimension is pinned. Re-fitting the saved real feed trace against the current implementation again pinned all 12 baselines (rho=0.9988503691527311 on the full trace; that rolling sample differs from the original fit window). The two targeted test files passed, 9 tests total. No strategy, report gate, or exchange state changed. ICT qualification batch session 52126 remains live; LINK and APT progress through February 2024, with ADA queued.


### Mandatory final entry admission at the order book boundary

`LiveOrderBook.submit` now rejects every opening order that does not carry the integrated final entry guard, even if the caller supplies `qualified=True` and a subcritical rho. Reduce-only exits remain available through the lifecycle path. Six focused order-submission tests passed, and Ruff passed on the changed implementation and test files. No order or VPS service was touched.


### Final ICT universe batch progress

Qualification process session 52126 is confirmed live. From frozen policy and immutable source inputs, LINK and APT have each replayed through 2025-02-24 (latest checkpoint `through_ms=1740355200000`); their checkpoint wallets are 100.814196454 and 99.5472964400 USDT respectively. These are progress checkpoints, not final metrics or decisions. ADA is queued. No strategy or qualification source changed during this run.


### Hawkes per-coefficient sample gate and real-trace replay

`fit_arrivals` now requires at least 30 observed events per fitted coefficient. In the 12-symbol model, each output dimension estimates 13 coefficients, so each dimension needs at least 390 post-burn-in arrivals. The gate reports every symbol's observed count when it rejects a fit. Replayed the saved 120-second Testnet trace through the current `RuntimeMicrostructure`: 2,234 retained trade arrivals, zero gaps, zero stale frames, and post-burn-in counts BTC 175, ETH 221, SOL 133, DOGE 126, BNB 144, XRP 113, SUI 130, AVAX 102, NEAR 118, LINK 112, APT 134, ADA 123. No Hawkes fit was produced. Targeted measured-Hawkes/runtime-microstructure tests pass (10); Ruff passes for the changed fitter and test. This trace remains insufficient for entry admission. No market orders, API-key changes, or VPS service actions occurred.


### Final ICT universe batch progress - 13 October 2026

Qualification parent process 14412 and symbol workers 17876 (LINK) and 43704 (APT) are confirmed live against frozen inputs in `artifacts/qualification/runtime-ict-universe-final3-20261013`. Both latest checkpoints reached 2025-05-25 (`through_ms=1748131200000`): LINK wallet 100.393153064 USDT; APT wallet 101.4390933400 USDT. These remain progress checkpoints, not final metrics or qualification decisions; ADA has not started. Do not restart this run. No strategy or qualification gates changed.


### Final ICT APT replay - rejected

The frozen APTUSDT ICT replay completed with **REJECTED**: 12 trades against the 30-trade minimum, net PnL +0.6722668940 USDT, stressed net PnL -0.4654765620 USDT, drawdown 0.7668264460 USDT, and one profitable window against the required three. The source report's per-trade net and stressed PnL reconcile exactly to those totals using Decimal arithmetic. Gates: samples=false, net_edge=true, stress=false, profit_factor=true, drawdown=true, windows=false, closed_at_end=true. No gate was changed to improve this result.

Report: `artifacts/qualification/runtime-ict-universe-final3-20261013/APTUSDT-e3e296ef0445ade7.json` (SHA-256 `6f2a851e8922d5ff16c6eaa9880854b49049d085f0870a7207756d1ed1eb8718`). Source attestation `APTUSDT-source-attestation-86afdabf89f2c53b.json` verified 51 indexed source files and records `original_decision=REJECTED`, `execution_authority=false`. This is historical OHLCV replay evidence, not actual fills.

The same qualification parent remains active: LINK worker 17876 has checkpointed through 2026-07-19 (`through_ms=1784419200000`, wallet 100.167260032 USDT). ADA worker 17328 has started against the frozen policy and source cache; its first policy record is present, with no strategy checkpoint yet. APT's worker has exited normally after writing its report. The deployment admission list remains empty, and neither the VPS service nor API key was changed.


### Final ICT LINK replay - rejected

The frozen LINKUSDT ICT replay completed with **REJECTED**: 16 trades against the 30-trade minimum, net PnL +0.097026848 USDT, stressed net PnL -1.724134189 USDT, drawdown 1.089347778 USDT, and one profitable window against the required three. Decimal sums from the individual trades reconcile to both net totals. Gates: samples=false, net_edge=true, stress=false, profit_factor=false, drawdown=true, windows=false, closed_at_end=true. No gate was changed.

Report: `artifacts/qualification/runtime-ict-universe-final3-20261013/LINKUSDT-4afbc0621ee03c3f.json` (SHA-256 `cbf3d99d743faa19845ada819a1ea72f7183281b686005ac6bcb88a33932b4a4`). Source attestation `LINKUSDT-source-attestation-5155179988494770.json` verified 51 indexed source files and records `original_decision=REJECTED`, `execution_authority=false`. This is historical OHLCV replay evidence, not actual fills.

ADA remains the only unfinished ICT symbol in this batch. Worker 17328 is active against the same frozen inputs and reached 2024-01-31 (`through_ms=1706659200000`, checkpoint wallet 100 USDT). No activation or deployment authority exists.


### Final ICT ADA replay and batch completion - rejected

The frozen ADAUSDT ICT replay completed with **REJECTED**: 17 trades against the 30-trade minimum, net PnL -1.5083578671700 USDT, stressed net PnL -2.8767925471700 USDT, drawdown 2.1248552600000 USDT, and zero profitable windows against the required three. Decimal sums from individual trades reconcile to both reported net totals. Gates: samples=false, net_edge=false, stress=false, profit_factor=false, drawdown=true, windows=false, closed_at_end=true. The report was source-attested against 51 indexed files; its attestation records `original_decision=REJECTED` and `execution_authority=false`.

Report: `artifacts/qualification/runtime-ict-universe-final3-20261013/ADAUSDT-202b8e14963c011d.json` (SHA-256 `be01923f5cbd2d1178d531f42c6e1e81e28b926efdc2bf48c48b28b3977769b6`). Attestation: `ADAUSDT-source-attestation-d25d6a59adf5073d.json`. The frozen batch process-results file confirms APTUSDT, LINKUSDT, and ADAUSDT each exited 0; all three decisions are REJECTED. Together with the nine already completed ICT rejections and eleven Macro Scalper rejections, no strategy qualified. This batch is historical OHLCV replay, not actual fills; deployment admission remains empty. The existing Testnet key, VPS service, and PID 87549 were untouched.

### ICT directional-resolution correction and frozen requalification

The Step 1 resolver previously chose bearish whenever both directional 5m CISD candidates existed and also defaulted to bearish when both directional PDA sets were touched without a confirmed displacement. The implementation now preserves each candidate's confirming candle, chooses the later confirmed 5m CISD, rejects same-candle ties, and leaves unresolved two-sided PDA state idle. A single-direction PDA still enters Step 2, where the full anchored CISD remains required. The focused ICT strategy test file passes (43 tests); Ruff passes for the changed implementation and test.

A new full 12-pair ICT replay has been started from the existing frozen official market-data cache and commission snapshot in `artifacts/qualification/runtime-ict-directional-fix-20261013`. It uses the unchanged frozen capital and qualification gates. No report from this run has yet been admitted, and no earlier rejection was changed. The user's selected Testnet credential is the existing API key; the qualified bootstrap and entry fence still need a safe single-writer design before that key can be used. The legacy daemon, its API access, VPS unit, and PID 87549 remain untouched.

### Existing Testnet key reuse with single-writer admission fence

The operator confirmed the existing Testnet API key must be reused. The qualified bootstrap now reads only the existing `BINANCE_TESTNET_API_KEY` and `BINANCE_TESTNET_SECRET_KEY` pair; it no longer requires a second writer credential or performs a key-permission write probe. Added `LegacyWriterHandoffGuard`, which fails closed unless a read-only systemd query reports the legacy service loaded but disabled, `Restart=no`, `ActiveState=inactive`, `SubState=dead`, and `MainPID=0`. Runtime startup checks this before credential/network use; entry admission checks it before lifecycle preparation and again at the final order guard. The existing daemon and key permissions were not changed.

Focused tests passed: 23 tests across qualified bootstrap, entry-admission timing, runtime session, and the handoff guard; Ruff and strict mypy passed on the changed runtime sources. The active local unit definition still has `Restart=always`; no VPS state has been changed, and the remote service status has not been freshly verified. The same-key qualified runtime must remain unstarted while the protected daemon may be active. The secure environment file still contains only `AFBOT_EQUITY_BASIS=ACCOUNT`.

### Directional-fix ICT requalification results: BTC and ETH rejected

The frozen BTCUSDT replay completed **REJECTED** with 10 trades, net PnL -0.90222265000000 USDT, stressed net PnL -2.07246230000000 USDT, drawdown 0.98569904000000 USDT, and zero profitable windows. Directions are balanced (5 SELL, 5 BUY); all 10 trades exited by CISD invalidation. Decimal trade totals reconcile: gross -0.463380 plus fees 0.4388426500 equals net -0.90222265000000; stressed net sums to -2.07246230000000. Samples, net edge, stress, profit-factor and window gates fail; drawdown and closed-at-end pass. Report `artifacts/qualification/runtime-ict-directional-fix-20261013/BTCUSDT-417cc8282169eced.json` (SHA-256 `66c39f14cf6ec0c226cfc84a084279c10c2b407674268a71537056561ac55b32`); source attestation `BTCUSDT-source-attestation-ee7e0f3d3e0426ab.json` verifies 51 source files and records `execution_authority=false`.

The frozen ETHUSDT replay completed **REJECTED** with 25 trades, net PnL -1.938910714 USDT, stressed net PnL -4.474138908 USDT, drawdown 2.027570602 USDT, and zero profitable windows. Directions now include 15 SELL and 10 BUY; 25 trades exited through CISD invalidation and one partial TP1 exit was recorded. Decimal totals reconcile: gross -0.99180 plus fees 0.947110714 equals net -1.938910714; stressed net sums to -4.474138908. Samples, net edge, stress, profit-factor and window gates fail; drawdown and closed-at-end pass. Report `artifacts/qualification/runtime-ict-directional-fix-20261013/ETHUSDT-84f467ba4157ba49.json` (SHA-256 `0376d4e5445a2a53b775ff87cfe68b69badb3086373caa5033febe9fe8301e0d`); source attestation `ETHUSDT-source-attestation-649ae0dd543582a8.json` verifies 51 source files and records `execution_authority=false`.

These completed rejections remain immutable and neither report is admitted. BTC and ETH are finished; SOL and DOGE workers are active in the same two-worker batch. No exchange orders or VPS actions occurred.

### Qualification activation-domain audit — 2026-10-13

The deployment reader requires every admitted report to bind a `researched-execution-domain-v1`, including Testnet, equity basis, equity interval, daily/trade risk, leverage and concurrent-symbol capacity. The existing per-symbol ICT and Macro Scalper reports do not include that domain; the scanner therefore cannot admit any of them, even if an individual report passes its historical gates. Their isolated 100-USDT replays also do not establish shared-wallet multi-symbol risk. A shared portfolio qualification and its reviewed execution domain are required before populating `deploy/qualification-admission.json`.

### Qualification throughput and measured-feed calibration update — 2026-10-13

The universe runner now accepts an explicit worker count from 1 to 4 and defaults to four for later batches. The active ICT directional-fix batch was already running with two workers and has been left on its frozen implementation; SOL and DOGE checkpointed through 2025-06-24. Its reports remain incomplete until each symbol writes a final report.

The runtime Hawkes arrival-retention window now defaults to 900 seconds rather than 180 seconds, while preserving the 390-post-burn-in-arrivals-per-symbol requirement and boundary-fit rejection. The window is validated and exposed in runtime health; the finite public probe accepts a matching duration. A separate diagnostic captures real Testnet trade/depth frames and fits on exchange event timestamps, explicitly marking clock freshness unchecked and execution authority false. It is currently running locally. The production feed still enforces its original clock interlock: five local exchange-clock samples consistently measured 1.33–1.38 seconds of Windows clock offset, beyond the 1-second limit. No clock or freshness gate was relaxed. The earlier zero-frame local probe was stopped; no VPS process was involved.

Targeted runtime microstructure, feed, session, lifecycle and admission checks passed (67 tests); Ruff and strict mypy passed on the changed sources. The public probe uses no order methods. SSH to Kainode timed out during the read-only service query, so the daemon's current state remains unverified; PID 87549 and all VPS services remain untouched.

### Exchange-clock correction and 15-minute Hawkes sample — 2026-10-13

The local clock offset was stable at approximately +1.35 seconds. `ExchangeClock` already aligns local receive time to Binance server time and carries half-RTT uncertainty, so the former absolute 1-second rejection prevented valid corrected timestamps. Its correctable-offset bound is now 2 seconds; freshness remains at 500 ms, RTT uncertainty remains bounded at 500 ms, calibration expiry remains 180 seconds, and fit/evidence bounds are unchanged. Focused exchange-clock, microstructure-boundary and live-feed tests pass (14); Ruff and strict mypy pass. A 20-second public Testnet feed check connected all 12 pairs with offset 1,367 ms, uncertainty 64 ms and 238 trade arrivals. This is diagnostic evidence only and grants no execution authority.

The completed 900-second exchange-event-time diagnostic connected and recorded 40,405 frames and 4,444 trade arrivals. It correctly produced no Hawkes fit: eight symbols had fewer than the required 390 post-burn-in arrivals (minimum 269). The 390-arrival gate and boundary-pinned-baseline rejection are unchanged. The saved trace uses Windows CRLF, while that diagnostic version hashed LF bytes; normalizing line endings reproduces the declared digest exactly. The probe now hashes the closed trace file's actual bytes and has a receive timeout so an idle stream cannot hang beyond its requested duration. The full 900-second persistent-feed check using corrected clock alignment is still in progress; its completion report is required before changing the default fit window or claiming live microstructure qualification.

The 900-second production-path probe completed with connected=true, all 12 symbols observed, zero sequence gaps, 1,134 stale frames, and 16,405 retained arrivals. Every symbol exceeded 390 arrivals, but the Hawkes fit remained **REJECTED**: rho=1.0002938385641917 and all 12 baseline estimates were pinned to the optimizer lower bound. No symbol had execution evidence; `execution_authority=false`. The 20,671,635-byte trace SHA-256 and all five implementation hashes verify against the report. The runtime default and both probe defaults are now 1,800 seconds; the 390-arrival and boundary-baseline gates are unchanged. The persistent probe now flushes its trace periodically and records the feed generation and duplicate count for replay audit. Targeted checks pass (33 tests; Ruff and strict mypy clean). A new 1,800-second production-path probe is running locally; it uses public Testnet market data only and submits no orders.

### Daily-loss telemetry aligned with verified day-start equity — 2026-10-13

`observe_account` now publishes `daily_loss_usdt` from the verified `DailyRiskTracker` result when available. Its former fallback added lifetime unrealized PnL to today's realized income, which could count an unrealized loss already present at the UTC day-start equity baseline as a new daily loss. A targeted regression covers a carried position whose unrealized loss is unchanged from the verified baseline. `tests/unit/test_production_remediation.py` passes (23 tests); Ruff and strict mypy pass for the modified implementation. No trading order or VPS action occurred.


### Runtime Hawkes parameter bound to independent Testnet traces — 13 October 2026

The completed 30-minute public Testnet feed trace contains 34,338 trade arrivals across all 12 pairs. The previously selected beta=7.5/s was profiled on this independent trace: no baseline was pinned to the optimizer floor and rho=0.7447951376677655. Along with the earlier selection trace, a new immutable calibration record binds both profile hashes, distinct trace hashes, the fitting implementation hash, per-trace coverage, and the 12-pair universe. It explicitly sets `execution_authority=false` and `qualification=false`.

The qualified runtime now requires this evidence-backed calibration at startup, passes beta=7.5/s to the measured Hawkes fitter, checks that profile symbols match the runtime universe, and reports the calibration hash, beta, trace hashes, and fitted beta in runtime health. Read-only probe CLIs also require an explicit calibration artifact. The calibration parameter does not admit a strategy or bypass any market freshness, rho, sequence, qualification, account, or protective-order gate. The qualified systemd unit now supplies the required artifact path.

Focused validation passed: 40 targeted tests for calibration loading and mutation, microstructure fitting/evidence, feed/session startup, scanner admission, and runtime bootstrap; Ruff and formatting checks passed. `run_qualified_runtime.py --help` confirms calibration is required. No live orders, systemd actions, API-key changes, or VPS changes occurred. The frozen 12-pair ICT batch remains live: BTC, ETH, SOL, and DOGE are rejected; BNB and XRP are progressing; six symbols remain queued. The admission manifest remains empty and protected PID 87549 remains untouched.

An additional 69 targeted protective-lifecycle checks passed across lifecycle reduction, durable protective I/O, coordinator recovery, fill reconciliation, causal exits, admission timing, and daily-risk behavior. These tests exercise deterministic exchange-response fixtures and do not count as live exchange execution proof. At the latest process checkpoint BNB had replayed through 2024-07-29 and XRP through 2024-08-27; the original two-worker batch remains active and was not interrupted.

### Capital policy and isolated VPS replay update — 2026-10-13

The user subsequently selected actual exchange ACCOUNT equity as the daily-loss basis and
accepted a 0.25% actual-account-equity risk budget per trade. The runtime default remains
0.5% until the currently running frozen replay results and source attestations are
preserved, because `trade_plan.py` is implementation-hash-bound in those reports. No
candidate is admitted, so the selected 0.25% policy has not granted live execution
authority. The 5% UTC day-start loss cutoff remains unchanged.

Two credential-free low-priority VPS units now use four worker cores total. At 2026-10-13
20:01 MYT, LINK was checkpointed through 2024-04-30 UTC, NEAR through 2024-03-31 UTC, and
APT/ADA through 2024-03-01 UTC. Both replay units remained active. The protected user-level
trader remained active at PID 87549 with NRestarts=0. No production unit, API key, or
exchange orders were changed.

Locally, qualified admission now verifies authenticated Binance position-mode evidence
and rejects Hedge Mode before preparing protection or submitting entries. Gateway
credentials are isolated by selected environment; signed requests fail closed when that
environment has no key pair, with no literal mock credentials. Focused tests passed (39),
as did Ruff and strict mypy on the modified Python sources. These changes have not been
installed on the VPS.

### Latest frozen-replay checkpoint — 2026-10-13 20:20 MYT

A fresh pinned read-only SSH query found both credential-free VPS replay units active with
`NRestarts=0`. NEAR, LINK and ADA checkpointed through 2024-06-29 UTC; APT through
2024-05-30 UTC. All four symbol processes were using about one CPU each. No final reports
were present. The protected trader remained active
at PID 87549 with `NRestarts=0`; it was not signaled or controlled.

The user confirmed 0.25% of actual account equity as the per-trade risk recommendation.
The in-flight frozen replay sidecar records 0.5%, so its outputs may be retained as
diagnostics but cannot establish qualification under the selected 0.25% policy. Preserve
the current reports and attestations before changing hash-bound source; then freeze and
qualify the approved 0.25% policy explicitly. The read-only checkpoint made no VPS service,
API-key, account-setting, or exchange-order changes.

### Read-only qualification checkpoint — 2026-10-13 20:25 MYT

Both credential-free replay units remained active with `NRestarts=0`. NEAR and LINK had
checkpointed through 2024-07-29 UTC, with wallet balances 99.69289040 and 99.890925178
USDT. APT and ADA had checkpointed through 2024-06-29 UTC, with wallet balances 100 and
99.3009999928300 USDT. No final reports or source attestations were present. The legacy
trader remained active at PID 87549 with `NRestarts=0`; it was not signaled or controlled.
The running replay still uses 0.5% per-trade risk and cannot qualify the selected 0.25%
policy. No source, admission, service, API-key, account setting, or exchange-order changes
were made during this read-only checkpoint.

### Replay progress and offline telemetry integrity — 2026-10-13 20:31 MYT

Both credential-free replay units were active with `NRestarts=0`. NEAR and LINK had
advanced through 2024-08-28 UTC (wallet balances 99.60069260 and 99.780166722 USDT); APT
and ADA had advanced through 2024-07-29 UTC (wallet balances 100 and 99.3009999928300
USDT). Their output directories contained checkpoint logs only; no final reports or source
attestations were present. The protected production trader remained active at PID 87549
with `NRestarts=0` and was not signaled or controlled.

Locally, the legacy offline `execution/self_driving.py` path now fails closed when measured
Hawkes/heartbeat evidence is absent or invalid. Generic and ICT autopsy feedback also skips
when required observed market-quality or price-excursion inputs are missing; incomplete
queued ICT evidence is rejected rather than filled from entry/exit prices. Three targeted
unit tests passed, and Ruff plus strict mypy passed for the changed source. These changes
were not deployed and do not alter the frozen replay source or its 0.5% risk policy.

### Read-only qualification and feed checkpoint — 2026-10-13 20:39 MYT

Both credential-free VPS replay units remained active with `NRestarts=0`. NEAR had
checkpointed through 2024-10-27 (wallet 99.60069260 USDT); LINK and ADA through
2024-09-27 (wallets 99.780166722 and 99.1353656728300 USDT); and APT through 2024-08-28
(wallet 99.5150112400 USDT). The output directories contained only frozen policy and
process checkpoint logs, with no final reports or source attestations. The frozen replay
still uses 0.5% risk per trade and cannot qualify the selected 0.25% policy. The protected
trader remained active at PID 87549 with `NRestarts=0`; it was not signaled or controlled.

A local source audit compared the combined WebSocket wrapper and aggregate-trade/depth
payload fields against Binance's official USDⓈ-M market-stream schema. The parser unwraps
the combined `data` field and consumes the documented event fields, so no code change was
needed. Testnet endpoint reachability was not tested. No source code, replay inputs,
services, API key, account setting, or exchange order was changed during this checkpoint.

### Authenticated account and protective-cycle checkpoint — 2026-10-13

At 20:46:32 MYT, a sanitized authenticated read-only Testnet probe observed total equity
and available balance of 4,224.09882354 USDT with zero open positions, ordinary orders,
or conditional orders. The probe's fresh temporary ledger set its starting wallet to that
same observation, so `ledger_reconciled=true` proves only the point-in-time wallet/equity
identity and does not attest to a continuous runtime ledger. The probe did not configure
`DailyRiskTracker`; `day_start_risk_verified=false`. Therefore the real UTC day-start equity
and today's 5% cutoff remain unknown. At this snapshot 0.25% is 10.56024705885 USDT per
trade, but future qualification must freeze the live account equity it actually uses. The
temporary full account snapshot was deleted; no key or secret was stored.

The audit found that `RuntimeSession.cycle()` returned before attempting lifecycle
reconciliation whenever its first authenticated account refresh raised an exception. It
now attempts the coordinator cycle using any still-fresh cached snapshot, blocks all new
entries for that cycle, and preserves the coordinator's stale/missing-evidence rejection.
`tests/unit/test_runtime_session.py` passes (6 targeted tests), Ruff and formatting pass,
and strict mypy passes for the modified Python source. This change remains local and is not
deployed.

At 20:54 MYT the two frozen credential-free VPS replays remained active with
`NRestarts=0`: NEAR reached 2024-12-26 (wallet 99.39627580 USDT); LINK and ADA reached
2024-11-26 (wallets 99.276206990 and 99.0052604128300 USDT); APT reached 2024-10-27
(wallet 99.2038214800 USDT). They still had no final reports or source attestations, and
still use 0.5% risk per trade rather than the selected 0.25%. The protected trader remained
active at PID 87549 with `NRestarts=0`; no VPS service, key, account setting, or order was
changed.

### Headerless official kline archive repair and worker checkpoint — 2026-10-14 01:21 MYT

Read-only Kainode journal inspection found failed October 13 BTC/LINK cache builds because
the parser required a CSV header; the official 2020 BTC monthly archive is headerless with
the expected 12 kline data columns. The local parser now accepts headered and headerless
12-column input while retaining archive checksum, exact Decimal, timestamp, row, continuity
and candle checks. The focused unit file passes (4 tests), Ruff and formatting pass. The
parser validated both the real headerless Kainode BTCUSDT 2020-10 archive and the real
headered local BTCUSDT 2023-01 archive (44,640 rows each). The 2020 archive and manifest
were copied through pinned read-only SSH to a temporary local directory, parsed, then
removed. The old remote cache units were not restarted or modified.

The frozen 12-pair local ICT `limit_touch` batch remains 8/12 complete; all eight finished
reports are attested and rejected by net-edge/stressed-net gates. LINK, NEAR, APT and ADA
are active. Per-trade risk remains 0.5% of equity and the daily-loss rule remains 5%; no
replay or policy was changed. Pinned read-only VPS checks at 01:21 MYT confirmed production
trader PID 87549 active with NRestarts=0, the credential-free APT/ADA worker active, and
the public-only microstructure probe PID 812622 active with a growing 13.7 MB trace. Host
load was 2.31 across six CPUs and 9.3 GiB memory was available. No live order, key, or
production service action occurred.

### Qualification replay source-fingerprint incident — 2026-10-14 01:25 MYT

NEARUSDT exited at 01:23:41 with `Qualification implementation changed during replay`
after the official-market-data parser was edited during the hash-attested batch. This is a
fail-closed rejection; NEAR has no admissible report. The eight reports completed before
the edit retain their data-source attestations and rejected decisions, but their
implementation hashes bind the pre-fix parser. The runtime receipt verifier will not
accept them as current-source admission evidence; retain them as diagnostics only. LINK,
APT and ADA were still running at 01:25 and may hit the same guard. The source tree remains
unchanged while they finish; failed symbols are rerun only in a fresh output directory
against the current stable source. Partial logs are not qualification evidence. Per-trade
risk remains 0.5%, daily loss remains 5%, and the pinned VPS check still showed production
PID 87549 active with NRestarts=0. No VPS service or exchange order was touched.

### Eight-pair ICT exit-reason diagnostic — 2026-10-14 01:14 MYT

The eight completed independent $100 `limit_touch` replays contain 189 modeled trades.
185 exited via `CISD_INVALIDATION` (net -15.475896573760000 USDT, stressed
-33.899216797760000 USDT). The three `TIME_OR_WINDOW` exits and one `TP2` total
+3.16918840777040 net and +2.73789885177040 stressed. This is an aggregate diagnostic
across isolated per-symbol accounts, not portfolio PnL; no exit rule or filter was
changed. It supports testing new causal entry-quality hypotheses while keeping the
existing invalidation rule intact until a full replay demonstrates otherwise. The median
modeled hold time for the 185 invalidations is 60 seconds.

### Account polling reliability fix — 2026-10-13 21:01 MYT

A local runtime audit found that the one-second protective loop was repeating the full
authenticated account, positions, open-order, symbol-configuration, and income-history
snapshot on every cycle. `RuntimeSession` now throttles routine snapshots to 10 seconds
and backs off failed refresh attempts exponentially from 1 to 10 seconds. Queued entries
still force a fresh authenticated snapshot before lifecycle recovery and another after
recovery before sizing/admission; the one-second protective cycle remains independent.
While an exchange refresh is failing or backing off, cached evidence can support protective
reconciliation only while it remains fresh; new entries remain blocked, and missing or
stale account evidence continues to fail closed.

Validation was limited to the modified runtime-session unit file (8 passed), Ruff,
formatting, and strict mypy. The revised runtime remains local and is not deployed. No VPS
worker, production service, credential, account setting, or exchange order was changed.

The follow-on lifecycle audit found no authenticated user-data WebSocket attached to the
qualified runtime. `LifecycleCoordinator.advance()` polls every nonterminal entry and
protective order through REST each second; the gateway's listen-key helper is not wired to
an event consumer. Binance's [USDⓈ-M User Data Streams documentation](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/user-data-streams)
defines `ACCOUNT_UPDATE` and `ORDER_TRADE_UPDATE`, recommends prioritizing stream events
for account/order state, and documents 60-minute listen-key expiry plus a 24-hour
connection lifetime. This is a confirmed integration gap; implementation is pending a
Testnet endpoint and reconnect/reconciliation design review. No listen key was created or
renewed, because the Testnet key is shared with the active protected writer.

At 21:04 MYT, a read-only SSH status check confirmed the protected trader remained active
at PID 87549 with `NRestarts=0`. Both credential-free replay services were also active,
at PIDs 639755 and 645096 with `NRestarts=0`. This query checked service state only and
did not read worker checkpoints or alter any VPS service.

### Qualification checkpoint and orphaned-protection recovery — 2026-10-13 21:08 MYT

Read-only worker checkpoint files advanced to NEAR 2025-02-24 (wallet 99.39627580 USDT),
LINK 2025-01-25 (100.514093660 USDT), and APT/ADA 2024-12-26 (99.2038214800 and
98.7728345928300 USDT). Neither output directory contained a final report or source
attestation; all four replays still use 0.5% risk and cannot qualify the selected 0.25%
policy. The two workers and protected trader were active with zero restarts in the
preceding read-only service query.

`LifecycleCoordinator.advance()` previously discarded the protective executor's
unresolved result when a persisted protective command was orphaned from the trade journal.
It now reports any remaining `UNKNOWN` protective command as unresolved, which blocks
entry admission while still allowing the coordinator to continue recovery work. Regression
coverage is in `tests/unit/test_lifecycle_coordinator.py`; the targeted file passes (6),
Ruff and formatting pass, and strict mypy passes for the modified coordinator. This fix is
local only.

Official USDⓈ-M user-stream schemas additionally include `ALGO_UPDATE` and
`CONDITIONAL_ORDER_TRIGGER_REJECT`, which matter for conditional protective orders. The
runtime has no consumer for these events yet. Testnet endpoint/reconnect recovery remains
unverified, and no shared account listen key was opened while the legacy writer is active.

### Phase 310 evidence-semantics repair — 2026-10-13 21:22 MYT

The local Phase 310 integrity verifier no longer claims that real autonomous trading was
verified. I removed the synthetic hardcoded-candle batch runner and `--test-run` option.
Phase 310 artifact exports explicitly mark internal simulation/non-executable mode, deny
execution authority, report zero exchange-confirmed fills, and no longer use a production-
launch verified status. Legacy capital bounds are labeled simulation-only. This is local-only;
the running VPS process and its dirty worktree remain untouched.

Targeted `tests/unit/test_phase_310_vps_solvency.py` passed (12 tests), Ruff and formatting
passed, and strict mypy passed on the two modified Python source files. No full-suite tests
were run.

### Risk-policy reaffirmation and live-stream integration — 2026-10-13 21:48 MYT

The user reaffirmed **0.5% of actual account equity risk per trade**, superseding all
earlier 0.25% selections recorded in this chronological log. The runtime planner and
ICT qualification freeze already bind 0.5%; the frozen replay sidecars also use 0.5%,
so there is no remaining per-trade-risk mismatch. The separate 5% daily-loss
cutoff remains based on genuine actual-account equity at UTC day start. No worker policy,
service, or VPS process was changed.

The local qualified runtime now consumes authenticated user-data WebSocket events,
reconciles account/order state through REST after reconnect, blocks entries during stream
gaps, and forces protective handling on margin-call/conditional-trigger-reject events.
Market ingress uses separate current Testnet `/market` and `/public` routes, and admission
requires both ingress channels to remain healthy. A recent flat REST snapshot is required
before clearing the risk-event block. Authenticated private-stream behavior has not been
verified against Testnet because the same API key remains shared with the protected legacy
writer; no listen key was created and no user-stream connection was opened.

Targeted integration validation passed: 91 tests across the authenticated stream, market
feed, runtime session, protective lifecycle, lifecycle coordinator, gateway, admission and
percentage-risk files. Ruff, format checks and strict mypy passed on the changed integration
modules.
These are local code checks only. No code was deployed, no orders were sent, and PID
87549 was not touched. Qualification and actual activation remain incomplete.

### Current ICT integration and read-only worker checkpoint — 2026-10-13 22:03 MYT

Per the user's latest confirmation, per-trade risk remains 0.5% of actual exchange account
equity; this supersedes the older 0.25% references above. Planner, qualification freeze, and
in-flight replay policies already agree at 0.5%.

Pinned read-only SSH confirmed the protected trader is active at PID 87549 with NRestarts=0;
both credential-free replay units are active with NRestarts=0 (PIDs 639755 and 645096).
Latest progress checkpoints: NEAR 2025-11-21, wallet 99.69621800 USDT; LINK 2025-10-22,
99.712660616 USDT; APT 2025-10-22, 100.79284200000000 USDT; ADA 2025-09-22,
98.2635464728300 USDT. No final reports were observed and no VPS state was changed.
Current unit properties confirm CPUQuota=200% for each replay service (four cores total);
the host reports six CPUs and load average around 4.2. The requested two-core increase is
already in place, so no quota adjustment was made.

The ICT engine now uses the exact PD-array touch index. Real-data differential validation
matched brute force across 48 snapshots, 12 pairs, and 9,371 arrays; median lookup was
0.537 ms indexed versus 2.828 ms brute force (5.27x for this lookup, not whole replay).
The qualification source manifest and receipt verifier now include this transitive helper.
Prior reports and remote workers predate that source-binding change and cannot be admitted
against the current implementation. Once the workers finish, current-source replay evidence
is required. Targeted validation passed (67 tests), along with Ruff, formatting, and strict
mypy. Full-suite tests were not run; the admission manifest remains empty and no code was
deployed.

### Daily-risk transfer accounting and qualification source binding — 2026-10-13 22:16 MYT

The daily-risk audit found that equity drawdown ignored authenticated transfers after the
UTC day-start capture. USDT TRANSFER rows now flow through as explicit basis adjustments,
with unique transaction identity and timestamp validation. Deposits no longer erase trading
losses; withdrawals no longer count as trading losses. Wallet reconciliation includes
starting equity, trading income, and the external basis adjustment; the equity identity still
uses wallet plus unrealized PnL. Unknown income types, non-USDT rows, duplicate transactions,
or ambiguous baseline-time transfers fail closed. The [official Binance income-history
reference](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account)
documents the endpoint and TRANSFER records.

Macro Scalper reports now bind daily_risk.py, and the receipt verifier requires this risk
dependency for both Macro Scalper and ICT reports. Existing reports without the current risk
hash are not admissible. Admission remains empty.

The touched risk/accounting, report-binding, runtime, receipt, lifecycle, and scanner checks
passed: 85 targeted tests, Ruff, format, and strict mypy. No full-suite test was run.

Read-only VPS verification at 22:16 MYT: trader service active, PID 87549, NRestarts=0; both
credential-free replay units active, PIDs 639755/645096, NRestarts=0, CPUQuota=200% each.
Host has six CPUs; the allocated four worker cores remain in place. Progress checkpoints are
NEAR 2026-01-20, LINK/APT 2025-12-21, ADA 2025-11-21. No final report files were present.
Worker source predates the current local risk-accounting changes, so current-source
requalification remains required. No VPS state was changed and PID 87549 was untouched.

### ICT development outcome diagnosis — 2026-10-13 22:19 MYT

Exploratory aggregation of the eight completed current-code ICT reports (BTC, ETH, SOL,
DOGE, BNB, XRP, SUI, AVAX), ending at 2026-08-01, found 189 trades: net -12.3067081659896
USDT, gross -5.27634 USDT, stressed net -31.1613179459896 USDT. There were 182
CISD-invalidation exits and 105 trades held for one minute or less. BUY (87 trades,
-7.06435 USDT) and SELL (102 trades, -5.242358 USDT) were both negative.

Only UTC hours 13 and 22 had positive aggregates, with three and four trades. Too little
evidence to justify a session filter; no time or side filter is a candidate. This uses
existing development reports through July 2026 only; the reserved Aug-Sep 2026 holdout
was not accessed. No qualification or execution authority follows from this diagnostic.
Next strategy work should test a causal alternate entry/retest model on development data,
including executable fees, slippage, funding, 0.5% per-trade risk, and the 5% daily-loss
cutoff before freezing any candidate for holdout.

The user reconfirmed 0.5% of actual exchange account equity as per-trade risk. Planner,
qualification domain, and frozen worker policies already match, so no risk change was
needed. The confirmation-displacement diagnostic JSON still has one obsolete limitation
sentence referring to 0.25%; its research sizing used 0.5%. The canonical correction is in
CODEX_HANDOFF.md §15, and the original diagnostic remains unchanged for hash integrity.

### Current-source reclaim-retest checkpoint — 2026-10-13 22:50 MYT

The user reaffirmed **0.5% of actual exchange account equity per trade**. Runtime planner,
qualification domain, and active local replay policies already match, so no risk-setting
change was needed.

Three local current-source `reclaim_retest` development runs remain active. At the latest
checkpoint, SUI was through 2025-03-26 with wallet 98.789342616 USDT; DOGE was through
2025-03-26 with wallet 100.67500640977040 USDT; SOL was through 2025-02-24 with wallet
100.4873627360 USDT. Their output folders contain only `frozen-policy.json`; there are no
final reports. The runs use development data, grant no execution authority, and do not use
the reserved Aug-Sep 2026 holdout. Keep the hash-bound qualification implementation
unchanged until these processes finish.

Pinned, read-only SSH at 22:50 MYT confirmed the protected trader active at PID 87549 with
NRestarts=0. Both existing credential-free VPS replay units remained active at PIDs 639755
and 645096 with NRestarts=0. No VPS service, credential, account setting, or exchange order
was changed; PID 87549 was not signaled or controlled.

### Testnet private-stream connectivity probe — 2026-10-13 22:55 MYT

Per the user's instruction to reuse the existing Testnet API key, a bounded 20-second
authenticated user-data-stream probe connected successfully and completed one initial REST
account reconciliation. It received zero private events and reported no connection or
reconciliation error. Output contains only event-type counts and status; temporary account
evidence was removed with its temporary directory. The reusable diagnostic is
`scripts/probe_runtime_user_stream.py`; it calls no order endpoint and reports
`execution_authority=false`.

This verifies Testnet private-stream connectivity and initial REST recovery only. Because
no private event arrived, event ordering, event-triggered recovery, and protective handling
remain unverified against live events. The probe did not start a trading runtime or alter
the protected service. The probe script passes Ruff, formatting, and strict mypy; the
targeted stream/runtime unit tests pass (14). No full suite was run. PID 87549 was not
signaled or controlled.

### ICT live-entry integration gate — 2026-10-13 22:58 MYT

Code review found that `CausalScanner` turns `setup.step_6_ready` directly into `ict_plan`,
placing the entry at the M1 CISD price. The current `reclaim_retest` research mode instead
requires a completed one-minute touch-and-reclaim candle followed by a distinct later
trade-through before the maker fill. The live scanner has no persistent state for that
sequence. Any report from this research mode must remain inadmissible until the matching
stateful live entry flow is implemented and tested.

`deploy/qualification-admission.json` remains empty, and `scripts/run_qualified_runtime.py`
blocks startup while the legacy writer is active. The new runtime and candidate are not
ready for activation. Keep the protected PID 87549 untouched and preserve source hashes
until the current development replays finish.

### Reclaim-retest development screen — 2026-10-13 23:02 MYT

The first three current-source reports are hash-valid and source-attested, but all are
**REJECTED** with `execution_authority=false`. SUI recorded 21 trades (net -2.026136880
USDT, stressed net -3.861931265 USDT, zero profitable windows); DOGE recorded 12 (net
+0.182333902 USDT, stressed net -0.830602238 USDT, one profitable window); SOL recorded 9
(net +0.235968916 USDT, stressed net -0.825465173 USDT, one profitable window). Every
report fails the 30-trade minimum and stressed-net gate. SUI also fails net edge and profit
factor; all three fail the minimum profitable-window gate. The source attestations verified
47 files for SUI and 51 each for DOGE and SOL.

The frozen policy remains 0.5% per-trade risk and 5% daily loss. The remaining-nine batch
is active with a four-worker cap, explicit symbol inclusion, and `reclaim_retest`
propagation through `scripts/qualify_runtime_universe.py`; queued symbols start as slots
free. Upon completion, it will finish the 12-pair development screen without using the
reserved Aug-Sep holdout. No individual report is admissible, and no shared-portfolio
qualification has been established.

The universe runner now forwards the frozen ICT entry mode to each child process. Its
targeted unit file passes (9 tests); Ruff, formatting, and strict mypy pass. No full test
suite was run.

### Reclaim-retest full-universe progress — 2026-10-13 23:18 MYT

Seven of 12 current-source per-pair development reports are complete, hash-valid, and
source-attested. All seven are **REJECTED** with `execution_authority=false`; every pair is
below the 30-trade minimum and has negative stressed net PnL: SUI (21 trades, net
-2.026136880 USDT, stressed -3.861931265 USDT), DOGE (12, +0.182333902, -0.830602238),
SOL (9, +0.235968916, -0.825465173), XRP (6, -0.463924148, -1.157791011), BNB (9,
-0.658401720, -1.648531990), BTC (6, -0.557835198, -1.239640806), and ETH (11,
-0.740839110, -1.733254130). Values are USDT.

AVAX, NEAR, LINK, APT, and ADA remain in the four-worker batch (four running, one queued
at this checkpoint). Risk policy remains 0.5% per trade and 5% daily loss. The reserved
Aug-Sep 2026 holdout remains untouched. No individual candidate is admissible, and these
independent per-pair runs do not establish shared-wallet portfolio qualification.

### Stateful ICT reclaim-entry integration — 2026-10-13 23:40 MYT

`CausalScanner` now recognizes the frozen ICT `entry_mode` in qualification reports and
retains a source-bound state for `reclaim_retest`: candidate plan, report identity, original
expiry and processed one-minute candle cursor. It applies the same completed close-reclaim
predicate as research, then sends a maker intention once. The report hash and reclaim
readiness timestamp travel through `RuntimeSession` to `EntryAdmission`, which re-verifies
the reviewed report and rechecks staged readiness against both its 60-second freshness and
the original five-minute plan expiry. The runtime refuses a staged intention unless the
report explicitly authorizes `reclaim_retest`. Persisted gaps/corruption fail closed.

Targeted scanner, reclaim-state, admission-time and runtime-session tests pass (26). Ruff,
format and strict mypy pass. No full suite ran, no hash-bound qualification source changed,
and no VPS or exchange state was touched. The current 12-pair reclaim-retest batch has 11
completed rejected reports and ADA remains active. The deployment manifest remains empty;
qualification, shared-wallet evidence, live private-event validation and single-writer
handoff are still required before activation.

### Reclaim-retest 12-pair screen completed — 2026-10-13 23:45 MYT

The current-source frozen `reclaim_retest` development screen completed for all 12
universe pairs at **0.5% per-trade risk** and a **5% UTC-day-start-equity daily-loss
limit**. All 12 reports are **REJECTED** and all are bound to verified source attestations
with `execution_authority=false`. Trade counts range from 5 to 21, below the 30-trade
minimum. Only DOGE and SOL have positive unstressed net PnL; every report has negative
stressed net PnL and fewer than three profitable windows.

Across 112 trades in independent $100 research runs, diagnostic arithmetic sums are
-7.33884668110960 USDT net and -17.98222028010960 USDT stressed. These sums do not model a
shared wallet. ADA's completed report is
`artifacts/qualification/runtime-ict-reclaim-retest-dev-remaining-20261013/ADAUSDT-6d106b234a8fd25a.json`;
it records 12 trades, -1.194076300 USDT net, -2.108607450 USDT stressed, and zero
profitable windows. Its source attestation was generated and the report/attestation pair
was verified. The deployment admission manifest remains empty. No VPS service, live
credential, account setting or exchange order was changed. Continue research only on
development data and preserve the reserved holdout.

### Expected stale setup handling in the live scanner — 2026-10-13 23:49 MYT

Across the 12 current-source reports, `STEP_6_READY` persisted across many minute
observations. The evaluator counted 1,202,082 stale-confirmation rejections across
1,252,537 ready-state observations; these are repeated observations of existing setups,
not unique entry signals. The original confirmation timestamp intentionally prevents an
old setup from refreshing its TTL.

`CausalScanner` previously propagated expected `IneligibleTrade` results to the runtime
supervisor, which marked stale confirmations and risk/minimum-size ineligibility as scan
errors. It now returns no intention for those expected outcomes for both ICT and Macro;
unexpected configuration, feed and account errors remain visible. The targeted scanner
file passes (4 tests), with Ruff, format check and strict mypy clean. No qualification
source hashes or existing reports changed; no full suite, VPS service, credential,
exchange setting or order was touched.

### Reclaim signal-candle displacement diagnostic — 2026-10-13 23:55 MYT

All 112 modeled trades from the rejected current-source `reclaim_retest` reports were
screened against the exact one-minute signal candle using verified official archive bars.
There were 109 `CISD_INVALIDATION` exit events; the median modeled exit timestamp was 60
seconds after fill. The diagnostic script now reads `trade_risk_pct` from the batch's
`frozen-policy.json` and records its SHA, removing the stale hard-coded 0.25% statement.
Each of the four outputs binds to 0.5% risk and sets both qualification and execution
authority to false. The reserved Aug 1, 2026 holdout was excluded.

The post-hoc displacement screen did not turn existing fills into positive aggregate
results: at 0.30 ATR, 53 trades summed to -2.37232381510960 USDT net and -7.43328203810960
USDT stressed; at 1.00 ATR, six trades summed to -0.498272308 USDT net and -1.002893626
USDT stressed. This filter screen is not a replay and grants no authority. Future candidate
work must be based on a pre-entry causal hypothesis, run through full chronological
replay, and leave reserved validation untouched until the candidate is frozen.

### Per-trade risk reaffirmed — 2026-10-14 00:02 MYT

The user reaffirmed 0.5% of actual exchange account equity as risk per trade. This
supersedes older 0.25% decisions in the chronological notes above. Runtime planning,
qualification freezes, and in-flight replay sidecars already bind to 0.5%, so no policy
artifact or running worker needed modification or restart. The separate 5% UTC-day-start-
equity daily-loss cutoff remains active; qualification and execution authority are still
not granted.

### Protective order response binding — 2026-10-14 00:04 MYT

`ProtectiveExecutor` now verifies acknowledged order type and trigger/limit price against
the durable command intent, in addition to symbol, client ID, side, reduce-only and
quantity. Conditional orders bind to the parent algo's `orderType` and `triggerPrice`, so
triggering into a child order cannot erase the protective intent being reconciled. Missing
or mismatched fields fail closed. The targeted executor/lifecycle/coordinator/fill-recovery
tests pass (43); Ruff, format check and strict mypy pass. No full suite or live order was
run. This is local logic evidence, not live exchange lifecycle proof; no VPS service,
credential, account setting or exchange order was touched.

### Current-source public Testnet feed probe — 2026-10-14 00:32 MYT

The 30-minute probe completed successfully. Report and trace SHA-256 match, and all six
run-recorded implementation hashes still match current probe/feed/clock/Hawkes sources.
At completion both channels were connected; the raw trace contains 34,352 aggTrade and
47,478 depthUpdate frames, with 428 stale observations, zero gaps/duplicates, no feed or
fit error, and a measured Hawkes spectral radius of 0.6463075 (no baseline-bound symbols).
The report grants no qualification or execution authority.

Only BTCUSDT and SOLUSDT passed the current 500 ms trade/depth age check at the final
snapshot. Conservative 100 ms sampling of the raw trace over 1,798,292 ms, using maximum
observed clock uncertainty of 72 ms, found 22.26%–41.18% pair freshness availability at
the current 500 ms maximum age; a 2,000 ms diagnostic threshold yielded 83.92%–97.53%.
This is feed-availability analysis only, not strategy PnL evidence. The production guard
remains 500 ms pending causal replay and current-source VPS validation. The report's
`source` field omitted the separate depth endpoint even though the hash-bound feed code
and raw trace confirm depth ingestion; record both endpoints in future probe output.
Local public Testnet only, with no authenticated calls or exchange orders; PID 87549 and
its service remain untouched.

### Dashboard telemetry and feed-route provenance repair — 2026-10-14 00:56 MYT

The Evolution page previously rendered generated event/ledger values and an active-daemon
indicator without live evidence, plus an obsolete $5 child-order cap. It now derives
those claims only from explicit telemetry and displays missing evidence as unavailable.
The focused component tests pass (13), and `npx tsc -b --pretty false` passes; targeted
Oxlint exits successfully with one existing render-time `Date.now()` warning.

The persistent public feed probe now records both `market` and `public_depth` WebSocket
URLs under a new `sources` object while preserving the old `source` string for existing
readers. One focused regression test passes; Ruff, formatting, and strict mypy pass for
the changed probe. Existing probe reports were not rewritten.

A current-source 12-pair ICT `limit_touch` development replay remains active locally
under the repository virtual environment, with four workers. Its frozen sidecar binds
0.5% per-trade risk, 5% daily loss, official inputs, and a 2024-01-01 through 2026-08-01
development boundary. At this observation no pair report has completed; no result is
qualified or admitted, and the reserved Aug-Sep holdout is untouched. The first attempt
using global Python failed before replay due to missing `pydantic`; that failed output
was preserved separately. No VPS service, credential, account setting, or order was
changed, and PID 87549 was not controlled.

### ICT `limit_touch` replay interim results — 2026-10-14 00:57 MYT

Four of 12 current-source per-pair reports have completed and each exact report passed
`attest_runtime_report_sources.py`. BTCUSDT is **REJECTED** (10 trades, net
-0.90222265000000 USDT, stressed net -2.07246230000000 USDT, zero profitable windows);
ETHUSDT is **REJECTED** (25 trades, net -1.938910714 USDT, stressed net -4.474138908
USDT, zero profitable windows); SOLUSDT is **REJECTED** (30 trades, net
-2.07345854488000 USDT, stressed net -5.34929594888000 USDT, one profitable window);
DOGEUSDT is **REJECTED** (32 trades, net -1.68850580022960 USDT, stressed net
-4.44987896722960 USDT, one profitable window). All four fail the net-edge, stressed-net,
and three-profitable-window gates; BTC and ETH also fail the sample minimum. All have
`execution_authority=false`. These are independent $100 single-symbol replays and do not
establish shared-wallet qualification. The remaining eight symbols are still being
processed by the same bounded four-worker batch. Risk remains 0.5% per trade and the
reserved Aug-Sep holdout is untouched; no candidate is admitted.

### Read-only Kainode worker checkpoint — 2026-10-14 01:00 MYT

A fresh read-only SSH check confirmed `autonomous-futures-trader.service` is active and
running at MainPID 87549 with NRestarts=0; no signal or service action was performed.
The six-vCPU host reported 9.4 GiB available memory. The existing credential-free
APTUSDT and ADAUSDT workers each used about one core and checkpointed through
`through_ms=1755907200000`. They are older `directional_fix` jobs, separate from the
current local `limit_touch` qualification. No VPS service, credential, or account state
was changed.

### Evolution clock and cycle telemetry follow-up — 2026-10-14 01:03 MYT

Removed the remaining render-time `Date.now()` call. The current-time display is
unavailable during server rendering and starts from the browser timer. The Next Cycle
card now formats the value supplied by telemetry and no longer decrements a client-only
counter or assumes a fixed 15-second interval/progress bar. The focused test asserts that
90 reported seconds renders as `1:30`; all 13 component tests pass, the TypeScript project
check passes, and targeted Oxlint is clean.

### Authenticated-stream to protective-cycle regression — 2026-10-14 01:05 MYT

Added a RuntimeSession integration regression that feeds a `MARGIN_CALL` payload through
the authenticated stream's decoder and its installed session callback. The callback
blocks entries and arms external-risk flattening; the next protective cycle uses that
reason, and the disconnect leaves the event-gap interlock set. All 11 targeted
RuntimeSession tests pass, with Ruff and formatting clean. This test uses a mocked
transport/account and does not claim live exchange event or order evidence.

### Eight-pair ICT `limit_touch` interim results — 2026-10-14 01:13 MYT

Eight of 12 current-source development reports are complete. The AVAXUSDT report is
**REJECTED** (25 trades, net -1.649098078880 USDT, stressed -4.109609678880 USDT, zero
profitable windows); BNBUSDT is **REJECTED** (17, net -1.300346340, stressed
-3.118868080, zero windows); SUIUSDT is **REJECTED** (33, net -2.100044168000000,
stressed -5.070059901000000, zero windows); and XRPUSDT is **REJECTED** (17, net
-0.6541218700000, stressed -2.5170041620000, one window). Each new report is source
attested; an independent Decimal reconciliation checked trade/window counts, net and
stress totals, profitability gates, chronological boundaries, and that no trade exit
crosses its window end. All eight completed reports fail net-edge and stressed-net gates.
LINK, NEAR, APT and ADA are still running; no report is admitted.

### Kainode public microstructure probe started — 2026-10-14 01:13 MYT

Transferred an isolated source/calibration package to
`/home/afbot/qualification-worker/runtime-microstructure-probe-20261014`; archive SHA-256
is `3300250b73d6e377402d13aead8fd06a5b68ec97f62bc4df765b12f9bc51b556`. The package has
no credential files. The host's isolated Python environment verified the 7.5 beta
calibration and its 12-symbol profile hashes. A 30-minute public Testnet probe is active
under transient unit `afb-microstructure-probe-20261014-0108.service`, constrained to one
CPU, 1 GiB memory, Nice 19 and a 1,860-second hard runtime. It inherits an empty
environment and uses public streams/server time only; trace capture is progressing but
the final result is not yet available. Read-only status still shows the protected trader
active at MainPID 87549 with NRestarts=0. No production service, key, account or order was
changed.

### Stable-source retries and microstructure probe results — 2026-10-14 01:47 MYT

After the source-fingerprint failure, LINK, NEAR, APT and ADA were rerun after the original
batch ended, with no source edits during replay, into
`artifacts/qualification/runtime-ict-limit-touch-stable-source-20261014`. All completed
successfully; current implementation hashes match, original data inputs pass independent
source-index verification, report hashes and Decimal trade/stress/window/gate checks pass,
and input-source attestations were saved. At 0.5% per-trade risk and 5% daily loss, all
four reject: LINK 25 trades, net -0.625323328, stress -3.362545416, one profitable window;
NEAR 17, -0.58929320, -1.95476240, one; APT 23, -0.40196090800000, -2.69677139300000,
one; ADA 28, -1.8254403871700, -4.0710501371700, zero. Each fails net-edge, stressed-net,
minimum-sample, profit-factor and profitable-window gates. The eight earlier reports are
rejected diagnostics from the prior implementation hash and cannot be admitted against
current source. No candidate qualifies and the admission manifest remains empty.

The bounded public Testnet microstructure probe completed its 1800-second capture normally;
the transient unit is inactive with MainPID 0, NRestarts 0 and exit status 0. Verified
report and raw trace are preserved under
`artifacts/qualification/runtime-microstructure-probe-20261014-final/`. Their SHA-256
values are `4b5f9f428eb4779ef6566b10a158d75a8676f9dea34ea6fdf07289863995a0c0` and
`e9e27cd69e434e8f8316b7c071523e1c6c24aa7328c96ecebe047b61d9256255`. All six implementation
hashes and the 12-symbol calibration hash match. Connected for the full probe, the feed
recorded 34,526 trade arrivals, 46,088 depth frames, zero gaps, zero duplicates, 13 stale
frames, no fit error, beta 7.5/s and spectral radius 0.6996643786. The strict 500 ms gate
accepted four pairs at the final snapshot (DOGE, BNB, SUI, AVAX); eight were stale. The
gate remains unchanged pending repeated-window data and the result grants no execution
authority.

Pinned read-only VPS verification at 01:47 MYT: production PID 87549 remains active with
NRestarts=0; the public probe exited successfully; credential-free APT/ADA workers remain
active at roughly one core each. Host load was 2.12 across six CPUs with 9.4 GiB available.
No production service, API key, account state, or exchange order was changed.

## 2026-10-14 01:54 MYT — displacement diagnostic path repair and screen

Fixed relative `--minute-root` handling in `scripts/diagnose_ict_confirmation_displacement.py`
and added `tests/unit/test_ict_confirmation_displacement.py`. Its regression builds a
checksummed official-format ZIP with a valid 12-column row and exercises the real archive
parser. The focused test passed; Ruff check and format passed. A source-attested screen
over the four current-source LINK/NEAR/APT/ADA `limit_touch` reports examined 93 filled
trades with the Aug 1 UTC
holdout boundary intact. Unfiltered net/stressed PnL was -3.4420/-12.0851 USDT. At 0.5 ATR,
27 trades remained and net/stressed PnL was -0.9444/-3.3782. At 1.0 ATR, six trades showed
small positive net/stressed PnL (+0.7465/+0.2919), below the sample gate; two later-window
trades summed to -0.4253 net. The screen is post-hoc, not a replay, and creates no candidate
or execution authority. Result artifact:
`artifacts/qualification/diagnostics/ict-confirmation-displacement-limit-touch-stable-20261014.json`.

Fresh pinned read-only VPS status at 01:54 confirms production PID 87549 active with
NRestarts=0 and the separate credential-free APT/ADA qualification unit active. The two
child processes remain at about one core each. No VPS worker, production service, API key,
account state, or exchange order was changed. Risk remains 0.5% per trade and 5% of
day-start actual exchange equity for the daily loss cutoff.

## 2026-10-14 02:00 MYT — legacy paper registry repair and second feed window

The working-tree paper candidate registry contained 12 placeholder records; four had
non-hex candidate hashes and the loader rejected the manifest. The prior bytes are
preserved at `artifacts/research/phase317/candidate_registry-invalid-placeholder-20261014.json`
(SHA-256 `e4bcb0810b248b071c9cd9b303973a4b7c6d49db904336f834dfc96fce9e15d1`). Restored the
verified Phase 295 paper-only BTC/ETH/SOL registry from the repository version. Loader
verification returned three source-bound candidate/qualification bundles. Ten focused
manifest/OOS tests pass. The actual runtime deployment list remains empty at
`deploy/qualification-admission.json`; paper legacy candidates do not establish current
Macro/ICT runtime qualification or execution authority.

Started a second 1800-second public Testnet feed capture under
`artifacts/qualification/runtime-microstructure-probe-20261014-window2`, with unchanged
implementation/calibration and no authenticated requests or orders. The process handle is
still active; no result is claimed yet. PID 87549 and the separate APT/ADA VPS qualification
workers remain untouched.

## 2026-10-14 02:05 MYT — Macro report source-binding audit

All 11 prior Macro Scalper report self-hashes validate and all 11 decisions are REJECTED,
but every report pins the stale `runtime_qualification.py` digest and lacks the current
`daily_risk.py` implementation binding. They are historical diagnostics, not current-source
qualification receipts. The LINK development and consumed Aug–Sep holdout reports have the
same source mismatch; do not retune or reuse that holdout. BTC is Macro regime context, not
a traded symbol, so 11 reports match the strategy's declared tradeable universe. Current
official bar/funding inputs for the 11 pairs are available through the Aug 1 UTC holdout
boundary. A current-source replay is queued after the active 1800-second public microstructure
window completes.

## 2026-10-14 02:11 MYT — risk reaffirmation and Macro runner repair

The user reaffirmed 0.5% of actual exchange account equity per trade. Runtime planning and
in-flight replay sidecars already use that value, so no risk change or worker restart was
needed. Historical 0.25% notes are superseded; the 5% UTC-day-start-equity daily cutoff stays
in force.

Repaired Macro CLI input selection: the canonical runner defaults to the pinned official
2026-10-13 snapshot, and its default funding path is resolved under whichever cache was
selected. The development variant runner now follows its selected cache for funding too.
Canonical reports include the CLI source digest in their implementation map and receive a
recomputed report hash. Targeted validation: 4 runner tests passed; Ruff and format checks
passed. No full suite or new replay was run. The second 30-minute public feed capture remains
active, with no result available yet; production PID 87549 and VPS workers were left alone.

## 2026-10-14 02:12 MYT — qualification orchestrator input cleanup

The bounded universe runner now requires commission data only for ICT. Macro Scalper does
not receive the unused argument, and direct orchestration calls fail closed for unknown
families or ICT without commission data. The official cache pin and 11-pair Macro / 12-pair
ICT selection rules are unchanged. Fifteen focused runner tests passed; Ruff and formatting
checks passed. No full suite or replay was started. The per-trade policy remains 0.5%.

## 2026-10-14 02:17 MYT — explicit risk policy binding and type repair

`RuntimeQualificationPolicy` now carries the approved 0.5% trade-risk value and 5% daily-loss
value, derived from `DEFAULT_CAPITAL_POLICY` so there is one canonical setting. It exposes the
shared planner policy and passes it into both strategy-family replays.
The ICT freeze derives its displayed trade-risk value from the policy. Receipt verification
rejects otherwise passing reports if either percentage is absent or disagrees with the live
runtime policy. A type annotation in the official kline parser now records that both the CSV
reader and headerless-row chain are iterators, resolving targeted strict mypy.

Targeted validation passed: 79 tests across qualification, risk, entry-mode, runner, and
official-market-data units; Ruff and formatting checks passed; strict mypy passed on five
source files. No full suite or replay was run. The public feed capture is still active, the
admission manifest remains empty, and PID 87549 plus the remote replay workers were left
untouched.

## 2026-10-14 02:20 MYT — read-only Kainode worker status

Read-only SSH confirmed the protected trader service is active/running at MainPID 87549 with
`NRestarts=0`; no signal or service action was performed. Previously recorded replay PIDs
639755, 744029, and 747836 are absent. The current user-unit listing shows no active
qualification/replay/probe worker; visible Python processes are attached to scheduler,
Telegram, paper-live, and a user session.

Two older BTC/LINK holdout cache-builder units are failed with exit status 1. Their logs show
the isolated 2026-10-13 checkout rejected headerless Binance klines as an unknown schema.
These jobs concern the consumed LINK holdout and were left failed; they were not restarted.
The current local parser already supports that format. The second local public feed window
remains active, so current-source Macro replays are still queued. No VPS worker, production
service, credential, account setting, or exchange order was changed.

## 2026-10-14 02:23 MYT — completed remote ICT batch evidence

Read-only journals confirm both credential-free Kainode ICT resume batches finished with
exit code 0 and are inactive. Their complete output directories were copied locally under
`artifacts/qualification/runtime-ict-directional-fix-resume-20261013` and
`artifacts/qualification/runtime-ict-directional-fix-resume-apt-ada-20261013`. The four
unique reports self-hash correctly and are all REJECTED: LINK 25 trades (-0.625323328 USDT
net, -3.362545416 stressed); NEAR 17 (-0.58929320, -1.95476240); APT 23
(-0.40196090800000, -2.69677139300000); ADA 28 (-1.8254403871700, -4.0710501371700).
Each fails sample, net-edge, stress, profit-factor, and profitable-window gates. The frozen
sidecars specify 0.5% risk, but each report predates explicit risk-policy binding and its
implementation hashes are stale, so these are diagnostics only. APT and ADA report bytes are
duplicated across the two separate batch output folders; both originals are preserved.

Read-only process and unit checks found no qualification/replay worker active now. The prior
qualification PIDs are absent; the two old BTC/LINK holdout-cache units remain failed from an
unsupported-header error and were not restarted. Production PID 87549 remains active with
`NRestarts=0`. The local public feed capture remains in progress, and current-source Macro
qualification is still queued until it completes.

## 2026-10-14 02:24 MYT — live service still uses legacy capital controls

The live user service at `/opt/autonomous-futures-bot` routes through the Phase 310
`ContinuousSelfDrivingTrader` and legacy `SelfDrivingTradingEngine`. Read-only inspection of
the VPS source confirms it still configures a $5 child-notional cap, $25 aggregate cap, 75%
cash-reserve floor, and fixed $3 daily-loss ceiling. This is separate from the new qualification
planner, which now binds 0.5% trade risk and a 5% day-start daily limit with no margin,
aggregate-notional, or reserve cap. Those changes are local qualification-path changes only;
they have not been applied to the live service.

No release was deployed, and production PID 87549 remains untouched. Since the admission
manifest is empty and no current-source candidate qualifies, keep the legacy service in place
until a validated replacement and reviewed single-writer handoff are available. Never restart
or signal PID 87549.

## 2026-10-14 02:30 MYT — portable qualification source indexes

Fixed a receipt gap: both runtime report builders now include the `source_files` records that
admission verification requires. Their provenance lists every dataset, manifest, funding,
filters, commissions, and official minute archive manifest by repository-relative path and
SHA-256. Inputs outside the repository are rejected, and the full index is recomputed after
replay to detect changes during qualification. The diagnostics runner that uses
`verified_bars` without producing admission evidence retains its existing compatibility path.

Targeted validation passed: 40 unit tests covering report verification, source attestation,
ICT and Macro runners, and archive parsing; Ruff/format passed; strict mypy passed for the
qualification engines. No full suite or new replay was run. The public feed window remains
active. Production PID 87549 and all VPS services were left untouched; no admission was
granted.

## 2026-10-14 02:43 MYT — probe verified and current-source Macro batch started

The second 1,800-second public Testnet probe completed with an intact trace and matching
implementation/calibration hashes: 33,578 arrivals, zero gaps or duplicates, and 75 stale
frames. Final freshness evidence accepted only BTC, DOGE, NEAR, and LINK; the other eight
symbols were stale. This is diagnostic only and does not qualify the universe.

Started `afb-runtime-macro-current-20261014.service` in a new credential-free worker path.
The exact 328-file source package and all 96 official cache file hashes were verified. Its
frozen policy records 0.5% per-trade risk and 5% daily loss. The service is limited to two CPU
cores, 4 GiB memory, low CPU weight, Nice 19, and idle I/O. Two pair reports have been written
but have not yet been checked. The worker remains active for all 11 Macro pairs.

Read-only status confirms the production trader remains active at PID 87549 with
`NRestarts=0`; it was never stopped, restarted, signaled, or killed. No exchange orders,
credentials, live account settings, or admission records were changed. The 0.5% risk setting
remains in force. No full-suite tests were run; the previously recorded targeted validation
remains the relevant code check.

## 2026-10-14 02:47 MYT — Macro current-source batch completed and rejected

All 11 current-source Macro pair jobs exited successfully under the bounded two-core VPS
worker. Local validation confirmed every report hash, implementation digest, input-file index,
policy hash, and Decimal trade-ledger metric. Every report remains bound to 0.5% trade risk
and 5% daily loss. All 11 decisions are REJECTED: 11/11 pass sample count, 2/11 pass positive
net edge, 0/11 pass stressed edge, 0/11 pass profit factor, 5/11 pass drawdown, and 1/11 pass
window consistency. These 1,183 modeled trades span independent per-symbol reports and do not
represent one portfolio return.

Exit-reason review found 627 `STOP_LOSS` exits, 293 `TAKE_PROFIT` exits, and 263 `TIME_STOP`
exits. Their combined per-symbol report net/stressed PnL was respectively -235.945/-289.092,
+165.403/+145.138, and +38.492/+18.574 USDT; these diagnostics are not portfolio returns.
Stop-loss losses dominate, but this evaluated OOS set must stay out of further tuning.

No report was admitted or used to retune this evaluated OOS set. The remote qualification unit
completed with `Result=success` and is inactive. The protected trader remains active at PID
87549 with `NRestarts=0`; no production service, key, live account setting, or exchange order
was changed. Reports were copied to `artifacts/qualification/runtime-macro-current-20261014/`.

## 2026-10-14 03:16 MYT — risk reaffirmed and actual-capital Macro replay rejected

The user confirmed **0.5% of actual exchange account equity per trade** remains the
approved risk. A fresh authenticated, read-only Testnet observation measured equity at
4,224.09882354 USDT; wallet and equity reconciled with zero drift, and the account was flat
with no orders. That observation is a sizing seed for historical research only. The
`daily_risk.verified` value is false because no UTC day-start baseline was configured, so
this snapshot is not evidence for the live 5% daily-loss cutoff and grants no execution
authority. The sanitized observation is preserved at
`artifacts/qualification/runtime-inputs/testnet-account-probe-20261014-1791918191661.json`.

The new explicit capital-scenario CLI path was exercised on the VPS with `--equity-evidence`.
The offline Macro replay completed all 11 pair jobs under a credential-free user unit limited
to two CPU cores and 4 GiB memory; elapsed time was 2m10s and peak memory was 1.2 GiB. Its
frozen policy and every report bind starting equity 4,224.09882354, 0.5% trade risk, and 5%
daily loss. Every report self-hash and source-file index, including the underlying cache
bytes, verified locally. The targeted test set for the capital-scenario change passed (32);
Ruff, formatting, and strict mypy passed. No full suite was run.

All 11 reports remain **REJECTED**: sample count 11/11; positive net edge 3/11; profit factor
0/11; drawdown 5/11; profitable-window consistency 2/11; stressed net edge 0/11. The 1,216
modeled trades belong to independent symbol reports and do not establish a combined-wallet
result. The batch uses the same historical sample as the prior current-source Macro replay,
so it is a capital-sensitivity check, not a fresh holdout and not a basis for further tuning.
No candidate was admitted. Reports are stored in
`artifacts/qualification/runtime-scalper-equity-4224-20261014/`.

Final read-only VPS status shows the protected trader active at PID 87549 with
`NRestarts=0`; the qualification unit completed successfully and is inactive. The worker
used no API key and submitted no orders. The 5% daily-risk baseline remains unverified, no
Macro strategy qualifies, and the admission manifest remains empty.

## 2026-10-14 06:09 MYT — 12-pair ICT capital-sensitivity replay rejected

The user reaffirmed 0.5% equity risk per trade. The six-pair local and six-pair isolated VPS
ICT `limit_touch` replays used 0.5% per-trade risk, 5% daily loss, and the 4,224.09882354 USDT
Testnet snapshot as a historical sizing seed. Its UTC day-start risk baseline is unverified,
and reports grant no execution authority.

All 12 reports are **REJECTED**: sample count 4/12; positive net edge 0/12; stressed edge
0/12; profit factor 0/12; drawdown 12/12; profitable-window consistency 0/12. The 292
modeled trades are across independent per-symbol reports, not one combined account result.
This is sensitivity analysis on the same historical sample, not a new holdout; no retuning or
admission followed. All report hashes, eight implementation hashes per report, source indexes,
and underlying bytes verified locally. No full-suite tests were run; this replay changed no
code.

The isolated Kainode worker used two CPU cores and 4 GiB maximum memory, completed all six
pair subprocesses with exit code zero, and is inactive after success. Final read-only SSH
confirmed the protected trader remains active at PID 87549 with `NRestarts=0`. No credentials,
orders, production services, account settings, or admission records changed. Both artifact
sets are preserved under `artifacts/qualification/runtime-ict-equity-4224-20261014/` and
`artifacts/qualification/runtime-ict-equity-4224-20261014-vps-v2/`.

## 2026-10-14 06:17 MYT — remove fabricated canary telemetry defaults

The user reconfirmed per-trade risk at 0.5% of actual exchange account equity. The risk
planner and frozen qualification policy already use that value; no replay or policy change
was needed.

Canary response-model defaults now fail closed: unverified responses are not marked
verified or paper-safe; live telemetry fields are unknown/null until sourced; and absent
macro data blocks long entries without claiming a bearish regime or inventing BTC prices
and EMAs. The unused `_fetch_macro_gating_state` helper was removed because it seeded fixed
values and could fall back to an old artifact. The verified-artifact loader now reads
required solvency fields directly and leaves a missing timestamp absent rather than
inventing a current-time timestamp. A focused test file covers these defaults.

Validation passed: 19 targeted canary unit tests, Ruff, Ruff format check, strict mypy for
`canary.py`, and `git diff --check` on the changed source. No full suite ran. A read-only VPS
query showed the protected trader active at PID 87549 with `NRestarts=0`; no matching
qualification/replay/probe systemd units were running. No VPS, production, exchange, or
account state was changed. Strategy qualification and shared-wallet portfolio evidence
remain unresolved; the current-source 12-pair ICT reports remain rejected.

## 2026-10-14 06:24 MYT — remove stale Stress-page fallback claims

The Phase 297 frontend adapter no longer fabricates a $100 balance, zero-drift pass, passing
sub-millisecond latency, 100% reserve, or $7 loss budget when evidence is missing. The page
now stops at an unavailable-evidence state; verified artifacts are labeled historical and
show only values present in the artifact. Removed stale “real-time” claims and fixed 40%
reserve and 93% survival floors that conflict with the current no-reserve-floor policy.

Validation passed: 7 targeted Vitest tests, frontend production build, plus the 19 targeted
Python canary tests, Ruff, format check, strict mypy, and scoped `git diff --check`. No full
suite ran. Additional fixed fallback metrics remain in other stage-specific builders in
`frontend/src/lib/canary.ts`; project-wide telemetry cleanup is still in progress. The live
daemon and VPS state were not changed.

## 2026-10-14 06:43 MYT — retain 0.5% trade risk and bind Macro commissions

Per-trade equity risk remains 0.5%, matching the planner and frozen workers; the separate
daily-loss trigger remains 5% of UTC day-start equity. Macro short entries now preserve
their SELL side through planning when BTC regime is bearish. All Macro qualification paths
require the authenticated commission snapshot and bind its symbol rates and file hash into
report provenance. No replay was started and no admission was granted.

Validation: 65 targeted Python unit tests passed; Ruff, formatting, strict mypy, and scoped
whitespace checks passed. The full suite was not run. Production, VPS, credentials, and
exchange state were not accessed or changed.

## 2026-10-14 06:46 MYT — correct holdout consumption state

The Aug–Sep 2026 holdout index and README no longer label the entire dataset untouched. A
frozen LINK Macro candidate had already been evaluated on that interval and was rejected;
its report is source-stale and diagnostic only. The use of LINK market/funding and BTC 1h
regime context is now recorded with the report's SHA-256. The other ten target-symbol
partitions remain uninspected. One focused ledger-integrity test passed.

Fresh SSH returned `Permission denied (publickey)`, so current VPS worker state could not be
verified. Local inspection found no matching worker; the admission manifest remains empty.
No worker was started, no service was touched, and no full-suite tests ran.

## 2026-10-14 07:07 MYT — symmetric-short Macro grid completed

The user reconfirmed 0.5% account-equity risk per trade; that is already frozen into the
research policy. The local development grid completed 275/275 jobs with zero failures,
passed its final protocol/source integrity checks, and all report file SHA-256 values match
the final summary. All five development-gate passes are XRPUSDT parameter variants; the
other ten symbols have none. The top development-ranked variant is distance -4.0 / 3.0 ATR
(32 trades), with net PnL 180.7171 USDT and stressed net PnL 65.6800 USDT. Reports remain
development-only with execution authority disabled.

No selection or admission artifact was created. The XRP market/funding partition in the
reserved Aug–Sep interval is individually uninspected, but BTC 1h shared regime context from
that interval was used by an earlier rejected LINK diagnostic. Any subsequent validation
must disclose that partial shared-context consumption; it cannot claim a pristine
common-context holdout. No tuning used that interval. The grid made no VPS, credential,
exchange, account, order, or production-service changes. Fresh SSH access was unavailable at
the previous check, so current VPS worker state is unverified. No tests were run because
this checkpoint changed documentation only; the full suite remains delegated to GitHub
Actions.

## 2026-10-14 07:10 MYT — remove fabricated Phase 307 bridge values

The bridge model and page no longer display a connection, mock key, listen key, orders,
filters, balance, paper-safe state, execution-off state, or zero-drift pass without API
evidence. Partial responses remain unverified; missing data renders as unknown/unavailable,
and symbol filters come from the returned data. The status badge is warning-colored until
the response is verified.

Validation passed: 3 targeted bridge-page tests, TypeScript and production frontend build,
and scoped `git diff --check`. No full suite ran. Remaining stage-specific canary mappers
and production-launch fallbacks still include fixed telemetry and legacy capital values, so
the data-driven frontend audit continues. No remote or trading state was changed.

## 2026-10-14 07:27 MYT — full engineering handoff to Antigravity

The owner requested return to Antigravity. The consolidated transfer guide is
`ANTIGRAVITY_HANDOFF_2026-10-14.md`, with canonical policy/architecture kept in
`CODEX_HANDOFF.md`, and custody/read-only/research snapshots under
`docs/handoff/2026-10-14/`. Older transfer documents point to the current guide while
preserving their historical text. The rollout guide now explicitly records the unresolved
protected-PID/same-key activation contradiction instead of prescribing incompatible states.

Pinned explicit-key read-only SSH at approximately 07:22–07:23 MYT succeeded: trader active
at PID 87549/NRestarts=0, web active at PID 287760/NRestarts=0. No active matching research
or replacement user unit was shown; two failed historical BTC/LINK cache-builder units
remain. The scoped metadata snapshot supersedes the earlier SSH failure, but does not
verify current exchange balances or process-loaded code.

Transfer file-integrity checks passed for all 120 grid inputs and 275 report file/self-hashes.
Five XRP development passes remain non-admissible; no candidate/qualification was created.
The admission manifest remains empty. No application source, remote service, credential,
account or order was changed for transfer; no tests, deployment, commit or push were run.
The dirty checkout and all local evidence must be preserved for the incoming engineer.

## 2026-10-14 11:50 MYT — Antigravity continuation: XRP holdout evaluation, shared-wallet portfolio engine, durable autopsy-to-Creator feedback, and frontend UI/UX cleanup

Following the owner's `/goal` instruction on the 14 October 2026 handoff, Antigravity completed the five continuation workstreams without modifying any of the eight grid-fingerprinted files (`macro_liquidity_scalper.py`, `trade_plan.py`, `daily_risk.py`, `runtime_qualification.py`, `qualify_runtime_scalper_variant.py`, `run_scalper_development_grid.py`, `select_scalper_development_candidates.py`, `freeze_scalper_development_grid.py`) and without touching the protected VPS daemon (`autonomous-futures-trader.service`, MainPID `87549`, `NRestarts=0`).

1. **Frozen XRP candidate bridge & single preregistered Aug–Sep 2026 holdout evaluation:**
   - Generated the frozen development selection manifest `research/qualification-development-2024-2026/scalper-symmetric-short-selected-candidates-v3.json` (`SHA-256: 34668f7e2b9079a08679c948fc7fae6facf0a40f4530997b220c80bb94c75da7`, `selected_count=1`, `XRPUSDT` distance `-4.0` / target `3.0` ATR).
   - Built `scripts/bridge_scalper_candidate_for_holdout.py` to bridge the aggregate `SELECTED_FOR_SINGLE_HOLDOUT` manifest into the per-candidate `FROZEN_BEFORE_VALIDATION` schema (`research/qualification-development-2024-2026/frozen-xrp-symmetric-short-candidate-v1.json`, `SHA-256: cb5a7e34c892c78b6a7fa6278ce66b6cf42d982ac6c48e23ce97395c751d27cf`) while enforcing `holdout-index.json` partition checks and disclosing prior `BTCUSDT` `1h` shared-context consumption.
   - Built the official `XRPUSDT` Aug–Sep 2026 market and funding caches (`research/immutable-data/scalper-xrp-forward-cache-local-20261014`, `research/immutable-data/scalper-forward-funding-local-20261013/funding/XRPUSDT-funding.csv`) and updated `scripts/qualify_frozen_scalper_candidate.py` to support optional `--funding-dir` and `shared_context_disclosure`.
   - Executed the single preregistered Aug–Sep 2026 holdout evaluation (`artifacts/qualification/runtime-scalper-xrp-holdout-2026-08-2026-09/XRPUSDT-92d4ce70f71e7096.json`, `SHA-256: 706adb88cb44c72f248304447918bfacece5f9f6598812d80f4fd11796a4de57`): 1 signal, 0 fills (`unfilled=1`), `net_pnl=0 USDT`, `decision="REJECTED"`, `execution_authority=false`. Updated `research/qualification-holdout-2026-08-2026-09/holdout-index.json` (`SHA-256: 5529f6ce37bf2f225c6cd3414675daa665bd73b4df8aee0843e0e9189809ec22`) and `README.md`. `deploy/qualification-admission.json` remains empty (`approved_reports: []`).

2. **Causal shared-wallet portfolio qualification engine:**
   - Implemented `src/autonomous_futures/research/portfolio_qualification.py` (`PortfolioLedger`, `PortfolioMemberSpec`, `PortfolioPendingOrder`, `PortfolioOpenPosition`, `simulate_shared_wallet_portfolio`, `qualify_scalper_portfolio`) and CLI runner `scripts/run_portfolio_qualification.py`.
   - Enforces a single shared Decimal wallet across multiple symbol members, reserving margin across concurrent pending entries and open positions, applying maker/taker fees and funding, enforcing the shared 5% UTC-day-start daily-loss circuit, and verifying `|wallet_drift| < 10^-15` and `|equity_drift| < 10^-15` at every bar (`artifacts/qualification/portfolio-scalper-development-20261014/portfolio-bd20efcc58d951e1.json`, `SHA-256: 8bf6a10945fd61619bb7798fd80d12bf6b854240afd7d3e6a28be4121e9bf9c2`).

3. **Durable fill-reconciled autopsy evidence & Creator self-learning loop:**
   - Implemented `src/autonomous_futures/execution/trade_autopsy_evidence.py` (`build_closed_trade_autopsy`, `summarize_autopsy_feedback`) and integrated `_record_closed_autopsy` into `LifecycleCoordinator` (`src/autonomous_futures/execution/lifecycle_coordinator.py`) so every exchange-reconciled closed owned trade persists `trade["outcome_autopsy"]` in `owned-trades.json` and writes durable records to `trade-autopsies.json`.
   - Updated `src/autonomous_futures/research/creator_prompts.py` (`RUNTIME_RISK_POLICY_GUIDELINES` enforcing the `0.5%` account-equity risk / `5%` UTC day-start daily-loss policy and injecting `autopsy_feedback` into `build_creator_revision_messages`) and `src/autonomous_futures/api/strategy_router.py` (`_load_recent_autopsies` merging fill-reconciled `trade-autopsies.json` records with SQLite autopsies).
   - Fixed `ContinuousSelfDrivingTrader.run_single_cycle` (`getattr(self.gateway, "offline_mode", True) is False`) and migrated stale 8-pair / `0.55` test assertions across the Phase 317 M4 test suites.

4. **Frontend UI/UX truthfulness, Phase 309 partial-data hardening & policy alignment:**
   - Updated `frontend/src/lib/canary.ts` (`buildProductionLaunchModel`) and `frontend/src/components/production-launch-page.tsx` to eliminate fabricated partial-data fallbacks (`$100` balance, `BTC/ETH/SOL` prices, `ord-p309`, `$5/$25/75%/$3` limits, static 3-pair universe, fallback Merkle root, and passing checklist claims on incomplete payloads).
   - Updated `frontend/src/components/evolution-page.tsx` to deterministically compute `SHADOW_OOS_GATE` cycle progress when `closed_trades_count` and `required_trades_count` are supplied without fabricating progress when `liveProgress` is null.
   - Updated `frontend/src/components/mission-control/types.ts` and `frontend/src/lib/use-ict-signals.ts` so `getFallbackIctSignals()` reports `verified: false` instead of claiming `verified: true` on offline fallback state.
   - Updated `frontend/src/components/mission-control/pair-price-tickers-card.tsx`, `frontend/src/components/executive-positions-page.tsx`, and `frontend/src/components/mission-control/kpi-cards.tsx` to display institutional bias/standby labels and the `0.5% Risk / 5% Daily Loss` policy badge.

5. **End-to-end AI Self-Learning feedback bridge & turnkey VPS preflight tooling (13:07 MYT):**
   - Added `build_runtime_qualification_failure_feedback` in `src/autonomous_futures/research/creator_failure_feedback.py` so rejected runtime/holdout/portfolio qualification reports (including `XRPUSDT-92d4ce70f71e7096.json`) and durable `trade-autopsies.json` records project directly into `CreatorQualificationFailureFeedback` for `LearnerCritic` and `CreatorGenerator`.
   - Created `scripts/preflight_qualified_runtime.py` and `tests/unit/test_preflight_qualified_runtime.py` to verify `deploy/qualification-admission.json`, Hawkes calibration (`runtime-hawkes-calibration-20261013.json`), `ACCOUNT` `0.5%` / `5%` capital policy, 12-pair universe, read-only `LegacyWriterHandoffGuard`, and durable `trade-autopsies.json` state.
   - Targeted Python unit suites, `ruff check`, `mypy`, frontend Vitest suites, and `npm run build` (`tsc -b && vite build`) passed cleanly.
   - Read-only SSH check at 2026-10-14 13:06 MYT confirmed `autonomous-futures-trader.service` (`ActiveState=active`, `SubState=running`, `MainPID=87549`, `NRestarts=0`) and `autonomous-futures-web.service` (`MainPID=287760`, `NRestarts=0`) remain active and untouched.

## 2026-10-14 16:28 MYT — AI Self-Learning strategy discovery & OOS qualification runs (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `SUIUSDT`, and `XRPUSDT + SUIUSDT` portfolio)

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

## 2026-10-14 16:48 MYT — SUIUSDT & Portfolio Independent Holdout Validation (`2026-08-01..2026-10-01`)

1. **Frozen `SUIUSDT` Holdout Candidate Manifest (Before Holdout Cache Derivation):**
   - Created `research/qualification-development-2024-2026/frozen-sui-symmetric-short-candidate-v1.json` (`candidate_id = "macro-scalper-suiusdt-d-3.4-t4.5"`, `manifest_hash = "be53bfeb4c386ab6e6a402388f2c5c5140c0242a1ec29a5ed9992915e9811a27"`, `SHA-256 = "8527e9c4e5175e0bc6f3e92a7bdca8895c234eec4483910cbe89088a39509607"`, `status = "FROZEN_BEFORE_VALIDATION"`, `execution_authority = false`).
   - Built official `SUIUSDT` `2026-08..2026-09` market and funding caches (`research/immutable-data/scalper-sui-forward-cache-local-20261014` and `research/immutable-data/scalper-forward-funding-local-20261013/funding/SUIUSDT-funding.csv`, `SHA-256 = "cd966a0dbe4755b7a87f508e652111c24568d8d853a6ec2e0c9106210b722084"`) from checksum-verified official archives after freezing the manifest.
2. **Single Preregistered Holdout Evaluation (`2026-08-01..2026-10-01`):**
   - **Single-Symbol `SUIUSDT` Holdout (`scripts/qualify_frozen_scalper_candidate.py`)**: `artifacts/qualification/runtime-scalper-sui-holdout-2026-08-2026-09/SUIUSDT-3072a78e72c0be73.json` (`report_hash = "3072a78e72c0be73c696869c8c1411578ea2e22b16d49e8e15b8324fa4a99b68"`, `SHA-256 = "9453c1044842fffce63f6af7328d91cc015701de8d0aa4c3dab898badf9829a9"`). Achieved positive net PnL (`+6.641106384 USDT`, `positive_net_edge = true`, `profit_factor = true`, `drawdown = true` with `52.2405 USDT` drawdown) across `6` filled trades (`profitable_windows = 2/5`, `stress_net_pnl = -15.1784 USDT`); formally `decision = "REJECTED"` (`execution_authority = false`) on the 30-trade minimum OOS sample and 2x fee/slippage stress gates.
   - **Shared-Wallet Portfolio `XRPUSDT + SUIUSDT` Holdout (`scripts/run_portfolio_qualification.py`)**: `artifacts/qualification/portfolio-scalper-holdout-2026-08-2026-09/portfolio-1c0ce7320bb8600d.json` (`report_hash = "1c0ce7320bb8600d2330869fc8c7c2c62b5352179c3d6cc4fdebf81508080981"`, `SHA-256 = "8bf5fbbd28471752db71603f360a750f87572d5cba2f06b8a8ff29a89d77d444"`). Achieved positive net PnL (`+6.350334368 USDT`, ending equity `4230.4492 USDT`, `positive_net_edge = true`, `profit_factor = true`, `accounting_reconciled = true`, `drawdown = true` at `1.405%` / `59.3596 USDT`); formally `decision = "REJECTED"` (`execution_authority = false`) on the 30-trade minimum OOS sample (`trade_count = 6`) and 2x fee/slippage stress gates.
   - Updated `research/qualification-holdout-2026-08-2026-09/holdout-index.json` (`SHA-256 = "55c44ee18f5500a841441d84555894bb35f3691f5b767529fdb9e5408d72e77b"`) and `research/qualification-holdout-2026-08-2026-09/README.md`. `deploy/qualification-admission.json` remains empty (`qualified_families: []`, `execution_authority: false`).
