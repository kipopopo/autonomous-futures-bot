# Paper Resume Control Preparation — 2026-09-13

## Decision

A dedicated **fail-closed paper-resume preparation control** is implemented and
verified. It can capture current paper state read-only, validate explicit
operator `ResumeEvidence`, and persist an expiring immutable request with
status `ready_for_operator_apply`.

The control deliberately does **not** apply the request. It does not change the
breaker sidecar, restart a service, call `request_resume()`, submit an order,
activate testnet/live, or grant execution authority. The current remote paper
runtime remains `HALTED` until a separately verified operator-apply boundary
exists and is explicitly used.

## Scope and safety boundary

Implemented files:

```text
src/autonomous_futures/paper/resume_control.py
scripts/prepare_paper_resume.py
src/autonomous_futures/paper/__init__.py
tests/unit/test_paper_resume_control.py
tests/unit/test_prepare_paper_resume_cli.py
```

The slice includes:

```text
read-only paper storage capture
→ explicit ResumeEvidence validation
→ current HALTED/preflight binding
→ expiring paper-only request
→ canonical hash
→ immutable atomic write/readback
```

Explicitly out of scope:

```text
sidecar mutation
service restart
runtime request_resume() invocation
scheduler mutation
candidate admission/promotion
provider or exchange access
credentials
testnet/live activation
orders
```

## Contract

`PaperRecoveryPreflight` captures the current read-only state and requires:

```text
breaker sidecar and daemon health: HALTED
paper daemon:                   RUNNING
paper/scheduler heartbeats:     fresh
scheduler:                      IDLE
ledger integrity:               ok
ledger opens == closes
zero dirty intents
zero unmatched opens
zero persisted/active positions
zero candidate-registry entries
zero submitted orders
execution_authority=false
live_trading_activation=false
zero_private_credentials=true
```

The storage capture reads health, breaker sidecar, scheduler health, the typed
candidate registry, and the SQLite ledger. SQLite is opened with:

```text
mode=ro
PRAGMA query_only = ON
PRAGMA busy_timeout = 1000
```

It checks SQLite integrity and the open/close, dirty-intent, unmatched-open,
and persisted-position counts without creating a missing path.

`PaperResumeRequest` requires:

```text
status:              ready_for_operator_apply
control_scope:       paper_only
request lifetime:    <= 15 minutes
preflight freshness: <= 2 minutes at request creation
promotion_state:     unpromoted
paper_activation:    false
execution_authority: false
testnet_activation:  false
live_activation:     false
```

All five `ResumeEvidence` fields must be true. The request hash covers the
complete request, including expiry and the captured preflight; only the
self-hash field is excluded from canonical hashing.

Persistence is write-once and fail-closed: caller hash is verified before
filesystem work, a unique same-directory temporary file is fsynced, exclusive
hard-link publication prevents replacement, and the created file is read back
through the typed verifier. Identical writes are idempotent; changed requests,
malformed JSON, and tampered hashes fail closed.

The CLI requires explicit evidence, request identity, creation/expiry timestamps,
and either live storage capture or an explicit offline preflight fixture:

```text
PYTHONPATH=src uv run --locked python scripts/prepare_paper_resume.py --help
```

There is intentionally no `--apply`, `--restart`, `--resume`, or order option.

## TDD evidence

Initial RED result for the core module:

```text
ModuleNotFoundError: autonomous_futures.paper.resume_control
exit code: 2
```

Initial CLI RED result after correcting the test's repository import path:

```text
ModuleNotFoundError: scripts.prepare_paper_resume
exit code: 2
```

The stale-preflight regression then failed before implementation because a
three-minute-old snapshot was accepted. After the freshness guard, it passed.
The storage-capture RED also failed at the missing exported function boundary.

Final focused result:

```text
core resume-control + CLI tests: 14 passed in 1.06s
related paper/daemon/risk/registry tests: 72 passed in 15.85s
```

Coverage includes:

```text
valid non-authoritative request round-trip
explicit paper-only safety flags
missing/false ResumeEvidence rejection
semantic model_copy tampering rejection
stale/future preflight rejection
current HALTED state and zero-position requirements
read-only health/sidecar/scheduler/registry/SQLite capture
SQLite byte preservation
missing storage fail-closed behavior
malformed/missing/tampered request rejection
immutable conflicting request rejection
caller hash mismatch before directory creation
CLI valid preparation
CLI invalid evidence blocked without output
CLI storage capture mode
```

The direct script invocation without `PYTHONPATH` correctly failed at the
non-package `src` import boundary. The documented explicit invocation with
`PYTHONPATH=src` passed the real CLI help smoke.

## Static and full verification

```text
Ruff check:                         passed
Ruff format --check:                passed
mypy src scripts/prepare_paper_resume.py: passed
uv lock --check:                    passed
py_compile changed files:           passed
git diff --check:                    passed
full locked pytest:                 2,226 passed in 972.34s
```

The full suite was run once from the repository root with ambient Python path
variables unset. No full-suite result was inferred from the focused tests.

## Pre-implementation remote readback

Before implementation, the existing remote paper state was inspected through
the project health CLI and direct status reads:

```text
health status:                    CRITICAL
checks:                           21 passed / 1 failure / 0 warnings
sole failure:                     circuit breaker HALTED
paper daemon:                     RUNNING
paper heartbeat:                  fresh
active positions:                 0
scheduler:                        IDLE
scheduler consecutive failures:  0
ledger integrity:                 ok
ledger opens / closes:            166 / 166
dirty intents:                    0
unmatched opens:                  0
persisted positions:              0
candidate registry:               0 admitted IDs
resume-evidence files:            none found
```

The five non-secret operator confirmations were received through the UI:
reconciled, incident resolved, data fresh, risk healthy, and explicit approval
to resume. No request artifact was created from those confirmations during this
implementation phase, and no runtime apply was attempted.

## Deployment boundary

The new control code is **not deployed to the remote runtime** in this phase.
The running paper service remains on its existing source and remains `HALTED`.
No deployment, daemon reload, restart, sidecar write, or resume command was
performed. This is intentional: implementation and validation of a safe control
surface are complete, while operator application remains a separate action.

## Resulting state

```text
control implementation:          verified
request preparation:              available
request application:              not implemented/invoked
paper service:                    HALTED
execution authority:              false
testnet/live activation:          false
orders from this phase:           0
candidate mutation:               none
ledger mutation:                  none
scheduler mutation:               none
```

A prepared request is evidence for a future operator-apply boundary, not proof
that paper is healthy, that a candidate is qualified, or that any trading action
is authorized.

## Delivery

Base repository before this slice:

```text
HEAD = origin/main = a57718f8e83d02d10abbad1751c08aede8699fb7
```

The implementation, tests, and this report must be staged together. After the
commit, a fresh post-commit suite, GitHub quality workflow, exact SHA readback,
and remote safety readback are required before this phase is considered
complete.

Recommended runtime for the next bounded phase: `gpt-5.6-luna-900k` via
`openai-codex`, Medium effort.
