import { useEffect, useState } from 'react'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ReferenceArea,
} from 'recharts'
import { api } from '../../api/client'

interface Props {
  nodeId: string
  sensor: string
  label: string
  unit: string
  color: string
  targetMin?: number
  targetMax?: number
  fromTs?: number
  toTs?: number
  rangeSeconds?: number
  resolution?: string
}

interface DataPoint {
  timestamp: number
  value: number
}

export default function TelemetryChart({
  nodeId,
  sensor,
  label,
  unit,
  color,
  targetMin,
  targetMax,
  fromTs,
  toTs,
  rangeSeconds,
  resolution,
}: Props) {
  const [data, setData] = useState<DataPoint[]>([])

  useEffect(() => {
    const params = new URLSearchParams({ node_id: nodeId, sensor })
    const effectiveFromTs = fromTs ?? (rangeSeconds ? Date.now() / 1000 - rangeSeconds : undefined)
    if (effectiveFromTs) params.set('from_ts', String(effectiveFromTs))
    if (toTs) params.set('to_ts', String(toTs))
    if (resolution) params.set('resolution', resolution)

    api
      .get<DataPoint[]>(`/telemetry/history?${params}`)
      .then(setData)
      .catch(() => {})
  }, [nodeId, sensor, fromTs, toTs, rangeSeconds, resolution])

  const formatTime = (ts: number) => {
    const d = new Date(ts * 1000)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }

  return (
    <div className="bg-[var(--color-bg-card)] rounded-xl p-4 border border-[var(--color-border)]">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium">{label}</h3>
        <span className="text-xs text-[var(--color-text-secondary)]">{unit}</span>
      </div>

      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
          <XAxis
            dataKey="timestamp"
            tickFormatter={formatTime}
            stroke="var(--color-text-secondary)"
            fontSize={10}
          />
          <YAxis stroke="var(--color-text-secondary)" fontSize={10} />
          <Tooltip
            contentStyle={{
              backgroundColor: 'var(--color-bg-card)',
              border: '1px solid var(--color-border)',
              borderRadius: '8px',
              fontSize: '12px',
            }}
            labelFormatter={(v) => formatTime(Number(v))}
            formatter={(value) => [`${Number(value).toFixed(1)} ${unit}`, label]}
          />

          {targetMin !== undefined && targetMax !== undefined && (
            <ReferenceArea
              y1={targetMin}
              y2={targetMax}
              fill="var(--color-accent-gourmet)"
              fillOpacity={0.05}
            />
          )}
          {targetMin !== undefined && (
            <ReferenceLine y={targetMin} stroke="var(--color-accent-gourmet)" strokeDasharray="3 3" strokeOpacity={0.5} />
          )}
          {targetMax !== undefined && (
            <ReferenceLine y={targetMax} stroke="var(--color-accent-gourmet)" strokeDasharray="3 3" strokeOpacity={0.5} />
          )}

          <Line
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 3 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
