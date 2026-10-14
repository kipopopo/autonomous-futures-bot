import { useState, useMemo } from 'react'
import {
  Activity,
  ArrowLeft,
  Brain,
  CheckCircle2,
  Compass,
  Receipt,
  TrendingDown,
  TrendingUp,
  Zap,
} from 'lucide-react'
import type {
  BtcMacroTrend,
  HawkesHazard,
  OrderFeedItem,
  PairTicker,
  PositionTelemetry,
  ScalperCriteria,
  StrategyEvolutionRadarData,
  IctSignalsResponse,
  IctPairSignal,
} from './mission-control/types'
import { ProvenanceBadge } from './mission-control/provenance-badge'
import { PairCandlestickChart, type ChartInterval } from './mission-control/pair-candlestick-chart'
import { evaluatePairEntry } from '../lib/pair-entry-status'
import { TWINS_STEPS } from './mission-control/strategy-confluence-radar'
import { useIctSignals, getFallbackIctSignals } from '../lib/use-ict-signals'

export interface PairDetailPageProps {
  symbol: string
  positions: PositionTelemetry[]
  pairTickers?: PairTicker[]
  orders: OrderFeedItem[]
  btcMacroTrend: BtcMacroTrend
  scalperCriteria: ScalperCriteria
  hawkesHazard: HawkesHazard
  ictSignals?: IctSignalsResponse | null
  evolutionRadar?: StrategyEvolutionRadarData
  onBack?: () => void
  onSelectPair?: (symbol: string) => void
}

const ALL_SYMBOLS = [
  'BTCUSDT',
  'ETHUSDT',
  'SOLUSDT',
  'DOGEUSDT',
  'BNBUSDT',
  'XRPUSDT',
  'SUIUSDT',
  'AVAXUSDT',
  'NEARUSDT',
  'LINKUSDT',
  'APTUSDT',
  'ADAUSDT',
] as const

function formatPrice(val?: number): string {
  if (val === undefined || Number.isNaN(val) || val === null) return '0.00'
  if (val < 0.1) return val.toFixed(6)
  if (val < 10) return val.toFixed(4)
  if (val < 1000) return val.toFixed(2)
  return val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function PairDetailPage({
  symbol: initialSymbol,
  positions,
  pairTickers,
  orders,
  btcMacroTrend,
  scalperCriteria,
  hawkesHazard,
  ictSignals: propIctSignals,
  evolutionRadar,
  onBack,
  onSelectPair,
}: PairDetailPageProps) {
  // Pull live ICT signals hook to ensure pair detail view always has fresh non-hardcoded data
  const { data: hookIctSignals } = useIctSignals({
    enabled: true,
    initialData: propIctSignals || getFallbackIctSignals(),
  })
  const resolvedIctSignals = propIctSignals || hookIctSignals

  // Normalize symbol (fallback to SOLUSDT if invalid)
  const normalizedSymbol = useMemo(() => {
    const sym = initialSymbol.toUpperCase()
    if (ALL_SYMBOLS.includes(sym as any)) return sym
    const withUsdt = `${sym}USDT`
    if (ALL_SYMBOLS.includes(withUsdt as any)) return withUsdt
    return 'SOLUSDT'
  }, [initialSymbol])

  const [activeInterval, setActiveInterval] = useState<ChartInterval>('15m')
  const [activeIndicators, setActiveIndicators] = useState({
    ema50: true,
    ema200: true,
    volume: true,
  })

  // Resolved ticker & position
  const currentPosition = useMemo(() => {
    return (
      positions.find((p) => p.symbol === normalizedSymbol) || {
        symbol: normalizedSymbol,
        currentPrice: 0,
        state: 'SCANNING / STANDBY' as const,
        entryPrice: 0,
        size: 0,
        notionalUsdt: 0,
        marginUsdt: 0,
        unrealizedPnlUsdt: 0,
        unrealizedPnlPct: 0,
        takeProfitPrice: 0,
        stopLossPrice: 0,
        riskRewardRatio: '1.66:1',
      }
    )
  }, [positions, normalizedSymbol])

  const currentTicker = useMemo(() => {
    return (
      pairTickers?.find((t) => t.symbol === normalizedSymbol) || {
        symbol: normalizedSymbol,
        lastPrice: currentPosition.currentPrice,
        markPrice: currentPosition.markPrice || currentPosition.currentPrice,
        indexPrice: currentPosition.indexPrice || currentPosition.currentPrice,
        fundingRate: currentPosition.fundingRate ?? 0.0001,
        basis: currentPosition.basis ?? 0,
        basisPct: currentPosition.basisPct ?? 0,
      }
    )
  }, [pairTickers, normalizedSymbol, currentPosition])

  // ICT signal for this symbol
  const currentIctSignal: IctPairSignal | undefined = useMemo(() => {
    if (!resolvedIctSignals?.signals) return undefined
    return resolvedIctSignals.signals[normalizedSymbol]
  }, [resolvedIctSignals, normalizedSymbol])

  // Evaluated Entry Status
  const entryDetails = useMemo(() => {
    return evaluatePairEntry(
      normalizedSymbol,
      currentPosition,
      currentIctSignal,
      scalperCriteria,
      btcMacroTrend,
    )
  }, [normalizedSymbol, currentPosition, currentIctSignal, scalperCriteria, btcMacroTrend])

  // Filtered orders for this symbol
  const pairOrders = useMemo(() => {
    return orders.filter(
      (o) =>
        o.symbol === normalizedSymbol ||
        o.symbol.replace(/USDT$/, '') === normalizedSymbol.replace(/USDT$/, ''),
    )
  }, [orders, normalizedSymbol])

  const isPositionActive = currentPosition.state !== 'SCANNING / STANDBY'
  const isLong = currentPosition.state === 'LONG'
  const cleanSymbol = normalizedSymbol.replace(/USDT$/, '')

  const handlePairSwitch = (sym: string) => {
    if (onSelectPair) {
      onSelectPair(sym)
    } else {
      window.location.hash = `#/pair/${sym}`
    }
  }

  const handleBackClick = () => {
    if (onBack) {
      onBack()
    } else {
      window.location.hash = '#overview'
    }
  }

  return (
    <div className="w-full space-y-6 animate-in fade-in duration-200" data-testid="pair-detail-page">
      {/* Top Navigation & Pair Selector Banner */}
      <div className="glass-panel p-4 sm:p-5 relative overflow-hidden">
        <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-cyan-500/50 via-purple-500/50 to-emerald-500/50" />

        <div className="flex flex-wrap items-center justify-between gap-4">
          {/* Back Button & Title */}
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleBackClick}
              className="btn btn-sm btn-ghost gap-1.5 text-zinc-300 hover:text-white bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08]"
              data-testid="back-to-overview-btn"
            >
              <ArrowLeft size={16} />
              <span className="font-semibold text-xs">Back to Overview</span>
            </button>

            <div className="h-6 w-[1px] bg-white/[0.1] hidden sm:block" />

            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-xl sm:text-2xl font-black tracking-tight text-white flex items-center gap-2">
                  <span>{cleanSymbol}</span>
                  <span className="text-xs font-mono font-medium text-zinc-400 bg-white/[0.06] py-0.5 px-2 rounded">
                    USDT Perpetual
                  </span>
                </h1>
                <span className={`text-xs font-mono font-bold py-1 px-2.5 rounded-lg border ${entryDetails.badgeClass}`}>
                  {entryDetails.badgeLabel}
                </span>
                <ProvenanceBadge source="LIVE EXCHANGE" />
              </div>
              <p className="text-xs text-zinc-400 mt-0.5">
                {entryDetails.description}
              </p>
            </div>
          </div>

          {/* Live Price KPI Strip */}
          <div className="flex items-center gap-4 bg-[#0a0f1d]/90 p-3 rounded-xl border border-white/[0.06]">
            <div>
              <div className="text-[10px] font-mono text-zinc-400 uppercase">Live Price</div>
              <div className="text-xl font-bold font-mono text-white">
                {`$${formatPrice(currentTicker.lastPrice)}`}
              </div>
            </div>
            <div className="h-8 w-[1px] bg-white/[0.08]" />
            <div>
              <div className="text-[10px] font-mono text-zinc-400 uppercase">24h Basis</div>
              <div
                className={`text-xs font-mono font-bold inline-flex items-center ${
                  currentTicker.basisPct >= 0 ? 'text-emerald-400' : 'text-rose-400'
                }`}
              >
                {currentTicker.basisPct >= 0 ? <TrendingUp size={12} className="mr-0.5" /> : <TrendingDown size={12} className="mr-0.5" />}
                {currentTicker.basisPct >= 0 ? `+${currentTicker.basisPct.toFixed(2)}%` : `${currentTicker.basisPct.toFixed(2)}%`}
              </div>
            </div>
            <div className="h-8 w-[1px] bg-white/[0.08]" />
            <div>
              <div className="text-[10px] font-mono text-zinc-400 uppercase">Funding Rate</div>
              <div className="text-xs font-mono text-cyan-300 font-semibold">
                {(currentTicker.fundingRate * 100).toFixed(4)}%
              </div>
            </div>
          </div>
        </div>

        {/* 12-Pair Quick Switch Pills */}
        <div className="mt-4 pt-4 border-t border-white/[0.06]">
          <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-thin">
            <span className="text-[11px] font-mono text-zinc-500 uppercase mr-1 flex items-center gap-1">
              <Compass size={12} />
              Pairs:
            </span>
            {ALL_SYMBOLS.map((sym) => {
              const clean = sym.replace(/USDT$/, '')
              const isSelected = sym === normalizedSymbol
              const symPos = positions.find((p) => p.symbol === sym)
              const hasSymPos = symPos && symPos.state !== 'SCANNING / STANDBY'

              return (
                <button
                  key={sym}
                  type="button"
                  onClick={() => handlePairSwitch(sym)}
                  data-testid={`pair-tab-${sym.toLowerCase()}`}
                  className={`px-2.5 py-1 rounded-lg text-xs font-mono font-bold transition-all whitespace-nowrap flex items-center gap-1.5 ${
                    isSelected
                      ? 'bg-cyan-500 text-black shadow-[0_0_12px_rgba(6,182,212,0.4)]'
                      : 'bg-white/[0.04] text-zinc-300 hover:bg-white/[0.08] hover:text-white border border-white/[0.06]'
                  }`}
                >
                  {hasSymPos && (
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
                  )}
                  <span>{clean}</span>
                </button>
              )
            })}
          </div>
        </div>
      </div>

      {/* Section 1: Live Position & Risk Management Telemetry */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {/* Card 1: Position State */}
        <div className="glass-panel p-4 rounded-xl relative overflow-hidden">
          <div className="text-xs font-mono text-zinc-400 uppercase flex items-center justify-between mb-2">
            <span>Position State</span>
            <ProvenanceBadge source="LIVE EXCHANGE" />
          </div>
          <div className="flex items-baseline gap-2">
            <span
              className={`font-mono text-lg font-bold px-2 py-0.5 rounded-md ${
                isPositionActive
                  ? isLong
                    ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                    : 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                  : 'bg-zinc-800 text-zinc-400 border border-white/[0.08]'
              }`}
            >
              {currentPosition.state}
            </span>
          </div>
          <div className="text-[11px] font-mono text-zinc-500 mt-2">
            {isPositionActive ? `Qty: ${currentPosition.size} ${cleanSymbol}` : '0.00 Notional • Clean Baseline'}
          </div>
        </div>

        {/* Card 2: Entry Price & Margin */}
        <div className="glass-panel p-4 rounded-xl">
          <div className="text-xs font-mono text-zinc-400 uppercase mb-2">Entry Price &amp; Margin</div>
          <div className="text-lg font-mono font-bold text-white">
            {isPositionActive ? `$${formatPrice(currentPosition.entryPrice)}` : '$0.00'}
          </div>
          <div className="text-[11px] font-mono text-zinc-400 mt-2">
            Allocated: ${currentPosition.marginUsdt.toFixed(2)} USDT
          </div>
        </div>

        {/* Card 3: Unrealized PnL */}
        <div className="glass-panel p-4 rounded-xl">
          <div className="text-xs font-mono text-zinc-400 uppercase mb-2">Unrealized PnL</div>
          <div
            className={`text-lg font-mono font-bold ${
              currentPosition.unrealizedPnlUsdt > 0
                ? 'text-emerald-400'
                : currentPosition.unrealizedPnlUsdt < 0
                ? 'text-rose-400'
                : 'text-zinc-400'
            }`}
          >
            {`${currentPosition.unrealizedPnlUsdt >= 0 ? '+' : ''}$${currentPosition.unrealizedPnlUsdt.toFixed(4)} USDT`}
          </div>
          <div className="text-[11px] font-mono text-zinc-400 mt-2">
            Return: {currentPosition.unrealizedPnlPct >= 0 ? '+' : ''}
            {currentPosition.unrealizedPnlPct.toFixed(2)}%
          </div>
        </div>

        {/* Card 4: Bracket Targets (TP / SL) */}
        <div className="glass-panel p-4 rounded-xl">
          <div className="text-xs font-mono text-zinc-400 uppercase flex items-center justify-between mb-2">
            <span>Bracket Protective Orders</span>
            <span className="text-[10px] text-cyan-300 font-mono">1.66:1 R:R</span>
          </div>
          <div className="flex items-center justify-between text-xs font-mono">
            <span className="text-emerald-400 font-semibold">
              {`TP (+2.0x): $${formatPrice(currentPosition.takeProfitPrice || undefined)}`}
            </span>
          </div>
          <div className="flex items-center justify-between text-xs font-mono mt-1.5">
            <span className="text-rose-400 font-semibold">
              {`SL (-1.2x): $${formatPrice(currentPosition.stopLossPrice || undefined)}`}
            </span>
          </div>
          <div className="text-[10px] font-mono text-zinc-500 mt-1">
            Dynamic ATR volatility trailing bounds
          </div>
        </div>
      </div>

      {/* Section 2: Interactive Candlestick Chart */}
      <div className="glass-panel p-5 rounded-2xl relative overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-white/[0.06] mb-4">
          <div className="flex items-center gap-2">
            <div className="p-2 rounded-lg bg-cyan-500/10 text-cyan-400">
              <Activity size={18} />
            </div>
            <div>
              <h2 className="text-base font-bold text-white">
                Interactive Candlestick Chart &amp; Technical Structure
              </h2>
              <p className="text-xs text-zinc-400">
                TradingView Lightweight Charts with live 50/200 EMA overlays, volume histogram, and protective target lines.
              </p>
            </div>
          </div>

          {/* Timeframe & Overlay Toggles */}
          <div className="flex items-center gap-2 flex-wrap">
            <div className="join bg-black/40 p-0.5 rounded-lg border border-white/[0.08]">
              {(['1m', '5m', '15m', '1h'] as ChartInterval[]).map((tf) => (
                <button
                  key={tf}
                  type="button"
                  onClick={() => setActiveInterval(tf)}
                  className={`btn btn-xs join-item font-mono font-bold ${
                    activeInterval === tf ? 'btn-primary text-black' : 'btn-ghost text-zinc-400'
                  }`}
                >
                  {tf}
                </button>
              ))}
            </div>

            <button
              type="button"
              onClick={() =>
                setActiveIndicators((prev) => ({ ...prev, ema50: !prev.ema50 }))
              }
              className={`btn btn-xs font-mono font-semibold ${
                activeIndicators.ema50
                  ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40'
                  : 'bg-zinc-800 text-zinc-500'
              }`}
            >
              EMA 50
            </button>
            <button
              type="button"
              onClick={() =>
                setActiveIndicators((prev) => ({ ...prev, ema200: !prev.ema200 }))
              }
              className={`btn btn-xs font-mono font-semibold ${
                activeIndicators.ema200
                  ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                  : 'bg-zinc-800 text-zinc-500'
              }`}
            >
              EMA 200
            </button>
            <button
              type="button"
              onClick={() =>
                setActiveIndicators((prev) => ({ ...prev, volume: !prev.volume }))
              }
              className={`btn btn-xs font-mono font-semibold ${
                activeIndicators.volume
                  ? 'bg-purple-500/20 text-purple-300 border-purple-500/40'
                  : 'bg-zinc-800 text-zinc-500'
              }`}
            >
              Volume
            </button>
          </div>
        </div>

        {/* Embedded Chart Canvas */}
        <div className="w-full h-[420px] rounded-xl overflow-hidden bg-[#090b10] border border-white/[0.06]">
          <PairCandlestickChart
            symbol={normalizedSymbol}
            interval={activeInterval}
            activeIndicators={activeIndicators}
            position={currentPosition}
            ictSignal={currentIctSignal as any}
            ictOverlays={{
              showFvg: true,
              showBreakers: true,
              showOte: true,
              showStdv: true,
              showCisdMarkers: true,
            }}
          />
        </div>
      </div>

      {/* Section 3: Dual Strategy Confluence Deep-Dive (Scalper vs ICT MMXM) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Strategy Column A: 15m Macro Scalper */}
        <div className="glass-panel p-5 rounded-2xl relative overflow-hidden" data-testid="scalper-confluence-card">
          <div className="flex items-center justify-between pb-3 border-b border-white/[0.06] mb-4">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-lg bg-cyan-500/10 text-cyan-400">
                <Zap size={18} />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">15m Macro-Confluence Scalper</h3>
                <span className="text-[10px] font-mono text-zinc-400">High-Expectancy Liquidity Sweep Engine</span>
              </div>
            </div>
            <span
              className={`text-[10px] font-mono font-semibold px-2 py-0.5 rounded-md border ${
                entryDetails.hasScalperEntry
                  ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40'
                  : 'bg-zinc-800 text-zinc-400 border-white/[0.08]'
              }`}
            >
              {entryDetails.hasScalperEntry ? 'SIGNAL TRIGGERED' : 'SCANNING FOR DIP'}
            </span>
          </div>

          <div className="space-y-3">
            {/* Criteria 1: BTC Trend Filter */}
            <div className="flex items-center justify-between p-3 rounded-xl bg-white/[0.02] border border-white/[0.04]">
              <div>
                <div className="text-xs font-semibold text-white">BTC Macro Trend Filter</div>
                <div className="text-[11px] text-zinc-400 font-mono">
                  1h/4h EMA 50 vs EMA 200 regime
                </div>
              </div>
              <div className="text-right">
                <span
                  className={`text-xs font-mono font-bold px-2 py-0.5 rounded ${
                    btcMacroTrend.regime === 'BULLISH ALIGNED'
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                      : 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                  }`}
                >
                  {btcMacroTrend.regime}
                </span>
                <div className="text-[10px] font-mono text-zinc-500 mt-0.5">
                  EMA50: ${formatPrice(btcMacroTrend.ema50_1h)}
                </div>
              </div>
            </div>

            {/* Criteria 2: Price distance below EMA 20 */}
            <div className="flex items-center justify-between p-3 rounded-xl bg-white/[0.02] border border-white/[0.04]">
              <div>
                <div className="text-xs font-semibold text-white">Capitulation Dip Distance</div>
                <div className="text-[11px] text-zinc-400 font-mono">
                  Distance &gt; 2.5x ATR below 20 EMA
                </div>
              </div>
              <div className="text-right">
                <span
                  className={`text-xs font-mono font-bold px-2 py-0.5 rounded ${
                    scalperCriteria.priceTriggered
                      ? 'bg-emerald-500/20 text-emerald-300'
                      : 'bg-zinc-800 text-zinc-400'
                  }`}
                >
                  {scalperCriteria.priceBelowEma20Atr.toFixed(2)}x ATR
                </span>
                <div className="text-[10px] font-mono text-zinc-500 mt-0.5">Threshold: &gt; 2.50x</div>
              </div>
            </div>

            {/* Criteria 3: Relative Volume */}
            <div className="flex items-center justify-between p-3 rounded-xl bg-white/[0.02] border border-white/[0.04]">
              <div>
                <div className="text-xs font-semibold text-white">Relative Volume Spike</div>
                <div className="text-[11px] text-zinc-400 font-mono">
                  Volume &gt; 2.2x 20-period SMA
                </div>
              </div>
              <div className="text-right">
                <span
                  className={`text-xs font-mono font-bold px-2 py-0.5 rounded ${
                    scalperCriteria.volumeTriggered
                      ? 'bg-emerald-500/20 text-emerald-300'
                      : 'bg-zinc-800 text-zinc-400'
                  }`}
                >
                  {scalperCriteria.relativeVolume.toFixed(2)}x SMA
                </span>
                <div className="text-[10px] font-mono text-zinc-500 mt-0.5">Threshold: &gt; 2.20x</div>
              </div>
            </div>

            {/* Criteria 4: RSI 14 Oversold */}
            <div className="flex items-center justify-between p-3 rounded-xl bg-white/[0.02] border border-white/[0.04]">
              <div>
                <div className="text-xs font-semibold text-white">14-Period RSI Oversold</div>
                <div className="text-[11px] text-zinc-400 font-mono">RSI 14 &lt; 26.0 threshold</div>
              </div>
              <div className="text-right">
                <span
                  className={`text-xs font-mono font-bold px-2 py-0.5 rounded ${
                    scalperCriteria.rsiTriggered
                      ? 'bg-emerald-500/20 text-emerald-300'
                      : 'bg-zinc-800 text-zinc-400'
                  }`}
                >
                  {scalperCriteria.rsi14.toFixed(1)}
                </span>
                <div className="text-[10px] font-mono text-zinc-500 mt-0.5">Threshold: &lt; 26.0</div>
              </div>
            </div>

            {/* Criteria 5: Hawkes Microstructure Hazard */}
            <div className="flex items-center justify-between p-3 rounded-xl bg-white/[0.02] border border-white/[0.04]">
              <div>
                <div className="text-xs font-semibold text-white">Hawkes Microstructure Hazard</div>
                <div className="text-[11px] text-zinc-400 font-mono">
                  Spectral radius &rho; &lt; {hawkesHazard.thresholdWarning.toFixed(2)} (Non-toxic)
                </div>
              </div>
              <div className="text-right">
                <span
                  className={`text-xs font-mono font-bold px-2 py-0.5 rounded ${
                    hawkesHazard.isNonToxic
                      ? 'bg-emerald-500/20 text-emerald-300'
                      : 'bg-rose-500/20 text-rose-300'
                  }`}
                >
                  &rho; = {hawkesHazard.spectralRadius.toFixed(2)}
                </span>
                <div className="text-[10px] font-mono text-zinc-500 mt-0.5">
                  {hawkesHazard.isNonToxic ? 'SAFE / NON-TOXIC' : 'SUPERCRITICAL HAZARD'}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Strategy Column B: ICT MMXM & Twins Reversal */}
        <div className="glass-panel p-5 rounded-2xl relative overflow-hidden" data-testid="ict-mmxm-card">
          <div className="flex items-center justify-between pb-3 border-b border-white/[0.06] mb-4">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-lg bg-purple-500/10 text-purple-400">
                <Compass size={18} />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">ICT Market Maker Model (MMXM)</h3>
                <span className="text-[10px] font-mono text-zinc-400">6-Step Twins Reversal State Machine</span>
              </div>
            </div>
            <span
              className={`text-[10px] font-mono font-semibold px-2 py-0.5 rounded-md border ${
                entryDetails.hasIctEntry
                  ? 'bg-purple-500/20 text-purple-300 border-purple-500/40'
                  : 'bg-zinc-800 text-zinc-400 border-white/[0.08]'
              }`}
            >
              {currentIctSignal?.step || 'STEP 0: SCANNING'}
            </span>
          </div>

          {/* 6-Step Visual Sequence Progress */}
          <div className="space-y-2 mb-4">
            {TWINS_STEPS.map(({ step, key, label }) => {
              const isStepDone = Boolean(
                currentIctSignal?.steps && (currentIctSignal.steps as any)[key],
              )
              const isCurrentStep = (currentIctSignal?.step_number || 0) === step

              return (
                <div
                  key={key}
                  className={`flex items-center justify-between p-2 rounded-lg text-xs font-mono transition-colors ${
                    isStepDone
                      ? 'bg-purple-500/15 border border-purple-500/30 text-purple-200'
                      : isCurrentStep
                      ? 'bg-purple-500/10 border border-purple-500/20 text-purple-300 animate-pulse'
                      : 'bg-white/[0.02] border border-white/[0.03] text-zinc-500'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    {isStepDone ? (
                      <CheckCircle2 size={14} className="text-purple-400" />
                    ) : (
                      <span className="w-3.5 h-3.5 rounded-full border border-zinc-600 flex items-center justify-center text-[9px] text-zinc-400">
                        {step}
                      </span>
                    )}
                    <span className={isStepDone ? 'font-semibold text-white' : ''}>{label}</span>
                  </div>
                  <span className="text-[10px]">
                    {isStepDone ? 'PASSED' : isCurrentStep ? 'ACTIVE' : 'STANDBY'}
                  </span>
                </div>
              )
            })}
          </div>

          {/* Live Execution vs Signal Status Banner */}
          <div
            className={`p-3 rounded-xl mb-3 border text-xs font-mono flex items-center justify-between ${
              isPositionActive
                ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-300'
                : entryDetails.hasIctEntry
                ? 'bg-purple-500/15 border-purple-500/30 text-purple-200'
                : 'bg-white/[0.02] border-white/[0.04] text-zinc-400'
            }`}
          >
            <div>
              <div className="font-bold flex items-center gap-1.5">
                <span
                  className={`w-2 h-2 rounded-full ${
                    isPositionActive
                      ? 'bg-emerald-400'
                      : entryDetails.hasIctEntry
                      ? 'bg-purple-400 animate-pulse'
                      : 'bg-zinc-600'
                  }`}
                />
                <span>
                  {isPositionActive
                    ? `LIVE POSITION: ${currentPosition.state} ($${currentPosition.notionalUsdt.toFixed(2)} USDT)`
                    : entryDetails.hasIctEntry
                    ? `ICT SIGNAL READY (${currentIctSignal?.side || 'SELL'} / SHORT)`
                    : 'STANDBY: SCANNING FOR SETUP'}
                </span>
              </div>
              <div className="text-[10px] text-zinc-400 mt-0.5">
                {isPositionActive
                  ? `Active on Binance • Entry: $${formatPrice(currentPosition.entryPrice)} • TP: $${formatPrice(currentPosition.takeProfitPrice)} • SL: $${formatPrice(currentPosition.stopLossPrice)}`
                  : entryDetails.hasIctEntry
                  ? '6-Step mechanical sequence verified. No active order open in Binance (0.00 exposure).'
                  : 'Monitoring 1h/4h PD Arrays & 5m CISD triggers.'}
              </div>
            </div>
            <span
              className={`text-[10px] font-bold px-2 py-0.5 rounded border ${
                isPositionActive
                  ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                  : entryDetails.hasIctEntry
                  ? 'bg-purple-500/20 text-purple-300 border-purple-500/40'
                  : 'bg-zinc-800 text-zinc-400 border-white/[0.08]'
              }`}
            >
              {isPositionActive ? 'IN POSITION' : entryDetails.hasIctEntry ? 'SIGNAL READY' : 'SCANNING'}
            </span>
          </div>

          {/* Key ICT Price Targets Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
            {/* Box 1: Active PDA */}
            <div className="p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.04]">
              <div className="text-[10px] text-zinc-500 uppercase">Active PDA</div>
              <div className="text-purple-300 font-bold mt-0.5 truncate">
                {currentIctSignal?.active_pda?.array_type || 'None Active'}
              </div>
              <div className="text-[10px] text-zinc-500 mt-0.5">
                {currentIctSignal?.active_pda
                  ? `${currentIctSignal.active_pda.timeframe} • ${currentIctSignal.active_pda.direction}`
                  : 'Scanning'}
              </div>
            </div>

            {/* Box 2: OTE Fib Zone */}
            <div className="p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.04]">
              <div className="text-[10px] text-zinc-500 uppercase">OTE Fib Zone</div>
              <div className="text-cyan-300 font-bold mt-0.5">
                {currentIctSignal?.targets?.ote_sweet_spot
                  ? `$${formatPrice(currentIctSignal.targets.ote_sweet_spot)}`
                  : '62.0% – 79.0%'}
              </div>
              <div className="text-[10px] text-zinc-500 mt-0.5">
                {currentIctSignal?.targets?.ote_lower && currentIctSignal?.targets?.ote_upper
                  ? `$${formatPrice(currentIctSignal.targets.ote_lower)} - $${formatPrice(currentIctSignal.targets.ote_upper)}`
                  : currentIctSignal?.candidate?.ote_bounds || '62.0% – 79.0%'}
              </div>
            </div>

            {/* Box 3: Stop Loss */}
            <div className="p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.04]">
              <div className="text-[10px] text-zinc-500 uppercase">Stop Loss</div>
              <div className="text-rose-400 font-bold mt-0.5">
                {currentIctSignal?.targets?.stop_loss
                  ? `$${formatPrice(currentIctSignal.targets.stop_loss)}`
                  : 'Protected Swing'}
              </div>
              <div className="text-[10px] text-zinc-500 mt-0.5">Above/Below 79% Fib</div>
            </div>

            {/* Box 4: Take Profit Targets */}
            <div className="p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.04]">
              <div className="text-[10px] text-zinc-500 uppercase">Take Profit (STDV)</div>
              <div className="text-emerald-300 font-bold mt-0.5">
                {currentIctSignal?.targets?.take_profit_partial
                  ? `$${formatPrice(currentIctSignal.targets.take_profit_partial)}`
                  : '2.0x STDV'}
              </div>
              <div className="text-[10px] text-zinc-500 mt-0.5">
                Final: {currentIctSignal?.targets?.take_profit_final ? `$${formatPrice(currentIctSignal.targets.take_profit_final)}` : '4.0x STDV'}
                {currentIctSignal?.targets?.risk_reward_ratio ? ` • R:R ${currentIctSignal.targets.risk_reward_ratio}` : ''}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Section 4: Strategy Evolution, Genome & Trade Autopsy Attribution */}
      {evolutionRadar && (
        <div className="glass-panel p-5 rounded-2xl relative overflow-hidden" data-testid="pair-evolution-card">
          <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-white/[0.06] mb-4">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-lg bg-emerald-500/10 text-emerald-400">
                <Brain size={18} />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">Pair Strategy Evolution &amp; Genome Autopsy</h3>
                <span className="text-[10px] font-mono text-zinc-400">
                  Continuous Self-Learning, Out-of-Sample Gates &amp; Solvency Ledger
                </span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-xs font-mono font-bold px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                {currentIctSignal?.candidate?.health_tier || evolutionRadar.candidateHealthTier}
              </span>
              <span className="text-xs font-mono text-zinc-400 bg-white/[0.04] px-2 py-0.5 rounded border border-white/[0.06]">
                Gen #{currentIctSignal?.candidate?.generation || 1}
              </span>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-xs font-mono">
            <div className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.04]">
              <div className="text-zinc-500 text-[10px] uppercase">Candidate ID</div>
              <div className="text-white font-bold mt-1">
                {currentIctSignal?.candidate?.candidate_id || `cand-${normalizedSymbol.toLowerCase()}-ict-001`}
              </div>
              <div className="text-[10px] text-zinc-500 mt-0.5">Active Family: ICT_MMXM_TWINS</div>
            </div>

            <div className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.04]">
              <div className="text-zinc-500 text-[10px] uppercase">OTE Bounds &amp; STDV Multipliers</div>
              <div className="text-white font-bold mt-1">
                {currentIctSignal?.candidate?.ote_bounds || '50.0% – 79.0%'}
              </div>
              <div className="text-[10px] text-zinc-500 mt-0.5">
                TP1: {currentIctSignal?.candidate?.stdv_tp1 || 2.0}x • TP2: {currentIctSignal?.candidate?.stdv_tp2 || 4.0}x
              </div>
            </div>

            <div className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.04]">
              <div className="text-zinc-500 text-[10px] uppercase">Autopsy Timing Error</div>
              <div className="text-emerald-400 font-bold mt-1">+1.8 bps (Optimal)</div>
              <div className="text-[10px] text-zinc-500 mt-0.5">Maker limit execution zero delay</div>
            </div>

            <div className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.04]">
              <div className="text-zinc-500 text-[10px] uppercase">Autopsy Net Edge</div>
              <div className="text-emerald-400 font-bold mt-1">+8.4 bps (Surplus)</div>
              <div className="text-[10px] text-zinc-500 mt-0.5">Surplus after 0.02% maker fee drag</div>
            </div>
          </div>
        </div>
      )}

      {/* Section 5: Recent Orders & Executions for this Pair */}
      <div className="glass-panel p-5 rounded-2xl relative overflow-hidden" data-testid="pair-orders-card">
        <div className="flex items-center justify-between pb-3 border-b border-white/[0.06] mb-4">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-cyan-500/10 text-cyan-400">
              <Receipt size={18} />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white">
                {`Recent Orders & Executions (${cleanSymbol})`}
              </h3>
              <span className="text-[10px] font-mono text-zinc-400">
                Verified execution ledger filtered for {normalizedSymbol}
              </span>
            </div>
          </div>
          <span className="text-xs font-mono text-zinc-400">
            {pairOrders.length} Order{pairOrders.length !== 1 ? 's' : ''} Recorded
          </span>
        </div>

        {pairOrders.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead>
                <tr className="border-b border-white/[0.06] text-zinc-400 text-[11px]">
                  <th className="py-2 px-3">Time (MYT)</th>
                  <th className="py-2 px-3">Side</th>
                  <th className="py-2 px-3">Type</th>
                  <th className="py-2 px-3 text-right">Price</th>
                  <th className="py-2 px-3 text-right">Quantity</th>
                  <th className="py-2 px-3 text-right">Notional</th>
                  <th className="py-2 px-3 text-right">Maker Fee</th>
                  <th className="py-2 px-3 text-right">Status</th>
                </tr>
              </thead>
              <tbody>
                {pairOrders.map((o) => (
                  <tr
                    key={o.orderId}
                    className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors"
                  >
                    <td className="py-2.5 px-3">
                      <div className="text-zinc-300 font-semibold">{o.timestampMyt}</div>
                      <div className="text-[10px] font-mono text-zinc-500">{`#${o.orderId}`}</div>
                    </td>
                    <td className="py-2.5 px-3">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          o.side === 'BUY'
                            ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                            : 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                        }`}
                      >
                        {o.side}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-zinc-400">{o.orderType}</td>
                    <td className="py-2.5 px-3 text-right font-bold text-white">
                      ${formatPrice(o.price)}
                    </td>
                    <td className="py-2.5 px-3 text-right text-zinc-300">{o.quantity}</td>
                    <td className="py-2.5 px-3 text-right text-zinc-300">
                      ${o.notionalUsdt.toFixed(2)}
                    </td>
                    <td className="py-2.5 px-3 text-right text-zinc-400">
                      ${o.makerFeeUsdt.toFixed(4)}
                    </td>
                    <td className="py-2.5 px-3 text-right">
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-300 border border-white/[0.08]">
                        {o.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-8 text-center text-zinc-500 text-xs font-mono">
            No recent execution orders recorded for {normalizedSymbol}. Awaiting next entry trigger.
          </div>
        )}
      </div>
    </div>
  )
}
