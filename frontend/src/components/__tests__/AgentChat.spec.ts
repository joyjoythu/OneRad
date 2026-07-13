import { describe, it, expect, beforeEach } from 'vitest'
import { mount, flushPromises, VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import AgentChat from '../AgentChat.vue'
import { DEFAULT_AGENT_MODEL } from '@/api/agent'
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
    api_key: '',
  },
})

function setupWrapper() {
  return mount(AgentChat, {
    global: {
      plugins: [ElementPlus],
    },
  })
}

describe('AgentChat', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders placeholder when no project is selected', async () => {
    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('.el-empty').exists()).toBe(true)
    expect(wrapper.text()).toContain('请先选择一个项目')
  })

  it('renders messages with correct role styles', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [
      { role: 'user', content: 'Hello' },
      { role: 'assistant', content: 'Hi there' },
      { role: 'tool', content: 'result', tool_call_id: 'call-1' },
    ]

    const wrapper = setupWrapper()
    await flushPromises()

    const rows = wrapper.findAll('.message-row')
    expect(rows).toHaveLength(3)

    expect(rows[0].classes()).toContain('message-row--user')
    expect(rows[0].find('.message-bubble--user').exists()).toBe(true)
    expect(rows[0].text()).toContain('Hello')

    expect(rows[1].classes()).toContain('message-row--assistant')
    expect(rows[1].find('.message-bubble--assistant').exists()).toBe(true)
    expect(rows[1].text()).toContain('Hi there')

    expect(rows[2].classes()).toContain('message-row--tool')
    expect(rows[2].find('.message-bubble--tool').exists()).toBe(true)
    expect(rows[2].text()).toContain('result')
  })

  it('emits send-message when clicking the send button', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const wrapper = setupWrapper()
    await flushPromises()

    const textarea = wrapper.find('textarea')
    await textarea.setValue('Test message')

    const sendButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('发送'))
    expect(sendButton).toBeDefined()
    await sendButton!.trigger('click')
    await flushPromises()

    expect(wrapper.emitted('send-message')).toHaveLength(1)
    expect(wrapper.emitted('send-message')![0]).toEqual(['Test message'])
    expect((textarea.element as HTMLTextAreaElement).value).toBe('')
  })

  it('emits send-message when pressing Enter', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const wrapper = setupWrapper()
    await flushPromises()

    const textarea = wrapper.find('textarea')
    await textarea.setValue('Enter message')
    await textarea.trigger('keydown', { key: 'Enter', shiftKey: false })
    await flushPromises()

    expect(wrapper.emitted('send-message')).toHaveLength(1)
    expect(wrapper.emitted('send-message')![0]).toEqual(['Enter message'])
  })

  it('does not emit send-message on Enter while IME is composing', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const wrapper = setupWrapper()
    await flushPromises()

    const textarea = wrapper.find('textarea')
    await textarea.setValue('Composing')
    await textarea.trigger('keydown', { key: 'Enter', shiftKey: false, isComposing: true })
    await flushPromises()

    expect(wrapper.emitted('send-message')).toBeUndefined()
  })

  it('does not emit send-message on Shift+Enter', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const wrapper = setupWrapper()
    await flushPromises()

    const textarea = wrapper.find('textarea')
    await textarea.setValue('Line 1')
    await textarea.trigger('keydown', { key: 'Enter', shiftKey: true })
    await flushPromises()

    expect(wrapper.emitted('send-message')).toBeUndefined()
  })

  it('enables the input and model selector when a project is selected without a thread', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const wrapper = setupWrapper()
    await flushPromises()

    const textarea = wrapper.find('textarea')
    expect(textarea.attributes('disabled')).toBeUndefined()

    const select = wrapper.findComponent('.model-selector') as VueWrapper<any>
    expect(select.props('disabled')).toBeFalsy()
  })

  it('defaults the model selector to DEFAULT_AGENT_MODEL', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'

    const wrapper = setupWrapper()
    await flushPromises()

    const select = wrapper.findComponent('.model-selector') as VueWrapper<any>
    expect(select.exists()).toBe(true)
    expect(select.props('modelValue')).toBe(DEFAULT_AGENT_MODEL)
  })

  it('emits update:model when the model selector changes', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'

    const wrapper = setupWrapper()
    await flushPromises()

    const select = wrapper.findComponent('.model-selector') as VueWrapper<any>
    select.vm.$emit('change', 'deepseek-v4-pro')
    await flushPromises()

    expect(wrapper.emitted('update:model')).toHaveLength(1)
    expect(wrapper.emitted('update:model')![0]).toEqual(['deepseek-v4-pro'])
  })
})
