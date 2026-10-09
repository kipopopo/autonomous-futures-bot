import {
  Activity,
  AlertTriangle,
  Clock,
  Compass,
  Flame,
  Percent,
  ShieldCheck,
  TrendingUp,
  Zap,
} from 'lucide-react'
import type { BtcMacroTrend, HawkesHazard, ScalperCriteria } from './types'

export interface StrategyConfluenceRadarProps {
  btcMacroTrend: BtcMacroTrend
  scalperCriteria: ScalperCriteria
  hawkesHazard: HawkesHazard
}

export function StrategyConfluenceRadar({
  btcMacroTrend,
  scalperCriteria,
  hawkesHazard,
}: StrategyConfluenceRadarProps) {
  const isBtcBullish = btcMacroTrend.regime === 'BULLISH ALIGNED'
  const isHawkesSafe = hawkesHazard.isNonToxic && hawkesHazard.spectralRadius < 1.0

  // Generate SVG points for sparkline from recentHistory
  const history = hawkesHazard.recentHistory && hawkesHazard.recentHistory.length > 0
    ? hawkesHazard.recentHistory
    : [0.35, 0.38, 0.42, 0.41, 0.45, 0.43, 0.40, 0.4286]

  const maxVal = Math.max(1.1, ...history)
  const minVal = Math.min(0.2, ...history)
  const svgWidth = 240
  const svgHeight = 45

  const points = history
    .map((val, idx) => {
      const x = (idx / (history.length - 1 || 1)) * svgWidth
      const y = svgHeight - ((val - minVal) / (maxVal - minVal || 1)) * svgHeight
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  return (
    <div className="glass-panel rounded-2xl p-5 mb-6 relative overflow-hidden">
      {/* Top Ambient Highlight */}
      <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-purple-500/30 to-transparent" />

      {/* Title Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-white/[0.06] mb-5">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-purple-500/10 border border-purple-500/20 text-purple-400 shadow-[0_0_12px_rgba(168,85,247,0.15)]">
            <Compass className="w-5 h-5 text-purple-400 animate-spin-slow" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base sm:text-lg font-bold tracking-tight text-white">
                Radar Konfluens Strategi &amp; Skalper 15m
              </h2>
              <span className="text-[11px] font-mono font-semibold py-0.5 px-2 rounded-md bg-purple-500/10 border border-purple-500/25 text-purple-300">
                Sistem Keputusan
              </span>
            </div>
            <p className="text-xs text-zinc-400">
              Penapis aliran makro Bitcoin, senarai semak pencetus jatuhan kecairan 15m, dan tolok bahaya Hawkes
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span
            className={`badge badge-sm font-mono font-semibold py-1 px-3 ${
              isBtcBullish && isHawkesSafe
                ? 'badge-success bg-emerald-500/15 border-emerald-500/30 text-emerald-400 shadow-[0_0_12px_rgba(16,185,129,0.15)]'
                : 'badge-warning bg-amber-500/15 border-amber-500/30 text-amber-400'
            }`}
          >
            {isBtcBullish && isHawkesSafe
              ? '✅ AUTORISASI BELIAN AKTIF'
              : '⚠️ KELULUSAN DITAHAN'}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Panel 1: BTC Macro Trend Filter */}
        <div className="glass-card-subtle rounded-xl p-4 flex flex-col justify-between hover:border-purple-500/30 transition-all duration-300">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
                <TrendingUp className="w-4 h-4 text-amber-400" />
                Penapis Trend Makro BTC
              </span>
              <span
                className={`inline-flex items-center gap-1 text-xs font-mono font-bold py-0.5 px-2.5 rounded-lg border ${
                  isBtcBullish
                    ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400'
                    : 'bg-rose-500/15 border-rose-500/30 text-rose-400'
                }`}
              >
                {btcMacroTrend.regime}
              </span>
            </div>

            <p className="text-xs text-zinc-400 mb-4 leading-relaxed">
              {btcMacroTrend.explanation}
            </p>

            <div className="space-y-2 text-xs font-mono">
              <div className="p-2.5 rounded-lg bg-black/25 border border-white/[0.06] flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5 text-cyan-400" />
                  <span className="text-zinc-300">BTC 1-Jam (1h):</span>
                </div>
                <div className="flex items-center gap-2 font-semibold">
                  <span className="text-emerald-400">
                    {`EMA50: $${btcMacroTrend.ema50_1h.toLocaleString()}`}
                  </span>
                  <span className="text-zinc-600">&gt;</span>
                  <span className="text-zinc-400">
                    {`EMA200: $${btcMacroTrend.ema200_1h.toLocaleString()}`}
                  </span>
                </div>
              </div>

              <div className="p-2.5 rounded-lg bg-black/25 border border-white/[0.06] flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5 text-cyan-400" />
                  <span className="text-zinc-300">BTC 4-Jam (4h):</span>
                </div>
                <div className="flex items-center gap-2 font-semibold">
                  <span className="text-emerald-400">
                    {`EMA50: $${btcMacroTrend.ema50_4h.toLocaleString()}`}
                  </span>
                  <span className="text-zinc-600">&gt;</span>
                  <span className="text-zinc-400">
                    {`EMA200: $${btcMacroTrend.ema200_4h.toLocaleString()}`}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-white/[0.06] flex items-center justify-between text-[11px] text-zinc-500 font-mono">
            <span>Perlindungan Aliran:</span>
            <span className="text-emerald-400 font-semibold flex items-center gap-1">
              <ShieldCheck className="w-3.5 h-3.5" />
              Kedudukan Belian Sahaja (Long Only)
            </span>
          </div>
        </div>

        {/* Panel 2: 15m Scalper Criteria Checklist */}
        <div className="glass-card-subtle rounded-xl p-4 flex flex-col justify-between hover:border-cyan-500/30 transition-all duration-300">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
                <Zap className="w-4 h-4 text-cyan-400" />
                Senarai Semak Skalper 15m
              </span>
              <span className="text-[11px] font-mono font-semibold py-0.5 px-2 rounded-md bg-cyan-500/10 border border-cyan-500/25 text-cyan-300">
                Sapu Kecairan
              </span>
            </div>

            <div className="space-y-2 text-xs font-mono">
              {/* Criterion 1: Price below 20 EMA */}
              <div className="p-2.5 rounded-lg bg-black/25 border border-white/[0.06] flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      scalperCriteria.priceTriggered ? 'bg-emerald-400 animate-ping' : 'bg-cyan-400'
                    }`}
                  />
                  <span className="text-zinc-300">Jarak Harga Bawah 20 EMA:</span>
                </div>
                <div className="flex items-center gap-1.5 font-bold">
                  <span className={scalperCriteria.priceTriggered ? 'text-emerald-400' : 'text-zinc-200'}>
                    {`${scalperCriteria.priceBelowEma20Atr.toFixed(1)}x ATR`}
                  </span>
                  <span className="text-zinc-500 font-normal">
                    {`(&gt; ${scalperCriteria.priceBelowEmaThreshold}x)`}
                  </span>
                </div>
              </div>

              {/* Criterion 2: Relative Volume */}
              <div className="p-2.5 rounded-lg bg-black/25 border border-white/[0.06] flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      scalperCriteria.volumeTriggered ? 'bg-emerald-400 animate-ping' : 'bg-cyan-400'
                    }`}
                  />
                  <span className="text-zinc-300">Volum Relatif (Lonjakan):</span>
                </div>
                <div className="flex items-center gap-1.5 font-bold">
                  <span className={scalperCriteria.volumeTriggered ? 'text-emerald-400' : 'text-zinc-200'}>
                    {`${scalperCriteria.relativeVolume.toFixed(1)}x SMA`}
                  </span>
                  <span className="text-zinc-500 font-normal">
                    {`(&gt; ${scalperCriteria.volumeThreshold}x)`}
                  </span>
                </div>
              </div>

              {/* Criterion 3: RSI 14 Oversold */}
              <div className="p-2.5 rounded-lg bg-black/25 border border-white/[0.06] flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      scalperCriteria.rsiTriggered ? 'bg-emerald-400 animate-ping' : 'bg-cyan-400'
                    }`}
                  />
                  <span className="text-zinc-300">RSI (14-Tempoh) Terlebih Jual:</span>
                </div>
                <div className="flex items-center gap-1.5 font-bold">
                  <span className={scalperCriteria.rsiTriggered ? 'text-emerald-400' : 'text-zinc-200'}>
                    {scalperCriteria.rsi14.toFixed(1)}
                  </span>
                  <span className="text-zinc-500 font-normal">
                    {`(&lt; ${scalperCriteria.rsiThreshold})`}
                  </span>
                </div>
              </div>

              {/* Criterion 4: Maker Limit Structuring */}
              <div className="p-2.5 rounded-lg bg-black/25 border border-white/[0.06] flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Percent className="w-3.5 h-3.5 text-amber-400" />
                  <span className="text-zinc-300">Struktur Pesanan Maker:</span>
                </div>
                <span className="text-emerald-400 font-bold">
                  0.02% Yuran (Tiada Taker Drag)
                </span>
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-white/[0.06] flex items-center justify-between text-[11px] text-zinc-500 font-mono">
            <span>Struktur Kurungan:</span>
            <span className="text-cyan-400 font-semibold">
              TP +2.0x ATR · SL -1.2x ATR (R:R 1.66)
            </span>
          </div>
        </div>

        {/* Panel 3: Hawkes Hazard & Microstructure Gauge */}
        <div className="glass-card-subtle rounded-xl p-4 flex flex-col justify-between hover:border-emerald-500/30 transition-all duration-300">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
                <Activity className="w-4 h-4 text-cyan-400" />
                Bahaya Mikrostruktur &amp; Hawkes
              </span>
              <span
                className={`badge badge-sm font-mono font-bold py-0.5 px-2.5 ${
                  isHawkesSafe
                    ? 'badge-success bg-emerald-500/15 border-emerald-500/30 text-emerald-400'
                    : 'badge-error bg-rose-500/15 border-rose-500/30 text-rose-400'
                }`}
              >
                {isHawkesSafe ? 'SELAMAT / TIDAK TOKSIK' : 'BAHAYA TOKSIK'}
              </span>
            </div>

            <div className="flex items-baseline justify-between mb-3">
              <div>
                <span className="text-xs text-zinc-400 block font-mono">
                  Radius Spektral (ρ):
                </span>
                <span className="text-2xl font-mono font-bold text-emerald-400 tabular-nums">
                  {`ρ = ${hawkesHazard.spectralRadius.toFixed(4)}`}
                </span>
              </div>
              <span className="text-xs font-mono text-zinc-500">
                Siling Selamat &lt; 1.000
              </span>
            </div>

            {/* Sparkline SVG Chart */}
            <div className="p-3 rounded-lg bg-black/30 border border-white/[0.06] mb-2 relative overflow-hidden">
              <div className="flex items-center justify-between text-[10px] text-zinc-400 font-mono mb-2">
                <span>Aliran Sejarah ρ (60 saat)</span>
                <span className="text-emerald-400 font-semibold flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  Stabil
                </span>
              </div>
              <svg
                viewBox={`0 0 ${svgWidth} ${svgHeight}`}
                className="w-full h-10 overflow-visible"
              >
                <defs>
                  <linearGradient id="hawkes-glow" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#10b981" stopOpacity="0.3" />
                    <stop offset="100%" stopColor="#10b981" stopOpacity="0.0" />
                  </linearGradient>
                </defs>
                <polyline
                  fill="none"
                  stroke="#10b981"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  points={points}
                />
              </svg>
            </div>
          </div>

          <div className="mt-3 pt-3 border-t border-white/[0.06] flex items-center justify-between text-[11px] text-zinc-400 font-mono">
            <span className="flex items-center gap-1">
              <AlertTriangle className="w-3 h-3 text-amber-400" />
              {`Amaran: ρ ≥ ${hawkesHazard.thresholdWarning.toFixed(2)}`}
            </span>
            <span className="flex items-center gap-1 text-rose-400 font-semibold">
              <Flame className="w-3 h-3" />
              {`Kritikal: ρ ≥ ${hawkesHazard.thresholdCritical.toFixed(2)}`}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
