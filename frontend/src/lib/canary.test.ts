import { describe, expect, it } from 'vitest'

import {
  buildAccountingModel,
  buildLiveMarketModel,
  buildMicrostructureModel,
  buildPaperExecutionModel,
  buildRiskModel,
  buildStrategyActivationModel,
  type CanaryAccountingResponse,
  type CanaryHawkesResponse,
  type CanaryLiveMarketResponse,
  type CanaryPaperExecutionResponse,
  type CanaryRiskResponse,
  type CanaryStrategyActivationResponse,
} from './canary'

describe('canary models', () => {
  describe('buildMicrostructureModel', () => {
    it('handles null data safely', () => {
      const model = buildMicrostructureModel(null)
      expect(model.phase).toBe('—')
      expect(model.currentRegime).toBe('UNKNOWN')
      expect(model.isSupercritical).toBe(false)
      expect(model.isHawkesElevated).toBe(false)
      expect(model.snapshots).toHaveLength(0)
    })

    it('processes Hawkes snapshots and detects elevated or supercritical regimes', () => {
      const fixture: CanaryHawkesResponse = {
        verified: true,
        phase: 'phase_291',
        timestamp_utc: '2026-09-21T03:29:37Z',
        candidates: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        current_regime: 'SUPERCRITICAL_CASCADE',
        max_spectral_radius: 1.394679,
        max_jump_intensity: 1.68,
        snapshots: [
          {
            record_id: 1,
            track_id: 'track_1',
            symbol: 'BTCUSDT',
            timestamp_utc: '2026-09-21T03:29:37Z',
            jump_intensity: '0.350000',
            branching_ratio: '0.2500',
            spectral_radius: '0.491677',
            self_excitation_alpha: '0.12',
            cross_excitation_json: '{}',
            cascade_state: 'NORMAL',
            regime: 'NOMINAL',
            pacing_interval_ms: 100,
            limit_offset_cushion_bps: '0.0',
            full_branching_matrix_json: '[[0.25]]',
          },
          {
            record_id: 2,
            track_id: 'track_3',
            symbol: 'SOLUSDT',
            timestamp_utc: '2026-09-21T03:29:38Z',
            jump_intensity: '1.680000',
            branching_ratio: '1.2000',
            spectral_radius: '1.394679',
            self_excitation_alpha: '0.45',
            cross_excitation_json: '{}',
            cascade_state: 'SEVERE_PREDATORY_FRONT_RUNNING',
            regime: 'SUPERCRITICAL_CASCADE',
            pacing_interval_ms: 1000,
            limit_offset_cushion_bps: '5.0',
            full_branching_matrix_json: '[[1.20]]',
          },
        ],
      }

      const model = buildMicrostructureModel(fixture)
      expect(model.phase).toBe('phase_291')
      expect(model.isSupercritical).toBe(true)
      expect(model.isHawkesElevated).toBe(true)
      expect(model.snapshots).toHaveLength(2)
      expect(model.latestBySymbol['BTCUSDT'].regime).toBe('NOMINAL')
      expect(model.latestBySymbol['SOLUSDT'].regime).toBe('SUPERCRITICAL_CASCADE')
    })
  })

  describe('buildRiskModel', () => {
    it('handles null data safely', () => {
      const model = buildRiskModel(null)
      expect(model.phase).toBe('—')
      expect(model.circuitState).toBe('UNKNOWN')
      expect(model.latestHeartbeat).toBeNull()
      expect(model.totalBlocks).toBe(0)
    })

    it('builds risk telemetry and tracks interlocks', () => {
      const fixture: CanaryRiskResponse = {
        verified: true,
        phase: 'phase_291',
        circuit_state: 'NORMAL',
        aggregate_exposure_cap_usdt: '60.00',
        individual_micro_notional_cap_usdt: '5.00',
        intra_phase_loss_ceiling_usdt: '7.0',
        max_allowed_heartbeat_age_ms: 500,
        heartbeats: [
          {
            record_id: 1,
            track_id: 'track_1',
            server_time_ms: 1789447964946,
            local_time_ms: 1789447964946,
            latency_ms: 18.5,
            clock_skew_ms: 0.1,
            status: 'HEALTHY',
            is_healthy: true,
            details: 'Heartbeat OK',
            timestamp_utc: '2026-09-21T03:29:37Z',
          },
        ],
        interlock_events: [
          {
            event_id: 'ev-1',
            timestamp_utc: '2026-09-21T03:29:37Z',
            track_id: 'track_2',
            interlock_type: 'HAWKES_CASCADE_BURST_PACING',
            allowed: false,
            symbol: 'SOLUSDT',
            notional_usdt: '5.00',
            details: 'Order throttled by Hawkes cascade',
          },
        ],
        total_interlock_blocks: 1,
      }

      const model = buildRiskModel(fixture)
      expect(model.phase).toBe('phase_291')
      expect(model.exposureCapUsdt).toBe('60.00')
      expect(model.microCapUsdt).toBe('5.00')
      expect(model.totalBlocks).toBe(1)
      expect(model.latestHeartbeat?.status).toBe('HEALTHY')
      expect(model.latestHeartbeat?.latency_ms).toBe(18.5)
    })
  })

  describe('buildAccountingModel', () => {
    it('handles null data safely', () => {
      const model = buildAccountingModel(null)
      expect(model.phase).toBe('—')
      expect(model.isZeroDrift).toBe(false)
      expect(model.tracks).toHaveLength(0)
    })

    it('builds zero-drift double-entry verification model', () => {
      const fixture: CanaryAccountingResponse = {
        verified: true,
        phase: 'phase_291',
        starting_capital_usdt: '100.00',
        final_cash_usdt: '99.99460000',
        final_equity_usdt: '99.99460000',
        realized_pnl_usdt: '-0.00540000',
        allocated_margin_usdt: '0.0',
        unrealized_pnl_usdt: '0.0',
        total_fees_usdt: '0.010889',
        total_slippage_usdt: '0.000000',
        drift_usdt: '0E-8',
        zero_balance_drift: true,
        tracks: [
          {
            track_id: 'track_1',
            track_name: 'Ingress Replay',
            status: 'SUCCESS',
            starting_equity_usdt: '100.00',
            final_cash_usdt: '99.99460000',
            allocated_margin_usdt: '0.0',
            unrealized_pnl_usdt: '0.0',
            realized_pnl_usdt: '-0.00540000',
            total_fees_usdt: '0.00540000',
            total_slippage_usdt: '0.0',
            drift_usdt: '0E-8',
            zero_balance_drift: true,
            orders_placed_count: 9,
            orders_filled_count: 9,
            orders_cancelled_count: 0,
            orders_rejected_count: 0,
            interlock_blocks_count: 0,
          },
        ],
        recent_balance_snapshots: [
          {
            snapshot_id: 'snap-1',
            timestamp_utc: '2026-09-21T03:29:37Z',
            track_id: 'track_1',
            cash_usdt: '100.00',
            allocated_margin_usdt: '0.0',
            unrealized_pnl_usdt: '0.0',
            realized_pnl_usdt: '0.0',
            starting_equity_usdt: '100.00',
            drift_usdt: '0.00',
            zero_balance_drift: true,
            trigger_event: 'DAEMON_INITIALIZED',
          },
        ],
      }

      const model = buildAccountingModel(fixture)
      expect(model.phase).toBe('phase_291')
      expect(model.isZeroDrift).toBe(true)
      expect(model.drift).toBe('0E-8')
      expect(model.startingCapital).toBe('100.00')
      expect(model.finalCash).toBe('99.99460000')
      expect(model.tracks).toHaveLength(1)
      expect(model.snapshots).toHaveLength(1)
    })
  })

  describe('buildLiveMarketModel', () => {
    it('handles null data safely', () => {
      const model = buildLiveMarketModel(null)
      expect(model.phase).toBe('—')
      expect(model.verified).toBe(false)
      expect(model.isFresh).toBe(false)
      expect(model.isPaperSafe).toBe(true)
      expect(model.isExecutionOff).toBe(true)
      expect(model.recentTrades).toHaveLength(0)
      expect(model.gatewayHealth).toBeNull()
    })

    it('processes live market responses with depth, trades, and mark prices', () => {
      const fixture: CanaryLiveMarketResponse = {
        verified: true,
        phase: 'phase_292',
        status: 'STREAMING',
        timestamp_utc: '2026-09-21T05:00:00Z',
        candidates: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        paper_safe: true,
        execution_authority: false,
        gateway_health: {
          status: 'CONNECTED',
          is_healthy: true,
          heartbeat_age_ms: 120,
          latency_ms: 10,
          clock_skew_ms: 2,
          reconnect_count: 0,
          packet_gap_count: 0,
          total_messages_received: 100,
          timestamp_utc: '2026-09-21T05:00:00Z',
        },
        orderbooks: {
          BTCUSDT: {
            symbol: 'BTCUSDT',
            bids: [{ price: '65000.00', quantity: '1.500' }],
            asks: [{ price: '65001.00', quantity: '2.000' }],
            last_update_id: 1001,
            event_time_utc: '2026-09-21T05:00:00Z',
            best_bid: '65000.00',
            best_ask: '65001.00',
            spread_bps: '0.1538',
          },
        },
        recent_trades: [
          {
            symbol: 'BTCUSDT',
            aggregate_trade_id: 5001,
            price: '65000.50',
            quantity: '0.250',
            trade_time_utc: '2026-09-21T05:00:00Z',
            is_buyer_maker: false,
          },
        ],
        mark_prices: {
          BTCUSDT: {
            symbol: 'BTCUSDT',
            mark_price: '65000.20',
            index_price: '65000.00',
            estimated_settle_price: '65000.10',
            funding_rate: '0.00010000',
            next_funding_time_utc: '2026-09-21T08:00:00Z',
            timestamp_utc: '2026-09-21T05:00:00Z',
          },
        },
        stream_stats: {
          total_messages: 100,
        },
      }

      const model = buildLiveMarketModel(fixture)
      expect(model.phase).toBe('phase_292')
      expect(model.verified).toBe(true)
      expect(model.isFresh).toBe(true)
      expect(model.isPaperSafe).toBe(true)
      expect(model.isExecutionOff).toBe(true)
      expect(model.candidates).toEqual(['BTCUSDT', 'ETHUSDT', 'SOLUSDT'])
      expect(model.orderbooks.BTCUSDT.best_bid).toBe('65000.00')
      expect(model.recentTrades).toHaveLength(1)
      expect(model.markPrices.BTCUSDT.funding_rate).toBe('0.00010000')
      expect(model.gatewayHealth?.is_healthy).toBe(true)
    })
  })

  describe('buildPaperExecutionModel', () => {
    it('handles null data safely', () => {
      const model = buildPaperExecutionModel(null)
      expect(model.phase).toBe('—')
      expect(model.verified).toBe(false)
      expect(model.circuitState).toBe('UNKNOWN')
      expect(model.isPaperSafe).toBe(true)
      expect(model.isExecutionOff).toBe(true)
      expect(model.isZeroDrift).toBe(true)
      expect(model.recentChildOrders).toHaveLength(0)
      expect(model.recentFills).toHaveLength(0)
    })

    it('processes paper execution response correctly', () => {
      const fixture: CanaryPaperExecutionResponse = {
        verified: true,
        phase: 'phase_294',
        status: 'STREAMING',
        circuit_state: 'NORMAL',
        timestamp_utc: '2026-09-21T07:00:00Z',
        paper_safe: true,
        execution_authority: false,
        candidates: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        active_exposure_usdt: '4.55',
        aggregate_exposure_cap_usdt: '60.00',
        individual_micro_notional_cap_usdt: '5.00',
        intra_phase_loss_ceiling_usdt: '7.00',
        unencumbered_cash_reserve_pct: '0.9545',
        order_stats: {
          total_parent_orders: 2,
          total_child_orders: 10,
          filled_child_orders: 9,
          cancelled_orders: 1,
          rejected_orders: 0,
          total_fees_usdt: '0.008000',
          total_slippage_usdt: '0.000000',
        },
        matching_stats: {
          passive_maker_fills_count: 8,
          aggressive_taker_fills_count: 1,
          avg_queue_wait_ms: 150.0,
          fill_ratio: 0.9,
        },
        ledger: {
          starting_equity_usdt: '100.00000000',
          cash_usdt: '99.99200000',
          allocated_margin_usdt: '4.50000000',
          unrealized_pnl_usdt: '0.01000000',
          realized_pnl_usdt: '0.00200000',
          drift_usdt: '0.0000000000000000',
          zero_balance_drift: true,
        },
        recent_child_orders: [
          {
            client_order_id: 'ord_1',
            parent_order_id: 'p_1',
            child_index: 0,
            symbol: 'BTCUSDT',
            side: 'BUY',
            order_type: 'LIMIT',
            price: '65000.00',
            quantity: '0.00007',
            notional_usdt: '4.55',
            status: 'FILLED',
            created_time_ms: 1726902000000,
            timestamp_utc: '2026-09-21T07:00:00Z',
          },
        ],
        recent_fills: [
          {
            fill_id: 'fill_1',
            client_order_id: 'ord_1',
            parent_order_id: 'p_1',
            child_index: 0,
            symbol: 'BTCUSDT',
            side: 'BUY',
            fill_price: '65000.00',
            fill_quantity: '0.00007',
            fill_notional_usdt: '4.55',
            fee_usdt: '0.00091000',
            fee_rate: '0.0002',
            is_maker: true,
            slippage_bps: '0.0',
            fill_time_ms: 1726902000010,
            timestamp_utc: '2026-09-21T07:00:00Z',
          },
        ],
        recent_interlocks: [],
      }

      const model = buildPaperExecutionModel(fixture)
      expect(model.phase).toBe('phase_294')
      expect(model.verified).toBe(true)
      expect(model.circuitState).toBe('NORMAL')
      expect(model.isPaperSafe).toBe(true)
      expect(model.isExecutionOff).toBe(true)
      expect(model.isZeroDrift).toBe(true)
      expect(model.recentChildOrders).toHaveLength(1)
      expect(model.recentFills).toHaveLength(1)
      expect(model.orderStats.total_child_orders).toBe(10)
      expect(model.matchingStats.passive_maker_fills_count).toBe(8)
      expect(model.ledger.starting_equity_usdt).toBe('100.00000000')
    })
  })

  describe('buildStrategyActivationModel', () => {
    it('handles null data safely with default values', () => {
      const model = buildStrategyActivationModel(null)
      expect(model.phase).toBe('—')
      expect(model.verified).toBe(false)
      expect(model.status).toBe('UNAVAILABLE')
      expect(model.circuitState).toBe('UNKNOWN')
      expect(model.isPaperSafe).toBe(true)
      expect(model.isExecutionOff).toBe(true)
      expect(model.isZeroDrift).toBe(true)
      expect(model.candidates).toHaveLength(3)
      expect(model.candidates[0].candidate_id).toBe('cand-btcusdt-dcb-002')
      expect(model.candidates[1].candidate_id).toBe('cand-ethusdt-dcb-003')
      expect(model.candidates[2].candidate_id).toBe('cand-solusdt-rgb-001')
      expect(model.signals).toHaveLength(0)
      expect(model.isHawkesSupercritical).toBe(false)
      expect(model.isHeartbeatStale).toBe(false)
      expect(model.isMarginBreached).toBe(false)
      expect(model.childOrdersCount).toBe(0)
      expect(model.fillsCount).toBe(0)
    })

    it('processes verified strategy activation response correctly', () => {
      const fixture: CanaryStrategyActivationResponse = {
        verified: true,
        phase: 'phase_295',
        status: 'STREAMING',
        timestamp_ms: 1789447964946,
        paper_safe: true,
        execution_authority: false,
        candidates: [
          {
            candidate_id: 'cand-btcusdt-dcb-002',
            symbol: 'BTCUSDT',
            status: 'PROMOTED',
            average_return_pct: 0.045,
            worst_drawdown_pct: 0.021,
            profit_factor: 1.85,
            trade_count: 42,
            window_count: 5,
            qualified: true,
          },
          {
            candidate_id: 'cand-ethusdt-dcb-003',
            symbol: 'ETHUSDT',
            status: 'PROMOTED',
            average_return_pct: 0.038,
            worst_drawdown_pct: 0.019,
            profit_factor: 1.72,
            trade_count: 36,
            window_count: 5,
            qualified: true,
          },
          {
            candidate_id: 'cand-solusdt-rgb-001',
            symbol: 'SOLUSDT',
            status: 'PROMOTED',
            average_return_pct: 0.052,
            worst_drawdown_pct: 0.028,
            profit_factor: 1.91,
            trade_count: 51,
            window_count: 5,
            qualified: true,
          },
        ],
        signals: [
          {
            signal_id: 'sig-001',
            candidate_id: 'cand-btcusdt-dcb-002',
            timestamp_ms: 1789447964900,
            symbol: 'BTCUSDT',
            side: 'BUY',
            order_type: 'LIMIT',
            limit_price: '65000.00',
            notional_usdt: 4.50,
            client_order_id: 'ord-001',
          },
        ],
        vetoes: {
          hawkes_supercritical: false,
          gateway_heartbeat_stale: false,
          margin_headroom_breach: false,
          clock_skew_breach: false,
          intra_phase_loss_lockout: false,
        },
        ledger: {
          starting_equity: 100.0,
          cash: 95.5,
          allocated_margin: 4.5,
          unrealized_pnl: 0.05,
          realized_pnl: 0.02,
          drift: 0.0,
          zero_balance_drift: true,
        },
        upstream_hash: '3f04f21a64c4c23db2be92c10b47fe7343e2646271c66299b9cf9c63fb93cb89',
        phase_hash: '2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae',
        child_orders_count: 10,
        fills_count: 9,
        circuit_state: 'NORMAL',
      }

      const model = buildStrategyActivationModel(fixture)
      expect(model.phase).toBe('phase_295')
      expect(model.verified).toBe(true)
      expect(model.status).toBe('STREAMING')
      expect(model.circuitState).toBe('NORMAL')
      expect(model.isPaperSafe).toBe(true)
      expect(model.isExecutionOff).toBe(true)
      expect(model.isZeroDrift).toBe(true)
      expect(model.candidates).toHaveLength(3)
      expect(model.candidates[0].candidate_id).toBe('cand-btcusdt-dcb-002')
      expect(model.candidates[0].qualified).toBe(true)
      expect(model.signals).toHaveLength(1)
      expect(model.signals[0].signal_id).toBe('sig-001')
      expect(model.isHawkesSupercritical).toBe(false)
      expect(model.isHeartbeatStale).toBe(false)
      expect(model.isMarginBreached).toBe(false)
      expect(model.childOrdersCount).toBe(10)
      expect(model.fillsCount).toBe(9)
      expect(model.upstreamHash).toBe('3f04f21a64c4c23db2be92c10b47fe7343e2646271c66299b9cf9c63fb93cb89')
      expect(model.phaseHash).toBe('2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae')
    })
  })
})
