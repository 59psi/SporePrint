import { describe, it, expect } from 'vitest'
import {
  CATEGORY_COLORS,
  CATEGORY_BADGE_COLORS,
  STATUS_COLORS,
  HEALTH_COLORS,
} from '../../constants/colors'

describe('CATEGORY_COLORS', () => {
  it('has all three categories', () => {
    expect(Object.keys(CATEGORY_COLORS)).toEqual(
      expect.arrayContaining(['gourmet', 'medicinal', 'active'])
    )
  })

  it('values are CSS custom properties', () => {
    for (const value of Object.values(CATEGORY_COLORS)) {
      expect(value).toMatch(/^var\(--.+\)$/)
    }
  })
})

describe('CATEGORY_BADGE_COLORS', () => {
  it('has all three categories', () => {
    expect(Object.keys(CATEGORY_BADGE_COLORS)).toEqual(
      expect.arrayContaining(['gourmet', 'medicinal', 'active'])
    )
  })

  it('each entry has bg and text properties', () => {
    for (const [, value] of Object.entries(CATEGORY_BADGE_COLORS)) {
      expect(value).toHaveProperty('bg')
      expect(value).toHaveProperty('text')
    }
  })
})

describe('STATUS_COLORS', () => {
  it('has all session statuses', () => {
    expect(Object.keys(STATUS_COLORS)).toEqual(
      expect.arrayContaining(['active', 'completed', 'aborted', 'paused'])
    )
  })
})

describe('HEALTH_COLORS', () => {
  it('has all health assessments', () => {
    expect(Object.keys(HEALTH_COLORS)).toEqual(
      expect.arrayContaining(['healthy', 'concern', 'contaminated', 'unknown'])
    )
  })
})
