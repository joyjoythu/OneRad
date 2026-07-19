import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import SettingsView from '../SettingsView.vue'
import PathPickerDialog from '@/components/PathPickerDialog.vue'
import { useProjectStore } from '@/stores/project'
import { useSettingsStore } from '@/stores/settings'
import type { AnalysisConfig, Project } from '@/api/projects'

vi.mock('@/api/filesystem', () => ({
  listFilesystemRoots: vi.fn(),
  listFilesystemEntries: vi.fn(),
}))

vi.mock('@/api/settings', () => ({
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
}))

import * as settingsApi from '@/api/settings'

const mockAnalysis = (overrides: Partial<AnalysisConfig> = {}): AnalysisConfig => ({
  image_dir: 'images',
  clinical_path: 'clinical.xlsx',
  output_dir: './outputs',
  modality: 'auto',
  covariates: 'age',
  model: 'logistic',
  analysis_model: 'logistic',
  ...overrides,
})

const mockProject = (id = 'proj-1', overrides: Partial<AnalysisConfig> = {}): Project => ({
  id,
  name: `测试项目 ${id}`,
  path: `/tmp/${id}`,
  description: '',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  analysis: mockAnalysis(overrides),
})

const wrappers: Array<{ unmount: () => void }> = []

function setupWrapper() {
  const wrapper = mount(SettingsView, {
    attachTo: document.body,
    global: { plugins: [ElementPlus] },
  })
  wrappers.push(wrapper)
  return wrapper
}

function selectProject(project: Project): ReturnType<typeof useProjectStore> {
  const store = useProjectStore()
  store.projects = [project]
  store.selectProject(project.id)
  return store
}

function savedProject(project: Project, config: AnalysisConfig): Project {
  return { ...project, analysis: { ...config } }
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

  it('separates general settings from project settings even without a project', async () => {
    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.text()).toContain('通用设置')
    expect(wrapper.text()).toContain('界面外观')
    expect(wrapper.text()).toContain('DeepSeek API 密钥')
    expect(wrapper.text()).toContain('项目设置')
    expect(wrapper.text()).toContain('请先从左侧选择一个项目')
    expect(wrapper.find('[data-testid="settings-save"]').exists()).toBe(false)
  })

  it('renders project-only analysis fields separately from the API key', async () => {
    selectProject(mockProject())
    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.findAll('.path-input-row')).toHaveLength(3)
    expect(wrapper.text()).toContain('影像目录')
    expect(wrapper.text()).toContain('临床数据文件')
    expect(wrapper.text()).toContain('输出目录')
    expect(wrapper.text()).toContain('影像模态')
    expect(wrapper.text()).toContain('协变量')
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

  it('debounces the general API key independently for 600ms', async () => {
    const project = mockProject()
    const projectStore = selectProject(project)
    const projectSaveSpy = vi.spyOn(projectStore, 'saveConfig')
    const wrapper = setupWrapper()
    await flushPromises()

    await wrapper.find('input[placeholder="请输入 DeepSeek API 密钥"]').setValue('sk-new')
    await vi.advanceTimersByTimeAsync(599)
    expect(settingsApi.updateSettings).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(1)
    await flushPromises()

    expect(settingsApi.updateSettings).toHaveBeenCalledOnce()
    expect(settingsApi.updateSettings).toHaveBeenCalledWith('sk-new')
    expect(projectSaveSpy).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="general-save-status"]').text()).toContain('已保存')
  })

  it('debounces project changes and saves only project analysis configuration', async () => {
    const project = mockProject()
    const store = selectProject(project)
    const saveSpy = vi.spyOn(store, 'saveConfig').mockImplementation(async (_id, config) =>
      savedProject(project, config)
    )
    const wrapper = setupWrapper()
    await flushPromises()

    await wrapper.find('input[placeholder*="age, sex"]').setValue('age, sex')
    await vi.advanceTimersByTimeAsync(599)
    expect(saveSpy).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(1)
    await flushPromises()

    expect(saveSpy).toHaveBeenCalledWith('proj-1', expect.objectContaining({
      covariates: 'age, sex',
    }))
    expect(settingsApi.updateSettings).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="project-save-status"]').text()).toContain('已保存')
  })

  it('flushes a pending project change immediately on field blur', async () => {
    const project = mockProject()
    const store = selectProject(project)
    const saveSpy = vi.spyOn(store, 'saveConfig').mockImplementation(async (_id, config) =>
      savedProject(project, config)
    )
    const wrapper = setupWrapper()
    await flushPromises()
    const input = wrapper.find('input[placeholder*="age, sex"]')

    await input.setValue('age, sex')
    await input.trigger('focusout')
    await flushPromises()

    expect(saveSpy).toHaveBeenCalledOnce()
    expect(saveSpy.mock.calls[0][1].covariates).toBe('age, sex')
  })

  it('flushes the previous project before switching drafts', async () => {
    const first = mockProject('project-a')
    const second = mockProject('project-b', { image_dir: 'B:\\images' })
    const store = useProjectStore()
    store.projects = [first, second]
    store.selectProject(first.id)
    const saveSpy = vi.spyOn(store, 'saveConfig').mockImplementation(async (_id, config) =>
      savedProject(first, config)
    )
    const wrapper = setupWrapper()
    await flushPromises()

    await wrapper.find('input[placeholder="包含影像与分割文件的目录"]').setValue('A:\\new-images')
    store.selectProject(second.id)
    await flushPromises()

    expect(saveSpy).toHaveBeenCalledWith('project-a', expect.objectContaining({
      image_dir: 'A:\\new-images',
    }))
    expect(wrapper.find<HTMLInputElement>('input[placeholder="包含影像与分割文件的目录"]')
      .element.value).toBe('B:\\images')
  })

  it('shows independent retry actions for general and project save failures', async () => {
    const project = mockProject()
    const store = selectProject(project)
    vi.mocked(settingsApi.updateSettings)
      .mockRejectedValueOnce(new Error('general failure'))
      .mockImplementationOnce(async (apiKey: string) => ({
        api_key: apiKey,
        api_key_configured: true,
        api_key_source: 'settings',
      }))
    const projectSaveSpy = vi.spyOn(store, 'saveConfig')
      .mockRejectedValueOnce(new Error('project failure'))
      .mockImplementationOnce(async (_id, config) => savedProject(project, config))
    const wrapper = setupWrapper()
    await flushPromises()

    await wrapper.find('input[placeholder="请输入 DeepSeek API 密钥"]').setValue('sk-new')
    await wrapper.find('input[placeholder="可手动填写尚未创建的目录"]').setValue('D:\\outputs')
    await vi.advanceTimersByTimeAsync(600)
    await flushPromises()

    expect(wrapper.find('[data-testid="general-save-status"]').text()).toContain('保存失败')
    expect(wrapper.find('[data-testid="project-save-status"]').text()).toContain('保存失败')

    await wrapper.find('[data-testid="general-save-retry"]').trigger('click')
    await wrapper.find('[data-testid="project-save-retry"]').trigger('click')
    await flushPromises()

    expect(settingsApi.updateSettings).toHaveBeenCalledTimes(2)
    expect(projectSaveSpy).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[data-testid="general-save-status"]').text()).toContain('已保存')
    expect(wrapper.find('[data-testid="project-save-status"]').text()).toContain('已保存')
  })

  it('reuses the path picker for directory and clinical file fields', async () => {
    const project = mockProject()
    const store = selectProject(project)
    vi.spyOn(store, 'saveConfig').mockImplementation(async (_id, config) =>
      savedProject(project, config)
    )
    const wrapper = setupWrapper()
    await flushPromises()
    const picker = wrapper.findComponent(PathPickerDialog)

    await wrapper.find('[data-testid="browse-image-dir"]').trigger('click')
    expect(picker.props('mode')).toBe('directory')
    picker.vm.$emit('select', 'C:\\study\\images')
    await flushPromises()
    expect(wrapper.find<HTMLInputElement>('input[placeholder="包含影像与分割文件的目录"]')
      .element.value).toBe('C:\\study\\images')

    await wrapper.find('[data-testid="browse-clinical-path"]').trigger('click')
    expect(picker.props('mode')).toBe('file')
    expect(picker.props('acceptedExtensions')).toEqual(['.csv', '.xlsx', '.xls'])

    await wrapper.find('[data-testid="browse-output-dir"]').trigger('click')
    expect(picker.props('mode')).toBe('directory')
  })
})
