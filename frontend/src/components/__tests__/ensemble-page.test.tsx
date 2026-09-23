import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { EnsemblePage } from '../ensemble-page'
import {
  buildEnsembleModel,
  type CanaryEnsembleData,
} from '../../lib/canary'

describe('EnsemblePage component', () => {
  const verifiedFixture: CanaryEnsembleData = {
    phase: 'phase_305',
    verified: true,
    status: 'ENSEMBLE_VERIFIED',
    circuit_state: 'NORMAL',
    timestamp_ms: 1790136000000,
    timestamp_utc: '2026-09-23T12:00:00.000000+00:00',
    paper_safe: true,
    execution_authority: false,
    candidates: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
    performance: {
      total_decisions: 6,
      conflict_count: 1,
      conflict_ratio_pct: 16.67,
      average_effective_conviction: 0.68,
      mean_horizon_weights: {
        micro: 0.35,
        short: 0.35,
        medium: 0.30,
      },
      regime_distribution: {
        CALM_BALANCED: 2,
        TRENDING_MOMENTUM: 1,
        VOLATILITY_EXPANSION: 1,
        TOXIC_TURBULENCE: 1,
        MEAN_REVERTING: 1,
      },
      defense_lockouts_triggered: 1,
      realized_sharpe_ratio: 1150.0,
      calmar_ratio: 7200.0,
      max_drawdown_pct: 0.0028,
      win_rate_pct: 100.0,
      profit_factor: 25.5,
    },
    shadow_states: {
      BTCUSDT: {
        symbol: 'BTCUSDT',
        active_regime: 'CALM_BALANCED',
        total_decisions: 2,
        conflict_count: 0,
        allocated_margin_usdt: 8.0,
        unrealized_pnl_usdt: 0.40,
        realized_pnl_usdt: 0.0,
        last_decision: {
          symbol: 'BTCUSDT',
          timestamp_ms: 1790136000200,
          regime: 'TRENDING_MOMENTUM',
          weights: {
            micro_weight: 0.15,
            short_weight: 0.35,
            medium_weight: 0.50,
            weights_sum: 1.0,
            regime: 'TRENDING_MOMENTUM',
            regime_confidence: 0.98,
          },
          signals: {
            MICRO_1S_5S: {
              horizon: 'MICRO_1S_5S',
              symbol: 'BTCUSDT',
              timestamp_ms: 1790136000200,
              direction: 0.25,
              conviction: 0.30,
              raw_score: 0.25,
              features: {},
            },
            SHORT_1M_5M: {
              horizon: 'SHORT_1M_5M',
              symbol: 'BTCUSDT',
              timestamp_ms: 1790136000200,
              direction: 0.70,
              conviction: 0.75,
              raw_score: 0.70,
              features: {},
            },
            MEDIUM_15M_1H: {
              horizon: 'MEDIUM_15M_1H',
              symbol: 'BTCUSDT',
              timestamp_ms: 1790136000200,
              direction: 0.85,
              conviction: 0.90,
              raw_score: 0.85,
              features: {},
            },
          },
          raw_blended_direction: 0.71,
          raw_blended_conviction: 0.76,
          conflict_detected: false,
          conflict_penalty: 1.0,
          effective_direction: 0.71,
          effective_conviction: 0.76,
          target_action: 'BUY',
          target_micro_chunk_usdt: 4.50,
          ensemble_state: 'ENSEMBLE_ACTIVE',
          notes: '',
        },
      },
    },
    decisions_trace: [
      {
        symbol: 'BTCUSDT',
        timestamp_ms: 1790136000200,
        regime: 'TRENDING_MOMENTUM',
        weights: {
          micro_weight: 0.15,
          short_weight: 0.35,
          medium_weight: 0.50,
          weights_sum: 1.0,
          regime: 'TRENDING_MOMENTUM',
          regime_confidence: 0.98,
        },
        signals: {},
        raw_blended_direction: 0.71,
        raw_blended_conviction: 0.76,
        conflict_detected: false,
        conflict_penalty: 1.0,
        effective_direction: 0.71,
        effective_conviction: 0.76,
        target_action: 'BUY',
        target_micro_chunk_usdt: 4.50,
        ensemble_state: 'ENSEMBLE_ACTIVE',
        notes: '',
      },
    ],
    solvency: {
      starting_equity_usdt: 100.0,
      cash_usdt: 87.70,
      allocated_margin_usdt: 12.30,
      unrealized_pnl_usdt: 0.43,
      realized_pnl_usdt: 0.0,
      total_equity_usdt: 100.43,
      total_fees_usdt: 0.0126,
      total_slippage_usdt: 0.0045,
      drift_usdt: 0.0,
      zero_balance_drift_verified: true,
      tolerance_ceiling_usdt: 1e-15,
      solvency_ratio_pct: 100.43,
      cash_reserve_pct: 87.70,
      unencumbered_cash_verified: true,
    },
    ledger: {
      starting_equity: 100.0,
      cash: 87.70,
      allocated_margin: 12.30,
      unrealized_pnl: 0.43,
      realized_pnl: 0.0,
      drift: 0.0,
      zero_balance_drift: true,
    },
    upstream_hash: '07ffc13325eeffaadd0fb2e2cc60fe15269943f0bfca55fd613289c02a4fb80b',
    phase_hash: 'abc123phasehash',
    merkle_root: 'e6d84cef9cef37b0c211a7c77536eeafd22537a511770f480e099b1847ea07d9',
  }

  it('renders verified ensemble status and title', () => {
    const model = buildEnsembleModel(verifiedFixture)
    const html = renderToString(<EnsemblePage model={model} />)

    expect(html).toContain('Autonomous Multi-Horizon Alpha Ensemble &amp; Meta-Policy Blending Engine')
    expect(html).toContain('PHASE 305')
    expect(html).toContain('ENSEMBLE_VERIFIED')
    expect(html).toContain('PAPER SAFE: CONFINED')
    expect(html).toContain('AUTHORITY: OFF')
  })

  it('renders KPI summary metrics accurately', () => {
    const model = buildEnsembleModel(verifiedFixture)
    const html = renderToString(<EnsemblePage model={model} />)

    expect(html).toContain('68.0%')
    expect(html).toContain('16.67%')
    expect(html).toContain('87.7%')
    expect(html).toContain('1150.0')
  })

  it('renders candidate alpha table rows and decision trace', () => {
    const model = buildEnsembleModel(verifiedFixture)
    const html = renderToString(<EnsemblePage model={model} />)

    expect(html).toContain('BTCUSDT')
    expect(html).toContain('TRENDING_MOMENTUM')
    expect(html).toContain('BUY')
    expect(html).toContain('$4.50')
  })

  it('renders solvency ledger and Merkle DAG chain', () => {
    const model = buildEnsembleModel(verifiedFixture)
    const html = renderToString(<EnsemblePage model={model} />)

    expect(html).toContain('Double-Entry Solvency Ledger')
    expect(html).toContain('07ffc13325eeffaadd0fb2e2cc60fe15269943f0bfca55fd613289c02a4fb80b')
    expect(html).toContain('e6d84cef9cef37b0c211a7c77536eeafd22537a511770f480e099b1847ea07d9')
    expect(html).toContain('VERIFIED IMMUTABLE')
  })

  it('renders fallback model gracefully when data is null', () => {
    const fallbackModel = buildEnsembleModel(null)
    const html = renderToString(<EnsemblePage model={fallbackModel} />)

    expect(html).toContain('PHASE 305')
    expect(html).toContain('ENSEMBLE_VERIFIED')
    expect(html).toContain('07ffc13325eeffaadd0fb2e2cc60fe15269943f0bfca55fd613289c02a4fb80b')
  })
})
