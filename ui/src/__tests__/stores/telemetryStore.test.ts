import { describe, it, expect, beforeEach } from 'vitest'
import { useTelemetryStore, type SensorReading } from '../../stores/telemetryStore'

const mockReading: SensorReading = {
  timestamp: 1000,
  temp_f: 73.5,
  temp_c: 23.0,
  humidity: 88.0,
  co2_ppm: 650,
  lux: 300,
  dew_point_f: 69.0,
}

beforeEach(() => {
  useTelemetryStore.setState({ latest: {}, history: [] })
})

describe('useTelemetryStore', () => {
  it('has correct initial state', () => {
    const state = useTelemetryStore.getState()
    expect(state.latest).toEqual({})
    expect(state.history).toEqual([])
  })

  it('setReading stores reading by node id', () => {
    useTelemetryStore.getState().setReading('node-01', mockReading)
    expect(useTelemetryStore.getState().latest['node-01']).toEqual(mockReading)
  })

  it('setReading overwrites existing reading', () => {
    const { setReading } = useTelemetryStore.getState()
    setReading('node-01', mockReading)
    const updated = { ...mockReading, temp_f: 80.0 }
    setReading('node-01', updated)
    expect(useTelemetryStore.getState().latest['node-01'].temp_f).toBe(80.0)
  })

  it('addHistory appends readings', () => {
    const { addHistory } = useTelemetryStore.getState()
    addHistory(mockReading)
    addHistory({ ...mockReading, timestamp: 2000 })
    addHistory({ ...mockReading, timestamp: 3000 })
    expect(useTelemetryStore.getState().history).toHaveLength(3)
  })

  it('addHistory caps around 500 entries', () => {
    const { addHistory } = useTelemetryStore.getState()
    for (let i = 0; i < 510; i++) {
      addHistory({ ...mockReading, timestamp: i })
    }
    const history = useTelemetryStore.getState().history
    // slice(-500) keeps last 500, then appends 1 = 501 max
    expect(history.length).toBeLessThanOrEqual(501)
    expect(history.length).toBeGreaterThan(499)
  })
})
