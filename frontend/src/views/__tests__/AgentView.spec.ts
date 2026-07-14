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
})
