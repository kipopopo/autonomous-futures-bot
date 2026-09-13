# Paper Recovery Read-Only Preflight — 2026-09-13

## Decision

Paper recovery is **BLOCKED**. This preflight performed read-only inspection
only. The paper daemon is running with a fresh heartbeat and no active position,
but both the breaker sidecar and daemon health report `HALTED`. No complete
operator-approved `ResumeEvidence` artifact exists.

No restart, resume request, force-close, force trade, breaker bypass, candidate
mutation, testnet action, live action, or order was performed.

## Inspection boundary

The inspection used the project's health diagnostics against the existing paper
storage, plus direct status-field readback. SQLite inspection is read-only and
uses the project's `mode=ro`, `PRAGMA query_only=ON`, and `busy_timeout=1000`
contract. No production file was written.

The inspected production candidate registry is:

```text
candidate registry hash: 4664eb4bd449145f0391291202d65a1fc13d9f35dae99a1da57f0c035bfd358b
admitted candidate IDs:  0
VWAP candidate present:  false
```

## Health diagnostic result

```text
health status:           CRITICAL
health CLI exit code:    2
checks passed:           21
warnings:                0
failures:                1
```

The single failure is the explicit safety blocker:

```text
paper circuit breaker:   HALTED
```

Other read-only component facts:

| Component | Observed state |
|---|---|
| Paper daemon | `RUNNING` |
| Paper daemon heartbeat | Fresh at `2026-09-13T05:59:47.431367+00:00` |
| Active positions reported by daemon | `0` |
| Scheduler | `IDLE` |
| Scheduler consecutive failures | `0` |
| Scheduler heartbeat | Fresh at `2026-09-13T05:59:58.452697+00:00` |
| Breaker sidecar | `HALTED` |
| Daemon health breaker state | `HALTED` |
| SQLite ledger integrity | `ok` |
| Ledger opens / closes | `166 / 166` |
| Dirty recovery intents | `0` |
| Unmatched open events | `0` |
| Persisted active positions | `0` |
| SQLite lifecycle integrity | `ok` |
| Research-related timers | `0` |

The health CLI's `CRITICAL` result is not converted to `HEALTHY` merely because
processes and databases are otherwise available.

## ResumeEvidence gate

The runtime model requires every field below to be true before an upward state
transition:

```text
reconciled:          not established as a complete resume artifact
incident_resolved:   not established as a complete resume artifact
data_fresh:          not established as a complete resume artifact
risk_healthy:       not established as a complete resume artifact
operator_approved:  absent
```

The code explicitly rejects automatic resume and requires operator approval
plus complete evidence. A path scan found no resume-evidence artifact under the
paper or research roots. Therefore a resume request would be unsafe and was not
attempted.

## Readiness gates

| Gate | Result | Reason |
|---|---|---|
| Paper process reachable/running | PASS | Daemon is `RUNNING`; heartbeat is fresh |
| Scheduler reachable/running | PASS | Scheduler is `IDLE`; heartbeat is fresh; zero consecutive failures |
| Ledger integrity | PASS | SQLite integrity `ok` |
| Ledger/open-position parity | PASS | `166` opens, `166` closes, zero unmatched opens |
| Dirty recovery intents | PASS | `0` |
| Active position flatness | PASS | Daemon and persisted state report `0` |
| Candidate registry | PASS for containment | Valid empty registry; zero admitted IDs |
| Breaker state | **BLOCKED** | Sidecar and health are `HALTED` |
| Complete ResumeEvidence | **BLOCKED** | No complete evidence artifact and no operator approval |
| Paper resume | **NOT RUN** | Explicitly withheld at the fail-closed boundary |
| Testnet/live | **BLOCKED** | No qualified candidate, approval, or live authority |

A flat ledger and fresh heartbeat do not by themselves prove incident
resolution, risk health, or authorization to resume.

## Resulting state

```text
recovery decision:             BLOCKED
resume request:                none
service restart:               none
force-close/trade:             none
candidate admission:           none
paper activation change:       none
execution authority:           false
testnet/live activation:       false
orders submitted by preflight: 0
```

## Next legitimate boundary

Recovery cannot proceed from this read-only result alone. The next action,
if separately authorized, must be a human-owned recovery review that produces a
fresh, hash-bound, operator-approved `ResumeEvidence` record after:

1. current ledger/position reconciliation is reviewed;
2. the incident is explicitly resolved;
3. current market-data freshness and risk health are evidenced; and
4. the operator approves the exact resume scope.

Only then may the existing runtime's explicit resume path be considered. This
report does not request or grant that approval. Do not restart the service or
reset the breaker to make the gate appear green.

## Repository delivery

This is a documentation-only readback. No production Python, paper ledger,
candidate registry, scheduler, or service configuration was changed.

Recommended runtime for any next bounded phase: `gpt-5.6-luna-900k` via
`openai-codex`, Medium effort.
