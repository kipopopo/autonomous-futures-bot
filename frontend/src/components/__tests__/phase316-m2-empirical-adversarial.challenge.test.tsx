import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import App from '@/App'
import { MissionControlHeader } from '../mission-control/mission-control-header'
import { KpiCards } from '../mission-control/kpi-cards'
import { MarketPositionsCard } from '../mission-control/market-positions-card'
import { OrderFeedTable } from '../mission-control/order-feed-table'
import {
  ResearchArchiveDrawer,
  ARCHIVE_PHASES,
} from '../mission-control/research-archive-drawer'
import { ProvenanceBadge } from '../mission-control/provenance-badge'
import {
  formatRelativeTime,
} from '../mission-control/adapter'
import type { ExecutiveDashboardModel } from '../mission-control/types'

// Raw source imports powered by Vite ?raw loader (browser- and type-safe)
import appSource from '@/App.tsx?raw'
import headerSource from '@/components/mission-control/mission-control-header.tsx?raw'
import badgeSource from '@/components/mission-control/provenance-badge.tsx?raw'
import drawerSource from '@/components/mission-control/research-archive-drawer.tsx?raw'
import kpiSource from '@/components/mission-control/kpi-cards.tsx?raw'
import positionsSource from '@/components/mission-control/market-positions-card.tsx?raw'
import chartSource from '@/components/mission-control/pair-candlestick-chart.tsx?raw'
import orderFeedSource from '@/components/mission-control/order-feed-table.tsx?raw'
import adapterSource from '@/components/mission-control/adapter.ts?raw'

// ----------------------------------------------------------------------------
// Baseline Mock Data
// ----------------------------------------------------------------------------
const MOCK_MODEL: ExecutiveDashboardModel = {
  botStatus: {
    state: 'ACTIVE 24/7',
    gatewayMode: 'BINANCE TESTNET GATEWAY',
    circuitBreaker: 'NORMAL',
    tripwiresCount: 0,
    lastSyncedAtMyt: '11 Oct 16:30:00',
    isStreaming: true,
  },
  kpis: {
    totalEquityUsdt: 100.12,
    cashUsdt: 100.12,
    allocatedMarginUsdt: 0.0,
    realizedPnlUsdt: 0.0,
    winRatePct: 100.0,
    totalTrades: 0,
    activeExposureUsdt: 0.0,
    maxExposureCapUsdt: 25.0,
    cashReservePct: 100.0,
    minCashReserveFloorPct: 75.0,
    latencyMs: 14.2,
    interlockBlocksCount: 0,
    balanceDriftUsdt: 0.0,
    isZeroDriftVerified: true,
  },
  positions: [
    {
      symbol: 'SOLUSDT',
      currentPrice: 185.0,
      state: 'SCANNING / STANDBY',
      entryPrice: 0.0,
      size: 0.0,
      notionalUsdt: 0.0,
      marginUsdt: 0.0,
      unrealizedPnlUsdt: 0.0,
      unrealizedPnlPct: 0.0,
      takeProfitPrice: 190.3,
      stopLossPrice: 181.8,
      riskRewardRatio: '1.66',
      atrDistanceTpPct: 2.86,
      atrDistanceSlPct: 1.73,
    },
    {
      symbol: 'ETHUSDT',
      currentPrice: 2750.0,
      state: 'SCANNING / STANDBY',
      entryPrice: 0.0,
      size: 0.0,
      notionalUsdt: 0.0,
      marginUsdt: 0.0,
      unrealizedPnlUsdt: 0.0,
      unrealizedPnlPct: 0.0,
      takeProfitPrice: 2815.0,
      stopLossPrice: 2710.0,
      riskRewardRatio: '1.66',
      atrDistanceTpPct: 2.36,
      atrDistanceSlPct: 1.45,
    },
    {
      symbol: 'BTCUSDT',
      currentPrice: 95000.0,
      state: 'SCANNING / STANDBY',
      entryPrice: 0.0,
      size: 0.0,
      notionalUsdt: 0.0,
      marginUsdt: 0.0,
      unrealizedPnlUsdt: 0.0,
      unrealizedPnlPct: 0.0,
      takeProfitPrice: 97500.0,
      stopLossPrice: 93500.0,
      riskRewardRatio: '1.66',
      atrDistanceTpPct: 2.63,
      atrDistanceSlPct: 1.58,
    },
  ],
  orders: [
    {
      orderId: 'canary-p311-drill-sol-1791554786355',
      symbol: 'SOLUSDT',
      side: 'BUY',
      orderType: 'LIMIT MAKER',
      price: 185.0,
      quantity: 0.03,
      notionalUsdt: 5.55,
      makerFeeUsdt: 0.00111,
      realizedPnlUsdt: 0.0,
      status: 'FILLED',
      timestampMyt: '11 Oct 16:25:00',
    },
  ],
  radar: {
    btcMacroTrend: {
      regime: 'BEARISH',
      ema50_1h: 94800,
      ema200_1h: 95200,
      ema50_4h: 94500,
      ema200_4h: 95100,
      explanation:
        'Long entries temporarily paused by BTC 1h/4h Bearish regime filter for capital protection (EMA 50 < EMA 200).',
    },
    scalperCriteria: {
      priceBelowEma20Atr: 1.2,
      priceBelowEmaThreshold: 2.5,
      priceTriggered: false,
      relativeVolume: 1.1,
      volumeThreshold: 2.2,
      volumeTriggered: false,
      rsi14: 42.5,
      rsiThreshold: 26.0,
      rsiTriggered: false,
      makerFeePct: 0.02,
    },
    hawkesHazard: {
      spectralRadius: 0.4286,
      isNonToxic: true,
      thresholdWarning: 0.8,
      thresholdCritical: 1.0,
      recentHistory: [0.35, 0.42, 0.4286],
    },
  },
  evolutionRadar: {
    activeStrategyFamily: '15m Macro-Confluence Scalper',
    microstructureFilter: 'Hawkes Point-Process Filter',
    activeCandidateId: 'cand-ethusdt-evo-002',
    candidateHealthTier: 'ELITE',
    generation: 'Gen #2',
    rollingSharpe: 1.85,
    winRatePct: 68.5,
    maxDrawdownPct: 4.1,
    hawkesResilienceScore: 0.94,
    allGatesPassed: true,
    gates: [
      {
        id: 'return',
        name: 'Average Return OOS',
        thresholdLabel: '≥ 0.0%',
        actualValueLabel: '+2.4%',
        passed: true,
      },
      {
        id: 'drawdown',
        name: 'Maximum Drawdown OOS',
        thresholdLabel: '≤ 15.0%',
        actualValueLabel: '4.1%',
        passed: true,
      },
      {
        id: 'profit_factor',
        name: 'Profit Factor OOS',
        thresholdLabel: '≥ 1.05',
        actualValueLabel: '1.42',
        passed: true,
      },
    ],
    attributionGauges: [
      {
        id: 'timing_error',
        label: 'Timing Error',
        bps: 12.0,
        thresholdBps: 25.0,
        isOptimal: true,
        description: 'Entry timing efficiency vs optimal bar liquidity',
      },
      {
        id: 'adverse_selection',
        label: 'Adverse Selection',
        bps: 8.5,
        thresholdBps: 20.0,
        isOptimal: true,
        description: 'Post-fill adverse price movement penalty',
      },
      {
        id: 'net_edge',
        label: 'Net Edge',
        bps: 79.5,
        thresholdBps: 50.0,
        isOptimal: true,
        description: 'Pure alpha expectancy after taker/maker fee deductions',
      },
    ],
    totalAutopsies: 18,
    promotedCandidatesCount: 3,
  },
}

// ----------------------------------------------------------------------------
// 70+ Banned Malay / Indonesian Roots & Lexical Items
// ----------------------------------------------------------------------------
export const BANNED_MALAY_ROOTS = [
  'fasa',
  'carta',
  'pesanan',
  'suapan',
  'kemasukan',
  'kecairan',
  'pelaksanaan',
  'kedudukan',
  'pendedahan',
  'kesihatan',
  'ketulenan',
  'untung',
  'kadar',
  'kemenangan',
  'sifar',
  'sekatan',
  'bahaya',
  'pasaran',
  'nisbah',
  'sembunyi',
  'dibuka',
  'dikecilkan',
  'segar',
  'semak',
  'senarai',
  'penapis',
  'yuran',
  'gagal',
  'tiada',
  'memuatkan',
  'baru sahaja',
  'yang lalu',
  'pulangan',
  'purata',
  'maksimum',
  'keuntungan',
  'dagangan',
  'ranap',
  'kilat',
  'kesilapan',
  'kelebihan',
  'pilihan',
  'buruk',
  'lantai',
  'utama',
  'posisi',
  'kawalan',
  'keselamatan',
  'pembelajaran',
  'autopsi',
  'arkib',
  'penyelidikan',
  'degupan',
  'jantung',
  'lejar',
  'dwi-kemasukan',
  'berterusan',
  'calon',
  'mutasi',
  'genom',
  'simulasi',
  'bayangan',
  'pintu',
  'promosi',
  'perdagangan',
  'baki',
  'ekuiti',
  'tunai',
  'tersedia',
  'diperuntukkan',
  'jumlah',
  'bersih',
  'nyata',
  'belum',
  'rizab',
  'tertutup',
  'terbuka',
  'simpanan',
  'sejarah',
  'pantau',
  'harga',
  'saiz',
  'sasaran',
  'kategori',
  'kemaskini',
  'kunci',
  'batal',
  'tutup',
  'padam',
  'cari',
  'maklumat',
  'terkini',
  'penyegerakan',
  'berjaya',
  'oleh',
  'untuk',
  'pada',
  'dari',
  'daripada',
  'dengan',
  'atau',
  'adalah',
  'iaitu',
  'dalam',
  'luar',
  'atas',
  'bawah',
  'kiri',
  'kanan',
  'tambah',
  'kurang',
  'baharu',
  'lama',
  'telah',
  'sedang',
  'akan',
  'pernah',
  'boleh',
  'tidak',
  'bukan',
  'jangan',
  'sila',
  'tolong',
  'kembali',
  'seterusnya',
  'sebelum',
  'selepas',
  'semasa',
  'ketika',
  'antara',
  'setiap',
  'banyak',
  'sedikit',
  'tinggi',
  'rendah',
  'cepat',
  'lambat',
  'mudah',
  'sukar',
  'betul',
  'salah',
  'pasti',
  'mungkin',
  'hanya',
  'juga',
  'lagi',
  'masih',
  'sudah',
  'selalu',
  'jarang',
  'kadang',
  'mana',
  'siapa',
  'apa',
  'bila',
  'kenapa',
  'mengapa',
  'bagaimana',
]

// The 9 files owned by Milestone M2 mapped to their raw text content
const M2_OWNED_SOURCES: Record<string, string> = {
  'src/App.tsx': appSource,
  'src/components/mission-control/mission-control-header.tsx': headerSource,
  'src/components/mission-control/provenance-badge.tsx': badgeSource,
  'src/components/mission-control/research-archive-drawer.tsx': drawerSource,
  'src/components/mission-control/kpi-cards.tsx': kpiSource,
  'src/components/mission-control/market-positions-card.tsx': positionsSource,
  'src/components/mission-control/pair-candlestick-chart.tsx': chartSource,
  'src/components/mission-control/order-feed-table.tsx': orderFeedSource,
  'src/components/mission-control/adapter.ts': adapterSource,
}

describe('Empirical Adversarial Challenge Suite: Milestone M2 Localization', () => {
  // --------------------------------------------------------------------------
  // Challenge 1: Banned Malay Roots Scan (70+ Dictionary)
  // --------------------------------------------------------------------------
  describe('Challenge 1: Exhaustive Dictionary Scan of 70+ Banned Malay Roots', () => {
    it('verifies the banned roots dictionary contains at least 70 distinct terms', () => {
      const uniqueRoots = new Set(BANNED_MALAY_ROOTS)
      expect(uniqueRoots.size).toBeGreaterThanOrEqual(70)
    })

    Object.entries(M2_OWNED_SOURCES).forEach(([relPath, content]) => {
      it(`scans ${relPath} for banned Malay roots and identifies any residual tokens`, () => {
        const violations: Array<{ root: string; line: number; text: string }> = []

        const lines = content.split('\n')
        lines.forEach((lineText: string, lineIdx: number) => {
          for (const root of BANNED_MALAY_ROOTS) {
            const pattern = new RegExp(`\\b${root.replace('-', '\\-')}\\b`, 'i')
            if (pattern.test(lineText)) {
              violations.push({
                root,
                line: lineIdx + 1,
                text: lineText.trim(),
              })
            }
          }
        })

        // All files (including App.tsx after M3 line 839 localization) are strictly 100% clean
        expect(violations.length).toBe(0)
      })
    })

    it('asserts that user-facing rendered UI from all components contains strictly 0 banned roots', () => {
      // Test rendered HTML output across all M2 components
      const renderedComponents = [
        renderToString(<App />),
        renderToString(
          <MissionControlHeader
            status={MOCK_MODEL.botStatus}
            onRefresh={() => {}}
            isLoading={false}
          />,
        ),
        renderToString(<KpiCards kpis={MOCK_MODEL.kpis} />),
        renderToString(<MarketPositionsCard positions={MOCK_MODEL.positions} />),
        renderToString(<OrderFeedTable orders={MOCK_MODEL.orders} />),
        renderToString(
          <ResearchArchiveDrawer
            isOpen={true}
            onClose={() => {}}
            onSelectPhase={() => {}}
          />,
        ),
        renderToString(<ProvenanceBadge source="LIVE EXCHANGE" />),
      ]

      const aggregateHtml = renderedComponents.join('\n')

      const renderedViolations: string[] = []
      for (const root of BANNED_MALAY_ROOTS) {
        const pattern = new RegExp(`>\\s*[^<]*\\b${root.replace('-', '\\-')}\\b[^<]*<`, 'i')
        if (pattern.test(aggregateHtml)) {
          renderedViolations.push(root)
        }
      }

      expect(renderedViolations).toEqual([])
    })
  })

  // --------------------------------------------------------------------------
  // Challenge 2: formatRelativeTime Corner Cases & Stress Probes
  // --------------------------------------------------------------------------
  describe('Challenge 2: formatRelativeTime Corner Cases & Stress Probes', () => {
    const fixedNow = 1728640000000 // Fixed reference timestamp in ms

    it('returns empty string for undefined and null inputs', () => {
      expect(formatRelativeTime(undefined, fixedNow)).toBe('')
      expect(formatRelativeTime(null, fixedNow)).toBe('')
    })

    it('returns empty string for number 0, string "0", and empty string', () => {
      expect(formatRelativeTime(0, fixedNow)).toBe('')
      expect(formatRelativeTime('0', fixedNow)).toBe('')
      expect(formatRelativeTime('', fixedNow)).toBe('')
    })

    it('returns empty string for negative timestamps and invalid dates', () => {
      expect(formatRelativeTime(-1000, fixedNow)).toBe('')
      expect(formatRelativeTime('invalid-string-token', fixedNow)).toBe('')
      expect(formatRelativeTime(new Date('invalid date string'), fixedNow)).toBe('')
      expect(formatRelativeTime(Number.NaN, fixedNow)).toBe('')
    })

    it('handles future timestamps (negative time delta) safely by clamping to "Just now"', () => {
      const future1s = fixedNow + 1000
      const future10s = fixedNow + 10_000
      const future1h = fixedNow + 3600_000
      expect(formatRelativeTime(future1s, fixedNow)).toBe('Just now')
      expect(formatRelativeTime(future10s, fixedNow)).toBe('Just now')
      expect(formatRelativeTime(future1h, fixedNow)).toBe('Just now')
    })

    it('handles exact zero delta and fresh sub-5-second timestamps as "Just now"', () => {
      expect(formatRelativeTime(fixedNow, fixedNow)).toBe('Just now')
      expect(formatRelativeTime(fixedNow - 999, fixedNow)).toBe('Just now')
      expect(formatRelativeTime(fixedNow - 1000, fixedNow)).toBe('Just now')
      expect(formatRelativeTime(fixedNow - 4000, fixedNow)).toBe('Just now')
      expect(formatRelativeTime(fixedNow - 4999, fixedNow)).toBe('Just now')
    })

    it('formats boundary and intermediate seconds [5s..59s] correctly with "s ago"', () => {
      expect(formatRelativeTime(fixedNow - 5000, fixedNow)).toBe('5s ago')
      expect(formatRelativeTime(fixedNow - 15_000, fixedNow)).toBe('15s ago')
      expect(formatRelativeTime(fixedNow - 30_000, fixedNow)).toBe('30s ago')
      expect(formatRelativeTime(fixedNow - 59_000, fixedNow)).toBe('59s ago')
      expect(formatRelativeTime(fixedNow - 59_999, fixedNow)).toBe('59s ago')
    })

    it('formats boundary and intermediate minutes [1m..59m] correctly with "m ago"', () => {
      expect(formatRelativeTime(fixedNow - 60_000, fixedNow)).toBe('1m ago')
      expect(formatRelativeTime(fixedNow - 300_000, fixedNow)).toBe('5m ago')
      expect(formatRelativeTime(fixedNow - 1800_000, fixedNow)).toBe('30m ago')
      expect(formatRelativeTime(fixedNow - 3599_000, fixedNow)).toBe('59m ago')
    })

    it('formats boundary and intermediate hours [1h..23h] correctly with "h ago"', () => {
      expect(formatRelativeTime(fixedNow - 3600_000, fixedNow)).toBe('1h ago')
      expect(formatRelativeTime(fixedNow - 10800_000, fixedNow)).toBe('3h ago')
      expect(formatRelativeTime(fixedNow - 43200_000, fixedNow)).toBe('12h ago')
      expect(formatRelativeTime(fixedNow - 86399_000, fixedNow)).toBe('23h ago')
    })

    it('formats boundary and multi-day spans [1d..] correctly with "d ago"', () => {
      expect(formatRelativeTime(fixedNow - 86400_000, fixedNow)).toBe('1d ago')
      expect(formatRelativeTime(fixedNow - 172800_000, fixedNow)).toBe('2d ago')
      expect(formatRelativeTime(fixedNow - 7 * 86400_000, fixedNow)).toBe('7d ago')
      expect(formatRelativeTime(fixedNow - 365 * 86400_000, fixedNow)).toBe('365d ago')
    })

    it('correctly handles leap year dates and Date objects', () => {
      // Leap day: 2024-02-29T12:00:00Z
      const leapDay = new Date('2024-02-29T12:00:00Z')
      const leapDayMs = leapDay.getTime()

      // 30 seconds later
      expect(formatRelativeTime(leapDay, leapDayMs + 30_000)).toBe('30s ago')
      // 5 minutes later
      expect(formatRelativeTime(leapDay, leapDayMs + 300_000)).toBe('5m ago')
      // 2 days later (crossing into March 2 in a leap year)
      expect(formatRelativeTime(leapDay, leapDayMs + 2 * 86400_000)).toBe('2d ago')
    })

    it('demonstrates type polymorphism consistency (Date vs number vs numeric string)', () => {
      const ts = fixedNow - 120_000 // 2 minutes ago
      const fromNumber = formatRelativeTime(ts, fixedNow)
      const fromString = formatRelativeTime(ts.toString(), fixedNow)
      const fromDate = formatRelativeTime(new Date(ts), fixedNow)

      expect(fromNumber).toBe('2m ago')
      expect(fromString).toBe('2m ago')
      expect(fromDate).toBe('2m ago')
    })
  })

  // --------------------------------------------------------------------------
  // Challenge 3: Exact English Rendering Verification of Navigation Shell & Header
  // --------------------------------------------------------------------------
  describe('Challenge 3: Exact English Rendering of Shell Navigation & Top Bar Header', () => {
    it('renders App navigation tabs and drawer buttons strictly in English', () => {
      const html = renderToString(<App />)

      // Navigation tab names in English
      expect(html).toContain('🚀 Executive Overview')
      expect(html).toContain('📊 Live Positions &amp; Markets')
      expect(html).toContain('⚡ Trade Log &amp; Executions')
      expect(html).toContain('🛡️ Risk Controls &amp; Solvency')
      expect(html).toContain('🧠 Strategy Evolution &amp; Autopsy')
      expect(html).toContain('📁 Research Archives')
      expect(html).toContain('23 Phases')

      // Bottom bar navigation in English
      expect(html).toContain('>Overview<')
      expect(html).toContain('>Positions<')
      expect(html).toContain('>Trade Log<')
      expect(html).toContain('>Safety<')
      expect(html).toContain('>Evolution<')
      expect(html).toContain('>Archives<')

      // Header branding in English
      expect(html).toContain('Autonomous')
      expect(html).toContain('Futures')
      expect(html).toContain('Trading Mission Control')
      expect(html).toContain('ACTIVE 24/7')

      // Assert zero residual Malay navigation strings
      expect(html).not.toContain('Dashboard Utama')
      expect(html).not.toContain('Pasaran &amp; Posisi')
      expect(html).not.toContain('Pasaran & Posisi')
      expect(html).not.toContain('Log Perdagangan')
      expect(html).not.toContain('Kawalan Keselamatan')
      expect(html).not.toContain('Pembelajaran &amp; Autopsi')
      expect(html).not.toContain('Arkib Penyelidikan')
    })

    it('renders MissionControlHeader with English status badges, clock, and refresh button', () => {
      const html = renderToString(
        <MissionControlHeader
          status={MOCK_MODEL.botStatus}
          onRefresh={() => {}}
          isLoading={false}
        />,
      )

      expect(html).toContain('ACTIVE 24/7')
      expect(html).toContain('BINANCE TESTNET GATEWAY')
      expect(html).toContain('CIRCUIT: NORMAL (0 tripwires)')
      expect(html).toContain('Telegram: Active')
      expect(html).toContain('STREAMING')
      expect(html).toContain('MYT (UTC+8)')
      expect(html).toMatch(/Sync:\s*(?:<!-- -->)?\s*11 Oct 16:30:00/)
      expect(html).toContain('Refresh')

      // Assert zero residual Malay header strings
      expect(html).not.toContain('Segar')
      expect(html).not.toContain('Memuatkan')
      expect(html).not.toContain('Aktif')
    })

    it('renders MissionControlHeader in loading state with "Syncing…"', () => {
      const html = renderToString(
        <MissionControlHeader
          status={MOCK_MODEL.botStatus}
          onRefresh={() => {}}
          isLoading={true}
        />,
      )

      expect(html).toContain('Syncing…')
      expect(html).not.toContain('Menyegerak')
    })
  })

  // --------------------------------------------------------------------------
  // Challenge 4: Exact English Rendering of KPI Cards
  // --------------------------------------------------------------------------
  describe('Challenge 4: Exact English Rendering of KPI Cards', () => {
    it('renders KpiCards with exact English titles, labels, tooltips, and sub-metrics', () => {
      const html = renderToString(<KpiCards kpis={MOCK_MODEL.kpis} />)

      // Card 1
      expect(html).toContain('Total Balance &amp; Equity')
      expect(html).toContain('Binance Futures Wallet (Protected Capital Reserve)')
      expect(html).toContain('Available Cash:')
      expect(html).toContain('Allocated Margin:')

      // Card 2
      expect(html).toContain('Net Realized PnL &amp; Win Rate')
      expect(html).toContain('0 Completed Trades')
      expect(html).toContain('Fee Savings:')

      // Card 3
      expect(html).toContain('Active Exposure &amp; Capital Sizing')
      expect(html).toContain('/ $25.00 Max Cap')
      expect(html).toContain('Cash Reserve:')
      expect(html).toContain('(Floor ≥ 75%)')
      expect(html).toContain('Order Cap:')
      expect(html).toContain('≤ $5.00 USDT / child')

      // Card 4
      expect(html).toContain('System Health &amp; Solvency')
      expect(html).toContain('Zero-Drift Solvency')
      expect(html).toContain('Gateway Latency:')
      expect(html).toContain('Interlock Blocks:')
      expect(html).toContain('0 Interlock Blocks (0 Hazards)')

      // Negative assertion: Malay KPI strings
      expect(html).not.toContain('Baki Keseluruhan')
      expect(html).not.toContain('Kadar Kemenangan')
      expect(html).not.toContain('Pendedahan Aktif')
      expect(html).not.toContain('Kesihatan Sistem')
      expect(html).not.toContain('Tunai Tersedia')
      expect(html).not.toContain('Margin Diperuntukkan')
    })
  })

  // --------------------------------------------------------------------------
  // Challenge 5: Exact English Rendering of Market Watch & Order Feed
  // --------------------------------------------------------------------------
  describe('Challenge 5: Exact English Rendering of Market Positions & Order Feed', () => {
    it('renders MarketPositionsCard with English headers, metric labels, and pair pills', () => {
      const html = renderToString(
        <MarketPositionsCard positions={MOCK_MODEL.positions} />,
      )

      // Card header
      expect(html).toContain('Live Positions &amp; Markets')
      expect(html).toContain('Perpetual Pairs')
      expect(html).toContain('1.66 : 1 R:R Ratio')
      expect(html).toContain('Interactive Chart (All)')

      // Filter pills
      expect(html).toContain('>ALL<')
      expect(html).toContain('>SOL<')
      expect(html).toContain('>ETH<')
      expect(html).toContain('>BTC<')

      // Position metrics
      expect(html).toContain('SCANNING / STANDBY')
      expect(html).toContain('Mark Price:')
      expect(html).toContain('Take Profit (TP 2.0x ATR):')
      expect(html).toContain('Stop Loss (SL 1.2x ATR):')
      expect(html).toContain('Risk/Reward Ratio:')
      expect(html).toContain('Interactive Chart')

      // Negative assertion
      expect(html).not.toContain('Kedudukan Langsung')
      expect(html).not.toContain('Harga Semasa')
      expect(html).not.toContain('Nisbah Risiko')
      expect(html).not.toContain('Carta Interaktif')
    })

    it('renders OrderFeedTable with English headers, table columns, and unit labels', () => {
      const html = renderToString(<OrderFeedTable orders={MOCK_MODEL.orders} />)

      // Title & subtitle
      expect(html).toContain('Recent Orders &amp; Execution Feed')
      expect(html).toContain('Maker 0.02%')
      expect(html).toContain(
        'Maker limit execution without taker fee drag, logged in Malaysia Time (MYT)',
      )

      // Table headers
      expect(html).toContain('Time (MYT)')
      expect(html).toContain('Pair')
      expect(html).toContain('Side / Type')
      expect(html).toContain('Price &amp; Quantity')
      expect(html).toContain('Notional Value')
      expect(html).toContain('Maker Fee (0.02%)')
      expect(html).toContain('Realized PnL')
      expect(html).toContain('Status')

      // Row data
      expect(html).toContain('0.03 units')
      expect(html).toContain('FILLED')

      // Negative assertion
      expect(html).not.toContain('Pesanan Terkini')
      expect(html).not.toContain('Masa (MYT)')
      expect(html).not.toContain('Nilai Notional')
      expect(html).not.toContain('Yuran Pembuat')
      expect(html).not.toMatch(/\bunit\b(?!s)/)
    })

    it('renders OrderFeedTable empty state in clean English', () => {
      const html = renderToString(<OrderFeedTable orders={[]} />)
      expect(html).toContain('No order records for this filter.')
      expect(html).not.toContain('Tiada rekod pesanan')
    })
  })

  // --------------------------------------------------------------------------
  // Challenge 6: Exact English Rendering of Research Archive Drawer
  // --------------------------------------------------------------------------
  describe('Challenge 6: Exact English Rendering of Research Archive Drawer & Catalog', () => {
    it('verifies all 23 ARCHIVE_PHASES are titled and categorized strictly in English', () => {
      expect(ARCHIVE_PHASES.length).toBe(23)

      const validCategories = [
        'Research & Modeling',
        'Microstructure & Markets',
        'Execution & Risk Controls',
        'Accounting & Foundations',
      ]

      ARCHIVE_PHASES.forEach((phase) => {
        expect(validCategories).toContain(phase.categoryLabel)
        expect(phase.phaseNumber).toMatch(/^(Phase \d+[A-Z]?|Foundations)$/)
        expect(phase.title.length).toBeGreaterThan(5)
        expect(phase.description.length).toBeGreaterThan(10)

        // Ensure zero banned words in catalog items
        for (const root of BANNED_MALAY_ROOTS) {
          const pattern = new RegExp(`\\b${root}\\b`, 'i')
          expect(pattern.test(phase.title)).toBe(false)
          expect(pattern.test(phase.description)).toBe(false)
          expect(pattern.test(phase.categoryLabel)).toBe(false)
        }
      })
    })

    it('renders ResearchArchiveDrawer modal in English when opened', () => {
      const html = renderToString(
        <ResearchArchiveDrawer
          isOpen={true}
          onClose={() => {}}
          onSelectPhase={() => {}}
        />,
      )

      expect(html).toContain('Research Archives')
      expect(html).toContain('23 Historical Phases')
      expect(html).toContain('Search phases, keywords, algorithms, or metrics…')
      expect(html).toContain('All (23)')
      expect(html).toContain('Modeling (6)')
      expect(html).toContain('Markets (3)')
      expect(html).toContain('Execution &amp; Risk (12)')
      expect(html).toContain('Accounting (2)')
      expect(html).toContain('Open Phase')
      expect(html).toContain('Close Archive')
      expect(html).toContain('All cryptographic DAG &amp; audit trail proofs preserved')

      // Negative assertion
      expect(html).not.toContain('Arkib Penyelidikan')
      expect(html).not.toContain('Buka Fasa')
      expect(html).not.toContain('Tutup Arkib')
      expect(html).not.toContain('Cari fasa')
    })
  })

  // --------------------------------------------------------------------------
  // Challenge 7: Provenance Badge Tooltips & Badges
  // --------------------------------------------------------------------------
  describe('Challenge 7: Provenance Badges English Contracts', () => {
    it('renders LIVE EXCHANGE, DAEMON 24/7, and RESEARCH ARTIFACT with English tooltips', () => {
      const liveHtml = renderToString(<ProvenanceBadge source="LIVE EXCHANGE" />)
      expect(liveHtml).toContain('LIVE EXCHANGE')
      expect(liveHtml).toContain('Live data from Binance Futures')

      const daemonHtml = renderToString(<ProvenanceBadge source="DAEMON 24/7" />)
      expect(daemonHtml).toContain('DAEMON 24/7')
      expect(daemonHtml).toContain('Live telemetry from Autonomous Futures trading daemon')

      const researchHtml = renderToString(
        <ProvenanceBadge source="RESEARCH ARTIFACT / SIMULATION" />,
      )
      expect(researchHtml).toContain('RESEARCH ARTIFACT / SIMULATION')
      expect(researchHtml).toContain('Historical research &amp; simulation artifacts')
    })
  })
})
