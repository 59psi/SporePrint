import { describe, it, expect, beforeEach } from 'vitest'
import { useSessionStore, type Session } from '../../stores/sessionStore'

const mockSession: Session = {
  id: 1,
  name: 'Test Grow',
  species_profile_id: 'cubensis_golden_teacher',
  current_phase: 'fruiting',
  status: 'active',
  created_at: 1000,
  substrate: 'CVG',
  inoculation_date: '2026-01-01',
}

beforeEach(() => {
  useSessionStore.setState({ sessions: [], activeSession: null })
})

describe('useSessionStore', () => {
  it('has correct initial state', () => {
    const state = useSessionStore.getState()
    expect(state.sessions).toEqual([])
    expect(state.activeSession).toBeNull()
  })

  it('setSessions stores sessions', () => {
    const sessions = [mockSession, { ...mockSession, id: 2, name: 'Grow 2' }]
    useSessionStore.getState().setSessions(sessions)
    expect(useSessionStore.getState().sessions).toHaveLength(2)
  })

  it('setActiveSession stores session', () => {
    useSessionStore.getState().setActiveSession(mockSession)
    expect(useSessionStore.getState().activeSession).toEqual(mockSession)
  })

  it('setActiveSession clears with null', () => {
    useSessionStore.getState().setActiveSession(mockSession)
    useSessionStore.getState().setActiveSession(null)
    expect(useSessionStore.getState().activeSession).toBeNull()
  })
})
