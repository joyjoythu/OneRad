import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import * as api from '@/api/settings'
import type { GeneralSettings } from '@/api/settings'

const emptySettings = (): GeneralSettings => ({
  api_key: '',
  api_key_configured: false,
  api_key_source: 'none',
})

export const useSettingsStore = defineStore('settings', () => {
  const settings = ref<GeneralSettings>(emptySettings())
  const loaded = ref(false)
  const loading = ref(false)
  const apiKeyRequired = ref(false)
  let loadPromise: Promise<void> | null = null

  const apiKeyConfigured = computed(() => settings.value.api_key_configured)

  async function loadSettings(): Promise<void> {
    loading.value = true
    try {
      settings.value = await api.getSettings()
      loaded.value = true
      if (settings.value.api_key_configured) apiKeyRequired.value = false
    } finally {
      loading.value = false
    }
  }

  function ensureLoaded(): Promise<void> {
    if (loaded.value) return Promise.resolve()
    if (!loadPromise) {
      loadPromise = loadSettings().finally(() => {
        loadPromise = null
      })
    }
    return loadPromise
  }

  async function saveApiKey(apiKey: string): Promise<GeneralSettings> {
    settings.value = await api.updateSettings(apiKey)
    loaded.value = true
    if (settings.value.api_key_configured) apiKeyRequired.value = false
    return settings.value
  }

  function requestApiKey(): void {
    apiKeyRequired.value = true
  }

  return {
    settings,
    loaded,
    loading,
    apiKeyRequired,
    apiKeyConfigured,
    loadSettings,
    ensureLoaded,
    saveApiKey,
    requestApiKey,
  }
})
