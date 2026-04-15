import { useEffect, useState } from 'react'
import { Wifi, WifiOff, Plug, Database, RefreshCw, Smartphone, Copy, Check, Thermometer, Scale } from 'lucide-react'
import { api } from '../api/client'
import { getTempUnit, getWeightUnit } from '../lib/units'
import { haptic } from '../lib/haptics'

interface HardwareNode {
  node_id: string
  node_type: string
  firmware_version: string | null
  last_seen: number | null
  ip_address: string | null
  status: string
}

interface SmartPlug {
  plug_id: string
  name: string
  plug_type: string
  device_role: string | null
  last_state: string | null
  last_power_w: number | null
  last_seen: number | null
}

function PairingCodeSection() {
  const [code, setCode] = useState<string | null>(null)
  const [expiresIn, setExpiresIn] = useState(0)
  const [generating, setGenerating] = useState(false)
  const [copied, setCopied] = useState(false)

  const generateCode = async () => {
    setGenerating(true)
    try {
      const data = await api.post<{ code: string; expires_in: number }>('/cloud/pairing-code', {})
      setCode(data.code)
      setExpiresIn(data.expires_in)
    } catch { /* ignore */ }
    setGenerating(false)
  }

  const copyCode = () => {
    if (code) {
      navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  // Countdown timer
  useEffect(() => {
    if (expiresIn <= 0) return
    const interval = setInterval(() => {
      setExpiresIn((prev) => {
        if (prev <= 1) { setCode(null); return 0 }
        return prev - 1
      })
    }, 1000)
    return () => clearInterval(interval)
  }, [expiresIn])

  return (
    <div className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)] mb-4">
      <div className="flex items-center gap-2 mb-3">
        <Smartphone size={16} className="text-[var(--color-accent-active)]" />
        <h3 className="font-medium text-sm">Mobile App Pairing</h3>
      </div>

      {code ? (
        <div className="text-center py-4">
          <p className="text-xs text-[var(--color-text-secondary)] mb-2">Enter this code in the SporePrint mobile app</p>
          <div className="flex items-center justify-center gap-3">
            <span className="text-4xl font-mono font-bold tracking-[0.3em] text-[var(--color-accent-gourmet)]">
              {code}
            </span>
            <button onClick={copyCode} className="p-2 rounded-lg hover:bg-[var(--color-bg-hover)]">
              {copied ? <Check size={16} className="text-[var(--color-success)]" /> : <Copy size={16} className="text-[var(--color-text-secondary)]" />}
            </button>
          </div>
          <p className="text-xs text-[var(--color-text-secondary)] mt-3">
            Expires in {Math.floor(expiresIn / 60)}:{(expiresIn % 60).toString().padStart(2, '0')}
          </p>
        </div>
      ) : (
        <div className="text-center py-2">
          <p className="text-xs text-[var(--color-text-secondary)] mb-3">
            Generate a one-time code to pair the SporePrint mobile app with this Pi
          </p>
          <button
            onClick={generateCode}
            disabled={generating}
            className="px-4 py-2 rounded-lg bg-[var(--color-accent-active)] text-white text-sm font-medium disabled:opacity-50"
          >
            {generating ? 'Generating...' : 'Generate Pairing Code'}
          </button>
        </div>
      )}
    </div>
  )
}

export default function SettingsPage() {
  const [nodes, setNodes] = useState<HardwareNode[]>([])
  const [plugs, setPlugs] = useState<SmartPlug[]>([])
  const [health, setHealth] = useState<{ status: string; version: string } | null>(null)
  const [tab, setTab] = useState<'hardware' | 'plugs' | 'system'>('hardware')

  // Unit preferences
  const [tempUnit, setTempUnit] = useState(getTempUnit())
  const [weightUnit, setWeightUnit] = useState(getWeightUnit())

  const updateTempUnit = (unit: 'f' | 'c') => {
    haptic('light')
    setTempUnit(unit)
    localStorage.setItem('sporeprint_temp_unit', unit)
  }
  const updateWeightUnit = (unit: 'g' | 'oz') => {
    haptic('light')
    setWeightUnit(unit)
    localStorage.setItem('sporeprint_weight_unit', unit)
  }

  const refresh = () => {
    api.get<HardwareNode[]>('/hardware/nodes').then(setNodes).catch(() => {})
    api.get<SmartPlug[]>('/automation/plugs').then(setPlugs).catch(() => {})
    api.get<{ status: string; version: string }>('/health').then(setHealth).catch(() => {})
  }

  useEffect(refresh, [])

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold">Settings</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">System configuration and hardware registry</p>
        </div>
        <button
          onClick={refresh}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-[var(--color-border)] text-sm text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]"
        >
          <RefreshCw size={14} />
          Refresh
        </button>
      </div>

      {/* Unit Preferences */}
      <div className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)] mb-6">
        <h3 className="font-medium text-sm mb-4">Units</h3>
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm">
              <Thermometer size={14} className="text-[var(--color-text-secondary)]" />
              <span>Temperature</span>
            </div>
            <div className="flex gap-1 p-0.5 bg-[var(--color-bg-secondary)] rounded-lg">
              {(['f', 'c'] as const).map((u) => (
                <button
                  key={u}
                  onClick={() => updateTempUnit(u)}
                  className={`px-3 py-1 rounded-md text-sm ${
                    tempUnit === u
                      ? 'bg-[var(--color-bg-card)] text-[var(--color-text-primary)] font-medium'
                      : 'text-[var(--color-text-secondary)]'
                  }`}
                >
                  {u === 'f' ? '\u00B0F' : '\u00B0C'}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm">
              <Scale size={14} className="text-[var(--color-text-secondary)]" />
              <span>Weight</span>
            </div>
            <div className="flex gap-1 p-0.5 bg-[var(--color-bg-secondary)] rounded-lg">
              {(['g', 'oz'] as const).map((u) => (
                <button
                  key={u}
                  onClick={() => updateWeightUnit(u)}
                  className={`px-3 py-1 rounded-md text-sm ${
                    weightUnit === u
                      ? 'bg-[var(--color-bg-card)] text-[var(--color-text-primary)] font-medium'
                      : 'text-[var(--color-text-secondary)]'
                  }`}
                >
                  {u}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 p-1 bg-[var(--color-bg-secondary)] rounded-lg w-fit">
        {(['hardware', 'plugs', 'system'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-1.5 rounded-md text-sm capitalize ${
              tab === t
                ? 'bg-[var(--color-bg-card)] text-[var(--color-text-primary)]'
                : 'text-[var(--color-text-secondary)]'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === 'hardware' && (
        <div className="space-y-3">
          {nodes.length > 0 ? (
            nodes.map((node) => (
              <div
                key={node.node_id}
                className="bg-[var(--color-bg-card)] rounded-xl p-4 border border-[var(--color-border)] flex items-center gap-4"
              >
                <div className={`p-2 rounded-lg ${node.status === 'online' ? 'bg-green-500/10' : 'bg-red-500/10'}`}>
                  {node.status === 'online' ? (
                    <Wifi size={16} className="text-green-500" />
                  ) : (
                    <WifiOff size={16} className="text-red-500" />
                  )}
                </div>
                <div className="flex-1">
                  <p className="font-medium text-sm">{node.node_id}</p>
                  <p className="text-xs text-[var(--color-text-secondary)]">
                    {node.node_type} &middot; FW {node.firmware_version || '?'} &middot; {node.ip_address || '?'}
                  </p>
                </div>
                <div className="text-right">
                  <p className={`text-xs font-medium ${node.status === 'online' ? 'text-green-500' : 'text-red-500'}`}>
                    {node.status}
                  </p>
                  {node.last_seen && (
                    <p className="text-xs text-[var(--color-text-secondary)]">
                      {new Date(node.last_seen * 1000).toLocaleTimeString()}
                    </p>
                  )}
                </div>
              </div>
            ))
          ) : (
            <div className="bg-[var(--color-bg-card)] rounded-xl p-8 border border-[var(--color-border)] text-center">
              <Wifi size={32} className="mx-auto mb-3 text-[var(--color-text-secondary)]" />
              <p className="text-sm text-[var(--color-text-secondary)]">
                No hardware nodes registered. Nodes register automatically via MQTT heartbeat.
              </p>
            </div>
          )}
        </div>
      )}

      {tab === 'plugs' && (
        <div className="space-y-3">
          {plugs.length > 0 ? (
            plugs.map((plug) => (
              <div
                key={plug.plug_id}
                className="bg-[var(--color-bg-card)] rounded-xl p-4 border border-[var(--color-border)] flex items-center gap-4"
              >
                <div className="p-2 rounded-lg bg-[var(--color-bg-hover)]">
                  <Plug size={16} className="text-[var(--color-text-secondary)]" />
                </div>
                <div className="flex-1">
                  <p className="font-medium text-sm">{plug.name || plug.plug_id}</p>
                  <p className="text-xs text-[var(--color-text-secondary)]">
                    {plug.plug_type} &middot; {plug.device_role || 'no role assigned'}
                  </p>
                </div>
                <div className="text-right">
                  <p className={`text-xs font-medium ${plug.last_state === 'on' ? 'text-green-500' : 'text-[var(--color-text-secondary)]'}`}>
                    {plug.last_state || 'unknown'}
                  </p>
                  {plug.last_power_w !== null && (
                    <p className="text-xs text-[var(--color-text-secondary)]">{plug.last_power_w}W</p>
                  )}
                </div>
              </div>
            ))
          ) : (
            <div className="bg-[var(--color-bg-card)] rounded-xl p-8 border border-[var(--color-border)] text-center">
              <Plug size={32} className="mx-auto mb-3 text-[var(--color-text-secondary)]" />
              <p className="text-sm text-[var(--color-text-secondary)]">
                No smart plugs registered. Plugs auto-register when they publish MQTT messages.
              </p>
            </div>
          )}
        </div>
      )}

      {tab === 'system' && (
        <div className="space-y-4">
          <div className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)]">
            <h3 className="font-medium text-sm mb-3 flex items-center gap-2">
              <Database size={14} /> System Status
            </h3>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <p className="text-xs text-[var(--color-text-secondary)]">API Status</p>
                <p className="font-medium">{health?.status || 'Unknown'}</p>
              </div>
              <div>
                <p className="text-xs text-[var(--color-text-secondary)]">Version</p>
                <p className="font-medium">{health?.version || '?'}</p>
              </div>
              <div>
                <p className="text-xs text-[var(--color-text-secondary)]">Hardware Nodes</p>
                <p className="font-medium">{nodes.length}</p>
              </div>
              <div>
                <p className="text-xs text-[var(--color-text-secondary)]">Smart Plugs</p>
                <p className="font-medium">{plugs.length}</p>
              </div>
            </div>
          </div>

          <PairingCodeSection />

          <div className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)]">
            <h3 className="font-medium text-sm mb-3">Configuration</h3>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between py-2 border-b border-[var(--color-border)]">
                <span className="text-[var(--color-text-secondary)]">MQTT Broker</span>
                <span>mqtt:1883</span>
              </div>
              <div className="flex justify-between py-2 border-b border-[var(--color-border)]">
                <span className="text-[var(--color-text-secondary)]">ntfy URL</span>
                <span>ntfy:80</span>
              </div>
              <div className="flex justify-between py-2 border-b border-[var(--color-border)]">
                <span className="text-[var(--color-text-secondary)]">Database</span>
                <span>SQLite</span>
              </div>
              <div className="flex justify-between py-2">
                <span className="text-[var(--color-text-secondary)]">Claude API</span>
                <span className="text-[var(--color-text-secondary)]">Configure via SPOREPRINT_CLAUDE_API_KEY</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
