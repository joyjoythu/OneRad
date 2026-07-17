import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import App from '../App.vue'

const SIDEBAR_COLLAPSED_KEY = 'onerad:app:sidebarCollapsed'

function setupWrapper() {
  return mount(App, {
    global: {
      plugins: [ElementPlus],
      stubs: {
        ProjectList: { template: '<div class="project-list-stub" />' },
        'router-link': { template: '<a><slot /></a>' },
        'router-view': true,
      },
    },
  })
}

describe('App sidebar collapse', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('renders expanded by default', () => {
    const wrapper = setupWrapper()

    expect(wrapper.find('.app-sidebar').classes()).not.toContain('app-sidebar--collapsed')
    expect(
      wrapper.find('[data-testid="sidebar-toggle-collapse"]').attributes('aria-label')
    ).toBe('折叠项目面板')
    expect(wrapper.find('.project-list-stub').isVisible()).toBe(true)
  })

  it('collapses on toggle click and persists state', async () => {
    const wrapper = setupWrapper()
    const toggle = wrapper.find('[data-testid="sidebar-toggle-collapse"]')

    await toggle.trigger('click')

    expect(wrapper.find('.app-sidebar').classes()).toContain('app-sidebar--collapsed')
    expect(toggle.attributes('aria-label')).toBe('展开项目面板')
    expect(wrapper.find('.project-list-stub').isVisible()).toBe(false)
    expect(localStorage.getItem(SIDEBAR_COLLAPSED_KEY)).toBe('true')

    await toggle.trigger('click')

    expect(wrapper.find('.app-sidebar').classes()).not.toContain('app-sidebar--collapsed')
    expect(localStorage.getItem(SIDEBAR_COLLAPSED_KEY)).toBe('false')
  })

  it('restores collapsed state from localStorage', () => {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, 'true')

    const wrapper = setupWrapper()

    expect(wrapper.find('.app-sidebar').classes()).toContain('app-sidebar--collapsed')
  })
})
