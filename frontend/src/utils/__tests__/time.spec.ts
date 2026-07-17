import { describe, it, expect } from 'vitest'
import { formatMessageTime } from '../time'

const pad = (n: number): string => String(n).padStart(2, '0')

describe('formatMessageTime', () => {
  it('formats same-day timestamps as HH:MM', () => {
    const now = new Date()
    const iso = new Date(
      now.getFullYear(),
      now.getMonth(),
      now.getDate(),
      9,
      5,
    ).toISOString()
    expect(formatMessageTime(iso)).toBe('09:05')
  })

  it('formats older timestamps as MM-DD HH:MM', () => {
    const iso = '2020-03-04T05:06:07+00:00'
    const d = new Date(iso)
    const expected = `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
    expect(formatMessageTime(iso)).toBe(expected)
  })

  it('returns empty string for invalid input', () => {
    expect(formatMessageTime('not-a-date')).toBe('')
    expect(formatMessageTime('')).toBe('')
  })
})
