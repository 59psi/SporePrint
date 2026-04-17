import { useMemo } from 'react'

interface SparklineProps {
  values: number[]
  width?: number
  height?: number
  stroke?: string
  fill?: boolean
  min?: number
  max?: number
}

/**
 * Thin, quiet sparkline — no axes, no grid, no legend. Just a pulse.
 * 1.5px stroke at 70% opacity. Optional soft vertical gradient fill.
 */
export default function Sparkline({
  values,
  width = 120,
  height = 32,
  stroke = 'var(--color-accent-primary)',
  fill = true,
  min,
  max,
}: SparklineProps) {
  const { path, areaPath, gradientId } = useMemo(() => {
    const id = `sparkgrad-${Math.random().toString(36).slice(2, 8)}`
    if (!values || values.length < 2) {
      return { path: '', areaPath: '', gradientId: id }
    }
    const lo = min ?? Math.min(...values)
    const hi = max ?? Math.max(...values)
    const range = hi - lo || 1
    const stepX = width / (values.length - 1)
    const pad = 2

    const pts = values.map((v, i) => {
      const x = i * stepX
      const y = height - pad - ((v - lo) / range) * (height - pad * 2)
      return [x, y] as const
    })
    const line = pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
    const area = `${line} L${width},${height} L0,${height} Z`
    return { path: line, areaPath: area, gradientId: id }
  }, [values, width, height, min, max])

  if (!path) {
    return (
      <svg width={width} height={height} aria-hidden>
        <line
          x1={0}
          x2={width}
          y1={height / 2}
          y2={height / 2}
          stroke="var(--color-border)"
          strokeWidth={1}
          strokeDasharray="2 3"
        />
      </svg>
    )
  }

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden>
      {fill && (
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity="0.3" />
            <stop offset="100%" stopColor={stroke} stopOpacity="0" />
          </linearGradient>
        </defs>
      )}
      {fill && <path d={areaPath} fill={`url(#${gradientId})`} />}
      <path d={path} fill="none" stroke={stroke} strokeWidth="1.5" strokeOpacity="0.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
