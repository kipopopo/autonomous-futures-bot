import { useEffect, useRef, useState } from 'react'
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  ColorType,
  CrosshairMode,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type IPriceLine,
  type UTCTimestamp,
} from 'lightweight-charts'
import {
  calculateEma,
  calculateVolumeSeries,
  calculateOhlcSummary,
  type OhlcSummary,
  type MarketKline,
} from '../../lib/chart-indicators'
import { fetchMarketKlines } from '../../lib/api'
import type { PositionTelemetry } from './types'

export interface PairCandlestickChartProps {
  symbol: string
  interval: '15m' | '1h'
  activeIndicators: {
    ema50: boolean
    ema200: boolean
    volume: boolean
  }
  position?: PositionTelemetry
  onOhlcUpdate?: (summary: OhlcSummary | null) => void
  className?: string
}

export function PairCandlestickChart({
  symbol,
  interval,
  activeIndicators,
  position,
  onOhlcUpdate,
  className,
}: PairCandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candlestickSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const ema50SeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const ema200SeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const resizeObserverRef = useRef<ResizeObserver | null>(null)
  const priceLinesRef = useRef<IPriceLine[]>([])
  const latestSummaryRef = useRef<OhlcSummary | null>(null)
  const onOhlcUpdateRef = useRef(onOhlcUpdate)
  const activeIndicatorsRef = useRef(activeIndicators)
  const positionRef = useRef(position)

  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Keep latest callbacks and props fresh in refs
  useEffect(() => {
    onOhlcUpdateRef.current = onOhlcUpdate
  }, [onOhlcUpdate])

  useEffect(() => {
    activeIndicatorsRef.current = activeIndicators
  }, [activeIndicators])

  useEffect(() => {
    positionRef.current = position
  }, [position])

  // Helper to lazily initialize TradingView Lightweight Charts canvas
  const initChartIfNeeded = () => {
    if (chartRef.current || typeof window === 'undefined' || !containerRef.current) {
      return chartRef.current
    }

    try {
      const chart = createChart(containerRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: '#0a0f1d' },
          textColor: '#94a3b8',
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 11,
        },
        grid: {
          vertLines: { color: 'rgba(255, 255, 255, 0.04)' },
          horzLines: { color: 'rgba(255, 255, 255, 0.04)' },
        },
        crosshair: {
          mode: CrosshairMode.Normal,
          vertLine: {
            color: 'rgba(255, 255, 255, 0.2)',
            width: 1,
            style: LineStyle.Dashed,
            labelBackgroundColor: '#1e293b',
          },
          horzLine: {
            color: 'rgba(255, 255, 255, 0.2)',
            width: 1,
            style: LineStyle.Dashed,
            labelBackgroundColor: '#1e293b',
          },
        },
        rightPriceScale: {
          borderColor: 'rgba(255, 255, 255, 0.08)',
          scaleMargins: { top: 0.1, bottom: 0.25 },
        },
        timeScale: {
          borderColor: 'rgba(255, 255, 255, 0.08)',
          timeVisible: true,
          secondsVisible: false,
        },
        localization: {
          priceFormatter: (price: number) => {
            if (price >= 1000) {
              return `$${price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USDT`
            }
            return `$${price.toFixed(2)} USDT`
          },
        },
        width: containerRef.current.clientWidth || 600,
        height: containerRef.current.clientHeight || 280,
      })

      chartRef.current = chart

      // 1. Volume histogram on lower 20% margin
      const volumeSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: 'volume' },
        priceScaleId: '', // overlay mode so it doesn't skew candlestick prices
        visible: Boolean(activeIndicatorsRef.current.volume),
      })
      volumeSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      })
      volumeSeriesRef.current = volumeSeries

      // 2. Candlestick series (emerald bullish, rose bearish)
      const candlestickSeries = chart.addSeries(CandlestickSeries, {
        upColor: '#10b981',
        downColor: '#f43f5e',
        borderVisible: false,
        wickUpColor: '#10b981',
        wickDownColor: '#f43f5e',
      })
      candlestickSeriesRef.current = candlestickSeries

      // 3. Trend EMA 50 line (cyan #06b6d4)
      const ema50Series = chart.addSeries(LineSeries, {
        color: '#06b6d4',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        visible: Boolean(activeIndicatorsRef.current.ema50),
      })
      ema50SeriesRef.current = ema50Series

      // 4. Trend EMA 200 line (amber #f59e0b)
      const ema200Series = chart.addSeries(LineSeries, {
        color: '#f59e0b',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        visible: Boolean(activeIndicatorsRef.current.ema200),
      })
      ema200SeriesRef.current = ema200Series

      // Crosshair hover inspection updates OHLC badge
      chart.subscribeCrosshairMove((param) => {
        if (!param.point || !param.time) {
          if (latestSummaryRef.current) {
            onOhlcUpdateRef.current?.(latestSummaryRef.current)
          }
          return
        }

        const bar = param.seriesData.get(candlestickSeries) as
          | { open: number; high: number; low: number; close: number }
          | undefined
        const volBar = param.seriesData.get(volumeSeries) as { value: number } | undefined

        if (bar && latestSummaryRef.current) {
          onOhlcUpdateRef.current?.({
            open: bar.open,
            high: bar.high,
            low: bar.low,
            close: bar.close,
            volume: volBar ? volBar.value : 0,
            high24h: latestSummaryRef.current.high24h,
            low24h: latestSummaryRef.current.low24h,
          })
        }
      })

      // Responsive auto-resize via ResizeObserver
      if (typeof ResizeObserver !== 'undefined' && containerRef.current) {
        const resizeObserver = new ResizeObserver((entries) => {
          if (!entries || entries.length === 0 || !entries[0].contentRect) return
          const { width, height } = entries[0].contentRect
          if (width > 0) {
            chart.applyOptions({
              width,
              height: height > 0 ? height : undefined,
            })
          }
        })
        resizeObserver.observe(containerRef.current)
        resizeObserverRef.current = resizeObserver
      }

      // Render bracket price lines if position exists on mount
      renderBracketLines(candlestickSeries, positionRef.current)

      return chart
    } catch (err) {
      console.warn('[PairCandlestickChart] Canvas initialization skipped:', err)
      return null
    }
  }

  // Bracket price lines helper
  const renderBracketLines = (
    series: ISeriesApi<'Candlestick'> | null,
    pos: PositionTelemetry | undefined,
  ) => {
    if (!series) return

    // Clean up previous bracket lines
    for (const line of priceLinesRef.current) {
      try {
        series.removePriceLine(line)
      } catch {
        // Ignore if already cleared
      }
    }
    priceLinesRef.current = []

    if (!pos) return

    // Entry Price: solid sky-blue (#38bdf8) line
    if (pos.entryPrice > 0) {
      try {
        const entryLine = series.createPriceLine({
          price: pos.entryPrice,
          color: '#38bdf8',
          lineWidth: 2,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: true,
          title: 'Entry',
        })
        priceLinesRef.current.push(entryLine)
      } catch (e) {
        console.warn('Failed to create entry price line:', e)
      }
    }

    // Take-Profit Target: dashed emerald green (#10b981) line (+2.0x ATR)
    if (pos.takeProfitPrice > 0) {
      try {
        const tpTitle = pos.atrDistanceTpPct
          ? `+2.0x ATR (+${pos.atrDistanceTpPct}%)`
          : '+2.0x ATR'
        const tpLine = series.createPriceLine({
          price: pos.takeProfitPrice,
          color: '#10b981',
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: tpTitle,
        })
        priceLinesRef.current.push(tpLine)
      } catch (e) {
        console.warn('Failed to create TP price line:', e)
      }
    }

    // Stop-Loss Target: dashed rose red (#f43f5e) line (-1.2x ATR)
    if (pos.stopLossPrice > 0) {
      try {
        const slTitle = pos.atrDistanceSlPct
          ? `-1.2x ATR (-${pos.atrDistanceSlPct}%)`
          : '-1.2x ATR'
        const slLine = series.createPriceLine({
          price: pos.stopLossPrice,
          color: '#f43f5e',
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: slTitle,
        })
        priceLinesRef.current.push(slLine)
      } catch (e) {
        console.warn('Failed to create SL price line:', e)
      }
    }
  }

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (resizeObserverRef.current) {
        resizeObserverRef.current.disconnect()
        resizeObserverRef.current = null
      }
      if (chartRef.current) {
        chartRef.current.remove()
        chartRef.current = null
        candlestickSeriesRef.current = null
        ema50SeriesRef.current = null
        ema200SeriesRef.current = null
        volumeSeriesRef.current = null
        priceLinesRef.current = []
      }
    }
  }, [])

  // Fetch and update candlestick series + indicators on symbol or interval switch
  useEffect(() => {
    let isMounted = true

    fetchMarketKlines(symbol, interval, 150)
      .then((klines) => {
        if (!isMounted) return

        if (!klines || klines.length === 0) {
          setError('Tiada data kline tersedia')
          setIsLoading(false)
          return
        }

        initChartIfNeeded()

        // Ensure monotonic ascending timestamps without duplicates
        const sorted = [...klines].sort((a, b) => a.timestamp - b.timestamp)
        const cleanData: MarketKline[] = []
        let lastTs = -1
        for (const item of sorted) {
          if (item.timestamp > lastTs) {
            cleanData.push(item)
            lastTs = item.timestamp
          }
        }

        if (cleanData.length === 0) {
          setIsLoading(false)
          return
        }

        // 1. Candlestick series
        const candleData = cleanData.map((k) => ({
          time: k.timestamp as UTCTimestamp,
          open: k.open,
          high: k.high,
          low: k.low,
          close: k.close,
        }))
        candlestickSeriesRef.current?.setData(candleData)

        // 2. 50 EMA
        const ema50Data = calculateEma(cleanData, 50)
        ema50SeriesRef.current?.setData(
          ema50Data.map((p) => ({
            time: p.time as UTCTimestamp,
            value: p.value,
          }))
        )

        // 3. 200 EMA
        const ema200Data = calculateEma(cleanData, 200)
        ema200SeriesRef.current?.setData(
          ema200Data.map((p) => ({
            time: p.time as UTCTimestamp,
            value: p.value,
          }))
        )

        // 4. Volume histogram
        const volData = calculateVolumeSeries(cleanData)
        volumeSeriesRef.current?.setData(
          volData.map((v) => ({
            time: v.time as UTCTimestamp,
            value: v.value,
            color: v.color,
          }))
        )

        // 5. Auto-fit chart to content
        chartRef.current?.timeScale().fitContent()

        // 6. Provide latest OHLC summary bounds
        const summary = calculateOhlcSummary(cleanData)
        latestSummaryRef.current = summary
        onOhlcUpdateRef.current?.(summary)

        setError(null)
        setIsLoading(false)
      })
      .catch((err) => {
        if (!isMounted) return
        setError(err instanceof Error ? err.message : 'Gagal memuatkan data kline')
        setIsLoading(false)
      })

    return () => {
      isMounted = false
    }
  }, [symbol, interval])

  // Reactive price bracket lines: Entry (sky-blue), Take-Profit (green dashed), Stop-Loss (red dashed)
  useEffect(() => {
    renderBracketLines(candlestickSeriesRef.current, position)
  }, [position])

  // Reactive indicator visibility toggles
  useEffect(() => {
    if (ema50SeriesRef.current) {
      ema50SeriesRef.current.applyOptions({ visible: Boolean(activeIndicators.ema50) })
    }
  }, [activeIndicators.ema50])

  useEffect(() => {
    if (ema200SeriesRef.current) {
      ema200SeriesRef.current.applyOptions({ visible: Boolean(activeIndicators.ema200) })
    }
  }, [activeIndicators.ema200])

  useEffect(() => {
    if (volumeSeriesRef.current) {
      volumeSeriesRef.current.applyOptions({ visible: Boolean(activeIndicators.volume) })
    }
  }, [activeIndicators.volume])

  return (
    <div
      className={`relative w-full h-[280px] bg-[#0a0f1d] rounded-xl overflow-hidden border border-white/5 ${className ?? ''}`}
      data-testid={`pair-candlestick-chart-${symbol.toLowerCase()}`}
      data-symbol={symbol}
      data-interval={interval}
    >
      <div
        ref={containerRef}
        className="w-full h-full"
        data-testid="chart-canvas-container"
      />
      {isLoading && (
        <div
          className="absolute inset-0 flex items-center justify-center bg-[#0a0f1d]/70 backdrop-blur-xs z-10"
          data-testid="chart-loading-overlay"
        >
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-900/90 border border-white/10 text-xs font-mono text-slate-300">
            <span className="loading loading-spinner loading-xs text-cyan-400" />
            <span>{`Memuatkan ${symbol} (${interval})...`}</span>
          </div>
        </div>
      )}
      {error && (
        <div
          className="absolute inset-0 flex items-center justify-center bg-[#0a0f1d]/85 z-10"
          data-testid="chart-error-overlay"
        >
          <div className="text-xs font-mono text-rose-400 px-3 py-1.5 rounded-lg bg-rose-950/40 border border-rose-900/50">
            {error}
          </div>
        </div>
      )}
    </div>
  )
}

export default PairCandlestickChart
