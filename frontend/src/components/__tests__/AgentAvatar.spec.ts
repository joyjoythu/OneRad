import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import AgentAvatar from '../AgentAvatar.vue'

describe('AgentAvatar', () => {
  it('renders a circular robot avatar', () => {
    const wrapper = mount(AgentAvatar)
    const avatar = wrapper.find('.agent-avatar')
    expect(avatar.exists()).toBe(true)
    expect(avatar.attributes('role')).toBe('img')
    expect(wrapper.find('svg').exists()).toBe(true)
  })
})
