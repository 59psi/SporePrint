import { useEffect, useState, useRef } from 'react'
import { Bug, Upload, ChevronDown, ChevronRight, AlertTriangle, Shield } from 'lucide-react'
import { api } from '../api/client'
import { reportFetchError } from '../stores/toastStore'

interface Contaminant {
  name: string
  classification: string
  confidence: number
  action: string
  reasoning: string
}

interface IdentifyResult {
  contamination_detected: boolean
  contaminants: Contaminant[]
}

interface LibraryEntry {
  id: string
  name: string
  scientific_name: string
  danger_level: 'critical' | 'high' | 'medium' | 'low'
  appearance: string
  growth_speed: string
  smell: string
  stages: string[]
  action: string
  prevention: string
}

const DANGER_BORDER: Record<string, string> = {
  critical: 'border-red-500',
  high: 'border-orange-500',
  medium: 'border-yellow-500',
  low: 'border-[var(--color-border)]',
}

const DANGER_TEXT: Record<string, string> = {
  critical: 'text-red-400',
  high: 'text-orange-400',
  medium: 'text-yellow-400',
  low: 'text-[var(--color-text-secondary)]',
}

export default function ContaminationGuide() {
  const [library, setLibrary] = useState<LibraryEntry[]>([])
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [identifyResult, setIdentifyResult] = useState<IdentifyResult | null>(null)
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api.get<LibraryEntry[]>('/contamination/library').then(setLibrary).catch((err) =>
      reportFetchError('Contamination/library', err, "Couldn't load contamination library")
    )
  }, [])

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setIdentifyResult(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await fetch('/api/contamination/identify', {
        method: 'POST',
        body: formData,
      })
      if (!res.ok) throw new Error('Upload failed')
      const data: IdentifyResult = await res.json()
      setIdentifyResult(data)
    } catch {
      // ignore
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold">Contamination Guide</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">Identify and prevent contamination</p>
        </div>
      </div>

      {/* Upload section */}
      <div className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)] mb-6">
        <h2 className="font-medium mb-3 flex items-center gap-2">
          <Upload size={16} />
          Upload Image for Identification
        </h2>
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          onChange={handleUpload}
          className="hidden"
        />
        <button
          onClick={() => fileRef.current?.click()}
          disabled={uploading}
          className="px-4 py-2 rounded-lg bg-[var(--color-accent-gourmet)] text-white text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
        >
          {uploading ? 'Analyzing...' : 'Choose Image'}
        </button>

        {identifyResult && (
          <div className="mt-4">
            {identifyResult.contamination_detected ? (
              <div>
                <div className="flex items-center gap-2 text-red-400 mb-3">
                  <AlertTriangle size={16} />
                  <span className="font-medium text-sm">Contamination Detected</span>
                </div>
                <div className="space-y-2">
                  {identifyResult.contaminants.map((c, i) => (
                    <div
                      key={i}
                      className="bg-[var(--color-bg)] rounded-lg p-3 border border-[var(--color-border)]"
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-medium text-sm">{c.classification}</span>
                        <span className="text-xs text-[var(--color-text-secondary)]">
                          {Math.round(c.confidence * 100)}% confidence
                        </span>
                      </div>
                      <p className="text-xs text-[var(--color-text-secondary)] mb-1">{c.reasoning}</p>
                      <p className="text-xs text-amber-400">Action: {c.action}</p>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-2 text-green-400">
                <Shield size={16} />
                <span className="font-medium text-sm">No contamination detected</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Library */}
      <div>
        <h2 className="text-sm font-medium text-[var(--color-text-secondary)] mb-3 uppercase tracking-wider">
          Contamination Library
        </h2>
        {library.length > 0 ? (
          <div className="space-y-2">
            {library.map((entry) => {
              const expanded = expandedId === entry.id
              return (
                <div
                  key={entry.id}
                  className={`bg-[var(--color-bg-card)] rounded-xl border-l-4 border ${DANGER_BORDER[entry.danger_level]} border-r-[var(--color-border)] border-t-[var(--color-border)] border-b-[var(--color-border)]`}
                >
                  <button
                    onClick={() => setExpandedId(expanded ? null : entry.id)}
                    className="w-full flex items-center justify-between p-4 text-left"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-sm">{entry.name}</span>
                        <span className={`text-xs uppercase font-medium ${DANGER_TEXT[entry.danger_level]}`}>
                          {entry.danger_level}
                        </span>
                      </div>
                      <p className="text-xs text-[var(--color-text-secondary)] italic">{entry.scientific_name}</p>
                    </div>
                    {expanded ? (
                      <ChevronDown size={16} className="text-[var(--color-text-secondary)]" />
                    ) : (
                      <ChevronRight size={16} className="text-[var(--color-text-secondary)]" />
                    )}
                  </button>

                  {expanded && (
                    <div className="px-4 pb-4 space-y-3 text-sm">
                      <div>
                        <span className="text-xs text-[var(--color-text-secondary)] uppercase">Appearance</span>
                        <p>{entry.appearance}</p>
                      </div>
                      <div>
                        <span className="text-xs text-[var(--color-text-secondary)] uppercase">Growth Speed</span>
                        <p>{entry.growth_speed}</p>
                      </div>
                      <div>
                        <span className="text-xs text-[var(--color-text-secondary)] uppercase">Smell</span>
                        <p>{entry.smell}</p>
                      </div>
                      <div>
                        <span className="text-xs text-[var(--color-text-secondary)] uppercase">Stages</span>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {entry.stages.map((s, i) => (
                            <span
                              key={i}
                              className="px-2 py-0.5 rounded-full text-xs bg-[var(--color-bg-hover)] text-[var(--color-text-secondary)]"
                            >
                              {s}
                            </span>
                          ))}
                        </div>
                      </div>
                      <div>
                        <span className="text-xs text-amber-400 uppercase">Action</span>
                        <p>{entry.action}</p>
                      </div>
                      <div>
                        <span className="text-xs text-green-400 uppercase">Prevention</span>
                        <p>{entry.prevention}</p>
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        ) : (
          <div className="bg-[var(--color-bg-card)] rounded-xl p-12 border border-[var(--color-border)] text-center">
            <Bug size={48} className="mx-auto mb-4 text-[var(--color-text-secondary)]" />
            <p className="text-[var(--color-text-secondary)]">Loading contamination library...</p>
          </div>
        )}
      </div>
    </div>
  )
}
