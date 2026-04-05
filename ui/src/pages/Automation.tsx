import { useEffect, useState } from 'react'
import { Cog, ToggleLeft, ToggleRight, Clock, Zap, Shield, ChevronDown, ChevronUp } from 'lucide-react'
import { api } from '../api/client'

interface Rule {
  id: number
  name: string
  description: string
  enabled: boolean
  priority: number
  condition: Record<string, unknown>
  action: Record<string, unknown>
  applies_to_phases?: string[]
  applies_to_species?: string[]
  cooldown_seconds: number
}

interface Firing {
  id: number
  rule_name: string
  timestamp: number
  condition_met: string
  action_taken: string
}

export default function Automation() {
  const [rules, setRules] = useState<Rule[]>([])
  const [firings, setFirings] = useState<Firing[]>([])
  const [expandedRule, setExpandedRule] = useState<number | null>(null)
  const [tab, setTab] = useState<'rules' | 'history' | 'overrides'>('rules')

  useEffect(() => {
    api.get<Rule[]>('/automation/rules').then(setRules).catch(() => {})
    api.get<Firing[]>('/automation/firings?limit=20').then(setFirings).catch(() => {})
  }, [])

  const toggleRule = async (ruleId: number) => {
    try {
      const result = await api.patch<{ id: number; enabled: boolean }>(
        `/automation/rules/${ruleId}/toggle`, {}
      )
      setRules((prev) =>
        prev.map((r) => (r.id === result.id ? { ...r, enabled: result.enabled } : r))
      )
    } catch { /* ignore */ }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold">Automation</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">
            Rules engine, overrides, and firing history
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm text-[var(--color-text-secondary)]">
          <Cog size={14} />
          {rules.filter((r) => r.enabled).length} / {rules.length} active
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 p-1 bg-[var(--color-bg-secondary)] rounded-lg w-fit">
        {(['rules', 'history', 'overrides'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-1.5 rounded-md text-sm capitalize transition-colors ${
              tab === t
                ? 'bg-[var(--color-bg-card)] text-[var(--color-text-primary)]'
                : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === 'rules' && (
        <div className="space-y-2">
          {rules.map((rule) => (
            <div
              key={rule.id}
              className="bg-[var(--color-bg-card)] rounded-xl border border-[var(--color-border)] overflow-hidden"
            >
              <div className="flex items-center gap-3 p-4">
                <button onClick={() => toggleRule(rule.id)} className="flex-shrink-0">
                  {rule.enabled ? (
                    <ToggleRight size={24} className="text-[var(--color-accent-gourmet)]" />
                  ) : (
                    <ToggleLeft size={24} className="text-[var(--color-text-secondary)]" />
                  )}
                </button>

                <div className="flex-1 min-w-0">
                  <p className={`text-sm font-medium ${!rule.enabled ? 'opacity-50' : ''}`}>
                    {rule.name}
                  </p>
                  <p className="text-xs text-[var(--color-text-secondary)] truncate">
                    {rule.description}
                  </p>
                </div>

                <div className="flex items-center gap-2 text-xs text-[var(--color-text-secondary)]">
                  {rule.applies_to_species && (
                    <span className="px-2 py-0.5 rounded bg-[var(--color-bg-hover)]">
                      {rule.applies_to_species.join(', ')}
                    </span>
                  )}
                  <span className="flex items-center gap-1">
                    <Zap size={10} /> P{rule.priority}
                  </span>
                  <span className="flex items-center gap-1">
                    <Clock size={10} /> {rule.cooldown_seconds}s
                  </span>
                </div>

                <button
                  onClick={() => setExpandedRule(expandedRule === rule.id ? null : rule.id)}
                  className="p-1 text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]"
                >
                  {expandedRule === rule.id ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                </button>
              </div>

              {expandedRule === rule.id && (
                <div className="px-4 pb-4 pt-0 border-t border-[var(--color-border)]">
                  <div className="grid grid-cols-2 gap-4 mt-3 text-sm">
                    <div>
                      <p className="text-xs text-[var(--color-text-secondary)] mb-1">Condition</p>
                      <pre className="text-xs bg-[var(--color-bg-primary)] p-2 rounded overflow-x-auto">
                        {JSON.stringify(rule.condition, null, 2)}
                      </pre>
                    </div>
                    <div>
                      <p className="text-xs text-[var(--color-text-secondary)] mb-1">Action</p>
                      <pre className="text-xs bg-[var(--color-bg-primary)] p-2 rounded overflow-x-auto">
                        {JSON.stringify(rule.action, null, 2)}
                      </pre>
                    </div>
                  </div>
                  {rule.applies_to_phases && (
                    <p className="text-xs text-[var(--color-text-secondary)] mt-2">
                      Phases: {rule.applies_to_phases.join(', ')}
                    </p>
                  )}
                </div>
              )}
            </div>
          ))}

          {rules.length === 0 && (
            <div className="bg-[var(--color-bg-card)] rounded-xl p-8 border border-[var(--color-border)] text-center">
              <Cog size={32} className="mx-auto mb-3 text-[var(--color-text-secondary)]" />
              <p className="text-sm text-[var(--color-text-secondary)]">
                No automation rules loaded. Start the backend to seed built-in templates.
              </p>
            </div>
          )}
        </div>
      )}

      {tab === 'history' && (
        <div className="bg-[var(--color-bg-card)] rounded-xl border border-[var(--color-border)]">
          {firings.length > 0 ? (
            <div className="divide-y divide-[var(--color-border)]">
              {firings.map((f) => (
                <div key={f.id} className="flex items-center gap-3 p-3">
                  <Zap size={14} className="text-[var(--color-accent-gourmet)] flex-shrink-0" />
                  <div className="flex-1">
                    <p className="text-sm font-medium">{f.rule_name}</p>
                    <p className="text-xs text-[var(--color-text-secondary)]">
                      {new Date(f.timestamp * 1000).toLocaleString()}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="p-8 text-center">
              <Clock size={32} className="mx-auto mb-3 text-[var(--color-text-secondary)]" />
              <p className="text-sm text-[var(--color-text-secondary)]">
                No rule firings yet.
              </p>
            </div>
          )}
        </div>
      )}

      {tab === 'overrides' && (
        <div className="bg-[var(--color-bg-card)] rounded-xl p-8 border border-[var(--color-border)] text-center">
          <Shield size={32} className="mx-auto mb-3 text-[var(--color-text-secondary)]" />
          <p className="text-sm text-[var(--color-text-secondary)]">
            Manual overrides lock out automation for specific targets. Active overrides will appear here.
          </p>
        </div>
      )}
    </div>
  )
}
