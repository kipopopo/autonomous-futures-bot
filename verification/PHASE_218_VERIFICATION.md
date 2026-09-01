# Phase 218 Verification — changed full Creator provider probe 040

## Status

**BLOCKED / EVIDENCE-ONLY**

This phase tested one materially changed provider request hypothesis: the full
Creator prompt and pinned model were retained, while `temperature` changed from
`0.2` to `0.0`. The first transient invocation failed before importing project
code because its `PYTHONPATH` was omitted. After correcting only that invocation
environment, exactly one provider request was issued and stopped at the
transport boundary before an HTTP response. The required `2xx` gate therefore
failed and campaign `041` was not run.

- Verification time: `2026-09-01T09:44:57Z`
- Source commit: `6343e2d1b8b2733d121e26d01086ce1ce338fa54`
- Provider: `opencode`
- Pinned model: `deepseek-v4-flash`
- SSH operator: `afbot-admin`
- Host: `147.79.18.15`
- Pinned ED25519 fingerprint: `SHA256:2EHNUWXLj2BPt/163uW942G+grhLoDVxhmtyrw7vdjQ`

## Probe construction and source binding

The temporary probe reused the existing Creator request and prompt builders. It
used the same immutable scope identifiers and complete 51-ID historical
candidate snapshot used by the preceding bounded campaign. The probe retained
no raw prompt or provider response body:

```text
probe_040_local_checks=PASS
forbidden_candidate_ids=51
source_archive_sha=c066782b30c08c0cf202c7eb7b02a0bdfb3da544095d852f12949cd88679f210
probe_sha=52c5402c8bc7400c3adb27b70828b316903f85c0c53fc2651098e70362944e9f
remote_compile=PASS
```

The request parameters were:

```text
provider=opencode
model=deepseek-v4-flash
prompt_chars=2364
temperature=0.0
max_tokens=2048
response_format=json_object
http_timeout_seconds=90
```

The probe referenced the existing immutable DOGEUSDT research scope:

```text
bundle_hash=30a365020f816f090d2ed66163dbda5f3a2a4490e1b283c6385b4b07cf27ccc3
dataset_registry_hash=17f140c77f1911f26dd63bd0d20144149dab7cd424a3760f4b7797d10b61375e
cached_symbol=DOGEUSDT
```

This was a provider completion probe, not a cached evaluation or qualification
run. No exchange endpoint or exchange credential was loaded.

## Transient setup attempt

The first systemd invocation failed before the probe imported the project
package because `PYTHONPATH` was missing. It did not reach the provider:

```text
ModuleNotFoundError: No module named 'autonomous_futures'
probe_unit_exit=1
provider_request_reached=false
```

The unit collected successfully and its uploaded probe was removed before the
corrected invocation. The correction added only the verified source path to the
transient command environment; it did not change the request payload or add a
retry policy.

## Changed provider probe result

The corrected transient unit issued exactly one authenticated request. The
provider returned no HTTP response before the 90-second client cap:

```text
provider_requests=1
provider_http_attempts=0
completion_status=provider_transport_error
completion_elapsed_seconds=90.880372
completion_exit=0
probe_unit_exit=0
response_body_retained=false
```

The typed transport failure is not a candidate result. No response JSON, OOS
result, qualification decision, or promotion evidence was manufactured from
it.

## Campaign gate and safety boundary

Campaign `041` was canceled because the changed full-prompt probe did not return
a valid `2xx` completion. No campaign runner, cached evaluator, candidate
persistence, OOS aggregation, qualification, promotion, paper activation,
testnet order, live order, or exchange request was invoked.

```text
campaign_041_started=false
candidate_count=0
oos_result_count=0
qualification_count=0
orders=0
exchange_access=false
promotion_state=unpromoted
paper_activation=false
execution_authority=false
live_enabled=false
```

The provider probe success/failure boundary does not grant execution authority.
The system remains research-only and fail-closed.

## Cleanup

The corrected transient unit, uploaded probe, extracted source tree, and source
archive were removed and independently checked. No research scheduler or active
research service remained:

```text
local_temp_cleanup=PASS
remote_temp_cleanup=PASS
probe_unit_after_cleanup=not-found
research_timer_matches=0
research_active_matches=0
```

No persistent provider loop, daemon, scheduler, or server was started.

## Local verification

This phase adds only this Markdown evidence report; no production Python,
frontend, dependency, or lockfile change is required. The probe itself passed
local syntax and Ruff checks before upload. Repository gates will be run against
this report before delivery.

## Decision and next gate

The one changed request hypothesis did not improve the full Creator completion
path: `temperature=0.0` still produced a transport failure before HTTP. The
bounded provider probe is complete and the campaign gate is closed. Do not repeat
this request, add a fallback model/provider, or create an unattended retry loop.
A future attempt requires a materially different provider-side hypothesis or
verified provider stability evidence plus a new explicit bounded budget.

This phase proves only bounded probe behavior and fail-closed handling. It does
not prove candidate quality, profitability, qualification, paper readiness,
testnet readiness, or live readiness.

Credentials must never be pasted, printed, logged, committed, or included in summaries:
[REDACTED]
