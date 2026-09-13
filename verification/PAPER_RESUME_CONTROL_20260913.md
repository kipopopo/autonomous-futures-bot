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

The new control code was deployed as a **minimal code-only overlay** after
separate operator approval for `atomic code-only install; no restart/resume/order`.
Only these five paths were installed; unrelated target drift was preserved:

```text
src/autonomous_futures/paper/resume_control.py
src/autonomous_futures/paper/__init__.py
scripts/prepare_paper_resume.py
tests/unit/test_paper_resume_control.py
tests/unit/test_prepare_paper_resume_cli.py
```

The full code-only archive used for isolated staging contained 492 files,
5,046,940 bytes, and manifest `0c3baef5791acbb1b46448e5c7f2cd2e4cfea92898851ca86dc956e58362d4d2`.
The staged archive and remote staging tree matched exactly. A compatibility
stage built from the pre-existing target source plus this five-file overlay
passed 14 focused tests, targeted Ruff/format, targeted mypy, and compile.
The installed target overlay then passed the same 14 tests, targeted Ruff,
format, targeted mypy, in-memory compilation, and CLI help.

The subsequent apply-boundary update was delivered from source commit
`ecaea534f69a9d92ed127617670467333b0aa9e5` as a minimal overlay of the
resume-control module, circuit-breaker bridge, package exports, and focused
regression test. A compatibility stage made from the target source plus this
overlay passed 24 relevant tests, targeted Ruff/format/mypy, and compile. The
target after installation passed 22 focused tests, targeted Ruff/format/mypy,
in-memory compilation, and CLI help. Data-dependent Phase-255 artifacts were
intentionally not transferred and were not used as remote acceptance evidence.

The remote full-tree mypy check exposed four pre-existing platform-specific
errors in unrelated Windows-only/OS-specific files; those were not changed in
this slice. Local full-tree CI remained green. The VPS has Python 3.14.7 and
the existing project venv, but no `uv` executable on PATH; no dependency
resolution or package installation was performed.

Rollback copies of the prior paper package export and online `Connection.backup()`
copies of the three paper SQLite databases were created with `integrity_check=ok`
and retained. No database file was replaced.

The running paper process was not reloaded. No daemon reload, restart, sidecar
write, resume command, force-close, order, candidate admission, or breaker
mutation was performed. Operator application remains a separate action.

## Resulting state

```text
control implementation:          verified and code-only deployed
request preparation:              available on disk; not invoked
request application:              implemented and verified; not invoked
paper service:                    active process; breaker HALTED
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

The implementation, tests, and initial report were staged together in
`383af694e2fbd3c5619008b83fd6d0e7dc9650c2`. Its first GitHub quality run
completed the test step but failed Ruff on an import-order error in the public
paper exports. The one-line ordering fix was delivered separately in
`820367d2ed90d94a3e9c4592f48101d233a91eb3`; no runtime behavior changed.

Final post-fix delivery evidence:

```text
fresh post-commit full locked pytest:  2,234 passed in 812.93s
affected resume/runtime pytest:        128 passed in 45.36s
target compatibility smoke:           24 passed in 2.38s
target post-install smoke:             22 passed in 2.05s
Ruff check/format:                     passed
mypy:                                  passed
uv lock --check:                       passed
py_compile:                            passed
git diff/show --check:                 passed
GitHub quality run 34750614324:        success (deployment report commit)
GitHub quality run 34754262891:        success (apply source commit)
source code deployed:                  ecaea534f69a9d92ed127617670467333b0aa9e5
worktree:                              clean
remote paper state:                    HALTED, unchanged
```

The final GitHub workflow passed tests, Ruff lint, Ruff formatting, strict
mypy, and Python compilation. The apply-boundary overlay was installed without
restarting the service; no prepared request or apply call was invoked.

Recommended runtime for the next bounded phase: `gpt-5.6-luna-900k` via
`openai-codex`, Medium effort.
