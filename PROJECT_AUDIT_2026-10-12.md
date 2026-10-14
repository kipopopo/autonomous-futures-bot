# Project audit — 12 October 2026 (MYT)

Read-only engineering review against CODEX_HANDOFF.md and the user's capital constraints. No trading code was changed, no orders were submitted, no services were restarted, and no tests were run. The working tree contains extensive pre-existing modifications and untracked files, which were preserved.

## Scope and evidence limits

Reviewed the repository structure, deployed service command, daemon entry point, strategy-to-execution paths, gateway, candle ingestion, accounting, API telemetry, evolution UI, deployment definitions, and CI. This is a cross-project audit focused on production paths, not a line-by-line certification of every research module or a profitability assessment.

Read-only SSH confirmed autonomous-futures-trader.service active, MainPID=87549, NRestarts=0. Its ExecStart still specifies SOLUSDT,ETHUSDT,BTCUSDT. SHA-256 hashes of execution/self_driving.py and execution/continuous_trader.py match local files. Files on disk do not establish which code the existing Python process has loaded; its in-memory module versions were not inspected.

The VPS /api/v1/execution/status response reported 15 orders. Several SOL limit drill records have price=185, quantity=0.03, notional=5.55, status=NEW, fill_price=185, fee=0.00111. These are API observations, not independent confirmation of exchange fills or present balances.

## Findings

1. **Critical — strategy dispatch records simulated fills instead of placing exchange orders.** In src/autonomous_futures/execution/self_driving.py:799, 804–909, 1355 and 1403, entry/exit paths call _execute_fill directly. That method marks FILLED and mutates positions/ledger without a gateway submission or exchange fill confirmation. _flatten_all_positions at 1410 onwards likewise clears internal positions without closing exchange positions. The separate execution drill does submit gateway orders; successful drills do not validate daemon execution.

2. **Critical — execution API conceals positions and exposure.** src/autonomous_futures/api/app.py:947–976, 1080–1087 and 1316–1327 constructs zero position quantities, zero margin/unrealized PnL, zero aggregate exposure and 100% reserves irrespective of candidate position state. Missing evidence produces verified=True and MICRO_CAPITAL_ACTIVE at 845–882. This endpoint cannot establish that the exchange account is flat or safe.

3. **Critical — strict $5 cap is deliberately relaxed.** execution/self_driving.py:536–611 and 1256 onwards permit target cap plus one quantity step. feed/execution_drill.py:437–488 has the same allowance. The live API contains $5.55 drill orders. Strict cap and exchange minimum/step filters may be incompatible for a symbol/price: the correct result is no order, not a cap exception or invented smaller BTC step size.

4. **High — protective orders can become exposure-increasing orders.** execution/binance_gateway.py:691–694 retries a conditional order with reduceOnly=false. feed/execution_drill.py:770–842 also retries TP/SL with reduce_only=False. An exit intended to reduce exposure can open/reverse a position if triggered when the original position is absent; protective intent must fail closed.

5. **High — market-data outages do not stop evaluation.** execution/continuous_trader.py:249–255 treats a failed position-risk lookup as an empty account. feed/kline_sequencer.py retains stale buffers on fetch failure, and the caller continues strategy evaluation without freshness gates. Unknown account state must not mean flat.

6. **High — advertised 12-pair trading does not match the service command.** deploy/autonomous-futures-trader.service:15 specifies three symbols. scripts/run_phase_310_real_autonomous_trading.py removes BTC from scalper symbols and passes SOL/ETH explicitly, overriding the expanded default. The sequencer then receives BTC/SOL/ETH only. Twelve dashboard rows and registered genomes do not establish twelve actively scanned/traded pairs.

7. **High — macro strategy omits the required BTC 4h gate.** execution/continuous_trader.py calls evaluate_and_dispatch_scalper without btc_4h_candles. strategy/macro_liquidity_scalper.py:180 makes the 4h check conditional on data being supplied. Sequencer capacity is 150 bars, below the 200-bar EMA requirement; fetching only 100 initially compounds warmup issues.

8. **High — Hawkes/heartbeat protection is supplied with constants.** execution/self_driving.py:1198–1204 supplies spectral radius=0.15 and heartbeat age=50ms rather than measured microstructure. dispatch_ict_intention does not run the equivalent Hawkes/heartbeat checks. These paths do not enforce the promised live microstructure veto.

9. **High — candle closure and gap provenance are lost.** execution/continuous_trader.py:347 labels candles[-1] a closed candle without checking close time. Raw REST candles are converted without retaining closure metadata. feed/kline_synchronizer.py inserts artificial flat bars for small gaps; the sequencer discards bars_interpolated and has_unrepaired_gap. Pattern detection can consume provisional or repaired candles without knowing their quality.

10. **High — ICT mechanics differ from the canonical strategy.** strategy/ict_mmxm.py:203 defaults to 50% OTE; execution/continuous_trader.py:122 explicitly selects 50%, whereas the handoff specifies 62–79%. ict_mmxm.py:920–966 counts any two qualifying FVGs in the displacement segment and skips adjacent qualifying indices; it does not enforce the documented consecutive Twin FVG rule. dispatch_ict_intention retains only TP1 (or TP2 as fallback), with no two-stage partial/final exit execution.

11. **High — accounting does not reconcile actual reserved funds.** safety/kill_switch.py:258–277 changes cash by fees and realized PnL but ignores qty/price for allocating margin. execution/self_driving.py converts Decimal values to float before recording them. Phase317SolvencyLedger at 169–178 adds unrealized PnL to both sides of the drift equation, differing from the literal handoff invariant and cancelling that term. Internal zero drift is not proof of exchange reconciliation or available cash. The correct futures accounting identity needs an explicit specification before repair.

12. **High — startup does not restore risk state.** execution/self_driving.py:215–299 initializes capital, positions, loss totals and order counters afresh; DB initialization does not restore them. continuous_trader.start reads wallet balance for logging/notification, not ledger reconciliation. Existing exchange positions can therefore have no local entry/bracket state. intra_day_loss_usdt increments on gross losing closes, excludes fees/unrealized losses, and has no date rollover in this engine.

13. **High — production fallbacks fabricate data and health.** api/app.py:788 onwards returns anchor prices; 2429–2482 generates sinusoidal candles when real sources fail. app.py:1045 clamps BTC report prices above 90,000 to 82,600. frontend/src/components/evolution-page.tsx:150 onwards supplies active daemon=true, PID=87549, heartbeat=42ms, 80% progress, generation numbers and all 12 scanned symbols when live progress is missing. api/canary.py also contains fixed daemon status/PID. Data unavailable should be explicit, not fabricated live state.

14. **Medium — order history is filtered by historical prefixes.** api/app.py:1298–1311 accepts only canary-p310-/canary-p311- records. Phase 317 dispatch IDs are consequently excluded. NEW order acknowledgements also receive fill prices/estimated fees in drill adaptation, so the displayed history does not consistently separate submission from fills.

15. **Medium — signal API is a separate evaluator, not daemon telemetry.** api/strategy_router.py builds signals using public REST when there is no shared trader/sequencer, evaluates independently, and returns verified=True even when fetch/evaluation fails. The daemon entry point does not bind itself to the separately running web process. Dashboard readiness is not proof that the trading process saw or dispatched that setup.

16. **Medium — duplication and deployment drift increase maintenance risk.** BTC/scalper candles are fetched by both the sequencer and update_market_candles. deploy/autonomous-futures-trader.service and deploy/systemd/autonomous-futures-trader.service duplicate the same definition. Multiple CentralizedSolvencyLedger classes exist in safety, auto_evolution, alpha_ensemble, orchestrator, regime_calibration and testnet_bridge. production/self_driving.py and execution/self_driving.py are distinct engines; the root continuous_trader.py is only a re-export shim, not another daemon. Research implementations may be legitimate archived experiments; do not delete them without an import/dependency map.

17. **Medium — CI covers Python but not the frontend.** .github/workflows/quality.yml runs pytest, Ruff, mypy and compileall, with no Node install, frontend build or Vitest. Its push trigger is main only (plus pull_request). Existing untracked strategy/frontend files are not included in CI until committed. Passing Python CI would not validate dashboard changes.

18. **Medium — simulation bootstrap shares the production artifact destination.** scripts/run_phase_310_real_autonomous_trading.py generates synthetic baseline artifacts if production-summary.json is absent; run_phase_310_execution deletes prior files before constructing offline data. Keep fixture/simulation artifacts separate from operational evidence.

## Repair order

1. Make account/execution telemetry truthful: unknown/unavailable states, actual exchange positions, real evidence timestamps, and submitted-versus-filled order states. Remove synthetic production fallbacks.
2. Implement an exchange-confirmed order lifecycle with pending-order exposure reservation, partial fills, idempotent reconciliation and strictly reduce-only exits. Keep simulated matching isolated.
3. Enforce exact micro-capital limits using exchange-derived filters and Decimal accounting; skip infeasible orders. Restore state and reconcile balances before enabling dispatch.
4. Unify the universe, closed-candle feed, freshness/gap gates and canonical strategy parameters. Connect measured Hawkes telemetry and explicit candidate qualification gates.
5. Add frontend CI; then map imports and consolidate duplicated production components while keeping research artifacts clearly archived.

The running trader must remain untouched under the user's explicit constraint. Any future activation plan must account for its old in-memory code; copying changed files does not safely update that process.
