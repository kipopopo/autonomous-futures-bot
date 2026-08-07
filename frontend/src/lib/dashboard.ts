export interface HealthResponse {
  status: 'ok'
  service: string
  paper_safe: boolean
  execution_authority: boolean
}

export interface BundleMetadata {
  symbols: string[]
  primary_interval: string
  context_interval: string
  context_feature_policy: string
  time_start: string
  time_end: string
}

export interface BundleResponse {
  verified: boolean
  registry_hash: string
  bundle_hash: string
  component_count: number
  bundle: BundleMetadata
}

export interface ComponentInspection {
  kind: string
  symbols: string[]
  interval: string | null
  artifact_ref: string
  data_ref: string | null
  manifest_hash: string
  artifact_sha256?: string | null
  rows?: number | null
  schema_version: string
}

export interface ComponentsResponse {
  verified: boolean
  component_count: number
  components: ComponentInspection[]
}

export interface DashboardApiData {
  health: HealthResponse | null
  bundle: BundleResponse | null
  components: ComponentsResponse | null
}

export type VerificationState = 'verified' | 'error'

export interface OverviewModel {
  verification: VerificationState
  paperSafe: boolean | null
  executionAuthority: boolean | null
  componentCount: number | null
  symbols: string[]
  bundleHash: string | null
  registryHash: string | null
  primaryInterval: string | null
  contextInterval: string | null
  contextFeaturePolicy: string | null
  timeStart: string | null
  timeEnd: string | null
  components: ComponentInspection[]
}

export function buildOverviewModel(data: DashboardApiData): OverviewModel {
  const verified =
    data.health?.status === 'ok' &&
    data.health.paper_safe === true &&
    data.health.execution_authority === false &&
    data.bundle?.verified === true &&
    data.components?.verified === true
  const bundle = data.bundle?.bundle

  return {
    verification: verified ? 'verified' : 'error',
    paperSafe: data.health?.paper_safe ?? null,
    executionAuthority: data.health?.execution_authority ?? null,
    componentCount: data.components?.component_count ?? data.bundle?.component_count ?? null,
    symbols: [...(bundle?.symbols ?? [])].sort(),
    bundleHash: data.bundle?.bundle_hash ?? null,
    registryHash: data.bundle?.registry_hash ?? null,
    primaryInterval: bundle?.primary_interval ?? null,
    contextInterval: bundle?.context_interval ?? null,
    contextFeaturePolicy: bundle?.context_feature_policy ?? null,
    timeStart: bundle?.time_start ?? null,
    timeEnd: bundle?.time_end ?? null,
    components: data.components?.components ?? [],
  }
}
