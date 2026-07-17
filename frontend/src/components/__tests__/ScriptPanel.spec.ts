import { describe, it, expect, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import ScriptPanel from '../ScriptPanel.vue'
import { useAgentStore } from '@/stores/agent'

function setupWrapper() {
  return mount(ScriptPanel, {
    global: { plugins: [ElementPlus] },
  })
}

describe('ScriptPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders script code and description from pendingScript', async () => {
    const store = useAgentStore()
    store.pendingScript = {
      tool_call_id: 'tc-1',
      code: "print('hello')",
      risk_level: 'low',
      description: '打印测试',
    }

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('.script-code').text()).toContain("print('hello')")
    expect(wrapper.find('.script-explanation').text()).toContain('打印测试')
  })

  it('shows fallback text when code is missing', async () => {
    const store = useAgentStore()
    store.pendingScript = {
      tool_call_id: 'tc-1',
      code: '',
      risk_level: 'low',
      description: '打印测试',
    }

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.text()).toContain('脚本内容不可用')
  })
})
