import type {
  PositionTelemetry,
  IctPairSignal,
  ScalperCriteria,
  BtcMacroTrend,
} from '../components/mission-control/types'

export type PairEntryType = 'DUAL' | 'ICT' | 'SCALPER' | 'FORMING' | 'STANDBY'

export interface PairEntryDetails {
  type: PairEntryType
  badgeLabel: string
  badgeClass: string
  pillClass: string
  description: string
  hasIctEntry: boolean
  hasScalperEntry: boolean
  hasActiveTrade: boolean
  ictStepNumber?: number
  ictStepLabel?: string
  side?: 'BUY' | 'SELL' | 'NEUTRAL'
}

export function evaluatePairEntry(
  _symbol: string,
  position?: PositionTelemetry,
  ictSignal?: IctPairSignal,
  scalperCriteria?: ScalperCriteria,
  btcMacroTrend?: BtcMacroTrend,
): PairEntryDetails {
  const hasActiveTrade = Boolean(
    position &&
    position.state !== 'SCANNING / STANDBY' &&
    (position.size > 0 || position.notionalUsdt > 0 || position.entryPrice > 0),
  )

  // 1. Evaluate ICT MMXM & Twins Reversal setup
  const isIctReady = Boolean(
    ictSignal &&
    (ictSignal.step === 'STEP_6_READY' ||
      ictSignal.step === 'DISPATCHED' ||
      ictSignal.steps?.step_6_ready),
  )
  const isIctForming = Boolean(
    ictSignal &&
    (ictSignal.step === 'STEP_4_OTE_RETRACE' ||
      ictSignal.step === 'STEP_5_M1_CISD' ||
      ictSignal.steps?.step_4_ote_retrace ||
      ictSignal.steps?.step_5_m1_cisd),
  )

  // 2. Evaluate Normal 15m Macro Scalper entry
  const isBtcBullish = btcMacroTrend ? btcMacroTrend.regime === 'BULLISH ALIGNED' : true
  const isScalperTriggered = Boolean(
    scalperCriteria &&
    scalperCriteria.priceTriggered &&
    scalperCriteria.volumeTriggered &&
    scalperCriteria.rsiTriggered &&
    isBtcBullish,
  )

  // Active position attribution
  const hasIctEntry = isIctReady || (hasActiveTrade && Boolean(ictSignal && ictSignal.step !== 'IDLE' && ictSignal.step !== 'INVALIDATED'))
  const hasScalperEntry = isScalperTriggered || (hasActiveTrade && !isIctReady)

  if (hasIctEntry && hasScalperEntry) {
    const badgeLabel = hasActiveTrade ? '🔥 DUAL ENTRY (POSITION)' : '🔥 DUAL ENTRY (SIGNAL)'
    return {
      type: 'DUAL',
      badgeLabel,
      badgeClass: 'bg-amber-500/20 text-amber-300 border-amber-500/40 shadow-[0_0_12px_rgba(245,158,11,0.2)]',
      pillClass: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
      description: hasActiveTrade
        ? 'Dual Confluence: Active position open on both 15m Scalper & ICT.'
        : 'Dual Confluence: Both 15m Macro Scalper and ICT Twins Reversal signals are ready.',
      hasIctEntry: true,
      hasScalperEntry: true,
      hasActiveTrade,
      ictStepNumber: 6,
      ictStepLabel: hasActiveTrade ? 'In Position' : 'Ready / Signal (6/6)',
      side: ictSignal?.side || (position?.state === 'LONG' ? 'BUY' : position?.state === 'SHORT' ? 'SELL' : 'NEUTRAL'),
    }
  }

  if (hasIctEntry) {
    const badgeLabel = hasActiveTrade ? '🎯 ICT ENTRY (POSITION)' : '🎯 ICT ENTRY (SIGNAL)'
    return {
      type: 'ICT',
      badgeLabel,
      badgeClass: 'bg-purple-500/20 text-purple-300 border-purple-500/40 shadow-[0_0_12px_rgba(168,85,247,0.2)]',
      pillClass: 'bg-purple-500/20 text-purple-300 border-purple-500/30',
      description: hasActiveTrade
        ? 'ICT Market Maker Model: Live active position open on Binance.'
        : 'ICT Market Maker Model: 6-Step Twins Reversal confirmation active (Signal Ready).',
      hasIctEntry: true,
      hasScalperEntry: false,
      hasActiveTrade,
      ictStepNumber: 6,
      ictStepLabel: hasActiveTrade ? 'In Position' : 'Ready / Signal (6/6)',
      side: ictSignal?.side || (position?.state === 'LONG' ? 'BUY' : position?.state === 'SHORT' ? 'SELL' : 'NEUTRAL'),
    }
  }

  if (hasScalperEntry) {
    const badgeLabel = hasActiveTrade ? '⚡ SCALPER ENTRY (POSITION)' : '⚡ SCALPER ENTRY (SIGNAL)'
    return {
      type: 'SCALPER',
      badgeLabel,
      badgeClass: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40 shadow-[0_0_12px_rgba(6,182,212,0.2)]',
      pillClass: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30',
      description: hasActiveTrade
        ? '15m Macro Scalper: Live active position open on Binance.'
        : '15m Macro Scalper: Volume-backed liquidity dip sweep active (Signal Ready).',
      hasIctEntry: false,
      hasScalperEntry: true,
      hasActiveTrade,
      side: position?.state === 'LONG' ? 'BUY' : position?.state === 'SHORT' ? 'SELL' : 'BUY',
    }
  }

  if (isIctForming) {
    const stepNum = ictSignal?.step_number || (ictSignal?.step === 'STEP_5_M1_CISD' ? 5 : 4)
    const stepLabel = ictSignal?.step === 'STEP_5_M1_CISD' ? 'M1 CISD (5/6)' : 'OTE Fib (4/6)'
    return {
      type: 'FORMING',
      badgeLabel: `⏳ ICT ${stepLabel}`,
      badgeClass: 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30',
      pillClass: 'bg-indigo-500/15 text-indigo-300 border-indigo-500/25',
      description: `ICT Twins setup forming: Step ${stepNum} of 6 in progress.`,
      hasIctEntry: false,
      hasScalperEntry: false,
      hasActiveTrade,
      ictStepNumber: stepNum,
      ictStepLabel: stepLabel,
      side: ictSignal?.side,
    }
  }

  return {
    type: 'STANDBY',
    badgeLabel: 'STANDBY / SCANNING',
    badgeClass: 'bg-zinc-800/80 text-zinc-400 border-white/[0.08]',
    pillClass: 'bg-zinc-800/60 text-zinc-400 border-zinc-700/40',
    description: 'Scanning order flow and market structure. Awaiting high-probability setup.',
    hasIctEntry: false,
    hasScalperEntry: false,
    hasActiveTrade,
    side: 'NEUTRAL',
  }
}
