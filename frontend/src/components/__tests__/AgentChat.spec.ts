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
    expect((textarea.element as HTMLTextAreaElement).value).toBe('Test message')
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
    select.vm.$emit('update:modelValue', 'deepseek-v4-pro')
    await flushPromises()

    expect(wrapper.emitted('update:model')).toHaveLength(1)
    expect(wrapper.emitted('update:model')![0]).toEqual(['deepseek-v4-pro'])
  })

  it('disables input while the agent is busy', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.busy = true

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('textarea').attributes('disabled')).toBeDefined()
  })

  it('shows a stop button while busy and emits stop on click', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.busy = true

    const wrapper = setupWrapper()
    await flushPromises()

    const stopButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('停止'))
    expect(stopButton).toBeDefined()
    const sendButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('发送'))
    expect(sendButton).toBeUndefined()

    await stopButton!.trigger('click')
    expect(wrapper.emitted('stop')).toHaveLength(1)
  })

  it('shows the send button and no stop button when idle', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'

    const wrapper = setupWrapper()
    await flushPromises()

    const sendButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('发送'))
    expect(sendButton).toBeDefined()
    const stopButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('停止'))
    expect(stopButton).toBeUndefined()
  })

  it('keeps the status bar mounted but hidden when idle to avoid layout shift', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [{ role: 'user', content: 'hi' }]
    agentStore.busy = false

    const wrapper = setupWrapper()
    await flushPromises()

    // 状态栏必须常驻占位（仅隐藏），否则出现/消失会改变消息列表高度，
    // 导致贴底滚动时内容被挤压回弹。
    const status = wrapper.find('.chat-status')
    expect(status.exists()).toBe(true)
    expect(status.classes()).toContain('chat-status--idle')
    expect(status.text()).not.toContain('正在思考')
  })

  it('shows a thinking indicator while the agent is busy', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [{ role: 'user', content: 'hi' }]
    agentStore.busy = true

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('.chat-status').exists()).toBe(true)
    expect(wrapper.text()).toContain('正在思考')
  })

  it('shows the tool name while the agent is calling a tool', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [
      { role: 'user', content: 'hi' },
      {
        role: 'assistant',
        content: '',
        tool_calls: [{ id: 'call-1', name: 'list_directory', args: {} }],
      },
    ]
    agentStore.busy = true

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.text()).toContain('正在调用工具：list_directory')
  })

  it('renders assistant tool calls as a tag instead of an empty bubble', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [
      {
        role: 'assistant',
        content: '',
        tool_calls: [{ id: 'call-1', name: 'list_directory', args: {} }],
      },
    ]

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.text()).toContain('调用工具：list_directory')
  })

  it('disables input and shows a hint while an interrupt is pending', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.interrupt = 'file_plan'

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('textarea').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.chat-status').exists()).toBe(true)
    expect(wrapper.text()).toContain('等待确认')
  })

  it('shows the running status when busy even if interrupt_type is stale', async () => {
    // 确认后 execute_confirmed 执行期间 interrupt_type 尚未清除，
    // 状态文案应以运行状态为准而不是显示「等待确认」。
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [{ role: 'user', content: 'hi' }]
    agentStore.busy = true
    agentStore.interrupt = 'python_script'

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('.chat-status').exists()).toBe(true)
    expect(wrapper.text()).toContain('正在思考')
    expect(wrapper.text()).not.toContain('等待确认')
  })

  it('does not show collapse toggle for short tool output', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [
      { role: 'tool', content: 'short\noutput', tool_call_id: 'call-1' },
    ]

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('.tool-toggle').exists()).toBe(false)
    expect(wrapper.find('.message-content--tool').classes()).not.toContain(
      'is-collapsed'
    )
  })

  it('collapses long tool output and toggles expand/collapse', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [
      {
        role: 'tool',
        content: Array.from({ length: 15 }, (_, i) => `line ${i + 1}`).join(
          '\n'
        ),
        tool_call_id: 'call-1',
      },
    ]

    const wrapper = setupWrapper()
    await flushPromises()

    const content = wrapper.find('.message-content--tool')
    expect(content.classes()).toContain('is-collapsed')

    let toggle = wrapper.find('.tool-toggle button')
    expect(toggle.exists()).toBe(true)
    expect(toggle.text()).toBe('展开')

    await toggle.trigger('click')
    await flushPromises()

    expect(content.classes()).not.toContain('is-collapsed')
    toggle = wrapper.find('.tool-toggle button')
    expect(toggle.text()).toBe('收起')

    await toggle.trigger('click')
    await flushPromises()

    expect(content.classes()).toContain('is-collapsed')
    toggle = wrapper.find('.tool-toggle button')
    expect(toggle.text()).toBe('展开')
  })

  it('shows context usage badge with formatted tokens and percentage', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.contextUsage = { input_tokens: 12345, output_tokens: 100, total_tokens: 12445 }
    agentStore.contextWindow = 1_000_000

    const wrapper = setupWrapper()
    await flushPromises()

    const badge = wrapper.find('.context-usage')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toContain('12.3k/1M · 1.2%')
  })

  it('shows -- when no context usage data yet', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('.context-usage').text()).toContain('--')
  })

  it('highlights the badge at 80% and 95% thresholds', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.contextWindow = 1_000_000
    agentStore.contextUsage = { input_tokens: 800_000, output_tokens: 0, total_tokens: 800_000 }

    const wrapper = setupWrapper()
    await flushPromises()
    expect(wrapper.find('.context-usage').classes()).toContain('context-usage--warning')

    agentStore.contextUsage = { input_tokens: 950_000, output_tokens: 0, total_tokens: 950_000 }
    await flushPromises()
    expect(wrapper.find('.context-usage').classes()).toContain('context-usage--danger')
  })
})
