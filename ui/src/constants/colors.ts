export const CATEGORY_COLORS: Record<string, string> = {
  gourmet: 'var(--color-accent-gourmet)',
  medicinal: 'var(--color-accent-medicinal)',
  active: 'var(--color-accent-active)',
}

export const CATEGORY_BADGE_COLORS: Record<string, { bg: string; text: string }> = {
  gourmet: { bg: 'bg-green-500/10', text: 'text-green-500' },
  medicinal: { bg: 'bg-amber-500/10', text: 'text-amber-500' },
  active: { bg: 'bg-purple-500/10', text: 'text-purple-500' },
}

export const STATUS_COLORS: Record<string, string> = {
  active: 'var(--color-accent-gourmet)',
  completed: 'var(--color-accent-active)',
  aborted: 'var(--color-danger)',
  paused: 'var(--color-warning)',
}

export const HEALTH_COLORS: Record<string, string> = {
  healthy: 'var(--color-success)',
  concern: 'var(--color-warning)',
  contaminated: 'var(--color-danger)',
  unknown: 'var(--color-text-secondary)',
}
