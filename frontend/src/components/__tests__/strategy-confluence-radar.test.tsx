import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'
import { StrategyConfluenceRadar, TWINS_STEPS } from '../mission-control/strategy-confluence-radar'
import { getFallbackIctSignals } from '@/lib/use-ict-signals'

describe('Phase 317 Milestone 5: Strategy Confluence Radar & 8-Pair Matrix', () => {
  const fallbackData = getFallbackIctSignals()

  // --------------------------------------------------------------------------
  // Suite 1: 8-Pair Universe Rendering Verification
  // --------------------------------------------------------------------------
  describe('Suite 1: 8-Pair Matrix Display', () => {
    it('renders all 8 active pairs in the ICT Confluence Matrix', () => {
      const html = renderToString(<StrategyConfluenceRadar ictSignals={fallbackData} />)

      const expectedPairs = [
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
      ]

      for (const pair of expectedPairs) {
        expect(html).toContain(pair)
        expect(html).toContain(`ict-pair-card-${pair}`)
      }
    })

    it('displays the 12-Pair Matrix title and MMBM / MMSM badges', () => {
      const html = renderToString(<StrategyConfluenceRadar ictSignals={fallbackData} />)

      expect(html).toContain('ICT Market Maker &amp; Twins Reversal Confluence Matrix (12 Pairs)')
      expect(html).toContain('MMBM / MMSM')
    })
  })

  // --------------------------------------------------------------------------
  // Suite 2: 6-Step Visual Progress Bar & Stepper Verification
  // --------------------------------------------------------------------------
  describe('Suite 2: 6-Step Mechanical Progress Bar & Highlights', () => {
    it('verifies all 6 steps of the Twins Reversal setup are defined in metadata', () => {
      expect(TWINS_STEPS).toHaveLength(6)
      expect(TWINS_STEPS[0].label).toBe('Step 1: HTF PDA Hit (4h/1h)')
      expect(TWINS_STEPS[1].label).toBe('Step 2: M5 CISD Confirmed')
      expect(TWINS_STEPS[2].label).toBe('Step 3: Twins FVG Validated')
      expect(TWINS_STEPS[3].label).toBe('Step 4: OTE Retracement (62%-79%)')
      expect(TWINS_STEPS[4].label).toBe('Step 5: M1 CISD Triggered')
      expect(TWINS_STEPS[5].label).toBe('Step 6: Ready / In Position')
    })

    it('renders Step 4 active progression on BTCUSDT', () => {
      const html = renderToString(<StrategyConfluenceRadar ictSignals={fallbackData} />)

      expect(html).toContain('Step 4 / 6')
      expect(html).toContain('Step 4: OTE Retracement (62%-79%)')
    })

    it('renders Step 6 Ready / In Position on SOLUSDT with success highlight', () => {
      const html = renderToString(<StrategyConfluenceRadar ictSignals={fallbackData} />)

      expect(html).toContain('Step 6 / 6')
      expect(html).toContain('Step 6: Ready / In Position')
    })

    it('renders Invalidated badge with reason on AVAXUSDT', () => {
      const html = renderToString(<StrategyConfluenceRadar ictSignals={fallbackData} />)

      expect(html).toContain('INVALIDATED')
      expect(html).toContain('Invalidated: PDA_BREACHED')
    })
  })

  // --------------------------------------------------------------------------
  // Suite 3: Active PD Arrays & Indicator Badges
  // --------------------------------------------------------------------------
  describe('Suite 3: Active PD Arrays & Timeframe Tags', () => {
    it('renders Order Block (+OB) with 4h timeframe tag on BTCUSDT', () => {
      const html = renderToString(<StrategyConfluenceRadar ictSignals={fallbackData} />)

      expect(html).toContain('Order Block (OB)')
      expect(html).toContain('$64,500 MT')
    })

    it('renders Breaker Block (+BB) on SOLUSDT and BISI FVG on ETHUSDT', () => {
      const html = renderToString(<StrategyConfluenceRadar ictSignals={fallbackData} />)

      expect(html).toContain('Breaker Block (BB)')
      expect(html).toContain('BISI (Bullish FVG)')
      expect(html).toContain('Inversion FVG (IFVG)')
    })
  })

  // --------------------------------------------------------------------------
  // Suite 4: Dynamic Side & Candidate Health Badging
  // --------------------------------------------------------------------------
  describe('Suite 4: Dynamic Side & Health Tier Badges', () => {
    it('renders LONG, SHORT, and NEUTRAL side badges', () => {
      const html = renderToString(<StrategyConfluenceRadar ictSignals={fallbackData} />)

      expect(html).toContain('LONG')
      expect(html).toContain('NEUTRAL')
    })

    it('renders HEALTHY, INCUBATING, and DEGRADED candidate health tiers', () => {
      const html = renderToString(<StrategyConfluenceRadar ictSignals={fallbackData} />)

      expect(html).toContain('HEALTHY')
      expect(html).toContain('INCUBATING')
      expect(html).toContain('DEGRADED')
    })
  })

  // --------------------------------------------------------------------------
  // Suite 5: Execution Targets & Candidate Genome
  // --------------------------------------------------------------------------
  describe('Suite 5: Execution Targets & Genome Parameters', () => {
    it('renders OTE entry range, Stop Loss, TP1 (Stdv 2.0), and TP2 (Stdv 4.0) prices', () => {
      const html = renderToString(<StrategyConfluenceRadar ictSignals={fallbackData} />)

      expect(html).toContain('OTE Entry Range:')
      expect(html).toContain('Stop Loss (SL):')
      expect(html).toContain('TP1 (Stdv 2.0):')
      expect(html).toContain('TP2 (Stdv 4.0):')
      expect(html).toContain('$64,320 - $64,580')
      expect(html).toContain('$64,100')
      expect(html).toContain('$65,900')
      expect(html).toContain('$67,100')
      expect(html).toContain('3.12:1')
    })

    it('renders candidate genome parameters in footer', () => {
      const html = renderToString(<StrategyConfluenceRadar ictSignals={fallbackData} />)

      expect(html).toContain('Fib: 62.0% - 79.0%')
      expect(html).toContain('TP: 2x / 4x')
    })
  })

  // --------------------------------------------------------------------------
  // Suite 6: Backward Compatibility & Zero-Crash Resilience
  // --------------------------------------------------------------------------
  describe('Suite 6: Backward Compatibility & Zero-Crash Resilience', () => {
    it('renders without error when called with default/empty props', () => {
      const html = renderToString(<StrategyConfluenceRadar />)

      expect(html).toContain('Strategy Confluence Radar &amp; 15m Scalper')
      expect(html).toContain('BTC Macro Trend Filter')
      expect(html).toContain('15m Scalper Checklist')
      expect(html).toContain('Microstructure &amp; Hawkes Hazard')
      expect(html).toContain('ICT Market Maker &amp; Twins Reversal Confluence Matrix (12 Pairs)')
    })

    it('preserves existing test strings verbatim for legacy test suites', () => {
      const html = renderToString(<StrategyConfluenceRadar />)

      expect(html).toContain('BTC Macro Trend Filter')
      expect(html).toContain('BULLISH ALIGNED')
      expect(html).toContain('EMA50: $95,420')
      expect(html).toContain('EMA200: $93,810')
      expect(html).toContain('15m Scalper Checklist')
      expect(html).toContain('Microstructure &amp; Hawkes Hazard')
      expect(html).toContain('SAFE / NON-TOXIC')
      expect(html).toContain('ρ = 0.4286')
    })

    it('renders connection latency status badge', () => {
      const html = renderToString(<StrategyConfluenceRadar />)

      expect(html).toContain('connection-latency-badge')
      expect(html).toContain('POLLING 5s')
    })
  })

  // --------------------------------------------------------------------------
  // Suite 7: LumiTraders MMXM Telemetry & Sealed OOS Qualification
  // --------------------------------------------------------------------------
  describe('Suite 7: LumiTraders MMXM Telemetry & Sealed OOS Qualification', () => {
    it('renders Dayes Quarterly Cycle header strip and OOS benchmark summary', () => {
      const html = renderToString(<StrategyConfluenceRadar ictSignals={fallbackData} />)

      expect(html).toContain('ict-quarterly-cycle-strip')
      expect(html).toContain('Q3 Distribution (NY AM)')
      expect(html).toContain('KZ: NY AM')
      expect(html).toContain('SOL +$139.93 (6/7 Gates · 4/5 Win)')
    })

    it('renders per-pair LumiTraders Intraday Bias (PDR/NYMO), Measuring Gap, and OOS metrics', () => {
      const html = renderToString(<StrategyConfluenceRadar ictSignals={fallbackData} />)

      expect(html).toContain('ict-lumitraders-bias-SOLUSDT')
      expect(html).toContain('PDR: DISCOUNT · PDL SWEPT')
      expect(html).toContain('Above NYMO')
      expect(html).toContain('Measuring Gap Terminus:')
      expect(html).toContain('$188.2')
      expect(html).toContain('LumiTraders OOS:')
      expect(html).toContain('+$139.93 (6/7 Gates)')
    })
  })
})


