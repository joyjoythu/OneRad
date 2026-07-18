import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import ApprovalPanel from '../ApprovalPanel.vue'
import { useAgentStore } from '@/stores/agent'

const mockPendingPlan = {
  tool_call_id: 'tc-plan-1',
  plan: [{ action: 'copy', source: 'a', target: 'b', reason: 'r' }],
}

const mockCommand = {
  tool_call_id: 'tc-cmd-1',
  _pending_tool: 'run_command',
  args: { cmd: 'ls' },
}

const mockScript = {
  tool_call_id: 'tc-script-1',
  code: "print('hi')",
  risk_level: 'high' as const,
  description: '测试',
}

function setupWrapper() {
  return mount(ApprovalPanel, { global: { plugins: [ElementPlus] } })
}

describe('ApprovalPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders nothing when there is no pending approval', () => {
    const wrapper = setupWrapper()
    expect(wrapper.find('.approval-panel').exists()).toBe(false)
  })

  it('embeds the plan editor for file_plan interrupts', () => {
    const store = useAgentStore()
    store.interrupt = 'file_plan'
    store.pendingPlan = mockPendingPlan

    const wrapper = setupWrapper()

    expect(wrapper.text()).toContain('待确认：文件计划')
    expect(wrapper.find('.plan-editor').exists()).toBe(true)
  })

  it('shows a summary and confirm/cancel buttons for system_command', async () => {
    const store = useAgentStore()
    store.interrupt = 'system_command'
    store.pendingCommand = mockCommand
    const confirmSpy = vi.spyOn(store, 'confirm').mockResolvedValue(undefined)
    const cancelSpy = vi.spyOn(store, 'cancel').mockResolvedValue(undefined)

    const wrapper = setupWrapper()

    expect(wrapper.text()).toContain('待确认：系统命令')
    expect(wrapper.text()).toContain('工具：run_command')

    const confirmBtn = wrapper
      .findAll('button')
      .find((b) => b.text().includes('确认执行'))
    await confirmBtn!.trigger('click')
    expect(confirmSpy).toHaveBeenCalled()

    const cancelBtn = wrapper
      .findAll('button')
      .find((b) => b.text().trim() === '取消')
    await cancelBtn!.trigger('click')
    expect(cancelSpy).toHaveBeenCalled()
  })

  it('shows the risk level for python_script interrupts', () => {
    const store = useAgentStore()
    store.interrupt = 'python_script'
    store.pendingScript = mockScript

    const wrapper = setupWrapper()

    expect(wrapper.text()).toContain('待确认：Python 脚本')
    expect(wrapper.text()).toContain('风险等级：高')
  })

  it('collapses on header click and re-expands when a new approval arrives', async () => {
    const store = useAgentStore()
    store.interrupt = 'system_command'
    store.pendingCommand = mockCommand

    const wrapper = setupWrapper()
    const bodyDisplay = () =>
      (wrapper.find('.approval-body').element as HTMLElement).style.display
    expect(bodyDisplay()).not.toBe('none')

    await wrapper.find('.approval-header').trigger('click')
    expect(bodyDisplay()).toBe('none')

    // 新的审批对象到达 → 自动重新展开
    store.pendingCommand = { ...mockCommand, tool_call_id: 'tc-cmd-2' }
    await wrapper.vm.$nextTick()
    expect(bodyDisplay()).not.toBe('none')
  })

  it('does not render while the agent is busy', () => {
    const store = useAgentStore()
    store.interrupt = 'system_command'
    store.pendingCommand = mockCommand
    store.busy = true

    const wrapper = setupWrapper()
    expect(wrapper.find('.approval-panel').exists()).toBe(false)
  })
})
