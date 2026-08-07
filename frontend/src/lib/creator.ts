import { buildOverviewModel, type DashboardApiData } from './dashboard'

export type CreatorFoundationState = 'verified' | 'unavailable'
export type CreatorAvailability = 'available' | 'unavailable'

export interface CreatorCandidateSummary {
  candidateId: string
  artifactHash: string
  artifactRef: string
  family: string
  symbols: string[]
  state: 'testing'
  creatorRunId: string
  createdAt: string
}

export interface CreatorModel {
  foundationState: CreatorFoundationState
  candidateAvailability: CreatorAvailability
  candidateCount: number | null
  candidates: CreatorCandidateSummary[]
  candidateRegistryHash: string | null
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
  const creatorRegistry = data.creatorRegistry?.verified ? data.creatorRegistry : null

  return {
    foundationState: overview.verification === 'verified' ? 'verified' : 'unavailable',
    candidateAvailability: creatorRegistry ? 'available' : 'unavailable',
    candidateCount: creatorRegistry?.candidate_count ?? null,
    candidates: creatorRegistry?.registry.entries.map((entry) => ({
      candidateId: entry.candidate_id,
      artifactHash: entry.artifact_hash,
      artifactRef: entry.artifact_ref,
      family: entry.family,
      symbols: entry.symbols,
      state: entry.state,
      creatorRunId: entry.creator_run_id,
      createdAt: entry.created_at,
    })) ?? [],
    candidateRegistryHash: creatorRegistry?.registry_hash ?? null,
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
