# Phase 228 Verification — bounded Creator campaign provider schema boundary

Status: `BLOCKED / EVIDENCE-ONLY`

## Scope

- Campaign: `creator-batch-20260902-002`
- Symbol: `DOGEUSDT`
- Model: `gemma-4-31b-it`
- Data root: `/var/lib/autonomous-futures/research/dogeusdt-365d-typed-20260902-001`
- Historical lineage root: `/var/lib/autonomous-futures/research/dogeusdt-365d`
- Final evidence root: `/var/lib/autonomous-futures/research/dogeusdt-365d-typed-20260902-001/creator-batch-20260902-002`
- Transient unit: `afbot-creator-campaign-20260902-002`
- Runner/source archive were disposable and were removed after readback.

## Preflight

- Local repository head and `origin/main` were equal at `b3455f9b929d1f41099083216b06cd9ff023f106`.
- Disposable runner SHA-256: `abf8c184463ee61233e3438d395017795aacd34f18aa944070136806f807b0b2`.
- Disposable source archive SHA-256: `2f10f03f1ce734f0ddc11ac5f231cfcfd00bcd8f75e1ee36927854b657adbbfc`.
- Imported provider endpoint was the official Google AI Studio OpenAI-compatible endpoint.
- Verified dataset components: `5`.
- Verified artifact inspections: `5`.
- Primary 5-minute rows: `105120`.
- Historical forbidden candidate snapshot: `24` IDs.
- Historical snapshot SHA-256: `71476c9e1c160ac0c142a03292ca566b1d21bf6bcb09b2ace71612d618fb06aa`.
- Credential source was injected through `LoadCredentialEncrypted`; metadata only: mode `600`, owner `root`, group `root`, regular file, size `223` bytes.
- No exchange or execution endpoint was used during preflight.

## Campaign result

- Request budget: `1`.
- Requests made: `1`.
- Retries: `0` (`max_retries=0`).
- Provider HTTP status: `200`.
- Response keys: `choices`, `created`, `id`, `model`, `object`, `usage`.
- Choice count: `1`.
- Finish reason: `stop`.
- Content kind: `string`.
- Content length: `1637`.
- Content SHA-256: `37a5a1412b773ff9e5b46928205a2447952e131c324deb6bf509517424cae007`.
- Generator decision: `rejected`.
- Rejection reason: `schema_rejected`.

The `HTTP 200` envelope did not satisfy the typed Creator proposal contract. The batch therefore stopped before candidate creation and deterministic evaluation. No retry, fallback provider, raw prompt, or raw provider response was persisted.

## Evidence readback

- Persisted JSON files: `2` (campaign summary plus one typed trial evidence file).
- Typed trial decision: `rejected`.
- Typed trial reason code: `schema_rejected`.
- Candidate artifacts: `0`.
- Candidate registry: absent.
- Cached evaluations: `0`.
- Qualification artifacts: `0`.
- Evidence tree SHA-256: `ba9a156989616b78d5713ed2b812e9230f884ba71e984c6004fea4911a7f69de`.
- Independent canonical trial readback: `PASS`.
- Forbidden raw-field scan: `PASS`.

## Safety boundary

- Promotion state: `unpromoted`.
- Paper activation: `false`.
- Execution authority: `false`.
- Exchange access: `false`.
- Orders: `0`.
- No candidate was qualified or promoted.

## Cleanup

- Final evidence root: mode `700`, owner `root`, group `root`.
- Temporary campaign root: absent.
- Temporary source root: absent.
- Temporary runner/archive: absent.
- Transient unit: `not-found`.
- Research timers: `0`.
- Research units: `0`.
- Matching campaign processes: `0`.
- Remote stage cleanup: `PASS`.
- Local transient cleanup: `PASS`.

## Boundary reached

Phase 228 remains blocked at the provider proposal-schema boundary. The successful transport envelope is not strategy evidence and does not authorize retry, fallback, qualification, promotion, paper activation, testnet execution, or live execution. Further work requires a separately bounded change to the provider/schema boundary or a separately approved campaign; this run is complete and not retried.
