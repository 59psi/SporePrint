import { useState, useEffect, useRef } from 'react'
import { Wrench, Send, Loader2, BookOpen, Clock } from 'lucide-react'
import { api } from '../api/client'

interface Guide {
  id: number
  request: string
  constraints: string
  guide?: string
  created_at: number
}

export default function Builder() {
  const [request, setRequest] = useState('')
  const [constraints, setConstraints] = useState('')
  const [generating, setGenerating] = useState(false)
  const [currentGuide, setCurrentGuide] = useState<string | null>(null)
  const [savedGuides, setSavedGuides] = useState<Guide[]>([])
  const [showSaved, setShowSaved] = useState(false)
  const resultRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.get<Guide[]>('/builder/guides').then(setSavedGuides).catch(() => {})
  }, [])

  const generate = async () => {
    if (!request.trim()) return
    setGenerating(true)
    setCurrentGuide(null)
    try {
      const result = await api.post<{ guide: string }>('/builder/guide', { request, constraints })
      setCurrentGuide(result.guide)
      // Refresh saved list
      api.get<Guide[]>('/builder/guides').then(setSavedGuides)
      setTimeout(() => resultRef.current?.scrollIntoView({ behavior: 'smooth' }), 100)
    } catch {
      setCurrentGuide('Error generating guide. Check that Claude API key is configured.')
    }
    setGenerating(false)
  }

  const loadGuide = async (id: number) => {
    try {
      const guide = await api.get<Guide>(`/builder/guides/${id}`)
      setCurrentGuide(guide.guide || null)
      setRequest(guide.request)
      setConstraints(guide.constraints || '')
      setShowSaved(false)
    } catch { /* ignore */ }
  }

  const examplePrompts = [
    "Add a peristaltic pump for automated substrate hydration between flushes",
    "Wire a Peltier cooler with H-bridge for heating AND cooling",
    "Add a second ESP32-CAM for top-down substrate monitoring",
    "Add a load cell (HX711) under each block for water loss / harvest weight",
    "Door reed switch so system pauses humidity when closet opens",
    "Add VOC/particulate sensor to detect contamination by smell",
    "Motorized dampers on intake/exhaust for precise FAE control",
  ]

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold">Builder's Assistant</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">
            AI-powered hardware integration guides
          </p>
        </div>
        <button
          onClick={() => setShowSaved(!showSaved)}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-[var(--color-border)] text-sm text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]"
        >
          <BookOpen size={14} />
          Saved ({savedGuides.length})
        </button>
      </div>

      {showSaved && savedGuides.length > 0 && (
        <div className="mb-6 space-y-2">
          {savedGuides.map((g) => (
            <button
              key={g.id}
              onClick={() => loadGuide(g.id)}
              className="w-full text-left p-3 rounded-lg bg-[var(--color-bg-card)] border border-[var(--color-border)] hover:border-[var(--color-bg-hover)]"
            >
              <p className="text-sm font-medium">{g.request}</p>
              <p className="text-xs text-[var(--color-text-secondary)] flex items-center gap-1 mt-1">
                <Clock size={10} />
                {new Date(g.created_at * 1000).toLocaleDateString()}
              </p>
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)] mb-4">
        <label className="block text-sm text-[var(--color-text-secondary)] mb-2">
          What do you want to add to your grow closet?
        </label>
        <textarea
          value={request}
          onChange={(e) => setRequest(e.target.value)}
          placeholder="Describe the hardware you want to integrate..."
          rows={3}
          className="w-full p-3 rounded-lg bg-[var(--color-bg-primary)] border border-[var(--color-border)] text-sm resize-none focus:outline-none focus:border-[var(--color-accent-gourmet)]"
        />

        <label className="block text-sm text-[var(--color-text-secondary)] mt-3 mb-2">
          Constraints (optional)
        </label>
        <input
          value={constraints}
          onChange={(e) => setConstraints(e.target.value)}
          placeholder="e.g. Food-safe, 12V supply, controlled from relay node"
          className="w-full p-3 rounded-lg bg-[var(--color-bg-primary)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
        />

        <button
          onClick={generate}
          disabled={generating || !request.trim()}
          className="mt-4 flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--color-accent-gourmet)] text-white text-sm font-medium disabled:opacity-40"
        >
          {generating ? (
            <>
              <Loader2 size={14} className="animate-spin" />
              Generating...
            </>
          ) : (
            <>
              <Send size={14} />
              Generate Guide
            </>
          )}
        </button>
      </div>

      {/* Example prompts */}
      {!currentGuide && !generating && (
        <div className="mb-4">
          <p className="text-xs text-[var(--color-text-secondary)] mb-2">Try one of these:</p>
          <div className="flex flex-wrap gap-2">
            {examplePrompts.map((prompt) => (
              <button
                key={prompt}
                onClick={() => setRequest(prompt)}
                className="px-3 py-1.5 rounded-lg text-xs bg-[var(--color-bg-card)] border border-[var(--color-border)] hover:border-[var(--color-bg-hover)] text-left"
              >
                {prompt}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Generated guide */}
      {generating && (
        <div className="bg-[var(--color-bg-card)] rounded-xl p-8 border border-[var(--color-border)] text-center">
          <Loader2 size={32} className="mx-auto mb-3 text-[var(--color-accent-gourmet)] animate-spin" />
          <p className="text-sm">Generating detailed integration guide...</p>
          <p className="text-xs text-[var(--color-text-secondary)] mt-1">This may take 15-30 seconds</p>
        </div>
      )}

      {currentGuide && !generating && (
        <div ref={resultRef} className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)]">
          <div className="flex items-center gap-2 mb-4">
            <Wrench size={16} className="text-[var(--color-accent-gourmet)]" />
            <h2 className="text-base font-semibold">Integration Guide</h2>
          </div>
          <div className="prose prose-invert prose-sm max-w-none">
            <pre className="whitespace-pre-wrap text-sm leading-relaxed overflow-auto">
              {currentGuide}
            </pre>
          </div>
        </div>
      )}
    </div>
  )
}
