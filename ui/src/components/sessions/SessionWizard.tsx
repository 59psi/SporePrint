import { useState, useEffect } from 'react'
import { ArrowLeft, ArrowRight, Box, Sprout } from 'lucide-react'
import { api } from '../../api/client'
import { CATEGORY_COLORS } from '../../constants/colors'
import type { Session } from '../../stores/sessionStore'

interface SpeciesProfile {
  id: string
  common_name: string
  scientific_name: string
  category: string
  substrate_types: string[]
}

interface Chamber {
  id: number
  name: string
  description: string | null
  node_count: number
  active_session_id: number | null
}

interface Props {
  onCreated: (session: Session) => void
  onCancel: () => void
}

export default function SessionWizard({ onCreated, onCancel }: Props) {
  const [step, setStep] = useState(0)
  const [profiles, setProfiles] = useState<SpeciesProfile[]>([])
  const [chambers, setChambers] = useState<Chamber[]>([])
  const [form, setForm] = useState({
    name: '',
    species_profile_id: '',
    substrate: '',
    substrate_volume: '',
    substrate_prep_notes: '',
    inoculation_date: new Date().toISOString().split('T')[0],
    inoculation_method: '',
    spawn_source: '',
    current_phase: 'substrate_colonization',
    tub_number: '',
    shelf_number: '',
    shelf_side: '',
    growth_form: '',
    pinning_tek: '',
    chamber_id: null as number | null,
  })

  useEffect(() => {
    api.get<SpeciesProfile[]>('/species').then(setProfiles).catch(() => {})
    api.get<Chamber[]>('/chambers').then(setChambers).catch(() => {})
  }, [])

  const selectedProfile = profiles.find((p) => p.id === form.species_profile_id)
  const categoryColors = CATEGORY_COLORS

  const handleSubmit = async () => {
    try {
      const session = await api.post<Session>('/sessions', form)
      onCreated(session)
    } catch (e) {
      console.error('Failed to create session', e)
    }
  }

  const steps = ['Species', 'Substrate', 'Chamber', 'Details']

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <button onClick={onCancel} className="p-2 rounded-lg hover:bg-[var(--color-bg-hover)]">
          <ArrowLeft size={18} />
        </button>
        <div>
          <h1 className="text-2xl font-semibold">New Session</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">Step {step + 1} of {steps.length}: {steps[step]}</p>
        </div>
      </div>

      {/* Progress */}
      <div className="flex gap-2 mb-6">
        {steps.map((_, i) => (
          <div
            key={i}
            className={`h-1 flex-1 rounded-full ${i <= step ? 'bg-[var(--color-accent-gourmet)]' : 'bg-[var(--color-border)]'}`}
          />
        ))}
      </div>

      {step === 0 && (
        <div>
          <label className="block text-sm text-[var(--color-text-secondary)] mb-2">Session Name</label>
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="e.g. Blue Oyster Block #1"
            className="w-full p-3 rounded-lg bg-[var(--color-bg-primary)] border border-[var(--color-border)] text-sm mb-4 focus:outline-none focus:border-[var(--color-accent-gourmet)]"
          />

          <label className="block text-sm text-[var(--color-text-secondary)] mb-2">Species</label>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {profiles.map((p) => (
              <button
                key={p.id}
                onClick={() => setForm({ ...form, species_profile_id: p.id })}
                className={`text-left p-3 rounded-lg border transition-all ${
                  form.species_profile_id === p.id
                    ? 'border-[var(--color-accent-gourmet)] bg-[var(--color-accent-gourmet)]/5'
                    : 'border-[var(--color-border)] hover:border-[var(--color-bg-hover)]'
                }`}
              >
                <p className="text-sm font-medium">{p.common_name}</p>
                <p className="text-xs text-[var(--color-text-secondary)]">
                  <span style={{ color: categoryColors[p.category] }}>{p.category}</span>
                  {' · '}{p.scientific_name}
                </p>
              </button>
            ))}
          </div>
        </div>
      )}

      {step === 1 && (
        <div className="space-y-4">
          <div>
            <label className="block text-sm text-[var(--color-text-secondary)] mb-2">Substrate Type</label>
            <div className="flex flex-wrap gap-2">
              {(selectedProfile?.substrate_types || ['CVG', 'straw', 'hardwood sawdust', 'masters mix', 'BRF', 'brown rice']).map((s) => (
                <button
                  key={s}
                  onClick={() => setForm({ ...form, substrate: s })}
                  className={`px-3 py-1.5 rounded-lg text-sm border ${
                    form.substrate === s
                      ? 'border-[var(--color-accent-gourmet)] bg-[var(--color-accent-gourmet)]/10'
                      : 'border-[var(--color-border)]'
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm text-[var(--color-text-secondary)] mb-2">Volume</label>
            <input
              value={form.substrate_volume}
              onChange={(e) => setForm({ ...form, substrate_volume: e.target.value })}
              placeholder="e.g. 6qt, 54qt monotub"
              className="w-full p-3 rounded-lg bg-[var(--color-bg-primary)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
            />
          </div>

          <div>
            <label className="block text-sm text-[var(--color-text-secondary)] mb-2">Prep Notes</label>
            <textarea
              value={form.substrate_prep_notes}
              onChange={(e) => setForm({ ...form, substrate_prep_notes: e.target.value })}
              placeholder="Pasteurization method, additives, etc."
              rows={3}
              className="w-full p-3 rounded-lg bg-[var(--color-bg-primary)] border border-[var(--color-border)] text-sm resize-none focus:outline-none focus:border-[var(--color-accent-gourmet)]"
            />
          </div>

          {/* Location */}
          <div>
            <label className="block text-sm text-[var(--color-text-secondary)] mb-2">Location</label>
            <div className="grid grid-cols-3 gap-2">
              <input
                value={form.tub_number}
                onChange={(e) => setForm({ ...form, tub_number: e.target.value })}
                placeholder="Tub #"
                className="p-3 rounded-lg bg-[var(--color-bg-primary)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
              />
              <input
                type="number"
                value={form.shelf_number}
                onChange={(e) => setForm({ ...form, shelf_number: e.target.value })}
                placeholder="Shelf #"
                className="p-3 rounded-lg bg-[var(--color-bg-primary)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
              />
              <div className="flex gap-1">
                {['left', 'right'].map((side) => (
                  <button
                    key={side}
                    onClick={() => setForm({ ...form, shelf_side: side })}
                    className={`flex-1 px-3 py-3 rounded-lg text-sm border capitalize ${
                      form.shelf_side === side
                        ? 'border-[var(--color-accent-gourmet)] bg-[var(--color-accent-gourmet)]/10'
                        : 'border-[var(--color-border)]'
                    }`}
                  >
                    {side}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {step === 2 && (
        <div>
          <label className="block text-sm text-[var(--color-text-secondary)] mb-2">Assign to Chamber</label>
          <p className="text-xs text-[var(--color-text-secondary)] mb-4">
            Optionally assign this session to a chamber for automated environment control.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <button
              onClick={() => setForm({ ...form, chamber_id: null })}
              className={`text-left p-3 rounded-lg border transition-all ${
                form.chamber_id === null
                  ? 'border-[var(--color-accent-gourmet)] bg-[var(--color-accent-gourmet)]/5'
                  : 'border-[var(--color-border)] hover:border-[var(--color-bg-hover)]'
              }`}
            >
              <p className="text-sm font-medium">No Chamber</p>
              <p className="text-xs text-[var(--color-text-secondary)]">Skip chamber assignment</p>
            </button>
            {chambers.map((c) => (
              <button
                key={c.id}
                onClick={() => setForm({ ...form, chamber_id: c.id })}
                className={`text-left p-3 rounded-lg border transition-all ${
                  form.chamber_id === c.id
                    ? 'border-[var(--color-accent-gourmet)] bg-[var(--color-accent-gourmet)]/5'
                    : 'border-[var(--color-border)] hover:border-[var(--color-bg-hover)]'
                }`}
              >
                <div className="flex items-center gap-2">
                  <Box size={14} className="text-[var(--color-text-secondary)]" />
                  <p className="text-sm font-medium">{c.name}</p>
                </div>
                <p className="text-xs text-[var(--color-text-secondary)] mt-0.5">
                  {c.node_count} node{c.node_count !== 1 ? 's' : ''}
                  {c.description ? ` · ${c.description}` : ''}
                </p>
                {c.active_session_id && (
                  <p className="text-xs text-amber-400 mt-1">Active session #{c.active_session_id}</p>
                )}
              </button>
            ))}
          </div>
          {chambers.length === 0 && (
            <p className="text-xs text-[var(--color-text-secondary)] mt-3">
              No chambers configured yet. You can create chambers from the Chambers page.
            </p>
          )}
        </div>
      )}

      {step === 3 && (
        <div className="space-y-4">
          <div>
            <label className="block text-sm text-[var(--color-text-secondary)] mb-2">Inoculation Date</label>
            <input
              type="date"
              value={form.inoculation_date}
              onChange={(e) => setForm({ ...form, inoculation_date: e.target.value })}
              className="w-full p-3 rounded-lg bg-[var(--color-bg-primary)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
            />
          </div>

          <div>
            <label className="block text-sm text-[var(--color-text-secondary)] mb-2">Inoculation Method</label>
            <div className="flex flex-wrap gap-2">
              {['grain spawn', 'liquid culture', 'agar wedge', 'spore syringe'].map((m) => (
                <button
                  key={m}
                  onClick={() => setForm({ ...form, inoculation_method: m })}
                  className={`px-3 py-1.5 rounded-lg text-sm border ${
                    form.inoculation_method === m
                      ? 'border-[var(--color-accent-gourmet)] bg-[var(--color-accent-gourmet)]/10'
                      : 'border-[var(--color-border)]'
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm text-[var(--color-text-secondary)] mb-2">Spawn Source</label>
            <input
              value={form.spawn_source}
              onChange={(e) => setForm({ ...form, spawn_source: e.target.value })}
              placeholder="e.g. LC from agar isolation #3"
              className="w-full p-3 rounded-lg bg-[var(--color-bg-primary)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
            />
          </div>

          <div>
            <label className="block text-sm text-[var(--color-text-secondary)] mb-2">Starting Phase</label>
            <select
              value={form.current_phase}
              onChange={(e) => setForm({ ...form, current_phase: e.target.value })}
              className="w-full p-3 rounded-lg bg-[var(--color-bg-primary)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
            >
              <option value="agar">Agar</option>
              <option value="liquid_culture">Liquid Culture</option>
              <option value="grain_colonization">Grain Colonization</option>
              <option value="substrate_colonization">Substrate Colonization</option>
            </select>
          </div>

          {form.species_profile_id === 'reishi' && (
            <div>
              <label className="block text-sm text-[var(--color-text-secondary)] mb-2">Growth Form</label>
              <div className="flex gap-2">
                {['antler', 'conk'].map((f) => (
                  <button
                    key={f}
                    onClick={() => setForm({ ...form, growth_form: f })}
                    className={`px-4 py-2 rounded-lg text-sm border capitalize ${
                      form.growth_form === f
                        ? 'border-[var(--color-accent-medicinal)] bg-[var(--color-accent-medicinal)]/10'
                        : 'border-[var(--color-border)]'
                    }`}
                  >
                    {f}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Navigation */}
      <div className="flex justify-between mt-8">
        <button
          onClick={() => step > 0 ? setStep(step - 1) : onCancel()}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]"
        >
          <ArrowLeft size={14} />
          {step > 0 ? 'Back' : 'Cancel'}
        </button>

        {step < steps.length - 1 ? (
          <button
            onClick={() => setStep(step + 1)}
            disabled={step === 0 && (!form.name || !form.species_profile_id)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--color-accent-gourmet)] text-white text-sm font-medium disabled:opacity-40"
          >
            Next
            <ArrowRight size={14} />
          </button>
        ) : (
          <button
            onClick={handleSubmit}
            disabled={!form.name || !form.species_profile_id}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--color-accent-gourmet)] text-white text-sm font-medium disabled:opacity-40"
          >
            <Sprout size={14} />
            Create Session
          </button>
        )}
      </div>
    </div>
  )
}
