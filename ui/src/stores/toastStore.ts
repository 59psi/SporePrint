import { create } from 'zustand'

export type ToastKind = 'error' | 'warning' | 'info' | 'success'

export interface Toast {
  id: number
  kind: ToastKind
  message: string
}

interface ToastState {
  toasts: Toast[]
  push: (kind: ToastKind, message: string) => void
  dismiss: (id: number) => void
}

let nextId = 1

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  push: (kind, message) => {
    const id = nextId++
    set((s) => ({ toasts: [...s.toasts, { id, kind, message }] }))
    // Auto-dismiss errors after 6s, others after 4s. Give the user long
    // enough to read "Couldn't load sessions" but don't let the stack grow.
    const ttl = kind === 'error' ? 6000 : 4000
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }))
    }, ttl)
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))

// Convenience wrapper used by the .catch sweep. Logs to console with context
// AND surfaces a toast — failures should be audible in both the dev console
// and the user-facing UI.
export function reportFetchError(context: string, err: unknown, userMessage: string): void {
  // Constant format string — context passed as a separate arg to avoid
  // format-string injection warnings.
  // eslint-disable-next-line no-console
  console.error('[%s]', context, err)
  useToastStore.getState().push('error', userMessage)
}
