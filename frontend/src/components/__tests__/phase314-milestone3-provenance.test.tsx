import { describe, it, expect } from 'vitest'
import { renderToString } from 'react-dom/server'
import { ProvenanceBadge } from '../mission-control/provenance-badge'
import { KpiCards } from '../mission-control/kpi-cards'
import { MarketPositionsCard } from '../mission-control/market-positions-card'
import { StrategyConfluenceRadar } from '../mission-control/strategy-confluence-radar'
import { StrategyEvolutionRadar } from '../mission-control/strategy-evolution-radar'
import { OrderFeedTable } from '../mission-control/order-feed-table'
import { ExecutivePositionsPage } from '../executive-positions-page'
import { ExecutiveTradesPage } from '../executive-trades-page'
import { ExecutiveSafetyPage } from '../executive-safety-page'
import {
  buildProductionLaunchModel,
  buildLiveMarketModel,
  buildBracketPositionsModel,
  buildMicrostructureModel,
  buildRiskModel,
  buildKillSwitchModel,
} from '@/lib/canary'
import { buildExecutiveDashboardModel } from '../mission-control/adapter'

describe('Phase 314 Milestone 3 Provenance Badging & Truth in Labeling', () => {
  it('renders ProvenanceBadge correctly for all 3 data sources', () => {
    const liveExchangeHtml = renderToString(<ProvenanceBadge source="LIVE EXCHANGE" />)
    expect(liveExchangeHtml).toContain('LIVE EXCHANGE')
    expect(liveExchangeHtml).toContain('data-testid="provenance-badge-live-exchange"')

    const daemonHtml = renderToString(<ProvenanceBadge source="DAEMON 24/7" />)
    expect(daemonHtml).toContain('DAEMON 24/7')
    expect(daemonHtml).toContain('data-testid="provenance-badge-daemon-24-7"')

    const researchHtml = renderToString(<ProvenanceBadge source="RESEARCH ARTIFACT / SIMULATION" />)
    expect(researchHtml).toContain('RESEARCH ARTIFACT / SIMULATION')
    expect(researchHtml).toContain('data-testid="provenance-badge-research-artifact"')
  })

  it('renders LIVE EXCHANGE and DAEMON 24/7 badges on KpiCards', () => {
    const prodLaunch = buildProductionLaunchModel(null)
    const liveMarket = buildLiveMarketModel(null)
    const brackets = buildBracketPositionsModel(null)
    const micro = buildMicrostructureModel(null)
    const telemetry = { status: 'OPEN' as const, latencyMs: 12.0 }

    const adapted = buildExecutiveDashboardModel(
      prodLaunch,
      liveMarket,
      brackets,
      micro,
      telemetry,
      new Date(),
    )

    const html = renderToString(<KpiCards kpis={adapted.kpis} />)
    expect(html).toContain('provenance-badge-live-exchange')
    expect(html).toContain('provenance-badge-daemon-24-7')
    expect(html).toContain('LIVE EXCHANGE')
    expect(html).toContain('DAEMON 24/7')
  })

  it('renders LIVE EXCHANGE badge on MarketPositionsCard and OrderFeedTable', () => {
    const prodLaunch = buildProductionLaunchModel(null)
    const liveMarket = buildLiveMarketModel(null)
    const brackets = buildBracketPositionsModel(null)
    const micro = buildMicrostructureModel(null)
    const telemetry = { status: 'OPEN' as const, latencyMs: 12.0 }

    const adapted = buildExecutiveDashboardModel(
      prodLaunch,
      liveMarket,
      brackets,
      micro,
      telemetry,
      new Date(),
    )

    const marketHtml = renderToString(<MarketPositionsCard positions={adapted.positions} />)
    expect(marketHtml).toContain('provenance-badge-live-exchange')

    const orderHtml = renderToString(<OrderFeedTable orders={adapted.orders} />)
    expect(orderHtml).toContain('provenance-badge-live-exchange')
  })

  it('renders DAEMON 24/7 badge on StrategyConfluenceRadar', () => {
    const prodLaunch = buildProductionLaunchModel(null)
    const liveMarket = buildLiveMarketModel(null)
    const brackets = buildBracketPositionsModel(null)
    const micro = buildMicrostructureModel(null)
    const telemetry = { status: 'OPEN' as const, latencyMs: 12.0 }

    const adapted = buildExecutiveDashboardModel(
      prodLaunch,
      liveMarket,
      brackets,
      micro,
      telemetry,
      new Date(),
    )

    const radarHtml = renderToString(
      <StrategyConfluenceRadar
        btcMacroTrend={adapted.radar.btcMacroTrend}
        scalperCriteria={adapted.radar.scalperCriteria}
        hawkesHazard={adapted.radar.hawkesHazard}
      />,
    )
    expect(radarHtml).toContain('provenance-badge-daemon-24-7')
  })

  it('renders DAEMON 24/7 and RESEARCH ARTIFACT badges on StrategyEvolutionRadar', () => {
    const prodLaunch = buildProductionLaunchModel(null)
    const liveMarket = buildLiveMarketModel(null)
    const brackets = buildBracketPositionsModel(null)
    const micro = buildMicrostructureModel(null)
    const telemetry = { status: 'OPEN' as const, latencyMs: 12.0 }

    const adapted = buildExecutiveDashboardModel(
      prodLaunch,
      liveMarket,
      brackets,
      micro,
      telemetry,
      new Date(),
    )

    const evolutionHtml = renderToString(
      <StrategyEvolutionRadar evolutionRadar={adapted.evolutionRadar} />,
    )
    expect(evolutionHtml).toContain('provenance-badge-daemon-24-7')
    expect(evolutionHtml).toContain('provenance-badge-research-artifact')
  })

  it('renders provenance badges across all executive subpages', () => {
    const prodLaunch = buildProductionLaunchModel(null)
    const liveMarket = buildLiveMarketModel(null)
    const brackets = buildBracketPositionsModel(null)
    const risk = buildRiskModel(null)
    const killSwitch = buildKillSwitchModel(null)
    const micro = buildMicrostructureModel(null)
    const telemetry = { status: 'OPEN' as const, latencyMs: 12.0 }

    const adapted = buildExecutiveDashboardModel(
      prodLaunch,
      liveMarket,
      brackets,
      micro,
      telemetry,
      new Date(),
    )

    const positionsHtml = renderToString(
      <ExecutivePositionsPage
        positions={adapted.positions}
        bracketPositionsModel={brackets}
        liveMarketModel={liveMarket}
      />,
    )
    expect(positionsHtml).toContain('provenance-badge-live-exchange')

    const tradesHtml = renderToString(<ExecutiveTradesPage orders={adapted.orders} />)
    expect(tradesHtml).toContain('provenance-badge-live-exchange')

    const safetyHtml = renderToString(
      <ExecutiveSafetyPage
        productionLaunchModel={prodLaunch}
        riskModel={risk}
        killSwitchModel={killSwitch}
        microstructureModel={micro}
        liveMarketModel={liveMarket}
        latencyMs={12.0}
      />,
    )
    expect(safetyHtml).toContain('provenance-badge-daemon-24-7')
  })
})
