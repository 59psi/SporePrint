import { create } from 'zustand'

export interface SensorReading {
  timestamp: number
  temp_f: number
  temp_c: number
  humidity: number
  co2_ppm: number
  lux: number
  dew_point_f: number
}

interface TelemetryState {
  latest: Record<string, SensorReading>
  history: SensorReading[]
  setReading: (nodeId: string, reading: SensorReading) => void
  addHistory: (reading: SensorReading) => void
}

export const useTelemetryStore = create<TelemetryState>((set) => ({
  latest: {},
  history: [],
  setReading: (nodeId, reading) =>
    set((state) => ({
      latest: { ...state.latest, [nodeId]: reading },
    })),
  addHistory: (reading) =>
    set((state) => ({
      history: [...state.history.slice(-500), reading],
    })),
}))
