import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElMessageBox, ElMessage, MessageBoxData, MessageHandler } from 'element-plus'
import ProjectTree from '../ProjectTree.vue'
import { useProjectStore } from '@/stores/project'
import { useAgentStore } from '@/stores/agent'
import type { Project } from '@/api/projects'
import type { ThreadSummary } from '@/api/agent'

vi.mock('@/api/projects', () => ({
  listProjects: vi.fn(),
  getProject: vi.fn(),
  createProject: vi.fn(),
  updateConfig: vi.fn(),
  deleteProject: vi.fn(),
  renameProject: vi.fn(),
}))

vi.mock('@/api/agent', () => ({
  createThread: vi.fn(),
  listThreads: vi.fn(),
  renameThread: vi.fn(),
  deleteThread: vi.fn(),
  resumeThread: vi.fn(),
  getThread: vi.fn(),
  sendMessage: vi.fn(),
  confirm: vi.fn(),
  cancel: vi.fn(),
  stopAgent: vi.fn(),
  setAutoApprove: vi.fn(),
  updatePlan: vi.fn(),
  connectAgentEvents: vi.fn(),
  DEFAULT_AGENT_MODEL: 'deepseek-v4-flash',
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ path: '/' }),
  useRouter: () => ({ push: vi.fn() }),
}))

import * as projectsApi from '@/api/projects'
import * as agentApi from '@/api/agent'

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

const mockThread = (id: string, projectId: string): ThreadSummary => ({
  id,
  project_id: projectId,
  title: `Thread ${id}`,
  llm_model: 'deepseek-v4-flash',
  created_at: '2026-01-01',
  updated_at: '2026-01-02',
})

function setupWrapper() {
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(ProjectTree, {
    global: {
      plugins: [pinia, ElementPlus],
    },
  })
}

describe('ProjectTree', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as MessageBoxData)
    vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({ value: '新名称', action: 'confirm' } as any)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: () => {} }) as MessageHandler)
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({ close: () => {} }) as MessageHandler)
  })

  it('renders empty state when there are no projects', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([])
    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.text()).toContain('暂无项目')
  })

  it('renders projects; clicking selects, expands and lazily loads threads', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([mockProject('1'), mockProject('2')])
    vi.mocked(agentApi.listThreads).mockResolvedValue({ threads: [mockThread('t1', '2')] })

    const wrapper = setupWrapper()
    await flushPromises()

    const rows = wrapper.findAll('[data-testid="project-row"]')
    expect(rows).toHaveLength(2)
    expect(wrapper.findAll('[data-testid="thread-row"]')).toHaveLength(0)

    await rows[1].trigger('click')
    await flushPromises()

    const projectStore = useProjectStore()
    expect(projectStore.currentProject?.id).toBe('2')
    expect(agentApi.listThreads).toHaveBeenCalledWith('2')
    expect(wrapper.findAll('[data-testid="thread-row"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('Thread t1')
  })

  it('shows a spinner for running threads and a dot for finished ones', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([mockProject('1')])
    vi.mocked(agentApi.listThreads).mockResolvedValue({
      threads: [mockThread('t1', '1'), mockThread('t2', '1')],
    })

    const wrapper = setupWrapper()
    await flushPromises()

    await wrapper.find('[data-testid="project-row"]').trigger('click')
    await flushPromises()

    const agentStore = useAgentStore()
    agentStore.runningThreadIds.add('t1')
    agentStore.finishedThreadIds.add('t2')
    await flushPromises()

    const rows = wrapper.findAll('[data-testid="thread-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[0].find('[data-testid="thread-running"]').exists()).toBe(true)
    expect(rows[0].find('[data-testid="thread-finished-dot"]').exists()).toBe(false)
    expect(rows[1].find('[data-testid="thread-running"]').exists()).toBe(false)
    expect(rows[1].find('[data-testid="thread-finished-dot"]').exists()).toBe(true)
  })

  it('collapses when clicking the current expanded project', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([mockProject('1')])
    vi.mocked(agentApi.listThreads).mockResolvedValue({ threads: [mockThread('t1', '1')] })

    const wrapper = setupWrapper()
    await flushPromises()

    const row = wrapper.find('[data-testid="project-row"]')
    await row.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-testid="thread-row"]')).toHaveLength(1)

    await row.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-testid="thread-row"]')).toHaveLength(0)
  })

  it('loads a thread of the current project directly on click', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([mockProject('1')])
    vi.mocked(agentApi.listThreads).mockResolvedValue({ threads: [mockThread('t1', '1')] })
    vi.mocked(agentApi.resumeThread).mockResolvedValue({
      thread_id: 't1',
      messages: [],
      interrupt_type: null,
      operation_log: [],
      pending_plan: null,
      pending_command: null,
      pending_script: null,
    })

    const wrapper = setupWrapper()
    await flushPromises()

    await wrapper.find('[data-testid="project-row"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="thread-row"]').trigger('click')
    await flushPromises()

    expect(agentApi.resumeThread).toHaveBeenCalledWith('t1', expect.objectContaining({
      api_key: '',
      llm_model: 'deepseek-v4-flash',
    }))
    const agentStore = useAgentStore()
    expect(agentStore.preferredThreadId).toBeNull()
  })

  it('defers loading a thread of another project via preferredThreadId', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([mockProject('1'), mockProject('2')])
    vi.mocked(agentApi.listThreads).mockImplementation(async (projectId: string) => ({
      threads: projectId === '2' ? [mockThread('t9', '2')] : [],
    }))

    const wrapper = setupWrapper()
    await flushPromises()

    const rows = wrapper.findAll('[data-testid="project-row"]')
    await rows[0].trigger('click') // 选中并展开项目 1
    await flushPromises()
    await rows[1].trigger('click') // 选中并展开项目 2
    await flushPromises()
    await rows[0].trigger('click') // 切回项目 1（项目 2 保持展开）
    await flushPromises()

    // 此时项目 2 展开但非当前项目，点击其对话走 preferredThreadId 延迟加载
    await wrapper.find('[data-testid="thread-row"]').trigger('click')
    await flushPromises()

    const agentStore = useAgentStore()
    expect(agentStore.preferredThreadId).toBe('t9')
    expect(agentApi.resumeThread).not.toHaveBeenCalled()
    expect(useProjectStore().currentProject?.id).toBe('2')
  })

  it('renames a project via prompt', async () => {
    const project = mockProject('1')
    vi.mocked(projectsApi.listProjects).mockResolvedValue([project])
    vi.mocked(projectsApi.renameProject).mockResolvedValue({ ...project, name: '新名称' })

    const wrapper = setupWrapper()
    await flushPromises()

    await wrapper.find('[data-testid="project-rename"]').trigger('click')
    await flushPromises()

    expect(ElMessageBox.prompt).toHaveBeenCalled()
    expect(projectsApi.renameProject).toHaveBeenCalledWith('1', '新名称')
  })

  it('deletes a project after confirming', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([mockProject('1')])
    vi.mocked(projectsApi.deleteProject).mockResolvedValue(undefined)
    vi.mocked(agentApi.listThreads).mockResolvedValue({ threads: [] })

    const wrapper = setupWrapper()
    await flushPromises()

    // 点击删除前先展开项目造出缓存
    await wrapper.find('[data-testid="project-row"]').trigger('click')
    await flushPromises()

    await wrapper.find('[data-testid="project-delete"]').trigger('click')
    await flushPromises()

    expect(ElMessageBox.confirm).toHaveBeenCalled()
    expect(projectsApi.deleteProject).toHaveBeenCalledWith('1')
    const agentStore = useAgentStore()
    expect(agentStore.threadsByProject['1']).toBeUndefined()
  })

  it('renames a thread via prompt', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([mockProject('1')])
    vi.mocked(agentApi.listThreads).mockResolvedValue({ threads: [mockThread('t1', '1')] })
    vi.mocked(agentApi.renameThread).mockResolvedValue({ thread: mockThread('t1', '1') })

    const wrapper = setupWrapper()
    await flushPromises()
    await wrapper.find('[data-testid="project-row"]').trigger('click')
    await flushPromises()

    await wrapper.find('[data-testid="thread-rename"]').trigger('click')
    await flushPromises()

    expect(agentApi.renameThread).toHaveBeenCalledWith('t1', '新名称')
  })

  it('deletes a thread after confirming', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([mockProject('1')])
    vi.mocked(agentApi.listThreads).mockResolvedValue({ threads: [mockThread('t1', '1')] })
    vi.mocked(agentApi.deleteThread).mockResolvedValue(undefined)

    const wrapper = setupWrapper()
    await flushPromises()
    await wrapper.find('[data-testid="project-row"]').trigger('click')
    await flushPromises()

    await wrapper.find('[data-testid="thread-delete"]').trigger('click')
    await flushPromises()

    expect(agentApi.deleteThread).toHaveBeenCalledWith('t1')
  })

  it('creates a project through the dialog', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([])
    const created = mockProject('new')
    vi.mocked(projectsApi.createProject).mockResolvedValue(created)

    const wrapper = setupWrapper()
    await flushPromises()

    await wrapper.find('[data-testid="new-project"]').trigger('click')
    await flushPromises()

    await wrapper.find('input[placeholder="请输入项目名称"]').setValue('New Project')
    await wrapper.find('input[placeholder*="本机绝对路径"]').setValue('/tmp/new')

    const createButton = wrapper.findAll('button').find((b) => b.text().includes('创建'))
    await createButton!.trigger('click')
    await flushPromises()

    expect(projectsApi.createProject).toHaveBeenCalledWith({
      name: 'New Project',
      path: '/tmp/new',
      description: undefined,
    })
  })

  it('creates a thread in the clicked project via its plus action', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([mockProject('1')])
    vi.mocked(agentApi.createThread).mockResolvedValue({ thread_id: 't-new' })
    vi.mocked(agentApi.listThreads).mockResolvedValue({ threads: [] })

    const wrapper = setupWrapper()
    await flushPromises()

    await wrapper.find('[data-testid="project-new-thread"]').trigger('click')
    await flushPromises()

    expect(agentApi.createThread).toHaveBeenCalledWith('1', expect.objectContaining({
      llm_model: 'deepseek-v4-flash',
    }))
    expect(useProjectStore().currentProject?.id).toBe('1')
  })

  it('warns on 新建任务 when no project is selected', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([mockProject('1')])

    const wrapper = setupWrapper()
    await flushPromises()

    await wrapper.find('[data-testid="new-task"]').trigger('click')
    await flushPromises()

    expect(ElMessage.warning).toHaveBeenCalled()
    expect(agentApi.createThread).not.toHaveBeenCalled()
  })

  it('creates the thread before switching project via another project\'s plus action', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([mockProject('1'), mockProject('2')])
    let resolveCreate: (v: { thread_id: string }) => void = () => {}
    vi.mocked(agentApi.createThread).mockImplementation(
      () => new Promise((resolve) => { resolveCreate = resolve })
    )
    vi.mocked(agentApi.listThreads).mockResolvedValue({ threads: [] })

    const wrapper = setupWrapper()
    await flushPromises()

    const projectStore = useProjectStore()
    projectStore.selectProject('1')

    const rows = wrapper.findAll('[data-testid="project-row"]')
    await rows[1].find('[data-testid="project-new-thread"]').trigger('click')
    await flushPromises()

    // 创建未完成前不切换项目
    expect(projectStore.currentProject?.id).toBe('1')

    resolveCreate({ thread_id: 't-new' })
    await flushPromises()

    expect(agentApi.createThread).toHaveBeenCalledWith('2', expect.objectContaining({
      llm_model: 'deepseek-v4-flash',
    }))
    expect(projectStore.currentProject?.id).toBe('2')
  })

  it('shows an inline retry when loading threads fails and recovers on click', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([mockProject('1')])
    vi.mocked(agentApi.listThreads).mockRejectedValueOnce(new Error('boom'))

    const wrapper = setupWrapper()
    await flushPromises()

    await wrapper.find('[data-testid="project-row"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="thread-retry"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('暂无会话')

    vi.mocked(agentApi.listThreads).mockResolvedValueOnce({ threads: [mockThread('t1', '1')] })
    await wrapper.find('[data-testid="thread-retry"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="thread-retry"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-testid="thread-row"]')).toHaveLength(1)
  })
})
