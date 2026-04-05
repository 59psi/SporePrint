interface SensorGaugeProps {
  label: string
  value: number | null
  unit: string
  min: number
  max: number
  targetMin?: number
  targetMax?: number
  decimals?: number
  icon?: React.ReactNode
}

export default function SensorGauge({
  label,
  value,
  unit,
  min,
  max,
  targetMin,
  targetMax,
  decimals = 1,
  icon,
}: SensorGaugeProps) {
  const range = max - min
  const pct = value !== null ? Math.max(0, Math.min(100, ((value - min) / range) * 100)) : 0
  const targetMinPct = targetMin !== undefined ? ((targetMin - min) / range) * 100 : 0
  const targetMaxPct = targetMax !== undefined ? ((targetMax - min) / range) * 100 : 100

  let status: 'ok' | 'warn' | 'danger' = 'ok'
  if (value !== null && targetMin !== undefined && targetMax !== undefined) {
    if (value < targetMin || value > targetMax) {
      const margin = (targetMax - targetMin) * 0.15
      if (value < targetMin - margin || value > targetMax + margin) {
        status = 'danger'
      } else {
        status = 'warn'
      }
    }
  }

  const statusColor = {
    ok: 'var(--color-success)',
    warn: 'var(--color-warning)',
    danger: 'var(--color-danger)',
  }[status]

  return (
    <div className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)]">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 text-sm text-[var(--color-text-secondary)]">
          {icon}
          {label}
        </div>
        <div
          className="w-2 h-2 rounded-full"
          style={{ backgroundColor: statusColor }}
        />
      </div>

      <div className="text-3xl font-semibold mb-1" style={{ color: statusColor }}>
        {value !== null ? value.toFixed(decimals) : '--'}
        <span className="text-base font-normal text-[var(--color-text-secondary)] ml-1">
          {unit}
        </span>
      </div>

      {/* Bar gauge */}
      <div className="mt-3 relative h-2 bg-[var(--color-bg-primary)] rounded-full overflow-hidden">
        {/* Target range */}
        {targetMin !== undefined && targetMax !== undefined && (
          <div
            className="absolute h-full opacity-20 rounded-full"
            style={{
              left: `${targetMinPct}%`,
              width: `${targetMaxPct - targetMinPct}%`,
              backgroundColor: 'var(--color-success)',
            }}
          />
        )}
        {/* Current value indicator */}
        <div
          className="absolute h-full w-1.5 rounded-full transition-all duration-500"
          style={{
            left: `${Math.max(0, pct - 0.5)}%`,
            backgroundColor: statusColor,
          }}
        />
      </div>

      <div className="flex justify-between mt-1 text-xs text-[var(--color-text-secondary)]">
        <span>{min}{unit}</span>
        {targetMin !== undefined && targetMax !== undefined && (
          <span className="text-[var(--color-success)]">
            {targetMin}-{targetMax}
          </span>
        )}
        <span>{max}{unit}</span>
      </div>
    </div>
  )
}
