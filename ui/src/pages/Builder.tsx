import { useState, useEffect, useRef } from 'react'
import {
  Wrench, Send, Loader2, ShoppingCart,
  Cpu, Cable, ListChecks, ChevronDown, ChevronRight,
  ExternalLink, Zap, Star, Rocket, Box,
  Target, Sprout, AlertTriangle, Info, Image as ImageIcon,
  FileCode,
} from 'lucide-react'
import { api } from '../api/client'
import WiringDiagram from '../components/builder/WiringDiagram'

interface CapabilityGroup {
  title: string
  items: string[]
}

interface TierSummary {
  id: string
  name: string
  tagline: string
  estimated_cost: string
  what_you_get: string[]
  best_for: string
  species_support: string
  capability_groups: CapabilityGroup[]
  limitations: string[]
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

interface TierDetail extends TierSummary {
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

interface CollapsibleProps {
  title: string
  summary?: string
  icon?: typeof Zap
  count?: number
  defaultOpen?: boolean
  children: React.ReactNode
}

function Collapsible({ title, summary, icon: Icon, count, defaultOpen = false, children }: CollapsibleProps) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="bg-[var(--color-bg-card)] rounded-xl border border-[var(--color-border)] mb-4 overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-4 text-left hover:bg-[var(--color-bg-hover)] transition-colors"
      >
        <div className="flex items-center gap-3 min-w-0">
          {Icon && <Icon size={18} className="text-[var(--color-accent-gourmet)] flex-shrink-0" />}
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-semibold">{title}</span>
              {count !== undefined && (
                <span className="text-xs px-1.5 py-0.5 rounded bg-[var(--color-bg-hover)] text-[var(--color-text-secondary)]">
                  {count}
                </span>
              )}
            </div>
            {summary && <p className="text-xs text-[var(--color-text-secondary)] mt-0.5 truncate">{summary}</p>}
          </div>
        </div>
        {open ? <ChevronDown size={16} className="flex-shrink-0" /> : <ChevronRight size={16} className="flex-shrink-0" />}
      </button>
      {open && <div className="border-t border-[var(--color-border)] p-5">{children}</div>}
    </div>
  )
}

export default function Builder() {
  const [tiers, setTiers] = useState<TierSummary[]>([])
  const [selectedTierId, setSelectedTierId] = useState<string | null>(null)
  const [tierDetail, setTierDetail] = useState<TierDetail | null>(null)
  const [activeTab, setActiveTab] = useState<'capabilities' | 'shopping' | 'wiring' | 'steps'>('capabilities')

  const [models, setModels] = useState<{filename: string, size_bytes: number, url: string}[]>([])
  const [diagrams, setDiagrams] = useState<{filename: string, size_bytes: number, url: string}[]>([])
  const [firmware, setFirmware] = useState<{node: string, path: string, files: {filename: string, size_bytes: number, url: string}[]}[]>([])

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
    api.get<{filename: string, size_bytes: number, url: string}[]>('/builder/diagrams')
      .then(setDiagrams).catch(() => {})
    api.get<{node: string, path: string, files: {filename: string, size_bytes: number, url: string}[]}[]>('/builder/firmware')
      .then(setFirmware).catch(() => {})
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
    setActiveTab('capabilities')
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

  const accent = selectedTierId ? tierAccents[selectedTierId] : 'var(--color-accent-gourmet)'

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">Hardware Builder</h1>
        <p className="text-sm text-[var(--color-text-secondary)]">
          Choose a tier below — each one includes a full shopping list, wiring diagrams, and step-by-step setup instructions.
        </p>
      </div>

      {/* Tier selection cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        {tiers.map((tier) => {
          const Icon = tierIcons[tier.id] || Zap
          const tierAccent = tierAccents[tier.id] || 'var(--color-accent-gourmet)'
          const isSelected = selectedTierId === tier.id
          return (
            <button
              key={tier.id}
              onClick={() => selectTier(tier.id)}
              className={`text-left p-5 rounded-xl border transition-all ${
                isSelected
                  ? 'border-[var(--color-accent-gourmet)] bg-[var(--color-accent-gourmet)]/5 shadow-lg'
                  : 'border-[var(--color-border)] bg-[var(--color-bg-card)] hover:border-[var(--color-bg-hover)]'
              }`}
            >
              <div className="flex items-center gap-2 mb-2">
                <Icon size={18} style={{ color: tierAccent }} />
                <span className="font-semibold">{tier.name}</span>
                <span className="ml-auto text-lg font-bold" style={{ color: tierAccent }}>
                  {tier.estimated_cost}
                </span>
              </div>
              <p className="text-sm text-[var(--color-text-secondary)] mb-3">{tier.tagline}</p>
              <div className="flex items-center gap-3 text-[11px] text-[var(--color-text-secondary)] mb-3">
                <span className="flex items-center gap-1">
                  <Box size={11} /> {tier.component_count} parts
                </span>
                <span className="flex items-center gap-1">
                  <ListChecks size={11} /> {tier.what_you_get.length} features
                </span>
              </div>
              <ul className="space-y-1">
                {tier.what_you_get.slice(0, 4).map((item, i) => (
                  <li key={i} className="text-xs text-[var(--color-text-secondary)] flex items-start gap-1.5">
                    <span style={{ color: tierAccent }} className="flex-shrink-0">+</span>
                    <span>{item}</span>
                  </li>
                ))}
                {tier.what_you_get.length > 4 && (
                  <li className="text-xs text-[var(--color-text-secondary)] italic mt-1">
                    +{tier.what_you_get.length - 4} more — {isSelected ? 'scroll down' : 'click to see all'}
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
          <div className="flex overflow-x-auto border-b border-[var(--color-border)]">
            {([
              { key: 'capabilities' as const, icon: Target, label: 'Capabilities' },
              { key: 'shopping' as const, icon: ShoppingCart, label: 'Shopping List' },
              { key: 'wiring' as const, icon: Cable, label: 'Wiring' },
              { key: 'steps' as const, icon: ListChecks, label: 'Setup Steps' },
            ]).map(({ key, icon: TabIcon, label }) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`flex items-center gap-2 px-5 py-3 text-sm border-b-2 transition-colors whitespace-nowrap ${
                  activeTab === key
                    ? 'text-[var(--color-text-primary)]'
                    : 'border-transparent text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'
                }`}
                style={activeTab === key ? { borderColor: accent } : {}}
              >
                <TabIcon size={14} />
                {label}
              </button>
            ))}
          </div>

          <div className="p-5">
            {/* Capabilities */}
            {activeTab === 'capabilities' && (
              <div className="space-y-5">
                {tierDetail.best_for && (
                  <div className="p-4 rounded-lg bg-[var(--color-bg-primary)] border border-[var(--color-border)]">
                    <div className="flex items-center gap-2 mb-2">
                      <Info size={14} style={{ color: accent }} />
                      <h3 className="text-sm font-semibold">Who it's for</h3>
                    </div>
                    <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed">{tierDetail.best_for}</p>
                  </div>
                )}

                {tierDetail.species_support && (
                  <div className="p-4 rounded-lg bg-[var(--color-bg-primary)] border border-[var(--color-border)]">
                    <div className="flex items-center gap-2 mb-2">
                      <Sprout size={14} style={{ color: accent }} />
                      <h3 className="text-sm font-semibold">Species support</h3>
                    </div>
                    <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed">{tierDetail.species_support}</p>
                  </div>
                )}

                {tierDetail.capability_groups?.length > 0 && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {tierDetail.capability_groups.map((group, gi) => (
                      <div key={gi} className="p-4 rounded-lg bg-[var(--color-bg-primary)] border border-[var(--color-border)]">
                        <h4 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: accent }}>
                          {group.title}
                        </h4>
                        <ul className="space-y-1.5">
                          {group.items.map((item, i) => (
                            <li key={i} className="text-xs text-[var(--color-text-secondary)] flex items-start gap-2 leading-relaxed">
                              <span style={{ color: accent }} className="flex-shrink-0 mt-0.5">✓</span>
                              <span>{item}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                )}

                {tierDetail.limitations?.length > 0 && (
                  <div className="p-4 rounded-lg bg-amber-950/20 border border-amber-900/30">
                    <div className="flex items-center gap-2 mb-2">
                      <AlertTriangle size={14} className="text-amber-400" />
                      <h3 className="text-sm font-semibold text-amber-200">Limitations</h3>
                    </div>
                    <ul className="space-y-1">
                      {tierDetail.limitations.map((lim, i) => (
                        <li key={i} className="text-xs text-amber-200/80 flex items-start gap-2 leading-relaxed">
                          <span className="flex-shrink-0 mt-0.5">•</span>
                          <span>{lim}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

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
                                className="p-1.5 rounded-lg hover:bg-[var(--color-bg-hover)]"
                                style={{ color: accent }}
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
                          <td className="py-1.5 pr-3 font-mono" style={{ color: accent }}>{w.from_pin}</td>
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
                      <span
                        className="flex-shrink-0 w-6 h-6 rounded-full text-xs flex items-center justify-center font-medium"
                        style={{ backgroundColor: `${accent}1a`, color: accent }}
                      >
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

      {/* Resources — collapsible sections */}
      {models.length > 0 && (
        <Collapsible
          title="3D Print Models"
          summary="Parametric OpenSCAD enclosures for Pi, ESP32, sensors, camera, and relay board"
          icon={Box}
          count={models.length}
        >
          <p className="text-xs text-[var(--color-text-secondary)] mb-3">
            Download .scad files and open in OpenSCAD or import into your slicer. Dimensions match the recommended hardware in the shopping lists above.
          </p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {models.map((m) => (
              <a key={m.filename} href={m.url} download
                 className="p-3 rounded-lg bg-[var(--color-bg-primary)] border border-[var(--color-border)] hover:border-emerald-500/30 transition-colors text-center">
                <Box size={20} className="mx-auto mb-1 text-emerald-400" />
                <p className="text-xs font-medium">{m.filename.replace('.scad', '').replace(/_/g, ' ')}</p>
                <p className="text-[10px] text-[var(--color-text-secondary)]">{(m.size_bytes / 1024).toFixed(1)} KB</p>
              </a>
            ))}
          </div>
        </Collapsible>
      )}

      {diagrams.length > 0 && (
        <Collapsible
          title="Wiring Diagrams"
          summary="Color-coded SVG diagrams for each tier"
          icon={ImageIcon}
          count={diagrams.filter(d => d.filename.startsWith('wiring-')).length}
        >
          <p className="text-xs text-[var(--color-text-secondary)] mb-3">
            Click a diagram to open at full size in a new tab.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {diagrams.filter(d => d.filename.startsWith('wiring-')).map((d) => (
              <a key={d.filename} href={d.url} target="_blank" rel="noopener noreferrer"
                 className="rounded-lg overflow-hidden bg-[var(--color-bg-primary)] border border-[var(--color-border)] hover:border-emerald-500/30 transition-colors">
                <img src={d.url} alt={d.filename} className="w-full h-auto" loading="lazy" />
                <p className="text-xs text-center py-2 font-medium capitalize">
                  {d.filename.replace('.svg', '').replace(/wiring-/g, '').replace(/-/g, ' ')}
                </p>
              </a>
            ))}
          </div>
        </Collapsible>
      )}

      {firmware.length > 0 && (
        <Collapsible
          title="ESP32 Firmware"
          summary="PlatformIO source for each node — clone + flash with pio run -t upload -e <node>"
          icon={FileCode}
          count={firmware.reduce((n, g) => n + g.files.length, 0)}
        >
          <p className="text-xs text-[var(--color-text-secondary)] mb-3">
            Download any file or browse the full source on GitHub:{' '}
            <a
              href="https://github.com/59psi/SporePrint/tree/main/firmware"
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'var(--color-accent-primary)' }}
            >
              github.com/59psi/SporePrint/firmware
            </a>
            . Each node compiles to an independent binary via{' '}
            <code className="font-mono text-[var(--color-accent-primary)]">
              pio run -t upload -e &lt;node&gt;
            </code>{' '}
            from the <code className="font-mono">firmware/</code> directory.
          </p>
          <div className="space-y-3">
            {firmware.map((group) => (
              <div key={group.path} className="rounded-lg border border-[var(--color-border)] overflow-hidden">
                <div className="px-3 py-2 text-xs font-mono bg-[var(--color-bg-hover)] flex items-center justify-between">
                  <span>{group.path}</span>
                  <span className="text-[var(--color-text-tertiary)]">{group.files.length} file{group.files.length !== 1 ? 's' : ''}</span>
                </div>
                <div className="divide-y divide-[var(--color-border)]">
                  {group.files.map((f) => (
                    <a
                      key={f.filename}
                      href={f.url}
                      download
                      className="flex items-center justify-between px-3 py-2 text-xs font-mono hover:bg-[var(--color-bg-hover)] transition-colors"
                    >
                      <span className="truncate">{f.filename}</span>
                      <span className="text-[var(--color-text-tertiary)] ml-2 flex-shrink-0">
                        {(f.size_bytes / 1024).toFixed(1)} KB
                      </span>
                    </a>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Collapsible>
      )}

      {/* Claude Assistant (collapsible) */}
      <div className="bg-[var(--color-bg-card)] rounded-xl border border-[var(--color-border)] mb-4 overflow-hidden">
        <button
          onClick={() => setShowAssistant(!showAssistant)}
          className="w-full flex items-center justify-between p-4 text-left hover:bg-[var(--color-bg-hover)] transition-colors"
        >
          <div className="flex items-center gap-3">
            <Wrench size={18} className="text-[var(--color-accent-active)]" />
            <div>
              <div className="text-sm font-semibold">Ask the Assistant</div>
              <p className="text-xs text-[var(--color-text-secondary)] mt-0.5">Custom hardware questions powered by Claude</p>
            </div>
          </div>
          {showAssistant ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
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
