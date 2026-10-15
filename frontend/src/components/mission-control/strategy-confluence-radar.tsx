import { useState, useMemo } from 'react'
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Compass,
  Flame,
  Layers,
  Percent,
  RefreshCw,
  ShieldCheck,
  Target,
  TrendingUp,
  Zap,
} from 'lucide-react'
import type {
  BtcMacroTrend,
  HawkesHazard,
  ScalperCriteria,
  IctPairSignal,
  IctSignalsResponse,
  IctPdArrayType,
} from './types'
import { ProvenanceBadge } from './provenance-badge'
import { useIctSignals, getFallbackIctSignals } from '../../lib/use-ict-signals'

export interface StrategyConfluenceRadarProps {
  btcMacroTrend?: BtcMacroTrend
  scalperCriteria?: ScalperCriteria
  hawkesHazard?: HawkesHazard
  ictSignals?: IctSignalsResponse | null
  enablePolling?: boolean
}

// 6-step mechanical metadata
export const TWINS_STEPS = [
  { step: 1, key: 'step_1_htf_hit', label: 'Step 1: HTF PDA Hit (4h/1h)', short: 'HTF PDA' },
  { step: 2, key: 'step_2_m5_cisd', label: 'Step 2: M5 CISD Confirmed', short: 'M5 CISD' },
  { step: 3, key: 'step_3_twins_fvg', label: 'Step 3: Twins FVG Validated', short: 'Twins FVG' },
  { step: 4, key: 'step_4_ote_retrace', label: 'Step 4: OTE Retracement (62%-79%)', short: 'OTE Fib' },
  { step: 5, key: 'step_5_m1_cisd', label: 'Step 5: M1 CISD Triggered', short: 'M1 CISD' },
  { step: 6, key: 'step_6_ready', label: 'Step 6: Ready / In Position', short: 'Ready' },
] as const

const DEFAULT_BTC_TREND: BtcMacroTrend = {
  regime: 'BULLISH ALIGNED',
  ema50_1h: 95420,
  ema200_1h: 93810,
  ema50_4h: 94800,
  ema200_4h: 92400,
  explanation: 'Bitcoin 1h & 4h EMA 50 > EMA 200 confirms macro trend bullish alignment.',
}

const DEFAULT_SCALPER: ScalperCriteria = {
  priceBelowEma20Atr: 1.8,
  priceBelowEmaThreshold: 2.5,
  priceTriggered: false,
  relativeVolume: 1.4,
  volumeThreshold: 2.2,
  volumeTriggered: false,
  rsi14: 38.5,
  rsiThreshold: 26.0,
  rsiTriggered: false,
  makerFeePct: 0.02,
}

const DEFAULT_HAWKES: HawkesHazard = {
  spectralRadius: 0.4286,
  isNonToxic: true,
  thresholdWarning: 0.85,
  thresholdCritical: 1.0,
  recentHistory: [0.35, 0.38, 0.42, 0.41, 0.45, 0.43, 0.4, 0.4286],
}

export function StrategyConfluenceRadar({
  btcMacroTrend = DEFAULT_BTC_TREND,
  scalperCriteria = DEFAULT_SCALPER,
  hawkesHazard = DEFAULT_HAWKES,
  ictSignals: propSignals,
  enablePolling = false,
}: StrategyConfluenceRadarProps) {
  // Use live hook when enabled or no prop passed, else use fallback
  const {
    data: hookData,
    latencyMs,
    connectionState,
    refetch,
  } = useIctSignals({
    enabled: enablePolling,
    initialData: propSignals || getFallbackIctSignals(),
  })

  const signalsResponse = propSignals || hookData || getFallbackIctSignals()
  const signals = signalsResponse.signals || {}

  const [selectedPair, setSelectedPair] = useState<string>('ALL')

  const isBtcBullish = btcMacroTrend.regime === 'BULLISH ALIGNED'
  const isHawkesSafe = hawkesHazard.isNonToxic && hawkesHazard.spectralRadius < 1.0

  // Sparkline history points
  const history =
    hawkesHazard.recentHistory && hawkesHazard.recentHistory.length > 0
      ? hawkesHazard.recentHistory
      : [0.35, 0.38, 0.42, 0.41, 0.45, 0.43, 0.4, 0.4286]

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

  const pairList = useMemo(() => Object.values(signals), [signals])

  const filteredPairs = useMemo(() => {
    if (selectedPair === 'ALL') return pairList
    return pairList.filter((p) => p.symbol === selectedPair)
  }, [pairList, selectedPair])

  return (
    <div className="glass-panel rounded-2xl p-5 mb-6 relative overflow-hidden" data-testid="strategy-confluence-radar">
      {/* Top Ambient Highlight */}
      <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-purple-500/30 to-transparent" />

      {/* Top Title Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-white/[0.06] mb-5">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-purple-500/10 border border-purple-500/20 text-purple-400 shadow-[0_0_12px_rgba(168,85,247,0.15)]">
            <Compass className="w-5 h-5 text-purple-400 animate-spin-slow" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-base sm:text-lg font-bold tracking-tight text-white">
                Strategy Confluence Radar &amp; 15m Scalper
              </h2>
              <span className="text-[11px] font-mono font-semibold py-0.5 px-2 rounded-md bg-purple-500/10 border border-purple-500/25 text-purple-300">
                Decision Engine
              </span>
              <span className="text-[11px] font-mono font-semibold py-0.5 px-2 rounded-md bg-cyan-500/10 border border-cyan-500/25 text-cyan-300">
                {`ICT MMXM & Twins (${pairList.length > 0 ? `${pairList.length} Pairs` : '12 Pairs'})`}
              </span>
              <ProvenanceBadge source="DAEMON 24/7" />
            </div>
            <p className="text-xs text-zinc-400">
              Bitcoin macro trend filter, 15m liquidity dip trigger checklist, Hawkes hazard gauge, and multi-timeframe ICT Twins state machine
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <span
            className="inline-flex items-center gap-1.5 text-xs font-mono font-bold py-1 px-3 rounded-lg border bg-cyan-500/10 border-cyan-500/30 text-cyan-300 shadow-[0_0_12px_rgba(6,182,212,0.15)]"
            title="Live polling latency and connection state"
            data-testid="connection-latency-badge"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
            {connectionState === 'STREAMING' ? 'LIVE STREAMING' : `POLLING 5s · ${latencyMs}ms`}
          </span>

          <span
            className={`badge badge-sm font-mono font-semibold py-1 px-3 ${
              isBtcBullish && isHawkesSafe
                ? 'badge-success bg-emerald-500/15 border-emerald-500/30 text-emerald-400 shadow-[0_0_12px_rgba(16,185,129,0.15)]'
                : 'badge-warning bg-amber-500/15 border-amber-500/30 text-amber-400'
            }`}
          >
            {isBtcBullish && isHawkesSafe
              ? '✅ BUY AUTHORIZATION ACTIVE'
              : '⚠️ APPROVAL WITHHELD'}
          </span>

          <button
            onClick={() => refetch()}
            className="btn btn-xs bg-purple-500/10 hover:bg-purple-500/20 text-purple-300 border border-purple-500/30"
            title="Refresh ICT Radar telemetry"
            aria-label="Refresh telemetry"
          >
            <RefreshCw className="w-3 h-3" />
          </button>
        </div>
      </div>

      {/* Section 1: Macro & Microstructure Confluence Checklist (3 Panels for Backward Compatibility) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 mb-6">
        {/* Panel 1: BTC Macro Trend Filter */}
        <div className="glass-card-subtle rounded-xl p-4 flex flex-col justify-between hover:border-purple-500/30 transition-all duration-300">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
                <TrendingUp className="w-4 h-4 text-amber-400" />
                BTC Macro Trend Filter
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
                  <span className="text-zinc-300">BTC 1-Hour (1h):</span>
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
                  <span className="text-zinc-300">BTC 4-Hour (4h):</span>
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
            <span>Trend Protection:</span>
            <span className="text-emerald-400 font-semibold flex items-center gap-1">
              <ShieldCheck className="w-3.5 h-3.5" />
              Long Only Positions
            </span>
          </div>
        </div>

        {/* Panel 2: 15m Scalper Criteria Checklist */}
        <div className="glass-card-subtle rounded-xl p-4 flex flex-col justify-between hover:border-cyan-500/30 transition-all duration-300">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
                <Zap className="w-4 h-4 text-cyan-400" />
                15m Scalper Checklist
              </span>
              <span className="text-[11px] font-mono font-semibold py-0.5 px-2 rounded-md bg-cyan-500/10 border border-cyan-500/25 text-cyan-300">
                Liquidity Sweep
              </span>
            </div>

            <div className="space-y-2 text-xs font-mono">
              <div className="p-2.5 rounded-lg bg-black/25 border border-white/[0.06] flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      scalperCriteria.priceTriggered ? 'bg-emerald-400 animate-ping' : 'bg-cyan-400'
                    }`}
                  />
                  <span className="text-zinc-300">Price Distance Below 20 EMA:</span>
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

              <div className="p-2.5 rounded-lg bg-black/25 border border-white/[0.06] flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      scalperCriteria.volumeTriggered ? 'bg-emerald-400 animate-ping' : 'bg-cyan-400'
                    }`}
                  />
                  <span className="text-zinc-300">Relative Volume (Surge):</span>
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

              <div className="p-2.5 rounded-lg bg-black/25 border border-white/[0.06] flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      scalperCriteria.rsiTriggered ? 'bg-emerald-400 animate-ping' : 'bg-cyan-400'
                    }`}
                  />
                  <span className="text-zinc-300">RSI (14-Period) Oversold:</span>
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

              <div className="p-2.5 rounded-lg bg-black/25 border border-white/[0.06] flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Percent className="w-3.5 h-3.5 text-amber-400" />
                  <span className="text-zinc-300">Maker Order Structure:</span>
                </div>
                <span className="text-emerald-400 font-bold">
                  0.02% Fee (Zero Taker Drag)
                </span>
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-white/[0.06] flex items-center justify-between text-[11px] text-zinc-500 font-mono">
            <span>Bracket Structure:</span>
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
                Microstructure &amp; Hawkes Hazard
              </span>
              <span
                className={`badge badge-sm font-mono font-bold py-0.5 px-2.5 ${
                  isHawkesSafe
                    ? 'badge-success bg-emerald-500/15 border-emerald-500/30 text-emerald-400'
                    : 'badge-error bg-rose-500/15 border-rose-500/30 text-rose-400'
                }`}
              >
                {isHawkesSafe ? 'SAFE / NON-TOXIC' : 'TOXIC HAZARD'}
              </span>
            </div>

            <div className="flex items-baseline justify-between mb-2">
              <div>
                <span className="text-xs text-zinc-400 block font-mono">
                  Market Condition:
                </span>
                <span className="text-xl sm:text-2xl font-mono font-bold text-emerald-400 tabular-nums">
                  {isHawkesSafe ? 'Normal & Stable' : 'High Volatility'}
                </span>
              </div>
              <div className="text-right">
                <span className="text-xs font-mono font-bold text-cyan-300 block">
                  {`ρ = ${hawkesHazard.spectralRadius.toFixed(4)}`}
                </span>
                <span className="text-[10px] font-mono text-zinc-500">
                  Safe Ceiling &lt; 1.000
                </span>
              </div>
            </div>

            <p className="text-[11px] text-zinc-400 font-mono mb-3">
              Order flow jump intensity is calm with zero toxic front-running risk.
            </p>

            <div className="p-3 rounded-lg bg-black/30 border border-white/[0.06] mb-2 relative overflow-hidden">
              <div className="flex items-center justify-between text-[10px] text-zinc-400 font-mono mb-2">
                <span>
                  {hawkesHazard.arrivalCount !== undefined && hawkesHazard.arrivalCount > 0
                    ? `Historical ρ Trend (60s) · ${hawkesHazard.arrivalCount.toLocaleString('en-US')} Arrivals (30m)`
                    : 'Historical ρ Trend (60s)'}
                </span>
                <span className="text-emerald-400 font-semibold flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  {hawkesHazard.marketConnected && hawkesHazard.userStreamConnected
                    ? 'Streams Live · Stable'
                    : 'Stable'}
                </span>
              </div>
              <svg viewBox={`0 0 ${svgWidth} ${svgHeight}`} className="w-full h-10 overflow-visible">
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
              {`Warning: ρ ≥ ${hawkesHazard.thresholdWarning.toFixed(2)}`}
            </span>
            <span className="flex items-center gap-1 text-rose-400 font-semibold">
              <Flame className="w-3 h-3" />
              {`Critical: ρ ≥ ${hawkesHazard.thresholdCritical.toFixed(2)}`}
            </span>
          </div>
        </div>
      </div>

      {/* Section 2: ICT MMXM & Twins Reversal 8-Pair Matrix Display */}
      <div className="pt-2">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4 pb-3 border-b border-white/[0.06]">
          <div className="flex items-center gap-2">
            <Target className="w-4 h-4 text-purple-400" />
            <h3 className="text-sm font-bold tracking-tight text-white uppercase font-mono">
              {`ICT Market Maker & Twins Reversal Confluence Matrix (${pairList.length > 0 ? `${pairList.length} Pairs` : '12 Pairs'})`}
            </h3>
            <span className="text-[10px] font-mono font-semibold py-0.5 px-2 rounded bg-purple-500/10 text-purple-300 border border-purple-500/20">
              MMBM / MMSM
            </span>
          </div>

          {/* Quick Filter Selector */}
          <div className="flex items-center gap-1 flex-wrap">
            {['ALL', ...Array.from(new Set(pairList.map((p) => p.symbol)))].map((sym) => (
              <button
                key={sym}
                onClick={() => setSelectedPair(sym)}
                className={`text-[11px] font-mono px-2 py-0.5 rounded transition-colors ${
                  selectedPair === sym
                    ? 'bg-purple-500 text-white font-bold shadow-[0_0_8px_rgba(168,85,247,0.3)]'
                    : 'bg-black/30 text-zinc-400 hover:text-white border border-white/5'
                }`}
              >
                {sym.replace('USDT', '')}
              </button>
            ))}
          </div>
        </div>

        {/* 8-Pair Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4" data-testid="ict-pair-matrix">
          {filteredPairs.map((pair) => (
            <IctPairCard key={pair.symbol} pair={pair} />
          ))}
        </div>
      </div>
    </div>
  )
}

/**
 * Individual Pair Card Component for the 8-Pair Matrix.
 */
export function IctPairCard({ pair }: { pair: IctPairSignal }) {
  const [showScanningDetails, setShowScanningDetails] = useState(false)
  const isLong = pair.side === 'BUY'
  const isShort = pair.side === 'SELL'
  const isInvalidated = pair.step === 'INVALIDATED'
  const isScanning = pair.step_number === 0 && !isInvalidated

  // Health Tier styling
  const healthBadgeStyle =
    pair.candidate.health_tier === 'HEALTHY' || pair.candidate.health_tier === 'ELITE'
      ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400'
      : pair.candidate.health_tier === 'INCUBATING'
        ? 'bg-amber-500/15 border-amber-500/30 text-amber-400'
        : 'bg-rose-500/15 border-rose-500/30 text-rose-400'

  // Format PDA Label
  const pdaLabel = pair.active_pda
    ? formatPdaLabel(pair.active_pda.array_type)
    : 'No Active PDA'

  return (
    <div
      className="glass-card-subtle rounded-xl p-3.5 flex flex-col justify-between border border-white/[0.06] hover:border-purple-500/40 transition-all duration-300 relative overflow-hidden"
      data-testid={`ict-pair-card-${pair.symbol}`}
    >
      {/* Accent corner tint for active ready state */}
      {pair.step === 'STEP_6_READY' && (
        <div className="absolute top-0 right-0 w-16 h-16 bg-emerald-500/10 rounded-bl-full pointer-events-none" />
      )}

      <div>
        {/* Pair Header */}
        <div className="flex items-center justify-between gap-2 mb-2">
          <div className="flex items-center gap-1.5">
            <span className="text-sm font-mono font-bold text-white tracking-wide">
              {pair.symbol}
            </span>
            <span
              className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded border ${
                isLong
                  ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400'
                  : isShort
                    ? 'bg-rose-500/15 border-rose-500/30 text-rose-400'
                    : 'bg-zinc-800 border-white/10 text-zinc-400'
              }`}
            >
              {isLong ? 'LONG BIAS' : isShort ? 'SHORT BIAS' : 'NEUTRAL'}
            </span>
          </div>

          <div className="flex items-center gap-1">
            <span
              className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded border ${healthBadgeStyle}`}
              title={`Candidate Health Tier: ${pair.candidate.health_tier}`}
            >
              {pair.candidate.health_tier}
            </span>
          </div>
        </div>

        {/* Candidate Identifier & Genome Parameters */}
        <div className="flex items-center justify-between text-[10px] font-mono text-zinc-400 mb-2.5 pb-2 border-b border-white/[0.05]">
          <span className="text-purple-300 bg-purple-500/10 px-1 rounded border border-purple-500/20">
            {pair.candidate.candidate_id}
          </span>
          <span>Gen #{pair.candidate.generation}</span>
        </div>

        {/* Active PDA Indicator Badge */}
        <div className="p-2 rounded-lg bg-black/30 border border-white/[0.06] mb-3">
          <div className="flex items-center justify-between text-[11px] font-mono mb-1">
            <span className="text-zinc-400 flex items-center gap-1">
              <Layers className="w-3 h-3 text-cyan-400" />
              Active PD Array:
            </span>
            {pair.active_pda && (
              <span className="text-[10px] font-mono font-bold px-1 rounded bg-cyan-500/10 border border-cyan-500/25 text-cyan-300">
                {pair.active_pda.timeframe}
              </span>
            )}
          </div>

          <div className="flex items-center justify-between gap-1">
            <span
              className={`text-xs font-mono font-bold truncate ${
                pair.active_pda ? 'text-emerald-400' : 'text-zinc-500'
              }`}
            >
              {pdaLabel}
            </span>
            {pair.active_pda && (
              <span className="text-[11px] font-mono text-zinc-300 shrink-0">
                {`$${pair.active_pda.mean_threshold.toLocaleString()} MT`}
              </span>
            )}
          </div>
        </div>

        {/* Step Progression & Execution Targets */}
        {isScanning && !showScanningDetails ? (
          <div className="p-3 rounded-lg bg-black/30 border border-white/[0.06] mb-3 text-center">
            <div className="flex items-center justify-center gap-2 text-xs font-mono text-cyan-300 mb-1">
              <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
              <span className="font-bold">Step 0: Scanning Markets</span>
            </div>
            <p className="text-[10px] font-mono text-zinc-500 mb-2">
              Multi-TF ingress active · Awaiting HTF PD Array setup
            </p>
            <button
              type="button"
              onClick={() => setShowScanningDetails(true)}
              className="text-[10px] font-mono text-zinc-400 hover:text-cyan-300 transition-colors cursor-pointer inline-flex items-center gap-1"
            >
              <span>Show Targets &amp; Genome</span>
              <span>▾</span>
            </button>
          </div>
        ) : (
          <>
            {/* 6-Step Visual Progress Bar & Badges */}
            <div className="mb-3">
              <div className="flex items-center justify-between text-[10px] font-mono text-zinc-400 mb-1.5">
                <span>Twins Reversal Sequence</span>
                <span
                  className={`font-bold ${
                    isInvalidated
                      ? 'text-rose-400'
                      : pair.step === 'STEP_6_READY'
                        ? 'text-emerald-400'
                        : 'text-cyan-300'
                  }`}
                >
                  {isInvalidated
                    ? 'INVALIDATED'
                    : `Step ${pair.step_number} / 6`}
                </span>
              </div>

              {/* 6 Segmented Progress Bars */}
              <div className="grid grid-cols-6 gap-1 mb-2">
                {TWINS_STEPS.map((s) => {
                  const isCompleted = pair.step_number >= s.step
                  const isActive = pair.step_number === s.step

                  return (
                    <div
                      key={s.step}
                      title={`${s.label}: ${isCompleted ? 'CONFIRMED' : 'PENDING'}`}
                      className={`h-2 rounded-sm transition-all duration-300 ${
                        isInvalidated
                          ? 'bg-rose-500/20 border border-rose-500/40'
                          : isActive
                            ? 'bg-cyan-400 shadow-[0_0_8px_rgba(6,182,212,0.6)] animate-pulse'
                            : isCompleted
                              ? 'bg-emerald-500'
                              : 'bg-zinc-800 border border-white/5'
                      }`}
                    />
                  )
                })}
              </div>

              {/* Stepper Status Badge */}
              <div
                className={`p-1.5 rounded-lg text-center text-[10px] font-mono font-bold border ${
                  isInvalidated
                    ? 'bg-rose-500/10 border-rose-500/30 text-rose-400'
                    : pair.step === 'STEP_6_READY'
                      ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400 shadow-[0_0_10px_rgba(16,185,129,0.15)]'
                      : 'bg-black/25 border-white/[0.06] text-zinc-300'
                }`}
              >
                {isInvalidated ? (
                  <span className="flex items-center justify-center gap-1">
                    <AlertTriangle className="w-3 h-3 text-rose-400" />
                    {`Invalidated: ${pair.invalidation_reason}`}
                  </span>
                ) : pair.step === 'STEP_6_READY' ? (
                  <span className="flex items-center justify-center gap-1">
                    <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                    Step 6: Ready / In Position
                  </span>
                ) : (
                  <span>
                    {pair.step_number === 0
                      ? 'Step 0: Scanning Markets'
                      : TWINS_STEPS[pair.step_number - 1]?.label || 'Step 0: Scanning Markets'}
                  </span>
                )}
              </div>
            </div>

            {/* Execution Targets & Risk Sizing Card */}
            <div className="p-2.5 rounded-lg bg-black/35 border border-white/[0.06] mb-3 space-y-1.5 text-[11px] font-mono">
              <div className="flex items-center justify-between text-zinc-400">
                <span>OTE Entry Range:</span>
                <span className="text-zinc-200 font-semibold">
                  {pair.targets.ote_lower != null && pair.targets.ote_upper != null
                    ? `$${pair.targets.ote_lower.toLocaleString()} - $${pair.targets.ote_upper.toLocaleString()}`
                    : '—'}
                </span>
              </div>

              <div className="flex items-center justify-between text-zinc-400">
                <span>Stop Loss (SL):</span>
                <span className="text-rose-400 font-semibold">
                  {pair.targets.stop_loss != null
                    ? `$${pair.targets.stop_loss.toLocaleString()}`
                    : '—'}
                </span>
              </div>

              <div className="flex items-center justify-between text-zinc-400">
                <span>TP1 (Stdv 2.0):</span>
                <span className="text-emerald-400 font-semibold">
                  {pair.targets.stdv_2_0 != null
                    ? `$${pair.targets.stdv_2_0.toLocaleString()}`
                    : '—'}
                </span>
              </div>

              <div className="flex items-center justify-between text-zinc-400">
                <span>TP2 (Stdv 4.0):</span>
                <span className="text-cyan-400 font-semibold">
                  {pair.targets.stdv_4_0 != null
                    ? `$${pair.targets.stdv_4_0.toLocaleString()}`
                    : '—'}
                </span>
              </div>

              {pair.targets.risk_reward_ratio && (
                <div className="pt-1 border-t border-white/[0.05] flex items-center justify-between text-[10px]">
                  <span className="text-zinc-500">Risk:Reward Ratio:</span>
                  <span className="text-emerald-400 font-bold">
                    {pair.targets.risk_reward_ratio}
                  </span>
                </div>
              )}
            </div>

            {isScanning && (
              <div className="text-center mb-2">
                <button
                  type="button"
                  onClick={() => setShowScanningDetails(false)}
                  className="text-[10px] font-mono text-zinc-400 hover:text-cyan-300 transition-colors cursor-pointer"
                >
                  Collapse to Scanning Summary ▴
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {/* Candidate Genome Footer */}
      <div className="pt-2 border-t border-white/[0.06] flex items-center justify-between text-[10px] font-mono text-zinc-500">
        <span title="Optimal Trade Entry Fib bounds">
          {`Fib: ${pair.candidate.ote_bounds}`}
        </span>
        <span title="Standard Deviation Target Multipliers">
          {`TP: ${pair.candidate.stdv_tp1}x / ${pair.candidate.stdv_tp2}x`}
        </span>
      </div>
    </div>
  )
}

function formatPdaLabel(type: IctPdArrayType): string {
  switch (type) {
    case 'ORDER_BLOCK':
      return 'Order Block (OB)'
    case 'BREAKER_BLOCK':
      return 'Breaker Block (BB)'
    case 'FVG_BISI':
      return 'BISI (Bullish FVG)'
    case 'FVG_SIBI':
      return 'SIBI (Bearish FVG)'
    case 'INVERSION_FVG':
      return 'Inversion FVG (IFVG)'
    case 'OLD_HIGH':
      return 'Old High (BSL)'
    case 'OLD_LOW':
      return 'Old Low (SSL)'
    default:
      return type
  }
}

export default StrategyConfluenceRadar
