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

## Consumer follow-up — published

- The first synthetic epoch-engine cycle regression exposed a receipt bug: the pipeline's separate unconfigured decider reported `completed_admitted` even when the actual epoch runtime rejected adoption. The cycle now uses the engine's configured decider and checks the actual adoption return value before changing its reported active candidate. Tests cover quarantine at initial admission and at the actual adoption seam; the latter receipt carries the runtime's blocked decision hash.
- The configured publication path now reuses the same epoch membership guard, validates the complete proposed manifest (including retained symbols) before replacing it, and rejects both a new legacy entry and retained legacy entries without changing prior manifest bytes. The existing cycle CLI forwards its engine decider. This does not introduce fresh-epoch CLI activation or new qualification authority.
- Eight-module consumer run initially reported **86 passed, one failed**: the existing 1.5-second daemon fixture processed 67 of 80 paced frames. Its unchanged isolated test passed; the unchanged full consumer rerun passed **87 tests in 96.71s**. No duration, count, production latency, risk or qualification threshold was relaxed. After adding the adoption-seam test-only variant, the complete three cycle/publication modules passed **9 tests in 1.76s**; static gates passed for the current tree. The earlier 4,923-test full run covers the published foundation only, not these follow-up edits.

### Trust limits and remaining integration

Final consumer publication regression: **88 passed in 109.27s** across all eight affected modules, including both adoption-seam variants. Focused read-only review confirmed no defects in receipt truth, configured membership propagation or all-entry-before-write publication. Published as `61ce51115f6b2424f45d7b324fc6dc023d5dba47`; exact-head Actions [36990207389](https://github.com/kipopopo/autonomous-futures-bot/actions/runs/36990207389) completed successfully with tests, lint, format, strict types and compilation. This remains offline fixture evidence, not production activation.

### Acceptance caller follow-up — published

The existing bounded cycle now has an explicit, default-off `reserve_creator_epoch` option requiring an already-configured paper engine. It reads the pinned journal/control and snapshots every accepted candidate ID before either injected transport or cycle outputs. Generator intake assigns epoch-scoped canonical identity before checking forbidden IDs; accepted candidate/outcome binding is reserved and control advanced atomically before external outcome/candidate files. Qualification and actual engine adoption use the existing unchanged gates. A synthetic positive cycle verifies durable membership before candidate persistence and makes no trade; repeated strategy is rejected against the journal snapshot. Missing control makes zero injected transport calls and leaves no cycle outputs; an injected failed control update rolls back reservation and leaves no candidate/outcome files. Downstream persistence failure does not erase or automatically retry a reserved acceptance.

RED: the new request epoch and explicit cycle option were rejected as absent. GREEN: eight-module affected regression **92 passed in 102.79s**; whole-tree lint/format and Windows/Linux strict types passed. Focused read-only review returned no confirmed defects; final two-module regression passed **13 tests in 2.03s**. No CLI/API/scheduler configuration, provider credential-resolution path or protected production provisioning was activated by this integration.

Acceptance caller published as `5c1581e8c04e7eccf6a24772488e25404ec47171`; exact-head Actions [37015447424](https://github.com/kipopopo/autonomous-futures-bot/actions/runs/37015447424) completed successfully (tests, lint, format, strict types and compile). It does not cover the CLI follow-up below.

### Offline CLI follow-up — published

The existing cycle CLI now accepts `--creator-epoch-journal`, `--creator-epoch-control` and `--creator-epoch-checkpoint` (typed JSON). All three are required together, with demo provider and explicit paper ledger. Existing state is verified before feedback, output directories, runtime initialization or credential lookup. The exact pins are forwarded to the engine; the cycle uses explicit reservation and existing all-entry publication checks. The CLI does not initialize stores, infer owner identity, discover a trust head or unlock real providers. Production pins must still be supplied by separately reviewed protected operator configuration.

Actual subprocess RED rejected the absent flags; GREEN **six subprocess cases passed in 71.72s**, including fresh reservation, absent control, partial pins and unchanged legacy cache-fault cases. Five injected preflight tests assert zero credential/client/transport resolution and no output/runtime-store writes for non-demo provider, invalid checkpoint/policy, absent journal or missing ledger configuration. The first broad foreground command timed out without a verdict; the bounded rerun passed **42 tests in 231.74s**. Whole-tree Ruff/format, Windows/Linux strict types, lock and diff checks passed. Focused read-only review returned no findings. Synthetic cached data, ledger and epoch fixtures are not market, provider or production readiness evidence.

These are local contracts, not initialized production authority. The control path and policy must be pinned by trusted operator configuration and separately protected from journal writers. Hashes, local file permissions and this document do not establish owner identity or defeat privileged replacement/rollback of **both** journal and control. Failed initialization leaves an unusable file rather than silently resetting history; repair requires an explicit reviewed recovery action.

CLI slice `87a132a9a890c80d8a7204e101e80f9851c78c26` passed exact-head Actions `37020877519` (tests, lint, format, strict types and compile).

### Offline scheduler follow-up — published

Scheduler demo cycle mode now accepts the same three operator pins; unsupported offline-base research mode, real provider, missing explicit ledger and incomplete/invalid state fail before output initialization. CLI and scheduler reuse the typed configuration reader. Each launch rereads state and rejects changed checkpoint pins; exact resolved pins and ledger are passed to the existing cycle child.

Actual scheduler process → actual cycle subprocess → accepted epoch journal/control membership passed using the existing cached/ledger fixture. The test verifies one cycle, stopped health and released lock, unchanged market fixture bytes, disabled execution and exact persisted candidate membership. It does not prove live market qualification or operational protection.

Read-only review identified that scheduler-created cycle directories/feedback snapshots survived a child preflight rejection. A late control-deletion regression reproduced this (RED). In epoch mode the scheduler now leaves per-cycle output creation and ledger feedback extraction to the child after its own preflight; it passes the ledger once and does not write a feedback snapshot (GREEN). Scheduler failure health remains diagnostic evidence. Failures *after* successful child preflight may retain research evidence and an accepted reservation; those must not be erased or automatically retried. No cross-process guarantee against arbitrary later mutation is claimed.

Final six-module regression after the fix: **99 passed in 182.11s**. The preceding **98-test** run predates the late-control fix and is not its verification. Whole-tree Ruff/format, Windows/Linux strict types, lock/diff checks passed. Published `427d7e73cc8e12abf06c6fc7b58943cbc0754dfe` passed exact-head Actions [37024189877](https://github.com/kipopopo/autonomous-futures-bot/actions/runs/37024189877), quality job `110894530880` in **16m7s**: tests, lint, format, strict types and compile succeeded. No full-suite count is inferred from its abbreviated watch output.

### Read-only Creator API follow-up — local verification

The existing registry, qualification-list and qualification-detail readers accept the same configured admission decider. Each returned registry artifact is membership-checked before it can be labelled verified; qualification readers use that shared loader rather than a separate preflight snapshot. `create_app` accepts all three existing pins explicitly or through `AFBOT_CREATOR_EPOCH_JOURNAL`, `AFBOT_CREATOR_EPOCH_CONTROL` and `AFBOT_CREATOR_EPOCH_CHECKPOINT`. Partial or invalid configuration fails at startup; no genesis or trust head is inferred. Every GET rereads protected control through the existing decider. This applies to these Creator evidence endpoints, not to a new provider API or all historical Learner/canary views.

RED reproduced absent configuration support and ignored partial operator environment. GREEN: **53 affected tests passed in 5.99s**; whole-tree lint/format, Windows/Linux strict types, lock/diff checks and in-memory compilation of **708 Python files** passed. A loopback TCP Uvicorn probe reused the same fixture assertions: configured accepted candidates returned **200**, legacy/unaccepted candidates and deleted control/journal returned **503**, POST returned **405**, and every source/evidence byte remained unchanged. Both explicit pins and operator-environment configuration were exercised; temporary servers were stopped. Frozen full locked suite: **4,955 passed, two warnings in 994.19s**, with JUnit independently confirming 4,955 tests and zero failures/errors/skips. Subsequent whole-tree lint/format, Windows/Linux strict types and lock/diff gates all passed. These are synthetic fixtures, not real OOS or operational-protection evidence; exact-published-SHA CI remains required.

The bounded offline acceptance caller, configured admission/publication guards, demo cycle/scheduler and read-only Creator API configuration are implemented. Real-provider fresh-epoch preflight and protected deployment control-store provisioning remain unfinished. Default legacy provider history remains blocked before credentials or transport; generic continuation does not authorize unlocking it. No real epoch, provider request, deployment, restart or order has been activated. This decision record is not an acceptance ledger, epoch manifest or executable bypass. Full project readiness remains unavailable; provider, deployment and trading approvals stay separate.
