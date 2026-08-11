# Phase 6B Verification — VPS immutable bundle

## Result

Materialized and reread a bounded immutable Binance USDⓈ-M Futures research
bundle on Kainode using unsigned public REST data and existing project
contracts.

| Item | Evidence |
|---|---|
| Host | `147.79.18.15`, Ubuntu 24.04.4, 6 vCPU, 15 GiB RAM |
| Runtime | CPython 3.14.7, `uv 0.12.2` |
| Remote locked suite | `481 passed in 20.56s` |
| Filter snapshot | `bd5d91c19bf09b8c3347681fdcdd380a236704cf647fb63962b383a1086965bb` |
| Dataset registry | `e9d25b86e82d99b8ca55bfe92a70fd165b39bd2b61bb501676608fdf66d6b754` |
| Dataset bundle | `d75de67e440d1caa9f33af05647cb782893b93c3a167836d93087981ab3edc95` |
| Components | 13: 6 kline, 3 mark-price, 3 funding, 1 exchange-filter |
| Bundle range | `2023-10-31T08:00:00Z` → `2023-11-10T03:40:00Z` |
| Mark rows | `2,828` per BTCUSDT/ETHUSDT/SOLUSDT |

The registry and bundle were read back through their hash-verifying readers.
Generated remote artifacts are under the ignored `research/immutable-data/`
root and are not committed as binary data.

## Boundary and limitation

The public mark-price endpoint has a real shared five-bar outage beginning at
`2023-11-10T03:40:00Z` (`1699587600000` through `1699588800000`). BTCUSDT,
ETHUSDT, and SOLUSDT all lack those rows. The bundle therefore ends before the
gap; no values were fabricated and no full-history claim is made.

No API/UI, candidate qualification, promotion, paper activation, credentials,
execution authority, or order routing was added. This is cached public
research evidence only.
