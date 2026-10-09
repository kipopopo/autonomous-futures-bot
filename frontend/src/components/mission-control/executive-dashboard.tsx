import type { ExecutiveDashboardModel } from './types'
import { MissionControlHeader } from './mission-control-header'
import { KpiCards } from './kpi-cards'
import { MarketPositionsCard } from './market-positions-card'
import { StrategyConfluenceRadar } from './strategy-confluence-radar'
import { OrderFeedTable } from './order-feed-table'

export interface ExecutiveDashboardProps {
  model: ExecutiveDashboardModel
  onRefresh: () => void
  isLoading?: boolean
}

export function ExecutiveDashboard({
  model,
  onRefresh,
  isLoading = false,
}: ExecutiveDashboardProps) {
  return (
    <div className="w-full">
      {/* R1: Top Mission Control Header */}
      <MissionControlHeader
        status={model.botStatus}
        onRefresh={onRefresh}
        isLoading={isLoading}
      />

      {/* R1: 4 Key Owner KPI Cards */}
      <KpiCards kpis={model.kpis} />

      {/* R2: Live Market Watch & Active Positions Card */}
      <MarketPositionsCard positions={model.positions} />

      {/* R3: Strategy & Scalper Confluence Radar */}
      <StrategyConfluenceRadar
        btcMacroTrend={model.radar.btcMacroTrend}
        scalperCriteria={model.radar.scalperCriteria}
        hawkesHazard={model.radar.hawkesHazard}
      />

      {/* R4: Clean Real-Time Order Feed & Execution Log */}
      <OrderFeedTable orders={model.orders} />
    </div>
  )
}
