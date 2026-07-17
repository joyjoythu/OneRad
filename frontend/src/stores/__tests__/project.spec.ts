import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useProjectStore } from '../project'
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

describe('useProjectStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.resetAllMocks()
  })

  it('loads projects from the API', async () => {
    vi.mocked(api.listProjects).mockResolvedValue([mockProject('1')])
    const store = useProjectStore()

    await store.loadProjects()

    expect(api.listProjects).toHaveBeenCalled()
    expect(store.projects).toHaveLength(1)
    expect(store.projects[0].id).toBe('1')
  })

  it('tracks loading state while fetching projects', async () => {
    vi.mocked(api.listProjects).mockResolvedValue([mockProject('1')])
    const store = useProjectStore()

    const promise = store.loadProjects()
    expect(store.loading).toBe(true)
    await promise
    expect(store.loading).toBe(false)
  })

  it('selects a project and clones its analysis config', () => {
    const store = useProjectStore()
    store.projects = [mockProject('1')]

    store.selectProject('1')

    expect(store.currentProject?.id).toBe('1')
    expect(store.currentConfig).toEqual(mockAnalysis())
    expect(store.currentConfig).not.toBe(store.currentProject?.analysis)
  })

  it('creates a project, prepends it and selects it', async () => {
    const created = mockProject('2')
    vi.mocked(api.createProject).mockResolvedValue(created)
    const store = useProjectStore()

    const result = await store.createProject({ name: 'New', path: 'new' })

    expect(api.createProject).toHaveBeenCalledWith({ name: 'New', path: 'new' })
    expect(store.projects[0].id).toBe('2')
    expect(result.id).toBe('2')
    expect(store.currentProject?.id).toBe('2')
  })

  it('saves config and refreshes the current project', async () => {
    const original = mockProject('1')
    const updated: Project = {
      ...original,
      analysis: { ...original.analysis, modality: 'CT' },
    }
    vi.mocked(api.updateConfig).mockResolvedValue(updated)

    const store = useProjectStore()
    store.projects = [original]
    store.selectProject('1')
    const cfg = { ...store.currentConfig!, modality: 'CT' }

    const result = await store.saveConfig('1', cfg)

    expect(api.updateConfig).toHaveBeenCalledWith('1', cfg)
    expect(result.analysis.modality).toBe('CT')
    expect(store.currentProject?.analysis.modality).toBe('CT')
    expect(store.currentConfig?.modality).toBe('CT')
  })

  it('uses the persisted api_key from the server response after saving', async () => {
    // api_key 现在随 project.yaml 持久化，保存后直接使用后端返回的配置。
    const persisted = mockProject('1')
    persisted.analysis = { ...persisted.analysis, api_key: 'secret-key' }
    vi.mocked(api.updateConfig).mockResolvedValue(persisted)

    const store = useProjectStore()
    store.projects = [mockProject('1')]
    store.selectProject('1')
    const cfg = { ...store.currentConfig!, api_key: 'secret-key' }

    await store.saveConfig('1', cfg)

    expect(store.currentConfig?.api_key).toBe('secret-key')
  })

  it('deletes a project and clears the current selection', async () => {
    vi.mocked(api.deleteProject).mockResolvedValue(undefined)
    const store = useProjectStore()
    store.projects = [mockProject('1')]
    store.selectProject('1')

    await store.deleteProject('1')

    expect(api.deleteProject).toHaveBeenCalledWith('1')
    expect(store.projects).toHaveLength(0)
    expect(store.currentProject).toBeNull()
    expect(store.currentConfig).toBeNull()
  })
})
