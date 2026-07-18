import { describe, it, expect, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import PlanDisplay from '../PlanDisplay.vue'
import { useAgentStore } from '@/stores/agent'

const mockPendingPlan = {
  tool_call_id: 'tc-plan-1',
  plan: [
    { action: 'copy', source: 'a.nii.gz', target: 'b/a.nii.gz', reason: '整理' },
  ],
}

function setupWrapper() {
  return mount(PlanDisplay, { global: { plugins: [ElementPlus] } })
}

describe('PlanDisplay', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders plan items as read-only text without inputs or buttons', async () => {
    const store = useAgentStore()
    store.pendingPlan = mockPendingPlan

    const wrapper = setupWrapper()
    // el-table 列注册需两轮微任务后才渲染出单元格，统一等待
    await flushPromises()

    expect(wrapper.text()).toContain('copy')
    expect(wrapper.text()).toContain('a.nii.gz')
    expect(wrapper.text()).toContain('整理')
    expect(wrapper.findAll('input')).toHaveLength(0)
    expect(wrapper.findAll('button')).toHaveLength(0)
  })

  it('renders an empty table when there is no pending plan', () => {
    const wrapper = setupWrapper()
    expect(wrapper.find('.plan-display').exists()).toBe(true)
    expect(wrapper.findAll('tbody tr')).toHaveLength(0)
  })
})
