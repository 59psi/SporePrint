import { useEffect, useMemo, useState } from 'react'
import { Thermometer, Droplets, Wind, Sun, CloudSun, ArrowRight } from 'lucide-react'
import SensorCard from '../components/ui/SensorCard'
import StatusPill from '../components/ui/StatusPill'
import Sparkline from '../components/ui/Sparkline'
import SporePrintMark from '../components/ui/SporePrintMark'
import NodeStatus from '../components/dashboard/NodeStatus'
import DeviceControl from '../components/dashboard/DeviceControl'
import WeatherForecast from '../components/dashboard/WeatherForecast'
import { useTelemetryStore } from '../stores/telemetryStore'
import { socket } from '../api/socket'
import { api } from '../api/client'
import { displayTemp, convertTemp, tempLabel } from '../lib/units'

const DEMO_READING = {
  timestamp: Date.now() / 1000,
  temp_f: 73.4,
  temp_c: 23.0,
  humidity: 89.2,
  co2_ppm: 620,
  lux: 340,
  dew_point_f: 69.8,
}

const DEMO_NODES = [
  { nodeId: 'climate-01', status: 'online' as const, lastSeen: Date.now() / 1000 - 30, firmwareVersion: '0.1.0' },
  { nodeId: 'relay-01', status: 'online' as const, lastSeen: Date.now() / 1000 - 45, firmwareVersion: '0.1.0' },
  { nodeId: 'light-01', status: 'offline' as const, lastSeen: Date.now() / 1000 - 3600 },
  { nodeId: 'cam-01', status: 'online' as const, lastSeen: Date.now() / 1000 - 120, firmwareVersion: '0.1.0' },
]

const DEMO_EVENTS = [
  { id: 1, type: 'phase_change', description: 'Phase advanced to fruiting', timestamp: Date.now() / 1000 - 1800 },
  { id: 2, type: 'automation', description: 'FAE fan activated (CO2 > 800ppm)', timestamp: Date.now() / 1000 - 3600 },
  { id: 3, type: 'note_added', description: 'Pins forming on east side of block', timestamp: Date.now() / 1000 - 7200 },
  { id: 4, type: 'harvest', description: 'Flush #2 harvested: 142g wet', timestamp: Date.now() / 1000 - 86400 },
]

const EVENT_TONE: Record<string, string> = {
  phase_change: 'var(--color-accent-primary)',
  automation: 'var(--color-accent-amber)',
  note_added: 'var(--color-text-tertiary)',
  harvest: 'var(--color-accent-primary)',
  alert: 'var(--color-danger)',
}

interface DeviceState {
  name: string
  type: 'fan' | 'humidifier' | 'heater' | 'cooler'
  target: string
  channel?: string
  status: 'on' | 'off'
}

function QuickControls() {
  const [devices, setDevices] = useState<DeviceState[]>([
    { name: 'FAE Fan', type: 'fan', target: 'relay-01', channel: 'fae', status: 'off' },
    { name: 'Exhaust', type: 'fan', target: 'relay-01', channel: 'exhaust', status: 'off' },
    { name: 'Circulation', type: 'fan', target: 'relay-01', channel: 'circulation', status: 'off' },
    { name: 'Humidifier', type: 'humidifier', target: 'plug-humidifier', status: 'off' },
    { name: 'Heater', type: 'heater', target: 'plug-heater', status: 'off' },
    { name: 'Cooler', type: 'cooler', target: 'plug-cooler', status: 'off' },
  ])

  const toggleDevice = async (idx: number) => {
    const dev = devices[idx]
    const newState = dev.status === 'on' ? 'off' : 'on'
    try {
      if (dev.channel) {
        await api.post(`/hardware/nodes/${dev.target}/command`, {
          topic: `sporeprint/${dev.target}/cmd/${dev.channel}`,
          state: newState,
        })
      } else {
        await api.post(`/automation/plugs/${dev.target}/command`, { state: newState })
      }
    } catch { /* optimistic */ }
    setDevices((prev) => prev.map((d, i) => (i === idx ? { ...d, status: newState } : d)))
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
      {devices.map((dev, idx) => (
        <DeviceControl
          key={dev.name}
          name={dev.name}
          type={dev.type}
          status={dev.status}
          onToggle={() => toggleDevice(idx)}
        />
      ))}
    </div>
  )
}

interface WeatherData {
  outdoor_temp_f: number
  outdoor_humidity: number
  outdoor_condition: string
  forecast_high_f: number | null
  forecast_low_f: number | null
}

function formatRelativeTime(ts: number): string {
  const diff = Date.now() / 1000 - ts
  if (diff < 60) return `${Math.floor(diff)}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

export default function Dashboard() {
  const { latest, history, setReading, addHistory } = useTelemetryStore()
  const [weather, setWeather] = useState<WeatherData | null>(null)

  useEffect(() => {
    setReading('climate-01', DEMO_READING)
    api.get<WeatherData>('/weather/current').then((w) => {
      if (w && !('status' in w)) setWeather(w)
    }).catch(() => {})

    socket.on('telemetry', (data: { node_id: string } & Record<string, number>) => {
      const { node_id, ...reading } = data
      setReading(node_id, reading as typeof DEMO_READING)
      addHistory(reading as typeof DEMO_READING)
    })
    socket.on('weather', (data: WeatherData) => setWeather(data))

    return () => {
      socket.off('telemetry')
      socket.off('weather')
    }
  }, [setReading, addHistory])

  const reading = latest['climate-01'] || DEMO_READING
  const hasRealData = history.length > 0

  const targets = {
    temp: { min: 72, max: 76 },
    humidity: { min: 85, max: 92 },
    co2: { max: 800 },
    lux: { min: 200, max: 500 },
  }

  const histories = useMemo(() => {
    const last = history.slice(-60)
    return {
      temp: last.map((r) => convertTemp(r.temp_f)),
      humidity: last.map((r) => r.humidity),
      co2: last.map((r) => r.co2_ppm),
      lux: last.map((r) => r.lux),
    }
  }, [history])

  return (
    <div className="max-w-[1400px]">
      {/* Hero — current grow status */}
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-4">
          <SporePrintMark size={56} />
          <div>
            <div className="label-caps mb-1">Current Grow</div>
            <h1 className="text-2xl font-light tracking-tight" style={{ color: 'var(--color-text-primary)' }}>
              Blue Oyster <span style={{ color: 'var(--color-text-tertiary)' }}>/</span> Block #1
            </h1>
            <div className="flex items-center gap-3 mt-1.5">
              <StatusPill label="Fruiting" tone="primary" />
              <span className="font-mono text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                <span style={{ color: 'var(--color-text-primary)' }}>Day 22</span> · Flush 2 · 284g wet
              </span>
            </div>
          </div>
        </div>
        <div className="hidden md:flex items-center gap-2">
          <div className="relative" style={{ width: 160, height: 40 }}>
            <Sparkline values={histories.temp.length ? histories.temp : [23, 23.2, 23.5, 23.3, 23.4]} width={160} height={40} />
          </div>
          <div className="label-caps">24h Temp</div>
        </div>
      </div>

      {/* Getting Started — first-run onboarding */}
      {!hasRealData && (
        <div
          className="p-6 rounded-2xl mb-8 relative overflow-hidden"
          style={{
            background: 'var(--color-bg-card)',
            border: '1px solid var(--color-border)',
            boxShadow: 'var(--shadow-glow)',
          }}
        >
          <div className="label-caps mb-2">Get started</div>
          <h2 className="text-xl font-light mb-5" style={{ color: 'var(--color-text-primary)' }}>
            Three steps to your first automated grow
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {[
              { href: '/builder', label: '01  Hardware', hint: '3 tiers from $135 — see build guides' },
              { href: '/settings', label: '02  Pi Setup', hint: 'docker compose up -d' },
              { href: '/species', label: '03  Species', hint: '55 profiles with TEK guides' },
            ].map((step) => (
              <a
                key={step.href}
                href={step.href}
                className="group p-4 rounded-xl transition-colors"
                style={{
                  background: 'var(--color-bg-hover)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-sm" style={{ color: 'var(--color-text-primary)' }}>{step.label}</span>
                  <ArrowRight size={14} style={{ color: 'var(--color-accent-primary)' }} className="opacity-60 group-hover:opacity-100 transition-opacity" />
                </div>
                <p className="text-xs mt-2" style={{ color: 'var(--color-text-secondary)' }}>{step.hint}</p>
              </a>
            ))}
          </div>
        </div>
      )}

      {/* Sensor cards */}
      <div className="mb-6">
        <div className="label-caps mb-3">Environment</div>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
          <SensorCard
            label="Temperature"
            value={convertTemp(reading.temp_f)}
            unit={tempLabel()}
            icon={<Thermometer size={14} strokeWidth={1.5} />}
            target={{ min: convertTemp(targets.temp.min), max: convertTemp(targets.temp.max) }}
            setpoint={convertTemp((targets.temp.min + targets.temp.max) / 2)}
            history={histories.temp}
          />
          <SensorCard
            label="Humidity"
            value={reading.humidity}
            unit="%"
            icon={<Droplets size={14} strokeWidth={1.5} />}
            target={{ min: targets.humidity.min, max: targets.humidity.max }}
            setpoint={(targets.humidity.min + targets.humidity.max) / 2}
            history={histories.humidity}
          />
          <SensorCard
            label="CO₂"
            value={reading.co2_ppm}
            unit="ppm"
            icon={<Wind size={14} strokeWidth={1.5} />}
            decimals={0}
            target={{ min: 0, max: targets.co2.max }}
            setpoint={targets.co2.max}
            history={histories.co2}
          />
          <SensorCard
            label="Light"
            value={reading.lux}
            unit="lux"
            icon={<Sun size={14} strokeWidth={1.5} />}
            decimals={0}
            target={{ min: targets.lux.min, max: targets.lux.max }}
            setpoint={(targets.lux.min + targets.lux.max) / 2}
            history={histories.lux}
          />
        </div>
      </div>

      <WeatherForecast />

      {/* Outdoor strip */}
      {weather && (
        <div
          className="flex items-center gap-6 px-4 py-3 rounded-xl mb-6"
          style={{
            background: 'var(--color-bg-card)',
            border: '1px solid var(--color-border)',
            boxShadow: 'var(--shadow-glow)',
          }}
        >
          <div className="flex items-center gap-2 label-caps">
            <CloudSun size={14} />
            Outdoor
          </div>
          <div className="flex gap-6 text-sm">
            <div className="font-mono">
              <span style={{ color: 'var(--color-text-tertiary)' }}>NOW </span>
              <span style={{ color: 'var(--color-text-primary)' }}>{displayTemp(weather.outdoor_temp_f)}</span>
              <span className="ml-2" style={{ color: 'var(--color-text-secondary)' }}>{weather.outdoor_humidity}% RH</span>
            </div>
            {weather.forecast_high_f != null && (
              <div className="font-mono">
                <span style={{ color: 'var(--color-text-tertiary)' }}>HIGH </span>
                <span style={{
                  color: weather.forecast_high_f > 95 ? 'var(--color-danger)'
                    : weather.forecast_high_f > 90 ? 'var(--color-accent-amber)'
                    : 'var(--color-text-primary)'
                }}>
                  {displayTemp(weather.forecast_high_f)}
                </span>
              </div>
            )}
            {weather.forecast_low_f != null && (
              <div className="font-mono">
                <span style={{ color: 'var(--color-text-tertiary)' }}>LOW </span>
                <span style={{ color: 'var(--color-text-primary)' }}>{displayTemp(weather.forecast_low_f)}</span>
              </div>
            )}
            <div style={{ color: 'var(--color-text-secondary)' }}>{weather.outdoor_condition}</div>
          </div>
        </div>
      )}

      {/* Hardware nodes + growth timeline */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 mb-6">
        <div
          className="lg:col-span-2 p-5 rounded-2xl"
          style={{
            background: 'var(--color-bg-card)',
            border: '1px solid var(--color-border)',
            boxShadow: 'var(--shadow-glow)',
          }}
        >
          <div className="label-caps mb-4">Growth Timeline</div>
          <GrowthTimeline current="fruiting" />
        </div>

        <div
          className="p-5 rounded-2xl"
          style={{
            background: 'var(--color-bg-card)',
            border: '1px solid var(--color-border)',
            boxShadow: 'var(--shadow-glow)',
          }}
        >
          <div className="label-caps mb-3">Hardware</div>
          <div style={{ borderTop: '1px solid var(--color-border)' }}>
            {DEMO_NODES.map((node) => (
              <NodeStatus key={node.nodeId} {...node} />
            ))}
          </div>
        </div>
      </div>

      {/* Quick Controls */}
      <div
        className="p-5 rounded-2xl mb-6"
        style={{
          background: 'var(--color-bg-card)',
          border: '1px solid var(--color-border)',
          boxShadow: 'var(--shadow-glow)',
        }}
      >
        <div className="label-caps mb-4">Actuators</div>
        <QuickControls />
      </div>

      {/* Recent Events — terminal-adjacent, softer */}
      <div
        className="p-5 rounded-2xl"
        style={{
          background: 'var(--color-bg-card)',
          border: '1px solid var(--color-border)',
          boxShadow: 'var(--shadow-glow)',
        }}
      >
        <div className="label-caps mb-3">Recent Events</div>
        <div>
          {DEMO_EVENTS.map((event) => (
            <div
              key={event.id}
              className="flex items-center gap-3 py-2 pl-3 font-mono text-xs"
              style={{ borderLeft: `3px solid ${EVENT_TONE[event.type] || 'var(--color-text-tertiary)'}` }}
            >
              <span style={{ color: 'var(--color-text-tertiary)', minWidth: 80 }}>
                {formatRelativeTime(event.timestamp)}
              </span>
              <span className="flex-1" style={{ color: 'var(--color-text-secondary)' }}>
                {event.description}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function GrowthTimeline({ current }: { current: string }) {
  const phases = ['inoculation', 'colonization', 'pinning', 'fruiting', 'harvest']
  const currentIdx = phases.indexOf(current)
  return (
    <div className="relative">
      <div
        className="absolute left-0 right-0 top-[11px] h-px"
        style={{ background: 'var(--color-border-raised)' }}
      />
      <div
        className="absolute left-0 top-[11px] h-px transition-all"
        style={{
          background: 'var(--color-accent-primary)',
          width: `${(currentIdx / (phases.length - 1)) * 100}%`,
          transitionDuration: 'var(--duration)',
        }}
      />
      <div className="relative flex justify-between">
        {phases.map((phase, i) => {
          const done = i < currentIdx
          const active = i === currentIdx
          return (
            <div key={phase} className="flex flex-col items-center gap-2">
              <div
                className="rounded-full"
                style={{
                  width: active ? 10 : 6,
                  height: active ? 10 : 6,
                  marginTop: active ? 8 : 10,
                  background: done || active ? 'var(--color-accent-primary)' : 'var(--color-bg-hover)',
                  border: `1px solid ${done || active ? 'var(--color-accent-primary)' : 'var(--color-border-raised)'}`,
                  boxShadow: active ? '0 0 0 4px rgba(61, 214, 140, 0.12)' : 'none',
                  animation: active ? 'sporepulse 2.4s var(--ease) infinite' : 'none',
                }}
              />
              <span
                className="label-caps"
                style={{
                  color: active ? 'var(--color-text-primary)' : done ? 'var(--color-text-secondary)' : 'var(--color-text-tertiary)',
                }}
              >
                {phase}
              </span>
            </div>
          )
        })}
      </div>
      <style>{`
        @keyframes sporepulse {
          0%, 100% { box-shadow: 0 0 0 4px rgba(61, 214, 140, 0.12); }
          50% { box-shadow: 0 0 0 7px rgba(61, 214, 140, 0.18); }
        }
      `}</style>
    </div>
  )
}
