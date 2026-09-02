# Phase 226 Verification — bounded Creator campaign blocked by cache integrity

## Status

```text
BLOCKED / EVIDENCE-ONLY
```

Date of evidence: `2026-09-02T02:19:07Z`

## Scope

Attempt one finite Creator campaign request using the committed Google AI Studio provider contract:

```text
verified dataset catalog
→ canonical artifact inspection
→ one Creator request
→ typed trial/candidate/OOS/qualification evidence
```

The campaign was bounded to one request, `gemma-4-31b-it`, `max_retries=0`, no fallback, cached-only market data, and no promotion or execution authority.

## Actual result

```text
campaign_id:       creator-batch-20260902-001
campaign_status:   blocked
failure boundary:  ArtifactIntegrityError
provider requests: 0
candidates:        0
OOS artifacts:     0
qualification:     0
```

The current canonical artifact inspector stopped the run before prompt construction and before provider authentication. No Google AI Studio request was sent.

Durable remote evidence:

```text
/var/lib/autonomous-futures/research/dogeusdt-365d/creator-batch-20260902-001/campaign-summary.json
sha256: 48d229e820190e52f65444230bd5e6e6b4721d15c34d7b705323d3d68b4e89c0
files: 1
mode/owner/group/type: 600 root root regular file
```

## Dataset binding and root cause

The persisted catalog itself passed its registry/bundle binding check:

```text
bundle_hash:          30a365020f816f090d2ed66163dbda5f3a2a4490e1b283c6385b4b07cf27ccc3
dataset_registry_hash: 17f140c77f1911f26dd63bd0d20144149dab7cd424a3760f4b7797d10b61375e
catalog binding:      PASS
```

The component artifacts are not consumable by the current typed inspector:

```text
DOGEUSDT-exchange-filters.json: PASS
DOGEUSDT-5m.manifest.json:      blocked; manifest is valid, but inspector resolves DOGEUSDT-5m.parquet under the parent of the dataset root
DOGEUSDT-15m.manifest.json:     blocked; same root-level parquet layout mismatch
DOGEUSDT-funding.json:          blocked; raw JSON array, 1095 items, not the current typed derivatives manifest
DOGEUSDT-mark-price-5m.manifest.json: blocked; DatasetManifest-shaped payload, not the current typed derivatives manifest
```

The root-level files do exist, but the current inspector's expected path differs:

```text
DOGEUSDT-5m.parquet:  present at dataset root, absent at inspector-resolved parent path
DOGEUSDT-15m.parquet: present at dataset root, absent at inspector-resolved parent path
```

This is a stale/incompatible remote cache foundation, not evidence of a provider failure. The campaign did not bypass the guard and did not reinterpret unverified data as usable.

## Safety

```text
data_source=cached_only
exchange_access=false
promotion_state=unpromoted
paper_activation=false
execution_authority=false
orders=0
raw_prompt_persisted=false
raw_provider_response_persisted=false
credential_persisted=false
automatic_retry=false
fallback_provider=false
```

## Cleanup

```text
local campaign transients: PASS
remote runner/source/archive/temp root: absent
transient systemd unit: not-found
research timers: 0
research units: 0
credential metadata: mode=600 owner=root group=root type=regular file
```

The blocked summary is retained as evidence; no empty candidate, OOS, or qualification artifact was created.

## Decision

No retry or cache bypass was performed. The next work requires a separately bounded foundation-repair slice that rebuilds or migrates the remote cached artifacts into the current typed schema and path contract, followed by fresh integrity verification. The Creator campaign remains unrun.
