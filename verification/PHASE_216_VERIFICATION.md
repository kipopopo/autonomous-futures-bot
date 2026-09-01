# Phase 216 Verification — bounded cached Creator campaign 037

## Status

**BLOCKED / EVIDENCE-ONLY**

This phase executed the single explicitly approved bounded Creator campaign
against the immutable cached DOGEUSDT scope. The provider request stopped at a
transport boundary before an HTTP response was received. The typed trial was
persisted as rejected; no candidate, cached evaluation, OOS aggregation, or
qualification artifact was created.

- Verification time: `2026-09-01T09:00:07Z`
- Source commit: `f74ed1b92ce2e399847b57aaea32ebafdf1edaa2`
- Campaign root: `/var/lib/autonomous-futures/research/dogeusdt-365d/creator-batch-20260901-037`
- Research run: `run-doge-experimental-037`
- Creator run: `doge-creator-experimental-037`
- Provider: `opencode`
- Pinned model: `deepseek-v4-flash`
- SSH operator: `afbot-admin`
- Host: `147.79.18.15`
- Pinned ED25519 fingerprint: `SHA256:2EHNUWXLj2BPt/163uW942G+grhLoDVxhmtyrw7vdjQ`

## Preflight and source binding

The temporary runner was syntax-checked, linted, imported through the project
source tree, and verified to contain the complete 51-ID historical candidate
snapshot before upload. The immutable source archive contained 198 `src`
entries and was uploaded with the runner through the pinned SSH route.

```text
runner_local_checks=PASS
forbidden_candidate_ids=51
source_archive_entries=198
remote_archive_hash=c066782b30c08c0cf202c7eb7b02a0bdfb3da544095d852f12949cd88679f210
remote_runner_hash=c760d1730c33122b0b8b703839b14959410c61bc54649382898676fdde21896e
remote_compile=PASS
```

The runner verified the DatasetBundle, DatasetRegistry, manifest bindings, and
source-file hashes before reading the cached frames:

```text
bundle_hash=30a365020f816f090d2ed66163dbda5f3a2a4490e1b283c6385b4b07cf27ccc3
dataset_registry_hash=17f140c77f1911f26dd63bd0d20144149dab7cd424a3760f4b7797d10b61375e
cached_symbol=DOGEUSDT
cached_rows=105120
cached_data_source=cached_only
configured_oos_windows=4
```

No exchange endpoint or exchange credential was loaded. The provider credential
was supplied only through the transient encrypted systemd credential mapping;
its value was never printed, logged, persisted, or included here.

## Bounded campaign result

The campaign used one request, one provider invocation, the pinned model, a
finite output-token cap, and no outer retry or fallback path.

```text
campaign_unit_exit=0
campaign_unit_result=success
service_runtime=1min35.875s
cpu_time=6.303s
memory_peak=696.0K
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

The durable typed trial evidence was read back successfully:

```text
trial_evidence_readback=PASS
trial_evidence_hash=ae4162676008e3839e02717f5c0c871ff2d034a237f0fbf0f722ce238f41670a
trial_research_run_id=run-doge-experimental-037
trial_candidate_id=null
trial_candidate_artifact_hash=null
```

The provider transport failure is not a candidate result. No OOS result or
qualification rejection was manufactured from it.

## Durable output and immutability boundary

Independent readback of the campaign summary and typed trial reader passed.
The batch root contains exactly these durable files:

```text
summary.json
trials/trial-0000-run-doge-experimental-037.json
```

The root was created for this batch only and verified as:

```text
batch_root_mode=750
batch_root_owner=afbot-admin:afbot-admin
persisted_candidate_files=0
persisted_aggregation_files=0
persisted_qualification_files=0
```

## Safety state

The persisted summary explicitly retained the non-authoritative research state:

```text
data_source=cached_only
exchange_access=false
promotion_state=unpromoted
paper_activation=false
execution_authority=false
live_enabled=false
orders=0
```

No candidate was promoted. Paper activation, testnet execution, live execution,
order submission, scheduler enablement, and persistent provider loops were not
performed.

## Cleanup

The transient unit was collected and independently verified absent. Temporary
source, runner, and archive paths were removed and independently verified absent:

```text
temporary_inputs_absent=true
campaign_unit_absent=true
campaign_unit_state=not-found
research_timer_units=none
research_active_units=none
```

The only matching unit definitions were the pre-existing static
`autonomous-futures-live-preflight.service` and
`autonomous-futures-live-readonly.service`; neither is a research scheduler and
neither was enabled or changed by this phase.

## Local verification

The locked project checks completed as follows:

```text
uv run --locked pytest -q: 703 passed in 15.34s
uv run --locked ruff check src tests: PASS
uv run --locked ruff format --check src tests: PASS
uv run --locked mypy src: PASS
uv lock --check: PASS
git diff --check: PASS
in_memory_syntax_compile: PASS; files=354
```

The cache-writing repository-wide `compileall` command was also attempted but
hit the pre-existing Windows path-length limitation in long `research_lab`
module/test filenames. For example, it failed while creating a `.cpython-314`
cache file for
`research_observation_integrity_evaluation_observation_observation_handoff_observation_review_handoff_observation_review_handoff_handoff.py`.
No new source file was involved. The in-memory syntax compile above verified
all 354 Python source/test files without writing cache paths.

## Post-commit verification

The initial evidence commit and its fresh locked regression were verified:

```text
initial_evidence_commit=b261ebb49d6ec9bd2975ab1455cc64143938536f
post_commit_test=703 passed in 9.16s
post_commit_test_commit=b261ebb49d6ec9bd2975ab1455cc64143938536f
post_commit_test_time=2026-09-01T09:03:08Z
```

## Decision and next gate

The bounded campaign attempt is complete but blocked by `provider_transport_error`
before HTTP completion. The approved one-request campaign budget is exhausted;
there was no retry or model/provider fallback. A future campaign requires a new
explicit bounded budget and a fresh provider transport/authorization decision.
This phase does not justify candidate qualification, profitability, paper
activation, testnet access, or live readiness.

Credentials must never be pasted, printed, logged, committed, or included in summaries:
[REDACTED]
