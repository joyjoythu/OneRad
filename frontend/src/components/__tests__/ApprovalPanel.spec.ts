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

  it('shows the pairs summary for radiomics_plan interrupts', () => {
    const store = useAgentStore()
    store.interrupt = 'radiomics_plan'
    store.pendingRadiomicsPlan = {
      tool_call_id: 'tc-rp-1',
      _pending_tool: 'discover_radiomics_pairs',
      success: true,
      images_found: 40,
      masks_found: 40,
      pairs: { high: [{}], medium: [], low: [] },
      unmatched_images: [],
      unmatched_masks: [],
    } as never

    const wrapper = setupWrapper()

    expect(wrapper.text()).toContain('待确认：配对计划')
    expect(wrapper.text()).toContain('发现 40 图 / 40 掩膜')
    expect(wrapper.text()).toContain('确认')
  })

  it('shows the case count for radiomics_execution interrupts', () => {
    const store = useAgentStore()
    store.interrupt = 'radiomics_execution'
    store.pendingRadiomicsExecution = {
      tool_call_id: 'tc-re-1',
      pairs: [],
      n_cases: 12,
      yaml_path: 'Params_labels.yaml',
      output_dir: 'out',
    } as never

    const wrapper = setupWrapper()

    expect(wrapper.text()).toContain('待确认：特征提取')
    expect(wrapper.text()).toContain('病例数：12')
    expect(wrapper.text()).toContain('确认提取')
  })

  it('shows the analysis summary for radiomics_analysis interrupts', () => {
    const store = useAgentStore()
    store.interrupt = 'radiomics_analysis'
    store.pendingRadiomicsAnalysis = {
      tool_call_id: 'tc-ra-1',
      feature_csv: 'features/radiomics.csv',
      clinical: 'clinical/data.csv',
      id_col: 'patient_id',
      label_col: 'label',
      covariates: [],
      output_dir: 'analysis_output',
      n_feature_cases: 100,
      n_features: 120,
      n_matched: 95,
      available_clinical_columns: [],
    } as never

    const wrapper = setupWrapper()

    expect(wrapper.text()).toContain('待确认：影像组学分析')
    expect(wrapper.text()).toContain('特征：features/radiomics.csv')
    expect(wrapper.text()).toContain('标签列：label')
    expect(wrapper.text()).toContain('匹配 95 例')
    expect(wrapper.text()).toContain('确认分析')
  })

  it('expands the custom instruction input when clicking the other button', async () => {
    const store = useAgentStore()
    store.interrupt = 'system_command'
    store.pendingCommand = mockCommand

    const wrapper = setupWrapper()
    expect(wrapper.find('.approval-other').exists()).toBe(false)

    const otherBtn = wrapper
      .findAll('button')
      .find((b) => b.text().trim() === '其他')
    await otherBtn!.trigger('click')
    expect(wrapper.find('.approval-other').exists()).toBe(true)
    expect(wrapper.find('textarea').exists()).toBe(true)

    // 再次点击收起
    await otherBtn!.trigger('click')
    expect(wrapper.find('.approval-other').exists()).toBe(false)
  })

  it('disables the other submit button for empty or whitespace input', async () => {
    const store = useAgentStore()
    store.interrupt = 'system_command'
    store.pendingCommand = mockCommand

    const wrapper = setupWrapper()
    const otherBtn = wrapper
      .findAll('button')
      .find((b) => b.text().trim() === '其他')
    await otherBtn!.trigger('click')

    const submitBtn = () =>
      wrapper.findAll('button').find((b) => b.text().trim() === '提交')!
    expect(submitBtn().attributes('disabled')).toBeDefined()

    await wrapper.find('textarea').setValue('   ')
    expect(submitBtn().attributes('disabled')).toBeDefined()

    await wrapper.find('textarea').setValue('换个目录')
    expect(submitBtn().attributes('disabled')).toBeUndefined()
  })

  it('submits the custom instruction via store.other', async () => {
    const store = useAgentStore()
    store.interrupt = 'system_command'
    store.pendingCommand = mockCommand
    const otherSpy = vi.spyOn(store, 'other').mockResolvedValue(undefined)

    const wrapper = setupWrapper()
    const otherBtn = wrapper
      .findAll('button')
      .find((b) => b.text().trim() === '其他')
    await otherBtn!.trigger('click')

    await wrapper.find('textarea').setValue('  改用 bash 执行  ')
    const submitBtn = wrapper
      .findAll('button')
      .find((b) => b.text().trim() === '提交')
    await submitBtn!.trigger('click')

    expect(otherSpy).toHaveBeenCalledWith('改用 bash 执行')
    // 提交后收起输入区
    expect(wrapper.find('.approval-other').exists()).toBe(false)
  })
})
