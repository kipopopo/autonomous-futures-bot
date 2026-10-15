import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'
import { PairPriceTickersCard } from '../mission-control/pair-price-tickers-card'
import type { PositionTelemetry, BtcMacroTrend, IctPairSignal } from '../mission-control/types'

describe('Empirical Challenger M2: PairPriceTickersCard Stress & Robustness Suite', () => {
  const cleanHtml = (raw: string) => raw.replace(/<!-- -->/g, '')

  const FORBIDDEN_MALAY_PATTERNS = [
    /\bFasa\b/i, /\bCarta\b/i, /\bPesanan\b/i, /\bSuapan\b/i, /\bKemasukan\b/i,
    /\bKecairan\b/i, /\bPelaksanaan\b/i, /\bKedudukan\b/i, /\bPendedahan\b/i,
    /\bKesihatan\b/i, /\bKetulenan\b/i, /\bUntung\b/i, /\bKadar\b/i, /\bKemenangan\b/i,
    /\bSifar\b/i, /\bSekatan\b/i, /\bBahaya\b/i, /\bPasaran\b/i, /\bNisbah\b/i,
    /\bDagangan\b/i, /\bLantai\b/i, /\bKeselamatan\b/i, /\bArkib\b/i, /\bPenyelidikan\b/i,
  ]

  const makeMockPosition = (overrides: Partial<PositionTelemetry>): PositionTelemetry => ({
    symbol: 'SOLUSDT',
    currentPrice: 150.0,
    state: 'SCANNING / STANDBY',
    entryPrice: 0,
    size: 0,
    notionalUsdt: 0,
    marginUsdt: 0,
    unrealizedPnlUsdt: 0,
    unrealizedPnlPct: 0,
    takeProfitPrice: 0,
    stopLossPrice: 0,
    riskRewardRatio: '0',
    ...overrides,
  })

  it('1. Empty positions array: renders all 12 canonical pairs in Standby state', () => {
    const html = cleanHtml(renderToString(<PairPriceTickersCard positions={[]} />))

    expect(html).toContain('Live Pair Tickers &amp; Opportunity Radar')
    expect(html).toContain('12 Perpetual Pairs')
    expect(html).toContain('All 12 Standby / Scanning')
    expect(html).toContain('LIVE EXCHANGE')

    const canonicalSymbols = [
      'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'DOGEUSDT', 'BNBUSDT', 'XRPUSDT',
      'SUIUSDT', 'AVAXUSDT', 'NEARUSDT', 'LINKUSDT', 'APTUSDT', 'ADAUSDT',
    ]
    for (const sym of canonicalSymbols) {
      expect(html).toContain(sym.replace(/USDT$/, ''))
    }
  })

  it('2. Active positions: renders LONG and SHORT positions with accurate notional amounts', () => {
    const mockPositions: PositionTelemetry[] = [
      makeMockPosition({
        symbol: 'SOLUSDT',
        state: 'LONG',
        size: 10,
        entryPrice: 150.0,
        currentPrice: 155.0,
        markPrice: 154.8,
        unrealizedPnlUsdt: 50.0,
        unrealizedPnlPct: 3.33,
        notionalUsdt: 1550.0,
        marginUsdt: 155.0,
        riskRewardRatio: '1:1.66',
        basisPct: 1.25,
        fundingRate: 0.0001,
      }),
      makeMockPosition({
        symbol: 'ETHUSDT',
        state: 'SHORT',
        size: 2,
        entryPrice: 2600.0,
        currentPrice: 2550.0,
        markPrice: 2552.0,
        unrealizedPnlUsdt: 100.0,
        unrealizedPnlPct: 1.96,
        notionalUsdt: 5100.0,
        marginUsdt: 510.0,
        riskRewardRatio: '1:1.66',
        basisPct: -0.75,
        fundingRate: 0.00015,
      }),
    ]

    const html = cleanHtml(renderToString(<PairPriceTickersCard positions={mockPositions} />))

    expect(html).toContain('🟢 LONG ($1550.00)')
    expect(html).toContain('🔴 SHORT ($5100.00)')
    expect(html).toContain('+1.25%')
    expect(html).toContain('-0.75%')
    expect(html).toContain('FR: 0.0100%')
    expect(html).toContain('FR: 0.0150%')
  })

  it('3. Extreme & sub-penny numerical formatting precision in tickers', () => {
    const extremePositions: PositionTelemetry[] = [
      makeMockPosition({
        symbol: 'DOGEUSDT',
        currentPrice: 0.00004218,
        markPrice: 0.0000422,
      }),
      makeMockPosition({
        symbol: 'ADAUSDT',
        currentPrice: 4.5678,
        markPrice: 4.568,
      }),
      makeMockPosition({
        symbol: 'BTCUSDT',
        currentPrice: 98765.43,
        markPrice: 98760.0,
      }),
    ]

    const html = cleanHtml(renderToString(<PairPriceTickersCard positions={extremePositions} />))

    // Sub-penny (<0.1) -> 6 decimals
    expect(html).toContain('$0.000042')
    // Low (<10) -> 4 decimals
    expect(html).toContain('$4.5678')
    // Large (>=1000) -> locale string with 2 decimals
    expect(html).toContain('$98,765.43')
  })

  it('4. Dynamic Entry Signals: computes active entry counts and badges', () => {
    const mockPositions: PositionTelemetry[] = [
      makeMockPosition({
        symbol: 'SOLUSDT',
        currentPrice: 150.0,
      }),
    ]

    const mockIctSignals: Record<string, IctPairSignal> = {
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
        active_pda: null,
        cisd: { m5_cisd_price: 150, m1_cisd_price: 151 },
        targets: {
          ote_lower: 149,
          ote_sweet_spot: 150,
          ote_upper: 151,
          stop_loss: 145,
          stdv_2_0: 155,
          stdv_4_0: 160,
          take_profit_partial: 155,
          take_profit_final: 160,
        },
        candidate: {
          candidate_id: 'sol-ict-v1',
          health_tier: 'ELITE',
          generation: 1,
          ote_bounds: '62-79',
          stdv_tp1: 2.0,
          stdv_tp2: 4.0,
          swing_lookback: 20,
          fvg_threshold_pct: '0.1',
        },
        invalidation_reason: '',
      },
    }

    const mockBtcMacroTrend: BtcMacroTrend = {
      regime: 'BULLISH ALIGNED',
      ema50_1h: 65000,
      ema200_1h: 64000,
      ema50_4h: 63000,
      ema200_4h: 62000,
      explanation: 'Bullish trend alignment',
    }

    const html = cleanHtml(
      renderToString(
        <PairPriceTickersCard
          positions={mockPositions}
          ictSignals={mockIctSignals}
          btcMacroTrend={mockBtcMacroTrend}
        />,
      ),
    )

    // Should detect active signal
    expect(html).toContain('1 Entry Signal Active')
    expect(html).toContain('ICT')
  })

  it('5. Non-canonical pair extension: handles arbitrary unlisted pairs seamlessly', () => {
    const unlistedPositions: PositionTelemetry[] = [
      makeMockPosition({
        symbol: 'CUSTOMUSDT',
        state: 'LONG',
        currentPrice: 12.34,
        size: 4,
        notionalUsdt: 50.0,
        marginUsdt: 5.0,
        entryPrice: 12.00,
        unrealizedPnlUsdt: 1.0,
        unrealizedPnlPct: 2.0,
        riskRewardRatio: '1:2',
      }),
    ]

    const html = cleanHtml(renderToString(<PairPriceTickersCard positions={unlistedPositions} />))
    expect(html).toContain('CUSTOM')
    expect(html).toContain('$12.34')
  })

  it('6. Accessibility & ARIA metadata: interactive buttons, testids, and labels properly rendered', () => {
    const mockPositions: PositionTelemetry[] = [
      makeMockPosition({
        symbol: 'SOLUSDT',
        currentPrice: 150.0,
      }),
    ]

    const html = cleanHtml(renderToString(<PairPriceTickersCard positions={mockPositions} />))

    expect(html).toContain('data-testid="pair-price-tickers-card"')
    expect(html).toContain('data-testid="pair-ticker-card-solusdt"')
    expect(html).toContain('data-testid="pair-entry-badge-solusdt"')
    expect(html).toContain('role="button"')
    expect(html).toContain('aria-label="Open details for SOLUSDT"')
    expect(html).toContain('tabindex="0"')
  })

  it('7. Clean Localization Invariant: zero forbidden Malay words in rendered HTML', () => {
    const mockPositions: PositionTelemetry[] = [
      makeMockPosition({
        symbol: 'ETHUSDT',
        state: 'SHORT',
        currentPrice: 2600.0,
        entryPrice: 2650.0,
        size: 0.2,
        unrealizedPnlUsdt: -12.5,
        unrealizedPnlPct: -1.5,
        notionalUsdt: 500.0,
        marginUsdt: 50.0,
        riskRewardRatio: '1:1.66',
        basisPct: -1.2,
        fundingRate: 0.0001,
      }),
    ]

    const html = cleanHtml(renderToString(<PairPriceTickersCard positions={mockPositions} />))

    for (const pattern of FORBIDDEN_MALAY_PATTERNS) {
      const match = html.match(pattern)
      expect(match, `Forbidden Malay word leaked: ${match?.[0]}`).toBeNull()
    }
  })

  it('8. Extreme malformed/null values & negative PnL do not throw during SSR', () => {
    const malformedPositions: PositionTelemetry[] = [
      makeMockPosition({
        symbol: 'SOLUSDT',
        state: 'LONG',
        currentPrice: undefined as unknown as number,
        markPrice: null as unknown as number,
        entryPrice: 100,
        size: 0.25,
        unrealizedPnlUsdt: -99999.99,
        unrealizedPnlPct: -150.5,
        notionalUsdt: 25.0,
        marginUsdt: 5.0,
        riskRewardRatio: '1:1.66',
        fundingRate: undefined,
        basisPct: undefined,
      }),
    ]

    const html = cleanHtml(renderToString(<PairPriceTickersCard positions={malformedPositions} />))

    expect(html).toContain('$0.00')
    expect(html).toContain('Mark: $0.00')
    expect(html).toContain('🟢 LONG ($25.00)')
    expect(html).toContain('+0.00%')
    expect(html).toContain('FR: 0.0100%')
  })

  it('9. Explicit pairTickers prop takes precedence over position fallback metrics', () => {
    const mockPositions: PositionTelemetry[] = [
      makeMockPosition({
        symbol: 'BTCUSDT',
        currentPrice: 50000.0,
        markPrice: 50000.0,
      }),
    ]

    const explicitTickers = [
      {
        symbol: 'BTCUSDT',
        lastPrice: 72150.25,
        markPrice: 72145.0,
        indexPrice: 72140.0,
        fundingRate: 0.00035,
        basis: 10.25,
        basisPct: 2.45,
      },
    ]

    const html = cleanHtml(
      renderToString(
        <PairPriceTickersCard
          positions={mockPositions}
          pairTickers={explicitTickers}
        />,
      ),
    )

    expect(html).toContain('$72,150.25')
    expect(html).toContain('Mark: $72,145.00')
    expect(html).toContain('+2.45%')
    expect(html).toContain('FR: 0.0350%')
  })
})
