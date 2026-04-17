type Tone = 'primary' | 'amber' | 'danger' | 'muted'

interface StatusPillProps {
  label: string
  tone?: Tone
}

const toneMap: Record<Tone, { color: string; bg: string; border: string }> = {
  primary: {
    color: 'var(--color-accent-primary)',
    bg: 'rgba(61, 214, 140, 0.08)',
    border: 'rgba(61, 214, 140, 0.25)',
  },
  amber: {
    color: 'var(--color-accent-amber)',
    bg: 'rgba(217, 164, 65, 0.08)',
    border: 'rgba(217, 164, 65, 0.25)',
  },
  danger: {
    color: 'var(--color-danger)',
    bg: 'rgba(217, 92, 65, 0.08)',
    border: 'rgba(217, 92, 65, 0.30)',
  },
  muted: {
    color: 'var(--color-text-secondary)',
    bg: 'rgba(255, 255, 255, 0.04)',
    border: 'rgba(255, 255, 255, 0.08)',
  },
}

/**
 * Instrument-grade status indicator — colored 6px dot + 11px all-caps label.
 * Uses explicit tones rather than string semantics so callers are explicit
 * about intent (primary = healthy/active, amber = attention, danger = fault).
 */
export default function StatusPill({ label, tone = 'primary' }: StatusPillProps) {
  const { color, bg, border } = toneMap[tone]
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full"
      style={{
        backgroundColor: bg,
        border: `1px solid ${border}`,
        color,
        fontSize: 11,
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
        fontWeight: 500,
        lineHeight: 1,
      }}
    >
      <span
        className="rounded-full"
        style={{ width: 6, height: 6, backgroundColor: color, flexShrink: 0 }}
      />
      {label}
    </span>
  )
}
