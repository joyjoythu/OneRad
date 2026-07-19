import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useSettingsStore } from '../settings'

vi.mock('@/api/settings', () => ({
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
}))

import * as api from '@/api/settings'

describe('useSettingsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.resetAllMocks()
  })

  it('loads application-wide settings only once for concurrent callers', async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      api_key: 'sk-general',
      api_key_configured: true,
      api_key_source: 'settings',
    })
    const store = useSettingsStore()

    await Promise.all([store.ensureLoaded(), store.ensureLoaded()])

    expect(api.getSettings).toHaveBeenCalledOnce()
    expect(store.apiKeyConfigured).toBe(true)
  })

  it('clears the required marker after a valid key is saved', async () => {
    vi.mocked(api.updateSettings).mockResolvedValue({
      api_key: 'sk-new',
      api_key_configured: true,
      api_key_source: 'settings',
    })
    const store = useSettingsStore()
    store.requestApiKey()

    await store.saveApiKey('sk-new')

    expect(api.updateSettings).toHaveBeenCalledWith('sk-new')
    expect(store.apiKeyRequired).toBe(false)
    expect(store.settings.api_key).toBe('sk-new')
  })
})
