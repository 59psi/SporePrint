import { useState, useEffect, useRef } from 'react'
import {
  Wrench, Send, Loader2, ShoppingCart,
  Cpu, Cable, ListChecks, ChevronDown, ChevronUp,
  ExternalLink, Zap, Star, Rocket, Box,
} from 'lucide-react'
import { api } from '../api/client'
import WiringDiagram from '../components/builder/WiringDiagram'

interface TierSummary {
  id: string
  name: string
  tagline: string
  estimated_cost: string
  what_you_get: string[]
  component_count: number
}

interface Component {
  name: string
  role: string
  quantity: number
  price_approx: string
  url: string
  category: string
  notes: string
}

interface WiringConnection {
  from_device: string
  from_pin: string
  to_device: string
  to_pin: string
  note: string
}

interface TierDetail {
  id: string
  name: string
  tagline: string
  estimated_cost: string
  what_you_get: string[]
  components: Component[]
  wiring: WiringConnection[]
  wiring_diagram: string
  firmware_targets: string[]
  setup_steps: string[]
}

const tierIcons: Record<string, typeof Zap> = {
  bare_bones: Zap,
  recommended: Star,
  all_the_things: Rocket,
}

const tierAccents: Record<string, string> = {
  bare_bones: 'var(--color-accent-gourmet)',
  recommended: 'var(--color-accent-active)',
  all_the_things: 'var(--color-accent-medicinal)',
}

export default function Builder() {
  const [tiers, setTiers] = useState<TierSummary[]>([])
  const [selectedTierId, setSelectedTierId] = useState<string | null>(null)
  const [tierDetail, setTierDetail] = useState<TierDetail | null>(null)
  const [activeTab, setActiveTab] = useState<'shopping' | 'wiring' | 'steps'>('shopping')

  // 3D print models
  const [models, setModels] = useState<{filename: string, size_bytes: number, url: string}[]>([])

  // Claude assistant (kept)
  const [showAssistant, setShowAssistant] = useState(false)
  const [request, setRequest] = useState('')
  const [constraints, setConstraints] = useState('')
  const [generating, setGenerating] = useState(false)
  const [currentGuide, setCurrentGuide] = useState<string | null>(null)
  const resultRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.get<TierSummary[]>('/builder/tiers').then(setTiers).catch(() => {})
    api.get<{filename: string, size_bytes: number, url: string}[]>('/builder/models')
      .then(setModels).catch(() => {})
  }, [])

  const selectTier = async (tierId: string) => {
    if (selectedTierId === tierId) {
      setSelectedTierId(null)
      setTierDetail(null)
      return
    }
    setSelectedTierId(tierId)
    const detail = await api.get<TierDetail>(`/builder/tiers/${tierId}`)
    setTierDetail(detail)
    setActiveTab('shopping')
  }

  const generate = async () => {
    if (!request.trim()) return
    setGenerating(true)
    setCurrentGuide(null)
    try {
      const result = await api.post<{ guide: string }>('/builder/guide', { request, constraints })
      setCurrentGuide(result.guide)
      setTimeout(() => resultRef.current?.scrollIntoView({ behavior: 'smooth' }), 100)
    } catch {
      setCurrentGuide('Error generating guide. Check that Claude API key is configured.')
    }
    setGenerating(false)
  }

  const categoryOrder = ['controller', 'sensor', 'actuator', 'power', 'plug', 'misc']
  const categoryLabels: Record<string, string> = {
    controller: 'Controllers', sensor: 'Sensors', actuator: 'Actuators & Fans',
    power: 'Power', plug: 'Smart Plugs', misc: 'Miscellaneous',
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">Hardware Builder</h1>
        <p className="text-sm text-[var(--color-text-secondary)]">
          Choose your build tier — everything you need to get SporePrint running
        </p>
      </div>

      {/* Tier selection cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        {tiers.map((tier) => {
          const Icon = tierIcons[tier.id] || Zap
          const accent = tierAccents[tier.id] || 'var(--color-accent-gourmet)'
          const isSelected = selectedTierId === tier.id
          return (
            <button
              key={tier.id}
              onClick={() => selectTier(tier.id)}
              className={`text-left p-5 rounded-xl border transition-all ${
                isSelected
                  ? 'border-[var(--color-accent-gourmet)] bg-[var(--color-accent-gourmet)]/5'
                  : 'border-[var(--color-border)] bg-[var(--color-bg-card)] hover:border-[var(--color-bg-hover)]'
              }`}
            >
              <div className="flex items-center gap-2 mb-2">
                <Icon size={18} style={{ color: accent }} />
                <span className="font-semibold">{tier.name}</span>
                <span className="ml-auto text-lg font-bold" style={{ color: accent }}>
                  {tier.estimated_cost}
                </span>
              </div>
              <p className="text-sm text-[var(--color-text-secondary)] mb-3">{tier.tagline}</p>
              <p className="text-xs text-[var(--color-text-secondary)]">
                {tier.component_count} components
              </p>
              <ul className="mt-3 space-y-1">
                {tier.what_you_get.slice(0, 4).map((item, i) => (
                  <li key={i} className="text-xs text-[var(--color-text-secondary)] flex items-start gap-1">
                    <span style={{ color: accent }}>+</span>
                    <span>{item}</span>
                  </li>
                ))}
                {tier.what_you_get.length > 4 && (
                  <li className="text-xs text-[var(--color-text-secondary)]">
                    +{tier.what_you_get.length - 4} more...
                  </li>
                )}
              </ul>
            </button>
          )
        })}
      </div>

      {/* Tier detail */}
      {tierDetail && (
        <div className="bg-[var(--color-bg-card)] rounded-xl border border-[var(--color-border)] mb-6">
          {/* Tabs */}
          <div className="flex border-b border-[var(--color-border)]">
            {([
              { key: 'shopping' as const, icon: ShoppingCart, label: 'Shopping List' },
              { key: 'wiring' as const, icon: Cable, label: 'Wiring Guide' },
              { key: 'steps' as const, icon: ListChecks, label: 'Setup Steps' },
            ]).map(({ key, icon: TabIcon, label }) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`flex items-center gap-2 px-5 py-3 text-sm border-b-2 transition-colors ${
                  activeTab === key
                    ? 'border-[var(--color-accent-gourmet)] text-[var(--color-text-primary)]'
                    : 'border-transparent text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'
                }`}
              >
                <TabIcon size={14} />
                {label}
              </button>
            ))}
          </div>

          <div className="p-5">
            {/* Shopping List */}
            {activeTab === 'shopping' && (
              <div>
                {categoryOrder.map((cat) => {
                  const items = tierDetail.components.filter((c) => c.category === cat)
                  if (items.length === 0) return null
                  return (
                    <div key={cat} className="mb-6 last:mb-0">
                      <h3 className="text-sm font-medium text-[var(--color-text-secondary)] uppercase tracking-wider mb-2">
                        {categoryLabels[cat] || cat}
                      </h3>
                      <div className="space-y-2">
                        {items.map((comp, i) => (
                          <div key={i} className="flex items-start gap-3 p-3 rounded-lg bg-[var(--color-bg-primary)]">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-medium">{comp.name}</span>
                                {comp.quantity > 1 && (
                                  <span className="text-xs px-1.5 py-0.5 rounded bg-[var(--color-bg-hover)]">
                                    x{comp.quantity}
                                  </span>
                                )}
                              </div>
                              <p className="text-xs text-[var(--color-text-secondary)] mt-0.5">{comp.role}</p>
                              {comp.notes && (
                                <p className="text-xs text-[var(--color-text-secondary)] mt-1 opacity-70">{comp.notes}</p>
                              )}
                            </div>
                            <div className="flex items-center gap-2 flex-shrink-0">
                              <span className="text-sm font-medium">{comp.price_approx}</span>
                              <a
                                href={comp.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="p-1.5 rounded-lg hover:bg-[var(--color-bg-hover)] text-[var(--color-accent-gourmet)]"
                              >
                                <ExternalLink size={14} />
                              </a>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}

            {/* Wiring Guide */}
            {activeTab === 'wiring' && (
              <div>
                <WiringDiagram tierId={tierDetail.id} />

                <h3 className="text-sm font-medium mb-2 mt-6">Connection Reference</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-left text-[var(--color-text-secondary)] border-b border-[var(--color-border)]">
                        <th className="py-2 pr-3">From</th>
                        <th className="py-2 pr-3">Pin</th>
                        <th className="py-2 pr-3">To</th>
                        <th className="py-2 pr-3">Pin</th>
                        <th className="py-2">Note</th>
                      </tr>
                    </thead>
                    <tbody>
                      {tierDetail.wiring.map((w, i) => (
                        <tr key={i} className="border-b border-[var(--color-border)]/50">
                          <td className="py-1.5 pr-3 font-medium">{w.from_device}</td>
                          <td className="py-1.5 pr-3 font-mono text-[var(--color-accent-gourmet)]">{w.from_pin}</td>
                          <td className="py-1.5 pr-3">{w.to_device}</td>
                          <td className="py-1.5 pr-3 font-mono">{w.to_pin}</td>
                          <td className="py-1.5 text-[var(--color-text-secondary)]">{w.note}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Setup Steps */}
            {activeTab === 'steps' && (
              <div>
                <div className="mb-3 flex items-center gap-2 text-xs text-[var(--color-text-secondary)] flex-wrap">
                  <Cpu size={12} />
                  Firmware targets:
                  {tierDetail.firmware_targets.map((t) => (
                    <span key={t} className="px-1.5 py-0.5 rounded bg-[var(--color-bg-hover)] font-mono">{t}</span>
                  ))}
                </div>
                <ol className="space-y-3">
                  {tierDetail.setup_steps.map((step, i) => (
                    <li key={i} className="flex gap-3">
                      <span className="flex-shrink-0 w-6 h-6 rounded-full bg-[var(--color-accent-gourmet)]/10 text-[var(--color-accent-gourmet)] text-xs flex items-center justify-center font-medium">
                        {i + 1}
                      </span>
                      <p className="text-sm pt-0.5">{step}</p>
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 3D Print Models */}
      {models.length > 0 && (
        <div className="mb-6">
          <h2 className="text-lg font-semibold mb-3">3D Print Models (OpenSCAD)</h2>
          <p className="text-xs text-[var(--color-text-secondary)] mb-3">
            Parametric enclosures for SporePrint hardware. Download .scad files and open in OpenSCAD or import into your slicer.
          </p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {models.map((m) => (
              <a key={m.filename} href={m.url} download
                 className="p-3 rounded-lg bg-[var(--color-bg-card)] border border-[var(--color-border)] hover:border-emerald-500/30 transition-colors text-center">
                <Box size={20} className="mx-auto mb-1 text-emerald-400" />
                <p className="text-xs font-medium">{m.filename.replace('.scad', '').replace(/_/g, ' ')}</p>
                <p className="text-[10px] text-[var(--color-text-secondary)]">{(m.size_bytes / 1024).toFixed(1)} KB</p>
              </a>
            ))}
          </div>
        </div>
      )}

      {/* Claude Assistant (collapsible) */}
      <div className="bg-[var(--color-bg-card)] rounded-xl border border-[var(--color-border)]">
        <button
          onClick={() => setShowAssistant(!showAssistant)}
          className="w-full flex items-center justify-between p-4 text-left"
        >
          <div className="flex items-center gap-2">
            <Wrench size={16} className="text-[var(--color-accent-active)]" />
            <span className="text-sm font-medium">Ask the Assistant</span>
            <span className="text-xs text-[var(--color-text-secondary)]">— custom hardware questions powered by Claude</span>
          </div>
          {showAssistant ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>

        {showAssistant && (
          <div className="px-4 pb-4 border-t border-[var(--color-border)] pt-4">
            <textarea
              value={request}
              onChange={(e) => setRequest(e.target.value)}
              placeholder="e.g. How do I add a peristaltic pump for automated misting?"
              rows={2}
              className="w-full p-3 rounded-lg bg-[var(--color-bg-primary)] border border-[var(--color-border)] text-sm resize-none focus:outline-none focus:border-[var(--color-accent-gourmet)]"
            />
            <div className="flex gap-2 mt-2">
              <input
                value={constraints}
                onChange={(e) => setConstraints(e.target.value)}
                placeholder="Constraints (optional)"
                className="flex-1 p-2 rounded-lg bg-[var(--color-bg-primary)] border border-[var(--color-border)] text-sm focus:outline-none"
              />
              <button
                onClick={generate}
                disabled={generating || !request.trim()}
                className="flex items-center gap-1 px-3 py-2 rounded-lg bg-[var(--color-accent-active)] text-white text-sm disabled:opacity-40"
              >
                {generating ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                {generating ? 'Generating...' : 'Ask'}
              </button>
            </div>

            {currentGuide && !generating && (
              <div ref={resultRef} className="mt-4 p-4 bg-[var(--color-bg-primary)] rounded-lg">
                <pre className="whitespace-pre-wrap text-xs leading-relaxed overflow-auto">{currentGuide}</pre>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
