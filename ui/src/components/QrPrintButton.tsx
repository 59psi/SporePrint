import { useState } from 'react'
import { Bluetooth, Download } from 'lucide-react'

interface QrPrintButtonProps {
  qrUrl: string
  label?: string
}

// Common thermal printer BLE service UUID
const PRINTER_SERVICE = '000018f0-0000-1000-8000-00805f9b34fb'
const PRINTER_CHARACTERISTIC = '00002af1-0000-1000-8000-00805f9b34fb'

// Web Bluetooth API — not in all TS lib targets
declare global {
  interface Navigator {
    bluetooth?: {
      requestDevice(options: {
        filters?: Array<{ services?: string[] }>
        optionalServices?: string[]
      }): Promise<BluetoothDevice>
    }
  }
  interface BluetoothDevice {
    name: string | null
    gatt?: BluetoothRemoteGATTServer
  }
  interface BluetoothRemoteGATTServer {
    connect(): Promise<BluetoothRemoteGATTServer>
    getPrimaryService(service: string): Promise<BluetoothRemoteGATTService>
  }
  interface BluetoothRemoteGATTService {
    getCharacteristic(characteristic: string): Promise<BluetoothRemoteGATTCharacteristic>
  }
  interface BluetoothRemoteGATTCharacteristic {
    writeValue(value: BufferSource): Promise<void>
  }
}

export default function QrPrintButton({ qrUrl, label = 'Print Label' }: QrPrintButtonProps) {
  const [status, setStatus] = useState<string>('')

  const printViaBluetooth = async () => {
    if (!navigator.bluetooth) {
      setStatus('Bluetooth not available \u2014 using download')
      downloadQr()
      return
    }

    try {
      setStatus('Searching for printer...')
      const device = await navigator.bluetooth.requestDevice({
        filters: [{ services: [PRINTER_SERVICE] }],
        optionalServices: [PRINTER_SERVICE],
      })

      setStatus(`Connected to ${device.name || 'printer'}`)
      const server = await device.gatt!.connect()
      const service = await server.getPrimaryService(PRINTER_SERVICE)
      const characteristic = await service.getCharacteristic(PRINTER_CHARACTERISTIC)

      // Fetch the QR image as bytes
      const response = await fetch(qrUrl)
      const blob = await response.blob()
      const bytes = new Uint8Array(await blob.arrayBuffer())

      // Send in chunks (BLE max is ~512 bytes per write)
      const chunkSize = 512
      for (let i = 0; i < bytes.length; i += chunkSize) {
        const chunk = bytes.slice(i, i + chunkSize)
        await characteristic.writeValue(chunk)
      }

      setStatus('Sent to printer!')
      setTimeout(() => setStatus(''), 3000)
    } catch (err: unknown) {
      const name = err instanceof DOMException ? err.name : ''
      if (name === 'NotFoundError') {
        setStatus('No printer found \u2014 downloading instead')
      } else {
        setStatus('Bluetooth error \u2014 downloading instead')
      }
      downloadQr()
    }
  }

  const downloadQr = () => {
    const a = document.createElement('a')
    a.href = qrUrl
    a.download = 'sporeprint-label.png'
    a.click()
    setStatus('Downloaded!')
    setTimeout(() => setStatus(''), 2000)
  }

  return (
    <div className="inline-flex flex-col items-start gap-1">
      <div className="flex gap-2">
        <button
          onClick={printViaBluetooth}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm bg-[var(--color-surface)] border border-[var(--color-border)] rounded hover:border-green-600 transition-colors"
        >
          <Bluetooth className="w-4 h-4" />
          {label}
        </button>
        <button
          onClick={downloadQr}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm bg-[var(--color-surface)] border border-[var(--color-border)] rounded hover:border-green-600 transition-colors"
        >
          <Download className="w-4 h-4" />
          Download
        </button>
      </div>
      {status && <p className="text-xs text-[var(--color-text-secondary)]">{status}</p>}
    </div>
  )
}
