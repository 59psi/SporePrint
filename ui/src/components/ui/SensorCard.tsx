import type { ReactNode } from 'react'
import Sparkline from './Sparkline'

type Range = { min?: number; max?: number }

interface SensorCardProps {
  label: string
  value: number | null
  unit: string
  icon?: ReactNode
  decimals?: number
  target?: Range
  history?: number[]
  setpoint?: number
}

function stateFor(value: number | null, target?: Range): 'ok' | 'warn' | 'danger' {
  if (value === null || !target || target.min === undefined || target.max === undefined) return 'ok'
  if (value < target.min || value > target.max) {
    const margin = (target.max - target.min) * 0.15
    if (value < target.min - margin || value > target.max + margin) return 'danger'
    return 'warn'
  }
  return 'ok'
}

/**
 * Premium sensor readout: icon + label (top), big mono value, tiny unit,
 * sparkline below, and delta-from-setpoint chip. Out-of-range conditions
 * shift the border from 4% white to amber — subtle but immediately readable.
 */
export default function SensorCard({
  label,
  value,
  unit,
  icon,
  decimals = 1,
  target,
  history,
  setpoint,
}: SensorCardProps) {
  const state = stateFor(value, target)
  const borderColor =
    state === 'danger' ? 'rgba(217, 92, 65, 0.40)'
    : state === 'warn' ? 'rgba(217, 164, 65, 0.40)'
    : 'var(--color-border)'
  const sparkColor =
    state === 'danger' ? 'var(--color-danger)'
    : state === 'warn' ? 'var(--color-accent-amber)'
    : 'var(--color-accent-primary)'

  const delta = value !== null && setpoint !== undefined ? value - setpoint : null
  const deltaSign = delta !== null ? (delta > 0 ? '+' : '') : ''

  return (
    <div
      className="relative p-5 rounded-2xl transition-colors"
      style={{
        background: 'var(--color-bg-card)',
        border: `1px solid ${borderColor}`,
        boxShadow: 'var(--shadow-glow)',
        transitionDuration: 'var(--duration)',
        transitionTimingFunction: 'var(--ease)',
      }}
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span style={{ color: 'var(--color-text-tertiary)' }} className="flex items-center">
            {icon}
          </span>
          <span className="label-caps">{label}</span>
        </div>
        {delta !== null && (
          <span
            className="font-mono px-1.5 py-0.5 rounded"
            style={{
              fontSize: 10,
              color: state === 'ok' ? 'var(--color-text-secondary)' : sparkColor,
              background: state === 'ok' ? 'rgba(255,255,255,0.04)' : `${sparkColor}15`,
            }}
          >
            {deltaSign}{delta.toFixed(decimals)}
          </span>
        )}
      </div>

      <div className="flex items-baseline gap-1.5 mb-3">
        <span
          className="font-mono"
          style={{
            fontSize: 36,
            fontWeight: 300,
            lineHeight: 1,
            color: state === 'ok' ? 'var(--color-text-primary)' : sparkColor,
            letterSpacing: '-0.02em',
          }}
        >
          {value !== null ? value.toFixed(decimals) : '—'}
        </span>
        <span className="label-caps" style={{ color: 'var(--color-text-secondary)' }}>{unit}</span>
      </div>

      <div className="h-8 -mx-1">
        <Sparkline
          values={history || []}
          width={220}
          height={32}
          stroke={sparkColor}
        />
      </div>

      {target?.min !== undefined && target?.max !== undefined && (
        <div className="flex justify-between mt-2 font-mono" style={{ fontSize: 10, color: 'var(--color-text-tertiary)' }}>
          <span>target</span>
          <span>{target.min}–{target.max}{unit}</span>
        </div>
      )}
    </div>
  )
}
