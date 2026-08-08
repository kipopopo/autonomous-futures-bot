import type {
  BundleResponse,
  ComponentsResponse,
  QualificationDetailResponse,
  CreatorQualificationsResponse,
  CreatorRegistryResponse,
  DashboardApiData,
  HealthResponse,
  LearnerArtifactResponse,
  LearnerRunResponse,
} from './dashboard'

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) {
    throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  }
  return (await response.json()) as T
}

async function fetchOptionalCreatorRegistry(): Promise<CreatorRegistryResponse | null> {
  const path = '/api/v1/creator/registry'
  const response = await fetch(path, {
    headers: { Accept: 'application/json' },
  })
  if (response.status === 404) return null
  if (!response.ok) {
    throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  }
  return (await response.json()) as CreatorRegistryResponse
}

async function fetchOptionalLearnerArtifact(): Promise<LearnerArtifactResponse | null> {
  const path = '/api/v1/learner/artifact'
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  return (await response.json()) as LearnerArtifactResponse
}

async function fetchOptionalLearnerRun(): Promise<LearnerRunResponse | null> {
  const path = '/api/v1/learner/run'
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  return (await response.json()) as LearnerRunResponse
}

export async function fetchCreatorQualifications(): Promise<CreatorQualificationsResponse | null> {
  const path = '/api/v1/creator/qualifications'
  const response = await fetch(path, {
    headers: { Accept: 'application/json' },
  })
  if (response.status === 404) return null
  if (!response.ok) {
    throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  }
  return (await response.json()) as CreatorQualificationsResponse
}

export async function fetchCreatorQualification(
  candidateId: string,
): Promise<QualificationDetailResponse | null> {
  const path = `/api/v1/creator/qualifications/${encodeURIComponent(candidateId)}`
  const response = await fetch(path, {
    headers: { Accept: 'application/json' },
  })
  if (response.status === 404) return null
  if (!response.ok) {
    throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  }
  return (await response.json()) as QualificationDetailResponse
}

export async function fetchOverviewData(): Promise<DashboardApiData> {
  const [health, bundle, components, creatorRegistry] = await Promise.all([
    fetchJson<HealthResponse>('/health'),
    fetchJson<BundleResponse>('/api/v1/dataset/bundle'),
    fetchJson<ComponentsResponse>('/api/v1/dataset/components'),
    fetchOptionalCreatorRegistry(),
  ])

  let creatorQualifications: CreatorQualificationsResponse | null = null
  let creatorQualificationError: string | null = null
  try {
    creatorQualifications = await fetchCreatorQualifications()
  } catch (error) {
    creatorQualificationError = error instanceof Error
      ? error.message
      : 'Qualification evidence could not be verified'
  }

  let learnerArtifact: LearnerArtifactResponse | null = null
  let learnerArtifactError: string | null = null
  try {
    learnerArtifact = await fetchOptionalLearnerArtifact()
  } catch (error) {
    learnerArtifactError = error instanceof Error
      ? error.message
      : 'Learner artifact evidence could not be verified'
  }

  let learnerRun: LearnerRunResponse | null = null
  let learnerRunError: string | null = null
  try {
    learnerRun = await fetchOptionalLearnerRun()
  } catch (error) {
    learnerRunError = error instanceof Error
      ? error.message
      : 'Learner run evidence could not be verified'
  }

  return {
    health,
    bundle,
    components,
    creatorRegistry,
    creatorQualifications,
    creatorQualificationError,
    learnerArtifact,
    learnerArtifactError,
    learnerRun,
    learnerRunError,
  }
}
