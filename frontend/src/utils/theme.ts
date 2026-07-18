export type Theme = 'light' | 'dark'

const THEME_KEY = 'onerad:theme'
const DEFAULT_THEME: Theme = 'dark'

export function getTheme(): Theme {
  try {
    return localStorage.getItem(THEME_KEY) === 'light' ? 'light' : DEFAULT_THEME
  } catch {
    return DEFAULT_THEME
  }
}

export function setTheme(theme: Theme): void {
  document.documentElement.classList.toggle('dark', theme === 'dark')
  try {
    localStorage.setItem(THEME_KEY, theme)
  } catch {
    // localStorage 不可用（如隐私模式）时静默失败，主题仍可切换
  }
}

export function initTheme(): void {
  setTheme(getTheme())
}
