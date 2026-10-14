/**
 * Phase 317: Live Polling Hook for ICT MMXM & Twins Signals.
 *
 * Polls `GET /api/v1/strategy/ict-signals` every 5 seconds.
 * Provides latency tracking, connection status, and deterministic fallback.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  IctCandidateGenomeInfo,
  IctHealthTier,
  IctPairSignal,
  IctPdArrayInfo,
  IctSide,
  IctSignalsResponse,
  IctTwinsStepName,
} from '@/components/mission-control/types'

export type IctConnectionState = 'STREAMING' | 'POLLING' | 'OFFLINE' | 'RECONNECTING'

export const ICT_ACTIVE_PAIRS = [
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

/**
 * Adapts backend response signals into normalized IctPairSignal items.
 */
export function adaptBackendSignal(sym: string, raw: any): IctPairSignal {
  if (raw && typeof raw === 'object' && raw.step_number !== undefined && raw.targets !== undefined) {
    return raw as IctPairSignal
  }

  const twins = raw?.twins_state || {}
  const genome = raw?.candidate_genome || {}

  let step_number = 0
  if (twins.step_6_ready) step_number = 6
  else if (twins.step_5_m1_cisd) step_number = 5
  else if (twins.step_4_ote_retrace) step_number = 4
  else if (twins.step_3_twins_fvg) step_number = 3
  else if (twins.step_2_m5_cisd) step_number = 2
  else if (twins.step_1_htf_hit) step_number = 1

  const stepName: IctTwinsStepName =
    twins.step === 'INVALIDATED'
      ? 'INVALIDATED'
      : step_number === 6
        ? 'STEP_6_READY'
        : step_number === 5
          ? 'STEP_5_M1_CISD'
          : step_number === 4
            ? 'STEP_4_OTE_RETRACE'
            : step_number === 3
              ? 'STEP_3_TWINS_FVG'
              : step_number === 2
                ? 'STEP_2_M5_CISD'
                : step_number === 1
                  ? 'STEP_1_HTF_HIT'
                  : 'IDLE'

  let active_pda: IctPdArrayInfo | null = null
  if (twins.active_pda) {
    active_pda = {
      array_type: twins.active_pda.array_type || twins.active_pda.type || 'ORDER_BLOCK',
      timeframe: twins.active_pda.timeframe || '1h',
      top: twins.active_pda.top,
      bottom: twins.active_pda.bottom,
      mean_threshold: twins.active_pda.mean_threshold,
      direction: twins.active_pda.direction || 'BULLISH',
      is_mitigated: Boolean(twins.active_pda.is_mitigated),
    }
  } else if (raw?.pd_arrays) {
    const allPdas: any[] = Array.isArray(raw.pd_arrays)
      ? raw.pd_arrays
      : Object.values(raw.pd_arrays).flat()
    const freshPda = allPdas.find((p: any) => !p.is_mitigated) || allPdas[0]
    if (freshPda) {
      active_pda = {
        array_type: freshPda.array_type || freshPda.type || 'ORDER_BLOCK',
        timeframe: freshPda.timeframe || '1h',
        top: freshPda.top,
        bottom: freshPda.bottom,
        mean_threshold: freshPda.mean_threshold,
        direction: freshPda.direction || 'BULLISH',
        is_mitigated: Boolean(freshPda.is_mitigated),
      }
    }
  }

  let rr: string | undefined = undefined
  if (twins.stop_loss && twins.take_profit_partial && twins.ote_705) {
    const risk = Math.abs(twins.ote_705 - twins.stop_loss)
    const reward = Math.abs(twins.take_profit_partial - twins.ote_705)
    if (risk > 0) {
      rr = `${(reward / risk).toFixed(2)}:1`
    }
  }

  const oteLower = genome.ote_lower ?? 0.62
  const oteUpper = genome.ote_upper ?? 0.79
  const fvgThreshold = genome.fvg_threshold_pct ?? 0.0015

  const candidateInfo: IctCandidateGenomeInfo = {
    candidate_id: genome.candidate_id || `cand-${sym.toLowerCase()}-ict-001`,
    health_tier: (genome.health_tier || genome.tier || 'HEALTHY') as IctHealthTier,
    generation: genome.generation || 1,
    ote_bounds: `${(oteLower * 100).toFixed(1)}% - ${(oteUpper * 100).toFixed(1)}%`,
    stdv_tp1: genome.stdv_tp1 ?? 2.0,
    stdv_tp2: genome.stdv_tp2 ?? 4.0,
    swing_lookback: genome.swing_lookback ?? 50,
    fvg_threshold_pct: `${(fvgThreshold * 100).toFixed(2)}%`,
  }

  return {
    symbol: sym,
    step: stepName,
    step_number,
    steps: {
      step_1_htf_hit: Boolean(twins.step_1_htf_hit),
      step_2_m5_cisd: Boolean(twins.step_2_m5_cisd),
      step_3_twins_fvg: Boolean(twins.step_3_twins_fvg),
      step_4_ote_retrace: Boolean(twins.step_4_ote_retrace),
      step_5_m1_cisd: Boolean(twins.step_5_m1_cisd),
      step_6_ready: Boolean(twins.step_6_ready),
    },
    side: (twins.side as IctSide) || 'NEUTRAL',
    active_pda,
    cisd: {
      m5_cisd_price: twins.m5_cisd_price ?? null,
      m1_cisd_price: twins.m1_cisd_price ?? null,
    },
    targets: {
      ote_lower: twins.ote_62 ?? null,
      ote_sweet_spot: twins.ote_705 ?? null,
      ote_upper: twins.ote_79 ?? null,
      stop_loss: twins.stop_loss ?? null,
      stdv_2_0: twins.stdv_2_0 ?? null,
      stdv_4_0: twins.stdv_4_0 ?? null,
      take_profit_partial: twins.take_profit_partial ?? null,
      take_profit_final: twins.take_profit_final ?? null,
      risk_reward_ratio: rr,
    },
    candidate: candidateInfo,
    invalidation_reason: twins.invalidation_reason || 'NONE',
  }
}

/**
 * Deterministic fallback signals when backend is offline or disconnected.
 */
export function getFallbackIctSignals(): IctSignalsResponse {
  const mockSignals: Record<string, IctPairSignal> = {
    BTCUSDT: {
      symbol: 'BTCUSDT',
      step: 'STEP_4_OTE_RETRACE',
      step_number: 4,
      steps: {
        step_1_htf_hit: true,
        step_2_m5_cisd: true,
        step_3_twins_fvg: true,
        step_4_ote_retrace: true,
        step_5_m1_cisd: false,
        step_6_ready: false,
      },
      side: 'BUY',
      active_pda: {
        array_type: 'ORDER_BLOCK',
        timeframe: '4h',
        top: 64800,
        bottom: 64200,
        mean_threshold: 64500,
        direction: 'BULLISH',
        is_mitigated: false,
      },
      cisd: {
        m5_cisd_price: 64950,
        m1_cisd_price: 64650,
      },
      targets: {
        ote_lower: 64320,
        ote_sweet_spot: 64450,
        ote_upper: 64580,
        stop_loss: 64100,
        stdv_2_0: 65900,
        stdv_4_0: 67100,
        take_profit_partial: 65900,
        take_profit_final: 67100,
        risk_reward_ratio: '3.12:1',
      },
      candidate: {
        candidate_id: 'cand-btcusdt-ict-001',
        health_tier: 'HEALTHY',
        generation: 1,
        ote_bounds: '62.0% - 79.0%',
        stdv_tp1: 2.0,
        stdv_tp2: 4.0,
        swing_lookback: 50,
        fvg_threshold_pct: '0.15%',
      },
      invalidation_reason: 'NONE',
    },
    ETHUSDT: {
      symbol: 'ETHUSDT',
      step: 'STEP_2_M5_CISD',
      step_number: 2,
      steps: {
        step_1_htf_hit: true,
        step_2_m5_cisd: true,
        step_3_twins_fvg: false,
        step_4_ote_retrace: false,
        step_5_m1_cisd: false,
        step_6_ready: false,
      },
      side: 'BUY',
      active_pda: {
        array_type: 'FVG_BISI',
        timeframe: '1h',
        top: 2780,
        bottom: 2750,
        mean_threshold: 2765,
        direction: 'BULLISH',
        is_mitigated: false,
      },
      cisd: {
        m5_cisd_price: 2795,
        m1_cisd_price: null,
      },
      targets: {
        ote_lower: 2755,
        ote_sweet_spot: 2762,
        ote_upper: 2772,
        stop_loss: 2740,
        stdv_2_0: 2840,
        stdv_4_0: 2895,
        take_profit_partial: 2840,
        take_profit_final: 2895,
        risk_reward_ratio: '2.65:1',
      },
      candidate: {
        candidate_id: 'cand-ethusdt-ict-001',
        health_tier: 'HEALTHY',
        generation: 1,
        ote_bounds: '62.0% - 79.0%',
        stdv_tp1: 2.0,
        stdv_tp2: 4.0,
        swing_lookback: 50,
        fvg_threshold_pct: '0.15%',
      },
      invalidation_reason: 'NONE',
    },
    SOLUSDT: {
      symbol: 'SOLUSDT',
      step: 'STEP_6_READY',
      step_number: 6,
      steps: {
        step_1_htf_hit: true,
        step_2_m5_cisd: true,
        step_3_twins_fvg: true,
        step_4_ote_retrace: true,
        step_5_m1_cisd: true,
        step_6_ready: true,
      },
      side: 'BUY',
      active_pda: {
        array_type: 'BREAKER_BLOCK',
        timeframe: '1h',
        top: 182.5,
        bottom: 180.2,
        mean_threshold: 181.35,
        direction: 'BULLISH',
        is_mitigated: true,
      },
      cisd: {
        m5_cisd_price: 184.2,
        m1_cisd_price: 182.8,
      },
      targets: {
        ote_lower: 181.2,
        ote_sweet_spot: 181.9,
        ote_upper: 182.8,
        stop_loss: 179.5,
        stdv_2_0: 189.5,
        stdv_4_0: 195.0,
        take_profit_partial: 189.5,
        take_profit_final: 195.0,
        risk_reward_ratio: '3.42:1',
      },
      candidate: {
        candidate_id: 'cand-solusdt-ict-001',
        health_tier: 'HEALTHY',
        generation: 1,
        ote_bounds: '62.0% - 79.0%',
        stdv_tp1: 2.0,
        stdv_tp2: 4.0,
        swing_lookback: 50,
        fvg_threshold_pct: '0.15%',
      },
      invalidation_reason: 'NONE',
    },
    DOGEUSDT: {
      symbol: 'DOGEUSDT',
      step: 'STEP_1_HTF_HIT',
      step_number: 1,
      steps: {
        step_1_htf_hit: true,
        step_2_m5_cisd: false,
        step_3_twins_fvg: false,
        step_4_ote_retrace: false,
        step_5_m1_cisd: false,
        step_6_ready: false,
      },
      side: 'BUY',
      active_pda: {
        array_type: 'FVG_BISI',
        timeframe: '4h',
        top: 0.142,
        bottom: 0.138,
        mean_threshold: 0.14,
        direction: 'BULLISH',
        is_mitigated: false,
      },
      cisd: {
        m5_cisd_price: null,
        m1_cisd_price: null,
      },
      targets: {
        ote_lower: 0.139,
        ote_sweet_spot: 0.1405,
        ote_upper: 0.1415,
        stop_loss: 0.1365,
        stdv_2_0: 0.152,
        stdv_4_0: 0.161,
        take_profit_partial: 0.152,
        take_profit_final: 0.161,
        risk_reward_ratio: '2.50:1',
      },
      candidate: {
        candidate_id: 'cand-dogeusdt-ict-001',
        health_tier: 'INCUBATING',
        generation: 1,
        ote_bounds: '62.0% - 79.0%',
        stdv_tp1: 2.0,
        stdv_tp2: 4.0,
        swing_lookback: 50,
        fvg_threshold_pct: '0.15%',
      },
      invalidation_reason: 'NONE',
    },
    BNBUSDT: {
      symbol: 'BNBUSDT',
      step: 'STEP_3_TWINS_FVG',
      step_number: 3,
      steps: {
        step_1_htf_hit: true,
        step_2_m5_cisd: true,
        step_3_twins_fvg: true,
        step_4_ote_retrace: false,
        step_5_m1_cisd: false,
        step_6_ready: false,
      },
      side: 'BUY',
      active_pda: {
        array_type: 'ORDER_BLOCK',
        timeframe: '1h',
        top: 592.0,
        bottom: 588.0,
        mean_threshold: 590.0,
        direction: 'BULLISH',
        is_mitigated: false,
      },
      cisd: {
        m5_cisd_price: 594.5,
        m1_cisd_price: null,
      },
      targets: {
        ote_lower: 589.5,
        ote_sweet_spot: 591.0,
        ote_upper: 592.8,
        stop_loss: 586.0,
        stdv_2_0: 605.0,
        stdv_4_0: 618.0,
        take_profit_partial: 605.0,
        take_profit_final: 618.0,
        risk_reward_ratio: '2.80:1',
      },
      candidate: {
        candidate_id: 'cand-bnbusdt-ict-001',
        health_tier: 'HEALTHY',
        generation: 1,
        ote_bounds: '62.0% - 79.0%',
        stdv_tp1: 2.0,
        stdv_tp2: 4.0,
        swing_lookback: 50,
        fvg_threshold_pct: '0.15%',
      },
      invalidation_reason: 'NONE',
    },
    XRPUSDT: {
      symbol: 'XRPUSDT',
      step: 'STEP_5_M1_CISD',
      step_number: 5,
      steps: {
        step_1_htf_hit: true,
        step_2_m5_cisd: true,
        step_3_twins_fvg: true,
        step_4_ote_retrace: true,
        step_5_m1_cisd: true,
        step_6_ready: false,
      },
      side: 'BUY',
      active_pda: {
        array_type: 'INVERSION_FVG',
        timeframe: '1h',
        top: 0.552,
        bottom: 0.546,
        mean_threshold: 0.549,
        direction: 'BULLISH',
        is_mitigated: true,
      },
      cisd: {
        m5_cisd_price: 0.556,
        m1_cisd_price: 0.551,
      },
      targets: {
        ote_lower: 0.5475,
        ote_sweet_spot: 0.5495,
        ote_upper: 0.5515,
        stop_loss: 0.542,
        stdv_2_0: 0.575,
        stdv_4_0: 0.595,
        take_profit_partial: 0.575,
        take_profit_final: 0.595,
        risk_reward_ratio: '3.10:1',
      },
      candidate: {
        candidate_id: 'cand-xrpusdt-ict-001',
        health_tier: 'HEALTHY',
        generation: 1,
        ote_bounds: '62.0% - 79.0%',
        stdv_tp1: 2.0,
        stdv_tp2: 4.0,
        swing_lookback: 50,
        fvg_threshold_pct: '0.15%',
      },
      invalidation_reason: 'NONE',
    },
    SUIUSDT: {
      symbol: 'SUIUSDT',
      step: 'IDLE',
      step_number: 0,
      steps: {
        step_1_htf_hit: false,
        step_2_m5_cisd: false,
        step_3_twins_fvg: false,
        step_4_ote_retrace: false,
        step_5_m1_cisd: false,
        step_6_ready: false,
      },
      side: 'NEUTRAL',
      active_pda: null,
      cisd: {
        m5_cisd_price: null,
        m1_cisd_price: null,
      },
      targets: {
        ote_lower: null,
        ote_sweet_spot: null,
        ote_upper: null,
        stop_loss: null,
        stdv_2_0: null,
        stdv_4_0: null,
        take_profit_partial: null,
        take_profit_final: null,
      },
      candidate: {
        candidate_id: 'cand-suiusdt-ict-001',
        health_tier: 'INCUBATING',
        generation: 1,
        ote_bounds: '62.0% - 79.0%',
        stdv_tp1: 2.0,
        stdv_tp2: 4.0,
        swing_lookback: 50,
        fvg_threshold_pct: '0.15%',
      },
      invalidation_reason: 'NONE',
    },
    AVAXUSDT: {
      symbol: 'AVAXUSDT',
      step: 'INVALIDATED',
      step_number: 0,
      steps: {
        step_1_htf_hit: true,
        step_2_m5_cisd: false,
        step_3_twins_fvg: false,
        step_4_ote_retrace: false,
        step_5_m1_cisd: false,
        step_6_ready: false,
      },
      side: 'NEUTRAL',
      active_pda: {
        array_type: 'ORDER_BLOCK',
        timeframe: '4h',
        top: 28.5,
        bottom: 27.8,
        mean_threshold: 28.15,
        direction: 'BULLISH',
        is_mitigated: true,
      },
      cisd: {
        m5_cisd_price: null,
        m1_cisd_price: null,
      },
      targets: {
        ote_lower: null,
        ote_sweet_spot: null,
        ote_upper: null,
        stop_loss: null,
        stdv_2_0: null,
        stdv_4_0: null,
        take_profit_partial: null,
        take_profit_final: null,
      },
      candidate: {
        candidate_id: 'cand-avaxusdt-ict-001',
        health_tier: 'DEGRADED',
        generation: 1,
        ote_bounds: '62.0% - 79.0%',
        stdv_tp1: 2.0,
        stdv_tp2: 4.0,
        swing_lookback: 50,
        fvg_threshold_pct: '0.15%',
      },
      invalidation_reason: 'PDA_BREACHED',
    },
    NEARUSDT: {
      symbol: 'NEARUSDT',
      step: 'IDLE',
      step_number: 0,
      steps: {
        step_1_htf_hit: false,
        step_2_m5_cisd: false,
        step_3_twins_fvg: false,
        step_4_ote_retrace: false,
        step_5_m1_cisd: false,
        step_6_ready: false,
      },
      side: 'NEUTRAL',
      active_pda: null,
      cisd: {
        m5_cisd_price: null,
        m1_cisd_price: null,
      },
      targets: {
        ote_lower: null,
        ote_sweet_spot: null,
        ote_upper: null,
        stop_loss: null,
        stdv_2_0: null,
        stdv_4_0: null,
        take_profit_partial: null,
        take_profit_final: null,
      },
      candidate: {
        candidate_id: 'cand-nearusdt-ict-001',
        health_tier: 'HEALTHY',
        generation: 1,
        ote_bounds: '50.0% - 79.0%',
        stdv_tp1: 2.0,
        stdv_tp2: 4.0,
        swing_lookback: 50,
        fvg_threshold_pct: '0.15%',
      },
      invalidation_reason: 'NONE',
    },
    LINKUSDT: {
      symbol: 'LINKUSDT',
      step: 'IDLE',
      step_number: 0,
      steps: {
        step_1_htf_hit: false,
        step_2_m5_cisd: false,
        step_3_twins_fvg: false,
        step_4_ote_retrace: false,
        step_5_m1_cisd: false,
        step_6_ready: false,
      },
      side: 'NEUTRAL',
      active_pda: null,
      cisd: {
        m5_cisd_price: null,
        m1_cisd_price: null,
      },
      targets: {
        ote_lower: null,
        ote_sweet_spot: null,
        ote_upper: null,
        stop_loss: null,
        stdv_2_0: null,
        stdv_4_0: null,
        take_profit_partial: null,
        take_profit_final: null,
      },
      candidate: {
        candidate_id: 'cand-linkusdt-ict-001',
        health_tier: 'HEALTHY',
        generation: 1,
        ote_bounds: '50.0% - 79.0%',
        stdv_tp1: 2.0,
        stdv_tp2: 4.0,
        swing_lookback: 50,
        fvg_threshold_pct: '0.15%',
      },
      invalidation_reason: 'NONE',
    },
    APTUSDT: {
      symbol: 'APTUSDT',
      step: 'IDLE',
      step_number: 0,
      steps: {
        step_1_htf_hit: false,
        step_2_m5_cisd: false,
        step_3_twins_fvg: false,
        step_4_ote_retrace: false,
        step_5_m1_cisd: false,
        step_6_ready: false,
      },
      side: 'NEUTRAL',
      active_pda: null,
      cisd: {
        m5_cisd_price: null,
        m1_cisd_price: null,
      },
      targets: {
        ote_lower: null,
        ote_sweet_spot: null,
        ote_upper: null,
        stop_loss: null,
        stdv_2_0: null,
        stdv_4_0: null,
        take_profit_partial: null,
        take_profit_final: null,
      },
      candidate: {
        candidate_id: 'cand-aptusdt-ict-001',
        health_tier: 'HEALTHY',
        generation: 1,
        ote_bounds: '50.0% - 79.0%',
        stdv_tp1: 2.0,
        stdv_tp2: 4.0,
        swing_lookback: 50,
        fvg_threshold_pct: '0.15%',
      },
      invalidation_reason: 'NONE',
    },
    ADAUSDT: {
      symbol: 'ADAUSDT',
      step: 'IDLE',
      step_number: 0,
      steps: {
        step_1_htf_hit: false,
        step_2_m5_cisd: false,
        step_3_twins_fvg: false,
        step_4_ote_retrace: false,
        step_5_m1_cisd: false,
        step_6_ready: false,
      },
      side: 'NEUTRAL',
      active_pda: null,
      cisd: {
        m5_cisd_price: null,
        m1_cisd_price: null,
      },
      targets: {
        ote_lower: null,
        ote_sweet_spot: null,
        ote_upper: null,
        stop_loss: null,
        stdv_2_0: null,
        stdv_4_0: null,
        take_profit_partial: null,
        take_profit_final: null,
      },
      candidate: {
        candidate_id: 'cand-adausdt-ict-001',
        health_tier: 'HEALTHY',
        generation: 1,
        ote_bounds: '50.0% - 79.0%',
        stdv_tp1: 2.0,
        stdv_tp2: 4.0,
        swing_lookback: 50,
        fvg_threshold_pct: '0.15%',
      },
      invalidation_reason: 'NONE',
    },
  }

  return {
    verified: false,
    timestamp_ms: Date.now(),
    active_family: 'ICT_MMXM_TWINS',
    latency_ms: 12,
    signals: mockSignals,
  }
}

export interface UseIctSignalsOptions {
  pollingIntervalMs?: number
  enabled?: boolean
  initialData?: IctSignalsResponse | null
}

export function useIctSignals(options: UseIctSignalsOptions = {}) {
  const { pollingIntervalMs = 5000, enabled = true, initialData = null } = options

  const [data, setData] = useState<IctSignalsResponse | null>(() => initialData || getFallbackIctSignals())
  const [isLoading, setIsLoading] = useState<boolean>(!initialData)
  const [error, setError] = useState<string | null>(null)
  const [latencyMs, setLatencyMs] = useState<number>(12)
  const [connectionState, setConnectionState] = useState<IctConnectionState>('POLLING')
  const [lastUpdated, setLastUpdated] = useState<Date>(() => new Date())

  const abortControllerRef = useRef<AbortController | null>(null)

  const fetchSignals = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    abortControllerRef.current = new AbortController()

    const startTime = performance.now()
    try {
      const response = await fetch('/api/v1/strategy/ict-signals', {
        headers: { Accept: 'application/json' },
        signal: abortControllerRef.current.signal,
      })

      const elapsed = Math.round(performance.now() - startTime)
      setLatencyMs(elapsed)

      if (!response.ok) {
        throw new Error(`GET /api/v1/strategy/ict-signals failed with HTTP ${response.status}`)
      }

      const json = await response.json()
      // Normalize signals map
      const normalizedSignals: Record<string, IctPairSignal> = {}
      if (json && json.signals && typeof json.signals === 'object') {
        for (const [sym, rawSig] of Object.entries(json.signals)) {
          normalizedSignals[sym] = adaptBackendSignal(sym, rawSig)
        }
      }

      const normalizedResponse: IctSignalsResponse = {
        verified: Boolean(json.verified),
        timestamp_ms: json.timestamp_ms || Date.now(),
        active_family: json.active_family || 'ICT_MMXM_TWINS',
        latency_ms: elapsed,
        signals: normalizedSignals,
      }

      setData(normalizedResponse)
      setError(null)
      setConnectionState('STREAMING')
      setLastUpdated(new Date())
    } catch (err: unknown) {
      if ((err as Error)?.name === 'AbortError') return
      console.warn('[useIctSignals] Using deterministic fallback:', err)
      setError((err as Error)?.message || 'Failed to fetch ICT signals')
      setConnectionState('OFFLINE')
      setData((prev) => prev || getFallbackIctSignals())
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!enabled) return

    fetchSignals()
    const timer = setInterval(fetchSignals, pollingIntervalMs)

    return () => {
      clearInterval(timer)
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
      }
    }
  }, [fetchSignals, pollingIntervalMs, enabled])

  return {
    data,
    isLoading,
    error,
    latencyMs,
    connectionState,
    lastUpdated,
    refetch: fetchSignals,
  }
}
