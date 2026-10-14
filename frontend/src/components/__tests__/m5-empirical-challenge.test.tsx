import { describe, expect, it, vi } from 'vitest'
import { renderToString } from 'react-dom/server'
import { ExecutiveDashboard } from '../mission-control/executive-dashboard'
import { StrategyConfluenceRadar } from '../mission-control/strategy-confluence-radar'
import {
  PairCandlestickChart,
  type ChartInterval,
  type IctPdArrayItem,
} from '../mission-control/pair-candlestick-chart'
import { buildExecutiveDashboardModel } from '../mission-control/adapter'
import {
  buildProductionLaunchModel,
  buildLiveMarketModel,
  buildBracketPositionsModel,
  buildMicrostructureModel,
  type ProductionLaunchModel,
  type BracketPositionsModel,
} from '@/lib/canary'
import { getFallbackIctSignals } from '@/lib/use-ict-signals'

describe('Empirical Adversarial Challenge Suite: Milestone 5 Radar & Overlays', () => {
  // Common baseline models
  const liveMarket = buildLiveMarketModel(null)
  const emptyBrackets: BracketPositionsModel = {
    ...buildBracketPositionsModel(null),
    positions: [],
  }
  const micro = buildMicrostructureModel(null)
  const emptyTelemetry = {}
  const testDate = new Date('2026-10-11T20:00:00Z')

  // ==========================================================================
  // Challenge 1: Flat Account / Empty Position Regression Invariant
  // ==========================================================================
  describe('Challenge 1: Flat Account & Radar Bias Regex Non-Collision', () => {
    it('proves flat positions in ExecutiveDashboard do NOT match />\\s*LONG\\s*</ or />\\s*SHORT\\s*</', () => {
      const prodLaunch: ProductionLaunchModel = {
        ...buildProductionLaunchModel(null),
        aggregateExposureUsdt: 0.0,
        candidateAllocations: [],
        solvency: {
          ...buildProductionLaunchModel(null).solvency,
          total_equity_usdt: 100.0,
          cash_usdt: 100.0,
          allocated_margin_usdt: 0.0,
          unrealized_pnl_usdt: 0.0,
          cash_reserve_pct: 100.0,
        },
      }

      const adapted = buildExecutiveDashboardModel(
        prodLaunch,
        liveMarket,
        emptyBrackets,
        micro,
        emptyTelemetry,
        testDate,
      )

      const html = renderToString(
        <ExecutiveDashboard model={adapted} onRefresh={() => {}} isLoading={false} />,
      )

      // Strict assertions on flat status
      expect(html).toContain('SCANNING / STANDBY')
      expect(html).toContain('$0.00')

      // CRITICAL Phase 314 invariant: flat accounts must NOT have solitary LONG/SHORT tag
      expect(html).not.toMatch(/>\s*LONG\s*</)
      expect(html).not.toMatch(/>\s*SHORT\s*</)

      // Confirm radar renders institutional BIAS labels instead
      expect(html).toContain('LONG BIAS')
      expect(html).toContain('NEUTRAL')
    })

    it('proves StrategyConfluenceRadar alone never produces />\\s*LONG\\s*</ even when signal side is BUY', () => {
      const fallback = getFallbackIctSignals()
      const html = renderToString(<StrategyConfluenceRadar ictSignals={fallback} />)

      // Matches 'LONG BIAS' or 'SHORT BIAS', never '>LONG<'
      expect(html).not.toMatch(/>\s*LONG\s*</)
      expect(html).not.toMatch(/>\s*SHORT\s*</)
      expect(html).toContain('LONG BIAS')
    })

    it('proves StrategyConfluenceRadar with all pairs set to BUY never produces />\\s*LONG\\s*</', () => {
      const fallback = getFallbackIctSignals()
      const allBuySignals = {
        ...fallback,
        signals: Object.fromEntries(
          Object.entries(fallback.signals).map(([sym, sig]) => [
            sym,
            { ...sig, side: 'BUY' as const },
          ]),
        ),
      }

      const html = renderToString(<StrategyConfluenceRadar ictSignals={allBuySignals} />)
      expect(html).not.toMatch(/>\s*LONG\s*</)
      expect(html).not.toMatch(/>\s*SHORT\s*</)
    })

    it('proves StrategyConfluenceRadar with all pairs set to SELL never produces />\\s*SHORT\\s*</', () => {
      const fallback = getFallbackIctSignals()
      const allSellSignals = {
        ...fallback,
        signals: Object.fromEntries(
          Object.entries(fallback.signals).map(([sym, sig]) => [
            sym,
            { ...sig, side: 'SELL' as const },
          ]),
        ),
      }

      const html = renderToString(<StrategyConfluenceRadar ictSignals={allSellSignals} />)
      expect(html).not.toMatch(/>\s*LONG\s*</)
      expect(html).not.toMatch(/>\s*SHORT\s*</)
    })
  })

  // ==========================================================================
  // Challenge 2: Multi-Timeframe Selection and Active Styling
  // ==========================================================================
  describe('Challenge 2: Multi-Timeframe Selection (1m, 5m, 15m, 1h, 4h)', () => {
    const timeframes: ChartInterval[] = ['1m', '5m', '15m', '1h', '4h']

    it.each(timeframes)(
      'renders timeframe %s with active styling when interval is %s',
      (tf) => {
        const onIntervalChange = vi.fn()
        const html = renderToString(
          <PairCandlestickChart
            symbol="SOLUSDT"
            interval={tf}
            activeIndicators={{ ema50: true, ema200: true, volume: true }}
            onIntervalChange={onIntervalChange}
          />,
        )

        // Verify root data-interval
        expect(html).toContain(`data-interval="${tf}"`)

        // Verify all 5 button testids exist
        for (const candidate of timeframes) {
          expect(html).toContain(`data-testid="timeframe-${candidate}-solusdt"`)
        }

        // Active button has cyan background & border
        // We verify that the html snippet for the active button contains cyan classes
        const buttonRegex = new RegExp(
          `data-testid="timeframe-${tf}-solusdt"[^>]*class="[^"]*bg-cyan-500/20[^"]*text-cyan-400[^"]*"`,
        )
        const alternateRegex = new RegExp(
          `class="[^"]*bg-cyan-500/20[^"]*text-cyan-400[^"]*"[^>]*data-testid="timeframe-${tf}-solusdt"`,
        )
        const hasActiveClass = buttonRegex.test(html) || alternateRegex.test(html)
        expect(hasActiveClass).toBe(true)
      },
    )

    it('verifies non-active timeframe buttons have inactive styling (text-zinc-400)', () => {
      const html = renderToString(
        <PairCandlestickChart
          symbol="SOLUSDT"
          interval="15m"
          activeIndicators={{ ema50: true, ema200: true, volume: true }}
        />,
      )

      // 1m is not active, should have text-zinc-400 and hover:text-white
      const regex1m = /data-testid="timeframe-1m-solusdt"[^>]*class="[^"]*text-zinc-400/
      const regex1mAlt = /class="[^"]*text-zinc-400[^"]*"[^>]*data-testid="timeframe-1m-solusdt"/
      expect(regex1m.test(html) || regex1mAlt.test(html)).toBe(true)

      // 4h is not active, should have text-zinc-400
      const regex4h = /data-testid="timeframe-4h-solusdt"[^>]*class="[^"]*text-zinc-400/
      const regex4hAlt = /class="[^"]*text-zinc-400[^"]*"[^>]*data-testid="timeframe-4h-solusdt"/
      expect(regex4h.test(html) || regex4hAlt.test(html)).toBe(true)
    })
  })

  // ==========================================================================
  // Challenge 3: SVG PDA Box Types & NaN/Undefined Immunity
  // ==========================================================================
  describe('Challenge 3: SVG PDA Box Overlays & Numerical Safety', () => {
    const fullPdaArray: IctPdArrayItem[] = [
      {
        array_type: 'FVG_BISI',
        timeframe: '15m',
        top: 185.0,
        bottom: 182.0,
        mean_threshold: 183.5,
        direction: 'BULLISH',
        creation_ts: 1728600000000,
        is_mitigated: false,
      },
      {
        array_type: 'FVG_SIBI',
        timeframe: '15m',
        top: 190.0,
        bottom: 187.0,
        mean_threshold: 188.5,
        direction: 'BEARISH',
        creation_ts: 1728600000000,
        is_mitigated: false,
      },
      {
        array_type: 'INVERSION_FVG',
        timeframe: '1h',
        top: 184.0,
        bottom: 181.0,
        mean_threshold: 182.5,
        direction: 'BULLISH',
        creation_ts: 1728600000000,
        is_mitigated: false,
      },
      {
        array_type: 'BREAKER_BLOCK',
        timeframe: '1h',
        top: 180.0,
        bottom: 178.0,
        mean_threshold: 179.0,
        direction: 'BULLISH',
        creation_ts: 1728600000000,
        is_mitigated: false,
      },
      {
        array_type: 'BREAKER_BLOCK',
        timeframe: '4h',
        top: 195.0,
        bottom: 193.0,
        mean_threshold: 194.0,
        direction: 'BEARISH',
        creation_ts: 1728600000000,
        is_mitigated: false,
      },
    ]

    const fullTwinsState = {
      symbol: 'SOLUSDT',
      step_1_htf_hit: true,
      step_2_m5_cisd: true,
      step_3_twins_fvg: true,
      step_4_ote_retrace: true,
      step_5_m1_cisd: true,
      step_6_ready: true,
      ote_62: 183.2,
      ote_705: 184.0,
      ote_79: 184.8,
      m5_cisd_price: 182.0,
      m1_cisd_price: 183.5,
      stdv_2_0: 192.0,
      stdv_4_0: 198.0,
      side: 'BUY' as const,
    }

    it('renders all 5 SVG PDA box types simultaneously', () => {
      const html = renderToString(
        <PairCandlestickChart
          symbol="SOLUSDT"
          interval="15m"
          activeIndicators={{ ema50: true, ema200: true, volume: true }}
          ictSignal={{
            twins_state: fullTwinsState,
            pd_arrays: fullPdaArray,
          }}
          ictOverlays={{
            showFvg: true,
            showBreakers: true,
            showOte: true,
            showStdv: true,
            showCisdMarkers: true,
          }}
        />,
      )

      // 1. Overlay container
      expect(html).toContain('data-testid="pda-box-overlay"')

      // 2. All 5 testids must be present
      expect(html).toContain('data-testid="pda-box-fvg_bisi"')
      expect(html).toContain('data-testid="pda-box-fvg_sibi"')
      expect(html).toContain('data-testid="pda-box-inversion_fvg"')
      expect(html).toContain('data-testid="pda-box-breaker_block"')
      expect(html).toContain('data-testid="pda-box-ote_band"')

      // 3. Labels for each box
      expect(html).toContain('+FVG BISI')
      expect(html).toContain('-FVG SIBI')
      expect(html).toContain('IFVG')
      expect(html).toContain('+BB Breaker Block')
      expect(html).toContain('-BB Breaker Block')
      expect(html).toContain('OTE Band (62.0% - 79.0%)')
    })

    it('strictly guarantees NO NaN or undefined attributes exist in rendered SVG', () => {
      const html = renderToString(
        <PairCandlestickChart
          symbol="SOLUSDT"
          interval="15m"
          activeIndicators={{ ema50: true, ema200: true, volume: true }}
          ictSignal={{
            twins_state: fullTwinsState,
            pd_arrays: fullPdaArray,
          }}
        />,
      )

      // Extract the SVG element content
      const svgMatch = html.match(/<svg[^>]*data-testid="pda-box-overlay"[^>]*>([\s\S]*?)<\/svg>/)
      expect(svgMatch).toBeTruthy()
      const svgContent = svgMatch![0]

      // Strict assertions against NaN, undefined, null
      expect(svgContent).not.toContain('NaN')
      expect(svgContent).not.toContain('undefined')
      expect(svgContent).not.toContain('null')
      expect(svgContent).not.toMatch(/y="NaN"/)
      expect(svgContent).not.toMatch(/height="NaN"/)
      expect(svgContent).not.toMatch(/y="undefined"/)
      expect(svgContent).not.toMatch(/height="undefined"/)
    })

    it('survives inverted OTE bounds (ote_62 > ote_79) gracefully', () => {
      const invertedOteTwins = {
        ...fullTwinsState,
        ote_62: 195.0, // Higher than 79% (e.g. for short retracements)
        ote_79: 188.0,
      }

      const html = renderToString(
        <PairCandlestickChart
          symbol="SOLUSDT"
          interval="15m"
          activeIndicators={{ ema50: true, ema200: true, volume: true }}
          ictSignal={{
            twins_state: invertedOteTwins,
            pd_arrays: [],
          }}
        />,
      )

      expect(html).toContain('data-testid="pda-box-ote_band"')
      expect(html).not.toContain('NaN')
      expect(html).not.toContain('undefined')
    })

    it('renders cleanly when pd_arrays is empty and twins_state has no OTE', () => {
      const html = renderToString(
        <PairCandlestickChart
          symbol="ETHUSDT"
          interval="1h"
          activeIndicators={{ ema50: false, ema200: false, volume: false }}
          ictSignal={{
            twins_state: {
              symbol: 'ETHUSDT',
              step_1_htf_hit: false,
              step_2_m5_cisd: false,
              step_3_twins_fvg: false,
              step_4_ote_retrace: false,
              step_5_m1_cisd: false,
              step_6_ready: false,
            },
            pd_arrays: [],
          }}
        />,
      )

      expect(html).toContain('data-testid="pda-box-overlay"')
      // No boxes pushed
      expect(html).not.toContain('pda-box-fvg_bisi')
      expect(html).not.toContain('pda-box-ote_band')
      expect(html).not.toContain('NaN')
    })

    it('handles high-value BTC prices without numerical overflow or string truncations', () => {
      const btcPda: IctPdArrayItem[] = [
        {
          array_type: 'FVG_BISI',
          timeframe: '4h',
          top: 96500.0,
          bottom: 95800.0,
          mean_threshold: 96150.0,
          direction: 'BULLISH',
          creation_ts: 1728600000000,
          is_mitigated: false,
        },
      ]
      const btcTwins = {
        symbol: 'BTCUSDT',
        step_1_htf_hit: true,
        step_2_m5_cisd: true,
        step_3_twins_fvg: true,
        step_4_ote_retrace: true,
        step_5_m1_cisd: true,
        step_6_ready: true,
        ote_62: 95500.0,
        ote_79: 95900.0,
      }

      const html = renderToString(
        <PairCandlestickChart
          symbol="BTCUSDT"
          interval="4h"
          activeIndicators={{ ema50: true, ema200: true, volume: true }}
          ictSignal={{ twins_state: btcTwins, pd_arrays: btcPda }}
        />,
      )

      expect(html).toContain('data-testid="pda-box-fvg_bisi"')
      expect(html).toContain('data-testid="pda-box-ote_band"')
      expect(html).toContain('$96,150')
      expect(html).not.toContain('NaN')
    })
  })

  // ==========================================================================
  // Challenge 4: Indicator Toggles and Overlay Suppression
  // ==========================================================================
  describe('Challenge 4: Indicator Toggles and Overlay Suppression', () => {
    const fullPdaArray: IctPdArrayItem[] = [
      {
        array_type: 'FVG_BISI',
        timeframe: '15m',
        top: 185.0,
        bottom: 182.0,
        mean_threshold: 183.5,
        direction: 'BULLISH',
        creation_ts: 1728600000000,
        is_mitigated: false,
      },
      {
        array_type: 'BREAKER_BLOCK',
        timeframe: '1h',
        top: 180.0,
        bottom: 178.0,
        mean_threshold: 179.0,
        direction: 'BULLISH',
        creation_ts: 1728600000000,
        is_mitigated: false,
      },
    ]

    const fullTwinsState = {
      symbol: 'SOLUSDT',
      step_1_htf_hit: true,
      step_2_m5_cisd: true,
      step_3_twins_fvg: true,
      step_4_ote_retrace: true,
      step_5_m1_cisd: true,
      step_6_ready: true,
      ote_62: 183.2,
      ote_705: 184.0,
      ote_79: 184.8,
      side: 'BUY' as const,
    }

    it('suppresses FVG boxes when showFvg is explicitly false', () => {
      const html = renderToString(
        <PairCandlestickChart
          symbol="SOLUSDT"
          interval="15m"
          activeIndicators={{ ema50: true, ema200: true, volume: true }}
          ictSignal={{ twins_state: fullTwinsState, pd_arrays: fullPdaArray }}
          ictOverlays={{ showFvg: false, showBreakers: true, showOte: true }}
        />,
      )

      expect(html).not.toContain('data-testid="pda-box-fvg_bisi"')
      expect(html).toContain('data-testid="pda-box-breaker_block"')
      expect(html).toContain('data-testid="pda-box-ote_band"')
    })

    it('suppresses Breaker Block boxes when showBreakers is explicitly false', () => {
      const html = renderToString(
        <PairCandlestickChart
          symbol="SOLUSDT"
          interval="15m"
          activeIndicators={{ ema50: true, ema200: true, volume: true }}
          ictSignal={{ twins_state: fullTwinsState, pd_arrays: fullPdaArray }}
          ictOverlays={{ showFvg: true, showBreakers: false, showOte: true }}
        />,
      )

      expect(html).toContain('data-testid="pda-box-fvg_bisi"')
      expect(html).not.toContain('data-testid="pda-box-breaker_block"')
      expect(html).toContain('data-testid="pda-box-ote_band"')
    })

    it('suppresses OTE Band when showOte is explicitly false', () => {
      const html = renderToString(
        <PairCandlestickChart
          symbol="SOLUSDT"
          interval="15m"
          activeIndicators={{ ema50: true, ema200: true, volume: true }}
          ictSignal={{ twins_state: fullTwinsState, pd_arrays: fullPdaArray }}
          ictOverlays={{ showFvg: true, showBreakers: true, showOte: false }}
        />,
      )

      expect(html).toContain('data-testid="pda-box-fvg_bisi"')
      expect(html).toContain('data-testid="pda-box-breaker_block"')
      expect(html).not.toContain('data-testid="pda-box-ote_band"')
    })

    it('renders cleanly without crashing when ictSignal is undefined or null', () => {
      const html = renderToString(
        <PairCandlestickChart
          symbol="SOLUSDT"
          interval="15m"
          activeIndicators={{ ema50: true, ema200: true, volume: true }}
          ictSignal={undefined}
        />,
      )

      expect(html).not.toContain('data-testid="pda-box-overlay"')
      expect(html).toContain('data-testid="pair-candlestick-chart-solusdt"')
      expect(html).not.toContain('NaN')
    })
  })
})

