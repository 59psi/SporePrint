import { useToastStore, type ToastKind } from '../../stores/toastStore'

// Mount once at the top of the app. Reads from the toast store and renders
// a stacked notification column in the top-right. No portals — relies on the
// host layout having `position: relative` / normal flow and sufficient
// z-index in the design system.

const KIND_STYLES: Record<ToastKind, { border: string; dot: string }> = {
  error: { border: 'rgba(217, 92, 65, 0.35)', dot: 'var(--color-danger, #d95c41)' },
  warning: { border: 'rgba(217, 164, 65, 0.35)', dot: 'var(--color-warn, #d9a441)' },
  info: { border: 'rgba(255, 255, 255, 0.1)', dot: 'var(--color-text-muted, #888)' },
  success: { border: 'rgba(61, 214, 140, 0.35)', dot: 'var(--color-accent, #3dd68c)' },
}

export function Toaster() {
  const toasts = useToastStore((s) => s.toasts)
  const dismiss = useToastStore((s) => s.dismiss)

  if (toasts.length === 0) return null

  return (
    <div
      style={{
        position: 'fixed',
        top: 16,
        right: 16,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        zIndex: 9999,
        pointerEvents: 'none',
      }}
    >
      {toasts.map((t) => {
        const s = KIND_STYLES[t.kind]
        return (
          <div
            key={t.id}
            role="status"
            onClick={() => dismiss(t.id)}
            style={{
              pointerEvents: 'auto',
              cursor: 'pointer',
              padding: '10px 14px',
              borderRadius: 12,
              background: 'var(--color-surface, #141411)',
              border: `1px solid ${s.border}`,
              boxShadow: '0 4px 16px rgba(0,0,0,0.35)',
              color: 'var(--color-text, #e8e4db)',
              fontSize: 13,
              maxWidth: 380,
              display: 'flex',
              alignItems: 'flex-start',
              gap: 10,
            }}
          >
            <span
              aria-hidden
              style={{
                display: 'inline-block',
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: s.dot,
                marginTop: 5,
                flexShrink: 0,
              }}
            />
            <span>{t.message}</span>
          </div>
        )
      })}
    </div>
  )
}
