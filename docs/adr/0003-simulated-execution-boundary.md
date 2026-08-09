# ADR-0003: Fail-closed simulated paper and shadow execution

- **Status:** Accepted
- **Date:** 2026-08-09
- **Decision owners:** Project operator and deterministic runtime authority

## Context

Research evaluation must never acquire order authority just because its artifacts are
available to a runtime. Paper and shadow work need simulated fills and audit events,
but must not inherit venue credentials, authenticated endpoints, or a live order
client. A mode flag without isolated namespaces and runtime assertions is inadequate.

## Decision

`autonomous_futures.execution.boundary` is the sole current order submission surface.
It implements only `paper` and `shadow` modes, and each starts with a unique runtime
identifier plus storage, database, and event-stream namespace. It accepts a
venue-neutral `OrderIntent` only when the intent's declared source environment exactly
matches the simulator's environment. A research-sourced intent therefore fails closed.

Permitted side effects are restricted to an in-memory simulated event record. Every
record contains the runtime environment, source environment, runtime identifier,
authority (`SIMULATED`), intent identifier, symbol, action, status, and simulated fill
price. No network client, venue adapter, endpoint, credentials, or live order path is
imported or constructed.

Configuration validation and startup assertions enforce these rules:

- paper/shadow require `execution_authority=SIMULATED`;
- paper/shadow reject `venue_endpoint` and `venue_credentials`;
- research requires `execution_authority=NONE` and rejects both venue fields;
- research cannot start an order runtime;
- demo and live cannot start this runtime. They require a future separately reviewed
  promotion and routing boundary; no default live authority is granted.

## Consequences

- Paper and shadow orders are auditable simulated events and cannot reach a venue from
  this module.
- Research artifacts have no implicit execution route.
- Environment identity is visible in every simulated record and isolated state root.
- Introducing demo/testnet or live execution requires a new explicit architecture
  decision, credentials review, deterministic gates, and human approval.

## Verification

`tests/unit/test_execution_boundary.py` proves independent paper/shadow namespaces,
simulated-only routing, mandatory environment-tagged records, rejected endpoint and
credential configuration, rejection of live authority, rejection of research-sourced
intents, and refusal to start research/live order runtimes.
