export const PHASE_ORDER = [
  'agar', 'liquid_culture', 'grain_colonization',
  'substrate_colonization', 'primordia_induction',
  'fruiting', 'rest', 'complete',
] as const

export type GrowPhase = typeof PHASE_ORDER[number]
