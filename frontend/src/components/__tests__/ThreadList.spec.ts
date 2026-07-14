import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import ElementPlus from 'element-plus'
import ThreadList from '@/components/ThreadList.vue'
import { ElMessageBox } from 'element-plus'

vi.mock('element-plus', async () => {
  const actual = await vi.importActual('element-plus')
  return {
    ...actual,
    ElMessageBox: {
      confirm: vi.fn(),
      prompt: vi.fn(),
    },
  }
})

const threads = [
  { id: 't1', project_id: 'p1', title: 'First', llm_model: 'deepseek-v4-pro', created_at: '2026-01-01', updated_at: '2026-01-02' },
  { id: 't2', project_id: 'p1', title: 'Second', llm_model: 'deepseek-v4-flash', created_at: '2026-01-01', updated_at: '2026-01-03' },
]

function mountThreadList(props: { threads: typeof threads; currentThreadId: string | null; collapsed?: boolean }) {
  return mount(ThreadList, {
    props,
    global: {
      plugins: [ElementPlus],
    },
  })
}

describe('ThreadList', () => {
  it('renders threads and highlights current', () => {
    const wrapper = mountThreadList({ threads, currentThreadId: 't2' })
    const items = wrapper.findAll('.thread-item')
    expect(items).toHaveLength(2)
    expect(items[1].classes()).toContain('thread-item--active')
  })

  it('emits select event on click', async () => {
    const wrapper = mountThreadList({ threads, currentThreadId: null })
    await wrapper.findAll('.thread-item')[0].trigger('click')
    expect(wrapper.emitted('select')).toBeTruthy()
    expect(wrapper.emitted('select')![0]).toEqual(['t1'])
  })

  it('emits create event', async () => {
    const wrapper = mountThreadList({ threads, currentThreadId: null, collapsed: false })
    await wrapper.findAll('.thread-list-header button')[1].trigger('click')
    expect(wrapper.emitted('create')).toBeTruthy()
  })

  it('confirms before delete', async () => {
    const wrapper = mountThreadList({ threads, currentThreadId: null })
    ;(ElMessageBox.confirm as any).mockResolvedValueOnce(undefined)
    await wrapper.findAll('.thread-item')[0].findAll('button')[1].trigger('click')
    await nextTick()
    expect(ElMessageBox.confirm).toHaveBeenCalled()
  })

  it('emits toggle-collapse when collapse button is clicked', async () => {
    const wrapper = mount(ThreadList, {
      props: { threads, currentThreadId: null, collapsed: false },
      global: { plugins: [ElementPlus] },
    })
    const buttons = wrapper.findAll('.thread-list-header button')
    // 第一个按钮是折叠按钮
    await buttons[0].trigger('click')
    expect(wrapper.emitted('toggle-collapse')).toBeTruthy()
  })

  it('hides content when collapsed', () => {
    const wrapper = mount(ThreadList, {
      props: { threads, currentThreadId: null, collapsed: true },
      global: { plugins: [ElementPlus] },
    })
    expect(wrapper.find('.thread-list-title').isVisible()).toBe(false)
    expect(wrapper.find('.thread-list-items').isVisible()).toBe(false)
    expect(wrapper.classes()).toContain('thread-list--collapsed')
  })

  it('shows content when expanded', () => {
    const wrapper = mount(ThreadList, {
      props: { threads, currentThreadId: null, collapsed: false },
      global: { plugins: [ElementPlus] },
    })
    expect(wrapper.find('.thread-list-title').isVisible()).toBe(true)
    expect(wrapper.find('.thread-list-items').exists()).toBe(true)
    expect(wrapper.classes()).not.toContain('thread-list--collapsed')
  })
})
