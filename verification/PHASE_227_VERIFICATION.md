# Phase 227 Verification — immutable remote cache layout repair

## Status

**GREEN / BOUNDED-CACHE-REPAIR / EVIDENCE-ONLY**

This phase repaired the remote DOGEUSDT research-cache layout into a new,
versioned root that satisfies the current registry, bundle, manifest, and typed
derivatives-reader contracts. The original cache root was not modified. This
phase did not run a Creator campaign or contact a provider.

- Verification time: `2026-09-02T02:54:55Z`
- Cache manifest creation time: `2026-09-02T02:36:49Z`
- Source snapshot: `659d9d2867dc22b3bbc632fdac5d3858b09608f3`
- Dependency lock hash: `487a92cfe4abbc2ff06bc4ff6e1c1a80b5c981cc6982fa7462f995ca8aef0264`
- SSH operator: `afbot-admin`
- Host: `147.79.18.15`
- New root: `/var/lib/autonomous-futures/research/dogeusdt-365d-typed-20260902-001`

## Scope and migration boundary

The repair read the existing cached files from:

```text
/var/lib/autonomous-futures/research/dogeusdt-365d
```

It performed no exchange or provider request. The two legacy kline Parquet
files were copied byte-for-byte into the new canonical layout after timestamp,
closed-bar, range, and row-count validation. The legacy mark-price Parquet and
funding JSON array were converted with the current typed derivatives writers.
The existing exchange-filter snapshot was read and written through the current
snapshot contract.

No file under the original root was overwritten or deleted.

## Input cache evidence

```text
legacy_5m_rows=105120
legacy_5m_range=2025-08-21T10:45:00Z .. 2026-08-21T10:40:00Z
legacy_5m_sha256=ed9322248a3f48f6f3aec77b9cc81988722b1d9a518f4a49c6e2ad00519b620d

legacy_15m_rows=35040
legacy_15m_range=2025-08-21T10:45:00Z .. 2026-08-21T10:30:00Z
legacy_15m_sha256=a7cc091cbc131311949fc8effc8ce28d5b129c86bebd1b04e63430558118be57

legacy_mark_rows=105120
legacy_mark_sha256=a09768f500d03fb0c1a5308c423f44227b63b664fa286ce83aeedca18c9a1307

legacy_funding_rows=1095
legacy_funding_sha256=35ef9d1e997b116c6fb734eba2a07b8121e991eb2aac4ab7030bbb85c29da807

legacy_filter_snapshot_sha256=31631a5272e77266e2dfdbded631c3d80bc6fb789afc3beb5a8bdc1572cfd5f2
legacy_filter_snapshot_hash=f7a1871f94520e206b7ed63ebd2a398d52bbf12969e6fb3e6910d3d8e9cffe5e
```

## New typed cache evidence

The new root contains exactly 11 expected files. Artifact and manifest
readback produced:

| Component | Rows | Artifact SHA-256 | Manifest hash |
|---|---:|---|---|
| 5m kline | 105120 | `ed9322248a3f48f6f3aec77b9cc81988722b1d9a518f4a49c6e2ad00519b620d` | `ec932df8d2544ad84bc1b73fd2d38a8c010d8ca223e3f01598ddf7e9cf63f535` |
| 15m kline | 35040 | `a7cc091cbc131311949fc8effc8ce28d5b129c86bebd1b04e63430558118be57` | `9d82181013983223f5c1273acf94ff1050918d9d81871c23db03860642f0e310` |
| mark price 5m | 105120 | `35f3d6b618bbfdf67ffc6e54a3f02c539a91a7be9cc68f0229f24313bb954222` | `4217879fdbf389a1e9bc2033b110f32eadfb54e29258f471dc454a7a722cf6fd` |
| funding rate | 1095 | `cf5f013409493606a2edbe16f320091206dd786e519036df149074ed34b92339` | `71ac381a7a148095fbb59d03ff3bbe87a9f7156c74fcbe635a2de7a971cfe414` |
| exchange filters | n/a | `31631a5272e77266e2dfdbded631c3d80bc6fb789afc3beb5a8bdc1572cfd5f2` | `f7a1871f94520e206b7ed63ebd2a398d52bbf12969e6fb3e6910d3d8e9cffe5e` |

The current readers confirmed primary coverage from
`2025-08-21T10:45:00Z` through `2026-08-21T10:45:00Z` exclusive. The 15m
context ends at `2026-08-21T10:30:00Z` and satisfies the closed-bar availability
boundary.

```text
registry_hash=583cd7d15cb0a3faf019cb9940f2739578ba9d88d1b62792cb1a9f0a2e8d72bb
bundle_hash=19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816
registry_binding=PASS
components=5
catalog_inspections=5 PASS
manifest_hashes=PASS
artifact_schema_readers=PASS
cache_readback=PASS
file_count=11 hashes=PASS
```

## Safety and cleanup

```text
data_source=cached_migration_only
network_access=false
exchange_access=false
provider_requests=0
campaign=not_run
candidates=0
qualification=0
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

Final-root publication was atomic. The original root remained unchanged, and
final remote audit passed with numeric owner/group `1000:1000`, mode `0775`.
The disposable staging root was removed.

```text
legacy_root_unchanged=PASS
stage_cleanup=PASS
research_units=0
research_timers=0
research_processes=0
remote_cleanup=PASS
```

No credential value was read, printed, or persisted. No systemd unit, timer,
network service, or unattended loop was created.

## Decision

The cache-foundation blocker is closed for this versioned root. The original
legacy root remains preserved and is not considered consumable by the current
Creator path.

The next major boundary is a separately bounded Creator campaign using the new
root. This phase does not authorize that campaign, provider usage, candidate
qualification, promotion, paper activation, testnet activity, or live
execution.

Credentials must never be pasted, printed, logged, committed, or included in summaries:
[REDACTED]
