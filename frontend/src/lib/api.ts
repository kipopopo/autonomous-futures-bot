import type {
  BundleResponse,
  ComponentsResponse,
  QualificationDetailResponse,
  CreatorQualificationsResponse,
  CreatorRegistryResponse,
  DashboardApiData,
  HealthResponse,
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

  return {
    health,
    bundle,
    components,
    creatorRegistry,
    creatorQualifications,
    creatorQualificationError,
  }
}
