import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
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

vi.mock('@/api/fs', () => ({
  listDirectory: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ path: '/' }),
  useRouter: () => ({ push: vi.fn() }),
}))

import * as projectsApi from '@/api/projects'
import * as agentApi from '@/api/agent'
import * as fsApi from '@/api/fs'

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

const mountedWrappers: Array<{ unmount: () => void }> = []

function setupWrapper() {
  const pinia = createPinia()
  setActivePinia(pinia)
  // 挂载到 document：el-dropdown 的触发与 teleport 菜单依赖真实文档
  const wrapper = mount(ProjectTree, {
    attachTo: document.body,
    global: {
      plugins: [pinia, ElementPlus],
    },
  })
  mountedWrappers.push(wrapper)
  return wrapper
}

/** 点击行内「更多操作」按钮，再点弹出菜单中指定 testid 的菜单项。
 * 注意：VTU 的 transition stub 会让所有 dropdown 菜单提早出现在 DOM 中
 * （含未展开的行），因此菜单项必须按 data-testid 精确定位。 */
async function clickRowMenuItem(
  wrapper: ReturnType<typeof setupWrapper>,
  triggerTestId: string,
  itemTestId: string
): Promise<void> {
  await wrapper.find(`[data-testid="${triggerTestId}"]`).trigger('click')
  await flushPromises()
  const item = document.querySelector<HTMLElement>(`[data-testid="${itemTestId}"]`)
  expect(item, `未找到菜单项：${itemTestId}`).toBeTruthy()
  item!.click()
  await flushPromises()
}

describe('ProjectTree', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as MessageBoxData)
    vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({ value: '新名称', action: 'confirm' } as any)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: () => {} }) as MessageHandler)
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({ close: () => {} }) as MessageHandler)
  })

  afterEach(() => {
    mountedWrappers.forEach((wrapper) => wrapper.unmount())
    mountedWrappers.length = 0
    // 注意：不要清空 document.body。el-dropdown 的 teleport 容器由 EP 在
    // body 上维护，整体清空会导致后续用例的菜单浮层不再渲染。
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

    // 转圈与提示点都位于「更多操作」按钮区（悬停时换出 ... 按钮）
    const runningActions = rows[0].find('.row-actions')
    expect(runningActions.classes()).toContain('row-actions--indicator')
    expect(runningActions.find('[data-testid="thread-running"]').exists()).toBe(true)
    const finishedActions = rows[1].find('.row-actions')
    expect(finishedActions.classes()).toContain('row-actions--indicator')
    expect(finishedActions.find('[data-testid="thread-finished-dot"]').exists()).toBe(true)
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

    await clickRowMenuItem(wrapper, 'project-more', 'project-menu-rename')

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

    await clickRowMenuItem(wrapper, 'project-more', 'project-menu-delete')

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

    await clickRowMenuItem(wrapper, 'thread-more', 'thread-menu-rename')

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

    await clickRowMenuItem(wrapper, 'thread-more', 'thread-menu-delete')

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

  it('browses folders and fills the create form on confirm', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([])
    vi.mocked(fsApi.listDirectory).mockImplementation(async (path?: string) => {
      if (!path) {
        return {
          path: '/home',
          parent: '/',
          dirs: [{ name: 'data', path: '/home/data' }],
          drives: [],
        }
      }
      if (path === '/home/data') {
        return { path: '/home/data', parent: '/home', dirs: [], drives: [] }
      }
      if (path === '/home') {
        return {
          path: '/home',
          parent: '/',
          dirs: [{ name: 'data', path: '/home/data' }],
          drives: [],
        }
      }
      return {
        path: '/',
        parent: null,
        dirs: [{ name: 'home', path: '/home' }],
        drives: [],
      }
    })

    const wrapper = setupWrapper()
    await flushPromises()

    await wrapper.find('[data-testid="new-project"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="browse-folder"]').trigger('click')
    await flushPromises()

    // 浏览器对话框 append-to-body：内部元素走 document 查询
    const docFind = (testid: string): HTMLElement => {
      const el = document.querySelector<HTMLElement>(`[data-testid="${testid}"]`)
      expect(el, `未找到元素：${testid}`).toBeTruthy()
      return el!
    }

    // 初始列出主目录，点击进入 data
    expect(fsApi.listDirectory).toHaveBeenCalledWith(undefined)
    docFind('browser-dir').click()
    await flushPromises()
    expect(fsApi.listDirectory).toHaveBeenCalledWith('/home/data')

    // 无子目录时显示空态；返回上一级
    expect(document.body.textContent).toContain('无子文件夹')
    docFind('browser-up').click()
    await flushPromises()
    expect(fsApi.listDirectory).toHaveBeenCalledWith('/home')

    // 回到 data 并确认：路径填入、名称为空时取文件夹名
    docFind('browser-dir').click()
    await flushPromises()
    docFind('browser-confirm').click()
    await flushPromises()

    const pathInput = wrapper.find('input[data-testid="project-path-input"]')
    expect((pathInput.element as HTMLInputElement).value).toBe('/home/data')
    const nameInput = wrapper.find('input[placeholder="请输入项目名称"]')
    expect((nameInput.element as HTMLInputElement).value).toBe('data')
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
