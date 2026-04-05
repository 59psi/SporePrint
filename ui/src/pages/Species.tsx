import { useEffect, useState } from 'react'
import { BookOpen, ChevronDown, ChevronUp } from 'lucide-react'
import { api } from '../api/client'
import { CATEGORY_BADGE_COLORS } from '../constants/colors'

interface PhaseParams {
  temp_min_f: number
  temp_max_f: number
  humidity_min: number
  humidity_max: number
  co2_max_ppm: number
  light_hours_on: number
  light_hours_off: number
  light_spectrum: string
  fae_mode: string
  expected_duration_days: [number, number]
  notes: string
  temp_swing_required?: boolean
  temp_swing_delta_f?: number
}

interface Profile {
  id: string
  common_name: string
  scientific_name: string
  category: string
  strain: string | null
  substrate_types: string[]
  colonization_visual_description: string
  contamination_risk_notes: string
  pinning_trigger_description: string
  phases: Record<string, PhaseParams>
  flush_count_typical: number
  yield_notes: string
  tags: string[]
}

const categoryColors = CATEGORY_BADGE_COLORS

const phaseLabels: Record<string, string> = {
  agar: 'Agar',
  liquid_culture: 'Liquid Culture',
  grain_colonization: 'Grain Colonization',
  substrate_colonization: 'Substrate Colonization',
  primordia_induction: 'Primordia Induction',
  fruiting: 'Fruiting',
  rest: 'Rest',
}

export default function Species() {
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [filter, setFilter] = useState<string>('all')

  useEffect(() => {
    api.get<Profile[]>('/species').then(setProfiles).catch(() => {})
  }, [])

  const filtered = filter === 'all' ? profiles : profiles.filter((p) => p.category === filter)

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold">Species Profiles</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">
            {profiles.length} cultivation profiles
          </p>
        </div>
      </div>

      {/* Category filter */}
      <div className="flex gap-2 mb-4">
        {['all', 'gourmet', 'medicinal', 'active'].map((cat) => (
          <button
            key={cat}
            onClick={() => setFilter(cat)}
            className={`px-3 py-1.5 rounded-lg text-sm capitalize ${
              filter === cat
                ? 'bg-[var(--color-bg-card)] text-[var(--color-text-primary)] border border-[var(--color-accent-gourmet)]/30'
                : 'text-[var(--color-text-secondary)] border border-[var(--color-border)]'
            }`}
          >
            {cat}
          </button>
        ))}
      </div>

      <div className="space-y-3">
        {filtered.map((profile) => {
          const colors = categoryColors[profile.category] || categoryColors.gourmet
          const expanded = expandedId === profile.id

          return (
            <div
              key={profile.id}
              className="bg-[var(--color-bg-card)] rounded-xl border border-[var(--color-border)] overflow-hidden"
            >
              <button
                onClick={() => setExpandedId(expanded ? null : profile.id)}
                className="w-full flex items-center gap-4 p-4 text-left"
              >
                <div className={`px-2 py-1 rounded text-xs font-medium ${colors.bg} ${colors.text}`}>
                  {profile.category}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium">{profile.common_name}</p>
                  <p className="text-sm text-[var(--color-text-secondary)] italic">{profile.scientific_name}</p>
                </div>
                <div className="flex items-center gap-2 text-xs text-[var(--color-text-secondary)]">
                  <span>{profile.flush_count_typical} flushes</span>
                  {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                </div>
              </button>

              {expanded && (
                <div className="px-4 pb-4 border-t border-[var(--color-border)]">
                  {/* Tags */}
                  <div className="flex flex-wrap gap-1 mt-3 mb-4">
                    {profile.tags.map((tag) => (
                      <span
                        key={tag}
                        className="px-2 py-0.5 rounded text-xs bg-[var(--color-bg-hover)] text-[var(--color-text-secondary)]"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>

                  {/* Substrates */}
                  <div className="mb-3">
                    <p className="text-xs text-[var(--color-text-secondary)] mb-1">Substrates</p>
                    <p className="text-sm">{profile.substrate_types.join(', ')}</p>
                  </div>

                  {/* Key info */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
                    <div className="p-3 bg-[var(--color-bg-primary)] rounded-lg">
                      <p className="text-xs text-[var(--color-text-secondary)] mb-1">Colonization</p>
                      <p className="text-xs">{profile.colonization_visual_description}</p>
                    </div>
                    <div className="p-3 bg-[var(--color-bg-primary)] rounded-lg">
                      <p className="text-xs text-[var(--color-text-secondary)] mb-1">Pinning Trigger</p>
                      <p className="text-xs">{profile.pinning_trigger_description}</p>
                    </div>
                    <div className="p-3 bg-[var(--color-bg-primary)] rounded-lg">
                      <p className="text-xs text-[var(--color-text-secondary)] mb-1">Contamination</p>
                      <p className="text-xs">{profile.contamination_risk_notes}</p>
                    </div>
                  </div>

                  {/* Phase table */}
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-left text-[var(--color-text-secondary)] border-b border-[var(--color-border)]">
                          <th className="py-2 pr-3">Phase</th>
                          <th className="py-2 pr-3">Temp °F</th>
                          <th className="py-2 pr-3">RH %</th>
                          <th className="py-2 pr-3">CO2 ppm</th>
                          <th className="py-2 pr-3">Light</th>
                          <th className="py-2 pr-3">FAE</th>
                          <th className="py-2">Duration</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(profile.phases).map(([phase, params]) => (
                          <tr key={phase} className="border-b border-[var(--color-border)]/50">
                            <td className="py-2 pr-3 font-medium">{phaseLabels[phase] || phase}</td>
                            <td className="py-2 pr-3">
                              {params.temp_min_f}–{params.temp_max_f}
                              {params.temp_swing_required && (
                                <span className="text-amber-400 ml-1">±{params.temp_swing_delta_f}°</span>
                              )}
                            </td>
                            <td className="py-2 pr-3">{params.humidity_min}–{params.humidity_max}</td>
                            <td className="py-2 pr-3">&lt;{params.co2_max_ppm}</td>
                            <td className="py-2 pr-3">
                              {params.light_hours_on}/{params.light_hours_off} {params.light_spectrum.replace('_', ' ')}
                            </td>
                            <td className="py-2 pr-3">{params.fae_mode}</td>
                            <td className="py-2">{params.expected_duration_days[0]}–{params.expected_duration_days[1]}d</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <p className="text-xs text-[var(--color-text-secondary)] mt-3">{profile.yield_notes}</p>
                </div>
              )}
            </div>
          )
        })}

        {filtered.length === 0 && (
          <div className="bg-[var(--color-bg-card)] rounded-xl p-8 border border-[var(--color-border)] text-center">
            <BookOpen size={32} className="mx-auto mb-3 text-[var(--color-text-secondary)]" />
            <p className="text-sm text-[var(--color-text-secondary)]">No profiles found. Start the backend to load built-in profiles.</p>
          </div>
        )}
      </div>
    </div>
  )
}
