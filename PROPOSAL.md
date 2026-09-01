# Architecture & Development Proposal
## Autonomous LLM Futures Trading System

**Document version:** 0.1  
**Prepared:** 6 August 2026 (MYT)  
**Status:** Proposal for review — no production bot, authenticated exchange client, deployment, or live trade has been created  
**Working title:** `Autonomous Futures Bot`; permanent product name is intentionally not locked yet  
**Starting portfolio:** USD 100 evidence capital  
**Initial venue reference:** Binance USDⓈ-M Futures public data and demo interfaces  
**Project boundary:** New standalone project; not a continuation, fork, or module of VibeCrypt

> **Important:** This proposal defines a system that can eventually trade autonomously only inside a deterministic risk envelope and only after venue/legal eligibility is resolved. It does not promise profit and does not authorize live trading.

---

## 1. Executive decision

### 1.1 Recommendation

Proceed with a **test-first, modular-monolith build** beginning with two inseparable foundations:

1. **Autonomous Research Lab** — LLMs generate, challenge, and revise constrained strategy specifications;
2. **Deterministic Paper Execution Kernel** — every signal, risk decision, simulated order, fill, position, and reconciliation is reproducible without relying on an LLM.

Do **not** begin with a live “AI trader”. Live order capability is the last adapter to be enabled, not the first feature to be written.

### 1.2 What “complete autonomous” means here

After the system is operational, it should be able to perform the following loop without a human writing each strategy:

```text
observe data
  -> detect regime
  -> create hypothesis
  -> write constrained StrategySpec
  -> reject invalid specifications
  -> backtest causally
  -> run walk-forward and stress tests
  -> register all trials, including failures
  -> promote qualified candidates into paper trading
  -> generate signals and manage positions
  -> attribute results and detect drift
  -> throttle, quarantine, revise, or retire strategies
  -> repeat
```

Once a live environment has been explicitly unlocked, qualified strategies may open and close trades automatically. Nevertheless, the LLM never gains the right to:

- possess exchange secrets;
- send broker commands directly;
- alter risk limits;
- approve its own candidate;
- ignore a failed gate;
- convert an unknown order status into a retry;
- change the production strategy during an open trade.

### 1.3 Five governing principles

1. **Profit is an uncertain outcome**, not an engineering guarantee.
2. **USD 100 is evidence capital**, not an income target.
3. **LLM autonomy belongs in the research and analysis plane**, not the safety-critical execution plane.
4. **Paper/shadow evidence precedes live authorization.**
5. **Venue and legal eligibility are hard gates**, not warnings that code may bypass.

---

## 2. Product scope

### 2.1 Core product objective

Build an autonomous research-and-trading operating system that:

- learns from immutable market and experiment data;
- proposes falsifiable futures strategies;
- compiles only approved strategy primitives;
- evaluates candidates across time, symbols, costs, and regimes;
- deploys successful candidates to a deterministic paper broker;
- manages entry, stop, take-profit, timeout, and emergency exit;
- maintains one authoritative account/position ledger;
- explains every decision using stored evidence;
- can later execute on an approved venue through a replaceable adapter.

### 2.2 Initial market scope

| Item | Version 1 scope |
|---|---|
| Product | Linear USDⓈ-M perpetual futures |
| Reference symbols | BTCUSDT, ETHUSDT, SOLUSDT |
| Primary timeframe | 5 minutes; signals only on a fully closed bar |
| Secondary timeframe | 15 minutes; closed-bar regime context only |
| Position direction | Long and short |
| Position mode | One-way |
| Margin model | Isolated |
| Concurrent positions | One globally at first |
| Strategy families | Regime-gated trend/breakout and range mean reversion |
| Funding | Included as cost, feature, and trade veto |
| Execution environments | Offline replay → paper → shadow/demo → separately authorized live |

The symbol list is deliberately small. Expanding the universe before the cost, filter, risk, and reconciliation models are correct would increase false confidence rather than improve diversification.

The 5m cadence is for fresher research and operational visibility—not permission to scalp or raise turnover. The original 1h strategy horizons are rescaled into 5m-bar units, and a 15m value is visible to a 5m signal only after that 15m candle has closed. The prior 1h family screen is archived as a benchmark; it is not evidence for promotion under this new timeframe contract.

### 2.3 Explicit non-goals for Version 1

- guaranteed daily or monthly profit;
- high-frequency trading or latency competition;
- market making;
- martingale, unlimited grid, or averaging down;
- discretionary prose converted directly into an order;
- social-media or news-driven execution;
- reinforcement learning controlling live orders;
- automatic deposits, withdrawals, or transfers;
- multi-exchange arbitrage;
- portfolio margin or cross margin;
- a microservice fleet, Kubernetes, Kafka, or unnecessary distributed infrastructure.

---

## 3. Preconditions and stop signs

### 3.1 Deployment-jurisdiction assumption

Untuk tujuan engineering, kita menganggap paper/demo dan eventual runtime akan diletakkan pada VPS di luar Malaysia. Ini bermakna isu lokasi Malaysia **bukan blocker teknikal untuk Phases 0–6** dan tidak menghentikan kerja data, research, paper runtime, atau demo adapter.

Namun, lokasi VPS bukan mekanisme untuk mengelak geofencing, KYC, account restriction, atau product restriction. Sistem ini tidak akan mempunyai feature untuk bypass mana-mana restriction tersebut. Sebelum satu live adapter dihidupkan pada Phase 7, operator hanya perlu mengesahkan bahawa account, product, dan venue tersebut memang available kepada environment deployment. Itu ialah go/no-go operasi kemudian—bukan skop kerja engineering sekarang.

Therefore:

- public market data, offline replay, paper simulation, dan demo technical integration boleh diteruskan;
- no USD 100 deposit is part of the initial build;
- the domain model and exchange adapter remain venue-independent;
- a live adapter remains disabled until the separate Phase 7 go/no-go ceremony.

### 3.2 Current Binance integration facts

Binance currently documents `https://demo-fapi.binance.com` as the USDⓈ-M Futures testnet REST base URL and provides an official modular Python connector package.[51] The adapter must nevertheless be wrapped behind our own interfaces because package models, endpoint semantics, and exchange change logs must never leak directly into the trading domain.

A particularly important current change is that conditional USDⓈ-M orders—such as stop-market and take-profit-market orders—were migrated to the Algo Service, with `fapi/v1/algoOrder` used for placement.[52] Any implementation copied from older examples that submits those order types through the old normal-order path is unacceptable.

### 3.3 Proceed/stop rules

| Condition | Result |
|---|---|
| Research or offline backtest | Proceed locally |
| Deterministic paper broker | Proceed after test gates |
| Binance public market streams | Proceed as read-only data input |
| Demo authenticated trading | Separate approval after adapter tests; demo only |
| Live Binance trading | Deferred to the Phase 7 operator go/no-go; not a Phases 0–6 engineering blocker |
| Any exchange key with withdrawal permission | **Permanently rejected** |
| LLM direct access to exchange tool | **Permanently rejected** |

---

## 4. Architecture choice

### 4.1 Recommended style: modular monolith

Use one repository and one Python domain model, separated into strict modules and independently runnable processes. This gives:

- transactional consistency for the event ledger;
- simple local development and replay;
- fewer network failure modes;
- easier strict typing and refactoring;
- a clean path to split a component later only if evidence shows a real need.

We should not begin with microservices. The hardest problems are causal correctness, order-state uncertainty, risk invariants, and candidate overfitting—not service discovery.

### 4.2 System context

```text
                           UNTRUSTED INPUTS
              market data | exchange events | text/news later
                                      |
                                      v
+----------------------------------------------------------------------------+
|                         TRUST BOUNDARY: DATA PLANE                          |
|  schema validation | timestamp policy | provenance | gaps | deduplication  |
+----------------------------------------------------------------------------+
                | immutable DatasetManifest          | live MarketEvent
                v                                    v
+-------------------------------+      +-------------------------------------+
| AUTONOMOUS RESEARCH PLANE     |      | DETERMINISTIC TRADING PLANE         |
|                               |      |                                     |
| LLM Research Orchestrator     |      | Approved Strategy Runtime           |
|  - Hypothesis Generator       |      |          |                          |
|  - Strategy Spec Author       |      |          v                          |
|  - Economic Critic            |      | Signal -> OrderIntent               |
|  - Failure Analyst            |      |          |                          |
|  - Post-Trade Reviewer        |      |          v                          |
|          |                    |      | Risk Engine -> RiskDecision          |
|          v                    |      |          |                          |
| Typed Strategy DSL            |      |          v                          |
|          |                    |      | Order Manager -> BrokerCommand       |
|          v                    |      |          |                          |
| Offline Sandbox Verifier      |      |          v                          |
|          |                    |      | Paper/Demo/Exchange Adapter          |
|          v                    |      |          |                          |
| Candidate Registry            |      |          v                          |
|          |                    |      | Reconciler + Position Manager        |
|          v                    |      |                                     |
| Deterministic Promotion Gate -+----->| Signed CandidateManifest only       |
+-------------------------------+      +-------------------------------------+
                |                                    |
                +------------------+-----------------+
                                   v
+----------------------------------------------------------------------------+
| CONTROL & EVIDENCE PLANE                                                   |
| append-only events | experiment trials | model-call audit | incidents      |
| metrics | read-only dashboard | alerts | halt/resume ceremony | backups    |
+----------------------------------------------------------------------------+
```

### 4.3 Fast path versus slow path

| Path | Cadence | LLM allowed? | Purpose |
|---|---|---:|---|
| Market fast path | Every market/account event | No | Data validation, mark/account state |
| Risk fast path | Before and after every order/fill | No | Exposure, stop, balance, filters |
| Signal path | Bar close / approved event | No | Evaluate frozen strategy manifest |
| Daily evidence path | Daily | Optional | Attribution, drift, failure summaries |
| Research path | Weekly or manually triggered | Yes | Candidate creation and falsification |
| Promotion path | Evidence milestone | No final authority | Deterministic gate and signed manifest |

An unavailable LLM must never prevent an active strategy from reducing risk or closing a position.

---

## 5. Domain components

### 5.1 Market Data Ingestor

Responsibilities:

- collect public OHLCV, funding, mark price, index price, and instrument rules;
- consume WebSocket events with reconnect and sequence handling;
- backfill missing intervals through bounded REST requests;
- persist raw data before transformation;
- record source URL, request time, exchange event time, receive time, and schema version;
- emit data-quality incidents rather than silently filling unknown values.

It must not contain strategy logic.

### 5.2 Data Quality & Dataset Builder

Produces an immutable `DatasetManifest` containing:

- exact symbols and time range;
- source-file hashes;
- row counts and gaps;
- timezone and timestamp semantics;
- feature availability policy;
- fee/funding/filter snapshots;
- code and dependency version;
- creation time and manifest hash.

A backtest result without a dataset manifest is invalid.

### 5.3 Feature & Regime Engine

Version 1 approved feature catalog:

- returns and log returns;
- ATR and normalized ATR;
- realized volatility;
- Donchian highs/lows shifted by one completed bar;
- EMA slope and distance;
- ADX/directional strength;
- Bollinger z-score and width;
- RSI;
- volume and relative volume;
- funding paid/received and projected funding burden;
- spread/liquidity proxy;
- volatility and trend regime probabilities.

Every feature definition includes:

- observation timestamp;
- earliest availability timestamp;
- warm-up length;
- missing-data behavior;
- legal parameter range;
- unit and numeric type;
- test vectors for look-ahead prevention.

### 5.4 Strategy DSL Compiler

The LLM writes a typed specification, not executable Python. The compiler:

1. validates schema and DSL version;
2. rejects unknown features and operators;
3. rejects current-bar future leakage;
4. checks parameter bounds;
5. builds deterministic entry/exit expressions;
6. generates a content hash;
7. runs unit and property tests;
8. produces a frozen runtime manifest.

No `eval`, dynamic import, arbitrary code generation, shell access, or network access exists in this path.

### 5.5 Experiment Runner

Runs:

- train-only parameter search within a declared budget;
- frozen validation;
- rolling walk-forward;
- purged/embargoed splits where labels overlap;
- symbol and regime attribution;
- base and stressed costs;
- missed/partial-fill scenarios;
- funding and execution-delay scenarios;
- deterministic replay from a stored seed.

Every attempted parameter set is stored. Backtest-overfitting research demonstrates why selection history cannot be discarded,[33] and the Deflated Sharpe Ratio exists specifically to account for selection bias, non-normal returns, and repeated trials.[34]

### 5.6 Candidate Registry & Promotion Gate

Candidate states:

```text
DRAFT
  -> STATIC_REJECTED
  -> SANDBOXED
  -> HISTORICALLY_REJECTED
  -> PAPER_PENDING
  -> PAPER_ACTIVE
  -> SHADOW_PENDING
  -> SHADOW_ACTIVE
  -> ELIGIBLE
  -> ACTIVE
  -> THROTTLED
  -> QUARANTINED
  -> RETIRED
```

Transitions are append-only events. No row is overwritten to pretend a failed version never existed.

A promoted `CandidateManifest` contains:

- immutable strategy specification hash;
- data and feature version;
- accepted parameter set;
- allowed symbols/timeframes;
- cost assumptions;
- expected and invalidating regimes;
- risk-envelope identifier;
- validation evidence references;
- model/prompt provenance;
- promotion policy version;
- digital/content signature.

### 5.7 Paper Broker

The first broker is an internal deterministic simulator, not Binance demo.

It models:

- maker/taker fee schedules;
- bid/ask and configurable slippage;
- next-feasible-tick execution;
- market/limit/stop/algo-order semantics;
- partial and missed fills;
- funding transfers;
- quantity and price rounding;
- minimum notional;
- rejects, latency, and maintenance windows;
- balance, isolated margin, liquidation proximity, and realized P&L.

Paper fills must not use bar extrema in a way that assumes both favourable entry and favourable exit occurred in an impossible sequence.

### 5.8 Risk Engine

The risk engine is a pure deterministic decision function:

```text
RiskDecision = evaluate(
    AccountState,
    PositionState,
    InstrumentRules,
    MarketState,
    CandidateManifest,
    OrderIntent,
    RiskPolicy
)
```

Outputs are only:

- `APPROVE` with normalized quantity and protective requirements;
- `REJECT` with machine-readable reasons;
- `REDUCE` with a smaller approved quantity;
- `HALT_AND_FLATTEN` through an emergency policy.

The LLM receives the result later for analysis but cannot amend it.

### 5.9 Order Manager

Responsibilities:

- translate approved intent into venue-neutral broker commands;
- assign deterministic client-order IDs;
- enforce idempotency;
- create protective exit orders;
- track normal and conditional/algo orders separately;
- process partial fills;
- cancel and replace safely;
- prevent duplicate positions after restart;
- never retry an unknown-status order without reconciliation.

Binance states that one type of HTTP 503 response has **unknown execution status** and may represent a successful request.[51] Therefore the system first checks account stream/order query state using the client-order ID; blind retry is forbidden.

### 5.10 Position Manager & Reconciler

Exchange or broker truth overrides local assumptions. The reconciler compares:

- open orders;
- conditional/algo orders;
- positions and entry prices;
- isolated margin and leverage;
- balances;
- fills and commissions;
- funding events;
- local intent and event history.

Any unexplained mismatch changes runtime state to `HALTED`. Reconciliation must occur:

- at process startup;
- after reconnect;
- after every order terminal event;
- periodically as a fallback;
- before resuming from a halt.

### 5.11 API, dashboard, and controls

The dashboard is observational and operational, not a manual trading terminal.

Initial pages:

1. **System** — environment, health, data freshness, current state;
2. **Research** — hypotheses, trials, failed gates, accepted candidates;
3. **Strategies** — manifests, regimes, attribution, drift;
4. **Risk** — equity, drawdown, exposure, risk budget, halt reason;
5. **Execution** — intents, risk decisions, orders, fills, reconciliation;
6. **Costs** — fees, spread/slippage, funding, LLM and infrastructure cost;
7. **Incidents** — immutable timeline and resolution evidence.

Permitted operator actions:

- halt;
- emergency flatten when a broker adapter is authorized;
- acknowledge an incident;
- resume through a guarded ceremony;
- approve an environment transition such as paper → demo or demo → live.

There is no free-form “place order” form in Version 1.

---

## 6. Data contracts

### 6.1 `StrategySpec`

```yaml
dsl_version: 1
strategy_id: llm-generated-uuid
family: regime_gated_breakout
thesis:
  economic_rationale: "Capture sustained directional expansion after compression"
  expected_regimes: [directional_expansion]
  failure_modes: [false_breakout, volatility_shock, funding_drag]
universe:
  symbols: [BTCUSDT, ETHUSDT, SOLUSDT]
  timeframe: 5m
  regime_context_timeframe: 15m
features:
  - {name: donchian_high, lookback: 2016, shift: 1}
  - {name: donchian_low, lookback: 2016, shift: 1}
  - {name: adx, period: 168}
  - {name: normalized_atr, period: 168}
entry:
  long: "close > donchian_high AND adx >= 25"
  short: "close < donchian_low AND adx >= 25"
exit:
  channel_lookback: 864
  max_hold_bars: 2880
risk_request:
  stop_model: atr
  stop_multiple: 2.0
vetoes:
  - stale_data
  - spread_above_limit
  - funding_cost_above_edge_budget
  - runtime_not_normal
```

Numbers above are an illustrative valid shape, not an approved trading strategy.

### 6.2 `OrderIntent`

```json
{
  "intent_id": "uuid",
  "candidate_manifest_hash": "sha256:...",
  "symbol": "BTCUSDT",
  "action": "OPEN_LONG",
  "signal_time": "2026-08-06T01:00:00Z",
  "valid_until": "2026-08-06T01:05:00Z",
  "reference_price": "0.00",
  "requested_stop_price": "0.00",
  "requested_take_profit": null,
  "reason_codes": ["BREAKOUT", "REGIME_DIRECTIONAL"],
  "feature_snapshot_hash": "sha256:..."
}
```

The intent contains no leverage and no final quantity. Those belong to the risk decision.

### 6.3 `RiskDecision`

```json
{
  "decision_id": "uuid",
  "intent_id": "uuid",
  "decision": "APPROVE",
  "normalized_quantity": "0.000",
  "selected_leverage": 2,
  "estimated_loss_at_stop_usd": "0.75",
  "estimated_round_trip_cost_usd": "0.00",
  "post_trade_effective_leverage": "0.00",
  "required_protection": {
    "stop_required": true,
    "reduce_only_exit": true
  },
  "policy_version": "risk-v1",
  "reason_codes": ["WITHIN_TRADE_RISK", "FILTERS_VALID"],
  "input_state_hash": "sha256:..."
}
```

### 6.4 Numeric and time rules

- store money, price, quantity, fee, and funding using decimal semantics;
- do not use binary floating point in execution accounting;
- persist timestamps in UTC;
- display user-facing time in MYT/GMT+8;
- record both event time and receive time;
- all order/risk/event IDs are immutable;
- all content hashes use a canonical serialization;
- exchange filters come from runtime `exchangeInfo`, not constants.[13][21]

---

## 7. Autonomous LLM Research Lab

### 7.1 Agent roles

| Role | Input | Output | Authority |
|---|---|---|---|
| Research Orchestrator | Research backlog and trial ledger | Bounded task graph | Schedule research only |
| Hypothesis Generator | Approved data dictionary and prior failures | Falsifiable hypothesis | None over trading |
| Strategy Spec Author | Hypothesis and DSL schema | `StrategySpec` JSON/YAML | Candidate creation only |
| Economic Critic | Spec, evidence, cost model | Critique and falsification tests | Can recommend rejection |
| Failure Analyst | Slice metrics and incident evidence | Failure classification | Can recommend throttle/retire |
| Post-Trade Reviewer | Closed-trade attribution | Lessons and new tests | No runtime modification |
| Portfolio Proposer | Eligible candidates and covariance | Allocation proposal | Risk engine remains final |

No agent both creates and approves the same candidate.

### 7.2 Model/provider design

Version 1 locks every embedded research-role call to **Google AI Studio** through its official OpenAI-compatible endpoint. The permitted model identifiers are **`gemma-4-26b-a4b-it`** and **`gemma-4-31b-it`**; role policy selects one explicitly and no silent substitution is allowed. This is an application-runtime decision: the backend calls the provider directly through an OpenAI-compatible `LLMProvider` interface, not through Hermes delegation or an interactive agent session.

The provider API base URL and API key remain deployment-only credentials; they are never placed in source, `.env.example`, StrategySpecs, the database, trial records, prompts, logs, or this proposal. Kainode's verified systemd 255 runtime supports `systemd-creds`; after VPS hardening, the Google AI Studio key will be delivered to the non-root service through a root-managed encrypted systemd credential and read from its private `$CREDENTIALS_DIRECTORY` at startup. Startup must verify that the configured provider exposes the exact selected model ID. If it does not, the research cycle records `provider_model_unavailable` and stops—there is no silent model substitution.

Role-level configuration remains explicit even though the provider is shared and the model is selected per role:

```text
role -> provider -> model -> temperature -> token/request limit
```

For every model call, store:

- provider and exact model identifier;
- prompt-template hash;
- system-policy version;
- input evidence references;
- output schema validation;
- token/request metadata, declared price tier, and rate-limit delay;
- retry count and error;
- final output hash.

Free availability does not mean unlimited throughput. Each permitted model still has hard per-role token/request limits, a global in-flight-call cap, no automatic retries, and a research-batch budget. A model may not select its own replacement or raise its token/request budget. Model changes are configuration deployments with evaluation evidence.

Using either permitted model for generator, author, critic, and analyst roles does not merge their authority: they have different prompt templates, input bundles, schema outputs, trial identities, and deterministic gates. In particular, no role may create and approve the same candidate.

### 7.3 Bounded creativity

The LLM may combine only:

- approved feature names;
- bounded numeric parameters;
- approved boolean/arithmetic operators;
- approved entry, exit, veto, and timeout constructs;
- known strategy families or explicitly labelled experimental families.

It may not emit:

- arbitrary code;
- URLs to fetch during verification;
- package-install instructions;
- exchange commands;
- secrets;
- new unsafe operators;
- self-approval statements.

### 7.4 Prompt injection and confabulation

OWASP describes prompt injection as input changing model behaviour in unintended ways.[43] NIST defines confabulation as confidently stated but erroneous content.[46] Consequently:

- market/news/social/exchange text is always data, never an instruction;
- the model sees a sanitized evidence bundle, not unrestricted tools;
- fetched text cannot change system policy or tool permissions;
- model output is untrusted until schema and policy validation succeeds;
- numerical claims are recomputed deterministically;
- strategy citations/provenance are stored but never substitute for backtests;
- a second critic model may challenge a hypothesis, but deterministic tests remain the authority.

### 7.5 Research budget

Each autonomous cycle has hard limits:

- maximum hypotheses;
- maximum candidate specifications;
- maximum parameter trials per family;
- maximum LLM tokens and cost;
- maximum CPU time;
- maximum storage growth;
- no automatic budget increase after failure.

Recommended Version 1 default: no more than 20 fresh candidate specifications **per versioned research batch**. A batch may be scheduled more frequently, but it always receives a distinct budget, seed, and trial ledger. This limits selection bias and operating cost while preserving meaningful exploration.

### 7.6 Bounded parallel research scheduler

Yes—research may run simultaneously, but only as a **bounded, deterministic task graph**. Parallelism reduces wall-clock time; it must not multiply trial count, blur data provenance, or create concurrent writers to candidate state.

```text
Frozen DatasetManifest + ResearchRun seed
                 |
                 v
         Orchestrator creates immutable WorkUnits
                 |
                 +--> worker 1: family/symbol/fold/cost slice
                 +--> worker 2: family/symbol/fold/cost slice
                 +--> worker 3: family/symbol/fold/cost slice
                 |
                 v
          single-writer Aggregator + Qualification Gate
                 |
                 v
        immutable trial records / reject / eligible-for-paper
```

Each `WorkUnit` is pinned to one tuple:

```text
(research_run_id, dataset_manifest_hash, strategy_spec_hash,
 symbol, 5m/15m timeframe contract, temporal_fold, friction_profile, seed)
```

The scheduler deduplicates this tuple before work begins. Completion order has no effect on ranking, promotion, or the next candidate batch.

| Activity | V1 concurrency | Boundary |
|---|---:|---|
| Exchange/public-data fetches | Up to 3 I/O requests | Respect API budget; one separate canonical writer commits each dataset partition |
| Parquet canonicalization / feature materialization | 1 | Avoid disk/memory thrash and duplicate artifacts |
| CPU research evaluation | **4 active CPU workers** initially | Kainode target has six vCPUs; reserve capacity for OS, data, database, and safety services |
| LLM hypothesis/spec work | **Up to 4 in-flight calls** | Network-bound independent hypotheses; token/cost quota remains shared |
| Critique | Shares the 4-call LLM cap | A critic waits for its own specification; no self-approval |
| Trial aggregation, deduplication, qualification, promotion | 1 | Single authoritative writer and deterministic ranking |
| Paper/execution/risk/reconciliation | 1 | Never parallelize order authority or account state |

This deployment plan is sized from the verified dedicated Kainode target, not the laptop or the existing Hostinger VPS. A read-only preflight found six QEMU virtual CPU cores, 15 GiB RAM (about 15 GiB available), no configured swap, and 113 GiB free disk. Its load average was 0.15 / 0.29 / 0.18. At inspection it contained no deployed project directory, no failed systemd units, and no application listener beyond SSH/local resolver services.

For this project, the initial VPS runtime overlaps different resource types instead of launching many competing CPU workers:

```text
4 × CPU-heavy causal backtest / walk-forward evaluators
3 × public-data I/O fetch slots
up to 4 × network-bound LLM calls shared by generator and critic roles
1 × short single-writer artifact/candidate aggregator
```

The Autonomous Futures Bot research service will initially be provisioned with a separate systemd resource envelope of `CPUQuota=500%` and `MemoryMax=10G`. Before enabling recurring research, run a cached-only fixed-manifest benchmark at one, two, four, and five CPU workers. Raise the four-worker cap to five only when wall-clock, peak RSS, I/O wait, and deterministic-output checks demonstrate safe headroom. One vCPU/core remains reserved for operating-system, database, data-ingest, dashboard, and safety work.

Do **not** schedule a 3 × 3 × 6 nested fan-out for family × symbol × fold. Those are flattened into a backlog of WorkUnits governed by the four CPU-evaluation slots plus the separate I/O/LLM caps above. The same dataset snapshot, fee/slippage profile, and frozen OOS rules apply to every comparable candidate.

Parallel research can therefore make the project visibly active and finish a bounded batch sooner, while the number of hypotheses and trials remains fixed. It does not make weak strategies valid faster.

---

## 8. Candidate qualification protocol

### 8.1 Gate sequence

```text
G0 Schema + policy
G1 Causality and invariant tests
G2 Training search within declared budget
G3 Frozen validation
G4 Rolling walk-forward
G5 Trial-aware statistics
G6 Cost, latency, and execution stress
G7 Portfolio risk overlay
G8 Paper evidence
G9 Shadow/demo operational evidence
G10 Venue/legal/live ceremony
```

Failure at any gate creates a recorded rejection. The candidate does not skip ahead.

### 8.2 Provisional quantitative gates

These are Version 1 engineering thresholds and may be revised only through a versioned policy change—not by an LLM inside a run.

| Gate | Provisional requirement |
|---|---|
| Causality | All look-ahead, timestamp, warm-up, and next-execution tests pass |
| Reproducibility | Same manifest and seed reproduce identical decisions and accounting |
| Walk-forward | At least 6 frozen OOS windows covering materially different regimes |
| Trade evidence | At least 60 OOS closed trades; otherwise continue accumulating evidence |
| Base costs | Positive net expectancy after realistic fees, slippage, and funding |
| Stress costs | Positive aggregate expectancy at 2× modeled execution friction |
| Concentration | Result not explained primarily by one short period or a few extreme trades |
| Parameter stability | Neighbouring legal parameter values preserve the economic sign |
| Selection correction | DSR confidence target ≥95%; PBO target ≤20% when sample design supports it |
| Portfolio overlay | Maximum simulated account drawdown ≤8% under risk policy |
| Failure drills | Disconnect, stale data, partial fill, unknown status, and restart tests pass |
| Paper duration | At least 90 days **and** 50 completed paper trades, whichever takes longer |
| Reconciliation | Zero unresolved order/position/balance mismatches |
| Live eligibility | Legal, account, venue, key, operations, and human unlock complete |

If a low-turnover strategy cannot produce enough independent observations, the correct action is to wait or acquire more historical evidence—not lower the gate.

### 8.3 Stress suite

Required scenarios:

- fee at 1×, 1.5×, and 2×;
- volatility-bucket slippage;
- an additional bar/tick of delay;
- missed entry and missed exit;
- partial fills;
- spread shock;
- funding schedule/cap/sign change;
- symbol filter change;
- stale mark price;
- WebSocket disconnect and REST recovery;
- HTTP 503 unknown execution state;
- process crash after send but before local acknowledgement;
- duplicate stream event;
- exchange maintenance;
- delisting/suspension;
- correlated market crash;
- database restart and restored backup.

---

## 9. USD 100 money and risk policy

### 9.1 Capital objective

The first USD 100 account is used to verify:

- position sizing correctness;
- minimum-order feasibility;
- real versus modeled fees/funding/slippage;
- reconciliation;
- strategy behaviour with actual capital constraints;
- operational discipline.

It is not used to prove the system can produce meaningful income.

### 9.2 Default risk envelope

| Control | Version 1 default |
|---|---:|
| Starting equity | USD 100 |
| Normal risk per trade | 0.50%–0.75% of current equity |
| Absolute trade-risk cap | 1.00% |
| Selected leverage cap | 2× |
| Effective total notional cap | 1.00× equity |
| Concurrent positions | 1 globally |
| Concurrent position per pair | 1 |
| Daily loss stop | 2R or 2% equity, whichever is smaller |
| Drawdown throttle | 5% from high-water mark → halve risk |
| Drawdown halt | 8% → no new entries |
| Catastrophic kill | 10% or critical state mismatch |
| Margin mode | Isolated |
| Liquidation | Never used as planned stop |

### 9.3 Position sizing

```text
risk_budget_usd = equity * risk_fraction
raw_notional    = risk_budget_usd / stop_distance_fraction
cost_adjustment = estimated_entry_cost + estimated_exit_cost + funding_buffer
approved_notional = min(
    raw_notional adjusted for cost,
    equity * effective_notional_cap,
    symbol/account exposure limits
)
```

Then:

1. round price and quantity using current exchange rules;
2. recompute notional and loss after rounding;
3. validate minimum notional;
4. reject if the smallest valid order breaches the risk budget;
5. create required protective exits;
6. record every intermediate calculation.

Current filters and commission rates are runtime data. Binance documents symbol-level minimum notional filters[13] and account commission-rate fields,[24] so neither is a permanent hardcoded assumption.

### 9.4 Runtime state machine

```text
NORMAL
  | daily loss / 5% drawdown
  v
THROTTLED
  | 8% drawdown / repeated operational warning
  v
HALTED
  | critical mismatch / 10% drawdown / emergency
  v
EMERGENCY_FLAT
```

Only deterministic policy can move downward automatically. Resuming upward requires:

- reconciled state;
- resolved incident evidence;
- data freshness;
- healthy risk and broker components;
- guarded operator approval.

### 9.5 Economic P&L

Track three layers separately:

1. **Trading P&L** — realized/unrealized market result;
2. **Execution P&L** — after fees, spread, slippage, and funding;
3. **Economic P&L** — after LLM API and infrastructure cost.

The USD 100 is trading equity. LLM and infrastructure budgets are funded separately but must still be reported because an “autonomous profitable bot” whose model bill exceeds trading gains is not economically profitable.

The LLM is therefore absent from the per-tick and per-order path and normally runs only in bounded research/review cycles.

---

## 10. Storage and audit design

### 10.1 Storage choices

| Data | Store | Rationale |
|---|---|---|
| Orders, fills, positions, risk, incidents | PostgreSQL | Transactions, constraints, audit queries |
| Hypotheses, specs, experiments, candidates | PostgreSQL + immutable artifacts | Trial ledger and searchable metadata |
| Raw/canonical market data | Partitioned Parquet | Compact immutable analytics data |
| Feature matrices/backtest traces | Parquet | Efficient columnar replay |
| Manifests and reports | Content-addressed filesystem | Reproducibility and hash verification |
| Secrets | OS/VPS secret store later | Never database, prompt, repo, or logs |

PostgreSQL 18.4 is the current supported major/patch line observed during proposal preparation; PostgreSQL 19 is still a development/beta line. Exact dependencies will be rechecked and lock-pinned when scaffolding begins.

### 10.2 Key logical tables

- `data_sources`
- `dataset_manifests`
- `instrument_rule_snapshots`
- `feature_definitions`
- `hypotheses`
- `strategy_specs`
- `experiment_trials`
- `evaluation_slices`
- `candidate_manifests`
- `promotion_events`
- `signals`
- `order_intents`
- `risk_decisions`
- `broker_orders`
- `conditional_orders`
- `fills`
- `positions`
- `funding_entries`
- `equity_snapshots`
- `reconciliation_runs`
- `model_calls`
- `incidents`
- `runtime_state_transitions`

Critical uniqueness constraints include:

- one event ID;
- one order intent ID;
- one client-order ID per environment;
- one active position per symbol;
- one manifest hash per immutable candidate version;
- no duplicate fill by venue fill/trade ID.

### 10.3 Environment isolation

Use separate credentials, databases/schemas, event streams, and storage roots for:

- `research`;
- `paper`;
- `demo`;
- `live`.

A manifest promoted between environments is copied by hash; database rows and secrets are never shared casually across environments.

---

## 11. Proposed technology stack

Versions below were rechecked during the pre-development audit on 6 August 2026 and are **candidate pins for the first lockfile**. They are not permission to install or scaffold until the security and environment gates in Section 13 pass. Exact cross-package compatibility must be resolved by `uv lock`/the frontend lockfile and exercised in CI.

### 11.1 Backend and research

| Technology | Candidate version | Use |
|---|---:|---|
| Python | 3.14.7 | Latest stable feature release; managed by uv rather than the OS Python |
| uv | 0.12.2 | Environment and locked dependencies |
| FastAPI | 0.141.1 | Internal API and dashboard backend |
| Pydantic | 2.13.4 | Domain contracts and strict LLM output validation |
| Uvicorn | 0.52.1 | ASGI runtime |
| SQLAlchemy | 2.0.51 | Database mapping and transactions |
| Alembic | 1.19.0 | Versioned schema migrations |
| PostgreSQL | 18.4 | Event, candidate, order, and audit store |
| Polars | 1.43.2 | Feature and research data processing |
| PyArrow | 25.0.0 | Parquet interchange |
| HTTPX | 0.28.1 | Narrow async REST transport when required |
| Binance USDⓈ-M Futures SDK (`binance-sdk-derivatives-trading-usds-futures`) | 16.0.0 | Wrapped connector candidate, never domain API |
| structlog | 26.1.0 | Structured logs |
| pandas | 3.0.5 | Existing offline screener compatibility and tabular research utilities |
| NumPy | 2.4.6 | Existing offline screener numerical operations |
| psycopg | 3.3.4 | PostgreSQL 18 driver; binary/pool extras selected explicitly at lock time |

The connector decision will be finalized through a small integration spike:

- **Option A:** official SDK behind our typed adapter;
- **Option B:** narrow HTTPX/WebSocket transport implementing only used endpoints.

Preferred starting point is Option A, while domain contracts, idempotency, and reconciliation remain ours. If the SDK cannot model current Algo Service and stream semantics reliably, Option B replaces it without changing domain code.

### 11.2 Testing and quality

| Technology | Candidate version | Use |
|---|---:|---|
| pytest | 9.1.1 | Unit/integration/replay tests |
| Hypothesis | 6.165.2 | Property tests for rounding, sizing, causality, state machines |
| Ruff | 0.16.1 | Formatting and linting |
| mypy | 2.3.0 | Static typing |
| cryptography | 50.0.0 | Manifest signatures/encryption support where needed |

### 11.3 Dashboard

| Technology | Candidate version | Use |
|---|---:|---|
| Node.js | 24.19.0 LTS | Dashboard build/runtime toolchain; use LTS, not the current non-LTS line |
| npm | 12.0.2 | Frontend package manager; lockfile committed |
| React | 19.2.8 patched line | Read-only operational dashboard |
| TypeScript | 7.0.2 | Strict frontend contracts |
| Vite | 8.2.0 | Build tooling |
| Tailwind CSS | 4.3.3 | Styling |
| Magic UI registry | Components selected per page and locked in the frontend lockfile | Visual component source; local component code is reviewed and committed |

Magic UI is the selected dashboard component source. Its official installation flow uses the `shadcn` CLI only as a bootstrap/registry tool, then adds selected components through `@magicui/...` entries.[53] `shadcn/ui` is therefore not the dashboard's component kit; no shadcn/ui components will be scaffolded for this project. Every selected Magic UI component and its runtime dependency is reviewed, package-locked, and committed with the frontend.

The dashboard starts only after the domain/API vertical slice can expose real data. It will not use fake performance metrics. It follows an accessible dark, data-dense finance design: `PAPER` state, data freshness, halted/error state, and risk exposure appear above the fold. Magic UI motion is optional, supports `prefers-reduced-motion`, and is limited to non-safety-critical status transitions; particle, beam, glare, confetti, and similar decorative effects are prohibited from risk, execution, and incident views.

### 11.4 Deliberately excluded infrastructure

Version 1 does not need:

- Kafka;
- Redis/Celery;
- Kubernetes;
- a vector database;
- a feature store product;
- a separate service for every module.

PostgreSQL job tables, advisory locks, filesystem artifacts, and systemd timers/processes are sufficient initially. Kainode does not need Docker or Kubernetes for Version 1; PostgreSQL 18 can be installed as a directly managed host service after hardening, while frontend assets can be built separately and served without a Node production daemon.

---

## 12. Repository shape

```text
Autonomous Futures Bot/
├─ PROPOSAL.md
├─ research/                       # completed feasibility research artifacts
├─ pyproject.toml                  # created only after approval
├─ uv.lock
├─ src/autonomous_futures/
│  ├─ domain/                      # pure types, policies, state machines
│  ├─ data/                        # ingestion, quality, manifests
│  ├─ features/                    # causal feature catalog
│  ├─ strategy/                    # DSL schema/compiler/runtime
│  ├─ research_lab/                # LLM roles and experiment orchestration
│  ├─ validation/                  # backtest, walk-forward, stress, PBO/DSR
│  ├─ candidates/                  # registry and promotion policy
│  ├─ risk/                        # deterministic risk engine
│  ├─ execution/                   # intents, order manager, positions
│  ├─ brokers/                     # paper/demo/live interfaces
│  ├─ exchanges/                   # Binance adapter isolated here
│  ├─ reconciliation/              # exchange truth and recovery
│  ├─ persistence/                 # SQLAlchemy repositories, migrations
│  ├─ observability/               # metrics, structured logs, incidents
│  └─ api/                         # FastAPI routes; no domain logic
├─ frontend/                       # React dashboard after API vertical slice
├─ tests/
│  ├─ unit/
│  ├─ property/
│  ├─ integration/
│  ├─ replay/
│  ├─ walkforward/
│  ├─ adapter_contract/
│  └─ failure_drills/
├─ migrations/
├─ policies/                       # versioned immutable risk/promotion policies
├─ prompts/                        # versioned role prompts; no secrets
├─ artifacts/                      # local ignored artifacts by content hash
└─ deploy/                         # added only when paper runtime is ready
```

Dependency direction:

```text
api / workers / adapters
          |
          v
domain application services
          |
          v
pure domain types and policies
```

The domain layer never imports FastAPI, SQLAlchemy, Binance SDK, or an LLM client.

---

## 13. Test strategy

Development follows strict incremental TDD:

1. write a failing invariant test;
2. implement the smallest behaviour;
3. make it pass;
4. refactor without altering evidence;
5. run broader replay/property gates.

### 13.1 Essential test classes

#### Domain and property tests

- decimal price/quantity rounding never violates step size;
- risk after rounding never exceeds policy;
- infeasible minimum notional causes `REJECT`;
- duplicate intent cannot create a second order;
- a close cannot reverse the position accidentally;
- one position per pair/global limit survives restart;
- account drawdown state transitions are monotonic until guarded resume;
- reduce-only exits cannot increase exposure.

#### Causality tests

- a feature cannot see data after its availability timestamp;
- completed-bar signals execute no earlier than the next feasible event;
- funding is charged only when a position spans the funding timestamp;
- train/validation/test boundaries are frozen;
- parameter search cannot access final test data.

#### Execution/reconciliation tests

- send succeeds but response times out;
- stream fill arrives before REST response;
- duplicated/out-of-order stream event;
- partial fill followed by cancel;
- crash between send and acknowledgement;
- conditional order rejected or missing;
- restart with an existing external position;
- account balance changed outside the bot.

#### LLM boundary tests

- prose or malformed output rejected;
- unknown DSL feature rejected;
- look-ahead reference rejected;
- prompt-injection text treated as data;
- LLM asks to change risk limit and is rejected;
- LLM-generated code is not executed;
- model timeout does not block emergency exit.

### 13.2 Required CI gates

- unit/property tests;
- static type checks;
- Ruff formatting/lint;
- migration consistency;
- deterministic replay checksum;
- no-secret scan;
- dependency vulnerability scan;
- adapter contract tests against recorded fixtures;
- coverage of critical risk/execution branches;
- artifact/manifest reproducibility.

A high aggregate code-coverage percentage cannot replace explicit invariant tests.

---

## 14. Observability and operational control

### 14.1 Metrics

#### Data

- event lag;
- missing/duplicate bars;
- stream reconnect count;
- backfill count;
- filter snapshot age.

#### Research

- hypotheses and candidates per cycle;
- rejection rate by gate;
- parameter-trial count;
- OOS expectancy and drawdown;
- cost-stress survival;
- DSR/PBO where valid;
- model cost per accepted candidate.
- research queue depth, worker occupancy, oldest queued WorkUnit, and completed/rejected/failed WorkUnits by run;
- active DatasetManifest timestamp and 5m/15m freshness state;
- per-run CPU, memory, disk-I/O, and LLM-cost budget consumption.

#### Execution

- intent-to-send latency;
- fill latency and ratio;
- expected versus realized slippage;
- reject/timeout/unknown-status rate;
- reconciliation age and mismatch count;
- order/fill/position lifecycle completeness.

#### Risk

- equity and high-water mark;
- realized/unrealized P&L;
- current and daily risk used;
- effective leverage;
- liquidation buffer;
- drawdown state;
- concentration and funding burden.

#### LLM

- schema-valid output rate;
- policy-rejection rate;
- unsupported factual/numeric claim rate;
- prompt/model version;
- token and monetary cost;
- repeat-candidate rate.

### 14.2 Alerts

Immediate alerts:

- stale market/account data;
- unresolved unknown order state;
- position/order/balance mismatch;
- missing protective exit;
- risk-policy halt or emergency flat;
- repeated API throttling;
- failed backup/restore check;
- LLM budget breach;
- process crash loop.

### 14.3 Source of truth

Priority order:

1. exchange/broker-confirmed state;
2. reconciled append-only execution ledger;
3. deterministic domain projection;
4. dashboard/API cache;
5. LLM explanation.

LLM memory is never a source of order or position truth.

---

## 15. Deployment model

### 15.1 Local development

Initial work remains on the Windows workstation:

- `uv` environment;
- local unit/property/replay tests;
- PostgreSQL 18 in an isolated development container if needed;
- public data only;
- no exchange credentials;
- no background live trading service.

### 15.2 Paper runtime

After local gates:

- dedicated isolated Linux deployment;
- PostgreSQL 18 as a directly managed host service on Kainode (Docker Compose remains an optional local-development convenience);
- systemd controls long-running processes and timers;
- PostgreSQL backups and restore drills;
- TLS/reverse proxy for the dashboard;
- firewall allowlist;
- no Hermes cron dependency for always-on operations;
- paper environment remains unable to reach live order endpoints.

Proposed processes:

```text
market-data
research-worker
paper-runtime
reconciler
api-dashboard
postgres
backup-timer
health-watchdog
```

### 15.3 Demo and live isolation

Demo/live adapters are separate deployments or profiles with:

- different base URLs;
- different keys;
- separate databases;
- explicit environment banners;
- no shared queues;
- IP restrictions;
- withdrawals disabled;
- independent emergency controls.

There is no configuration flag that silently turns `paper` into `live` at runtime.

---

## 16. Delivery roadmap and hard exit gates

This roadmap uses capability gates rather than calendar promises.

### Phase 0 — Project constitution and domain contracts

**Build:**

- repository and dependency lock;
- architecture decision records;
- environment separation;
- Pydantic domain contracts;
- decimal/time conventions;
- risk and runtime state machines;
- initial failing invariant tests;
- CI quality gates.

**Exit gate:** Pure-domain tests demonstrate that invalid sizing, duplicate positions, unsafe state transitions, and malformed LLM output are rejected.

### Phase 1 — Immutable data foundation

**Build:**

- public Binance collector migration from research script;
- raw/canonical Parquet pipeline;
- dataset manifests and hashes;
- gap detection/backfill;
- instrument/filter snapshots;
- funding and mark-price alignment;
- data-quality dashboard/API.

**Exit gate:** A dataset can be rebuilt and produces an identical manifest; gaps and timestamp violations are surfaced.

### Phase 2 — Deterministic research and backtest kernel

**Build:**

- feature catalog;
- strategy DSL compiler;
- event-driven backtester;
- fee/slippage/funding model;
- walk-forward and stress runner;
- trial registry;
- candidate evidence bundle.

**Exit gate:** Existing research screens can be reproduced through the new kernel, and causality/cost invariants pass.

### Phase 3 — Autonomous LLM Research Lab

**Build:**

- provider-agnostic model adapter;
- hypothesis/spec/critic/failure roles;
- prompt and model audit;
- bounded, parallelizable research-batch scheduler;
- schema/policy rejection;
- trial-aware candidate registry;
- research dashboard.

**Exit gate:** The system autonomously generates candidates, rejects invalid/weak candidates, and produces a reproducible evidence bundle without executing model-generated code.

### Phase 4 — Paper execution kernel

**Build:**

- paper broker;
- signal runtime;
- risk engine;
- order/position manager;
- protective exits;
- reconciliation;
- runtime states and alerts;
- real-time paper dashboard.

**Exit gate:** Restart, partial fill, unknown status, stale data, missing stop, duplicate order, and drawdown drills pass. No authenticated Binance order access exists.

### Phase 5 — Autonomous paper maturation

**Operate:**

- bounded autonomous research cycles;
- automatic paper candidate promotion under policy;
- daily attribution and drift detection;
- automatic throttle/quarantine/retirement;
- 90-day-plus evidence cohort;
- operating-cost accounting.

**Exit gate:** At least one candidate satisfies all historical and paper gates—or the project honestly reports that no strategy qualifies. “No qualified alpha” is a valid result.

### Phase 6 — Demo/shadow integration

**Build after explicit approval:**

- Binance adapter spike;
- current normal and Algo Service order semantics;
- user-data stream and reconciliation;
- demo-only credentials;
- adapter contract tests;
- shadow decision comparison;
- operational incident drills.

**Exit gate:** Demo/shadow state remains reconciled through disconnects, unknown statuses, and restarts; paper and demo environments cannot be confused.

### Phase 7 — Live-readiness decision

**Requires:**

- venue/account/product confirmation for the deployment environment;
- qualified strategy evidence;
- explicit user authorization;
- live key with withdrawal disabled and IP allowlist;
- backup/restore and emergency drills;
- reviewed risk policy;
- USD 100 funding ceremony;
- final go/no-go checklist.

**Result:** Live can be enabled at the small fixed envelope, or remain blocked. Software completion does not force live activation.

---

## 17. Risk register

| Risk | Severity | Detection | Mitigation |
|---|---|---|---|
| Venue/account/product eligibility changes | Critical | Pre-live operator confirmation | Exchange abstraction; live adapter stays disabled until Phase 7 |
| No durable trading edge exists | Critical | OOS, paper, trial-aware evidence | Treat “no candidate” as valid; do not force deployment |
| Backtest overfitting | Critical | Trial ledger, DSR/PBO, walk-forward | Fixed budgets, untouched test, store failures |
| LLM hallucination/confabulation | Critical | Schema/policy/numeric checks | DSL only; deterministic computation and authority |
| Prompt injection | High | Adversarial tests, rejected instructions | Untrusted-data boundary; no exchange tools/secrets |
| Small-account cost drag | High | Economic P&L | Low turnover; skip infeasible orders; LLM off fast path |
| API semantic change | High | Change-log monitor, contract tests | Adapter isolation; pinned versions; Algo Service tests |
| Unknown order execution status | Critical | Reconciliation incident | Query/stream before retry; deterministic client IDs |
| Missing or duplicate position | Critical | Startup/periodic reconciliation | Uniqueness, exchange truth, halt on mismatch |
| Stale/corrupt market data | High | Data freshness and manifest checks | Fail closed; no forward fill across unknown gaps |
| Exchange outage/liquidation cascade | Critical | Health, mark/margin monitoring | Isolated/low leverage; exchange-side protection; halt |
| Secret leakage | Critical | Secret scan and audit | No secrets in LLM/log/repo; least privilege, IP allowlist |
| VPS/process/database failure | High | Watchdogs, backup tests | Restart-safe event ledger; restore drills; systemd |
| LLM/infrastructure cost exceeds gains | High | Economic P&L | Hard research quota; separate cost accounting |
| Model/provider behaviour changes | High | Versioned evaluation suite | Pin exact model; promotion tests before model change |
| Google AI Studio model unavailable or rate-limited | High | Startup model check, request telemetry, bounded retries | Stop that research cycle; do not silently substitute a model |

---

## 18. Acceptance criteria

### 18.1 Software-complete criteria

The system is software-complete when:

- autonomous research cycles run from immutable data to candidate decisions;
- all trials and failures remain auditable;
- StrategySpecs compile only through a constrained DSL;
- paper trading opens, manages, and closes positions without LLM availability;
- risk, order, position, and reconciliation invariants pass;
- incidents and costs are visible using real data;
- candidate promotion, throttle, quarantine, and retirement are machine-verifiable;
- every decision can be replayed from manifests and events;
- live capability remains physically/logically gated.

### 18.2 Strategy-qualified criteria

A strategy is qualified only after satisfying the Phase 5 evidence gates. The project may become software-complete with zero qualified strategies.

### 18.3 Live-authorized criteria

Live authorization is a separate governance outcome requiring legal/venue clearance and explicit user approval. It is not implied by passing unit tests, backtests, paper trading, or demo trading.

---

## 19. Proposed decisions for approval

Recommended defaults:

| Decision | Recommended answer |
|---|---|
| Begin implementation? | Only Phase 0 after proposal acceptance |
| First integration | Public data + internal paper broker |
| Exchange credentials during Phases 0–5 | None |
| LLM provider | Google AI Studio, with `gemma-4-26b-a4b-it` and `gemma-4-31b-it` selected explicitly per embedded research role |
| Initial symbols | BTCUSDT, ETHUSDT, SOLUSDT |
| Initial timeframe | 5m signal, 15m closed-bar regime context |
| Initial strategy families | Regime trend/breakout, then range mean reversion |
| Database | PostgreSQL 18 + Parquet artifacts |
| Architecture | Modular monolith |
| Dashboard | Read-only/operational; real data only |
| Initial deployment | Local Windows development; verified Kainode Linux VPS after security hardening and benchmark |
| Trading capital | Do not deposit until Phase 7 |
| Permanent project name | Decide later; working title only |

### 19.1 Deferred decisions

These do not block Phase 0:

- permanent brand/project name;
- approved live venue;
- all-in monthly LLM/infrastructure budget;
- whether any candidate is ever granted live authority.

---

## 20. Immediate next step after approval

The next deliverable should be **Phase 0 only**:

1. create the repository skeleton;
2. pin and verify actual versions;
3. define pure domain contracts;
4. write failing tests for money, filters, risk states, duplicate positions, and LLM boundary;
5. implement the minimum code required to pass those tests;
6. produce a Phase 0 verification report.

It should **not** include:

- Binance credentials;
- authenticated demo/live orders;
- VPS deployment;
- a profitability claim;
- a generated strategy promoted into trading.

---

## Sources

[13] https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition
[21] https://fapi.binance.com/fapi/v1/exchangeInfo
[24] https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/User-Commission-Rate
[33] https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf
[34] https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
[43] https://genai.owasp.org/llmrisk/llm01-prompt-injection
[46] https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf
[51] https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info — Binance USD-M Futures General Info
[52] https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/change-log — Binance USD-M Futures Change Log
[53] https://magicui.design/docs/installation — Magic UI installation
