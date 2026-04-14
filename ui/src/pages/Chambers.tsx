import { useEffect, useState } from 'react'
import { Box, Plus, Trash2 } from 'lucide-react'
import { api } from '../api/client'

interface Chamber {
  id: number
  name: string
  description: string | null
  node_count: number
  active_session_id: number | null
  rule_count: number
  created_at: string
}

export default function Chambers() {
  const [chambers, setChambers] = useState<Chamber[]>([])
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  useEffect(() => {
    api.get<Chamber[]>('/chambers').then(setChambers).catch(() => {})
  }, [])

  const handleCreate = async () => {
    if (!name.trim()) return
    try {
      const created = await api.post<Chamber>('/chambers', {
        name: name.trim(),
        description: description.trim() || null,
      })
      setChambers([...chambers, created])
      setName('')
      setDescription('')
      setShowForm(false)
    } catch {
      // ignore
    }
  }

  const handleDelete = async (id: number) => {
    try {
      await api.delete(`/chambers/${id}`)
      setChambers(chambers.filter((c) => c.id !== id))
    } catch {
      // ignore
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold">Chambers</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">Manage grow chambers</p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--color-accent-gourmet)] text-white text-sm font-medium hover:opacity-90 transition-opacity"
        >
          <Plus size={16} />
          New Chamber
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <div className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)] mb-6">
          <h3 className="font-medium text-sm mb-3">New Chamber</h3>
          <div className="space-y-3">
            <div>
              <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Name</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Main Closet"
                className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
              />
            </div>
            <div>
              <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Description (optional)</label>
              <input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="e.g. 4x2x6 closet, top shelf fruiting"
                className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
              />
            </div>
            <button
              onClick={handleCreate}
              disabled={!name.trim()}
              className="px-4 py-2 rounded-lg bg-[var(--color-accent-gourmet)] text-white text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              Create Chamber
            </button>
          </div>
        </div>
      )}

      {/* Chamber grid */}
      {chambers.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {chambers.map((c) => (
            <div
              key={c.id}
              className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)]"
            >
              <div className="flex items-start justify-between mb-3">
                <div>
                  <h3 className="font-medium">{c.name}</h3>
                  {c.description && (
                    <p className="text-xs text-[var(--color-text-secondary)] mt-0.5">{c.description}</p>
                  )}
                </div>
                <button
                  onClick={() => handleDelete(c.id)}
                  className="p-1.5 rounded-lg hover:bg-[var(--color-bg-hover)] text-[var(--color-text-secondary)] hover:text-red-400 transition-colors"
                >
                  <Trash2 size={14} />
                </button>
              </div>
              <div className="space-y-1.5 text-xs text-[var(--color-text-secondary)]">
                <div className="flex justify-between">
                  <span>Nodes</span>
                  <span className="font-medium text-[var(--color-text-primary)]">{c.node_count}</span>
                </div>
                <div className="flex justify-between">
                  <span>Active Session</span>
                  <span className="font-medium text-[var(--color-text-primary)]">
                    {c.active_session_id ? `#${c.active_session_id}` : 'None'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>Rules</span>
                  <span className="font-medium text-[var(--color-text-primary)]">{c.rule_count}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="bg-[var(--color-bg-card)] rounded-xl p-12 border border-[var(--color-border)] text-center">
          <Box size={48} className="mx-auto mb-4 text-[var(--color-text-secondary)]" />
          <p className="text-[var(--color-text-secondary)]">No chambers configured. Create one to organize your grow spaces.</p>
        </div>
      )}
    </div>
  )
}
