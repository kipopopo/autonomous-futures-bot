export type DashboardPage =
  | 'overview'
  | 'creator'
  | 'learner'
  | 'microstructure'
  | 'risk'
  | 'accounting'

export function pageFromHash(hash: string): DashboardPage {
  const normalized = hash.replace(/^#\/?/, '')
  if (normalized === 'creator') return 'creator'
  if (normalized === 'learner') return 'learner'
  if (normalized === 'microstructure') return 'microstructure'
  if (normalized === 'risk') return 'risk'
  if (normalized === 'accounting') return 'accounting'
  return 'overview'
}
