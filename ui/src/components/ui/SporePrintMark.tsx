import { useEffect, useRef } from 'react'

interface SporePrintMarkProps {
  size?: number
  particleCount?: number
  /** Loop duration in ms — the full fall + reset cycle. */
  cycleMs?: number
}

/**
 * Slow, endless spore-drop animation — particles fall radially from the
 * center and settle into an emergent pattern, then fade and repeat.
 * The signature moment: unmistakably SporePrint. Not decorative fluff,
 * just a quiet pulse that makes the product feel alive.
 */
export default function SporePrintMark({
  size = 56,
  particleCount = 48,
  cycleMs = 9000,
}: SporePrintMarkProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = size * dpr
    canvas.height = size * dpr
    ctx.scale(dpr, dpr)

    const cx = size / 2
    const cy = size / 2
    const maxR = size * 0.42

    type Particle = {
      angle: number
      targetR: number
      phase: number
      opacity: number
    }

    const particles: Particle[] = Array.from({ length: particleCount }, (_, i) => ({
      angle: (i / particleCount) * Math.PI * 2 + Math.random() * 0.3,
      targetR: (0.25 + Math.random() * 0.75) * maxR,
      phase: Math.random(),
      opacity: 0.3 + Math.random() * 0.5,
    }))

    let start = performance.now()
    let frame = 0

    const draw = (now: number) => {
      const t = ((now - start) % cycleMs) / cycleMs
      ctx.clearRect(0, 0, size, size)

      for (const p of particles) {
        const localT = (t + p.phase) % 1
        const r = p.targetR * localT
        const x = cx + Math.cos(p.angle) * r
        const y = cy + Math.sin(p.angle) * r
        const fade = Math.sin(localT * Math.PI)
        ctx.fillStyle = `rgba(61, 214, 140, ${p.opacity * fade * 0.85})`
        ctx.beginPath()
        ctx.arc(x, y, 1.1, 0, Math.PI * 2)
        ctx.fill()
      }

      frame = requestAnimationFrame(draw)
    }

    frame = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(frame)
  }, [size, particleCount, cycleMs])

  return (
    <canvas
      ref={canvasRef}
      style={{ width: size, height: size }}
      aria-hidden
    />
  )
}
