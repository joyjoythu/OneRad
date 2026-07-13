import { describe, it, expect, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import AnalysisForm from '../AnalysisForm.vue'
import { useProjectStore } from '@/stores/project'
import type { Project, AnalysisConfig } from '@/api/projects'

const mockConfig = (): AnalysisConfig => ({
  image_dir: '/data/images',
  clinical_path: '/data/clinical.csv',
  output_dir: './outputs',
  modality: 'CT',
  covariates: 'age,sex',
  model: 'random_forest',
  analysis_model: 'random_forest',
  llm_model: 'deepseek-v4-pro',
  api_key: 'secret-key',
})

const mockProject = (): Project => ({
  id: 'proj-1',
  name: '测试项目',
  path: '/tmp/proj-1',
  description: '',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  analysis: mockConfig(),
})

function setupWrapper(config: AnalysisConfig | null = null) {
  return mount(AnalysisForm, {
    props: { config },
    global: {
      plugins: [ElementPlus],
    },
  })
}

async function selectProject() {
  const store = useProjectStore()
  const project = mockProject()
  store.projects = [project]
  store.selectProject(project.id)
  await flushPromises()
  return { store, project }
}

describe('AnalysisForm', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders placeholder when no project is selected', async () => {
    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('.el-empty').exists()).toBe(true)
    expect(wrapper.text()).toContain('请选择一个项目')
  })

  it('renders all config fields when a project is selected', async () => {
    const { store } = await selectProject()
    const wrapper = setupWrapper(store.currentConfig)
    await flushPromises()

    expect(wrapper.find('.el-empty').exists()).toBe(false)
    expect(wrapper.find('input[placeholder="请输入影像目录路径"]').exists()).toBe(true)
    expect(wrapper.find('input[placeholder="请输入临床数据文件路径"]').exists()).toBe(true)
    expect(wrapper.find('input[placeholder="请输入输出目录路径"]').exists()).toBe(true)
    expect(wrapper.find('input[placeholder="请输入协变量，多个用逗号分隔"]').exists()).toBe(true)

    const selects = wrapper.findAll('.el-select')
    expect(selects.length).toBeGreaterThanOrEqual(2)

    expect(wrapper.find('input[placeholder="请输入 API 密钥"]').exists()).toBe(true)
  })

  it('emits save event when clicking the save button', async () => {
    const { store } = await selectProject()
    const wrapper = setupWrapper(store.currentConfig)
    await flushPromises()

    const saveButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('保存配置'))
    expect(saveButton).toBeDefined()
    await saveButton!.trigger('click')

    expect(wrapper.emitted('save')).toHaveLength(1)
  })

  it('emits run event when clicking the start button', async () => {
    const { store } = await selectProject()
    const wrapper = setupWrapper(store.currentConfig)
    await flushPromises()

    const runButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('开始分析'))
    expect(runButton).toBeDefined()
    await runButton!.trigger('click')

    expect(wrapper.emitted('run')).toHaveLength(1)
  })

  it('emits update:config when a field is edited', async () => {
    const { store } = await selectProject()
    const wrapper = setupWrapper(store.currentConfig)
    await flushPromises()

    const input = wrapper.find('input[placeholder="请输入影像目录路径"]')
    await input.setValue('/new/images')
    await flushPromises()

    const events = wrapper.emitted('update:config')
    expect(events).toBeDefined()
    expect(events!.length).toBeGreaterThan(0)
    expect((events!.at(-1) as [AnalysisConfig])[0].image_dir).toBe('/new/images')
  })
})
