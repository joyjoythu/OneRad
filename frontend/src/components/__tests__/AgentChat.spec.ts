import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElDropdown, ElMessageBox, type MessageBoxData } from 'element-plus'
import AgentChat from '../AgentChat.vue'
import { useAgentStore } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'
import { listProjectEntries } from '@/api/projects'
import type { Project } from '@/api/projects'

vi.mock('@/api/projects', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/projects')>()
  return {
    ...actual,
    listProjectEntries: vi.fn().mockResolvedValue(['data/', 'data/image.nii.gz']),
  }
})

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
    localStorage.clear()
    vi.mocked(listProjectEntries).mockReset()
    vi.mocked(listProjectEntries).mockResolvedValue(['data/', 'data/image.nii.gz'])
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders placeholder when no project is selected', async () => {
    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('.chat-empty-brand').exists()).toBe(true)
    expect(wrapper.find('.chat-empty-brand').text()).toBe('OneRad')
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

  it('opens the mention dropdown upward instead of flipping from below', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const wrapper = setupWrapper()
    await flushPromises()

    const mention = wrapper.findComponent({ name: 'ElMention' })
    expect(mention.exists()).toBe(true)
    expect(mention.props('placement')).toBe('top')
  })

  it('shows the model selector bound to the store selection', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.setModel('deepseek-v4-pro')

    const wrapper = setupWrapper()
    await flushPromises()

    const select = wrapper.findComponent({ name: 'ElSelect' })
    expect(select.exists()).toBe(true)
    expect(select.props('modelValue')).toBe('deepseek-v4-pro')
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

  it('fills the input with the quick action prompt instead of sending it', async () => {
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

    expect(wrapper.emitted('send-message')).toBeUndefined()
    expect((textarea.element as HTMLTextAreaElement).value).toBe(
      '尚未发送的草稿\n请检查当前项目配置与数据完整性，并开始执行完整的影像组学分析流程。'
    )
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

  it('renders el-mention as the input and queries project files on @ search', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const wrapper = setupWrapper()
    await flushPromises()

    const mention = wrapper.findComponent({ name: 'ElMention' })
    expect(mention.exists()).toBe(true)

    vi.useFakeTimers()
    try {
      mention.vm.$emit('search', 'image', '@')
      await vi.advanceTimersByTimeAsync(250)
      await flushPromises()

      expect(listProjectEntries).toHaveBeenCalledWith('proj-1', 'image')
      // 目录条目以 / 结尾，与文件一起作为候选
      expect(mention.props('options')).toEqual([
        { value: 'data/' },
        { value: 'data/image.nii.gz' },
      ])
      // 服务端已按关键词过滤，本地不再二次过滤
      expect(mention.props('filterOption')).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not query files on @ search when no project is selected', async () => {
    const wrapper = setupWrapper()
    await flushPromises()

    // 无项目时输入区不渲染（显示空状态），mention 无从触发；
    // 这里直接验证 mock 未被调用即可。
    expect(wrapper.find('.chat-empty-brand').exists()).toBe(true)
    expect(listProjectEntries).not.toHaveBeenCalled()
  })

  /** 真实触发 @ 补全弹层：输入 @关键词、移动光标到末尾、派发 input，
   * 等待防抖查询完成。返回 textarea 元素。 */
  async function openMentionDropdown(wrapper: VueWrapper<any>, text = '分析 @im') {
    vi.useFakeTimers()
    const el = wrapper.find('textarea').element as HTMLTextAreaElement
    el.value = text
    el.setSelectionRange(el.value.length, el.value.length)
    // el-mention 只在 textarea 获得焦点时才显示弹层（jsdom 需显式聚焦）
    el.focus()
    el.dispatchEvent(new Event('input', { bubbles: true }))
    await vi.advanceTimersByTimeAsync(250)
    await flushPromises()
    return el
  }

  it('selects the highlighted mention candidate with Tab', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const wrapper = setupWrapper()
    await flushPromises()

    try {
      const el = await openMentionDropdown(wrapper)

      const tabEvent = new KeyboardEvent('keydown', {
        key: 'Tab',
        bubbles: true,
        cancelable: true,
      })
      el.dispatchEvent(tabEvent)
      await flushPromises()

      // Tab 被选中所消费（不移动焦点），候选（首个为目录）写入输入框
      expect(tabEvent.defaultPrevented).toBe(true)
      expect(el.value).toContain('@data/')
      expect(wrapper.emitted('send-message')).toBeUndefined()
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not send on Enter while the mention dropdown is open', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const wrapper = setupWrapper()
    await flushPromises()

    try {
      const el = await openMentionDropdown(wrapper)

      el.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
      )
      await flushPromises()

      // Enter 用于选中候选而非发送消息
      expect(wrapper.emitted('send-message')).toBeUndefined()
      expect(el.value).toContain('@data/')
    } finally {
      vi.useRealTimers()
    }
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

  it('does not render the status bar when idle', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [{ role: 'user', content: 'hi' }]
    agentStore.busy = false

    const wrapper = setupWrapper()
    await flushPromises()

    // 状态栏无内容时不渲染不占位：聊天内容可直接显示到输入框正上方。
    expect(wrapper.find('.chat-status').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('正在思考')
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

  it('shows a progress bar with percentage while extracting features', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [{ role: 'user', content: 'hi' }]
    agentStore.busy = true
    agentStore.radiomicsProgress = {
      stage: 'extracting', current: 2, total: 5, patient_id: 'case_002',
    }

    const wrapper = setupWrapper()
    await flushPromises()

    // 比例数字保留在状态文本中
    expect(wrapper.text()).toContain('(2/5)')
    expect(wrapper.text()).toContain('case_002')
    expect(wrapper.find('.el-progress').exists()).toBe(true)
    expect(wrapper.find('.el-progress__text').text()).toContain('40%')
  })

  it('shows a full progress bar while finalizing extraction', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [{ role: 'user', content: 'hi' }]
    agentStore.busy = true
    agentStore.radiomicsProgress = { stage: 'finalizing', current: 5, total: 5 }

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.text()).toContain('正在保存特征结果')
    expect(wrapper.find('.el-progress__text').text()).toContain('100%')
  })

  it('does not render the progress strip when not extracting', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [{ role: 'user', content: 'hi' }]
    agentStore.busy = true

    const wrapper = setupWrapper()
    await flushPromises()

    // 进度条无提取进度时整体不渲染不占位
    expect(wrapper.find('.chat-progress').exists()).toBe(false)
    expect(wrapper.find('.el-progress').exists()).toBe(false)
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

  it('renders a serialized textual tool result as decoded Markdown', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [
      {
        role: 'tool',
        content:
          '{"success":true,"result":"\\u4ee5\\u4e0b\\u662f\\u9879\\u76ee\\u62a5\\u544a\\n\\n## \\u9879\\u76ee\\u76ee\\u5f55"}',
        tool_call_id: 'call-1',
      },
    ]

    const wrapper = setupWrapper()
    await flushPromises()

    const content = wrapper.find('.message-content--tool')
    expect(content.text()).toContain('以下是项目报告')
    expect(content.text()).not.toContain('{"success"')
    expect(content.text()).not.toContain('\\u4ee5')
    expect(content.find('h2').text()).toBe('项目目录')
  })

  it('renders file search results as a readable list instead of JSON', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.messages = [
      {
        role: 'tool',
        content: JSON.stringify({
          tool: 'find_files',
          result: ['project.yaml', 'outputs\\radiomics_report.docx'],
        }),
        tool_call_id: 'call-1',
      },
    ]

    const wrapper = setupWrapper()
    await flushPromises()

    const content = wrapper.find('.message-content--tool')
    expect(content.text()).toContain('找到 2 个文件或目录')
    expect(content.findAll('li')).toHaveLength(2)
    expect(content.findAll('code').map((item) => item.text())).toEqual([
      'project.yaml',
      'outputs\\radiomics_report.docx',
    ])
    expect(content.text()).not.toContain('"tool"')
    expect(content.text()).not.toContain('{')
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


describe('AgentChat subagent panel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  const mockSubagentStatus = (
    id: string,
    status: 'running' | 'done' | 'failed' | 'cancelled',
    task = '统计项目根目录下的文件数量'
  ) => ({
    id,
    task,
    status,
    entries: [
      { role: 'assistant', text: '调用工具：list_directory' },
      { role: 'tool', text: '{"result": "F a.txt"}' },
    ],
  })

  it('shows the subagent panel with task and entries while busy', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.busy = true
    agentStore.subagentStatuses = {
      'sub-1': mockSubagentStatus('sub-1', 'running'),
    }

    const wrapper = setupWrapper()
    await flushPromises()

    const panel = wrapper.find('.subagent-panel')
    expect(panel.exists()).toBe(true)
    expect(panel.text()).toContain('内部执行阶段')
    expect(panel.text()).toContain('统计项目根目录下的文件数量')
    expect(panel.text()).toContain('运行中')
    expect(panel.text()).toContain('调用工具：list_directory')
    expect(panel.text()).toContain('{"result": "F a.txt"}')
  })

  it('renders one panel per subagent when dispatching in parallel', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.busy = true
    agentStore.subagentStatuses = {
      'sub-1': mockSubagentStatus('sub-1', 'running', '统计数据文件'),
      'sub-2': mockSubagentStatus('sub-2', 'done', '检查掩膜目录'),
    }

    const wrapper = setupWrapper()
    await flushPromises()

    const panels = wrapper.findAll('.subagent-panel')
    expect(panels).toHaveLength(2)
    expect(panels[0].text()).toContain('统计数据文件')
    expect(panels[0].text()).toContain('运行中')
    expect(panels[1].text()).toContain('检查掩膜目录')
    expect(panels[1].text()).toContain('结果已返回')
  })

  it('keeps the subagent panel frozen after the run ends', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.busy = false
    agentStore.subagentStatuses = {
      'sub-1': mockSubagentStatus('sub-1', 'done'),
    }

    const wrapper = setupWrapper()
    await flushPromises()

    const panel = wrapper.find('.subagent-panel')
    expect(panel.exists()).toBe(true)
    expect(panel.text()).toContain('子 Agent')
    expect(panel.text()).toContain('结果已返回')
    // 结束后不再显示“主任务仍在处理”类运行期提示。
    expect(panel.text()).not.toContain('主任务仍在')
  })

  it('shows terminal status labels on the tag', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.busy = true
    agentStore.subagentStatuses = {
      'sub-1': mockSubagentStatus('sub-1', 'failed'),
    }

    const wrapper = setupWrapper()
    await flushPromises()
    expect(wrapper.find('.subagent-panel').text()).toContain('失败')

    agentStore.subagentStatuses = {
      'sub-1': mockSubagentStatus('sub-1', 'cancelled'),
    }
    await flushPromises()
    expect(wrapper.find('.subagent-panel').text()).toContain('已停止')
  })

  it('presents a completed subagent as an internal stage, not a final reply', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.busy = true
    agentStore.subagentStatuses = {
      'sub-1': mockSubagentStatus('sub-1', 'done'),
    }

    const wrapper = setupWrapper()
    await flushPromises()

    const stage = wrapper.find('[data-testid="subagent-stage"]')
    expect(stage.exists()).toBe(true)
    expect(stage.text()).toContain('结果已返回')
    expect(stage.text()).toContain('主任务仍在整理结果或继续执行')
    expect(stage.find('.message-bubble--assistant').exists()).toBe(false)
    expect(stage.find('.message-avatar').exists()).toBe(false)
    expect(stage.find('.el-tag').classes()).toContain('el-tag--info')
  })

  it('collapses and re-expands the entries list per subagent', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.busy = true
    agentStore.subagentStatuses = {
      'sub-1': mockSubagentStatus('sub-1', 'running'),
    }

    const wrapper = setupWrapper()
    await flushPromises()

    const entries = wrapper.find('.subagent-entries')
    expect(entries.isVisible()).toBe(true)

    await wrapper.find('.subagent-toggle').trigger('click')
    await flushPromises()
    expect(wrapper.find('.subagent-entries').isVisible()).toBe(false)

    await wrapper.find('.subagent-toggle').trigger('click')
    await flushPromises()
    expect(wrapper.find('.subagent-entries').isVisible()).toBe(true)
  })

  it('anchors the subagent panel inside the dispatching assistant message', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.busy = false
    agentStore.messages = [
      {
        role: 'assistant',
        content: '我先派一个子任务去统计。',
        tool_calls: [
          { id: 'call-1', name: 'dispatch_subagent', args: { tasks: ['统计数据文件'] } },
        ],
      },
      { role: 'assistant', content: '子任务结果如下，请查收。' },
    ]
    agentStore.subagentStatuses = {
      'sub-1': { ...mockSubagentStatus('sub-1', 'done'), tool_call_id: 'call-1' },
    }

    const wrapper = setupWrapper()
    await flushPromises()

    const rows = wrapper.findAll('.message-row')
    expect(rows).toHaveLength(2)
    // 面板内联在发起 dispatch 的那条消息里，而不是钉在消息列表末尾。
    expect(rows[0].find('.subagent-panel').exists()).toBe(true)
    expect(rows[1].find('.subagent-panel').exists()).toBe(false)
  })

  it('falls back to the bottom stage when the dispatching message is unknown', async () => {
    const projectStore = useProjectStore()
    projectStore.currentProject = mockProject()

    const agentStore = useAgentStore()
    agentStore.threadId = 'thread-1'
    agentStore.busy = true
    agentStore.messages = [{ role: 'user', content: 'hi' }]
    agentStore.subagentStatuses = {
      'sub-1': mockSubagentStatus('sub-1', 'running'),
    }

    const wrapper = setupWrapper()
    await flushPromises()

    // 没有 tool_call_id 锚点时仍渲染在列表底部（原有行为兜底）。
    const rows = wrapper.findAll('.message-row')
    expect(rows[0].find('.subagent-panel').exists()).toBe(false)
    expect(wrapper.find('.subagent-panel').exists()).toBe(true)
  })
})
