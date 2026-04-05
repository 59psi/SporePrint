import { useEffect, useState } from 'react'
import { CloudSun, AlertTriangle, CheckCircle, Loader2, Brain } from 'lucide-react'
import { api } from '../../api/client'

interface DaySummary {
  date: string
  day_name: string
  high_f: number
  low_f: number
  avg_humidity: number
  condition: string
}

interface Impact {
  type: 'danger' | 'warning' | 'good' | 'info'
  day: string
  message: string
}

interface ModelStatus {
  status: 'learning' | 'active'
  days_collected?: number
  days_needed?: number
  temp_model?: { r_squared: number; training_days: number }
}

interface ImpactData {
  forecast: DaySummary[]
  impacts: Impact[]
  model_status: ModelStatus
}

export default function WeatherForecast() {
  const [data, setData] = useState<ImpactData | null>(null)

  useEffect(() => {
    api.get<ImpactData>('/weather/impact').then((d) => {
      if (d && d.forecast) setData(d)
    }).catch(() => {})

    const interval = setInterval(() => {
      api.get<ImpactData>('/weather/impact').then((d) => {
        if (d && d.forecast) setData(d)
      }).catch(() => {})
    }, 600_000) // refresh every 10 min
    return () => clearInterval(interval)
  }, [])

  if (!data || data.forecast.length === 0) return null

  const conditionIcon = (c: string) => {
    if (/clear|sunny/i.test(c)) return '☀️'
    if (/partly|few/i.test(c)) return '⛅'
    if (/cloud|overcast/i.test(c)) return '☁️'
    if (/rain|shower|drizzle/i.test(c)) return '🌧️'
    if (/thunder/i.test(c)) return '⛈️'
    if (/snow/i.test(c)) return '🌨️'
    if (/fog/i.test(c)) return '🌫️'
    return '🌤️'
  }

  return (
    <div className="bg-[var(--color-bg-card)] rounded-xl border border-[var(--color-border)] p-5 mb-6">
      <div className="flex items-center gap-2 mb-4">
        <CloudSun size={16} className="text-[var(--color-text-secondary)]" />
        <h2 className="text-sm font-semibold">7-Day Forecast</h2>
        {data.model_status.status === 'active' && (
          <div className="flex items-center gap-1 ml-auto text-xs text-[var(--color-accent-gourmet)]">
            <Brain size={12} />
            Predictive
          </div>
        )}
        {data.model_status.status === 'learning' && (
          <div className="flex items-center gap-1 ml-auto text-xs text-[var(--color-text-secondary)]">
            <Loader2 size={12} className="animate-spin" />
            Learning ({data.model_status.days_collected}/{data.model_status.days_needed} days)
          </div>
        )}
      </div>

      {/* Day cards */}
      <div className="flex gap-2 overflow-x-auto pb-2 mb-4">
        {data.forecast.map((day, i) => {
          const hasImpact = data.impacts.some((imp) => imp.day === day.day_name && imp.type !== 'good')
          return (
            <div
              key={day.date}
              className={`flex-shrink-0 w-24 p-3 rounded-lg border text-center text-xs ${
                hasImpact
                  ? 'border-[var(--color-warning)]/30 bg-[var(--color-warning)]/5'
                  : 'border-[var(--color-border)] bg-[var(--color-bg-primary)]'
              }`}
            >
              <p className="font-medium mb-1">{i === 0 ? 'Today' : day.day_name}</p>
              <p className="text-lg mb-1">{conditionIcon(day.condition)}</p>
              <p>
                <span className="font-medium">{Math.round(day.high_f)}°</span>
                <span className="text-[var(--color-text-secondary)]"> / {Math.round(day.low_f)}°</span>
              </p>
              <p className="text-[var(--color-text-secondary)]">{Math.round(day.avg_humidity)}% RH</p>
            </div>
          )
        })}
      </div>

      {/* Impact analysis */}
      {data.impacts.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-[var(--color-text-secondary)] uppercase tracking-wider">
            Grow Impact
          </p>
          {data.impacts.map((impact, i) => (
            <div
              key={i}
              className={`flex items-start gap-2 text-xs p-2 rounded-lg ${
                impact.type === 'danger'
                  ? 'bg-red-500/10 text-red-400'
                  : impact.type === 'warning'
                  ? 'bg-amber-500/10 text-amber-400'
                  : 'bg-green-500/10 text-green-400'
              }`}
            >
              {impact.type === 'good' ? (
                <CheckCircle size={14} className="flex-shrink-0 mt-0.5" />
              ) : (
                <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
              )}
              <span>{impact.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
