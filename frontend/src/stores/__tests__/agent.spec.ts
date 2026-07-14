import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAgentStore } from '../agent'
import client from '@/api/client'
import * as agentApi from '@/api/agent'
import type { AgentState } from '@/api/agent'

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
  API_BASE: '/api',
}))

const mockState = (overrides: Partial<AgentState> = {}): AgentState => ({
  messages: [],
  interrupt_type: null,
  operation_log: [],
  pending_plan: null,
  pending_command: null,
  pending_script: null,
  ...overrides,
})

class MockEventSource {
  static instances: MockEventSource[] = []
  onerror: ((event: Event) => void) | null = null
  private listeners: Record<string, ((event: MessageEvent) => void)[]> = {}

  constructor(public url: string) {
    MockEventSource.instances.push(this)
  }

  addEventListener(type: string, handler: (event: MessageEvent) => void): void {
    if (!this.listeners[type]) this.listeners[type] = []
    this.listeners[type].push(handler)
  }

  close(): void {
    // no-op for tests
  }

  emit(type: string, data: unknown): void {
    this.listeners[type]?.forEach((handler) =>
      handler({ data: JSON.stringify(data) } as MessageEvent)
    )
  }
}

describe('useAgentStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('EventSource', MockEventSource)
    MockEventSource.instances = []
    vi.mocked(client.post).mockResolvedValue({ data: { thread_id: 'thread-1' } })
    vi.mocked(client.get).mockResolvedValue({
      data: { thread_id: 'thread-1', ...mockState() },
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('sendMessage appends the user message and calls the API', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test', 'deepseek-v4-flash')
    await store.sendMessage('Hello')

    expect(store.messages).toContainEqual({ role: 'user', content: 'Hello' })
    expect(client.post).toHaveBeenCalledWith(
      '/agent/threads/thread-1/messages',
      { role: 'user', content: 'Hello' }
    )
  })

  it('applies state from SSE events', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test', 'deepseek-v4-flash')
    const es = MockEventSource.instances[0]

    es.emit('agent', mockState({
      messages: [{ role: 'assistant', content: 'Hi' }],
      operation_log: ['step 1'],
    }))

    expect(store.messages).toEqual([{ role: 'assistant', content: 'Hi' }])
    expect(store.operationLog).toEqual(['step 1'])
  })

  it('reconnect syncs state and reopens the event stream', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test', 'deepseek-v4-flash')
    store.disconnect()
    MockEventSource.instances = []

    vi.mocked(client.get).mockResolvedValue({
      data: {
        thread_id: 'thread-1',
        ...mockState({ messages: [{ role: 'assistant', content: 'Welcome back' }] }),
      },
    })

    await store.reconnect()

    expect(store.messages).toEqual([{ role: 'assistant', content: 'Welcome back' }])
    expect(MockEventSource.instances).toHaveLength(1)
  })

  it('lists threads for a project', async () => {
    const store = useAgentStore()
    vi.spyOn(agentApi, 'listThreads').mockResolvedValueOnce({ threads: [] })
    await store.listThreads('p1')
    expect(store.threads).toEqual([])
  })
})
