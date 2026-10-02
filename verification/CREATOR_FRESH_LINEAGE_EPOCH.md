# Fresh Creator lineage epoch — authority-policy decision

## Owner decision and scope

The owner confirmed that the complete authoritative historical acceptance record does not exist: **“rekod itu tidak wujud”**. Following the proposal to preserve/quarantine old history, exclude legacy artifacts from promotion and record every new acceptance immutably, the owner authorized the method: **“Okay, ikut cara awak. proceed sampai siap sepenuhnya.”**

This authorizes offline design and implementation of a new lineage boundary. It does not attest old history, adjudicate any collision, authorize a provider request, deploy code, restart a service, activate testnet/live or authorize an order. The legacy complete-history gate remains blocked. No epoch initialization or runtime activation is claimed by this document.

## Isolation contract

- Preserve all historical candidate, proposal, registry, trial and qualification bytes. Do not choose collision winners, rename old artifacts, backfill acceptance events or relabel old evidence into the new epoch.
- The fresh epoch has a separately bound owner policy and genesis. Its completeness claim covers only new events recorded from that genesis, never missing historical events.
- Scope candidate identity and immutable acceptance to the epoch; canonical strategy equivalence alone does not confer epoch membership.
- A new candidate must bind its exact candidate/artifact/epoch identities to a durable acceptance event. A filename, metadata marker, valid hash, empty directory or caller-selected history subset is insufficient.
- Reserve each acceptance before candidate persistence. Failed downstream persistence cannot erase the reservation or justify reusing its identity. Duplicate/conflicting acceptance and incomplete durable state fail closed.
- Verify the authoritative epoch record and acceptance set before a new request. Snapshot deletion, subset selection, replay and tampering must not silently reset the epoch or create apparent completeness.
- In fresh-epoch mode, qualification, publication, direct admission, startup discovery and hot reload must all reject legacy or foreign-epoch candidate bindings. Protective handling of already-open trades remains trade-owned; quarantine must not force-close positions or mutate the historical runtime.
- Source-bound OOS qualification and existing risk/admission rules still apply. Epoch membership is not qualification, paper activation, promotion, execution or exchange authority.

## Required implementation evidence

1. Real local acceptance/persistence/readback with exact epoch/candidate/artifact/outcome binding; immutable duplicate/replay rejection.
2. Foreign/legacy candidate rejection at shared admission/publication/startup/reload boundaries, even with internally valid qualification hashes.
3. Missing/deleted/tampered or substituted epoch state blocks before provider transport, credential resolution and partial outputs.
4. Existing offline cycle and scheduler integration retain typed feedback, deterministic checkpoint behavior and disabled exchange/live authority.
5. Relevant canonical regressions, repository static gates and exact-published-SHA full CI. A synthetic fixture proves the contract only, not real provider output, real-market eligibility or deployment.

## Verified offline implementation boundary

- Canonical candidate identity includes the epoch in the digest while preserving omitted-epoch legacy identity and existing ID lengths.
- `research/creator_epoch.py` replays exact accepted proposal/candidate/outcome bindings, contiguous sequence, predecessors, unique proposal/candidate IDs and the expected final checkpoint. An old checkpoint does **not** accept a longer journal. Rejected trials remain outside this acceptance-only journal.
- A separate operator-pinned SQLite control store binds the exact journal path, epoch and policy. It initializes only at empty authorized genesis; missing control is not reconstructed from journal rows. Atomic reservation with `control_path` advances journal and control in one SQLite attached-database rollback-journal transaction. WAL is rejected; an injected control-write failure rolls back both stores.
- Configured epoch admission/runtime requires journal, pinned epoch/checkpoint and control store before runtime output initialization. Startup manifest loading, direct admission, entry execution and hot reload reuse the same engine decider. Every entry rereads control and verifies membership; failed reload preserves prior state, but an invalid journal/control cannot authorize a new entry. Protective close remains unchanged.
- Outcome write-once persistence uses a unique same-directory temporary file, flushed before hard-link publication. A synchronized conflicting-writer regression demonstrated the former shared-temp payload race and verifies only one matching writer can succeed.
- Focused regression: **58 passed in 12.26s** across proposal, paper-admission, unit hot-reload and integration hot-reload modules. Whole-tree Ruff check/format and lock/diff checks passed. Windows/Linux mypy passed for 356 source files before the final test-only additions.
- Frozen full locked suite: **4,923 passed**, zero failures/errors/skips, two warnings, **1,026.48s**. JUnit independently confirms 4,923 tests and zero failures/errors/skips. Final Windows/Linux mypy passed for 356 source files; lint/format and in-memory compilation of 703 Python files passed. Windows bytecode-writing `compileall` encountered pre-existing long-path failures; the in-memory compiler check does not claim that command succeeded.

- Published foundation `071a4c52bc7346a233bc38c1e9ab37487faeae72` passed exact-head Actions [36987105437](https://github.com/kipopopo/autonomous-futures-bot/actions/runs/36987105437): **4,922 passed, one skipped, two warnings in 703.33s**, plus lint, format, strict types and compilation. Metadata was re-read as completed/success; that CI does not cover the uncommitted consumer follow-up below.

## Consumer follow-up — publication pending

- The first synthetic epoch-engine cycle regression exposed a receipt bug: the pipeline's separate unconfigured decider reported `completed_admitted` even when the actual epoch runtime rejected adoption. The cycle now uses the engine's configured decider and checks the actual adoption return value before changing its reported active candidate. Tests cover quarantine at initial admission and at the actual adoption seam; the latter receipt carries the runtime's blocked decision hash.
- The configured publication path now reuses the same epoch membership guard, validates the complete proposed manifest (including retained symbols) before replacing it, and rejects both a new legacy entry and retained legacy entries without changing prior manifest bytes. The existing cycle CLI forwards its engine decider. This does not introduce fresh-epoch CLI activation or new qualification authority.
- Eight-module consumer run initially reported **86 passed, one failed**: the existing 1.5-second daemon fixture processed 67 of 80 paced frames. Its unchanged isolated test passed; the unchanged full consumer rerun passed **87 tests in 96.71s**. No duration, count, production latency, risk or qualification threshold was relaxed. After adding the adoption-seam test-only variant, the complete three cycle/publication modules passed **9 tests in 1.76s**; static gates passed for the current tree. The earlier 4,923-test full run covers the published foundation only, not these follow-up edits.

### Trust limits and remaining integration

Final consumer publication regression: **88 passed in 109.27s** across all eight affected modules, including both adoption-seam variants. Focused read-only review confirmed no defects in receipt truth, configured membership propagation or all-entry-before-write publication. This is offline fixture evidence; exact-head consumer CI remains required after publication.

These are local contracts, not initialized production authority. The control path and policy must be pinned by trusted operator configuration and separately protected from journal writers. Hashes, local file permissions and this document do not establish owner identity or defeat privileged replacement/rollback of **both** journal and control. Failed initialization leaves an unusable file rather than silently resetting history; repair requires an explicit reviewed recovery action.

The research provider preflight/acceptance caller, qualification/publication resolvers, API/CLI/scheduler configuration and protected deployment control-store provisioning are not yet wired to this new mode. Default legacy provider history remains blocked. No real epoch, provider request, deployment, restart or order has been activated. This decision record is not an acceptance ledger, epoch manifest or executable bypass. Full project readiness and exact-published-SHA CI remain pending; provider, deployment and trading approvals stay separate.
