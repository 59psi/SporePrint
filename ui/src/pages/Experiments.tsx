import { useEffect, useState } from 'react'
import { FlaskConical, Plus, X, BarChart3, ArrowUpRight, ArrowDownRight, Minus } from 'lucide-react'
import { api } from '../api/client'
import { reportFetchError } from '../stores/toastStore'

interface Experiment {
  id: number
  title: string
  hypothesis: string
  control_session_id: number
  variant_session_id: number
  independent_variable: string
  control_value: string
  variant_value: string
  status: 'active' | 'completed' | 'cancelled'
  created_at: string
}

interface ComparisonMetric {
  metric: string
  control_value: number
  variant_value: number
  pct_difference: number
  winner: 'control' | 'variant' | 'tie'
}

const STATUS_BADGE: Record<string, string> = {
  active: 'bg-green-500/10 text-green-400',
  completed: 'bg-blue-500/10 text-blue-400',
  cancelled: 'bg-neutral-500/10 text-[var(--color-text-secondary)]',
}

export default function Experiments() {
  const [experiments, setExperiments] = useState<Experiment[]>([])
  const [showForm, setShowForm] = useState(false)
  const [comparison, setComparison] = useState<{ id: number; metrics: ComparisonMetric[] } | null>(null)
  const [form, setForm] = useState({
    title: '',
    hypothesis: '',
    control_session_id: '',
    variant_session_id: '',
    independent_variable: '',
    control_value: '',
    variant_value: '',
  })

  useEffect(() => {
    api.get<Experiment[]>('/experiments').then(setExperiments).catch((err) =>
      reportFetchError('Experiments/list', err, "Couldn't load experiments")
    )
  }, [])

  const handleCreate = async () => {
    if (!form.title.trim() || !form.control_session_id || !form.variant_session_id) return
    try {
      const created = await api.post<Experiment>('/experiments', {
        title: form.title.trim(),
        hypothesis: form.hypothesis.trim(),
        control_session_id: Number(form.control_session_id),
        variant_session_id: Number(form.variant_session_id),
        independent_variable: form.independent_variable.trim(),
        control_value: form.control_value.trim(),
        variant_value: form.variant_value.trim(),
      })
      setExperiments([created, ...experiments])
      setShowForm(false)
      setForm({ title: '', hypothesis: '', control_session_id: '', variant_session_id: '', independent_variable: '', control_value: '', variant_value: '' })
    } catch {
      // ignore
    }
  }

  const handleViewComparison = async (id: number) => {
    if (comparison?.id === id) {
      setComparison(null)
      return
    }
    try {
      const metrics = await api.get<ComparisonMetric[]>(`/experiments/${id}/comparison`)
      setComparison({ id, metrics })
    } catch {
      // ignore
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold">Experiments</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">A/B test your grow parameters</p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--color-accent-gourmet)] text-white text-sm font-medium hover:opacity-90 transition-opacity"
        >
          {showForm ? <X size={16} /> : <Plus size={16} />}
          {showForm ? 'Cancel' : 'New Experiment'}
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <div className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)] mb-6">
          <h3 className="font-medium text-sm mb-3">New Experiment</h3>
          <div className="space-y-3">
            <div>
              <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Title</label>
              <input
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                placeholder="e.g. Straw vs Sawdust for Blue Oyster"
                className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
              />
            </div>
            <div>
              <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Hypothesis</label>
              <input
                value={form.hypothesis}
                onChange={(e) => setForm({ ...form, hypothesis: e.target.value })}
                placeholder="e.g. Sawdust will produce 20% more yield"
                className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Control Session ID</label>
                <input
                  value={form.control_session_id}
                  onChange={(e) => setForm({ ...form, control_session_id: e.target.value })}
                  placeholder="Session ID"
                  className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
                />
              </div>
              <div>
                <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Variant Session ID</label>
                <input
                  value={form.variant_session_id}
                  onChange={(e) => setForm({ ...form, variant_session_id: e.target.value })}
                  placeholder="Session ID"
                  className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
                />
              </div>
            </div>
            <div>
              <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Independent Variable</label>
              <input
                value={form.independent_variable}
                onChange={(e) => setForm({ ...form, independent_variable: e.target.value })}
                placeholder="e.g. substrate_type"
                className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Control Value</label>
                <input
                  value={form.control_value}
                  onChange={(e) => setForm({ ...form, control_value: e.target.value })}
                  placeholder="e.g. straw"
                  className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
                />
              </div>
              <div>
                <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Variant Value</label>
                <input
                  value={form.variant_value}
                  onChange={(e) => setForm({ ...form, variant_value: e.target.value })}
                  placeholder="e.g. sawdust"
                  className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
                />
              </div>
            </div>
            <button
              onClick={handleCreate}
              disabled={!form.title.trim() || !form.control_session_id || !form.variant_session_id}
              className="px-4 py-2 rounded-lg bg-[var(--color-accent-gourmet)] text-white text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              Create Experiment
            </button>
          </div>
        </div>
      )}

      {/* Experiment list */}
      {experiments.length > 0 ? (
        <div className="space-y-3">
          {experiments.map((exp) => (
            <div key={exp.id}>
              <div className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)]">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <h3 className="font-medium">{exp.title}</h3>
                    {exp.hypothesis && (
                      <p className="text-sm text-[var(--color-text-secondary)] mt-0.5">{exp.hypothesis}</p>
                    )}
                  </div>
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[exp.status]}`}>
                    {exp.status}
                  </span>
                </div>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--color-text-secondary)] mb-3">
                  <span>Variable: {exp.independent_variable}</span>
                  <span>Control: {exp.control_value} (#{exp.control_session_id})</span>
                  <span>Variant: {exp.variant_value} (#{exp.variant_session_id})</span>
                </div>
                <button
                  onClick={() => handleViewComparison(exp.id)}
                  className="flex items-center gap-1.5 text-xs text-[var(--color-accent-gourmet)] hover:opacity-80 transition-opacity"
                >
                  <BarChart3 size={12} />
                  {comparison?.id === exp.id ? 'Hide Comparison' : 'View Comparison'}
                </button>
              </div>

              {/* Comparison table */}
              {comparison?.id === exp.id && (
                <div className="mt-2 bg-[var(--color-bg-card)] rounded-xl border border-[var(--color-border)] overflow-hidden">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-[var(--color-border)]">
                        <th className="text-left px-4 py-2.5 text-xs text-[var(--color-text-secondary)] font-medium">Metric</th>
                        <th className="text-right px-4 py-2.5 text-xs text-[var(--color-text-secondary)] font-medium">Control</th>
                        <th className="text-right px-4 py-2.5 text-xs text-[var(--color-text-secondary)] font-medium">Variant</th>
                        <th className="text-right px-4 py-2.5 text-xs text-[var(--color-text-secondary)] font-medium">Diff</th>
                        <th className="text-center px-4 py-2.5 text-xs text-[var(--color-text-secondary)] font-medium">Winner</th>
                      </tr>
                    </thead>
                    <tbody>
                      {comparison.metrics.map((m, i) => (
                        <tr key={i} className="border-b border-[var(--color-border)] last:border-0">
                          <td className="px-4 py-2.5 font-medium">{m.metric}</td>
                          <td className="px-4 py-2.5 text-right">{m.control_value.toFixed(1)}</td>
                          <td className="px-4 py-2.5 text-right">{m.variant_value.toFixed(1)}</td>
                          <td className="px-4 py-2.5 text-right">
                            <span className={`flex items-center justify-end gap-0.5 ${
                              m.pct_difference > 0 ? 'text-green-400' : m.pct_difference < 0 ? 'text-red-400' : 'text-[var(--color-text-secondary)]'
                            }`}>
                              {m.pct_difference > 0 ? <ArrowUpRight size={12} /> : m.pct_difference < 0 ? <ArrowDownRight size={12} /> : <Minus size={12} />}
                              {Math.abs(m.pct_difference).toFixed(1)}%
                            </span>
                          </td>
                          <td className="px-4 py-2.5 text-center">
                            <span className={`text-xs font-medium ${
                              m.winner === 'control' ? 'text-blue-400' : m.winner === 'variant' ? 'text-amber-400' : 'text-[var(--color-text-secondary)]'
                            }`}>
                              {m.winner}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="bg-[var(--color-bg-card)] rounded-xl p-12 border border-[var(--color-border)] text-center">
          <FlaskConical size={48} className="mx-auto mb-4 text-[var(--color-text-secondary)]" />
          <p className="text-[var(--color-text-secondary)]">No experiments yet. Create one to start comparing grow parameters.</p>
        </div>
      )}
    </div>
  )
}
