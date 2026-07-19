import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import AgentView from '../AgentView.vue'
import AgentChat from '@/components/AgentChat.vue'
import { useProjectStore } from '@/stores/project'
import { useAgentStore } from '@/stores/agent'
import type { Project } from '@/api/projects'

const mockProject = (id: string): Project => ({
  id,
  name: `Project ${id}`,
  path: `/tmp/${id}`,
  description: '',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  analysis: {
    image_dir: '',
    clinical_path: '',
    output_dir: './outputs',
    modality: 'auto',
    covariates: '',
    model: 'logistic',
    analysis_model: 'logistic',
  },
})

function setupWrapper() {
  return mount(AgentView, {
    global: {
      plugins: [ElementPlus],
    },
  })
}

describe('AgentView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('resets the agent thread when the selected project changes', async () => {
    const projectStore = useProjectStore()
    const agentStore = useAgentStore()
    vi.spyOn(agentStore, 'listThreads').mockResolvedValue(undefined)
    vi.spyOn(agentStore, 'loadThread').mockResolvedValue(undefined)
    const resetThreadSpy = vi.spyOn(agentStore, 'resetThread')

    projectStore.currentProject = mockProject('1')
    setupWrapper()
    await flushPromises()

    resetThreadSpy.mockClear()

    projectStore.currentProject = mockProject('2')
    await flushPromises()

    expect(resetThreadSpy).toHaveBeenCalled()
  })

  it('shows the empty state in the side panel when no approval is pending', async () => {
    const projectStore = useProjectStore()
    const agentStore = useAgentStore()
    vi.spyOn(agentStore, 'listThreads').mockResolvedValue(undefined)
    vi.spyOn(agentStore, 'loadThread').mockResolvedValue(undefined)

    projectStore.currentProject = mockProject('1')
    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.text()).toContain('暂无待审批的计划/文件')
  })

  it('runs quick actions through the same agent message pipeline', async () => {
    const projectStore = useProjectStore()
    const agentStore = useAgentStore()
    projectStore.projects = [mockProject('1')]
    projectStore.selectProject('1')

    vi.spyOn(agentStore, 'listThreads').mockResolvedValue(undefined)
    vi.spyOn(agentStore, 'loadThread').mockResolvedValue(undefined)
    const ensureSpy = vi.spyOn(agentStore, 'ensureThread').mockResolvedValue('thread-quick')
    const sendSpy = vi.spyOn(agentStore, 'sendMessage').mockResolvedValue(undefined)

    const wrapper = setupWrapper()
    await flushPromises()

    wrapper.findComponent(AgentChat).vm.$emit('quick-action', '快捷分析指令')
    await flushPromises()

    expect(ensureSpy).toHaveBeenCalledWith('1')
    expect(sendSpy).toHaveBeenCalledWith('快捷分析指令', 'user')
  })

  it('shows the read-only script panel in the side panel for python_script interrupts', async () => {
    const projectStore = useProjectStore()
    const agentStore = useAgentStore()
    vi.spyOn(agentStore, 'listThreads').mockResolvedValue(undefined)
    vi.spyOn(agentStore, 'loadThread').mockResolvedValue(undefined)

    projectStore.currentProject = mockProject('1')
    const wrapper = setupWrapper()
    await flushPromises()

    // 生产中 interrupt 状态在 mount 后由 loadThread/SSE 写入
    agentStore.interrupt = 'python_script'
    agentStore.pendingScript = {
      tool_call_id: 'tc-1',
      code: "print('hello')",
      risk_level: 'low' as const,
      description: '打印测试',
    }
    await flushPromises()

    const sidePanel = wrapper.find('.agent-side-panel')
    expect(sidePanel.text()).toContain('待执行 Python 脚本')
    expect(sidePanel.text()).toContain("print('hello')")
  })

  it('collapses the side panel and persists state in localStorage', async () => {
    const projectStore = useProjectStore()
    const agentStore = useAgentStore()
    vi.spyOn(agentStore, 'listThreads').mockResolvedValue(undefined)
    vi.spyOn(agentStore, 'loadThread').mockResolvedValue(undefined)

    projectStore.currentProject = mockProject('1')
    const wrapper = setupWrapper()
    await flushPromises()

    const toggle = wrapper.find('[data-testid="side-panel-toggle"]')
    expect(toggle.exists()).toBe(true)

    await toggle.trigger('click')
    expect(localStorage.getItem('onerad:agent:sidePanelCollapsed')).toBe('true')
    expect(wrapper.find('.agent-side-panel').classes()).toContain(
      'agent-side-panel--collapsed'
    )

    await toggle.trigger('click')
    expect(localStorage.getItem('onerad:agent:sidePanelCollapsed')).toBe('false')
    expect(wrapper.find('.agent-side-panel').classes()).not.toContain(
      'agent-side-panel--collapsed'
    )
  })

  it('restores side panel collapse state from localStorage on mount', async () => {
    localStorage.setItem('onerad:agent:sidePanelCollapsed', 'true')

    const projectStore = useProjectStore()
    const agentStore = useAgentStore()
    vi.spyOn(agentStore, 'listThreads').mockResolvedValue(undefined)
    vi.spyOn(agentStore, 'loadThread').mockResolvedValue(undefined)

    projectStore.currentProject = mockProject('1')
    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('.agent-side-panel').classes()).toContain(
      'agent-side-panel--collapsed'
    )
  })

  it('loads the preferred thread instead of the latest when one is set', async () => {
    const projectStore = useProjectStore()
    const agentStore = useAgentStore()
    const t1 = {
      id: 't1',
      project_id: '2',
      title: 'Latest',
      created_at: '2026-01-01',
      updated_at: '2026-01-03',
    }
    const t2 = { ...t1, id: 't2', title: 'Preferred', updated_at: '2026-01-02' }
    vi.spyOn(agentStore, 'listThreads').mockImplementation(async () => {
      agentStore.threads = [t1, t2]
    })
    const loadSpy = vi.spyOn(agentStore, 'loadThread').mockResolvedValue(undefined)

    // 用 selectProject 而不是直接赋值，保证 currentConfig 被设置（watcher 依赖）
    projectStore.projects = [mockProject('1'), mockProject('2')]
    projectStore.selectProject('1')
    setupWrapper()
    await flushPromises()

    agentStore.preferredThreadId = 't2'
    projectStore.selectProject('2')
    await flushPromises()

    expect(loadSpy).toHaveBeenCalledWith('t2')
    expect(agentStore.preferredThreadId).toBeNull()
  })

  it('does not reload when the current thread already belongs to the project', async () => {
    const projectStore = useProjectStore()
    const agentStore = useAgentStore()
    const listSpy = vi.spyOn(agentStore, 'listThreads').mockResolvedValue(undefined)
    vi.spyOn(agentStore, 'loadThread').mockResolvedValue(undefined)
    const reconnectSpy = vi.spyOn(agentStore, 'reconnect').mockResolvedValue(undefined)

    agentStore.threadId = 't1'
    agentStore.currentThread = {
      id: 't1',
      project_id: '1',
      title: 'Open',
      created_at: '2026-01-01',
      updated_at: '2026-01-02',
    }

    projectStore.currentProject = mockProject('1')
    setupWrapper()
    await flushPromises()

    expect(listSpy).not.toHaveBeenCalled()
    expect(reconnectSpy).toHaveBeenCalled()
  })
})
