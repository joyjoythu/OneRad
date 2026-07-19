import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElDropdown, ElMessageBox, type MessageBoxData } from 'element-plus'
import AgentChat from '../AgentChat.vue'
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

function setupWrapper() {
  return mount(AgentChat, {
    // 挂载到 document：jsdom 对游离元素缓存 getComputedStyle 结果，
    // v-show 切换后 isVisible() 会读到过期的 display: none。
    attachTo: document.body,
    global: {
      plugins: [ElementPlus],
    },
  })
}

describe('AgentChat', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
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

  it('shows the current conversation name above the message area', async () => {
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

    const wrapper = setupWrapper()
    await flushPromises()

    const title = wrapper.find('[data-testid="current-conversation-title"]')
    expect(title.text()).toContain('当前会话')
    expect(title.text()).toContain('肺结节影像组学分析')
  })

  it('emits send-message when clicking the send button', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const wrapper = setupWrapper()
    await flushPromises()

    const textarea = wrapper.find('textarea')
    await textarea.setValue('Test message')

    const sendButton = wrapper.find('[aria-label="发送"]')
    expect(sendButton.exists()).toBe(true)
    await sendButton.trigger('click')
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

  it('starts a quick action immediately while preserving the input draft', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const wrapper = setupWrapper()
    await flushPromises()

    const textarea = wrapper.find('textarea')
    await textarea.setValue('尚未发送的草稿')

    const dropdown = wrapper.findComponent(ElDropdown)
    expect(dropdown.exists()).toBe(true)
    dropdown.vm.$emit('command', 'start-analysis')
    await flushPromises()

    expect(wrapper.emitted('quick-action')).toEqual([
      ['请检查当前项目配置与数据完整性，并开始执行完整的影像组学分析流程。'],
    ])
    expect((textarea.element as HTMLTextAreaElement).value).toBe('尚未发送的草稿')
  })

  it('confirms before clearing the current task and keeps history untouched', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [{ role: 'user', content: '保留的历史内容' }]
    const resetSpy = vi.spyOn(agentStore, 'resetThread')
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as MessageBoxData)

    const wrapper = setupWrapper()
    await flushPromises()

    wrapper.findComponent(ElDropdown).vm.$emit('command', 'clear-task')
    await flushPromises()

    expect(ElMessageBox.confirm).toHaveBeenCalledWith(
      '清除当前任务上下文并开始新对话？历史对话仍会保留。',
      '清除当前任务',
      expect.objectContaining({ customClass: 'compact-confirm-box' })
    )
    expect(resetSpy).toHaveBeenCalledOnce()
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

  it('enables the input when a project is selected without a thread', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const wrapper = setupWrapper()
    await flushPromises()

    const textarea = wrapper.find('textarea')
    expect(textarea.attributes('disabled')).toBeUndefined()

    expect(wrapper.find('.model-selector').exists()).toBe(false)
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

    const stopButton = wrapper.find('[aria-label="停止"]')
    expect(stopButton.exists()).toBe(true)
    expect(wrapper.find('[aria-label="发送"]').exists()).toBe(false)

    await stopButton.trigger('click')
    expect(wrapper.emitted('stop')).toHaveLength(1)
  })

  it('shows the send button and no stop button when idle', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('[aria-label="发送"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="停止"]').exists()).toBe(false)
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

  it('collapses long single-line tool output (e.g. JSON-encoded script result)', async () => {
    // 后端把工具结果 json.dumps 成单行字符串（换行转义为 \n），
    // 只按真实换行统计永远是一行，必须按字符数兜底折叠。
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [
      {
        role: 'tool',
        content: JSON.stringify({ stdout: 'x'.repeat(2000), returncode: 0 }),
        tool_call_id: 'call-1',
      },
    ]

    const wrapper = setupWrapper()
    await flushPromises()

    const content = wrapper.find('.message-content--tool')
    expect(content.classes()).toContain('is-collapsed')
    expect(wrapper.find('.tool-toggle button').exists()).toBe(true)
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

  it('renders the auto-approve switch and toggles the store', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()
    const agentStore = useAgentStore()

    const wrapper = setupWrapper()
    await flushPromises()

    const row = wrapper.find('.auto-approve-row')
    expect(row.exists()).toBe(true)
    expect(row.text()).toContain('自动审批')

    await wrapper.find('.el-switch').trigger('click')
    expect(agentStore.autoApprove).toBe(true)
  })

  it('disables the auto-approve switch while syncing', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()
    const agentStore = useAgentStore()
    agentStore.autoApproveSyncing = true

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('.el-switch').classes()).toContain('is-disabled')
  })

  it('shows timestamp only under messages that have one', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    const now = new Date()
    const iso = new Date(
      now.getFullYear(),
      now.getMonth(),
      now.getDate(),
      8,
      30,
    ).toISOString()
    agentStore.messages = [
      { role: 'user', content: 'hi', timestamp: iso },
      { role: 'assistant', content: 'hello' },
    ]

    const wrapper = setupWrapper()
    await flushPromises()

    const times = wrapper.findAll('.message-time')
    expect(times).toHaveLength(1)
    expect(times[0].text()).toBe('08:30')
  })

  it('renders avatar for assistant messages only', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.messages = [
      { role: 'user', content: 'hi' },
      { role: 'assistant', content: 'hello' },
    ]

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.findAll('.agent-avatar')).toHaveLength(1)
    const rows = wrapper.findAll('.message-row')
    expect(rows[0].find('.agent-avatar').exists()).toBe(false)
    expect(rows[1].find('.agent-avatar').exists()).toBe(true)
  })

  it('renders the approval panel between the message list and the input area when an interrupt is pending', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.interrupt = 'system_command'
    agentStore.pendingCommand = {
      tool_call_id: 'tc-cmd-1',
      _pending_tool: 'run_command',
      args: { cmd: 'ls' },
    }

    const wrapper = setupWrapper()
    await flushPromises()

    const panel = wrapper.find('.approval-panel')
    expect(panel.exists()).toBe(true)

    const html = wrapper.html()
    expect(html.indexOf('message-list')).toBeLessThan(html.indexOf('approval-panel'))
    expect(html.indexOf('approval-panel')).toBeLessThan(html.indexOf('input-container'))
  })

  it('renders the input area as a unified container with a toolbar', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'

    const wrapper = setupWrapper()
    await flushPromises()

    const container = wrapper.find('.input-container')
    expect(container.exists()).toBe(true)
    expect(container.find('textarea').exists()).toBe(true)

    const toolbar = container.find('.input-toolbar')
    expect(toolbar.exists()).toBe(true)
    expect(toolbar.find('.auto-approve-row').exists()).toBe(true)
    expect(toolbar.find('.model-selector').exists()).toBe(false)
    expect(toolbar.find('[aria-label="发送"]').exists()).toBe(true)
  })

  it('renders streaming thinking bubble while busy', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.busy = true
    agentStore.currentThinking = { text: '正在分析数据…', done: false }

    const wrapper = setupWrapper()
    await flushPromises()

    const bubble = wrapper.find('.thinking-stream')
    expect(bubble.exists()).toBe(true)
    expect(bubble.text()).toContain('思考过程')
    expect(bubble.text()).toContain('正在分析数据…')
  })

  it('hides streaming bubble when thinking is done or not busy', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.busy = true
    agentStore.currentThinking = { text: '想完了', done: true }

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('.thinking-stream').exists()).toBe(false)
  })

  it('renders collapsed reasoning block for assistant messages and expands on click', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [
      { role: 'assistant', content: '答案', reasoning_content: '完整的思考过程' },
    ]

    const wrapper = setupWrapper()
    await flushPromises()

    const toggle = wrapper.find('.reasoning-toggle')
    expect(toggle.exists()).toBe(true)
    const reasoning = wrapper.find('.reasoning-content')
    expect(reasoning.exists()).toBe(true)
    expect(reasoning.isVisible()).toBe(false)

    await toggle.trigger('click')
    expect(wrapper.find('.reasoning-content').isVisible()).toBe(true)
    expect(wrapper.find('.reasoning-content').text()).toContain('完整的思考过程')
  })

  it('does not render reasoning block for messages without reasoning_content', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [{ role: 'assistant', content: '普通回复' }]

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('.reasoning-toggle').exists()).toBe(false)
  })

  it('renders assistant message content as markdown', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [
      { role: 'assistant', content: '**加粗** 和 `代码`\n\n- 第一项\n- 第二项' },
    ]

    const wrapper = setupWrapper()
    await flushPromises()

    const content = wrapper.find('.message-content--markdown')
    expect(content.exists()).toBe(true)
    expect(content.find('strong').text()).toBe('加粗')
    expect(content.find('code').text()).toBe('代码')
    expect(content.findAll('li')).toHaveLength(2)
  })

  it('escapes raw html in assistant markdown and keeps user messages plain', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [
      { role: 'assistant', content: '<script>alert(1)</script>正常文本' },
      { role: 'user', content: '**不按 markdown 渲染**' },
    ]

    const wrapper = setupWrapper()
    await flushPromises()

    const rendered = wrapper.find('.message-content--markdown')
    expect(rendered.find('script').exists()).toBe(false)
    expect(rendered.text()).toContain('正常文本')

    const userRow = wrapper.find('.message-row--user')
    expect(userRow.find('.message-content--markdown').exists()).toBe(false)
    expect(userRow.find('strong').exists()).toBe(false)
    expect(userRow.text()).toContain('**不按 markdown 渲染**')
  })
})
