import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { OrchestratorPage } from '../orchestrator-page'
import {
  buildOrchestratorModel,
  type CanaryOrchestratorData,
} from '../../lib/canary'

describe('OrchestratorPage component', () => {
  const verifiedFixture: CanaryOrchestratorData = {
    phase: 'phase_303',
    verified: true,
    status: 'ORCHESTRATOR_VERIFIED',
    circuit_state: 'NORMAL',
    timestamp_ms: 1790131419749,
    timestamp_utc: '2026-09-23T02:43:39.749553+00:00',
    paper_safe: true,
    execution_authority: false,
    candidates: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
    performance: {
      total_cycles: 3,
      completed_cycles: 2,
      defended_cycles: 1,
      interlocked_cycles: 0,
      stale_halted_cycles: 0,
      realized_sharpe_ratio: 1044.827,
      calmar_ratio: 6935.0,
      max_drawdown_pct: 0.0035,
      win_rate_pct: 100.0,
      profit_factor: 0.067,
      total_gross_pnl_usdt: 0.07,
      total_fees_usdt: 0.0015,
      total_slippage_usdt: 0.002,
      total_net_pnl_usdt: 0.0665,
      alpha_attribution_pnl_usdt: 0.07,
      slippage_drag_pnl_usdt: 0.002,
      fee_drag_pnl_usdt: 0.0015,
    },
    shadow_states: {
      BTCUSDT: {
        symbol: 'BTCUSDT',
        active_positions_count: 1,
        allocated_margin_usdt: 0.0,
        unrealized_pnl_usdt: 0.035,
        realized_pnl_usdt: 0.0,
        total_cycles_count: 1,
        last_vpin: 0.25,
        last_hawkes_rho: 0.35,
        last_action: 'FILLED',
        status: 'NORMAL',
      },
      ETHUSDT: {
        symbol: 'ETHUSDT',
        active_positions_count: 0,
        allocated_margin_usdt: 0.0,
        unrealized_pnl_usdt: 0.0,
        realized_pnl_usdt: 0.0,
        total_cycles_count: 1,
        last_vpin: 0.82,
        last_hawkes_rho: 0.88,
        last_action: 'PULLED_DEFENSE',
        status: 'NORMAL',
      },
      SOLUSDT: {
        symbol: 'SOLUSDT',
        active_positions_count: 1,
        allocated_margin_usdt: 1.0,
        unrealized_pnl_usdt: 0.035,
        realized_pnl_usdt: 0.0,
        total_cycles_count: 1,
        last_vpin: 0.3,
        last_hawkes_rho: 0.42,
        last_action: 'FILLED',
        status: 'NORMAL',
      },
    },
    cycles: [
      {
        cycle_id: 'cyc-00001-btcusdt',
        timestamp_ms: 1790131419702,
        timestamp_utc: '2026-09-23T02:43:39.702958+00:00',
        symbol: 'BTCUSDT',
        heartbeat_age_ms: 45.0,
        vpin: 0.25,
        kyles_lambda: 0.00001,
        hawkes_rho: 0.35,
        signal_side: 'BUY',
        signal_strength: 0.85,
        risk_action: 'APPROVED',
        quote_action: 'SHADED',
        shading_bps: 4.2,
        executed_notional_usdt: 0.0,
        mean_slippage_bps: 1.0,
        total_fees_usdt: 0.0,
        total_slippage_usdt: 0.0,
        net_pnl_usdt: 0.035,
        cycle_status: 'COMPLETED',
        stages: [
          {
            stage: 'STAGE_1_INGRESS_SLA',
            name: 'Market Ingress & SLA Freshness',
            status: 'HEALTHY',
            latency_ms: 0.05,
            detail: 'Heartbeat age 45.0 ms <= 500 ms SLA',
          },
          {
            stage: 'STAGE_2_HAZARD_TOXICITY',
            name: 'Microstructure Toxicity & Hawkes Hazard',
            status: 'HEALTHY',
            latency_ms: 0.08,
            detail: 'VPIN=0.250, Kyle\'s λ=0.00001, Hawkes ρ=0.350',
          },
        ],
        child_orders: [
          {
            child_order_id: 'ord-ch-00001-btcusdt',
            symbol: 'BTCUSDT',
            side: 'BUY',
            intended_price: 50101.0,
            executed_price: 50106.01,
            quantity: 0.0,
            notional_usdt: 0.0,
            fee_usdt: 0.0,
            slippage_usdt: 0.0,
            slippage_bps: 1.0,
            status: 'FILLED',
          },
        ],
        brackets: [
          {
            bracket_id: 'brk-tp-0001',
            symbol: 'BTCUSDT',
            bracket_type: 'TAKE_PROFIT_LIMIT',
            side: 'SELL',
            trigger_price: 50857.6,
            limit_price: 50857.6,
            quantity: 0.0,
            notional_usdt: 0.0,
            ratchet_watermark: 50106.01,
            trailing_delta_bps: 80.0,
            status: 'ACTIVE',
            oco_partner_id: 'brk-tsl-0001',
          },
        ],
      },
    ],
    solvency: {
      starting_equity_usdt: 100.0,
      cash_usdt: 98.9965,
      allocated_margin_usdt: 1.0,
      unrealized_pnl_usdt: 0.035,
      realized_pnl_usdt: 0.0,
      total_equity_usdt: 100.0315,
      total_fees_usdt: 0.0015,
      total_slippage_usdt: 0.002,
      drift_usdt: 0.0,
      zero_balance_drift_verified: true,
      tolerance_ceiling_usdt: 1e-15,
      solvency_ratio_pct: 100.0315,
      cash_reserve_pct: 98.9965,
      unencumbered_cash_verified: true,
    },
    ledger: {
      starting_equity: 100.0,
      cash: 98.9965,
      allocated_margin: 1.0,
      unrealized_pnl: 0.035,
      realized_pnl: 0.0,
      drift: 0.0,
      zero_balance_drift: true,
    },
    upstream_hash: '5919a67c92e3121b66005ef7e9a36a651cb71b19556c19d4feb9470bdf289d76',
    phase_hash: '2116a48cf5f40248b86547df12176f14bef0c4fbf917dcc6b631d8a1f0cfd6e2',
    merkle_root: '8ec3824da1946a3fc6fb70f2302a3b139f046385e76bf6050bf00fc58ae31f70',
  }

  it('renders verified orchestrator model with all indicators and sections', () => {
    const model = buildOrchestratorModel(verifiedFixture)
    const html = renderToString(<OrchestratorPage model={model} />)

    expect(html).toContain('Autonomous Closed-Loop Paper Trading Orchestrator')
    expect(html).toContain('PHASE 303')
    expect(html).toContain('ORCHESTRATOR_VERIFIED')
    expect(html).toContain('PAPER SAFE: CONFINED')
    expect(html).toContain('AUTHORITY: OFF')
    expect(html).toContain('ZERO DRIFT')
    expect(html).toContain('BTCUSDT')
    expect(html).toContain('ETHUSDT')
    expect(html).toContain('SOLUSDT')
    expect(html).toContain('8-Stage Sequential Execution Pipeline')
    expect(html).toContain('Centralized Double-Entry Solvency Ledger')
    expect(html).toContain('Cryptographic Merkle DAG Governance')
    expect(html).toContain('8ec3824da1946a3fc6fb70f2302a3b139f046385e76bf6050bf00fc58ae31f70')
    expect(html).toContain('5919a67c92e3121b66005ef7e9a36a651cb71b19556c19d4feb9470bdf289d76')
  })

  it('renders fallback model gracefully without throwing when data is null', () => {
    const fallbackModel = buildOrchestratorModel(null)
    const html = renderToString(<OrchestratorPage model={fallbackModel} />)

    expect(html).toContain('Autonomous Closed-Loop Paper Trading Orchestrator')
    expect(html).toContain('PHASE 303')
    expect(html).toContain('ORCHESTRATOR_VERIFIED')
    expect(html).toContain('PAPER SAFE: CONFINED')
    expect(html).toContain('AUTHORITY: OFF')
    expect(html).toContain('BTCUSDT')
  })
})
