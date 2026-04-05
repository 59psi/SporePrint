import { useEffect, useState } from 'react'
import { Wifi, WifiOff, Plug, Database, RefreshCw } from 'lucide-react'
import { api } from '../api/client'

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

export default function SettingsPage() {
  const [nodes, setNodes] = useState<HardwareNode[]>([])
  const [plugs, setPlugs] = useState<SmartPlug[]>([])
  const [health, setHealth] = useState<{ status: string; version: string } | null>(null)
  const [tab, setTab] = useState<'hardware' | 'plugs' | 'system'>('hardware')

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
