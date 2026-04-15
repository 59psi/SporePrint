import { useState, useEffect } from 'react'
import { Calendar, Star, AlertTriangle, Thermometer, Droplets } from 'lucide-react'
import { api } from '../api/client'
import { displayTemp } from '../lib/units'

interface RecommendedSpecies {
  species_id: string
  common_name: string
  scientific_name: string
  score: number
  tldr: string
  optimal_temp_min_f: number
  optimal_temp_max_f: number
  optimal_humidity_min: number
  optimal_humidity_max: number
  warnings: string[]
}

interface MonthData {
  month: string
  avg_temp_f: number
  avg_humidity: number
  top_species: { common_name: string; score: number }[]
}

export default function Planner() {
  const [tab, setTab] = useState<'recommend' | 'calendar'>('recommend')
  const [outdoorTemp, setOutdoorTemp] = useState('')
  const [outdoorHumidity, setOutdoorHumidity] = useState('')
  const [results, setResults] = useState<RecommendedSpecies[]>([])
  const [calendar, setCalendar] = useState<MonthData[]>([])
  const [loading, setLoading] = useState(false)
  const [calendarLoading, setCalendarLoading] = useState(false)

  useEffect(() => {
    if (tab === 'calendar' && calendar.length === 0) {
      setCalendarLoading(true)
      api.get<MonthData[]>('/planner/calendar')
        .then(setCalendar)
        .catch(() => {})
        .finally(() => setCalendarLoading(false))
    }
  }, [tab, calendar.length])

  const handleFind = async () => {
    if (!outdoorTemp || !outdoorHumidity) return
    setLoading(true)
    try {
      const data = await api.get<RecommendedSpecies[]>(
        `/planner/recommend?outdoor_temp_f=${outdoorTemp}&outdoor_humidity=${outdoorHumidity}`
      )
      setResults(data)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold">Planner</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">Seasonal grow planner</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 p-1 bg-[var(--color-bg-card)] rounded-lg border border-[var(--color-border)] w-fit">
        <button
          onClick={() => setTab('recommend')}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            tab === 'recommend'
              ? 'bg-[var(--color-accent-gourmet)] text-white'
              : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'
          }`}
        >
          What Should I Grow?
        </button>
        <button
          onClick={() => setTab('calendar')}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            tab === 'calendar'
              ? 'bg-[var(--color-accent-gourmet)] text-white'
              : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'
          }`}
        >
          Calendar
        </button>
      </div>

      {tab === 'recommend' && (
        <div>
          {/* Input controls */}
          <div className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)] mb-6">
            <div className="flex flex-wrap items-end gap-4">
              <div>
                <label className="block text-xs text-[var(--color-text-secondary)] mb-1">
                  <Thermometer size={12} className="inline mr-1" />
                  Outdoor Temp (F)
                </label>
                <input
                  type="number"
                  value={outdoorTemp}
                  onChange={(e) => setOutdoorTemp(e.target.value)}
                  placeholder="72"
                  className="w-28 px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
                />
              </div>
              <div>
                <label className="block text-xs text-[var(--color-text-secondary)] mb-1">
                  <Droplets size={12} className="inline mr-1" />
                  Outdoor Humidity (%)
                </label>
                <input
                  type="number"
                  value={outdoorHumidity}
                  onChange={(e) => setOutdoorHumidity(e.target.value)}
                  placeholder="60"
                  className="w-28 px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
                />
              </div>
              <button
                onClick={handleFind}
                disabled={loading || !outdoorTemp || !outdoorHumidity}
                className="px-4 py-2 rounded-lg bg-[var(--color-accent-gourmet)] text-white text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
              >
                {loading ? 'Searching...' : 'Find Species'}
              </button>
            </div>
          </div>

          {/* Results */}
          {results.length > 0 && (
            <div className="space-y-3">
              {results.map((sp) => (
                <div
                  key={sp.species_id}
                  className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)]"
                >
                  <div className="flex items-start justify-between mb-2">
                    <div>
                      <h3 className="font-medium">{sp.common_name}</h3>
                      <p className="text-sm text-[var(--color-text-secondary)] italic">{sp.scientific_name}</p>
                    </div>
                    <div className="flex items-center gap-1 text-amber-400">
                      <Star size={16} fill="currentColor" />
                      <span className="text-sm font-semibold">{sp.score}</span>
                    </div>
                  </div>
                  <p className="text-sm text-[var(--color-text-secondary)] mb-3">{sp.tldr}</p>
                  <div className="flex flex-wrap gap-3 text-xs text-[var(--color-text-secondary)] mb-2">
                    <span>Temp: {displayTemp(sp.optimal_temp_min_f)}-{displayTemp(sp.optimal_temp_max_f)}</span>
                    <span>RH: {sp.optimal_humidity_min}-{sp.optimal_humidity_max}%</span>
                  </div>
                  {sp.warnings.length > 0 && (
                    <div className="space-y-1">
                      {sp.warnings.map((w, i) => (
                        <div key={i} className="flex items-center gap-1.5 text-xs text-amber-400">
                          <AlertTriangle size={12} />
                          <span>{w}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {results.length === 0 && !loading && (
            <div className="bg-[var(--color-bg-card)] rounded-xl p-12 border border-[var(--color-border)] text-center">
              <Calendar size={48} className="mx-auto mb-4 text-[var(--color-text-secondary)]" />
              <p className="text-[var(--color-text-secondary)]">Enter your outdoor conditions to find the best species to grow.</p>
            </div>
          )}
        </div>
      )}

      {tab === 'calendar' && (
        <div>
          {calendarLoading ? (
            <div className="text-center py-12 text-[var(--color-text-secondary)]">Loading calendar data...</div>
          ) : calendar.length > 0 ? (
            <div className="grid grid-cols-3 md:grid-cols-4 gap-3">
              {calendar.map((m) => (
                <div
                  key={m.month}
                  className="bg-[var(--color-bg-card)] rounded-xl p-4 border border-[var(--color-border)]"
                >
                  <h3 className="font-medium text-sm mb-2">{m.month}</h3>
                  <div className="text-xs text-[var(--color-text-secondary)] mb-3 space-y-0.5">
                    <p>Avg temp: {displayTemp(m.avg_temp_f)}</p>
                    <p>Avg RH: {m.avg_humidity}%</p>
                  </div>
                  <div className="space-y-1">
                    {m.top_species.map((sp, i) => (
                      <div key={i} className="flex items-center justify-between text-xs">
                        <span className="truncate mr-2">{sp.common_name}</span>
                        <span className="flex items-center gap-0.5 text-amber-400 shrink-0">
                          <Star size={10} fill="currentColor" />
                          {sp.score}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="bg-[var(--color-bg-card)] rounded-xl p-12 border border-[var(--color-border)] text-center">
              <Calendar size={48} className="mx-auto mb-4 text-[var(--color-text-secondary)]" />
              <p className="text-[var(--color-text-secondary)]">No calendar data available.</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
