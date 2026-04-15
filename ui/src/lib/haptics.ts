/**
 * Haptic feedback utility — wraps @capacitor/haptics via dynamic import.
 * No-op on web or when Capacitor is not available. Safe to call anywhere.
 *
 * Uses string-variable dynamic imports so the submodule compiles without
 * @capacitor/* type declarations in its own package.json.
 */

type HapticStyle = 'light' | 'medium' | 'heavy'

/* Opaque module specifiers — TypeScript won't attempt module resolution */
const CAP_CORE = '@capacitor/core'
const CAP_HAPTICS = '@capacitor/haptics'

export async function haptic(style: HapticStyle = 'medium'): Promise<void> {
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const core: any = await import(/* @vite-ignore */ CAP_CORE)
    if (!core.Capacitor?.isNativePlatform()) return

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const hapticsModule: any = await import(/* @vite-ignore */ CAP_HAPTICS)
    const { Haptics, ImpactStyle } = hapticsModule

    switch (style) {
      case 'light':
        return Haptics.impact({ style: ImpactStyle.Light })
      case 'medium':
        return Haptics.impact({ style: ImpactStyle.Medium })
      case 'heavy':
        return Haptics.impact({ style: ImpactStyle.Heavy })
    }
  } catch {
    // Capacitor not available (pure web / submodule dev context) — silently ignore
  }
}
