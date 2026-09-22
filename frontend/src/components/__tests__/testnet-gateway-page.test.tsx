import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { TestnetGatewayPage } from '../testnet-gateway-page'
import {
  buildTestnetGatewayModel,
  type CanaryTestnetGatewayData,
} from '../../lib/canary'

describe('TestnetGatewayPage component', () => {
  const verifiedFixture: CanaryTestnetGatewayData = {
    phase: 'phase_300',
    verified: true,
    status: 'TESTNET_GATEWAY_VERIFIED',
    timestamp_ms: 1789543000000,
    timestamp_utc: '2026-09-22T07:30:00.000Z',
    paper_safe: true,
    execution_authority: false,
    circuit_state: 'NORMAL',
    candidates: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
    dispatch_mode: 'DRY_RUN_MOCK',
    tickets: [
      {
        ticket_id: 'ticket-btc-001',
        symbol: 'BTCUSDT',
        target_notional_usdt: 5.0,
        created_at_utc: '2026-09-22T07:29:50.000Z',
        expires_at_utc: '2026-09-22T07:30:00.000Z',
        is_valid: true,
        rejection_reason: null,
        signers: [
          {
            signer_id: 'signer-risk-001',
            role: 'ROLE_RISK_INTERLOCK',
            signature_hex: 'a1b2c3d4e5f60718293a4b5c6d7e8f90',
            signed_at_utc: '2026-09-22T07:29:51.000Z',
            nonce: 'nonce-risk-001',
          },
          {
            signer_id: 'signer-portfolio-001',
            role: 'ROLE_PORTFOLIO_OFFICER',
            signature_hex: 'b2c3d4e5f6a10718293a4b5c6d7e8f90',
            signed_at_utc: '2026-09-22T07:29:52.000Z',
            nonce: 'nonce-port-001',
          },
        ],
      },
      {
        ticket_id: 'ticket-eth-002',
        symbol: 'ETHUSDT',
        target_notional_usdt: 5.0,
        created_at_utc: '2026-09-22T07:29:53.000Z',
        expires_at_utc: '2026-09-22T07:30:03.000Z',
        is_valid: true,
        rejection_reason: null,
        signers: [
          {
            signer_id: 'signer-risk-001',
            role: 'ROLE_RISK_INTERLOCK',
            signature_hex: 'c3d4e5f6a1b20718293a4b5c6d7e8f90',
            signed_at_utc: '2026-09-22T07:29:54.000Z',
            nonce: 'nonce-risk-002',
          },
          {
            signer_id: 'signer-portfolio-001',
            role: 'ROLE_PORTFOLIO_OFFICER',
            signature_hex: 'd4e5f6a1b2c30718293a4b5c6d7e8f90',
            signed_at_utc: '2026-09-22T07:29:55.000Z',
            nonce: 'nonce-port-002',
          },
        ],
      },
    ],
    staged_orders: [
      {
        client_order_id: 'canary-ord-001',
        ticket_id: 'ticket-btc-001',
        symbol: 'BTCUSDT',
        side: 'BUY',
        order_type: 'LIMIT',
        price: 50000.0,
        quantity: 0.0001,
        notional_usdt: 5.0,
        current_state: 'FILLED',
        tau_rtt_ms: 6.25,
        fee_usdt: 0.001,
        dispatched_at_utc: '2026-09-22T07:29:56.000Z',
        filled_at_utc: '2026-09-22T07:29:56.006Z',
        rejection_reason: null,
      },
      {
        client_order_id: 'canary-ord-002',
        ticket_id: 'ticket-eth-002',
        symbol: 'ETHUSDT',
        side: 'BUY',
        order_type: 'LIMIT',
        price: 2500.0,
        quantity: 0.002,
        notional_usdt: 5.0,
        current_state: 'FILLED',
        tau_rtt_ms: 5.8,
        fee_usdt: 0.001,
        dispatched_at_utc: '2026-09-22T07:29:57.000Z',
        filled_at_utc: '2026-09-22T07:29:57.005Z',
        rejection_reason: null,
      },
    ],
    filter_compliance: [
      {
        symbol: 'BTCUSDT',
        compliant: true,
        lot_size_compliant: true,
        price_filter_compliant: true,
        min_notional_compliant: true,
        micro_cap_compliant: true,
        percent_price_compliant: true,
        validated_qty: 0.0001,
        validated_price: 50000.0,
        validated_notional_usdt: 5.0,
        violations: [],
      },
      {
        symbol: 'ETHUSDT',
        compliant: true,
        lot_size_compliant: true,
        price_filter_compliant: true,
        min_notional_compliant: true,
        micro_cap_compliant: true,
        percent_price_compliant: true,
        validated_qty: 0.002,
        validated_price: 2500.0,
        validated_notional_usdt: 5.0,
        violations: [],
      },
    ],
    latency_summary: {
      mean_tau_auth_ms: 1.15,
      mean_tau_filter_ms: 0.75,
      mean_tau_dispatch_ms: 4.25,
      mean_tau_rtt_ms: 6.025,
      max_tau_rtt_ms: 6.25,
      all_sub_50ms_verified: true,
      total_dispatches: 2,
    },
    ledger: {
      starting_equity: 100.0,
      cash: 99.998,
      allocated_margin: 0.0,
      unrealized_pnl: 0.0,
      realized_pnl: -0.002,
      drift: 0.0,
      zero_balance_drift: true,
    },
    solvency: {
      starting_equity_usdt: 100.0,
      cash_usdt: 99.998,
      allocated_margin_usdt: 0.0,
      unrealized_pnl_usdt: 0.0,
      realized_pnl_usdt: -0.002,
      total_equity_usdt: 99.998,
      total_fees_usdt: 0.002,
      total_slippage_usdt: 0.0,
      drift_usdt: 0.0,
      zero_balance_drift_verified: true,
      tolerance_ceiling_usdt: 1e-15,
      solvency_ratio_pct: 100.0,
      cash_reserve_pct: 100.0,
      unencumbered_cash_verified: true,
    },
    upstream_hash: '328a3afdb22b95242614e1ae0269f5bc9fadfba875170e66b2024d6cd7aa0544',
    phase_hash: 'phase300_hash_0000000000000000000000000000000000000000000000000000000000',
    merkle_root: 'merkle300_root_00000000000000000000000000000000000000000000000000000000',
  }

  it('renders top banner and global safety indicators', () => {
    const model = buildTestnetGatewayModel(verifiedFixture)
    const html = renderToString(<TestnetGatewayPage model={model} />)

    expect(html).toContain('Testnet Exchange Gateway')
    expect(html).toContain('PHASE 300')
    expect(html).toContain('TESTNET_GATEWAY_VERIFIED')
    expect(html).toContain('PAPER SAFE: VERIFIED')
    expect(html).toContain('AUTHORITY: OFF')
    expect(html).toContain('ZERO DRIFT: 0.00 USDT')
  })

  it('renders KPI summary cards', () => {
    const model = buildTestnetGatewayModel(verifiedFixture)
    const html = renderToString(<TestnetGatewayPage model={model} />)

    expect(html).toContain('Multi-Sig Quorum')
    expect(html).toContain('Dual-Custody')
    expect(html).toContain('Staged Orders')
    expect(html).toContain('Filter Conformance')
    expect(html).toContain('Round-Trip Latency')
    expect(html).toContain('6.03')
    expect(html).toContain('&lt; 50 ms Limit')
  })

  it('renders Multi-Sig Authorization Tickets queue and signers table', () => {
    const model = buildTestnetGatewayModel(verifiedFixture)
    const html = renderToString(<TestnetGatewayPage model={model} />)

    expect(html).toContain('Multi-Sig Authorization Tickets')
    expect(html).toContain('ticket-btc-001')
    expect(html).toContain('2/2 Quorum Verified')
    expect(html).toContain('ROLE_RISK_INTERLOCK')
    expect(html).toContain('ROLE_PORTFOLIO_OFFICER')
    expect(html).toContain('HMAC-SHA256')
  })

  it('renders Exchange Filter Conformance Matrix with exchange specs', () => {
    const model = buildTestnetGatewayModel(verifiedFixture)
    const html = renderToString(<TestnetGatewayPage model={model} />)

    expect(html).toContain('Exchange Filter Conformance Matrix')
    expect(html).toContain('BINANCE USDⓈ-M')
    expect(html).toContain('LOT_SIZE')
    expect(html).toContain('PRICE_FILTER')
    expect(html).toContain('MIN_NOTIONAL')
    expect(html).toContain('MICRO_CAP')
    expect(html).toContain('Compliant')
  })

  it('renders Order Dispatch Latency Attribution Waterfall', () => {
    const model = buildTestnetGatewayModel(verifiedFixture)
    const html = renderToString(<TestnetGatewayPage model={model} />)

    expect(html).toContain('Order Dispatch Latency Attribution Waterfall')
    expect(html).toContain('Multi-Sig Collation')
    expect(html).toContain('Pre-Dispatch Rules')
    expect(html).toContain('Gateway Transmission')
    expect(html).toContain('Total Pipeline Round-Trip')
    expect(html).toContain('6.25')
  })

  it('renders Staged Order Lifecycle Pipeline table', () => {
    const model = buildTestnetGatewayModel(verifiedFixture)
    const html = renderToString(<TestnetGatewayPage model={model} />)

    expect(html).toContain('Staged Order Lifecycle Pipeline')
    expect(html).toContain('canary-ord-001')
    expect(html).toContain('canary-ord-002')
    expect(html).toContain('FILLED')
    expect(html).toContain('5.00')
  })

  it('renders Mathematical Double-Entry Solvency Meter and Merkle DAG linkage', () => {
    const model = buildTestnetGatewayModel(verifiedFixture)
    const html = renderToString(<TestnetGatewayPage model={model} />)

    expect(html).toContain('Mathematical Double-Entry Solvency Meter')
    expect(html).toContain('TOLERANCE: &lt; 10⁻¹⁵ USDT')
    expect(html).toContain('100.00')
    expect(html).toContain('0.00000000')
    expect(html).toContain('Upstream Phase 299:')
    expect(html).toContain('328a3afdb22b9524...')
  })

  it('handles null/default data safely without crashing', () => {
    const defaultModel = buildTestnetGatewayModel(null)
    const html = renderToString(<TestnetGatewayPage model={defaultModel} />)

    expect(html).toBeDefined()
    expect(html).toContain('Testnet Exchange Gateway')
    expect(html).toContain('PHASE 300')
    expect(html).toContain('Mathematical Double-Entry Solvency Meter')
  })
})
