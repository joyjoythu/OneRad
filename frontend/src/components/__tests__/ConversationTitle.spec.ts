import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ConversationTitle from '../ConversationTitle.vue'
import { useAgentStore } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'
import type { Project } from '@/api/projects'

const mockProject = (): Project => ({
  id: 'proj-1',
  name: '测试项目',
  path: '/tmp/proj-1',
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

describe('ConversationTitle', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders nothing when no project is selected', () => {
    const wrapper = mount(ConversationTitle)
    expect(wrapper.find('[data-testid="current-conversation-title"]').exists()).toBe(false)
  })

  it('shows the current conversation title', () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.currentThread = {
      id: 'thread-1',
      project_id: 'proj-1',
      title: '肺结节影像组学分析',
      created_at: '2026-01-01',
      updated_at: '2026-01-01',
    }

    const wrapper = mount(ConversationTitle)

    const title = wrapper.find('[data-testid="current-conversation-title"]')
    expect(title.text()).toContain('当前会话')
    expect(title.text()).toContain('肺结节影像组学分析')
  })

  it('falls back to a default title when the thread has no title', () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const wrapper = mount(ConversationTitle)

    const title = wrapper.find('[data-testid="current-conversation-title"]')
    expect(title.text()).toContain('新对话')
  })
})
