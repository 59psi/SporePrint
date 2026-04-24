import { useEffect, useState } from 'react'
import { AlertTriangle, BookOpen, ChevronDown, ChevronUp } from 'lucide-react'
import { api } from '../api/client'
import { CATEGORY_BADGE_COLORS } from '../constants/colors'
import { reportFetchError } from '../stores/toastStore'

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

interface TekStep {
  step_number: number
  title: string
  description: string
  duration: string
  tips: string[]
  common_mistakes: string[]
}

interface SubstrateRecipe {
  name: string
  ingredients: Record<string, string>
  water_liters_per_liter_substrate: number
  spawn_rate_percent: number
  sterilization_method: string
  sterilization_time_min: number
  sterilization_temp_f: number | null
  suitability: string
  notes: string
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
  tldr: string
  flavor_profile: string
  edible: boolean
  safety_warning: string
  legal_disclaimer: string
  tek_guide: TekStep[]
  substrate_recipes: SubstrateRecipe[]
  substrate_preference_ranking: string[]
  contamination_risks: string[]
  photo_references: Record<string, string>
  regional_notes: string
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
    api.get<Profile[]>('/species').then(setProfiles).catch((err) =>
      reportFetchError('Species/list', err, "Couldn't load species library")
    )
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

      <div className="flex gap-2 mb-4">
        {['all', 'gourmet', 'medicinal', 'active', 'novelty'].map((cat) => (
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
                  {/* Legal disclaimer (active species) */}
                  {profile.legal_disclaimer && (
                    <div className="mt-3 p-3 rounded-lg bg-red-500/10 border border-red-500/30">
                      <p className="text-xs text-red-400 font-medium">{profile.legal_disclaimer}</p>
                    </div>
                  )}

                  {/* Not edible warning */}
                  {!profile.edible && (
                    <div className="mt-3 p-3 rounded-lg bg-red-500/10 border border-red-500/30">
                      <div className="flex items-center gap-2">
                        <AlertTriangle size={16} className="text-red-400" />
                        <p className="text-xs text-red-400 font-bold">NOT EDIBLE — {profile.safety_warning}</p>
                      </div>
                    </div>
                  )}

                  {/* Safety warning for edible species */}
                  {profile.edible && profile.safety_warning && (
                    <div className="mt-3 p-3 rounded-lg bg-amber-500/10 border border-amber-500/30">
                      <p className="text-xs text-amber-400">{profile.safety_warning}</p>
                    </div>
                  )}

                  {/* TLDR */}
                  {profile.tldr && (
                    <p className="text-sm mt-3 text-[var(--color-text-secondary)]">{profile.tldr}</p>
                  )}

                  {/* Flavor profile */}
                  {profile.flavor_profile && (
                    <p className="text-xs mt-1 italic text-[var(--color-text-secondary)]">{profile.flavor_profile}</p>
                  )}

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

                  <div className="mb-3">
                    <p className="text-xs text-[var(--color-text-secondary)] mb-1">Substrates</p>
                    <p className="text-sm">{profile.substrate_types.join(', ')}</p>
                  </div>

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

                  {profile.tek_guide?.length > 0 && (
                    <details className="mt-4">
                      <summary className="text-sm font-medium cursor-pointer hover:text-emerald-400">
                        Growing Guide ({profile.tek_guide.length} steps)
                      </summary>
                      <div className="mt-2 space-y-3">
                        {profile.tek_guide.map((step) => (
                          <div key={step.step_number} className="p-3 bg-[var(--color-bg-primary)] rounded-lg">
                            <p className="text-sm font-medium">
                              {step.step_number}. {step.title}
                              <span className="text-xs text-[var(--color-text-secondary)] ml-2">({step.duration})</span>
                            </p>
                            <p className="text-xs mt-1">{step.description}</p>
                            {step.tips.length > 0 && (
                              <div className="mt-2">
                                {step.tips.map((tip, i) => (
                                  <p key={i} className="text-xs text-emerald-400">{'\u2713'} {tip}</p>
                                ))}
                              </div>
                            )}
                            {step.common_mistakes.length > 0 && (
                              <div className="mt-1">
                                {step.common_mistakes.map((m, i) => (
                                  <p key={i} className="text-xs text-red-400">{'\u2717'} {m}</p>
                                ))}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </details>
                  )}

                  {profile.substrate_recipes?.length > 0 && (
                    <details className="mt-3">
                      <summary className="text-sm font-medium cursor-pointer hover:text-emerald-400">
                        Substrate Recipes ({profile.substrate_recipes.length})
                      </summary>
                      <div className="mt-2 space-y-2">
                        {profile.substrate_recipes.map((recipe, i) => (
                          <div key={i} className="p-3 bg-[var(--color-bg-primary)] rounded-lg">
                            <div className="flex justify-between items-center mb-1">
                              <p className="text-sm font-medium">{recipe.name}</p>
                              <span className={`text-xs px-2 py-0.5 rounded ${
                                recipe.suitability === 'optimal' ? 'bg-emerald-500/10 text-emerald-400' :
                                recipe.suitability === 'good' ? 'bg-blue-500/10 text-blue-400' :
                                'bg-amber-500/10 text-amber-400'
                              }`}>{recipe.suitability}</span>
                            </div>
                            <div className="text-xs space-y-0.5">
                              {Object.entries(recipe.ingredients).map(([name, amount]) => (
                                <p key={name}>{name}: {amount}</p>
                              ))}
                            </div>
                            <p className="text-xs text-[var(--color-text-secondary)] mt-1">
                              Spawn rate: {recipe.spawn_rate_percent}% · {recipe.sterilization_method.replace(/_/g, ' ')} · {recipe.sterilization_time_min}min
                              {recipe.sterilization_temp_f && ` at ${recipe.sterilization_temp_f}\u00b0F`}
                            </p>
                            {recipe.notes && <p className="text-xs text-[var(--color-text-secondary)] mt-1 italic">{recipe.notes}</p>}
                          </div>
                        ))}
                      </div>
                    </details>
                  )}

                  {profile.photo_references && Object.keys(profile.photo_references).length > 0 && (
                    <details className="mt-3">
                      <summary className="text-sm font-medium cursor-pointer hover:text-emerald-400">
                        Reference Photos
                      </summary>
                      <div className="mt-2 grid grid-cols-2 md:grid-cols-3 gap-3">
                        {Object.entries(profile.photo_references).map(([phase, ref]) => {
                          // Convert Wikimedia wiki page URL to thumbnail
                          let imgUrl: string | null = null
                          if (ref.includes('commons.wikimedia.org/wiki/File:')) {
                            const filename = ref.split('File:')[1]
                            if (filename) {
                              imgUrl = `https://commons.wikimedia.org/w/thumb.php?f=${encodeURIComponent(filename)}&w=300`
                            }
                          } else if (ref.startsWith('http') && /\.(jpg|jpeg|png|webp)$/i.test(ref)) {
                            imgUrl = ref
                          }

                          return (
                            <div key={phase} className="rounded-lg overflow-hidden bg-[var(--color-bg-primary)]">
                              {imgUrl ? (
                                <a href={ref} target="_blank" rel="noopener noreferrer">
                                  <img src={imgUrl} alt={`${phase} phase`}
                                       className="w-full h-32 object-cover"
                                       loading="lazy"
                                       onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
                                </a>
                              ) : (
                                <div className="h-32 flex items-center justify-center text-xs text-[var(--color-text-secondary)] p-2 text-center">
                                  {ref}
                                </div>
                              )}
                              <p className="text-xs text-center py-1 text-[var(--color-text-secondary)] capitalize">{phase.replace(/_/g, ' ')}</p>
                            </div>
                          )
                        })}
                      </div>
                    </details>
                  )}

                  {profile.contamination_risks?.length > 0 && (
                    <div className="mt-3">
                      <p className="text-xs text-[var(--color-text-secondary)] mb-1">Species-Specific Risks</p>
                      {profile.contamination_risks.map((risk, i) => (
                        <p key={i} className="text-xs text-amber-400">{'\u26a0'} {risk}</p>
                      ))}
                    </div>
                  )}
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
