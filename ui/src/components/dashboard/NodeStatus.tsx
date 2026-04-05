import { Wifi, WifiOff } from 'lucide-react'

interface NodeStatusProps {
  nodeId: string
  status: 'online' | 'offline' | 'unknown'
  lastSeen?: number
  firmwareVersion?: string
}

function timeAgo(ts: number): string {
  const diff = Math.floor(Date.now() / 1000 - ts)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

export default function NodeStatus({ nodeId, status, lastSeen, firmwareVersion }: NodeStatusProps) {
  const isOnline = status === 'online'

  return (
    <div className="flex items-center gap-3 py-2">
      <div className={`p-1.5 rounded-lg ${isOnline ? 'bg-green-500/10' : 'bg-red-500/10'}`}>
        {isOnline ? (
          <Wifi size={14} className="text-green-500" />
        ) : (
          <WifiOff size={14} className="text-red-500" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate">{nodeId}</p>
        <p className="text-xs text-[var(--color-text-secondary)]">
          {lastSeen ? timeAgo(lastSeen) : 'never seen'}
          {firmwareVersion && ` \u00b7 v${firmwareVersion}`}
        </p>
      </div>
      <div
        className="w-2 h-2 rounded-full"
        style={{ backgroundColor: isOnline ? 'var(--color-success)' : 'var(--color-danger)' }}
      />
    </div>
  )
}
