import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import SettingsView from '../SettingsView.vue'
import { useSettingsStore } from '@/stores/settings'

vi.mock('@/api/settings', () => ({
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
}))

import * as settingsApi from '@/api/settings'

const wrappers: Array<{ unmount: () => void }> = []

function setupWrapper() {
  const wrapper = mount(SettingsView, {
    attachTo: document.body,
    global: { plugins: [ElementPlus] },
  })
  wrappers.push(wrapper)
  return wrapper
}

describe('SettingsView', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    vi.mocked(settingsApi.getSettings).mockResolvedValue({
      api_key: 'sk-old',
      api_key_configured: true,
      api_key_source: 'settings',
    })
    vi.mocked(settingsApi.updateSettings).mockImplementation(async (apiKey: string) => ({
      api_key: apiKey,
      api_key_configured: Boolean(apiKey),
      api_key_source: apiKey ? 'settings' : 'none',
    }))
  })

  afterEach(() => {
    wrappers.forEach((wrapper) => wrapper.unmount())
    wrappers.length = 0
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('renders only the general settings section', async () => {
    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.text()).toContain('通用设置')
    expect(wrapper.text()).toContain('界面外观')
    expect(wrapper.text()).toContain('DeepSeek API 密钥')
    expect(wrapper.text()).not.toContain('项目设置')
    expect(wrapper.find('[data-testid="settings-save"]').exists()).toBe(false)
  })

  it('loads the saved API key into the input', async () => {
    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find<HTMLInputElement>('input[placeholder="请输入 DeepSeek API 密钥"]')
      .element.value).toBe('sk-old')
  })

  it('shows and focuses the red global API key prompt requested by new-thread action', async () => {
    vi.mocked(settingsApi.getSettings).mockResolvedValue({
      api_key: '',
      api_key_configured: false,
      api_key_source: 'none',
    })
    useSettingsStore().requestApiKey()

    const wrapper = setupWrapper()
    await flushPromises()

    const hint = wrapper.find('[data-testid="missing-api-key-hint"]')
    const input = wrapper.find<HTMLInputElement>('input[placeholder="请输入 DeepSeek API 密钥"]')
    expect(hint.exists()).toBe(true)
    expect(hint.classes()).toContain('field-hint--danger')
    expect(hint.text()).toContain('尚未填写 DeepSeek API 密钥')
    expect(document.activeElement).toBe(input.element)

    await input.setValue('sk-new')
    expect(wrapper.find('[data-testid="missing-api-key-hint"]').exists()).toBe(false)
    await vi.advanceTimersByTimeAsync(600)
    await flushPromises()

    expect(settingsApi.updateSettings).toHaveBeenCalledWith('sk-new')
    expect(useSettingsStore().apiKeyRequired).toBe(false)
  })

  it('debounces the general API key for 600ms', async () => {
    const wrapper = setupWrapper()
    await flushPromises()

    await wrapper.find('input[placeholder="请输入 DeepSeek API 密钥"]').setValue('sk-new')
    await vi.advanceTimersByTimeAsync(599)
    expect(settingsApi.updateSettings).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(1)
    await flushPromises()

    expect(settingsApi.updateSettings).toHaveBeenCalledOnce()
    expect(settingsApi.updateSettings).toHaveBeenCalledWith('sk-new')
    expect(wrapper.find('[data-testid="general-save-status"]').text()).toContain('已保存')
  })

  it('offers a retry action when saving the API key fails', async () => {
    vi.mocked(settingsApi.updateSettings)
      .mockRejectedValueOnce(new Error('general failure'))
      .mockImplementationOnce(async (apiKey: string) => ({
        api_key: apiKey,
        api_key_configured: true,
        api_key_source: 'settings',
      }))
    const wrapper = setupWrapper()
    await flushPromises()

    await wrapper.find('input[placeholder="请输入 DeepSeek API 密钥"]').setValue('sk-new')
    await vi.advanceTimersByTimeAsync(600)
    await flushPromises()

    expect(wrapper.find('[data-testid="general-save-status"]').text()).toContain('保存失败')

    await wrapper.find('[data-testid="general-save-retry"]').trigger('click')
    await flushPromises()

    expect(settingsApi.updateSettings).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[data-testid="general-save-status"]').text()).toContain('已保存')
  })
})
