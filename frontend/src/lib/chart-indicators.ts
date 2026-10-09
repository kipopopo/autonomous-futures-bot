export interface MarketKline {
  timestamp: number // Unix epoch seconds
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface EmaPoint {
  time: number // Unix epoch seconds
  value: number
}

export interface VolumePoint {
  time: number // Unix epoch seconds
  value: number
  color: string
}

export interface OhlcSummary {
  open: number
  high: number
  low: number
  close: number
  volume: number
  high24h: number
  low24h: number
}

/**
 * Calculates Exponential Moving Average (EMA) for a candlestick series.
 *
 * Formula:
 *   Multiplier k = 2 / (period + 1)
 *
 * Behavior:
 *   - Returns [] if data is empty or period <= 0.
 *   - When data.length >= period: seeds at index (period - 1) using the Simple Moving
 *     Average (SMA) of the first `period` bars, then applies the standard EMA formula iteratively.
 *   - When data.length < period (warmup mode): seeds at index 0 using data[0].close,
 *     then applies EMA iteration for remaining bars so lines render without hard clipping.
 */
export function calculateEma(data: MarketKline[] | null | undefined, period: number): EmaPoint[] {
  if (!data || data.length === 0 || period <= 0) {
    return []
  }

  const k = 2 / (period + 1)
  const result: EmaPoint[] = []

  if (data.length >= period) {
    let sum = 0
    for (let i = 0; i < period; i++) {
      sum += data[i].close
    }
    let prevEma = sum / period
    result.push({
      time: data[period - 1].timestamp,
      value: Number(prevEma.toFixed(4)),
    })

    for (let i = period; i < data.length; i++) {
      const currentEma = data[i].close * k + prevEma * (1 - k)
      result.push({
        time: data[i].timestamp,
        value: Number(currentEma.toFixed(4)),
      })
      prevEma = currentEma
    }
  } else {
    // Warmup mode for datasets shorter than period
    let prevEma = data[0].close
    result.push({
      time: data[0].timestamp,
      value: Number(prevEma.toFixed(4)),
    })

    for (let i = 1; i < data.length; i++) {
      const currentEma = data[i].close * k + prevEma * (1 - k)
      result.push({
        time: data[i].timestamp,
        value: Number(currentEma.toFixed(4)),
      })
      prevEma = currentEma
    }
  }

  return result
}

/**
 * Maps candlestick data to volume histogram bars with emerald/rose coloring.
 * Green ('rgba(16, 185, 129, 0.5)') when close >= open.
 * Red ('rgba(244, 63, 94, 0.5)') when close < open.
 */
export function calculateVolumeSeries(data: MarketKline[] | null | undefined): VolumePoint[] {
  if (!data || data.length === 0) {
    return []
  }

  return data.map((k) => ({
    time: k.timestamp,
    value: k.volume,
    color: k.close >= k.open ? 'rgba(16, 185, 129, 0.5)' : 'rgba(244, 63, 94, 0.5)',
  }))
}

/**
 * Computes latest OHLC metrics and 24h high/low bounds across available candles.
 */
export function calculateOhlcSummary(data: MarketKline[] | null | undefined): OhlcSummary | null {
  if (!data || data.length === 0) {
    return null
  }

  const latest = data[data.length - 1]
  let high24h = latest.high
  let low24h = latest.low

  for (const bar of data) {
    if (bar.high > high24h) high24h = bar.high
    if (bar.low < low24h) low24h = bar.low
  }

  return {
    open: latest.open,
    high: latest.high,
    low: latest.low,
    close: latest.close,
    volume: latest.volume,
    high24h: Number(high24h.toFixed(2)),
    low24h: Number(low24h.toFixed(2)),
  }
}

/**
 * Generates deterministic synthetic candlestick data for offline environments and test runners.
 */
export function generateSyntheticKlines(
  symbol: string = 'SOLUSDT',
  interval: '15m' | '1h' = '15m',
  count: number = 100,
): MarketKline[] {
  if (count <= 0) {
    return []
  }

  const upperSym = symbol.toUpperCase()
  const basePrice = upperSym.startsWith('BTC')
    ? 85000
    : upperSym.startsWith('ETH')
      ? 2700
      : upperSym.startsWith('SOL')
        ? 180
        : 100

  const intervalSeconds = interval === '1h' ? 3600 : 900
  const now = Math.floor(Date.now() / 1000)
  const result: MarketKline[] = []

  let currentClose = basePrice

  for (let i = count - 1; i >= 0; i--) {
    const timestamp = now - i * intervalSeconds
    // Predictable oscillation with mild stochastic spread
    const phase = ((count - i) % 20) / 20
    const drift = Math.sin(phase * Math.PI * 2) * (basePrice * 0.003)
    const open = Number(currentClose.toFixed(2))
    const close = Number(Math.max(0.01, open + drift).toFixed(2))
    const spread = Math.abs(close - open) + basePrice * 0.001
    const high = Number((Math.max(open, close) + spread).toFixed(2))
    const low = Number(Math.max(0.01, Math.min(open, close) - spread).toFixed(2))
    const volume = Number((2500 + Math.abs(drift) * 100).toFixed(2))

    result.push({
      timestamp,
      open,
      high,
      low,
      close,
      volume,
    })

    currentClose = close
  }

  return result
}
