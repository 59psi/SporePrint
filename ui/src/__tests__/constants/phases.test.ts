import { describe, it, expect } from 'vitest'
import { PHASE_ORDER } from '../../constants/phases'

describe('PHASE_ORDER', () => {
  it('has 8 phases', () => {
    expect(PHASE_ORDER).toHaveLength(8)
  })

  it('starts with agar', () => {
    expect(PHASE_ORDER[0]).toBe('agar')
  })

  it('ends with complete', () => {
    expect(PHASE_ORDER[PHASE_ORDER.length - 1]).toBe('complete')
  })

  it('contains all expected cultivation phases', () => {
    expect(PHASE_ORDER).toContain('substrate_colonization')
    expect(PHASE_ORDER).toContain('primordia_induction')
    expect(PHASE_ORDER).toContain('fruiting')
    expect(PHASE_ORDER).toContain('rest')
  })

  it('has phases in correct order', () => {
    const subColIdx = PHASE_ORDER.indexOf('substrate_colonization')
    const primIdx = PHASE_ORDER.indexOf('primordia_induction')
    const fruitIdx = PHASE_ORDER.indexOf('fruiting')
    expect(subColIdx).toBeLessThan(primIdx)
    expect(primIdx).toBeLessThan(fruitIdx)
  })
})
