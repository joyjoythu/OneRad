import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import ProjectList from '../ProjectList.vue'

vi.mock('@/api/projects', () => ({
  listProjects: vi.fn().mockResolvedValue([]),
  getProject: vi.fn(),
  createProject: vi.fn(),
  updateConfig: vi.fn(),
  deleteProject: vi.fn(),
}))

describe('ProjectList', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders the create project button', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)

    const wrapper = mount(ProjectList, {
      global: {
        plugins: [pinia, ElementPlus],
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('新建项目')
  })
})
