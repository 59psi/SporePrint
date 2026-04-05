import { Power, Fan, Droplets, Thermometer, Sun } from 'lucide-react'

interface DeviceControlProps {
  name: string
  type: 'fan' | 'humidifier' | 'heater' | 'cooler' | 'light' | 'plug'
  status: 'on' | 'off'
  pwm?: number
  onToggle: () => void
}

const icons = {
  fan: Fan,
  humidifier: Droplets,
  heater: Thermometer,
  cooler: Thermometer,
  light: Sun,
  plug: Power,
}

export default function DeviceControl({ name, type, status, pwm, onToggle }: DeviceControlProps) {
  const Icon = icons[type] || Power
  const isOn = status === 'on'

  return (
    <button
      onClick={onToggle}
      className={`flex items-center gap-3 p-3 rounded-lg border transition-all ${
        isOn
          ? 'bg-[var(--color-accent-gourmet)]/10 border-[var(--color-accent-gourmet)]/30'
          : 'bg-[var(--color-bg-primary)] border-[var(--color-border)] hover:border-[var(--color-bg-hover)]'
      }`}
    >
      <div
        className={`p-2 rounded-lg ${
          isOn ? 'bg-[var(--color-accent-gourmet)]/20' : 'bg-[var(--color-bg-hover)]'
        }`}
      >
        <Icon
          size={16}
          className={isOn ? 'text-[var(--color-accent-gourmet)]' : 'text-[var(--color-text-secondary)]'}
        />
      </div>
      <div className="flex-1 text-left">
        <p className="text-sm font-medium">{name}</p>
        <p className="text-xs text-[var(--color-text-secondary)]">
          {isOn ? (pwm !== undefined ? `ON (${Math.round((pwm / 255) * 100)}%)` : 'ON') : 'OFF'}
        </p>
      </div>
      <div
        className={`w-2 h-2 rounded-full ${
          isOn ? 'bg-[var(--color-accent-gourmet)]' : 'bg-[var(--color-text-secondary)]'
        }`}
      />
    </button>
  )
}
