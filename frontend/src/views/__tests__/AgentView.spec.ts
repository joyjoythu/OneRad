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
})
