import { PHASE_ORDER } from '../../constants/phases'

interface Phase {
  phase: string
  entered_at: number
  exited_at: number | null
}

interface Props {
  phases: Phase[]
  currentPhase: string
}

const phaseLabels: Record<string, string> = {
  agar: 'Agar',
  liquid_culture: 'LC',
  grain_colonization: 'Grain',
  substrate_colonization: 'Sub. Colonization',
  primordia_induction: 'Primordia',
  fruiting: 'Fruiting',
  rest: 'Rest',
  complete: 'Complete',
}

function formatDuration(entered: number, exited: number | null): string {
  const end = exited || Date.now() / 1000
  const days = Math.floor((end - entered) / 86400)
  if (days === 0) return '<1d'
  return `${days}d`
}

export default function PhaseTimeline({ phases, currentPhase }: Props) {
  const activePhases = PHASE_ORDER.filter((p) =>
    phases.some((ph) => ph.phase === p) || p === currentPhase
  )

  return (
    <div className="flex items-center gap-1 overflow-x-auto py-2">
      {activePhases.map((phase, i) => {
        const phaseData = phases.find((p) => p.phase === phase)
        const isCurrent = phase === currentPhase
        const isCompleted = phaseData?.exited_at !== null && phaseData?.exited_at !== undefined
        const isActive = isCurrent && !isCompleted

        return (
          <div key={phase} className="flex items-center">
            {i > 0 && (
              <div
                className={`w-6 h-0.5 ${
                  isCompleted || isActive ? 'bg-[var(--color-accent-gourmet)]' : 'bg-[var(--color-border)]'
                }`}
              />
            )}
            <div
              className={`flex flex-col items-center px-3 py-2 rounded-lg text-xs transition-colors ${
                isActive
                  ? 'bg-[var(--color-accent-gourmet)]/10 border border-[var(--color-accent-gourmet)]/30'
                  : isCompleted
                  ? 'bg-[var(--color-bg-hover)]'
                  : 'opacity-40'
              }`}
            >
              <div
                className={`w-2.5 h-2.5 rounded-full mb-1 ${
                  isActive
                    ? 'bg-[var(--color-accent-gourmet)] animate-pulse'
                    : isCompleted
                    ? 'bg-[var(--color-accent-gourmet)]'
                    : 'bg-[var(--color-border)]'
                }`}
              />
              <span className="font-medium whitespace-nowrap">{phaseLabels[phase] || phase}</span>
              {phaseData && (
                <span className="text-[var(--color-text-secondary)]">
                  {formatDuration(phaseData.entered_at, phaseData.exited_at)}
                </span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
