import { describe, expect, it, vi } from 'vitest'
import { renderToString } from 'react-dom/server'
import {
  PairCandlestickChart,
  type PairCandlestickChartProps,
} from './pair-candlestick-chart'
import type { PositionTelemetry } from './types'

describe('PairCandlestickChart component', () => {
  const defaultProps: PairCandlestickChartProps = {
    symbol: 'SOLUSDT',
    interval: '15m',
    activeIndicators: {
      ema50: true,
      ema200: true,
      volume: true,
    },
  }

  const activeLongPosition: PositionTelemetry = {
    symbol: 'SOLUSDT',
    currentPrice: 185.5,
    state: 'LONG',
    entryPrice: 182.0,
    size: 0.05,
    notionalUsdt: 9.27,
    marginUsdt: 1.85,
    unrealizedPnlUsdt: 0.175,
    unrealizedPnlPct: 9.45,
    takeProfitPrice: 191.2,
    stopLossPrice: 176.5,
    riskRewardRatio: '1.66 : 1',
    atrDistanceTpPct: 3.1,
    atrDistanceSlPct: 3.0,
  }

  const activeShortPosition: PositionTelemetry = {
    symbol: 'ETHUSDT',
    currentPrice: 2650.0,
    state: 'SHORT',
    entryPrice: 2680.0,
    size: 0.01,
    notionalUsdt: 26.5,
    marginUsdt: 5.3,
    unrealizedPnlUsdt: 0.3,
    unrealizedPnlPct: 5.66,
    takeProfitPrice: 2590.0,
    stopLossPrice: 2730.0,
    riskRewardRatio: '1.66 : 1',
    atrDistanceTpPct: 2.3,
    atrDistanceSlPct: 1.9,
  }

  const scanningStandbyPosition: PositionTelemetry = {
    symbol: 'BTCUSDT',
    currentPrice: 85200.0,
    state: 'SCANNING / STANDBY',
    entryPrice: 0.0,
    size: 0.0,
    notionalUsdt: 0.0,
    marginUsdt: 0.0,
    unrealizedPnlUsdt: 0.0,
    unrealizedPnlPct: 0.0,
    takeProfitPrice: 87500.0,
    stopLossPrice: 83800.0,
    riskRewardRatio: '1.66 : 1',
  }

  it('renders cleanly via renderToString without throwing exceptions', () => {
    const html = renderToString(<PairCandlestickChart {...defaultProps} />)
    expect(html).toBeTruthy()
    expect(html).toContain('data-testid="pair-candlestick-chart-solusdt"')
    expect(html).toContain('data-testid="chart-canvas-container"')
  })

  it('preserves symbol and interval attributes on the root container', () => {
    const html = renderToString(
      <PairCandlestickChart
        {...defaultProps}
        symbol="ETHUSDT"
        interval="1h"
      />,
    )
    expect(html).toContain('data-symbol="ETHUSDT"')
    expect(html).toContain('data-interval="1h"')
    expect(html).toContain('data-testid="pair-candlestick-chart-ethusdt"')
  })

  it('applies custom className and obsidian dark styling classes', () => {
    const html = renderToString(
      <PairCandlestickChart
        {...defaultProps}
        className="my-custom-chart-wrapper shadow-2xl"
      />,
    )
    expect(html).toContain('my-custom-chart-wrapper')
    expect(html).toContain('shadow-2xl')
    expect(html).toContain('bg-[#0a0f1d]')
  })

  it('renders loading overlay with symbol and interval feedback during initial mount', () => {
    const html = renderToString(
      <PairCandlestickChart
        symbol="BTCUSDT"
        interval="15m"
        activeIndicators={{ ema50: true, ema200: false, volume: true }}
      />,
    )
    expect(html).toContain('data-testid="chart-loading-overlay"')
    expect(html).toContain('Memuatkan BTCUSDT (15m)...')
  })

  it('supports 1h macro trend timeframe', () => {
    const html = renderToString(
      <PairCandlestickChart
        symbol="SOLUSDT"
        interval="1h"
        activeIndicators={{ ema50: true, ema200: true, volume: true }}
      />,
    )
    expect(html).toContain('data-interval="1h"')
    expect(html).toContain('Memuatkan SOLUSDT (1h)...')
  })

  it('handles active LONG position prop with entry, TP, and SL brackets', () => {
    const html = renderToString(
      <PairCandlestickChart
        {...defaultProps}
        position={activeLongPosition}
      />,
    )
    expect(html).toContain('data-testid="pair-candlestick-chart-solusdt"')
    expect(html).toContain('data-symbol="SOLUSDT"')
  })

  it('handles active SHORT position prop without errors', () => {
    const html = renderToString(
      <PairCandlestickChart
        symbol="ETHUSDT"
        interval="15m"
        activeIndicators={{ ema50: true, ema200: true, volume: false }}
        position={activeShortPosition}
      />,
    )
    expect(html).toContain('data-testid="pair-candlestick-chart-ethusdt"')
    expect(html).toContain('data-symbol="ETHUSDT"')
  })

  it('handles SCANNING / STANDBY state position gracefully', () => {
    const html = renderToString(
      <PairCandlestickChart
        symbol="BTCUSDT"
        interval="15m"
        activeIndicators={{ ema50: false, ema200: false, volume: false }}
        position={scanningStandbyPosition}
      />,
    )
    expect(html).toContain('data-testid="pair-candlestick-chart-btcusdt"')
  })

  it('handles undefined position gracefully', () => {
    const html = renderToString(
      <PairCandlestickChart
        {...defaultProps}
        position={undefined}
      />,
    )
    expect(html).toContain('data-testid="pair-candlestick-chart-solusdt"')
  })

  it('accepts onOhlcUpdate callback prop without errors', () => {
    const onOhlcUpdate = vi.fn()
    const html = renderToString(
      <PairCandlestickChart
        {...defaultProps}
        onOhlcUpdate={onOhlcUpdate}
      />,
    )
    expect(html).toBeTruthy()
    expect(onOhlcUpdate).not.toHaveBeenCalled() // Not called during SSR
  })

  it('renders correctly across all indicator permutations', () => {
    const indicatorPermutations = [
      { ema50: false, ema200: false, volume: false },
      { ema50: true, ema200: false, volume: false },
      { ema50: false, ema200: true, volume: false },
      { ema50: false, ema200: false, volume: true },
      { ema50: true, ema200: true, volume: true },
    ]

    for (const activeIndicators of indicatorPermutations) {
      const html = renderToString(
        <PairCandlestickChart
          symbol="SOLUSDT"
          interval="15m"
          activeIndicators={activeIndicators}
        />,
      )
      expect(html).toContain('data-testid="pair-candlestick-chart-solusdt"')
    }
  })

  it('handles partial bracket positions with zero TP or SL values', () => {
    const partialPosition: PositionTelemetry = {
      ...activeLongPosition,
      takeProfitPrice: 0,
      stopLossPrice: 0,
    }
    const html = renderToString(
      <PairCandlestickChart
        {...defaultProps}
        position={partialPosition}
      />,
    )
    expect(html).toContain('data-testid="pair-candlestick-chart-solusdt"')
  })

  it('handles high precision prices and large notionals on BTCUSDT', () => {
    const btcPosition: PositionTelemetry = {
      symbol: 'BTCUSDT',
      currentPrice: 85241.25,
      state: 'LONG',
      entryPrice: 84900.5,
      size: 0.005,
      notionalUsdt: 426.2,
      marginUsdt: 42.62,
      unrealizedPnlUsdt: 1.7,
      unrealizedPnlPct: 3.99,
      takeProfitPrice: 86500.0,
      stopLossPrice: 83900.0,
      riskRewardRatio: '1.66 : 1',
      atrDistanceTpPct: 1.88,
      atrDistanceSlPct: 1.18,
    }
    const html = renderToString(
      <PairCandlestickChart
        symbol="BTCUSDT"
        interval="1h"
        activeIndicators={{ ema50: true, ema200: true, volume: true }}
        position={btcPosition}
      />,
    )
    expect(html).toContain('data-testid="pair-candlestick-chart-btcusdt"')
    expect(html).toContain('data-symbol="BTCUSDT"')
    expect(html).toContain('data-interval="1h"')
  })

  it('renders default export identical to named export', async () => {
    const DefaultImportModule = await import('./pair-candlestick-chart')
    expect(DefaultImportModule.default).toBe(DefaultImportModule.PairCandlestickChart)
  })
})
