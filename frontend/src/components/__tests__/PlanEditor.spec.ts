import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import PlanEditor from '../PlanEditor.vue'
import { useAgentStore } from '@/stores/agent'

const mockPendingPlan = {
  tool_call_id: 'tc-plan-1',
  plan: [
    { action: 'copy', source: 'a.nii.gz', target: 'b/a.nii.gz', reason: '整理' },
    { action: 'move', source: 'c.csv', target: 'b/c.csv', reason: '归档' },
  ],
}

function setupWrapper() {
  return mount(PlanEditor, { global: { plugins: [ElementPlus] } })
}

describe('PlanEditor', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders editable inputs for each plan item', async () => {
    const store = useAgentStore()
    store.pendingPlan = mockPendingPlan

    const wrapper = setupWrapper()
    // el-table 列注册需两轮微任务后才渲染出单元格，统一等待
    await flushPromises()

    // 2 行 × 4 列（操作/源路径/目标路径/原因）均为输入框
    expect(wrapper.findAll('input').length).toBeGreaterThanOrEqual(8)
    expect(wrapper.text()).toContain('添加步骤')
  })

  it('adds and removes plan items', async () => {
    const store = useAgentStore()
    store.pendingPlan = mockPendingPlan

    const wrapper = setupWrapper()

    const addBtn = wrapper
      .findAll('button')
      .find((b) => b.text().includes('添加步骤'))
    await addBtn!.trigger('click')
    expect(wrapper.findAll('tbody tr')).toHaveLength(3)

    const delBtns = wrapper
      .findAll('button')
      .filter((b) => b.text().includes('删除'))
    await delBtns[0].trigger('click')
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
  })

  it('calls updatePlan with the edited plan, and confirm/cancel call the store', async () => {
    const store = useAgentStore()
    store.pendingPlan = mockPendingPlan
    const updateSpy = vi.spyOn(store, 'updatePlan').mockResolvedValue(undefined)
    const confirmSpy = vi.spyOn(store, 'confirm').mockResolvedValue(undefined)
    const cancelSpy = vi.spyOn(store, 'cancel').mockResolvedValue(undefined)

    const wrapper = setupWrapper()
    await flushPromises()

    const input = wrapper.find('input')
    await input.setValue('rename')

    const updateBtn = wrapper
      .findAll('button')
      .find((b) => b.text().includes('更新计划'))
    expect(updateBtn).toBeDefined()
    await updateBtn!.trigger('click')
    expect(updateSpy).toHaveBeenCalledWith({
      tool_call_id: 'tc-plan-1',
      plan: expect.any(Array),
    })

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
})
