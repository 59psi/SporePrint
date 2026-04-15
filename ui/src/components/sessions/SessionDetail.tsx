import { useEffect, useState } from 'react'
import {
  ArrowLeft, Square, Trash2, MessageSquare, Scale,
  ChevronRight, Clock,
} from 'lucide-react'
import { api } from '../../api/client'
import { PHASE_ORDER } from '../../constants/phases'
import { displayWeight, tempLabel } from '../../lib/units'
import PhaseTimeline from './PhaseTimeline'
import TelemetryChart from './TelemetryChart'

interface SessionFull {
  id: number
  name: string
  species_profile_id: string
  substrate: string | null
  substrate_volume: string | null
  inoculation_date: string | null
  current_phase: string
  status: string
  created_at: number
  total_wet_yield_g: number
  total_dry_yield_g: number
  tub_number: string | null
  shelf_number: number | null
  shelf_side: string | null
  phase_history: { phase: string; entered_at: number; exited_at: number | null }[]
}

interface Event {
  id: number
  type: string
  source: string
  description: string
  timestamp: number
}

interface Props {
  sessionId: number
  onBack: () => void
}

const phaseOptions = PHASE_ORDER

export default function SessionDetail({ sessionId, onBack }: Props) {
  const [session, setSession] = useState<SessionFull | null>(null)
  const [events, setEvents] = useState<Event[]>([])
  const [tab, setTab] = useState<'charts' | 'events' | 'notes'>('charts')
  const [noteText, setNoteText] = useState('')
  const [harvestForm, setHarvestForm] = useState({ flush: 1, wet: '', dry: '' })
  const [showHarvest, setShowHarvest] = useState(false)
  const [timeRange, setTimeRange] = useState('24h')
  const rangeSecondsMap: Record<string, number> = {
    '1h': 3600, '6h': 21600, '24h': 86400, '7d': 604800, '30d': 2592000,
  }
  const rangeSeconds = rangeSecondsMap[timeRange] || 86400

  useEffect(() => {
    api.get<SessionFull>(`/sessions/${sessionId}`).then(setSession).catch(() => {})
    api.get<Event[]>(`/sessions/${sessionId}/events`).then(setEvents).catch(() => {})
  }, [sessionId])

  if (!session) return null

  const advancePhase = async (phase: string) => {
    const result = await api.post<SessionFull>(`/sessions/${sessionId}/phase`, { phase })
    setSession(result)
    api.get<Event[]>(`/sessions/${sessionId}/events`).then(setEvents)
  }

  const addNote = async () => {
    if (!noteText.trim()) return
    await api.post(`/sessions/${sessionId}/note`, { text: noteText })
    setNoteText('')
    api.get<Event[]>(`/sessions/${sessionId}/events`).then(setEvents)
  }

  const addHarvest = async () => {
    await api.post(`/sessions/${sessionId}/harvest`, {
      flush_number: harvestForm.flush,
      wet_weight_g: harvestForm.wet ? parseFloat(harvestForm.wet) : null,
      dry_weight_g: harvestForm.dry ? parseFloat(harvestForm.dry) : null,
    })
    setShowHarvest(false)
    api.get<SessionFull>(`/sessions/${sessionId}`).then(setSession)
    api.get<Event[]>(`/sessions/${sessionId}/events`).then(setEvents)
  }

  const completeSession = async () => {
    const result = await api.post<SessionFull>(`/sessions/${sessionId}/complete`, {})
    setSession(result)
  }

  const abortSession = async () => {
    const result = await api.post<SessionFull>(`/sessions/${sessionId}/abort`, {})
    setSession(result)
  }

  const nextPhaseIdx = phaseOptions.indexOf(session.current_phase) + 1
  const nextPhase = nextPhaseIdx < phaseOptions.length ? phaseOptions[nextPhaseIdx] : null

  const resolution = timeRange === '7d' || timeRange === '30d' ? 'hourly' : undefined

  return (
    <div>
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <button onClick={onBack} className="p-2 rounded-lg hover:bg-[var(--color-bg-hover)]">
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-semibold">{session.name}</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">
            {session.species_profile_id.replace(/_/g, ' ')}
            {session.substrate && ` · ${session.substrate}`}
            {session.substrate_volume && ` (${session.substrate_volume})`}
            {(session.tub_number || session.shelf_number) && (
              <span className="text-[var(--color-text-secondary)]">
                {' · '}
                {session.tub_number && `Tub ${session.tub_number}`}
                {session.shelf_number != null && ` Shelf ${session.shelf_number}`}
                {session.shelf_side && ` ${session.shelf_side}`}
              </span>
            )}
          </p>
        </div>
        {session.status === 'active' && (
          <div className="flex gap-2">
            {nextPhase && (
              <button
                onClick={() => advancePhase(nextPhase)}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-[var(--color-accent-gourmet)] text-white text-sm"
              >
                <ChevronRight size={14} />
                {nextPhase.replace(/_/g, ' ')}
              </button>
            )}
            <button
              onClick={completeSession}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-[var(--color-accent-gourmet)] text-[var(--color-accent-gourmet)] text-sm"
            >
              <Square size={14} />
              Complete
            </button>
            <button
              onClick={abortSession}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-[var(--color-danger)] text-[var(--color-danger)] text-sm"
            >
              <Trash2 size={14} />
              Abort
            </button>
          </div>
        )}
      </div>

      {/* Phase Timeline */}
      <div className="bg-[var(--color-bg-card)] rounded-xl p-4 border border-[var(--color-border)] mb-4">
        <PhaseTimeline phases={session.phase_history} currentPhase={session.current_phase} />
      </div>

      {/* Stats Bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
        {[
          { label: 'Status', value: session.status },
          { label: 'Phase', value: session.current_phase.replace(/_/g, ' ') },
          { label: 'Wet Yield', value: displayWeight(session.total_wet_yield_g) },
          { label: 'Dry Yield', value: displayWeight(session.total_dry_yield_g) },
        ].map((s) => (
          <div key={s.label} className="bg-[var(--color-bg-card)] rounded-lg p-3 border border-[var(--color-border)]">
            <p className="text-xs text-[var(--color-text-secondary)]">{s.label}</p>
            <p className="text-sm font-medium capitalize">{s.value}</p>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 p-1 bg-[var(--color-bg-secondary)] rounded-lg w-fit">
        {(['charts', 'events', 'notes'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-1.5 rounded-md text-sm capitalize ${
              tab === t
                ? 'bg-[var(--color-bg-card)] text-[var(--color-text-primary)]'
                : 'text-[var(--color-text-secondary)]'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === 'charts' && (
        <div>
          {/* Time range selector */}
          <div className="flex gap-1 mb-4">
            {['1h', '6h', '24h', '7d', '30d'].map((r) => (
              <button
                key={r}
                onClick={() => setTimeRange(r)}
                className={`px-3 py-1 rounded-md text-xs ${
                  timeRange === r
                    ? 'bg-[var(--color-bg-card)] text-[var(--color-text-primary)]'
                    : 'text-[var(--color-text-secondary)]'
                }`}
              >
                {r}
              </button>
            ))}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <TelemetryChart
              nodeId="climate-01" sensor="temp_f" label="Temperature" unit={tempLabel()}
              color="#ef4444" rangeSeconds={rangeSeconds} resolution={resolution}
            />
            <TelemetryChart
              nodeId="climate-01" sensor="humidity" label="Humidity" unit="%"
              color="#3b82f6" rangeSeconds={rangeSeconds} resolution={resolution}
            />
            <TelemetryChart
              nodeId="climate-01" sensor="co2_ppm" label="CO2" unit="ppm"
              color="#f59e0b" rangeSeconds={rangeSeconds} resolution={resolution}
            />
            <TelemetryChart
              nodeId="climate-01" sensor="lux" label="Light" unit="lux"
              color="#22c55e" rangeSeconds={rangeSeconds} resolution={resolution}
            />
          </div>
        </div>
      )}

      {tab === 'events' && (
        <div className="bg-[var(--color-bg-card)] rounded-xl border border-[var(--color-border)]">
          {events.length > 0 ? (
            <div className="divide-y divide-[var(--color-border)]">
              {events.map((e) => (
                <div key={e.id} className="flex items-start gap-3 p-3">
                  <Clock size={14} className="text-[var(--color-text-secondary)] mt-0.5 flex-shrink-0" />
                  <div className="flex-1">
                    <p className="text-sm">{e.description}</p>
                    <p className="text-xs text-[var(--color-text-secondary)]">
                      {e.type} &middot; {e.source} &middot;{' '}
                      {new Date(e.timestamp * 1000).toLocaleString()}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="p-6 text-center text-sm text-[var(--color-text-secondary)]">No events yet</p>
          )}
        </div>
      )}

      {tab === 'notes' && (
        <div className="space-y-4">
          {/* Add Note */}
          {session.status === 'active' && (
            <div className="bg-[var(--color-bg-card)] rounded-xl p-4 border border-[var(--color-border)]">
              <div className="flex gap-2">
                <input
                  value={noteText}
                  onChange={(e) => setNoteText(e.target.value)}
                  placeholder="Add observation..."
                  className="flex-1 p-2 rounded-lg bg-[var(--color-bg-primary)] border border-[var(--color-border)] text-sm focus:outline-none"
                  onKeyDown={(e) => e.key === 'Enter' && addNote()}
                />
                <button
                  onClick={addNote}
                  className="px-3 py-2 rounded-lg bg-[var(--color-accent-gourmet)] text-white text-sm"
                >
                  <MessageSquare size={14} />
                </button>
              </div>

              <div className="mt-3 flex gap-2">
                <button
                  onClick={() => setShowHarvest(!showHarvest)}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-[var(--color-border)] text-sm text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]"
                >
                  <Scale size={14} />
                  Log Harvest
                </button>
              </div>

              {showHarvest && (
                <div className="mt-3 p-3 bg-[var(--color-bg-primary)] rounded-lg space-y-2">
                  <div className="grid grid-cols-3 gap-2">
                    <input
                      type="number"
                      value={harvestForm.flush}
                      onChange={(e) => setHarvestForm({ ...harvestForm, flush: parseInt(e.target.value) || 1 })}
                      placeholder="Flush #"
                      className="p-2 rounded bg-[var(--color-bg-card)] border border-[var(--color-border)] text-sm"
                    />
                    <input
                      value={harvestForm.wet}
                      onChange={(e) => setHarvestForm({ ...harvestForm, wet: e.target.value })}
                      placeholder="Wet (g)"
                      className="p-2 rounded bg-[var(--color-bg-card)] border border-[var(--color-border)] text-sm"
                    />
                    <input
                      value={harvestForm.dry}
                      onChange={(e) => setHarvestForm({ ...harvestForm, dry: e.target.value })}
                      placeholder="Dry (g)"
                      className="p-2 rounded bg-[var(--color-bg-card)] border border-[var(--color-border)] text-sm"
                    />
                  </div>
                  <button
                    onClick={addHarvest}
                    className="px-3 py-1.5 rounded-lg bg-[var(--color-accent-gourmet)] text-white text-sm"
                  >
                    Record Harvest
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
