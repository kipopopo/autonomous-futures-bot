import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { buildExecutiveDashboardModel, formatRelativeTime } from '../mission-control/adapter'
import App from '@/App'
import { ExecutiveDashboard } from '../mission-control/executive-dashboard'
import { KpiCards } from '../mission-control/kpi-cards'
import { MarketPositionsCard } from '../mission-control/market-positions-card'
import { OrderFeedTable } from '../mission-control/order-feed-table'
import { MissionControlHeader } from '../mission-control/mission-control-header'
import { ProvenanceBadge } from '../mission-control/provenance-badge'
import { ResearchArchiveDrawer, ARCHIVE_PHASES } from '../mission-control/research-archive-drawer'
import type { ExecutiveDashboardModel, PositionTelemetry, OrderFeedItem } from '../mission-control/types'
import {
  buildProductionLaunchModel,
  buildLiveMarketModel,
  buildBracketPositionsModel,
  buildMicrostructureModel,
  type ProductionLaunchModel,
} from '@/lib/canary'

// Comprehensive dictionary of Malay/Indonesian words to forbid in M2-owned components
const FORBIDDEN_MALAY_PATTERNS = [
  /\bFasa\b/i,
  /\bCarta\b/i,
  /\bPesanan\b/i,
  /\bSuapan\b/i,
  /\bKemasukan\b/i,
  /\bKecairan\b/i,
  /\bPelaksanaan\b/i,
  /\bKedudukan\b/i,
  /\bPendedahan\b/i,
  /\bKesihatan\b/i,
  /\bKetulenan\b/i,
  /\bUntung\b/i,
  /\bKadar\b/i,
  /\bKemenangan\b/i,
  /\bSifar\b/i,
  /\bSekatan\b/i,
  /\bBahaya\b/i,
  /\bPasaran\b/i,
  /\bNisbah\b/i,
  /\bSembunyi\b/i,
  /\bDibuka\b/i,
  /\bDikecilkan\b/i,
  /\bSegar\b/i,
  /\bSemak\b/i,
  /\bSenarai\b/i,
  /\bPenapis\b/i,
  /\bYuran\b/i,
  /\bGagal\b/i,
  /\bTiada\b/i,
  /\bMemuatkan\b/i,
  /\bBaru sahaja\b/i,
  /\byang lalu\b/i,
  /\bPulangan\b/i,
  /\bPurata\b/i,
  /\bMaksimum\b/i,
  /\bKeuntungan\b/i,
  /\bDagangan\b/i,
  /\bRanap\b/i,
  /\bKilat\b/i,
  /\bKesilapan\b/i,
  /\bKelebihan\b/i,
  /\bPilihan\b/i,
  /\bBuruk\b/i,
  /\bLantai\b/i,
  /\bUtama\b/i,
  /\bKeselamatan\b/i,
  /\bPembelajaran\b/i,
  /\bAutopsi\b/i,
  /\bArkib\b/i,
  /\bPenyelidikan\b/i,
  /\bBuka\b/i,
  /\bTutup\b/i,
]

function assertNoMalayLeakage(html: string, contextDescription: string) {
  for (const pattern of FORBIDDEN_MALAY_PATTERNS) {
    const match = html.match(pattern)
    if (match) {
      throw new Error(
        `Malay leakage detected in ${contextDescription}: matched "${match[0]}" via pattern ${pattern.toString()}`,
      )
    }
  }
}

describe('Empirical Adversarial Stress Suite: Milestone M2 (challenger_m2_2)', () => {
  const dummyDate = new Date('2026-10-11T08:00:00Z')

  describe('Adversarial Stress 1: Extreme KpiCards SSR Rendering', () => {
    it('handles zero balance ($0.00 equity, $0.00 cash, 0% reserve) without crashing or Malay leakage', () => {
      const zeroKpis: ExecutiveDashboardModel['kpis'] = {
        totalEquityUsdt: 0.0,
        cashUsdt: 0.0,
        allocatedMarginUsdt: 0.0,
        cashReservePct: 0.0,
        minCashReserveFloorPct: 75.0,
        realizedPnlUsdt: 0.0,
        winRatePct: 0.0,
        totalTrades: 0,
        activeExposureUsdt: 0.0,
        maxExposureCapUsdt: 25.0,
        latencyMs: 0.0,
        interlockBlocksCount: 0,
        balanceDriftUsdt: 0.0,
        isZeroDriftVerified: true,
      }

      const html = renderToString(<KpiCards kpis={zeroKpis} />)
      expect(html).toContain('$0.00')
      expect(html).toContain('0.0% Win Rate')
      expect(html).toContain('0 Completed Trades')
      expect(html).toContain('Total Balance &amp; Equity')
      expect(html).toContain('Net Realized PnL &amp; Win Rate')
      expect(html).toContain('Active Exposure &amp; Capital Sizing')
      expect(html).toContain('System Health &amp; Solvency')
      expect(html).toContain('Zero-Drift Solvency')
      expect(html).toContain('Available Cash:')
      expect(html).toContain('Allocated Margin:')
      expect(html).toContain('Fee Savings:')
      expect(html).toContain('Cash Reserve:')
      expect(html).toContain('Gateway Latency:')
      expect(html).toContain('Interlock Blocks:')
      assertNoMalayLeakage(html, 'KpiCards with zero balance')
    })

    it('handles extreme negative PnL (-$12,345.6789) and massive negative margin safely', () => {
      const negativeKpis: ExecutiveDashboardModel['kpis'] = {
        totalEquityUsdt: 87.6543,
        cashUsdt: 87.6543,
        allocatedMarginUsdt: 0.0,
        cashReservePct: 100.0,
        minCashReserveFloorPct: 75.0,
        realizedPnlUsdt: -12345.6789,
        winRatePct: 0.0,
        totalTrades: 42,
        activeExposureUsdt: 0.0,
        maxExposureCapUsdt: 25.0,
        latencyMs: 499.9,
        interlockBlocksCount: 15,
        balanceDriftUsdt: 0.0,
        isZeroDriftVerified: true,
      }

      const html = renderToString(<KpiCards kpis={negativeKpis} />)
      expect(html).toContain('$-12,345.6789')
      expect(html).toContain('42 Completed Trades')
      expect(html).toContain('15 Interlock Blocks')
      assertNoMalayLeakage(html, 'KpiCards with extreme negative PnL')
    })

    it('handles max exposure cap breach ($25.00 and $100.00) with proper color classes and text', () => {
      const overExposureKpis: ExecutiveDashboardModel['kpis'] = {
        totalEquityUsdt: 100.0,
        cashUsdt: 5.0,
        allocatedMarginUsdt: 25.0,
        cashReservePct: 5.0,
        minCashReserveFloorPct: 75.0,
        realizedPnlUsdt: 15.5,
        winRatePct: 85.5,
        totalTrades: 20,
        activeExposureUsdt: 25.0,
        maxExposureCapUsdt: 25.0,
        latencyMs: 12.4,
        interlockBlocksCount: 1,
        balanceDriftUsdt: 0.0,
        isZeroDriftVerified: true,
      }

      const html = renderToString(<KpiCards kpis={overExposureKpis} />)
      expect(html).toContain('$25.00')
      expect(html).toContain('/ $25.00 Max Cap')
      expect(html).toContain('5.0% (Floor ≥ 75%)')
      expect(html).toContain('text-amber-400') // unhealthy reserve indicator
      assertNoMalayLeakage(html, 'KpiCards with max exposure cap')
    })
  })

  describe('Adversarial Stress 2: Extreme MarketPositionsCard SSR Rendering', () => {
    it('handles completely empty positions array without error or Malay fallback', () => {
      const html = renderToString(<MarketPositionsCard positions={[]} />)
      expect(html).toContain('Live Positions &amp; Markets')
      expect(html).toContain('Perpetual Pairs')
      expect(html).toContain('1.66 : 1 R:R Ratio')
      expect(html).toContain('Interactive Chart (All)')
      assertNoMalayLeakage(html, 'MarketPositionsCard empty positions')
    })

    it('handles 8 pairs with extreme price scales (sub-penny DOGE vs $1.5M BTC)', () => {
      const extremePositions: PositionTelemetry[] = [
        {
          symbol: 'BTCUSDT',
          currentPrice: 1500000.5,
          state: 'LONG',
          size: 0.00001,
          notionalUsdt: 15.0,
          marginUsdt: 15.0,
          unrealizedPnlUsdt: 2.55,
          unrealizedPnlPct: 17.0,
          entryPrice: 1250000.0,
          takeProfitPrice: 1600000.0,
          stopLossPrice: 1100000.0,
          riskRewardRatio: '1.66:1',
        },
        {
          symbol: 'DOGEUSDT',
          currentPrice: 0.00004567,
          state: 'SHORT',
          size: 100000,
          notionalUsdt: 4.567,
          marginUsdt: 4.567,
          unrealizedPnlUsdt: -0.234,
          unrealizedPnlPct: -5.12,
          entryPrice: 0.000048,
          takeProfitPrice: 0.00004,
          stopLossPrice: 0.000052,
          riskRewardRatio: '1.66:1',
        },
        {
          symbol: 'SOLUSDT',
          currentPrice: 185.25,
          state: 'SCANNING / STANDBY',
          size: 0,
          notionalUsdt: 0,
          marginUsdt: 0,
          unrealizedPnlUsdt: 0,
          unrealizedPnlPct: 0,
          entryPrice: 0,
          takeProfitPrice: 0,
          stopLossPrice: 0,
          riskRewardRatio: '—',
        },
      ]

      const html = renderToString(
        <MarketPositionsCard positions={extremePositions} initialExpanded={false} />,
      )
      expect(html).toContain('BTCUSDT')
      expect(html).toContain('DOGEUSDT')
      expect(html).toContain('SOLUSDT')
      expect(html).toContain('Scanning 15m liquidity (Capitulation Sweep)...')
      expect(html).toContain('Entry Price:')
      expect(html).toContain('Take Profit (TP 2.0x ATR):')
      expect(html).toContain('Stop Loss (SL 1.2x ATR):')
      expect(html).toContain('Risk/Reward Ratio:')
      assertNoMalayLeakage(html, 'MarketPositionsCard extreme prices')
    })

    it('renders expanded candlestick drawers for all pairs without throwing', () => {
      const positions: PositionTelemetry[] = [
        {
          symbol: 'ETHUSDT',
          currentPrice: 2850.0,
          state: 'SCANNING / STANDBY',
          size: 0,
          notionalUsdt: 0,
          marginUsdt: 0,
          unrealizedPnlUsdt: 0,
          unrealizedPnlPct: 0,
          entryPrice: 0,
          takeProfitPrice: 0,
          stopLossPrice: 0,
          riskRewardRatio: '—',
        },
      ]

      const html = renderToString(
        <MarketPositionsCard positions={positions} initialExpanded={true} defaultInterval="15m" />,
      )
      expect(html).toContain('Interactive Chart')
      expect(html).toContain('Expanded')
      expect(html).toContain('EMA 50')
      expect(html).toContain('EMA 200')
      expect(html).toContain('Volume')
      expect(html).toContain('15m')
      expect(html).toContain('1h')
      expect(html).toContain('OHLC:')
      assertNoMalayLeakage(html, 'MarketPositionsCard expanded chart drawer')
    })
  })

  describe('Adversarial Stress 3: Extreme OrderFeedTable SSR Rendering', () => {
    it('handles empty order feed with clean English placeholder', () => {
      const html = renderToString(<OrderFeedTable orders={[]} />)
      expect(html).toContain('Recent Orders &amp; Execution Feed')
      expect(html).toContain('Maker 0.02%')
      expect(html).toContain('No order records for this filter.')
      assertNoMalayLeakage(html, 'OrderFeedTable empty orders')
    })

    it('handles mixed profit and loss orders with micro fees and large unit quantities', () => {
      const orders: OrderFeedItem[] = [
        {
          orderId: 'canary-test-p316-001',
          timestampMyt: '2026-10-11 16:30:00',
          symbol: 'DOGEUSDT',
          side: 'BUY',
          orderType: 'LIMIT MAKER',
          price: 0.0854,
          quantity: 58.548,
          notionalUsdt: 5.0,
          makerFeeUsdt: 0.001,
          realizedPnlUsdt: 0.0,
          status: 'FILLED',
        },
        {
          orderId: 'canary-test-p316-002',
          timestampMyt: '2026-10-11 16:31:00',
          symbol: 'SOLUSDT',
          side: 'SELL',
          orderType: 'LIMIT MAKER',
          price: 185.0,
          quantity: 0.027,
          notionalUsdt: 4.995,
          makerFeeUsdt: 0.000999,
          realizedPnlUsdt: -0.1542,
          status: 'FILLED',
        },
        {
          orderId: 'canary-test-p316-003',
          timestampMyt: '2026-10-11 16:32:00',
          symbol: 'BTCUSDT',
          side: 'SELL',
          orderType: 'LIMIT MAKER',
          price: 95500.0,
          quantity: 0.00005,
          notionalUsdt: 4.775,
          makerFeeUsdt: 0.000955,
          realizedPnlUsdt: 0.4521,
          status: 'FILLED',
        },
      ]

      const html = renderToString(<OrderFeedTable orders={orders} />)
      expect(html).toContain('58.548 units')
      expect(html).toContain('$-0.1542')
      expect(html).toContain('+$0.4521')
      expect(html).toContain('Time (MYT)')
      expect(html).toContain('Maker Fee (0.02%)')
      expect(html).toContain('Realized PnL')
      assertNoMalayLeakage(html, 'OrderFeedTable with mixed orders')
    })
  })

  describe('Adversarial Stress 4: ResearchArchiveDrawer SSR Rendering & Search Invariants', () => {
    it('returns null when isOpen is false', () => {
      const html = renderToString(<ResearchArchiveDrawer isOpen={false} onClose={() => {}} />)
      expect(html).toBe('')
    })

    it('renders all 23 phases in English when isOpen is true', () => {
      const html = renderToString(<ResearchArchiveDrawer isOpen={true} onClose={() => {}} />)
      expect(html).toContain('Research Archives')
      expect(html).toContain('23 Historical Phases')
      expect(html).toContain('All (23)')
      expect(html).toContain('Modeling (6)')
      expect(html).toContain('Markets (3)')
      expect(html).toContain('Execution &amp; Risk (12)')
      expect(html).toContain('Accounting (2)')
      expect(html).toContain('Open Phase')
      expect(html).toContain('Close Archive')
      expect(html).toContain('All cryptographic DAG &amp; audit trail proofs preserved')

      // Verify all 23 phases are present in ARCHIVE_PHASES catalog
      expect(ARCHIVE_PHASES.length).toBe(23)
      for (const phase of ARCHIVE_PHASES) {
        expect(html).toContain(phase.phaseNumber)
        // Check title with HTML entity escaping accounted for
        const escapedTitle = phase.title.replace(/&/g, '&amp;')
        expect(html).toContain(escapedTitle)
      }

      assertNoMalayLeakage(html, 'ResearchArchiveDrawer open state')
    })
  })

  describe('Adversarial Stress 5: formatRelativeTime and Telemetry Fallback Invariants', () => {
    it('formats all relative time windows into clean English with zero Malay leaks', () => {
      const now = 1000000000000 // reference ms
      expect(formatRelativeTime(now - 1000, now)).toBe('Just now')
      expect(formatRelativeTime(now - 5000, now)).toBe('5s ago')
      expect(formatRelativeTime(now - 45000, now)).toBe('45s ago')
      expect(formatRelativeTime(now - 120000, now)).toBe('2m ago')
      expect(formatRelativeTime(now - 3600000, now)).toBe('1h ago')
      expect(formatRelativeTime(now - 7200000, now)).toBe('2h ago')
      expect(formatRelativeTime(now - 86400000, now)).toBe('1d ago')
      expect(formatRelativeTime(now - 172800000, now)).toBe('2d ago')
      // Future or zero/negative timestamp returns safe fallback
      expect(formatRelativeTime(now + 10000, now)).toBe('Just now')
      expect(formatRelativeTime(0, now)).toBe('')
      expect(formatRelativeTime(-100, now)).toBe('')
      expect(formatRelativeTime(undefined, now)).toBe('')
    })
  })

  describe('Adversarial Stress 6: MissionControlHeader & ProvenanceBadge SSR Invariants', () => {
    it('renders MissionControlHeader in English with zero Malay text', () => {
      const status: ExecutiveDashboardModel['botStatus'] = {
        state: 'ACTIVE 24/7',
        gatewayMode: 'BINANCE TESTNET GATEWAY',
        circuitBreaker: 'NORMAL',
        tripwiresCount: 0,
        lastSyncedAtMyt: '16:30:00 MYT',
        isStreaming: true,
      }

      const html = renderToString(
        <MissionControlHeader status={status} onRefresh={() => {}} isLoading={false} />,
      )
      expect(html).toContain('Telegram: Active')
      expect(html).toContain('ACTIVE 24/7')
      expect(html).toContain('NORMAL')
      expect(html).toContain('Refresh')
      assertNoMalayLeakage(html, 'MissionControlHeader')
    })

    it('renders ProvenanceBadge with English tooltips for all 3 data sources', () => {
      const sources = ['LIVE EXCHANGE', 'DAEMON 24/7', 'RESEARCH ARTIFACT / SIMULATION'] as const
      for (const src of sources) {
        const html = renderToString(<ProvenanceBadge source={src} />)
        expect(html).toContain(src)
        assertNoMalayLeakage(html, `ProvenanceBadge for ${src}`)
      }
    })
  })

  describe('Adversarial Stress 7: buildExecutiveDashboardModel under Hostile/Corrupted API Payloads', () => {
    it('handles empty fallback models across all arguments gracefully and renders ExecutiveDashboard', () => {
      const fallbackLaunch = buildProductionLaunchModel(null)
      const adapted = buildExecutiveDashboardModel(
        fallbackLaunch,
        buildLiveMarketModel(null),
        buildBracketPositionsModel(null),
        buildMicrostructureModel(null),
        {},
        dummyDate,
      )

      expect(adapted).toBeDefined()
      expect(adapted.kpis.activeExposureUsdt).toBe(0)
      expect(adapted.kpis.totalEquityUsdt).toBe(100.0)
      expect(adapted.positions.length).toBe(8)
      expect(adapted.botStatus.state).toBe('ACTIVE 24/7')

      // Verify that M2-owned subcomponents rendered from this adapted model leak ZERO Malay
      const kpisHtml = renderToString(<KpiCards kpis={adapted.kpis} />)
      assertNoMalayLeakage(kpisHtml, 'KpiCards from adapted fallback')

      const positionsHtml = renderToString(<MarketPositionsCard positions={adapted.positions} />)
      assertNoMalayLeakage(positionsHtml, 'MarketPositionsCard from adapted fallback')

      const ordersHtml = renderToString(<OrderFeedTable orders={adapted.orders} />)
      assertNoMalayLeakage(ordersHtml, 'OrderFeedTable from adapted fallback')

      const headerHtml = renderToString(
        <MissionControlHeader status={adapted.botStatus} onRefresh={() => {}} isLoading={false} />,
      )
      assertNoMalayLeakage(headerHtml, 'MissionControlHeader from adapted fallback')

      // Full ExecutiveDashboard renders safely
      const fullHtml = renderToString(
        <ExecutiveDashboard model={adapted} onRefresh={() => {}} isLoading={false} />,
      )
      expect(fullHtml).toContain('Autonomous Futures')
      expect(fullHtml).toContain('ACTIVE 24/7')
    })

    it('handles malformed numbers, NaN, and negative exposure in productionLaunch model without crash', () => {
      const dirtyLaunch = {
        ...buildProductionLaunchModel(null),
        aggregateExposureUsdt: -5.0, // Invalid negative exposure
        candidateAllocations: undefined as unknown as [],
        solvency: {
          total_equity_usdt: -10.0,
          cash_usdt: 0.0,
          allocated_margin_usdt: 0.0,
          unrealized_pnl_usdt: 0.0,
          cash_reserve_pct: -50.0,
          balance_drift_usdt: 0.0,
          zero_balance_drift_verified: true,
        },
      }

      const adapted = buildExecutiveDashboardModel(
        dirtyLaunch as unknown as ProductionLaunchModel,
        buildLiveMarketModel(null),
        buildBracketPositionsModel(null),
        buildMicrostructureModel(null),
        {},
        dummyDate,
      )

      // Verify KPI cards under malformed numbers
      const kpisHtml = renderToString(<KpiCards kpis={adapted.kpis} />)
      expect(kpisHtml).toBeDefined()
      assertNoMalayLeakage(kpisHtml, 'KpiCards with malformed numbers')

      // Verify Market positions under malformed numbers
      const positionsHtml = renderToString(<MarketPositionsCard positions={adapted.positions} />)
      expect(positionsHtml).toBeDefined()
      assertNoMalayLeakage(positionsHtml, 'MarketPositionsCard with malformed numbers')

      // Full dashboard does not throw
      const fullHtml = renderToString(
        <ExecutiveDashboard model={adapted} onRefresh={() => {}} isLoading={false} />,
      )
      expect(fullHtml).toBeDefined()
    })
  })

  describe('Adversarial Stress 8: Full Navigation Shell & App Component SSR Rendering', () => {
    it('SSR renders <App /> in loading state without crashing or leaking Malay strings', () => {
      const html = renderToString(<App />)

      // Primary navigation tabs
      expect(html).toContain('🚀 Executive Overview')
      expect(html).toContain('📊 Live Positions &amp; Markets')
      expect(html).toContain('⚡ Trade Log &amp; Executions')
      expect(html).toContain('🛡️ Risk Controls &amp; Solvency')
      expect(html).toContain('🧠 Strategy Evolution &amp; Autopsy')
      expect(html).toContain('📁 Research Archives')
      expect(html).toContain('23 Phases')

      // Brand mark & title
      expect(html).toContain('Autonomous')
      expect(html).toContain('Trading Mission Control')

      // Initial loading state
      expect(html).toContain('Synchronizing live data &amp; telemetry')
      expect(html).toContain(
        'Connecting to read-only telemetry services for health status, double-entry ledger balance, and strategy signals.',
      )

      // Mobile bottom nav
      expect(html).toContain('Overview')
      expect(html).toContain('Positions')
      expect(html).toContain('Trade Log')
      expect(html).toContain('Safety')
      expect(html).toContain('Evolution')
      expect(html).toContain('Archives')

      // Malay text leakage check on rendered App HTML
      assertNoMalayLeakage(html, 'Full <App /> SSR markup')
    })
  })
})

