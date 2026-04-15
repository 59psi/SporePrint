import { create } from 'zustand'

export interface Session {
  id: number
  name: string
  species_profile_id: string
  current_phase: string
  status: string
  created_at: number
  substrate: string | null
  inoculation_date: string | null
  tub_number: string | null
  shelf_number: number | null
  shelf_side: string | null
  chamber_id: number | null
}

interface SessionState {
  sessions: Session[]
  activeSession: Session | null
  setSessions: (sessions: Session[]) => void
  setActiveSession: (session: Session | null) => void
}

export const useSessionStore = create<SessionState>((set) => ({
  sessions: [],
  activeSession: null,
  setSessions: (sessions) => set({ sessions }),
  setActiveSession: (session) => set({ activeSession: session }),
}))
