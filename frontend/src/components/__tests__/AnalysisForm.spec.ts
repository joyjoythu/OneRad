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

describe('AnalysisForm', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  function setupWrapper() {
    return mount(AnalysisForm, {
      global: {
        plugins: [ElementPlus],
      },
    })
  }

  it('renders placeholder when no project is selected', async () => {
    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('.el-empty').exists()).toBe(true)
    expect(wrapper.text()).toContain('请选择一个项目')
  })

  it('renders all config fields when a project is selected', async () => {
    const store = useProjectStore()
    const project = mockProject()
    store.currentProject = project
    store.currentConfig = { ...project.analysis }

    const wrapper = setupWrapper()
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

  it('emits run event when clicking the start button', async () => {
    const store = useProjectStore()
    const project = mockProject()
    store.currentProject = project
    store.currentConfig = { ...project.analysis }

    const wrapper = setupWrapper()
    await flushPromises()

    const runButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('开始分析'))
    expect(runButton).toBeDefined()
    await runButton!.trigger('click')

    expect(wrapper.emitted('run')).toHaveLength(1)
  })
})
