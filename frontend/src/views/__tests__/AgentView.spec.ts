import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import AgentView from '../AgentView.vue'
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
    api_key: '',
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

  it('persists thread list collapse state in localStorage', async () => {
    const projectStore = useProjectStore()
    const agentStore = useAgentStore()
    vi.spyOn(agentStore, 'listThreads').mockResolvedValue(undefined)
    vi.spyOn(agentStore, 'loadThread').mockResolvedValue(undefined)

    const project = mockProject('1')
    projectStore.projects = [project]
    projectStore.selectProject(project.id)

    const wrapper = setupWrapper()

    await flushPromises()

    const collapseButton = wrapper.find('.thread-list-header button')
    expect(collapseButton.exists()).toBe(true)

    await collapseButton.trigger('click')
    expect(localStorage.getItem('onerad:agent:threadListCollapsed')).toBe('true')
    expect(wrapper.find('.thread-list').classes()).toContain('thread-list--collapsed')

    await collapseButton.trigger('click')
    expect(localStorage.getItem('onerad:agent:threadListCollapsed')).toBe('false')
    expect(wrapper.find('.thread-list').classes()).not.toContain('thread-list--collapsed')
  })

  it('restores thread list collapse state from localStorage on mount', async () => {
    localStorage.setItem('onerad:agent:threadListCollapsed', 'true')

    const projectStore = useProjectStore()
    const agentStore = useAgentStore()
    vi.spyOn(agentStore, 'listThreads').mockResolvedValue(undefined)
    vi.spyOn(agentStore, 'loadThread').mockResolvedValue(undefined)

    const project = mockProject('1')
    projectStore.projects = [project]
    projectStore.selectProject(project.id)

    const wrapper = setupWrapper()

    await flushPromises()

    expect(wrapper.find('.thread-list').classes()).toContain('thread-list--collapsed')
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
})
