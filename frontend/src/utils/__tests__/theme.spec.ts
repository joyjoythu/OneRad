import { describe, it, expect, beforeEach, vi } from 'vitest'
import { getTheme, setTheme, initTheme } from '../theme'

const THEME_KEY = 'onerad:theme'

describe('theme', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.classList.remove('dark')
  })

  it('defaults to light when nothing is stored', () => {
    expect(getTheme()).toBe('light')
  })

  it('initTheme keeps the light class state by default', () => {
    initTheme()
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('setTheme(light) removes the dark class and persists the choice', () => {
    setTheme('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(localStorage.getItem(THEME_KEY)).toBe('light')
  })

  it('setTheme(dark) adds the dark class and persists the choice', () => {
    setTheme('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(localStorage.getItem(THEME_KEY)).toBe('dark')
  })

  it('initTheme restores a persisted dark choice', () => {
    localStorage.setItem(THEME_KEY, 'dark')
    initTheme()
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('falls back to light and still toggles the class when localStorage throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied')
    })

    expect(getTheme()).toBe('light')
    setTheme('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)

    vi.restoreAllMocks()
  })
})
