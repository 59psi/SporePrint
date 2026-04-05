import { useEffect, useState } from 'react'
import { Thermometer, Droplets, Wind, Sun, Activity, CloudSun } from 'lucide-react'
import SensorGauge from '../components/dashboard/SensorGauge'
import NodeStatus from '../components/dashboard/NodeStatus'
import DeviceControl from '../components/dashboard/DeviceControl'
import { useTelemetryStore } from '../stores/telemetryStore'
import { socket } from '../api/socket'
import { api } from '../api/client'

// Demo data for when no real telemetry is connected
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
    } catch { /* still update UI optimistically */ }

    setDevices((prev) =>
      prev.map((d, i) => (i === idx ? { ...d, status: newState } : d))
    )
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

export default function Dashboard() {
  const { latest, setReading, addHistory } = useTelemetryStore()
  const [weather, setWeather] = useState<WeatherData | null>(null)

  useEffect(() => {
    // Set demo data as initial
    setReading('climate-01', DEMO_READING)

    // Fetch initial weather
    api.get<WeatherData>('/weather/current').then((w) => {
      if (w && !('status' in w)) setWeather(w)
    }).catch(() => {})

    socket.on('telemetry', (data: { node_id: string } & Record<string, number>) => {
      const { node_id, ...reading } = data
      setReading(node_id, reading as typeof DEMO_READING)
      addHistory(reading as typeof DEMO_READING)
    })

    socket.on('weather', (data: WeatherData) => {
      setWeather(data)
    })

    return () => {
      socket.off('telemetry')
      socket.off('weather')
    }
  }, [setReading, addHistory])

  const reading = latest['climate-01'] || DEMO_READING

  // Default targets (Golden Teacher fruiting phase)
  const targets = {
    temp: { min: 72, max: 76 },
    humidity: { min: 85, max: 92 },
    co2: { max: 800 },
    lux: { min: 200, max: 500 },
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold">Dashboard</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">Real-time grow environment</p>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[var(--color-accent-active)]/10 text-[var(--color-accent-active)] text-sm">
          <Activity size={14} />
          Live
        </div>
      </div>

      {/* Sensor Gauges */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
        <SensorGauge
          label="Temperature"
          value={reading.temp_f}
          unit="\u00b0F"
          min={40}
          max={100}
          targetMin={targets.temp.min}
          targetMax={targets.temp.max}
          icon={<Thermometer size={14} />}
        />
        <SensorGauge
          label="Humidity"
          value={reading.humidity}
          unit="%"
          min={0}
          max={100}
          targetMin={targets.humidity.min}
          targetMax={targets.humidity.max}
          icon={<Droplets size={14} />}
        />
        <SensorGauge
          label="CO2"
          value={reading.co2_ppm}
          unit="ppm"
          min={0}
          max={5000}
          targetMin={0}
          targetMax={targets.co2.max}
          decimals={0}
          icon={<Wind size={14} />}
        />
        <SensorGauge
          label="Light"
          value={reading.lux}
          unit="lux"
          min={0}
          max={2000}
          targetMin={targets.lux.min}
          targetMax={targets.lux.max}
          decimals={0}
          icon={<Sun size={14} />}
        />
      </div>

      {/* Weather Widget */}
      {weather && (
        <div className="bg-[var(--color-bg-card)] rounded-xl p-4 border border-[var(--color-border)] mb-6">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2 text-sm text-[var(--color-text-secondary)]">
              <CloudSun size={16} />
              Outdoor
            </div>
            <div className="flex gap-6 text-sm">
              <div>
                <span className="text-[var(--color-text-secondary)]">Now </span>
                <span className="font-medium">{weather.outdoor_temp_f}°F</span>
                <span className="text-[var(--color-text-secondary)] ml-1">{weather.outdoor_humidity}% RH</span>
              </div>
              {weather.forecast_high_f != null && (
                <div>
                  <span className="text-[var(--color-text-secondary)]">High </span>
                  <span className={`font-medium ${weather.forecast_high_f > 90 ? 'text-[var(--color-warning)]' : weather.forecast_high_f > 95 ? 'text-[var(--color-danger)]' : ''}`}>
                    {weather.forecast_high_f}°F
                  </span>
                </div>
              )}
              {weather.forecast_low_f != null && (
                <div>
                  <span className="text-[var(--color-text-secondary)]">Low </span>
                  <span className="font-medium">{weather.forecast_low_f}°F</span>
                </div>
              )}
              <div className="text-[var(--color-text-secondary)]">{weather.outdoor_condition}</div>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Active Session Card */}
        <div className="lg:col-span-2 bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)]">
          <h2 className="text-base font-semibold mb-4">Active Session</h2>
          <div className="flex items-start gap-4">
            <div className="flex-1">
              <p className="text-lg font-medium">Golden Teacher — Tub #1</p>
              <p className="text-sm text-[var(--color-text-secondary)] mt-0.5">
                <span className="text-[var(--color-accent-active)]">Active</span> &middot; CVG substrate
              </p>

              <div className="mt-4 space-y-3">
                <div>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-[var(--color-text-secondary)]">Current Phase</span>
                    <span className="font-medium">Fruiting</span>
                  </div>
                  <div className="h-2 bg-[var(--color-bg-primary)] rounded-full overflow-hidden">
                    <div className="h-full bg-[var(--color-accent-active)] rounded-full" style={{ width: '65%' }} />
                  </div>
                </div>
                <div className="flex gap-6 text-sm">
                  <div>
                    <span className="text-[var(--color-text-secondary)]">Days in Phase</span>
                    <p className="font-medium">8 / 14</p>
                  </div>
                  <div>
                    <span className="text-[var(--color-text-secondary)]">Flush</span>
                    <p className="font-medium">#2</p>
                  </div>
                  <div>
                    <span className="text-[var(--color-text-secondary)]">Total Yield</span>
                    <p className="font-medium">284g wet</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Node Health */}
        <div className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)]">
          <h2 className="text-base font-semibold mb-3">Hardware Nodes</h2>
          <div className="divide-y divide-[var(--color-border)]">
            {DEMO_NODES.map((node) => (
              <NodeStatus key={node.nodeId} {...node} />
            ))}
          </div>
        </div>

        {/* Quick Controls */}
        <div className="lg:col-span-3 bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)]">
          <h2 className="text-base font-semibold mb-3">Quick Controls</h2>
          <QuickControls />
        </div>

        {/* Recent Events */}
        <div className="lg:col-span-3 bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)]">
          <h2 className="text-base font-semibold mb-3">Recent Events</h2>
          <div className="space-y-2">
            {DEMO_EVENTS.map((event) => (
              <div
                key={event.id}
                className="flex items-center gap-3 py-2 px-3 rounded-lg hover:bg-[var(--color-bg-hover)] transition-colors"
              >
                <div className="w-1.5 h-1.5 rounded-full bg-[var(--color-accent-gourmet)]" />
                <span className="flex-1 text-sm">{event.description}</span>
                <span className="text-xs text-[var(--color-text-secondary)]">
                  {new Date(event.timestamp * 1000).toLocaleTimeString([], {
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
