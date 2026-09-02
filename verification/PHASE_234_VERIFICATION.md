# Phase 234 Verification — Console-Verified Creator Campaign

Date: 2026-09-02 (MYT / UTC+08:00)

Status: **BLOCKED / EVIDENCE-ONLY / FORBIDDEN-LINEAGE-ID**

## Scope

Close the Phase 233 SSH identity boundary through Kainode's out-of-band VNC console, then run exactly one bounded Creator campaign from the previously audited pushed source.

This phase did not change production code, qualification policy, promotion state, paper activation, exchange access, or execution authority.

## SSH identity closure

The server's Ed25519 fingerprint was read directly from the Kainode VNC console:

```text
SHA256:2EHNUWXLj2BPt/163uW942G+grhLoDVxhmtyrw7vdjQ
```

The out-of-band value:

- has the valid 43-character unpadded Base64 SHA-256 shape;
- matched the independently scanned Ed25519 fingerprint exactly;
- was pinned explicitly for every PuTTY SSH/SCP operation;
- passed a harmless identity probe as `afbot-admin` on host `kipopopo`.

No host-key check was bypassed and the malformed Phase 233 retained value was not repaired from the network scan.

## Exact-source binding

```text
source_commit=cd17e31d6f07d902532178c8d4f5ffaaaed93c57
runner_sha256=966649a348b47191ac71d6d3762a70097092afee98eb893747ae3c32312e9edd
archive_sha256=02040a5a4c6b6848d0d4c2cdfd795a25951f750ddd5d6f151d9afe57fc93669c
provider_source_sha256=a8cde3b33d401a00cdfcfa0653733f6f6e859be64a96682a5da9714c5fcc36cb
```

The runner and archive matched the prior audited hashes. The extracted provider module was imported from the archived source root.

## Cached-data and lineage preflight

```text
catalog_components=5
artifact_inspections=5
primary_rows=105120
bundle_hash=19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816
dataset_registry_hash=583cd7d15cb0a3faf019cb9940f2739578ba9d88d1b62792cb1a9f0a2e8d72bb
historical_candidate_count=24
historical_candidate_snapshot_sha256=71476c9e1c160ac0c142a03292ca566b1d21bf6bcb09b2ace71612d618fb06aa
```

The campaign read only the immutable cached DOGEUSDT dataset. Exchange access remained disabled.

## Provider attempt

```text
campaign_id=creator-batch-20260902-003
model_id=gemma-4-31b-it
request_count=1
max_retries=0
fallback_provider=false
status_code=200
finish_reason=stop
thinking_level=minimal
include_thoughts=false
response_format=json_object
content_length=1628
content_sha256=4968cc7bec10bc8f8045a73c619389ad79e1aff784ad050ebffac234e276f5eb
```

The raw prompt and raw provider response were not persisted.

## Result

Typed trial readback returned:

```text
decision=rejected
reason_codes=[candidate_id_forbidden]
candidates=0
cached_evaluations=0
qualifications=0
orders=0
```

The provider reused a candidate ID from the complete forbidden historical snapshot. The existing lineage guard rejected it before candidate persistence, deterministic evaluation, or qualification.

This is valid negative evidence. It does not authorize a retry, candidate-ID rewrite, qualification, promotion, paper activation, testnet, live execution, or orders.

## Immutable evidence

Final root:

```text
/var/lib/autonomous-futures/research/dogeusdt-365d-typed-20260902-001/creator-batch-20260902-003
```

Persisted files:

```text
campaign-summary.json
  sha256=38c598ba88be7141cc2a361daedc3f68fc30ce2ceeceee7e181f3e77b3190f38
trials/trial-0000-run-doge-google-gemma-20260902-003.json
  sha256=e15eddc78d3022e5cf791579e94cb4c2c352d4dce7f739f7fd02b19d39d67bcd
```

The trial was independently read through `read_creator_batch_trial_evidence` from the exact archived source.

## Safety and cleanup

```text
promotion_state=unpromoted
paper_activation=false
execution_authority=false
exchange_access=false
orders=0
raw_prompt_persisted=false
raw_provider_response_persisted=false
credential_persisted=false
automatic_retry=false
fallback_provider=false
matching_processes=0
research_timers=0
research_units=0
unit_load_state=not-found
local_transients=absent
```

The final immutable evidence was preserved. Temporary runner, archive, source root, systemd unit state, readback script, and local staging files were removed.

## Next major boundary

Do not run another provider campaign unchanged. The next decision is architectural: keep requiring provider-authored globally unique candidate IDs, or move canonical candidate-ID assignment to the trusted local boundary while preserving provider proposal identity and complete historical lineage. That contract requires a separate strict-TDD review before any further provider request.
