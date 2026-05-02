import { useEffect, useState, useCallback } from 'react'
import { Wifi, WifiOff, Plug, Database, RefreshCw, Smartphone, Copy, Check, Thermometer, Scale, Settings2, Loader2, RotateCcw } from 'lucide-react'
import { api } from '../api/client'
import { reportFetchError } from '../stores/toastStore'
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

interface SettingEntry {
  value: string
  source: 'user' | 'env' | 'default'
  description: string
  display_value: string
}

type SettingsMap = Record<string, SettingEntry>

const SOURCE_BADGE: Record<string, { label: string; className: string }> = {
  user: { label: 'user', className: 'bg-blue-500/15 text-blue-400' },
  env: { label: 'env', className: 'bg-amber-500/15 text-amber-400' },
  default: { label: 'default', className: 'bg-[var(--color-bg-hover)] text-[var(--color-text-secondary)]' },
}

function SystemSettingsSection() {
  const [settings, setSettings] = useState<SettingsMap | null>(null)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editingKey, setEditingKey] = useState<string | null>(null)

  const load = useCallback(() => {
    api.get<SettingsMap>('/settings').then((data) => {
      setSettings(data)
      setDraft({})
      setEditingKey(null)
    }).catch(() => setError('Failed to load settings'))
  }, [])

  useEffect(load, [load])

  const save = async (key: string, value: string) => {
    setSaving(key)
    setError(null)
    try {
      const updated = await api.put<SettingsMap>(`/settings/${key}`, { value })
      setSettings(updated)
      setDraft((d) => { const n = { ...d }; delete n[key]; return n })
      setEditingKey(null)
      haptic('light')
    } catch {
      setError(`Failed to save ${key}`)
    }
    setSaving(null)
  }

  const revert = async (key: string) => {
    setSaving(key)
    setError(null)
    try {
      const updated = await api.delete<SettingsMap>(`/settings/${key}`)
      setSettings(updated)
      setDraft((d) => { const n = { ...d }; delete n[key]; return n })
      haptic('light')
    } catch {
      setError(`Failed to revert ${key}`)
    }
    setSaving(null)
  }

  const currentVal = (key: string) =>
    draft[key] !== undefined ? draft[key] : (settings?.[key]?.value ?? '')

  const isDirty = (key: string) =>
    draft[key] !== undefined && draft[key] !== (settings?.[key]?.value ?? '')

  if (!settings) {
    return (
      <div className="bg-[var(--color-bg-card)] rounded-xl p-8 border border-[var(--color-border)] text-center">
        <Loader2 size={20} className="mx-auto mb-2 animate-spin text-[var(--color-text-secondary)]" />
        <p className="text-sm text-[var(--color-text-secondary)]">Loading settings...</p>
      </div>
    )
  }

  const inputCls = 'w-full mt-1 px-3 py-2 rounded-lg bg-[var(--color-bg-primary)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-active)]'
  const saveBtnCls = 'px-3 py-1.5 rounded-lg bg-[var(--color-accent-active)] text-white text-xs font-medium disabled:opacity-50'

  return (
    <div className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)]">
      <div className="flex items-center gap-2 mb-1">
        <Settings2 size={14} className="text-[var(--color-accent-active)]" />
        <h3 className="font-medium text-sm">System Settings</h3>
      </div>
      <p className="text-xs text-[var(--color-text-secondary)] mb-4">
        Configure weather location, providers, and API keys. Changes take effect on the next poll cycle.
      </p>

      {error && (
        <div className="mb-4 px-3 py-2 rounded-lg bg-red-500/10 text-red-400 text-xs">{error}</div>
      )}

      {/* Weather Location */}
      <fieldset className="mb-4">
        <legend className="text-xs font-medium text-[var(--color-text-secondary)] uppercase tracking-wider mb-2">Location</legend>
        <div className="grid grid-cols-2 gap-3">
          {(['weather_lat', 'weather_lon'] as const).map((key) => (
            <div key={key}>
              <div className="flex items-center gap-2">
                <label className="text-xs text-[var(--color-text-secondary)]">
                  {key === 'weather_lat' ? 'Latitude' : 'Longitude'}
                </label>
                <SourceBadge source={settings[key]?.source} />
              </div>
              <div className="flex gap-2 items-end">
                <input
                  type="text"
                  value={currentVal(key)}
                  onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                  placeholder={key === 'weather_lat' ? 'e.g. 37.7749' : 'e.g. -122.4194'}
                  className={inputCls}
                />
              </div>
              {isDirty(key) && (
                <div className="flex gap-2 mt-1.5">
                  <button onClick={() => save(key, draft[key])} disabled={saving === key} className={saveBtnCls}>
                    {saving === key ? 'Saving...' : 'Save'}
                  </button>
                  <button onClick={() => setDraft((d) => { const n = { ...d }; delete n[key]; return n })} className="text-xs text-[var(--color-text-secondary)]">
                    Cancel
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </fieldset>

      {/* Weather Provider */}
      <fieldset className="mb-4">
        <legend className="text-xs font-medium text-[var(--color-text-secondary)] uppercase tracking-wider mb-2">Weather Provider</legend>
        <div className="flex items-center gap-2 mb-1">
          <SourceBadge source={settings.weather_provider?.source} />
        </div>
        <select
          value={currentVal('weather_provider')}
          onChange={(e) => { setDraft({ ...draft, weather_provider: e.target.value }); save('weather_provider', e.target.value) }}
          className={inputCls}
        >
          <option value="openmeteo">Open-Meteo (free, no key)</option>
          <option value="nws">National Weather Service (US only)</option>
          <option value="openweathermap">OpenWeatherMap (requires API key)</option>
        </select>
      </fieldset>

      {/* Poll Interval */}
      <fieldset className="mb-4">
        <legend className="text-xs font-medium text-[var(--color-text-secondary)] uppercase tracking-wider mb-2">Poll Interval</legend>
        <div className="flex items-center gap-2 mb-1">
          <SourceBadge source={settings.weather_poll_minutes?.source} />
        </div>
        <div className="flex gap-2 items-end">
          <input
            type="number"
            min={1}
            max={60}
            value={currentVal('weather_poll_minutes')}
            onChange={(e) => setDraft({ ...draft, weather_poll_minutes: e.target.value })}
            className={inputCls + ' max-w-[120px]'}
          />
          <span className="text-xs text-[var(--color-text-secondary)] pb-2">minutes</span>
        </div>
        {isDirty('weather_poll_minutes') && (
          <div className="flex gap-2 mt-1.5">
            <button onClick={() => save('weather_poll_minutes', draft.weather_poll_minutes)} disabled={saving === 'weather_poll_minutes'} className={saveBtnCls}>
              {saving === 'weather_poll_minutes' ? 'Saving...' : 'Save'}
            </button>
            <button onClick={() => setDraft((d) => { const n = { ...d }; delete n.weather_poll_minutes; return n })} className="text-xs text-[var(--color-text-secondary)]">
              Cancel
            </button>
          </div>
        )}
      </fieldset>

      {/* API Keys */}
      <fieldset>
        <legend className="text-xs font-medium text-[var(--color-text-secondary)] uppercase tracking-wider mb-2">API Keys</legend>
        <div className="space-y-3">
          {(['weather_api_key', 'claude_api_key'] as const).map((key) => (
            <div key={key} className="flex items-center justify-between py-2 border-b border-[var(--color-border)] last:border-0">
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm">{settings[key]?.description}</span>
                  <SourceBadge source={settings[key]?.source} />
                </div>
                {editingKey === key ? (
                  <div className="flex gap-2 mt-1.5 items-end">
                    <input
                      type="text"
                      value={draft[key] ?? ''}
                      onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                      placeholder="Paste API key"
                      className={inputCls + ' max-w-[300px]'}
                      autoFocus
                    />
                    <button onClick={() => save(key, draft[key] ?? '')} disabled={saving === key} className={saveBtnCls}>
                      {saving === key ? 'Saving...' : 'Save'}
                    </button>
                    <button onClick={() => { setEditingKey(null); setDraft((d) => { const n = { ...d }; delete n[key]; return n }) }} className="text-xs text-[var(--color-text-secondary)]">
                      Cancel
                    </button>
                  </div>
                ) : (
                  <p className="text-xs text-[var(--color-text-secondary)] mt-0.5 font-mono">
                    {settings[key]?.display_value || '(not set)'}
                  </p>
                )}
              </div>
              {editingKey !== key && (
                <div className="flex gap-1">
                  <button onClick={() => setEditingKey(key)} className="px-2 py-1 rounded text-xs text-[var(--color-accent-active)] hover:bg-[var(--color-bg-hover)]">
                    Edit
                  </button>
                  {settings[key]?.source === 'user' && (
                    <button onClick={() => revert(key)} disabled={saving === key} className="px-2 py-1 rounded text-xs text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]" title="Revert to env/default">
                      <RotateCcw size={12} />
                    </button>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </fieldset>

      {/* OTA Verify Key — Ed25519 public key used to verify firmware
          bundles. Public keys aren't secrets, so we render the full
          value (the settings_service `_mask` helper has an explicit
          carve-out for this key). Empty = OTA disabled. */}
      <fieldset className="mt-4">
        <legend className="text-xs font-medium text-[var(--color-text-secondary)] uppercase tracking-wider mb-2">OTA Updates</legend>
        <div className="py-2">
          <div className="flex items-center gap-2">
            <span className="text-sm">OTA verify key</span>
            <SourceBadge source={settings.ota_pubkey_b64?.source} />
          </div>
          <p className="text-xs text-[var(--color-text-secondary)] mt-0.5">
            Base64-encoded raw 32-byte Ed25519 public key. Generate with{' '}
            <code className="font-mono">scripts/generate-ota-keypair.py</code> and
            paste the public half here. Empty = OTA disabled (fail-closed).
          </p>
          {editingKey === 'ota_pubkey_b64' ? (
            <div className="flex gap-2 mt-1.5 items-end flex-wrap">
              <input
                type="text"
                value={draft.ota_pubkey_b64 ?? ''}
                onChange={(e) => setDraft({ ...draft, ota_pubkey_b64: e.target.value })}
                placeholder="Paste base64 public key (44 chars)"
                className={inputCls + ' min-w-[320px] flex-1 font-mono text-xs'}
                autoFocus
                spellCheck={false}
                autoCorrect="off"
              />
              <button
                onClick={() => save('ota_pubkey_b64', draft.ota_pubkey_b64 ?? '')}
                disabled={saving === 'ota_pubkey_b64'}
                className={saveBtnCls}
              >
                {saving === 'ota_pubkey_b64' ? 'Saving...' : 'Save'}
              </button>
              <button
                onClick={() => {
                  setEditingKey(null)
                  setDraft((d) => { const n = { ...d }; delete n.ota_pubkey_b64; return n })
                }}
                className="text-xs text-[var(--color-text-secondary)]"
              >
                Cancel
              </button>
            </div>
          ) : (
            <div className="flex gap-2 mt-1.5 items-center">
              <p className="text-xs font-mono break-all flex-1">
                {settings.ota_pubkey_b64?.display_value || '(not set — OTA disabled)'}
              </p>
              <div className="flex gap-1">
                <button
                  onClick={() => setEditingKey('ota_pubkey_b64')}
                  className="px-2 py-1 rounded text-xs text-[var(--color-accent-active)] hover:bg-[var(--color-bg-hover)]"
                >
                  Edit
                </button>
                {settings.ota_pubkey_b64?.source === 'user' && (
                  <button
                    onClick={() => revert('ota_pubkey_b64')}
                    disabled={saving === 'ota_pubkey_b64'}
                    className="px-2 py-1 rounded text-xs text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]"
                    title="Revert to env/default"
                  >
                    <RotateCcw size={12} />
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </fieldset>

      {/* ntfy Topic */}
      <fieldset className="mt-4">
        <legend className="text-xs font-medium text-[var(--color-text-secondary)] uppercase tracking-wider mb-2">Notifications</legend>
        <div className="flex items-center gap-2 mb-1">
          <label className="text-xs text-[var(--color-text-secondary)]">ntfy Topic</label>
          <SourceBadge source={settings.ntfy_topic?.source} />
        </div>
        <div className="flex gap-2 items-end">
          <input
            type="text"
            value={currentVal('ntfy_topic')}
            onChange={(e) => setDraft({ ...draft, ntfy_topic: e.target.value })}
            placeholder="sporeprint"
            className={inputCls + ' max-w-[200px]'}
          />
        </div>
        {isDirty('ntfy_topic') && (
          <div className="flex gap-2 mt-1.5">
            <button onClick={() => save('ntfy_topic', draft.ntfy_topic)} disabled={saving === 'ntfy_topic'} className={saveBtnCls}>
              {saving === 'ntfy_topic' ? 'Saving...' : 'Save'}
            </button>
            <button onClick={() => setDraft((d) => { const n = { ...d }; delete n.ntfy_topic; return n })} className="text-xs text-[var(--color-text-secondary)]">
              Cancel
            </button>
          </div>
        )}
      </fieldset>
    </div>
  )
}

function SourceBadge({ source }: { source?: string }) {
  if (!source) return null
  const badge = SOURCE_BADGE[source] ?? SOURCE_BADGE.default
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium ${badge.className}`}>
      {badge.label}
    </span>
  )
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
    } catch (err) {
      reportFetchError('Settings/pairing-code', err, "Couldn't generate pairing code")
    }
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
    api.get<HardwareNode[]>('/hardware/nodes').then(setNodes).catch((err) =>
      reportFetchError('Settings/hardware-nodes', err, "Couldn't load hardware nodes")
    )
    api.get<SmartPlug[]>('/automation/plugs').then(setPlugs).catch((err) =>
      reportFetchError('Settings/plugs', err, "Couldn't load smart plugs")
    )
    api.get<{ status: string; version: string }>('/health').then(setHealth).catch((err) =>
      reportFetchError('Settings/health', err, "Couldn't check server health")
    )
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

          <SystemSettingsSection />

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
              <div className="flex justify-between py-2">
                <span className="text-[var(--color-text-secondary)]">Database</span>
                <span>SQLite</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
