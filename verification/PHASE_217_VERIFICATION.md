# Phase 217 Verification — provider probe and bounded Creator campaign 039

## Status

**BLOCKED / EVIDENCE-ONLY**

This phase ran one fresh tiny authenticated provider probe after Phase 216 and,
because that probe returned `2xx`, one separately bounded cached Creator
campaign. The tiny probe succeeded, but the full Creator request again stopped at
the provider transport boundary before an HTTP response. The typed campaign trial
was persisted as rejected. No candidate, OOS aggregation, qualification,
promotion, paper activation, or execution artifact was created.

- Verification time: `2026-09-01T09:21:36Z`
- Source commit: `ac39435fe641820ccf229203dfc60efd3331e019`
- Provider: `opencode`
- Pinned model: `deepseek-v4-flash`
- SSH operator: `afbot-admin`
- Host: `147.79.18.15`
- Pinned ED25519 fingerprint: `SHA256:2EHNUWXLj2BPt/163uW942G+grhLoDVxhmtyrw7vdjQ`

## Fresh completion probe 038

The probe used the retained credential only through the encrypted systemd
credential mapping, an explicit 90-second HTTP cap, the pinned model, JSON
response mode, `temperature=0.0`, and `max_tokens=16`. It issued exactly one
HTTP request and retained no response body:

```text
provider=opencode
model=deepseek-v4-flash
provider_requests=1
provider_http_attempts=1
completion_status=200
completion_json=valid
choice_count=1
content_kind=str
completion_elapsed_seconds=1.869046
response_body_retained=false
probe_unit_exit=0
probe_unit_after_cleanup=not-found
probe_script_absent=true
research_timer_matches=0
research_active_matches=0
```

This cleared the preflight decision for at most one bounded cached campaign. It
did not qualify a candidate or prove that the larger Creator prompt is stable.
No raw prompt, response body, authorization header, or credential value was
printed or persisted.

## Campaign source and immutable scope

The verified runner was reused with only the campaign scope and run identifiers
changed from the prior runner. No production source logic was changed.

```text
runner_039_import=PASS
forbidden_candidate_ids=51
source_archive_entries=198
source_archive_hash=c066782b30c08c0cf202c7eb7b02a0bdfb3da544095d852f12949cd88679f210
runner_hash=387643c4fd8d223f29df7376747cc4857c6109b7a41261b083ec9071fbfc8a45
remote_compile=PASS
```

The runner verified the immutable DatasetBundle, DatasetRegistry, manifest
bindings, source-file hashes, and cached frame before the provider call:

```text
campaign_root=/var/lib/autonomous-futures/research/dogeusdt-365d/creator-batch-20260901-039
research_run_id=run-doge-experimental-039
creator_run_id=doge-creator-experimental-039
bundle_hash=30a365020f816f090d2ed66163dbda5f3a2a4490e1b283c6385b4b07cf27ccc3
dataset_registry_hash=17f140c77f1911f26dd63bd0d20144149dab7cd424a3760f4b7797d10b61375e
cached_symbol=DOGEUSDT
cached_rows=105120
cached_data_source=cached_only
configured_oos_windows=4
```

No exchange endpoint or exchange credential was loaded.

## Campaign result

The campaign used exactly one provider invocation, the pinned model, a finite
`max_output_tokens=2048` cap, and no fallback or outer retry loop:

```text
campaign_unit_exit=0
campaign_unit_result=success
service_runtime=1min36.319s
cpu_time=6.586s
memory_peak=256.0K
provider_requests=1
provider_http_attempts=0
provider_status_codes=[]
trial_count=1
trial_decision=rejected
trial_reason_code=provider_transport_error
accepted_candidate_count=0
candidate_ids=[]
cached_evaluation_statuses=[]
qualification_count=0
qualification_decisions=[]
```

The provider transport failure is not a candidate result. No OOS result or
qualification rejection was manufactured from it.

## Durable evidence readback

The campaign summary and typed trial evidence were independently read back:

```text
summary_readback=PASS
trial_evidence_readback=PASS
trial_evidence_hash=3f15378862d284a753ffc230df3ea0a1984d659a02eb47204445a88ee1a6bffd
trial_research_run_id=run-doge-experimental-039
trial_decision=rejected
trial_reason_code=provider_transport_error
trial_candidate_id=null
trial_candidate_artifact_hash=null
persisted_candidate_files=0
persisted_aggregation_files=0
persisted_qualification_files=0
```

The batch root was created only for this attempt and verified as:

```text
batch_root_mode=750
batch_root_owner=afbot-admin:afbot-admin
durable_file_count=2
```

The only durable files are:

```text
summary.json
trials/trial-0000-run-doge-experimental-039.json
```

## Safety state

```text
data_source=cached_only
exchange_access=false
promotion_state=unpromoted
paper_activation=false
execution_authority=false
live_enabled=false
orders=0
```

No candidate was promoted. No paper activation, testnet order, live order,
exchange call, scheduler, daemon, or persistent provider loop was started.

## Cleanup

The probe and campaign transient units, uploaded source tree, runner, archive,
and probe script were independently verified absent:

```text
temporary_inputs_absent=true
probe_unit_absent=true
campaign_unit_absent=true
research_timer_matches=0
research_active_matches=0
durable_file_count=2
```

## Local verification

This phase added only this Markdown evidence report; no production Python or
frontend code changed. The prior source commit had already passed its locked
suite and quality gates. The current pre-commit checks also passed:

```text
uv run --locked pytest -q: 703 passed in 8.96s
uv run --locked ruff check src tests: PASS
uv run --locked ruff format --check src tests: PASS
uv run --locked mypy src: PASS
uv lock --check: PASS
in_memory_syntax_compile: PASS; files=354
git diff --check: PASS
local_temp_cleanup: PASS
```

The cache-writing repository-wide `compileall` check remains unsuitable on this
Windows checkout because pre-existing overlong `research_lab` filenames fail
when Python creates `.pyc` paths. The in-memory compile above verifies the same
354 Python source/test files without writing those paths. The phase report also
passed the staged credential scan before delivery.

## Post-commit verification

The initial Phase 217 evidence commit and its fresh locked regression passed:

```text
initial_evidence_commit=d7e0beff6af80767e5a2a3d9d654e8e60c67934b
post_commit_test=703 passed in 9.49s
post_commit_test_commit=d7e0beff6af80767e5a2a3d9d654e8e60c67934b
post_commit_test_time=2026-09-01T09:23:50Z
```

## Decision and next gate

The small authenticated completion probe is currently reachable and authorized
(`HTTP 200`), but the full Creator request remains unstable: campaign `039`
again failed before any HTTP response. The single campaign budget for this
phase is exhausted. Do not repeat it, add a fallback model/provider, or create
an unattended retry loop. A future attempt needs a materially changed provider
request hypothesis or provider-side stability evidence plus a new explicit
bounded budget.

This phase proves only bounded provider-probe/campaign behavior and durable
fail-closed evidence. It does not prove candidate quality, profitability,
qualification, paper readiness, testnet readiness, or live readiness.

Credentials must never be pasted, printed, logged, committed, or included in summaries:
[REDACTED]
