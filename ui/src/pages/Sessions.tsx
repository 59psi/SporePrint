import { useEffect, useState } from 'react'
import { Sprout, Plus, ChevronRight } from 'lucide-react'
import { api } from '../api/client'
import { STATUS_COLORS } from '../constants/colors'
import { useSessionStore, type Session } from '../stores/sessionStore'
import SessionDetail from '../components/sessions/SessionDetail'
import SessionWizard from '../components/sessions/SessionWizard'

export default function Sessions() {
  const { sessions, setSessions } = useSessionStore()
  const [showWizard, setShowWizard] = useState(false)
  const [selectedId, setSelectedId] = useState<number | null>(null)

  useEffect(() => {
    api.get<Session[]>('/sessions').then(setSessions).catch(() => {})
  }, [setSessions])

  const handleCreated = (session: Session) => {
    setSessions([session, ...sessions])
    setShowWizard(false)
    setSelectedId(session.id)
  }

  if (showWizard) {
    return <SessionWizard onCreated={handleCreated} onCancel={() => setShowWizard(false)} />
  }

  if (selectedId !== null) {
    return (
      <SessionDetail
        sessionId={selectedId}
        onBack={() => setSelectedId(null)}
      />
    )
  }

  const active = sessions.filter((s) => s.status === 'active')
  const completed = sessions.filter((s) => s.status !== 'active')

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold">Sessions</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">Manage grow sessions</p>
        </div>
        <button
          onClick={() => setShowWizard(true)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--color-accent-gourmet)] text-white text-sm font-medium hover:opacity-90 transition-opacity"
        >
          <Plus size={16} />
          New Session
        </button>
      </div>

      {active.length > 0 && (
        <div className="mb-6">
          <h2 className="text-sm font-medium text-[var(--color-text-secondary)] mb-2 uppercase tracking-wider">Active</h2>
          <div className="space-y-2">
            {active.map((s) => (
              <SessionCard key={s.id} session={s} onClick={() => setSelectedId(s.id)} />
            ))}
          </div>
        </div>
      )}

      {completed.length > 0 && (
        <div>
          <h2 className="text-sm font-medium text-[var(--color-text-secondary)] mb-2 uppercase tracking-wider">Completed / Aborted</h2>
          <div className="space-y-2">
            {completed.map((s) => (
              <SessionCard key={s.id} session={s} onClick={() => setSelectedId(s.id)} />
            ))}
          </div>
        </div>
      )}

      {sessions.length === 0 && (
        <div className="bg-[var(--color-bg-card)] rounded-xl p-12 border border-[var(--color-border)] text-center">
          <Sprout size={48} className="mx-auto mb-4 text-[var(--color-text-secondary)]" />
          <p className="text-[var(--color-text-secondary)]">No sessions yet. Create one to get started.</p>
        </div>
      )}
    </div>
  )
}

function SessionCard({ session, onClick }: { session: Session; onClick: () => void }) {
  const statusColors = STATUS_COLORS

  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-4 p-4 bg-[var(--color-bg-card)] rounded-xl border border-[var(--color-border)] hover:border-[var(--color-bg-hover)] transition-colors text-left"
    >
      <div className="flex-1 min-w-0">
        <p className="font-medium truncate">{session.name}</p>
        <p className="text-sm text-[var(--color-text-secondary)]">
          <span style={{ color: statusColors[session.status] }}>{session.status}</span>
          {' · '}
          {session.species_profile_id.replace(/_/g, ' ')}
          {' · '}
          {session.current_phase.replace(/_/g, ' ')}
        </p>
      </div>
      <ChevronRight size={16} className="text-[var(--color-text-secondary)]" />
    </button>
  )
}
