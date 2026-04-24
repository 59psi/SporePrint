import { useEffect, useState } from 'react'
import { FileText, Download, Brain, Loader2 } from 'lucide-react'
import { api } from '../api/client'
import { reportFetchError } from '../stores/toastStore'

interface Session {
  id: number
  name: string
  species_profile_id: string
  status: string
  current_phase: string
}

interface Analysis {
  overall_score?: number
  summary?: string
  issues_identified?: string[]
  recommendations?: string[]
  yield_assessment?: string
  error?: string
}

export default function Transcripts() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [analyzing, setAnalyzing] = useState(false)
  const [markdownPreview, setMarkdownPreview] = useState<string | null>(null)

  useEffect(() => {
    api.get<Session[]>('/sessions').then(setSessions).catch((err) =>
      reportFetchError('Transcripts/sessions', err, "Couldn't load sessions")
    )
  }, [])

  const exportJSON = async (id: number) => {
    const data = await api.get<Record<string, unknown>>(`/transcript/sessions/${id}/transcript?format=json`)
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `session_${id}_transcript.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const exportMarkdown = async (id: number) => {
    const res = await fetch(`/api/transcript/sessions/${id}/transcript?format=markdown`)
    const text = await res.text()
    const blob = new Blob([text], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `session_${id}_transcript.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  const previewMarkdown = async (id: number) => {
    const res = await fetch(`/api/transcript/sessions/${id}/transcript?format=markdown`)
    const text = await res.text()
    setMarkdownPreview(text)
    setSelectedId(id)
  }

  const runAnalysis = async (id: number) => {
    setAnalyzing(true)
    setSelectedId(id)
    try {
      const result = await api.post<Analysis>(`/transcript/sessions/${id}/analyze`, {})
      setAnalysis(result)
    } catch {
      setAnalysis({ error: 'Analysis failed' })
    }
    setAnalyzing(false)
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold mb-2">Transcripts & Analysis</h1>
      <p className="text-sm text-[var(--color-text-secondary)] mb-6">Export session data and run Claude analysis</p>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Session list */}
        <div className="space-y-2">
          {sessions.map((s) => (
            <div
              key={s.id}
              className={`p-4 rounded-xl border transition-colors cursor-pointer ${
                selectedId === s.id
                  ? 'bg-[var(--color-bg-card)] border-[var(--color-accent-gourmet)]/30'
                  : 'bg-[var(--color-bg-card)] border-[var(--color-border)] hover:border-[var(--color-bg-hover)]'
              }`}
              onClick={() => { setSelectedId(s.id); setAnalysis(null); setMarkdownPreview(null) }}
            >
              <p className="font-medium text-sm">{s.name}</p>
              <p className="text-xs text-[var(--color-text-secondary)]">
                {s.species_profile_id.replace(/_/g, ' ')} &middot; {s.status}
              </p>

              <div className="flex gap-2 mt-3">
                <button
                  onClick={(e) => { e.stopPropagation(); exportJSON(s.id) }}
                  className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-[var(--color-bg-hover)] hover:bg-[var(--color-bg-primary)]"
                >
                  <Download size={10} /> JSON
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); exportMarkdown(s.id) }}
                  className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-[var(--color-bg-hover)] hover:bg-[var(--color-bg-primary)]"
                >
                  <Download size={10} /> MD
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); previewMarkdown(s.id) }}
                  className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-[var(--color-bg-hover)] hover:bg-[var(--color-bg-primary)]"
                >
                  <FileText size={10} /> Preview
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); runAnalysis(s.id) }}
                  className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-[var(--color-accent-active)]/10 text-[var(--color-accent-active)]"
                >
                  <Brain size={10} /> Analyze
                </button>
              </div>
            </div>
          ))}

          {sessions.length === 0 && (
            <div className="bg-[var(--color-bg-card)] rounded-xl p-8 border border-[var(--color-border)] text-center">
              <FileText size={32} className="mx-auto mb-3 text-[var(--color-text-secondary)]" />
              <p className="text-sm text-[var(--color-text-secondary)]">No sessions to export.</p>
            </div>
          )}
        </div>

        {/* Analysis / Preview panel */}
        <div className="lg:col-span-2">
          {analyzing && (
            <div className="bg-[var(--color-bg-card)] rounded-xl p-8 border border-[var(--color-border)] text-center">
              <Loader2 size={32} className="mx-auto mb-3 text-[var(--color-accent-active)] animate-spin" />
              <p className="text-sm">Running Claude analysis...</p>
            </div>
          )}

          {analysis && !analyzing && (
            <div className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)]">
              <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <Brain size={18} className="text-[var(--color-accent-active)]" />
                Claude Analysis
                {analysis.overall_score && (
                  <span className="ml-auto text-2xl font-bold text-[var(--color-accent-gourmet)]">
                    {analysis.overall_score}/100
                  </span>
                )}
              </h2>

              {analysis.error && (
                <p className="text-sm text-[var(--color-danger)]">{analysis.error}</p>
              )}

              {analysis.summary && (
                <p className="text-sm mb-4">{analysis.summary}</p>
              )}

              {analysis.yield_assessment && (
                <div className="mb-4">
                  <h3 className="text-sm font-medium text-[var(--color-text-secondary)] mb-1">Yield Assessment</h3>
                  <p className="text-sm">{analysis.yield_assessment}</p>
                </div>
              )}

              {analysis.issues_identified && analysis.issues_identified.length > 0 && (
                <div className="mb-4">
                  <h3 className="text-sm font-medium text-[var(--color-warning)] mb-1">Issues Found</h3>
                  <ul className="text-sm space-y-1">
                    {analysis.issues_identified.map((issue, i) => (
                      <li key={i} className="flex items-start gap-2">
                        <span className="text-[var(--color-warning)]">&bull;</span> {issue}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {analysis.recommendations && analysis.recommendations.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-[var(--color-accent-gourmet)] mb-1">Recommendations</h3>
                  <ul className="text-sm space-y-1">
                    {analysis.recommendations.map((rec, i) => (
                      <li key={i} className="flex items-start gap-2">
                        <span className="text-[var(--color-accent-gourmet)]">&bull;</span> {rec}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {markdownPreview && !analyzing && !analysis && (
            <div className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)]">
              <h2 className="text-sm font-medium mb-3">Markdown Preview</h2>
              <pre className="text-xs whitespace-pre-wrap overflow-auto max-h-[600px] bg-[var(--color-bg-primary)] p-4 rounded-lg">
                {markdownPreview}
              </pre>
            </div>
          )}

          {!analysis && !markdownPreview && !analyzing && selectedId && (
            <div className="bg-[var(--color-bg-card)] rounded-xl p-8 border border-[var(--color-border)] text-center">
              <p className="text-sm text-[var(--color-text-secondary)]">
                Select an action: Preview, Export, or Analyze
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
