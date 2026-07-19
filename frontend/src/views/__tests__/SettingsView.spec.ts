import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import SettingsView from '../SettingsView.vue'
import PathPickerDialog from '@/components/PathPickerDialog.vue'
import { useProjectStore } from '@/stores/project'
import type { AnalysisConfig, Project } from '@/api/projects'

vi.mock('@/api/filesystem', () => ({
  listFilesystemRoots: vi.fn(),
  listFilesystemEntries: vi.fn(),
}))

const mockAnalysis = (overrides: Partial<AnalysisConfig> = {}): AnalysisConfig => ({
  image_dir: 'images',
  clinical_path: 'clinical.xlsx',
  output_dir: './outputs',
  modality: 'auto',
  covariates: 'age',
  model: 'logistic',
  analysis_model: 'logistic',
  api_key: 'sk-old',
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
  })

  afterEach(() => {
    wrappers.forEach((wrapper) => wrapper.unmount())
    wrappers.length = 0
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('prompts to select a project when none is selected', () => {
    const wrapper = setupWrapper()

    expect(wrapper.text()).toContain('请先选择一个项目')
  })

  it('renders the complete project configuration without a save button', () => {
    selectProject(mockProject())
    const wrapper = setupWrapper()

    expect(wrapper.text()).toContain('影像目录')
    expect(wrapper.text()).toContain('临床数据文件')
    expect(wrapper.text()).toContain('输出目录')
    expect(wrapper.text()).toContain('影像模态')
    expect(wrapper.text()).toContain('协变量')
    expect(wrapper.text()).toContain('DeepSeek API 密钥')
    expect(wrapper.text()).toContain('明文写入')
    expect(wrapper.find('[data-testid="settings-save"]').exists()).toBe(false)
    expect(wrapper.findAll('.path-input-row')).toHaveLength(3)
    expect(wrapper.find<HTMLInputElement>('input[placeholder="请输入 DeepSeek API 密钥"]').element.value)
      .toBe('sk-old')
  })

  it('shows a red API key prompt requested by the project new-thread action', async () => {
    const project = mockProject('proj-1', { api_key: '' })
    const store = selectProject(project)
    vi.spyOn(store, 'saveConfig').mockImplementation(async (_id, config) =>
      savedProject(project, config)
    )
    store.requestApiKey('proj-1')

    const wrapper = setupWrapper()
    await flushPromises()

    const hint = wrapper.find('[data-testid="missing-api-key-hint"]')
    expect(hint.exists()).toBe(true)
    expect(hint.classes()).toContain('field-hint--danger')
    expect(hint.text()).toContain('尚未填写 DeepSeek API 密钥')
    expect(document.activeElement).toBe(
      wrapper.find<HTMLInputElement>('input[placeholder="请输入 DeepSeek API 密钥"]').element
    )

    await wrapper.find('input[placeholder="请输入 DeepSeek API 密钥"]').setValue('sk-new')
    await flushPromises()

    expect(wrapper.find('[data-testid="missing-api-key-hint"]').exists()).toBe(false)
    expect(store.apiKeyRequiredProjectId).toBe('proj-1')

    await vi.advanceTimersByTimeAsync(600)
    await flushPromises()

    expect(store.apiKeyRequiredProjectId).toBeNull()
  })

  it('debounces changes for 600ms and saves the full configuration', async () => {
    const project = mockProject()
    const store = selectProject(project)
    const saveSpy = vi.spyOn(store, 'saveConfig').mockImplementation(async (_id, config) =>
      savedProject(project, config)
    )
    const wrapper = setupWrapper()

    await wrapper.find('input[placeholder="请输入 DeepSeek API 密钥"]').setValue('sk-new')
    await vi.advanceTimersByTimeAsync(599)
    expect(saveSpy).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(1)
    await flushPromises()

    expect(saveSpy).toHaveBeenCalledTimes(1)
    expect(saveSpy).toHaveBeenCalledWith('proj-1', {
      ...project.analysis,
      api_key: 'sk-new',
    })
    expect(wrapper.find('[data-testid="settings-save-status"]').text()).toContain('已保存')
  })

  it('flushes a pending change immediately when a field loses focus', async () => {
    const project = mockProject()
    const store = selectProject(project)
    const saveSpy = vi.spyOn(store, 'saveConfig').mockImplementation(async (_id, config) =>
      savedProject(project, config)
    )
    const wrapper = setupWrapper()
    const input = wrapper.find('input[placeholder*="age, sex"]')

    await input.setValue('age, sex')
    await input.trigger('focusout')
    await flushPromises()

    expect(saveSpy).toHaveBeenCalledTimes(1)
    expect(saveSpy.mock.calls[0][1].covariates).toBe('age, sex')
  })

  it('serializes requests and does not let an older response replace the newer draft', async () => {
    const project = mockProject()
    const store = selectProject(project)
    let resolveFirst: ((project: Project) => void) | undefined
    const firstResponse = new Promise<Project>((resolve) => { resolveFirst = resolve })
    const saveSpy = vi.spyOn(store, 'saveConfig')
      .mockReturnValueOnce(firstResponse)
      .mockImplementationOnce(async (_id, config) => savedProject(project, config))
    const wrapper = setupWrapper()
    const input = wrapper.find<HTMLInputElement>('input[placeholder="包含影像与分割文件的目录"]')

    await input.setValue('C:\\study\\first')
    await vi.advanceTimersByTimeAsync(600)
    expect(saveSpy).toHaveBeenCalledTimes(1)

    await input.setValue('C:\\study\\latest')
    await vi.advanceTimersByTimeAsync(600)
    expect(saveSpy).toHaveBeenCalledTimes(1)

    resolveFirst!(savedProject(project, mockAnalysis({ image_dir: 'C:\\study\\first' })))
    await flushPromises()

    expect(saveSpy).toHaveBeenCalledTimes(2)
    expect(saveSpy.mock.calls[1][1].image_dir).toBe('C:\\study\\latest')
    expect(input.element.value).toBe('C:\\study\\latest')
  })

  it('flushes the previous project before switching drafts', async () => {
    const first = mockProject('project-a')
    const second = mockProject('project-b', { image_dir: 'B:\\images', api_key: 'sk-b' })
    const store = useProjectStore()
    store.projects = [first, second]
    store.selectProject(first.id)
    const saveSpy = vi.spyOn(store, 'saveConfig').mockImplementation(async (_id, config) =>
      savedProject(first, config)
    )
    const wrapper = setupWrapper()

    await wrapper.find('input[placeholder="包含影像与分割文件的目录"]').setValue('A:\\new-images')
    store.selectProject(second.id)
    await flushPromises()

    expect(saveSpy).toHaveBeenCalledWith('project-a', expect.objectContaining({
      image_dir: 'A:\\new-images',
    }))
    expect(wrapper.find<HTMLInputElement>('input[placeholder="包含影像与分割文件的目录"]').element.value)
      .toBe('B:\\images')
  })

  it('flushes a pending change when leaving the settings page', async () => {
    const project = mockProject()
    const store = selectProject(project)
    const saveSpy = vi.spyOn(store, 'saveConfig').mockImplementation(async (_id, config) =>
      savedProject(project, config)
    )
    const wrapper = setupWrapper()

    await wrapper.find('input[placeholder="可手动填写尚未创建的目录"]').setValue('E:\\result')
    wrapper.unmount()
    await flushPromises()

    expect(saveSpy).toHaveBeenCalledWith('proj-1', expect.objectContaining({
      output_dir: 'E:\\result',
    }))
  })

  it('shows a retry action after failure and saves the latest draft on retry', async () => {
    const project = mockProject()
    const store = selectProject(project)
    const saveSpy = vi.spyOn(store, 'saveConfig')
      .mockRejectedValueOnce(new Error('network error'))
      .mockImplementationOnce(async (_id, config) => savedProject(project, config))
    const wrapper = setupWrapper()

    await wrapper.find('input[placeholder="可手动填写尚未创建的目录"]').setValue('D:\\outputs')
    await vi.advanceTimersByTimeAsync(600)
    await flushPromises()

    expect(wrapper.find('[data-testid="settings-save-status"]').text()).toContain('保存失败')
    await wrapper.find('[data-testid="settings-save-retry"]').trigger('click')
    await flushPromises()

    expect(saveSpy).toHaveBeenCalledTimes(2)
    expect(saveSpy.mock.calls[1][1].output_dir).toBe('D:\\outputs')
    expect(wrapper.find('[data-testid="settings-save-status"]').text()).toContain('已保存')
  })

  it('reuses the path picker for directory and clinical file fields', async () => {
    const project = mockProject()
    const store = selectProject(project)
    vi.spyOn(store, 'saveConfig').mockImplementation(async (_id, config) =>
      savedProject(project, config)
    )
    const wrapper = setupWrapper()
    const picker = wrapper.findComponent(PathPickerDialog)

    await wrapper.find('[data-testid="browse-image-dir"]').trigger('click')
    expect(picker.props('mode')).toBe('directory')
    picker.vm.$emit('select', 'C:\\study\\images')
    await flushPromises()
    expect(wrapper.find<HTMLInputElement>('input[placeholder="包含影像与分割文件的目录"]').element.value)
      .toBe('C:\\study\\images')

    await wrapper.find('[data-testid="browse-clinical-path"]').trigger('click')
    expect(picker.props('mode')).toBe('file')
    expect(picker.props('acceptedExtensions')).toEqual(['.csv', '.xlsx', '.xls'])
    picker.vm.$emit('select', 'C:\\study\\clinical.xlsx')
    await flushPromises()
    expect(wrapper.find<HTMLInputElement>('input[placeholder="CSV 或 Excel 临床数据文件"]').element.value)
      .toBe('C:\\study\\clinical.xlsx')

    await wrapper.find('[data-testid="browse-output-dir"]').trigger('click')
    expect(picker.props('mode')).toBe('directory')
  })
})
