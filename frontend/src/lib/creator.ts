import { buildOverviewModel, type DashboardApiData } from './dashboard'

export type CreatorFoundationState = 'verified' | 'unavailable'
export type CreatorAvailability = 'unavailable'

export interface CreatorModel {
  foundationState: CreatorFoundationState
  candidateAvailability: CreatorAvailability
  candidateCount: null
  symbols: string[]
  componentCount: number | null
  primaryInterval: string | null
  contextInterval: string | null
  contextPolicy: string | null
  timeStart: string | null
  timeEnd: string | null
  bundleHash: string | null
  registryHash: string | null
}

export function buildCreatorModel(data: DashboardApiData): CreatorModel {
  const overview = buildOverviewModel(data)

  return {
    foundationState: overview.verification === 'verified' ? 'verified' : 'unavailable',
    candidateAvailability: 'unavailable',
    candidateCount: null,
    symbols: overview.symbols,
    componentCount: overview.componentCount,
    primaryInterval: overview.primaryInterval,
    contextInterval: overview.contextInterval,
    contextPolicy: overview.contextFeaturePolicy,
    timeStart: overview.timeStart,
    timeEnd: overview.timeEnd,
    bundleHash: overview.bundleHash,
    registryHash: overview.registryHash,
  }
}
