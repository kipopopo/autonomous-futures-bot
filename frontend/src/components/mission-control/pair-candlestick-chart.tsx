import { useEffect, useRef, useState } from 'react'
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  ColorType,
  CrosshairMode,
  LineStyle,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type IPriceLine,
  type UTCTimestamp,
  type SeriesMarker,
  type ISeriesMarkersPluginApi,
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

export type ChartInterval = '1m' | '5m' | '15m' | '1h' | '4h'

export type IctArrayType =
  | 'ORDER_BLOCK'
  | 'BREAKER_BLOCK'
  | 'FVG_BISI'
  | 'FVG_SIBI'
  | 'INVERSION_FVG'
  | 'OLD_HIGH'
  | 'OLD_LOW'

export interface IctPdArrayItem {
  array_type: IctArrayType
  timeframe: ChartInterval
  top: number
  bottom: number
  mean_threshold: number
  direction: 'BULLISH' | 'BEARISH'
  creation_ts: number
  is_mitigated: boolean
}

export interface IctTwinsStateItem {
  symbol: string
  step_1_htf_hit: boolean
  step_2_m5_cisd: boolean
  step_3_twins_fvg: boolean
  step_4_ote_retrace: boolean
  step_5_m1_cisd: boolean
  step_6_ready: boolean
  active_pda?: IctPdArrayItem | null
  m5_cisd_price?: number | null
  m1_cisd_price?: number | null
  ote_62?: number | null
  ote_705?: number | null
  ote_79?: number | null
  stdv_2_0?: number | null
  stdv_4_0?: number | null
  stop_loss?: number | null
  take_profit_partial?: number | null
  take_profit_final?: number | null
  side?: 'BUY' | 'SELL' | null
  step?: string
  invalidation_reason?: string
}

export interface IctOverlayOptions {
  showFvg?: boolean
  showBreakers?: boolean
  showOte?: boolean
  showStdv?: boolean
  showCisdMarkers?: boolean
}

export interface PairCandlestickChartProps {
  symbol: string
  interval: ChartInterval
  activeIndicators: {
    ema50: boolean
    ema200: boolean
    volume: boolean
  }
  ictOverlays?: IctOverlayOptions
  ictSignal?: {
    twins_state?: IctTwinsStateItem
    pd_arrays?: IctPdArrayItem[]
  }
  position?: PositionTelemetry
  onIntervalChange?: (interval: ChartInterval) => void
  onOhlcUpdate?: (summary: OhlcSummary | null) => void
  className?: string
}

export function PairCandlestickChart({
  symbol,
  interval,
  activeIndicators,
  ictOverlays,
  ictSignal,
  position,
  onIntervalChange,
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
  const ictPriceLinesRef = useRef<IPriceLine[]>([])
  const markersPrimitiveRef = useRef<ISeriesMarkersPluginApi<any> | null>(null)
  const latestCandleTimeRef = useRef<UTCTimestamp | null>(null)
  const latestSummaryRef = useRef<OhlcSummary | null>(null)
  const onOhlcUpdateRef = useRef(onOhlcUpdate)
  const activeIndicatorsRef = useRef(activeIndicators)
  const positionRef = useRef(position)
  const ictSignalRef = useRef(ictSignal)
  const ictOverlaysRef = useRef(ictOverlays)

  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [, setForceUpdate] = useState(0)

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

  useEffect(() => {
    ictSignalRef.current = ictSignal
  }, [ictSignal])

  useEffect(() => {
    ictOverlaysRef.current = ictOverlays
  }, [ictOverlays])

  // Bracket price lines helper
  const renderBracketLines = (
    series: ISeriesApi<'Candlestick'> | null,
    pos: PositionTelemetry | undefined,
  ) => {
    if (!series) return

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

  // ICT Overlay Price Lines helper (FVG CE 50%, Breakers, OTE, STDV)
  const renderIctPriceLines = (
    series: ISeriesApi<'Candlestick'> | null,
    signal: PairCandlestickChartProps['ictSignal'],
    options: IctOverlayOptions = { showFvg: true, showBreakers: true, showOte: true, showStdv: true },
  ) => {
    if (!series) return

    for (const line of ictPriceLinesRef.current) {
      try {
        series.removePriceLine(line)
      } catch {
        // Ignore if already removed
      }
    }
    ictPriceLinesRef.current = []

    if (!signal) return

    const { twins_state, pd_arrays } = signal

    // A. Breaker Blocks (Horizontal dashed ray at high/low)
    if (options.showBreakers !== false && pd_arrays) {
      pd_arrays
        .filter((p) => p.array_type === 'BREAKER_BLOCK' && !p.is_mitigated)
        .forEach((bb) => {
          const isBullish = bb.direction === 'BULLISH'
          const color = isBullish ? '#f59e0b' : '#fb923c'
          const tag = isBullish ? '+BB' : '-BB'

          try {
            const topLine = series.createPriceLine({
              price: bb.top,
              color,
              lineWidth: 1,
              lineStyle: LineStyle.Dashed,
              axisLabelVisible: true,
              title: `${tag} High`,
            })
            const botLine = series.createPriceLine({
              price: bb.bottom,
              color,
              lineWidth: 1,
              lineStyle: LineStyle.Dashed,
              axisLabelVisible: true,
              title: `${tag} Low`,
            })
            ictPriceLinesRef.current.push(topLine, botLine)
          } catch (e) {
            console.warn('Failed to create Breaker Block price lines:', e)
          }
        })
    }

    // B. FVG Consequent Encroachment (50% dashed line)
    if (options.showFvg !== false && pd_arrays) {
      pd_arrays
        .filter(
          (p) =>
            (p.array_type === 'FVG_BISI' ||
              p.array_type === 'FVG_SIBI' ||
              p.array_type === 'INVERSION_FVG') &&
            !p.is_mitigated,
        )
        .forEach((fvg) => {
          const isBisi = fvg.array_type === 'FVG_BISI'
          const isIfvg = fvg.array_type === 'INVERSION_FVG'
          const color = isBisi ? '#10b981' : isIfvg ? '#a855f7' : '#f43f5e'
          const label = isBisi ? 'BISI CE (50%)' : isIfvg ? 'IFVG CE (50%)' : 'SIBI CE (50%)'

          try {
            const ceLine = series.createPriceLine({
              price: fvg.mean_threshold,
              color,
              lineWidth: 1,
              lineStyle: LineStyle.Dashed,
              axisLabelVisible: true,
              title: label,
            })
            ictPriceLinesRef.current.push(ceLine)
          } catch (e) {
            console.warn('Failed to create FVG CE price line:', e)
          }
        })
    }

    // C. Optimal Trade Entry (OTE 62%-79%) Levels
    if (options.showOte !== false && twins_state) {
      if (twins_state.ote_62 && twins_state.ote_79) {
        try {
          const ote62 = series.createPriceLine({
            price: twins_state.ote_62,
            color: '#a855f7',
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: 'OTE 62.0%',
          })
          const ote79 = series.createPriceLine({
            price: twins_state.ote_79,
            color: '#a855f7',
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: 'OTE 79.0%',
          })
          ictPriceLinesRef.current.push(ote62, ote79)

          if (twins_state.ote_705) {
            const ote705 = series.createPriceLine({
              price: twins_state.ote_705,
              color: '#c084fc',
              lineWidth: 1,
              lineStyle: LineStyle.Dotted,
              axisLabelVisible: true,
              title: 'OTE 70.5% (Sweet Spot)',
            })
            ictPriceLinesRef.current.push(ote705)
          }
        } catch (e) {
          console.warn('Failed to create OTE price lines:', e)
        }
      }
    }

    // D. Standard Deviation Expansion Projections (TP1 -2.0, TP2 -4.0)
    if (options.showStdv !== false && twins_state) {
      if (twins_state.stdv_2_0) {
        try {
          const tp1Line = series.createPriceLine({
            price: twins_state.stdv_2_0,
            color: '#10b981',
            lineWidth: 2,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: 'TP1 (-2.0 STDV)',
          })
          ictPriceLinesRef.current.push(tp1Line)
        } catch (e) {
          console.warn('Failed to create STDV TP1 line:', e)
        }
      }
      if (twins_state.stdv_4_0) {
        try {
          const tp2Line = series.createPriceLine({
            price: twins_state.stdv_4_0,
            color: '#06b6d4',
            lineWidth: 2,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: 'TP2 Terminus (-4.0 STDV)',
          })
          ictPriceLinesRef.current.push(tp2Line)
        } catch (e) {
          console.warn('Failed to create STDV TP2 line:', e)
        }
      }
    }
  }

  // CISD Confirmation Markers via createSeriesMarkers
  const renderCisdMarkers = (
    series: ISeriesApi<'Candlestick'> | null,
    twinsState?: IctTwinsStateItem,
    latestCandleTime?: UTCTimestamp | null,
    options: IctOverlayOptions = { showCisdMarkers: true },
  ) => {
    if (!series) return

    if (options.showCisdMarkers === false || !twinsState || !latestCandleTime) {
      if (markersPrimitiveRef.current) {
        try {
          markersPrimitiveRef.current.setMarkers([])
        } catch {
          // Ignore detach errors
        }
      }
      return
    }

    const markers: SeriesMarker<UTCTimestamp>[] = []
    if (twinsState.step_5_m1_cisd || twinsState.step_2_m5_cisd) {
      const isBullish = twinsState.side === 'BUY'
      markers.push({
        time: latestCandleTime,
        position: isBullish ? 'belowBar' : 'aboveBar',
        shape: isBullish ? 'arrowUp' : 'arrowDown',
        color: isBullish ? '#10b981' : '#f43f5e',
        text: isBullish ? 'CISD ↑' : 'CISD ↓',
        size: 2,
      })
    }

    try {
      if (markersPrimitiveRef.current) {
        markersPrimitiveRef.current.setMarkers(markers)
      } else {
        markersPrimitiveRef.current = createSeriesMarkers(series, markers)
      }
    } catch (e) {
      console.warn('Failed to set CISD markers:', e)
    }
  }

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
            if (price < 10) {
              return `$${price.toFixed(4)} USDT`
            }
            return `$${price.toFixed(2)} USDT`
          },
        },
        width: containerRef.current.clientWidth || 600,
        height: containerRef.current.clientHeight || 280,
      })

      chartRef.current = chart

      const upperSym = symbol.toUpperCase()
      const isSubDollar =
        upperSym.includes('DOGE') ||
        upperSym.includes('XRP') ||
        upperSym.includes('SUI')

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
        priceFormat: {
          type: 'price',
          precision: isSubDollar ? 4 : 2,
          minMove: isSubDollar ? 0.0001 : 0.01,
        },
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
        priceFormat: {
          type: 'price',
          precision: isSubDollar ? 4 : 2,
          minMove: isSubDollar ? 0.0001 : 0.01,
        },
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
        priceFormat: {
          type: 'price',
          precision: isSubDollar ? 4 : 2,
          minMove: isSubDollar ? 0.0001 : 0.01,
        },
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

      // Update box overlay coordinates on visible range changes (pan/zoom)
      chart.timeScale().subscribeVisibleTimeRangeChange(() => {
        setForceUpdate((n) => n + 1)
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
            setForceUpdate((n) => n + 1)
          }
        })
        resizeObserver.observe(containerRef.current)
        resizeObserverRef.current = resizeObserver
      }

      // Render bracket price lines if position exists on mount
      renderBracketLines(candlestickSeries, positionRef.current)

      // Render ICT price lines and CISD markers if signal exists on mount
      renderIctPriceLines(candlestickSeries, ictSignalRef.current, ictOverlaysRef.current)
      renderCisdMarkers(
        candlestickSeries,
        ictSignalRef.current?.twins_state,
        latestCandleTimeRef.current,
        ictOverlaysRef.current,
      )

      return chart
    } catch (err) {
      console.warn('[PairCandlestickChart] Canvas initialization skipped:', err)
      return null
    }
  }

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (resizeObserverRef.current) {
        resizeObserverRef.current.disconnect()
        resizeObserverRef.current = null
      }
      if (markersPrimitiveRef.current) {
        try {
          markersPrimitiveRef.current.detach()
        } catch {
          // Ignore
        }
        markersPrimitiveRef.current = null
      }
      if (chartRef.current) {
        chartRef.current.remove()
        chartRef.current = null
        candlestickSeriesRef.current = null
        ema50SeriesRef.current = null
        ema200SeriesRef.current = null
        volumeSeriesRef.current = null
        priceLinesRef.current = []
        ictPriceLinesRef.current = []
      }
    }
  }, [])

  // Fetch and update candlestick series + indicators on symbol or interval switch
  useEffect(() => {
    let isMounted = true

    fetchMarketKlines(symbol, interval as '15m' | '1h', 150)
      .then((klines) => {
        if (!isMounted) return

        if (!klines || klines.length === 0) {
          setError('No kline data available')
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

        const latestTs = (cleanData[cleanData.length - 1]?.timestamp ?? null) as UTCTimestamp | null
        latestCandleTimeRef.current = latestTs

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
          })),
        )

        // 3. 200 EMA
        const ema200Data = calculateEma(cleanData, 200)
        ema200SeriesRef.current?.setData(
          ema200Data.map((p) => ({
            time: p.time as UTCTimestamp,
            value: p.value,
          })),
        )

        // 4. Volume histogram
        const volData = calculateVolumeSeries(cleanData)
        volumeSeriesRef.current?.setData(
          volData.map((v) => ({
            time: v.time as UTCTimestamp,
            value: v.value,
            color: v.color,
          })),
        )

        // 5. Auto-fit chart to content
        chartRef.current?.timeScale().fitContent()

        // 6. Provide latest OHLC summary bounds
        const summary = calculateOhlcSummary(cleanData)
        latestSummaryRef.current = summary
        onOhlcUpdateRef.current?.(summary)

        // 7. Update ICT overlays & CISD markers
        renderIctPriceLines(candlestickSeriesRef.current, ictSignalRef.current, ictOverlaysRef.current)
        renderCisdMarkers(
          candlestickSeriesRef.current,
          ictSignalRef.current?.twins_state,
          latestTs,
          ictOverlaysRef.current,
        )

        setError(null)
        setIsLoading(false)
        setForceUpdate((n) => n + 1)
      })
      .catch((err) => {
        if (!isMounted) return
        setError(err instanceof Error ? err.message : 'Failed to load kline data')
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

  // Reactive ICT price lines and CISD markers on signal or overlay changes
  useEffect(() => {
    renderIctPriceLines(candlestickSeriesRef.current, ictSignal, ictOverlays)
    renderCisdMarkers(
      candlestickSeriesRef.current,
      ictSignal?.twins_state,
      latestCandleTimeRef.current,
      ictOverlays,
    )
  }, [ictSignal, ictOverlays])

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

  // Prepare translucent shaded boxes for SVG overlay
  const boxes: Array<{
    type: string
    top: number
    bottom: number
    fillColor: string
    strokeColor: string
    textColor: string
    label: string
  }> = []

  const pdArrays = ictSignal?.pd_arrays || []
  const twinsState = ictSignal?.twins_state
  const overlays = {
    showFvg: true,
    showBreakers: true,
    showOte: true,
    showStdv: true,
    showCisdMarkers: true,
    ...ictOverlays,
  }

  if (overlays.showFvg) {
    for (const pda of pdArrays) {
      if (pda.array_type === 'FVG_BISI') {
        boxes.push({
          type: 'fvg_bisi',
          top: pda.top,
          bottom: pda.bottom,
          fillColor: 'rgba(16, 185, 129, 0.12)',
          strokeColor: 'rgba(16, 185, 129, 0.4)',
          textColor: '#10b981',
          label: `+FVG BISI [CE: $${pda.mean_threshold.toLocaleString()}]`,
        })
      } else if (pda.array_type === 'FVG_SIBI') {
        boxes.push({
          type: 'fvg_sibi',
          top: pda.top,
          bottom: pda.bottom,
          fillColor: 'rgba(244, 63, 94, 0.12)',
          strokeColor: 'rgba(244, 63, 94, 0.4)',
          textColor: '#f43f5e',
          label: `-FVG SIBI [CE: $${pda.mean_threshold.toLocaleString()}]`,
        })
      } else if (pda.array_type === 'INVERSION_FVG') {
        boxes.push({
          type: 'inversion_fvg',
          top: pda.top,
          bottom: pda.bottom,
          fillColor: 'rgba(168, 85, 247, 0.12)',
          strokeColor: 'rgba(168, 85, 247, 0.4)',
          textColor: '#a855f7',
          label: `IFVG [CE: $${pda.mean_threshold.toLocaleString()}]`,
        })
      }
    }
  }

  if (overlays.showBreakers) {
    for (const pda of pdArrays) {
      if (pda.array_type === 'BREAKER_BLOCK') {
        const isBullish = pda.direction === 'BULLISH'
        boxes.push({
          type: 'breaker_block',
          top: pda.top,
          bottom: pda.bottom,
          fillColor: isBullish ? 'rgba(245, 158, 11, 0.12)' : 'rgba(251, 146, 60, 0.12)',
          strokeColor: isBullish ? 'rgba(245, 158, 11, 0.4)' : 'rgba(251, 146, 60, 0.4)',
          textColor: isBullish ? '#f59e0b' : '#fb923c',
          label: `${isBullish ? '+BB' : '-BB'} Breaker Block`,
        })
      }
    }
  }

  if (overlays.showOte && twinsState?.ote_62 && twinsState?.ote_79) {
    const oteTop = Math.max(twinsState.ote_62, twinsState.ote_79)
    const oteBottom = Math.min(twinsState.ote_62, twinsState.ote_79)
    boxes.push({
      type: 'ote_band',
      top: oteTop,
      bottom: oteBottom,
      fillColor: 'rgba(168, 85, 247, 0.08)',
      strokeColor: 'rgba(168, 85, 247, 0.3)',
      textColor: '#c084fc',
      label: 'OTE Band (62.0% - 79.0%)',
    })
  }

  return (
    <div
      className={`relative w-full h-[280px] bg-[#0a0f1d] rounded-xl overflow-hidden border border-white/5 ${className ?? ''}`}
      data-testid={`pair-candlestick-chart-${symbol.toLowerCase()}`}
      data-symbol={symbol}
      data-interval={interval}
    >
      {/* Timeframe Selector Bar */}
      <div
        className="absolute top-2 right-2 z-10 flex items-center gap-1 p-0.5 bg-black/60 backdrop-blur-xs rounded-lg border border-white/10"
        data-testid={`timeframe-selector-${symbol.toLowerCase()}`}
      >
        {(['1m', '5m', '15m', '1h', '4h'] as const).map((tf) => (
          <button
            key={tf}
            type="button"
            onClick={() => onIntervalChange?.(tf)}
            className={`px-2 py-0.5 rounded text-[11px] font-mono font-medium transition-colors ${
              interval === tf
                ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 shadow-[0_0_8px_rgba(6,182,212,0.2)]'
                : 'text-zinc-400 hover:text-white hover:bg-white/[0.04] border border-transparent'
            }`}
            data-testid={`timeframe-${tf}-${symbol.toLowerCase()}`}
          >
            {tf}
          </button>
        ))}
      </div>

      <div
        ref={containerRef}
        className="w-full h-full"
        data-testid="chart-canvas-container"
      />

      {/* Shaded Translucent PDA Boxes Overlay Layer */}
      {ictSignal && (
        <svg
          className="absolute inset-0 w-full h-full pointer-events-none z-[5]"
          data-testid="pda-box-overlay"
        >
          {boxes.map((box, idx) => {
            const hasCoordinates = Boolean(chartRef.current && candlestickSeriesRef.current)
            const yTop = hasCoordinates
              ? candlestickSeriesRef.current?.priceToCoordinate(box.top)
              : null
            const yBottom = hasCoordinates
              ? candlestickSeriesRef.current?.priceToCoordinate(box.bottom)
              : null

            let y: number | string = 10 + idx * 30
            let height: number | string = 24
            if (
              yTop !== null &&
              yTop !== undefined &&
              yBottom !== null &&
              yBottom !== undefined
            ) {
              y = Math.min(yTop, yBottom)
              height = Math.max(2, Math.abs(yBottom - yTop))
            }

            return (
              <g
                key={`pda-box-${box.type}-${idx}`}
                data-testid={`pda-box-${box.type.toLowerCase()}`}
              >
                <rect
                  x="0"
                  y={y}
                  width="100%"
                  height={height}
                  fill={box.fillColor}
                  stroke={box.strokeColor}
                  strokeWidth="1"
                  strokeDasharray="4 2"
                  opacity="0.8"
                />
                <text
                  x="8"
                  y={typeof y === 'number' ? y + 12 : 12}
                  fill={box.textColor}
                  fontSize="10"
                  fontFamily="monospace"
                  fontWeight="bold"
                >
                  {box.label}
                </text>
              </g>
            )
          })}
        </svg>
      )}

      {isLoading && (
        <div
          className="absolute inset-0 flex items-center justify-center bg-[#0a0f1d]/70 backdrop-blur-xs z-10"
          data-testid="chart-loading-overlay"
        >
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-900/90 border border-white/10 text-xs font-mono text-slate-300">
            <span className="loading loading-spinner loading-xs text-cyan-400" />
            <span>{`Loading ${symbol} (${interval})...`}</span>
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
