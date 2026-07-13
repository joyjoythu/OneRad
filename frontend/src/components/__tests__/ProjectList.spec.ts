import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElMessageBox, ElMessage } from 'element-plus'
import ProjectList from '../ProjectList.vue'
import { useProjectStore } from '@/stores/project'
import type { Project } from '@/api/projects'

vi.mock('@/api/projects', () => ({
  listProjects: vi.fn(),
  getProject: vi.fn(),
  createProject: vi.fn(),
  updateConfig: vi.fn(),
  deleteProject: vi.fn(),
}))

import * as api from '@/api/projects'

const mockAnalysis = () => ({
  image_dir: '',
  clinical_path: '',
  output_dir: './outputs',
  modality: 'auto',
  covariates: '',
  model: 'logistic',
  analysis_model: 'logistic',
  api_key: '',
})

const mockProject = (id: string): Project => ({
  id,
  name: `Project ${id}`,
  path: `/tmp/${id}`,
  description: '',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  analysis: mockAnalysis(),
})

describe('ProjectList', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as any)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as any)
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => undefined as any)
  })

  function setupWrapper() {
    const pinia = createPinia()
    setActivePinia(pinia)
    return mount(ProjectList, {
      global: {
        plugins: [pinia, ElementPlus],
      },
    })
  }

  it('renders empty state when there are no projects', async () => {
    vi.mocked(api.listProjects).mockResolvedValue([])
    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('.el-empty').exists()).toBe(true)
    expect(wrapper.text()).toContain('暂无项目')
  })

  it('renders a list of projects', async () => {
    vi.mocked(api.listProjects).mockResolvedValue([
      mockProject('1'),
      mockProject('2'),
    ])
    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.findAll('.project-items li')).toHaveLength(2)
    expect(wrapper.text()).toContain('Project 1')
    expect(wrapper.text()).toContain('Project 2')
  })

  it('opens the create dialog and submits a new project', async () => {
    vi.mocked(api.listProjects).mockResolvedValue([])
    const created = mockProject('new')
    vi.mocked(api.createProject).mockResolvedValue(created)

    const wrapper = setupWrapper()
    await flushPromises()

    await wrapper.find('button').trigger('click')
    await flushPromises()

    expect(wrapper.find('.el-dialog').isVisible()).toBe(true)

    const nameInput = wrapper.find('input[placeholder="请输入项目名称"]')
    const pathInput = wrapper.find('input[placeholder*="本机绝对路径"]')

    await nameInput.setValue('New Project')
    await pathInput.setValue('/tmp/new')

    const createButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('创建'))
    expect(createButton).toBeDefined()
    await createButton!.trigger('click')
    await flushPromises()

    expect(api.createProject).toHaveBeenCalledWith({
      name: 'New Project',
      path: '/tmp/new',
      description: undefined,
    })
    expect(wrapper.text()).toContain('Project new')
    expect(wrapper.find('.el-dialog').isVisible()).toBe(false)
  })

  it('selects a project when clicking a project item', async () => {
    vi.mocked(api.listProjects).mockResolvedValue([
      mockProject('1'),
      mockProject('2'),
    ])
    const wrapper = setupWrapper()
    await flushPromises()

    const store = useProjectStore()
    const items = wrapper.findAll('.project-items li')
    expect(items).toHaveLength(2)

    await items[1].trigger('click')
    await flushPromises()

    expect(store.currentProject?.id).toBe('2')
  })

  it('deletes a project after confirming', async () => {
    vi.mocked(api.listProjects).mockResolvedValue([
      mockProject('1'),
      mockProject('2'),
    ])
    vi.mocked(api.deleteProject).mockResolvedValue(undefined)

    const wrapper = setupWrapper()
    await flushPromises()

    const deleteButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('删除'))
    expect(deleteButton).toBeDefined()
    await deleteButton!.trigger('click')
    await flushPromises()

    expect(ElMessageBox.confirm).toHaveBeenCalled()
    expect(api.deleteProject).toHaveBeenCalledWith('1')
    expect(wrapper.findAll('.project-items li')).toHaveLength(1)
  })
})
