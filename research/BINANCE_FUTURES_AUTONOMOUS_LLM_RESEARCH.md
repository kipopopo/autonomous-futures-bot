# Research Report: Autonomous LLM Binance Futures Trading System

**Tarikh research:** 6 Ogos 2026 (MYT)  
**Status:** Research dan feasibility assessment sahaja — belum proposal pembangunan, belum live trading  
**Baseline portfolio:** USD 100  
**Fokus awal:** Binance USDⓈ-M perpetual futures  
**Pemisahan projek:** Projek baharu; bukan sambungan VibeCrypt

> **Timeframe decision update (6 Ogos 2026):** Baseline research selepas laporan ini menggunakan **5m primary bars** dan **15m closed-bar regime context**. Hasil 1h di bawah kekal sebagai archived benchmark sahaja; ia tidak boleh digunakan untuk candidate promotion pada 5m/15m.

> **Amaran penting:** Futures berleverage boleh menghapuskan seluruh modal. Tiada strategi, LLM, backtest, atau architecture yang boleh menjamin keuntungan. Laporan ini ialah analisis teknikal dan research, bukan nasihat kewangan atau undang-undang.

---

## 1. Executive summary

### 1.1 Kesimpulan utama

Projek ini **secara teknikal boleh dibina sebagai sistem autonomous research-and-execution**, tetapi matlamat yang realistik bukan “LLM pasti mengutip keuntungan.” Matlamat yang defensible ialah:

1. LLM mencari hipotesis, menulis specification strategy, mencadangkan perubahan, mengkritik hasil, dan belajar daripada bukti;
2. verifier deterministik menguji setiap calon secara causal dan cost-aware;
3. promotion pipeline hanya meluluskan calon yang lulus walk-forward, stress test, paper trading, dan governance gates;
4. risk engine dan order manager deterministik mempunyai kuasa mutlak ke atas sizing, leverage, stops, exposure, reconciliation, dan kill switch;
5. LLM **tidak pernah** memegang API secret, memanggil exchange order endpoint secara langsung, atau menaikkan risk limit sendiri.

Kajian agentic trading terkini mendapati evidence protocol masih sukar dibandingkan: dalam subset utama 19 kajian, hanya 2 melaporkan time-consistent split yang boleh diekstrak dan hanya 1 melaporkan transaction-cost model secara eksplisit.[38] Jadi, kewujudan demo LLM trading yang nampak hebat bukan bukti ia mempunyai edge yang boleh diperdagangkan.

### 1.2 Reality check untuk modal USD 100

USD 100 sesuai sebagai **evidence account**, bukan income account. Dengan modal sekecil ini:

- fee, spread, slippage, funding, minimum notional, dan rounding mempunyai impak besar;
- terlalu banyak pair atau terlalu kerap trade akan memecahkan modal kepada order yang tidak feasible;
- high leverage tidak mencipta edge; ia cuma mengurangkan margin yang diperlukan dan mendekatkan liquidation;
- objective pertama mesti **survive, measure, and learn**, bukan memaksimumkan turnover atau ROE.

Baseline research yang disyorkan:

| Parameter | Baseline research |
|---|---:|
| Position mode | One-way |
| Margin mode | Isolated |
| Concurrent positions | 1 pada peringkat awal |
| Selected leverage | 2× maksimum untuk fasa awal |
| Effective total notional | Tidak melebihi 1.0× equity |
| Normal risk per trade | 0.50%–0.75% equity |
| Absolute hard cap | 1.00% equity per trade |
| Daily loss stop | 2R atau 2% equity, mana lebih kecil |
| Drawdown throttle | 5%: risiko dibelah dua |
| Drawdown halt | 8%: hentikan candidate live/paper cohort |
| Catastrophic kill | 10% atau state mismatch kritikal |

**Rule paling penting:** jika minimum valid order selepas `tickSize`, `stepSize`, dan `MIN_NOTIONAL` menyebabkan potential loss melebihi risk budget, bot mesti **skip trade**, bukan menaikkan risk.

### 1.3 Strategi yang patut diprioritikan

| Rank | Keluarga strategy | Keputusan research | Sebab utama |
|---:|---|---|---|
| 1 | Regime-gated, low-turnover trend/breakout | **Paling sesuai untuk dikaji dahulu** | Hipotesis jelas, causal, mudah diaudit; tetapi static parameters gagal stabil dalam screen kita |
| 2 | Range mean reversion dengan strict regime veto | **Secondary candidate** | Boleh bekerja dalam range; sangat berbahaya ketika trend/breakout |
| 3 | Funding-aware exposure / delta-neutral carry | **Kajian lanjut, bukan untuk USD 100 awal** | Potensi diversifikasi; perlukan dua legs, modal dan execution lebih kompleks |
| 4 | Pairs/stat-arb dan cross-sectional momentum | **Defer** | Minimum order, korelasi pecah, dan capital fragmentation |
| 5 | Order-flow / microstructure | **Research-only** | Signal mungkin wujud, tetapi latency, queue, spread dan data depth menjadikannya sukar untuk retail bot |
| 6 | Market making | **Reject untuk fasa awal** | Adverse selection, inventory risk, queue position, operational intensity |
| 7 | Grid tanpa regime stop, averaging down, martingale | **Reject** | Small frequent wins menutup tail risk sehingga satu trend menghapuskan akaun |
| 8 | LLM discretionary direct-to-order | **Reject** | Hallucination, prompt injection, non-determinism, tiada reproducibility |

### 1.4 Hasil empirical screen 1h yang diarkibkan

Kita menjalankan causal 1-hour family screen pada BTCUSDT, ETHUSDT dan SOLUSDT dari 1 Januari 2023 hingga snapshot 6 Ogos 2026. Parameter dipilih hanya pada 2023–2024, dibekukan, kemudian dinilai pada 2025 dan 2026 YTD. Model memasukkan 0.04% taker fee per fill, 0.02% slippage per fill, actual historical funding, next-open execution, dan reversal dua fills.

| Family | 2025 frozen OOS return | 2025 max DD | 2026 YTD return | 2026 max DD |
|---|---:|---:|---:|---:|
| Bollinger reversion | +4.82% | -37.15% | -10.31% | -38.95% |
| Donchian breakout | -32.06% | -40.74% | -0.51% | -43.53% |
| EMA trend | -63.73% | -69.47% | -3.82% | -43.95% |
| Regime hybrid | -5.84% | -30.06% | +5.17% | -33.69% |
| RSI reversion | -28.05% | -32.33% | -6.95% | -17.34% |

Ini **bukan** bukti semua trend atau mean-reversion strategy tidak berfungsi. Ia bukti lebih berguna: static textbook rules tidak cukup stabil, cost drag material, dan result boleh bertukar tanda antara regime. Tiada satu pun candidate ini layak dipromosikan. Hasil ini kini **archived** kerana contract timeframe telah berubah.

### 1.4.1 Replacement screen: 5m primary + 15m closed-bar context

Snapshot baharu telah dikutip secara public/read-only dari 1 Januari 2023 hingga 6 Ogos 2026: **378,211 fully closed 5m candles** dan **126,070 fully closed 15m candles** bagi setiap BTCUSDT, ETHUSDT, dan SOLUSDT. Semua 15m regime values hanya di-forward ke 5m selepas source candle 15m ditutup. Window parameter asal 1h discale 12× untuk mengekalkan anggaran horizon masa asal, bukan dikecilkan menjadi strategi scalp.

Screen replacement masih menggunakan next-open execution, historical funding, 0.04% taker fee per fill, dan 0.02% slippage per fill. Oleh sebab 0.12% round-trip stress itu mungkin masih terlalu optimistik untuk 5m execution sebenar, result hanya boleh digunakan untuk **reject/continue research**, bukan promote candidate.

| Family | 2025 frozen OOS return | 2025 max DD | 2026 YTD return | 2026 max DD |
|---|---:|---:|---:|---:|
| Bollinger reversion | -31.83% | -47.82% | -8.65% | -44.31% |
| Donchian breakout | -29.76% | -39.12% | -12.71% | -47.75% |
| EMA trend | -23.50% | -39.01% | +8.12% | -41.99% |
| Regime hybrid | -12.30% | -17.95% | -0.32% | -11.80% |
| RSI reversion | -37.73% | -42.07% | +8.92% | -11.53% |

**Decision:** zero candidate promoted. Even the least-bad outcomes violate the USD 100 drawdown envelope by a wide margin. The refreshed research pipeline passed **8 tests**, including a causality test proving a 15m context candle is unavailable to 5m logic until that 15m candle has closed.

### 1.5 Regulatory stop sign untuk Malaysia

SC Malaysia mengambil enforcement action terhadap Binance pada 2021 kerana mengendalikan DAX secara tidak sah di Malaysia dan ketika itu meminta pelabur Malaysia berhenti berdagang serta mengeluarkan pelaburan.[19]

SC memperkemas Guidelines on Recognized Markets untuk DAX pada Mei 2026.[48]

Senarai registered DAX yang dikemas kini pada 20 Julai 2026 tidak menyenaraikan Binance.[49]

Trading, issuance dan safekeeping digital assets di Malaysia berada di bawah SC.[50]

**Inference, bukan legal opinion:** sebelum live Binance integration, kita perlu mendapat pengesahan undang-undang/contractual semasa bahawa user, account, lokasi operasi, dan product futures dibenarkan. Sistem tidak akan direka untuk mengelak geo-restriction atau peraturan. Proposal kelak mesti exchange-abstracted supaya paper research tidak bergantung kepada satu venue.

---

## 2. Scope dan kaedah research

### 2.1 Scope

Research ini meliputi:

- USDⓈ-M perpetual contract mechanics;
- margin, leverage, maintenance margin, liquidation, insurance fund, dan ADL;
- mark price, index price, last price, funding, fees, filters dan order semantics;
- family strategi futures dan regime/failure modes;
- small-account economics untuk USD 100;
- backtest integrity dan model risk;
- architecture autonomous LLM dengan deterministic safety boundary;
- Malaysia access/regulatory risk.

### 2.2 Evidence hierarchy

1. **Binance Developer/Support documentation dan live public endpoint** untuk exchange mechanics.
2. **SC Malaysia** untuk regulatory facts.
3. **Academic/primary research** untuk strategy evidence dan validation risk.
4. **Empirical local screen** untuk falsification awal, bukan production backtest.

### 2.3 Limitations

- Fee sebenar bergantung pada account/VIP level; public example bukan jaminan rate account.
- Historical OHLCV tidak merekonstruksi queue position, partial fill atau intra-bar stop path.
- Three-symbol, one-hour screen bukan exhaustive search dan sengaja tidak melakukan parameter mining besar-besaran.
- Regulatory interpretation memerlukan penasihat bertauliah.
- Research sebelum proposal bermakna kita belum memilih provider LLM, deployment topology, atau live exchange credentials.

---

## 3. Binance Futures mechanics yang wajib difahami

## 3.1 Kenapa fokus USDⓈ-M perpetual

USDⓈ-M perpetual ialah linear contract yang quoted dan settled dalam USDT atau USDC.[3] Untuk baseline USD 100, ia lebih mudah untuk:

- mengukur PnL dalam unit stablecoin;
- menyatukan risk budget;
- mengelakkan coin-margined collateral yang nilainya sendiri turun ketika market crash;
- membuat accounting fee/funding yang lebih jelas.

Perpetual futures tidak tamat tempoh. Funding membantu mengecilkan jurang perpetual dengan spot/index melalui pembayaran antara long dan short.[25]

### Linear PnL ringkas

Untuk position quantity `Q` unit underlying:

- Long PnL: `Q × (exit_price − entry_price)`
- Short PnL: `Q × (entry_price − exit_price)`
- Notional: `abs(Q × mark_price)`
- Approximate initial margin: `notional / selected_leverage`

**ROE di UI boleh mengelirukan:** leverage mengecilkan margin denominator, jadi ROE nampak besar walaupun perubahan equity sebenar tidak sebesar itu.

## 3.2 Leverage, initial margin dan maintenance margin

Binance menyatakan maximum leverage bergantung pada position notional; position lebih besar mempunyai maximum leverage lebih rendah.[4] Exact tiers mesti diambil daripada leverage-bracket/account endpoint pada runtime, bukan di-hardcode.

Leverage mempunyai dua makna berbeza:

1. **Selected leverage** — setting exchange yang menentukan initial margin.
2. **Effective leverage** — total position notional dibahagi account equity.

Bot selamat mengawal **kedua-duanya**. Menetapkan 20× tetapi hanya membuka notional kecil masih berbeza daripada benar-benar menggunakan 20× effective exposure; namun selected leverage tinggi tetap mengecilkan liquidation buffer dan mengundang sizing error. Untuk USD 100, baseline 2× selected leverage dan ≤1× effective notional adalah jauh lebih masuk akal daripada mengejar maximum leverage.

## 3.3 Cross vs isolated margin

Dalam isolated mode, position mempunyai dedicated margin dan liquidation satu position kurang berpotensi menjangkiti position lain.[5] Cross margin berkongsi balance, yang boleh menangguhkan liquidation satu trade tetapi membenarkan trade buruk memakan baki seluruh account.

**Keputusan research:** isolated margin untuk fasa awal. Cross hanya boleh dinilai kemudian apabila portfolio-level hedging, covariance, dan reconciliation sudah terbukti.

## 3.4 Mark price, index price, last price

Binance menggunakan Mark Price sebagai anggaran fair value yang kurang volatile untuk mengurangkan liquidation tidak perlu dan manipulasi.[6] Liquidation dicetuskan apabila Mark Price mencapai liquidation price.[10]

Bot perlu menyimpan sekurang-kurangnya:

- last/contract price;
- mark price;
- index price;
- entry price;
- liquidation price yang dilaporkan exchange;
- maintenance margin dan margin ratio.

Stop boleh mempunyai trigger semantics berbeza. Strategy specification mesti menyatakan sama ada signal dan protection menggunakan mark atau contract price; jangan biarkan default tersembunyi.

## 3.5 Funding

Binance menerangkan `Funding Amount = Nominal Value of Positions × Funding Rate`, dan funding payment dipindahkan antara pihak long dan short, bukan fee yang disimpan Binance.[7]

Implikasi:

- long membayar apabila funding positif; short menerima;
- short membayar apabila funding negatif; long menerima;
- interval dan cap/floor boleh berubah mengikut symbol/condition;
- funding boleh mengubah strategy gross-positive menjadi net-negative;
- backtest mesti align funding event dengan position yang benar-benar terbuka pada timestamp event.

Funding tidak boleh diandaikan sentiasa setiap lapan jam atau fixed; runtime mesti membaca metadata/current schedule.

## 3.6 Fees, spread dan slippage

Maker/taker fees berubah mengikut VIP level.[8] Endpoint commission-rate rasmi memberikan example BTCUSDT `makerCommissionRate=0.0002` dan `takerCommissionRate=0.0004`, iaitu 0.02% dan 0.04%; bot mesti query rate account sebenar.[24]

Empirical screen menggunakan conservative baseline:

- taker fee: 0.04% setiap fill;
- slippage: 0.02% setiap fill;
- round trip biasa: 0.12% notional;
- reversal long-to-short: exit dan re-entry dikira sebagai dua fills.

Kajian ML Bitcoin menunjukkan gross-positive models boleh gagal selepas kos 10 basis points, dan cost-aware execution filter perlu mengurangkan turnover.[28] Satu lagi walk-forward study mendapati pada andaian cost 0.1%, interval lebih pendek daripada 30 minit gagal mengatasi kos dalam experiment tersebut.[29] Ia bukan universal law, tetapi warning kuat terhadap scalping account kecil.

## 3.7 Filters dan minimum valid order

`MIN_NOTIONAL` menetapkan minimum `price × quantity`; untuk market order, mark price digunakan.[13] Runtime juga perlu mematuhi:

- `PRICE_FILTER` / tick size;
- `LOT_SIZE` dan `MARKET_LOT_SIZE` / step size;
- minimum dan maximum quantity;
- percent-price controls;
- order-count limits;
- symbol status dan contract type.

Live public `exchangeInfo` snapshot pada 6 Ogos 2026 menunjukkan:

| Symbol | MIN_NOTIONAL snapshot |
|---|---:|
| BTCUSDT | 50 USDT |
| ETHUSDT | 20 USDT |
| SOLUSDT | 5 USDT |

Nilai ini datang daripada runtime metadata dan boleh berubah; ia tidak boleh menjadi constant production.[21]

## 3.8 Liquidation, insurance fund dan ADL

Liquidation bukan exit strategy. Ia berlaku terlalu lewat, dikenakan execution uncertainty, dan boleh meninggalkan jauh lebih sedikit equity daripada planned stop.

Futures insurance fund ialah safety net untuk mengurangkan impak bankrupt positions.[12] Jika insurance fund tidak dapat menerima bankrupt position, ADL ialah langkah akhir liquidation process.[11] Maka “stop berada sebelum liquidation” perlu dibuktikan secara numerik pada setiap order, dan bot mesti mempunyai liquidation-distance gate.

## 3.9 Order lifecycle yang betul

Execution engine perlu menganggap order sebagai state machine, bukan satu REST call:

`INTENT → VALIDATED → SUBMITTED → ACKNOWLEDGED/UNKNOWN → PARTIALLY_FILLED → FILLED/CANCELLED/REJECTED → RECONCILED`

Wajib ada:

- unique deterministic `clientOrderId`;
- `reduceOnly`/close semantics untuk protective exit;
- exchange-side stop sebaik sahaja entry fill berlaku;
- partial-fill handling;
- stale-order cancellation;
- position/order reconciliation selepas timeout;
- no blind retry apabila status submission tidak pasti;
- local intent ledger dan exchange truth comparison.

Binance user data stream perlu keepalive; dokumentasi menyatakan stream ditutup selepas 60 minit tanpa keepalive.[17] Rate-limit errors mengarahkan penggunaan WebSocket untuk live updates dan boleh membawa IP ban jika polling berlebihan.[18]

**Safety implication:** HTTP timeout/503 selepas submit bukan lesen untuk menghantar duplicate order. Query by client ID, reconcile position, kemudian tentukan action.

---

## 4. Strategy research: hypothesis, regime, dan failure modes

## 4.1 Trend following / time-series momentum

### Hypothesis

Return yang sehala boleh berterusan kerana slow information diffusion, positioning, forced liquidations, dan behavioural herding.

### Bentuk implementasi

- EMA fast/slow;
- Donchian breakout;
- lookback return sign;
- volatility-adjusted momentum;
- breakout + ATR/trailing exit;
- long/short asymmetry.

Research crypto momentum yang memasukkan realistic assumptions mendapati evidence time-series momentum lebih kuat daripada cross-sectional momentum, tetapi banyak portfolio yang kelihatan significant boleh dilikuidasi atau menjadi economically insignificant selepas real-world considerations.[37]

### Regime sesuai

- persistent directional move;
- volatility expansion selepas compression;
- trend yang mempunyai breadth/volume confirmation;
- funding tidak terlalu menentang exposure.

### Failure modes

- choppy range menghasilkan whipsaw;
- signal lambat selepas V-shaped reversal;
- high turnover apabila lookback terlalu pendek;
- short-side squeeze jauh lebih ganas;
- parameter decay dan symbol dependence;
- correlated positions memberi ilusi diversification.

### Research decision

**Priority tinggi, tetapi bukan static EMA.** Kajian lanjut perlu menguji regime gating, asymmetric long/short rules, volatility targeting, no-trade buffer, dan cost-aware hysteresis.

## 4.2 Breakout / volatility expansion

### Hypothesis

Harga keluar daripada range apabila information/positioning imbalance cukup besar; stop clusters dan liquidation cascade boleh menyambung move.

### Candidate rules

- Donchian high/low menggunakan channel yang di-shift satu bar;
- volatility compression sebelum breakout;
- volume/order-flow confirmation;
- retest entry untuk mengurangkan false break;
- ATR initial stop dan trailing stop.

### Failure modes

- false breakout dan wick;
- masuk selepas move sudah extended;
- slippage bertambah semasa volatility spike;
- same-bar ambiguity dalam OHLC backtest;
- stop yang terlalu rapat dibunuh noise, terlalu jauh melanggar risk budget.

### Research decision

Gabungkan dengan trend family. Untuk USD 100, gunakan timeframe lebih perlahan dan no-trade zones; jangan trade setiap channel break.

## 4.3 Mean reversion

### Hypothesis

Short-term dislocation daripada equilibrium akan kembali apabila liquidity pulih dan tiada regime shift.

### Candidate rules

- Bollinger/z-score reversion;
- distance daripada VWAP/anchored VWAP;
- RSI extreme dengan trend veto;
- residual reversion dalam pair/cointegrated basket;
- order-book imbalance exhaustion.

### Regime sesuai

- bounded range;
- declining/normal volatility;
- tiada news shock;
- stable funding dan basis;
- spread/depth normal.

### Failure modes

- “oversold” terus jatuh dalam trend;
- averaging down menukar reversion menjadi martingale;
- equilibrium berubah selepas structural break;
- altcoin liquidity hilang;
- backtest close-price fill terlalu optimistik.

### Research decision

Secondary candidate sahaja. Entry perlu mempunyai trend/volatility veto, hard stop, maximum hold time, dan **tiada averaging down**.

## 4.4 Funding-rate and basis strategies

### Variants

1. **Directional funding-aware:** funding menjadi feature/cost, bukan primary signal.
2. **Funding contrarian:** extreme positive funding boleh menyokong short thesis, extreme negative menyokong long.
3. **Delta-neutral carry:** long spot + short perpetual ketika positive funding, atau struktur terbalik apabila feasible.
4. **Cross-exchange funding arbitrage:** exposure offset di venue berlainan.

Research funding arbitrage melaporkan beberapa scenario sangat kuat, termasuk satu leveraged case dengan return tinggi dan max drawdown rendah,[36] tetapi itu tidak bermaksud hasil boleh dipindahkan terus. Risiko tersembunyi termasuk:

- basis divergence;
- funding sign flip;
- two-leg execution mismatch;
- borrow, transfer dan withdrawal constraints;
- venue/counterparty risk;
- liquidation pada derivative leg;
- return besar yang bergantung kepada leverage, coin, venue, dan sample tertentu.

### Research decision

**Bukan strategy pertama untuk USD 100.** Dua legs dan minimum notional memecahkan modal. Funding perlu digunakan dahulu sebagai cost/veto feature; delta-neutral carry dikaji semula selepas modal dan execution maturity meningkat.

## 4.5 Cross-sectional momentum / rotation

Rank assets berdasarkan momentum dan long top/short bottom boleh mengurangkan market beta secara teori. Tetapi evidence crypto cross-sectional lebih lemah daripada time-series dalam research yang sama.[37]

Failure modes:

- survivorship bias;
- listing/delisting bias;
- liquidity bias;
- universe reconstitution leakage;
- correlated crash;
- banyak legs, fee dan minimum notional.

**Decision:** defer untuk USD 100.

## 4.6 Pairs trading / statistical arbitrage

### Hypothesis

Spread antara related assets mempunyai stable equilibrium dan akan mean-revert.

### Wajib diuji

- point-in-time cointegration, bukan full-sample;
- hedge ratio yang dilatih rolling;
- half-life dan maximum holding time;
- residual stationarity selepas costs;
- legging risk dan correlation break.

### Failure modes

- relationship pecah selepas token-specific event;
- kedua-dua legs rugi kerana hedge ratio salah;
- satu leg minimum order memaksa oversizing;
- hidden market beta;
- delisting/contract suspension.

**Decision:** academically menarik, operationally tidak sesuai sebagai first USD 100 strategy.

## 4.7 Market making

Market maker cuba menang spread sambil mengawal inventory. Real requirement termasuk:

- low-latency book maintenance;
- queue position model;
- cancel/replace discipline;
- adverse-selection predictor;
- inventory skew;
- self-trade prevention;
- disconnect fail-safe.

Liquidity dan order-book variation secara langsung mempengaruhi trading cost/profit.[31] Walaupun microstructure features seperti order-flow imbalance, spread dan depth boleh meramal short-horizon behaviour,[32] alpha tersebut boleh lenyap selepas latency dan execution.

**Decision:** reject untuk fasa awal retail USD 100.

## 4.8 Order-flow / liquidation-event strategies

Potential features:

- bid/ask depth imbalance;
- aggressive buy/sell flow;
- CVD;
- open-interest change;
- liquidation bursts;
- spread/depth deterioration;
- mark-index basis.

Gunakan sebagai **confirmation atau veto**, bukan standalone HFT strategy. Data perlu disimpan event-time, sequence-consistent, dan gap-aware.

## 4.9 News, sentiment dan LLM interpretation

LLM memang berguna untuk unstructured text, tetapi output perlu mempunyai:

- source provenance;
- publication/event timestamp;
- duplicate-story detection;
- entity resolution;
- freshness limit;
- confidence calibration;
- prompt-injection sanitization.

OWASP menyatakan prompt injection boleh mengubah behaviour/output LLM secara tidak diingini dan boleh mempengaruhi critical decisions.[43] External news/social content ialah untrusted data, bukan instruction. LLM sentiment paling sesuai menjadi risk veto atau feature berweight kecil, bukan direct BUY/SELL authority.

## 4.10 Supervised ML, deep learning dan RL

### Potential targets

- future return distribution;
- probability move melebihi round-trip cost;
- volatility/liquidity forecast;
- regime probability;
- stop/holding-time hazard;
- expected slippage.

### Common traps

- optimizing accuracy bukan net expectancy;
- overlapping labels;
- leakage daripada scaler/feature selection;
- random train/test split;
- class imbalance;
- feature availability mismatch;
- transaction cost omitted;
- model retraining terlalu kerap;
- RL exploiting simulator bug.

**Decision:** ML perlu meramal component yang terukur. Jangan meminta model “predict next candle” lalu terus trade setiap sign.

## 4.11 Grid, DCA dan martingale

Grid boleh mendapat banyak small wins dalam range tetapi mengumpul inventory melawan trend. Martingale menambah size selepas loss dan mempunyai negative convexity.

**Hard rejection rules:**

- tiada loss-recovery multiplier;
- tiada unlimited averaging down;
- tiada widening stop untuk mengelak realized loss;
- tiada strategy yang bergantung kepada “harga akhirnya mesti kembali.”

## 4.12 Multi-strategy portfolio

Portfolio yang matang mungkin mempunyai:

- trend sleeve;
- range-reversion sleeve;
- funding/carry sleeve;
- event-risk veto;
- portfolio risk allocator.

Tetapi signals berbeza tidak semestinya risks berbeza. Portfolio layer mesti mengukur:

- rolling correlation dan tail correlation;
- shared BTC beta;
- long/short net exposure;
- gross notional;
- liquidity concentration;
- strategy contribution to drawdown;
- funding and cost budget;
- marginal expected shortfall.

Dengan USD 100, practical implementation bermula dengan **winner-takes-eligibility, bukan simultaneous allocation**: hanya satu approved strategy-position pada satu masa. Ini mengelakkan minimum-notional dan correlation problems sambil mengumpul clean evidence.

---

## 5. Empirical family screen: apa yang kita buat dan apa yang ia buktikan

## 5.1 Dataset dan protocol — archived 1h benchmark

- Public Binance USDⓈ-M 1h klines + realized funding; superseded by the 5m/15m replacement screen in Section 1.4.1.
- BTCUSDT, ETHUSDT, SOLUSDT.
- 2023-01-01 hingga snapshot 2026-08-06.
- Train/selection: 2023–2024.
- Frozen validation: 2025.
- Frozen test: 2026 YTD.
- Signal pada bar close, execution pada next bar open.
- 1× total portfolio notional untuk comparability.
- Equal-weight theoretical three-symbol portfolio.
- 0.04% taker + 0.02% slippage setiap fill.
- Funding aligned kepada timestamp position.
- Tiada stop-loss overlay atau parameter retuning dalam OOS.

Portfolio tiga pair ini ialah robustness screen, **bukan executable sizing plan USD 100**, kerana equal allocation boleh melanggar minimum notional BTC.

## 5.2 Frozen parameters dan results

| Family | Frozen parameters | 2025 return | 2025 Sharpe | 2025 DD | 2026 YTD return | 2026 Sharpe | 2026 DD |
|---|---|---:|---:|---:|---:|---:|---:|
| Bollinger reversion | period 96, z 2.0 | +4.82% | 0.33 | -37.15% | -10.31% | -0.23 | -38.95% |
| Donchian breakout | entry 168, exit 72 | -32.06% | -0.57 | -40.74% | -0.51% | 0.19 | -43.53% |
| EMA trend | fast 24, slow 120 | -63.73% | -1.52 | -69.47% | -3.82% | 0.11 | -43.95% |
| Regime hybrid | EMA 48/240, ADX 25/18, BB 48/2 | -5.84% | 0.11 | -30.06% | +5.17% | 0.41 | -33.69% |
| RSI reversion | RSI 14, 20/80 | -28.05% | -1.47 | -32.33% | -6.95% | -0.45 | -17.34% |

### Cost drag examples

- Regime hybrid 2025: additive cost drag sekitar 22.1 percentage points.
- EMA trend 2025: sekitar 13.5 points.
- Bollinger 2025: sekitar 10.6 points.

Ini menunjukkan win rate/gross signal sahaja tidak cukup; turnover ialah design variable.

## 5.3 Interpretation

1. **Regime instability:** family yang positif pada satu window bertukar negatif pada window lain.
2. **Symbol instability:** result portfolio boleh disokong satu symbol sahaja; contoh regime hybrid 2025 mendapat SOL positif sedangkan BTC dan ETH negatif.
3. **Volatility drag:** positive arithmetic Sharpe tidak semestinya memberi positive compounded return.
4. **Cost sensitivity:** high-turnover hybrid membayar drag besar.
5. **No production candidate:** drawdown 17%–69% jauh melebihi envelope USD 100.

Backtest overfitting literature memberi amaran bahawa calibration mudah memilih historical noise, dan standard hold-out boleh tidak mencukupi apabila banyak trials dicuba.[33] Deflated Sharpe Ratio secara khusus membetulkan selection bias, overfitting dan non-normality.[34]

## 5.4 Apa yang perlu dibuat dalam research iteration seterusnya

Bukan menambah 1,000 indicator. Sebaliknya:

- trial registry untuk setiap hypothesis/parameter;
- parameter stability surfaces;
- long dan short dianalisis berasingan;
- no-trade buffer/hysteresis;
- volatility-targeted sizing;
- asymmetric stops;
- market-impact and latency stress;
- walk-forward across multiple regimes;
- paired bootstrap confidence intervals;
- PBO/DSR;
- attribution per symbol, regime, side, dan cost component.

---

## 6. Money and risk management untuk USD 100

## 6.1 Position sizing formula

Gunakan loss budget, bukan leverage target:

`risk_usd = equity × risk_fraction`

`notional ≈ risk_usd / (stop_fraction + round_trip_cost_fraction + gap_buffer_fraction)`

`quantity_raw = notional / entry_price`

Kemudian:

1. round quantity turun mengikut step size;
2. recompute notional dan worst-case loss;
3. verify minimum notional;
4. verify margin dan liquidation distance;
5. jika tidak feasible, skip.

## 6.2 Baseline calculation

Dengan equity USD 100 dan conservative round-trip fee+slippage 0.12%:

| Risk | Stop distance | Risk-sized notional | Margin @ 2× |
|---:|---:|---:|---:|
| 0.50% | 0.5% | $80.65 | $40.32 |
| 0.50% | 1.0% | $44.64 | $22.32 |
| 0.50% | 2.0% | $23.58 | $11.79 |
| 0.75% | 0.5% | $120.97 | $60.48 |
| 0.75% | 1.0% | $66.96 | $33.48 |
| 0.75% | 2.0% | $35.38 | $17.69 |
| 1.00% | 0.5% | $161.29 | $80.65 |
| 1.00% | 1.0% | $89.29 | $44.64 |
| 1.00% | 2.0% | $47.17 | $23.58 |

Notional melebihi equity dalam table tidak semestinya dibenarkan oleh portfolio cap. Contoh risk 0.75%, stop 0.5% mencadangkan $120.97, tetapi ≤1× effective-notional gate mengecilkannya kepada maksimum $100.

## 6.3 Minimum-notional distortion

At live snapshot minima:

| Symbol | Min notional | Estimated loss @ 0.5% stop | @ 1.0% stop | @ 2.0% stop |
|---|---:|---:|---:|---:|
| BTCUSDT | $50 | $0.31 | $0.56 | $1.06 |
| ETHUSDT | $20 | $0.12 | $0.22 | $0.42 |
| SOLUSDT | $5 | $0.03 | $0.06 | $0.11 |

BTC dengan 2% stop pada minimum order sudah melebihi 1% account risk selepas cost assumption. Bot mesti skip atau memilih symbol/setup lain—bukan mengecilkan stop secara artificial.

## 6.4 Losing-streak mathematics

Fixed-fraction drawdown selepas consecutive full-R losses:

| Risk/trade | 5 losses | 10 losses | 20 losses | 30 losses |
|---:|---:|---:|---:|---:|
| 0.50% | 2.48% | 4.89% | 9.54% | 13.96% |
| 0.75% | 3.69% | 7.25% | 13.98% | 20.22% |
| 1.00% | 4.90% | 9.56% | 18.21% | 26.03% |
| 2.00% | 9.61% | 18.29% | 33.24% | 45.45% |

Selepas 30% drawdown, account memerlukan 42.86% gain untuk pulih; selepas 50%, ia memerlukan 100%. Ini sebab 2% risk terlalu agresif untuk experimental USD 100 bot.

## 6.5 Expectancy selepas cost

`Expectancy = p(win) × avg_win_R − p(loss) × avg_loss_R − average_cost_R`

Jika average win 1.5R dan average loss 1R:

- tanpa cost, break-even win rate = 40%;
- jika total cost = 0.12R, break-even menjadi 44.8%;
- jika cost = 0.20R, break-even menjadi 48%.

Maka bot mesti mempunyai **minimum predicted edge over cost**, bukan trade kerana probability naik sedikit melebihi 50%.

## 6.6 Deterministic risk controls

### Pre-trade

- symbol status active;
- data fresh dan clock synchronized;
- spread/slippage bawah threshold;
- actual commission loaded;
- funding event risk checked;
- quantity precision valid;
- min notional valid;
- stop exists dan jauh sebelum liquidation;
- per-trade, daily, gross, net, correlation limits valid;
- no duplicate intent/client ID;
- model/candidate version approved.

### In-trade

- exchange-side protective stop;
- reduce-only exit;
- maximum holding time;
- stale-data freeze;
- websocket disconnect policy;
- margin ratio/liquidation distance monitor;
- partial-fill and orphan-order detection.

### Account-level

- max one position per pair;
- max one concurrent position initially;
- 5% DD throttle;
- 8% halt;
- 10% kill;
- no new entries after reconciliation mismatch;
- manual emergency flatten path.

---

## 7. Architecture boundary untuk complete-autonomous LLM

## 7.1 Definisi autonomy yang selamat

“Complete autonomous” patut bermaksud sistem boleh menjalankan seluruh learning loop tanpa menunggu prompt manusia—**bukan** LLM bebas mengubah safety constraints.

NIST GenAI profile menekankan risk management untuk unique generative-AI risks,[45] termasuk confabulation: content salah yang dinyatakan dengan yakin.[46] Dalam trading, satu hallucinated price, symbol, leverage atau order state boleh menyebabkan loss sebenar.

## 7.2 Layered architecture

```text
UNTRUSTED WORLD
  market data | news | social | exchange events
           |
           v
[1] DATA PLANE
  validation, timestamps, schema, gap detection, provenance
           |
           v
[2] FEATURE / REGIME PLANE (deterministic)
  causal features, costs, liquidity, funding, regime probabilities
           |
           v
[3] LLM RESEARCH LAB (no secrets, no order tools)
  Hypothesis Generator
  Strategy Spec Writer
  Red-Team Critic
  Failure Analyst
  Post-Trade Reviewer
           |
           v
[4] SANDBOX VERIFIER (network disabled)
  compile strategy DSL -> tests -> backtest -> walk-forward -> stress
           |
           v
[5] PROMOTION GATE
  trial-aware statistics, human policy constraints, signed manifest
           |
           v
[6] DETERMINISTIC RUNTIME
  signal evaluator -> risk engine -> order manager -> exchange adapter
           |
           v
[7] RECONCILIATION / AUDIT / KILL SWITCH
  exchange truth, append-only events, alerts, rollback, quarantine
```

Multi-agent research frameworks boleh membahagi peranan analyst, bull/bear debate, trader dan risk manager,[40] manakala verifier-guided self-evolution menunjukkan pattern LLM mencadangkan perubahan kemudian verifier menilai robustness/walk-forward.[42] Kita boleh mengambil **architecture pattern**, bukan menerima performance claim tanpa independent reproduction.

## 7.3 Apa yang LLM dibenarkan buat

- cadangkan hypothesis dalam typed schema;
- pilih daripada approved feature catalog;
- menulis strategy DSL, bukan arbitrary production Python;
- menerangkan economic rationale dan expected regime;
- mencadangkan ablation dan falsification test;
- menganalisis failures dan trade attribution;
- propose candidate retirement/throttle;
- summarize evidence dengan provenance.

## 7.4 Apa yang LLM dilarang buat

- access API secret;
- call order endpoint;
- set leverage atau quantity secara langsung;
- edit risk constants/kill switch;
- approve candidate yang ia sendiri cipta;
- membaca untrusted text sebagai system instruction;
- install package atau melakukan network call dalam verifier;
- overwrite trial history;
- bypass failed gate;
- retry unknown-status order.

## 7.5 Strategy DSL / typed intent

LLM output mesti seperti specification, bukan prose bebas:

```yaml
strategy_family: trend_breakout
universe: [BTCUSDT]
timeframe: 5m
regime_context_timeframe: 15m
features:
  donchian_entry: {lookback: 2016, shifted: 1}
  adx: {period: 168}
entry:
  long: close > donchian_high and adx > 25
exit:
  channel_lookback: 864
risk_request:
  stop_model: atr
  stop_multiple: 2.0
  max_hold_bars: 2880
expected_regime: directional_expansion
invalidating_conditions:
  - stale_data
  - spread_above_limit
  - funding_cost_above_edge_budget
```

Compiler deterministik menolak unknown field, lookahead reference, unavailable feature, atau unsafe action.

## 7.6 Autonomous lifecycle

```text
DISCOVER
  -> SPECIFY
  -> STATIC CHECK
  -> SANDBOX TEST
  -> HISTORICAL VALIDATION
  -> PAPER CANDIDATE
  -> SHADOW OBSERVATION
  -> ELIGIBLE
  -> ACTIVE WITH SMALL RISK
  -> THROTTLED / QUARANTINED / RETIRED
```

Tiada direct jump daripada “idea” ke “active”. Setiap transition mempunyai machine-verifiable evidence bundle.

## 7.7 Learning cadence

- **Fast loop:** market/state update dan deterministic risk, tanpa LLM.
- **Trade loop:** approved strategy signals; LLM optional explanation, bukan dependency.
- **Daily loop:** attribution, data quality, drift alerts.
- **Weekly loop:** LLM research dan candidate generation.
- **Monthly/after sufficient evidence:** promotion/retirement review.

Ini mengelakkan model berubah semasa trade dan memutuskan reproducibility.

---

## 8. Validation protocol sebelum sesuatu strategy boleh aktif

## 8.1 Causal data contract

Setiap feature mempunyai:

- observation timestamp;
- availability timestamp;
- source;
- revision policy;
- missing-data policy;
- exact execution delay.

Bar-close signal mesti execute pada next feasible timestamp. Funding, open interest, liquidation dan news tidak boleh muncul sebelum event sebenarnya diketahui.

## 8.2 Split protocol

- untouched final test;
- rolling walk-forward;
- purge/embargo untuk overlapping labels;
- parameter selection hanya dalam training window;
- frozen evaluation;
- multiple symbols/regimes;
- long/short attribution.

## 8.3 Trial accounting

Log setiap:

- strategy variant;
- parameter set;
- feature set;
- dataset version;
- random seed;
- cost assumption;
- result, termasuk failed experiments.

Kemudian gunakan PBO/DSR atau equivalent trial-aware correction. Jangan memadam bad trials dan melaporkan hanya winner.[33][34]

## 8.4 Stress tests

Minimum scenarios:

- fee 1×, 1.5×, 2×;
- slippage by volatility/liquidity bucket;
- next-bar delay tambahan;
- random missed fills;
- partial fills;
- spread shock;
- funding sign/cap change;
- websocket disconnect;
- REST timeout with unknown status;
- mark-price gap;
- symbol filter change;
- delisting/suspension;
- correlated crash;
- exchange maintenance.

## 8.5 Provisional promotion gates

Calon tidak boleh dipromosikan kecuali:

1. positive net expectancy selepas realistic cost dan 2× stress;
2. positive result tidak bergantung pada satu pair, satu month atau satu side;
3. parameter neighbourhood stabil;
4. drawdown berada dalam account overlay;
5. no leakage/invariant tests lulus;
6. reproducible daripada immutable data + manifest;
7. paper/shadow evidence meliputi cukup masa dan trade diversity;
8. reconciliation, partial-fill dan kill-switch drills lulus;
9. legal/venue eligibility telah disahkan.

Gate akhir tidak boleh menggunakan backtest Sharpe sahaja.

---

## 9. Regulatory, operational dan security risks

## 9.1 Malaysia/Binance

Facts semasa research:

- Enforcement action SC terhadap Binance berlaku pada 2021.[19]
- Revised DAX guidelines diumumkan pada Mei 2026.[48]
- Current registered DAX list updated 20 Julai 2026 tidak menunjukkan Binance.[49]
- Digital asset activities di Malaysia berada dalam regulatory perimeter SC.[50]

Before-live checklist:

- obtain qualified legal/compliance confirmation;
- review Binance terms dan user eligibility pada masa deployment;
- jangan bypass geofence/KYC/product restriction;
- jangan deposit USD 100 ke futures account sehingga venue clearance selesai;
- design exchange adapter supaya research boleh dipindah kepada venue yang dibenarkan.

## 9.2 Secret and permission design

Jika/selepas venue dibenarkan:

- separate read-only dan trading keys;
- withdrawals disabled;
- IP allowlist;
- secrets di OS/Vault, tidak masuk prompt/log;
- minimum permission;
- key rotation dan revocation drill;
- separate paper/test/live environments;
- live enablement memerlukan explicit manual ceremony.

## 9.3 Prompt injection dan untrusted data

News, social posts, webpages, strategy text, exchange symbols dan even model-generated memory ialah data. Mereka tidak boleh memberi instructions kepada agent. OWASP menyatakan RAG/fine-tuning tidak menghapuskan prompt-injection risk sepenuhnya.[43]

## 9.4 Operational truth

Source of truth untuk position/order ialah exchange reconciliation, bukan LLM memory dan bukan local assumption. Sistem mesti fail closed apabila:

- order state unknown;
- position mismatch;
- market data stale;
- clock skew;
- risk service unavailable;
- account balance berubah di luar expected ledger.

---

## 10. Feasibility verdict sebelum proposal

### 10.1 Apa yang feasible

- autonomous hypothesis generation dan critique;
- strategy specification dalam constrained DSL;
- offline verifier dan self-evolution pipeline;
- causal multi-regime research;
- deterministic paper execution;
- risk-controlled live execution **jika** legal/venue eligibility disahkan kemudian;
- continuous learning melalui candidate generation, not uncontrolled online parameter mutation.

### 10.2 Apa yang tidak defensible

- janji steady profit daripada USD 100;
- LLM direct trading tanpa guardrails;
- high-frequency scalping dengan OHLCV backtest;
- martingale/grid sebagai income engine;
- pilih strategy hanya kerana Sharpe tertinggi;
- live Binance deployment dari Malaysia tanpa compliance clearance;
- menaikkan leverage untuk mengimbangi modal kecil.

### 10.3 Research verdict

**Proceed kepada proposal architecture hanya selepas user menerima lima prinsip ini:**

1. profit ialah uncertain outcome, bukan requirement yang boleh dijamin;
2. USD 100 ialah evidence capital;
3. LLM autonomous pada research plane, bukan safety plane;
4. paper/shadow evidence dan deterministic gates mendahului live;
5. venue/legal clearance ialah hard prerequisite.

Proposal seterusnya sepatutnya bermula dengan **Research Lab + Paper Execution Kernel**, bukan terus “AI live trader.”

---

## 11. Research artifacts dan verification

Folder:

`C:\Users\thaqi\Projects\Autonomous Futures Bot\research`

| Artifact | Purpose |
|---|---|
| `collect_binance_public.py` | Public GET-only data snapshot; tiada auth/order endpoint |
| `strategy_screen.py` | Offline causal strategy-family screen |
| `test_strategy_screen.py` | Causality, cost, cache dan result invariant tests |
| `strategy_screen_results.json` | Full machine-readable results |
| `simple_family_screen.md` | Generated result summary |
| `evidence/` | Retrieved evidence text untuk citation audit |

Verification sebenar:

```text
python -m pytest -q test_strategy_screen.py
....                                                                     [100%]
4 passed in 0.51s
```

---

## Sources

[3] https://www.binance.com/en/support/faq/detail/360033161972
[4] https://www.binance.com/en/support/faq/detail/360033162192
[5] https://www.binance.com/en/support/faq/detail/7e5f04b86f124776bb1c784973769ade
[6] https://www.binance.com/en/support/faq/detail/360033525071
[7] https://www.binance.com/en/support/faq/detail/360033525031
[8] https://www.binance.com/en/support/faq/detail/360033544231
[10] https://www.binance.com/en/support/faq/detail/360033525271
[11] https://www.binance.com/en/support/faq/detail/360033525471
[12] https://www.binance.com/en/support/faq/detail/360033525371
[13] https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition
[17] https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams
[18] https://developers.binance.com/docs/derivatives/usds-margined-futures/error-code
[19] https://www.sc.com.my/resources/media/media-release/sc-takes-enforcement-actions-on-binance-for-illegally-operating-in-malaysia
[21] https://fapi.binance.com/fapi/v1/exchangeInfo
[24] https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/User-Commission-Rate
[25] https://arxiv.org/html/2212.06888v5
[28] https://arxiv.org/html/2606.00060v1
[29] https://arxiv.org/html/2602.10785v1
[31] https://www.mdpi.com/1911-8074/18/3/124
[32] https://arxiv.org/html/2602.00776v1
[33] https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf
[34] https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
[36] https://www.sciencedirect.com/science/article/pii/S2096720925000818
[37] https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/Time_Series_and_Cross_Sectional_Momentum_in_the_Cryptocurrency_Market_with_IA.pdf
[38] https://arxiv.org/html/2605.19337v1
[40] https://arxiv.org/html/2412.20138v3
[42] https://arxiv.org/html/2607.12455v1
[43] https://genai.owasp.org/llmrisk/llm01-prompt-injection
[45] https://www.nist.gov/itl/ai-risk-management-framework
[46] https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf
[48] https://www.sc.com.my/resources/media/media-release/sc-issues-revised-guidelines-on-recognized-markets-for-digital-asset-exchange
[49] https://www.sc.com.my/regulation/guidelines/recognizedmarkets/list-of-registered-digital-asset-exchanges
[50] https://www.sc.com.my/digital-assets
