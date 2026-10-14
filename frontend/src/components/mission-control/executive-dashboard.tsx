import type { ExecutiveDashboardModel, IctSignalsResponse } from './types'
import { MissionControlHeader } from './mission-control-header'
import { KpiCards } from './kpi-cards'
import { PairPriceTickersCard } from './pair-price-tickers-card'
import { StrategyEvolutionRadar } from './strategy-evolution-radar'
import { OrderFeedTable } from './order-feed-table'
import { useIctSignals, getFallbackIctSignals } from '../../lib/use-ict-signals'

export interface ExecutiveDashboardProps {
  model: ExecutiveDashboardModel
  onRefresh: () => void
  isLoading?: boolean
  ictSignals?: IctSignalsResponse | null
  onSelectPair?: (symbol: string) => void
}

export function ExecutiveDashboard({
  model,
  onRefresh,
  isLoading = false,
  ictSignals: propIctSignals,
  onSelectPair,
}: ExecutiveDashboardProps) {
  // Pull live ICT signals hook to provide real-time non-hardcoded entry status
  const { data: hookIctSignals } = useIctSignals({
    enabled: true,
    initialData: propIctSignals || getFallbackIctSignals(),
  })

  const resolvedIctSignals = propIctSignals?.signals || hookIctSignals?.signals || null

  return (
    <div className="w-full space-y-6" data-testid="executive-dashboard">
      {/* Top Mission Control Header */}
      <MissionControlHeader
        status={model.botStatus}
        onRefresh={onRefresh}
        isLoading={isLoading}
      />

      {/* 4 Key Owner KPI Cards */}
      <KpiCards kpis={model.kpis} />

      {/* 12-Pair Price Ticker Matrix with Dynamic Entry Status */}
      <PairPriceTickersCard
        positions={model.positions}
        pairTickers={model.pairTickers}
        ictSignals={resolvedIctSignals}
        scalperCriteria={model.radar.scalperCriteria}
        btcMacroTrend={model.radar.btcMacroTrend}
        onSelectPair={onSelectPair}
      />

      {/* AI Self-Learning Strategy Evolution & Autopsy Status */}
      <StrategyEvolutionRadar evolutionRadar={model.evolutionRadar} />

      {/* Recent Orders & Execution Log */}
      <OrderFeedTable orders={model.orders} />
    </div>
  )
}
