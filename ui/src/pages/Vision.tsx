import { useEffect, useRef, useState } from 'react'
import { Camera, Brain, CheckCircle, XCircle, AlertTriangle, Eye } from 'lucide-react'
import { api } from '../api/client'
import { HEALTH_COLORS } from '../constants/colors'
import { reportFetchError } from '../stores/toastStore'

interface Frame {
  id: number
  node_id: string
  timestamp: number
  file_path: string
  resolution: string | null
  analysis_local: {
    prediction?: string
    confidence?: number
    user_label?: string
    user_confirmed?: boolean
  } | null
  analysis_claude: {
    health_assessment?: string
    summary?: string
    contamination_detected?: { type: string; description: string } | null
    harvest_readiness?: string
    recommendations?: string[]
  } | null
}

export default function Vision() {
  const [frames, setFrames] = useState<Frame[]>([])
  const [selectedFrame, setSelectedFrame] = useState<Frame | null>(null)
  const [analyzing, setAnalyzing] = useState(false)
  // Tracks the in-flight Claude analysis request so we can cancel it when
  // the user clicks a different frame (or unmounts). Without this, a slow
  // response for frame A would clobber state after the user had already
  // navigated to frame B.
  const analysisController = useRef<AbortController | null>(null)

  useEffect(() => {
    api.get<Frame[]>('/vision/frames?limit=50').then(setFrames).catch((err) =>
      reportFetchError('Vision/frames', err, "Couldn't load vision frames")
    )
    return () => {
      analysisController.current?.abort()
    }
  }, [])

  const triggerAnalysis = async (frameId: number) => {
    // Cancel any previous analysis before starting a new one.
    analysisController.current?.abort()
    const controller = new AbortController()
    analysisController.current = controller
    setAnalyzing(true)
    try {
      const result = await api.post<Record<string, unknown>>(
        `/vision/frames/${frameId}/analyze`,
        {},
        { signal: controller.signal },
      )
      if (controller.signal.aborted) return
      setFrames((prev) =>
        prev.map((f) => (f.id === frameId ? { ...f, analysis_claude: result as Frame['analysis_claude'] } : f))
      )
      if (selectedFrame?.id === frameId) {
        setSelectedFrame({ ...selectedFrame, analysis_claude: result as Frame['analysis_claude'] })
      }
    } catch (err) {
      // AbortError is expected when the user navigates away — don't noise the
      // log or pop a toast for a user-initiated cancel.
      if (controller.signal.aborted) return
      reportFetchError('Vision/analyze', err, "Analysis request failed")
    } finally {
      if (analysisController.current === controller) {
        setAnalyzing(false)
      }
    }
  }

  const labelFrame = async (frameId: number, label: string, correct: boolean) => {
    await api.post(`/vision/frames/${frameId}/label`, { label, correct })
    setFrames((prev) =>
      prev.map((f) =>
        f.id === frameId
          ? { ...f, analysis_local: { ...f.analysis_local, user_label: label, user_confirmed: correct } }
          : f
      )
    )
  }

  const healthColors = HEALTH_COLORS

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold">Vision</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">Camera feeds and analysis</p>
        </div>
        <span className="text-xs text-[var(--color-text-secondary)]">{frames.length} frames</span>
      </div>

      {selectedFrame ? (
        <div>
          <button
            onClick={() => setSelectedFrame(null)}
            className="text-sm text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] mb-4"
          >
            &larr; Back to gallery
          </button>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Frame image placeholder */}
            <div className="bg-[var(--color-bg-card)] rounded-xl border border-[var(--color-border)] p-4">
              <div className="aspect-video bg-[var(--color-bg-primary)] rounded-lg flex items-center justify-center mb-3">
                <Camera size={48} className="text-[var(--color-text-secondary)]" />
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-[var(--color-text-secondary)]">
                  {selectedFrame.node_id} &middot; {new Date(selectedFrame.timestamp * 1000).toLocaleString()}
                </span>
                <button
                  onClick={() => triggerAnalysis(selectedFrame.id)}
                  disabled={analyzing}
                  className="flex items-center gap-1 px-3 py-1 rounded-lg bg-[var(--color-accent-active)] text-white text-xs"
                >
                  <Brain size={12} />
                  {analyzing ? 'Analyzing...' : 'Claude Analysis'}
                </button>
              </div>
            </div>

            {/* Analysis results */}
            <div className="space-y-4">
              {/* Local CNN */}
              <div className="bg-[var(--color-bg-card)] rounded-xl p-4 border border-[var(--color-border)]">
                <h3 className="text-sm font-medium mb-2 flex items-center gap-2">
                  <Eye size={14} /> Local CNN
                </h3>
                {selectedFrame.analysis_local ? (
                  <div>
                    <p className="text-sm">
                      Prediction:{' '}
                      <span className="font-medium">{selectedFrame.analysis_local.prediction}</span>
                    </p>
                    <p className="text-xs text-[var(--color-text-secondary)]">
                      Confidence: {((selectedFrame.analysis_local.confidence || 0) * 100).toFixed(1)}%
                    </p>
                    {!selectedFrame.analysis_local.user_confirmed && (
                      <div className="flex gap-2 mt-2">
                        <button
                          onClick={() => labelFrame(selectedFrame.id, selectedFrame.analysis_local?.prediction || '', true)}
                          className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-green-500/10 text-green-500"
                        >
                          <CheckCircle size={12} /> Correct
                        </button>
                        <button
                          onClick={() => labelFrame(selectedFrame.id, 'trich_early', false)}
                          className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-red-500/10 text-red-500"
                        >
                          <XCircle size={12} /> Incorrect
                        </button>
                      </div>
                    )}
                    {selectedFrame.analysis_local.user_confirmed && (
                      <p className="text-xs text-[var(--color-success)] mt-1">
                        Confirmed: {selectedFrame.analysis_local.user_label}
                      </p>
                    )}
                  </div>
                ) : (
                  <p className="text-sm text-[var(--color-text-secondary)]">No local analysis</p>
                )}
              </div>

              {/* Claude Vision */}
              {selectedFrame.analysis_claude && (
                <div className="bg-[var(--color-bg-card)] rounded-xl p-4 border border-[var(--color-border)]">
                  <h3 className="text-sm font-medium mb-2 flex items-center gap-2">
                    <Brain size={14} /> Claude Vision Analysis
                  </h3>
                  {selectedFrame.analysis_claude.health_assessment && (
                    <div className="flex items-center gap-2 mb-2">
                      <div
                        className="w-3 h-3 rounded-full"
                        style={{ backgroundColor: healthColors[selectedFrame.analysis_claude.health_assessment] || healthColors.unknown }}
                      />
                      <span className="text-sm font-medium capitalize">
                        {selectedFrame.analysis_claude.health_assessment}
                      </span>
                    </div>
                  )}
                  {selectedFrame.analysis_claude.summary && (
                    <p className="text-sm mb-2">{selectedFrame.analysis_claude.summary}</p>
                  )}
                  {selectedFrame.analysis_claude.contamination_detected && (
                    <div className="flex items-start gap-2 p-2 rounded bg-red-500/10 text-sm mb-2">
                      <AlertTriangle size={14} className="text-red-500 mt-0.5 flex-shrink-0" />
                      <div>
                        <p className="font-medium text-red-400">
                          {selectedFrame.analysis_claude.contamination_detected.type}
                        </p>
                        <p className="text-xs">{selectedFrame.analysis_claude.contamination_detected.description}</p>
                      </div>
                    </div>
                  )}
                  {selectedFrame.analysis_claude.harvest_readiness && (
                    <p className="text-xs text-[var(--color-text-secondary)]">
                      Harvest: {selectedFrame.analysis_claude.harvest_readiness}
                    </p>
                  )}
                  {selectedFrame.analysis_claude.recommendations && (
                    <div className="mt-2">
                      <p className="text-xs text-[var(--color-text-secondary)] mb-1">Recommendations:</p>
                      <ul className="text-xs space-y-1">
                        {selectedFrame.analysis_claude.recommendations.map((r, i) => (
                          <li key={i} className="flex items-start gap-1">
                            <span className="text-[var(--color-accent-gourmet)]">&bull;</span> {r}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div>
          {frames.length > 0 ? (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              {frames.map((frame) => (
                <button
                  key={frame.id}
                  onClick={() => setSelectedFrame(frame)}
                  className="bg-[var(--color-bg-card)] rounded-xl border border-[var(--color-border)] overflow-hidden hover:border-[var(--color-bg-hover)] transition-colors text-left"
                >
                  <div className="aspect-video bg-[var(--color-bg-primary)] flex items-center justify-center">
                    <Camera size={24} className="text-[var(--color-text-secondary)]" />
                  </div>
                  <div className="p-2">
                    <p className="text-xs font-medium truncate">{frame.node_id}</p>
                    <p className="text-xs text-[var(--color-text-secondary)]">
                      {new Date(frame.timestamp * 1000).toLocaleString([], {
                        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
                      })}
                    </p>
                    {frame.analysis_local?.prediction && (
                      <span className={`text-xs px-1.5 py-0.5 rounded mt-1 inline-block ${
                        frame.analysis_local.prediction === 'healthy'
                          ? 'bg-green-500/10 text-green-500'
                          : 'bg-red-500/10 text-red-500'
                      }`}>
                        {frame.analysis_local.prediction}
                      </span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div className="bg-[var(--color-bg-card)] rounded-xl p-12 border border-[var(--color-border)] text-center">
              <Camera size={48} className="mx-auto mb-4 text-[var(--color-text-secondary)]" />
              <p className="text-[var(--color-text-secondary)]">No frames captured yet. Add an ESP32-CAM node to get started.</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
