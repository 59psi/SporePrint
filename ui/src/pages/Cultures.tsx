import { useEffect, useState } from 'react'
import { GitBranch, Plus, X, ChevronRight } from 'lucide-react'
import { api } from '../api/client'
import { reportFetchError } from '../stores/toastStore'

interface Culture {
  id: number
  type: string
  species_profile_id: string
  source: string
  parent_id: number | null
  vendor_name: string | null
  storage_location: string | null
  generation: number
  status: string
  created_at: string
}

interface LineageNode {
  id: number
  type: string
  species_profile_id: string
  generation: number
  status: string
  contamination_rate: number | null
  children: LineageNode[]
}

const CULTURE_TYPES = [
  'spore_syringe',
  'spore_print',
  'agar_plate',
  'liquid_culture',
  'grain_spawn',
  'slant',
  'clone',
]

const SOURCES = ['vendor', 'clone', 'spore_isolation', 'transfer', 'gift']

const STATUS_COLORS: Record<string, string> = {
  active: 'text-green-400',
  stored: 'text-blue-400',
  contaminated: 'text-red-400',
  exhausted: 'text-[var(--color-text-secondary)]',
}

export default function Cultures() {
  const [cultures, setCultures] = useState<Culture[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [lineage, setLineage] = useState<LineageNode | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({
    type: 'agar_plate',
    species_profile_id: '',
    source: 'vendor',
    parent_id: '',
    vendor_name: '',
    storage_location: '',
  })

  useEffect(() => {
    api.get<Culture[]>('/cultures').then(setCultures).catch((err) =>
      reportFetchError('Cultures/list', err, "Couldn't load cultures")
    )
  }, [])

  useEffect(() => {
    if (selectedId) {
      api.get<LineageNode>(`/cultures/${selectedId}/lineage`).then(setLineage).catch(() => setLineage(null))
    } else {
      setLineage(null)
    }
  }, [selectedId])

  const handleCreate = async () => {
    try {
      const body: Record<string, unknown> = {
        type: form.type,
        species_profile_id: form.species_profile_id,
        source: form.source,
      }
      if (form.parent_id) body.parent_id = Number(form.parent_id)
      if (form.vendor_name) body.vendor_name = form.vendor_name
      if (form.storage_location) body.storage_location = form.storage_location

      const created = await api.post<Culture>('/cultures', body)
      setCultures([created, ...cultures])
      setShowForm(false)
      setForm({ type: 'agar_plate', species_profile_id: '', source: 'vendor', parent_id: '', vendor_name: '', storage_location: '' })
    } catch {
      // ignore
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold">Cultures</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">Culture library and lineage tracking</p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--color-accent-gourmet)] text-white text-sm font-medium hover:opacity-90 transition-opacity"
        >
          {showForm ? <X size={16} /> : <Plus size={16} />}
          {showForm ? 'Cancel' : 'New Culture'}
        </button>
      </div>

      <div className="flex gap-6">
        {/* Left: culture list */}
        <div className="flex-1 min-w-0">
          {/* New culture form */}
          {showForm && (
            <div className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)] mb-4">
              <h3 className="font-medium text-sm mb-3">New Culture</h3>
              <div className="space-y-3">
                <div>
                  <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Type</label>
                  <select
                    value={form.type}
                    onChange={(e) => setForm({ ...form, type: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
                  >
                    {CULTURE_TYPES.map((t) => (
                      <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Species Profile ID</label>
                  <input
                    value={form.species_profile_id}
                    onChange={(e) => setForm({ ...form, species_profile_id: e.target.value })}
                    placeholder="e.g. blue_oyster"
                    className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
                  />
                </div>
                <div>
                  <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Source</label>
                  <select
                    value={form.source}
                    onChange={(e) => setForm({ ...form, source: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
                  >
                    {SOURCES.map((s) => (
                      <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Parent Culture ID (optional)</label>
                  <input
                    value={form.parent_id}
                    onChange={(e) => setForm({ ...form, parent_id: e.target.value })}
                    placeholder="Parent culture ID"
                    className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
                  />
                </div>
                <div>
                  <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Vendor Name (optional)</label>
                  <input
                    value={form.vendor_name}
                    onChange={(e) => setForm({ ...form, vendor_name: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
                  />
                </div>
                <div>
                  <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Storage Location (optional)</label>
                  <input
                    value={form.storage_location}
                    onChange={(e) => setForm({ ...form, storage_location: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
                  />
                </div>
                <button
                  onClick={handleCreate}
                  disabled={!form.species_profile_id}
                  className="px-4 py-2 rounded-lg bg-[var(--color-accent-gourmet)] text-white text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
                >
                  Create Culture
                </button>
              </div>
            </div>
          )}

          {/* Culture cards */}
          {cultures.length > 0 ? (
            <div className="space-y-2">
              {cultures.map((c) => (
                <button
                  key={c.id}
                  onClick={() => setSelectedId(c.id)}
                  className={`w-full flex items-center justify-between p-4 rounded-xl border transition-colors text-left ${
                    selectedId === c.id
                      ? 'bg-[var(--color-bg-card)] border-[var(--color-accent-gourmet)]'
                      : 'bg-[var(--color-bg-card)] border-[var(--color-border)] hover:border-[var(--color-bg-hover)]'
                  }`}
                >
                  <div className="min-w-0">
                    <p className="font-medium text-sm truncate">
                      {c.species_profile_id.replace(/_/g, ' ')}
                    </p>
                    <p className="text-xs text-[var(--color-text-secondary)]">
                      {c.type.replace(/_/g, ' ')} · Gen {c.generation} ·{' '}
                      <span className={STATUS_COLORS[c.status] || ''}>{c.status}</span>
                    </p>
                  </div>
                  <ChevronRight size={16} className="text-[var(--color-text-secondary)] shrink-0" />
                </button>
              ))}
            </div>
          ) : (
            <div className="bg-[var(--color-bg-card)] rounded-xl p-12 border border-[var(--color-border)] text-center">
              <GitBranch size={48} className="mx-auto mb-4 text-[var(--color-text-secondary)]" />
              <p className="text-[var(--color-text-secondary)]">No cultures yet. Add your first culture to get started.</p>
            </div>
          )}
        </div>

        {/* Right: lineage tree */}
        <div className="w-80 shrink-0 hidden lg:block">
          <div className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)] sticky top-4">
            <h3 className="font-medium text-sm mb-3 flex items-center gap-2">
              <GitBranch size={14} />
              Lineage Tree
            </h3>
            {lineage ? (
              <LineageTree node={lineage} depth={0} />
            ) : (
              <p className="text-xs text-[var(--color-text-secondary)]">
                Select a culture to view its lineage tree.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function LineageTree({ node, depth }: { node: LineageNode; depth: number }) {
  return (
    <div style={{ paddingLeft: depth * 16 }}>
      <div className="flex items-center gap-2 py-1">
        {depth > 0 && <span className="text-[var(--color-text-secondary)]">|--</span>}
        <div className="text-xs">
          <span className="font-medium">{node.type.replace(/_/g, ' ')}</span>
          <span className="text-[var(--color-text-secondary)]"> · Gen {node.generation}</span>
          <span className={`ml-1 ${STATUS_COLORS[node.status] || ''}`}>{node.status}</span>
          {node.contamination_rate != null && (
            <span className="text-[var(--color-text-secondary)]"> · {Math.round(node.contamination_rate * 100)}% contam</span>
          )}
        </div>
      </div>
      {node.children.map((child) => (
        <LineageTree key={child.id} node={child} depth={depth + 1} />
      ))}
    </div>
  )
}
