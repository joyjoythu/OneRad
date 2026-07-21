import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import TodoPanel from '../TodoPanel.vue'
import { useAgentStore } from '@/stores/agent'

function setupWrapper() {
  return mount(TodoPanel, { global: { plugins: [ElementPlus] } })
}

describe('TodoPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders in_progress item with a spinning loading icon', () => {
    const store = useAgentStore()
    store.todos = [
      { content: '项目勘察', status: 'completed' },
      { content: '特征提取', status: 'in_progress' },
    ]

    const wrapper = setupWrapper()

    expect(wrapper.find('.todo-icon--running.is-loading').exists()).toBe(true)
    expect(wrapper.text()).toContain('已完成 1/2')
  })

  it('renders cancelled item with a static warning icon instead of a spinner', () => {
    const store = useAgentStore()
    store.todos = [
      { content: '项目勘察', status: 'completed' },
      { content: '特征提取', status: 'cancelled' },
      { content: '统计分析', status: 'pending' },
    ]

    const wrapper = setupWrapper()

    // 已停止的步骤不再转圈，显示黄色填充标识
    expect(wrapper.find('.is-loading').exists()).toBe(false)
    const icon = wrapper.find('.todo-icon--cancelled')
    expect(icon.exists()).toBe(true)
    expect(wrapper.find('.todo-item--cancelled').text()).toContain('特征提取')
  })
})
