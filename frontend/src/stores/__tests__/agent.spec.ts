import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAgentStore } from '../agent'
import client from '@/api/client'
import * as agentApi from '@/api/agent'
import type { AgentState, PendingRadiomicsAnalysis } from '@/api/agent'

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

const mockAnalysis: PendingRadiomicsAnalysis = {
  tool_call_id: 'tc-analysis-1',
  feature_csv: 'path/to/radiomics_features.csv',
  clinical: 'path/to/clinical.xlsx',
  id_col: 'patient_id',
  label_col: 'Label',
  covariates: ['age', 'gender'],
  output_dir: 'path/to/output',
  n_feature_cases: 100,
  n_features: 120,
  n_matched: 95,
  available_clinical_columns: ['age', 'gender', 'Label'],
}

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
    await store.ensureThread('project-1', 'sk-test')
    await store.sendMessage('Hello')

    expect(store.messages).toContainEqual({ role: 'user', content: 'Hello' })
    expect(client.post).toHaveBeenCalledWith(
      '/agent/threads/thread-1/messages',
      { role: 'user', content: 'Hello' }
    )
  })

  it('sendMessage marks the store busy until the stream ends', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test')
    await store.sendMessage('Hello')

    expect(store.busy).toBe(true)

    const es = MockEventSource.instances[0]
    es.emit('agent_end', {})
    expect(store.busy).toBe(false)
  })

  it('syncs the final state from the server when the stream ends', async () => {
    // SSE 只推订阅后的新事件，订阅空窗内可能漏事件；
    // agent_end 时必须同步一次最终状态保证收敛。
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test')
    await store.sendMessage('Hello')
    vi.mocked(client.get).mockClear()

    const es = MockEventSource.instances[0]
    es.emit('agent_end', {})

    expect(client.get).toHaveBeenCalledWith('/agent/threads/thread-1')
  })

  it('refreshes the thread list when the stream ends so generated titles show up', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test')
    await store.sendMessage('Hello')
    const listSpy = vi.spyOn(agentApi, 'listThreads').mockResolvedValue({ threads: [] })

    const es = MockEventSource.instances[0]
    es.emit('agent_end', {})

    expect(listSpy).toHaveBeenCalledWith('project-1')
  })

  it('sendMessage rolls back the optimistic message and clears busy on API failure', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test')
    vi.mocked(client.post).mockRejectedValueOnce({
      response: { data: { detail: '智能体正在处理中' } },
    })

    await expect(store.sendMessage('Second')).rejects.toBeTruthy()
    expect(store.messages).not.toContainEqual({ role: 'user', content: 'Second' })
    expect(store.busy).toBe(false)
  })

  it('keeps existing messages when an error payload arrives over SSE', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test')
    const es = MockEventSource.instances[0]
    es.emit('agent', mockState({ messages: [{ role: 'user', content: 'Hello' }] }))
    expect(store.messages).toHaveLength(1)

    es.emit('agent', { ...mockState(), messages: [], error: 'stream error: boom' })

    expect(store.messages).toEqual([{ role: 'user', content: 'Hello' }])
    expect(store.busy).toBe(false)
  })

  it('keeps busy when a running snapshot carries a stale interrupt_type', async () => {
    // 点「确认」后 human_review 的中间快照仍带 interrupt_type（尚未被
    // execute_confirmed 清除），但 running=true 表示运行仍在继续，
    // busy 必须保持——否则停止按钮会在工具执行期间消失。
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test')
    await store.sendMessage('Hello')
    expect(store.busy).toBe(true)

    const es = MockEventSource.instances[0]
    es.emit('agent', mockState({ interrupt_type: 'python_script', running: true }))

    expect(store.interrupt).toBe('python_script')
    expect(store.busy).toBe(true)
  })

  it('clears busy when a snapshot reports running false', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test')
    await store.sendMessage('Hello')
    expect(store.busy).toBe(true)

    const es = MockEventSource.instances[0]
    es.emit('agent', mockState({ interrupt_type: 'file_plan', running: false }))

    expect(store.interrupt).toBe('file_plan')
    expect(store.busy).toBe(false)
  })

  it('stop calls the stop API and clears busy', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test')
    await store.sendMessage('Hello')
    expect(store.busy).toBe(true)

    await store.stop()

    expect(client.post).toHaveBeenCalledWith('/agent/threads/thread-1/stop')
    expect(store.busy).toBe(false)
  })

  it('stop clears busy even when the API fails', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test')
    await store.sendMessage('Hello')
    expect(store.busy).toBe(true)
    vi.mocked(client.post).mockRejectedValueOnce(new Error('network error'))

    await expect(store.stop()).rejects.toThrow('network error')
    expect(store.busy).toBe(false)
  })

  it('applies state from SSE events', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test')
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
    await store.ensureThread('project-1', 'sk-test')
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

  it('listThreads also syncs the per-project cache', async () => {
    const store = useAgentStore()
    const thread = {
      id: 't1',
      project_id: 'p1',
      title: 'T1',
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    }
    vi.spyOn(agentApi, 'listThreads').mockResolvedValueOnce({ threads: [thread] })

    await store.listThreads('p1')

    expect(store.threadsByProject['p1']).toEqual([thread])
  })

  it('loadProjectThreads caches threads per project without touching current list', async () => {
    const store = useAgentStore()
    const thread = {
      id: 't2',
      project_id: 'p2',
      title: 'T2',
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    }
    const spy = vi.spyOn(agentApi, 'listThreads').mockResolvedValueOnce({ threads: [thread] })

    await store.loadProjectThreads('p2')

    expect(spy).toHaveBeenCalledWith('p2')
    expect(store.threadsByProject['p2']).toEqual([thread])
    expect(store.threads).toEqual([])
  })

  it('resetThread clears the flat list but keeps the per-project cache', async () => {
    const store = useAgentStore()
    const thread = {
      id: 't1',
      project_id: 'p1',
      title: 'T1',
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    }
    vi.spyOn(agentApi, 'listThreads').mockResolvedValueOnce({ threads: [thread] })
    await store.listThreads('p1')

    store.resetThread()

    expect(store.threads).toEqual([])
    expect(store.threadsByProject['p1']).toEqual([thread])
  })

  it('deleteThread of another project only refreshes the cache, not the flat list', async () => {
    const store = useAgentStore()
    const current = {
      id: 't-cur',
      project_id: 'p1',
      title: 'Current',
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    }
    vi.spyOn(agentApi, 'listThreads').mockResolvedValueOnce({ threads: [current] })
    await store.listThreads('p1')

    vi.spyOn(agentApi, 'deleteThread').mockResolvedValueOnce(undefined)
    const otherSpy = vi
      .spyOn(agentApi, 'listThreads')
      .mockResolvedValueOnce({ threads: [] })

    await store.deleteThread('t-other', 'p2')

    expect(otherSpy).toHaveBeenCalledWith('p2')
    expect(store.threads).toEqual([current])
    expect(store.threadsByProject['p2']).toEqual([])
  })

  it('createThread creates a new thread, refreshes the list and connects SSE', async () => {
    const store = useAgentStore()
    vi.spyOn(agentApi, 'createThread').mockResolvedValueOnce({ thread_id: 'thread-new' })
    vi.spyOn(agentApi, 'listThreads').mockResolvedValueOnce({
      threads: [
        {
          id: 'thread-new',
          project_id: 'project-1',
          title: 'New Thread',
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        },
      ],
    })

    const id = await store.createThread('project-1', 'sk-test')

    expect(id).toBe('thread-new')
    expect(agentApi.createThread).toHaveBeenCalledWith('project-1', {
      api_key: 'sk-test',
      auto_approve: false,
    })
    expect(store.threadId).toBe('thread-new')
    expect(store.currentThread).toEqual({
      id: 'thread-new',
      project_id: 'project-1',
      title: 'New Thread',
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    })
    expect(store.threads).toHaveLength(1)
    expect(MockEventSource.instances).toHaveLength(1)
  })

  it('loadThread resumes a thread, applies state and connects SSE', async () => {
    const store = useAgentStore()
    store.threads = [
      {
        id: 'thread-load',
        project_id: 'project-1',
        title: 'Loaded Thread',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      },
    ]
    vi.spyOn(agentApi, 'resumeThread').mockResolvedValueOnce({
      thread_id: 'thread-load',
      ...mockState({
        messages: [{ role: 'assistant', content: 'Resumed' }],
        operation_log: ['loaded'],
      }),
    })

    await store.loadThread('thread-load', 'sk-test')

    expect(agentApi.resumeThread).toHaveBeenCalledWith('thread-load', {
      api_key: 'sk-test',
      auto_approve: false,
    })
    expect(store.threadId).toBe('thread-load')
    expect(store.currentThread).toEqual({
      id: 'thread-load',
      project_id: 'project-1',
      title: 'Loaded Thread',
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    })
    expect(store.messages).toEqual([{ role: 'assistant', content: 'Resumed' }])
    expect(store.operationLog).toEqual(['loaded'])
    expect(MockEventSource.instances).toHaveLength(1)
  })

  it('loadThread resolves currentThread from the per-project cache when the flat list is empty', async () => {
    const store = useAgentStore()
    const thread = {
      id: 'thread-cached',
      project_id: 'project-9',
      title: 'Cached Thread',
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    }
    store.threadsByProject = { 'project-9': [thread] }
    vi.spyOn(agentApi, 'resumeThread').mockResolvedValueOnce({
      thread_id: 'thread-cached',
      ...mockState(),
    })

    await store.loadThread('thread-cached', 'sk-test')

    expect(store.currentThread?.project_id).toBe('project-9')
    expect(store.currentThread?.title).toBe('Cached Thread')
  })

  it('tracks radiomics progress from SSE and clears it on stream end', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test')
    await store.sendMessage('提取特征')
    const es = MockEventSource.instances[0]

    es.emit('agent', {
      radiomics_progress: { stage: 'extracting', current: 2, total: 5, patient_id: 'case_002' },
      running: true,
    })
    expect(store.radiomicsProgress).toEqual({
      stage: 'extracting',
      current: 2,
      total: 5,
      patient_id: 'case_002',
    })
    expect(store.busy).toBe(true)

    // 进度事件不带 messages 等字段时，现有消息不受影响
    expect(store.messages).toEqual([{ role: 'user', content: '提取特征' }])

    es.emit('agent', { radiomics_progress: null, running: true })
    expect(store.radiomicsProgress).toBeNull()

    es.emit('agent', {
      radiomics_progress: { stage: 'extracting', current: 3, total: 5 },
      running: true,
    })
    es.emit('agent_end', {})
    expect(store.radiomicsProgress).toBeNull()
    expect(store.busy).toBe(false)
  })

  it('stop clears radiomics progress', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test')
    await store.sendMessage('提取特征')
    const es = MockEventSource.instances[0]
    es.emit('agent', {
      radiomics_progress: { stage: 'extracting', current: 1, total: 5 },
      running: true,
    })
    expect(store.radiomicsProgress).not.toBeNull()

    await store.stop()

    expect(store.radiomicsProgress).toBeNull()
    expect(store.busy).toBe(false)
  })

  it('tracks thinking stream from SSE and clears it on stream end', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test')
    await store.sendMessage('你好')
    const es = MockEventSource.instances[0]

    es.emit('agent', { thinking: { text: '先分析', done: false }, running: true })
    expect(store.currentThinking).toEqual({ text: '先分析', done: false })
    expect(store.busy).toBe(true)
    // thinking 事件不带 messages 字段时，现有消息不受影响
    expect(store.messages).toEqual([{ role: 'user', content: '你好' }])

    es.emit('agent', { thinking: { text: '先分析再回答', done: true }, running: true })
    expect(store.currentThinking).toEqual({ text: '先分析再回答', done: true })

    es.emit('agent_end', {})
    expect(store.currentThinking).toBeNull()
    expect(store.busy).toBe(false)
  })

  it('clears current thinking when an error payload arrives', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test')
    await store.sendMessage('你好')
    const es = MockEventSource.instances[0]

    es.emit('agent', { thinking: { text: '思考中', done: false }, running: true })
    expect(store.currentThinking).not.toBeNull()

    es.emit('agent', { ...mockState(), messages: [], error: 'stream error: boom' })
    expect(store.currentThinking).toBeNull()
    expect(store.busy).toBe(false)
  })

  it('stop clears current thinking', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test')
    await store.sendMessage('你好')
    const es = MockEventSource.instances[0]
    es.emit('agent', { thinking: { text: '思考中', done: false }, running: true })
    expect(store.currentThinking).not.toBeNull()

    await store.stop()

    expect(store.currentThinking).toBeNull()
    expect(store.busy).toBe(false)
  })

  it('clears current thinking when the event stream errors', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test')
    await store.sendMessage('你好')
    const es = MockEventSource.instances[0]
    es.emit('agent', { thinking: { text: '思考中', done: false }, running: true })
    expect(store.currentThinking).not.toBeNull()

    es.onerror?.(new Event('error'))

    expect(store.currentThinking).toBeNull()
  })

  it('tracks pending radiomics plan/execution from SSE state', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test')
    const es = MockEventSource.instances[0]

    const execution = {
      tool_call_id: 'tc1',
      pairs: [{ patient_id: 'p1', image_path: 'images/p1.nii.gz', mask_path: 'masks/p1.nii.gz' }],
      n_cases: 1,
      yaml_path: 'Params_labels.yaml',
      output_dir: 'radiomics_features',
    }
    es.emit('agent', mockState({
      interrupt_type: 'radiomics_execution',
      pending_radiomics_execution: execution,
    }))
    expect(store.pendingRadiomicsExecution).toEqual(execution)
    expect(store.interrupt).toBe('radiomics_execution')

    // 确认/取消后后端返回清空后的状态
    es.emit('agent', mockState({
      interrupt_type: null,
      pending_radiomics_execution: null,
      pending_radiomics_plan: null,
    }))
    expect(store.pendingRadiomicsExecution).toBeNull()
    expect(store.pendingRadiomicsPlan).toBeNull()
    expect(store.interrupt).toBeNull()
  })

  it('tracks pending radiomics analysis from SSE state', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test')
    const es = MockEventSource.instances[0]

    es.emit('agent', mockState({
      interrupt_type: 'radiomics_analysis',
      pending_radiomics_analysis: mockAnalysis,
    }))
    expect(store.pendingRadiomicsAnalysis).toEqual(mockAnalysis)
    expect(store.interrupt).toBe('radiomics_analysis')

    // 确认/取消后后端返回清空后的状态
    es.emit('agent', mockState({
      interrupt_type: null,
      pending_radiomics_analysis: null,
    }))
    expect(store.pendingRadiomicsAnalysis).toBeNull()
    expect(store.interrupt).toBeNull()
  })

  it('resetThread clears pending radiomics analysis', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test')
    const es = MockEventSource.instances[0]

    es.emit('agent', mockState({
      pending_radiomics_analysis: mockAnalysis,
    }))
    expect(store.pendingRadiomicsAnalysis).not.toBeNull()

    store.resetThread()

    expect(store.pendingRadiomicsAnalysis).toBeNull()
  })

  it('deleteThread removes the current thread and resets internal state', async () => {
    const store = useAgentStore()
    vi.spyOn(agentApi, 'createThread').mockResolvedValueOnce({ thread_id: 'thread-del' })
    vi.spyOn(agentApi, 'listThreads').mockResolvedValue({
      threads: [
        {
          id: 'thread-del',
          project_id: 'project-1',
          title: 'To Delete',
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        },
      ],
    })
    await store.createThread('project-1', 'sk-test')

    vi.spyOn(agentApi, 'deleteThread').mockResolvedValueOnce(undefined)
    const listSpy = vi.spyOn(agentApi, 'listThreads').mockResolvedValueOnce({ threads: [] })

    await store.deleteThread('thread-del', 'project-1')

    expect(agentApi.deleteThread).toHaveBeenCalledWith('thread-del')
    expect(store.threadId).toBeNull()
    expect(store.currentThread).toBeNull()
    expect(store.messages).toEqual([])
    expect(listSpy).toHaveBeenCalledWith('project-1')
    expect(store.threads).toEqual([])
  })

  it('deleteThread refreshes the list without resetting state when deleting another thread', async () => {
    const store = useAgentStore()
    vi.spyOn(agentApi, 'createThread').mockResolvedValueOnce({ thread_id: 'thread-current' })
    vi.spyOn(agentApi, 'listThreads').mockResolvedValue({
      threads: [
        {
          id: 'thread-current',
          project_id: 'project-1',
          title: 'Current',
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        },
        {
          id: 'thread-other',
          project_id: 'project-1',
          title: 'Other',
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        },
      ],
    })
    await store.createThread('project-1', 'sk-test')

    vi.spyOn(agentApi, 'deleteThread').mockResolvedValueOnce(undefined)
    const listSpy = vi.spyOn(agentApi, 'listThreads').mockResolvedValueOnce({
      threads: [
        {
          id: 'thread-current',
          project_id: 'project-1',
          title: 'Current',
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        },
      ],
    })

    await store.deleteThread('thread-other', 'project-1')

    expect(store.threadId).toBe('thread-current')
    expect(store.currentThread).not.toBeNull()
    expect(listSpy).toHaveBeenCalledWith('project-1')
    expect(store.threads).toHaveLength(1)
  })

  it('renameThread renames a thread, refreshes the list and updates currentThread.title', async () => {
    const store = useAgentStore()
    vi.spyOn(agentApi, 'createThread').mockResolvedValueOnce({ thread_id: 'thread-ren' })
    vi.spyOn(agentApi, 'listThreads').mockResolvedValue({
      threads: [
        {
          id: 'thread-ren',
          project_id: 'project-1',
          title: 'Old Title',
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        },
      ],
    })
    await store.createThread('project-1', 'sk-test')

    vi.spyOn(agentApi, 'renameThread').mockResolvedValueOnce({
      thread: {
        id: 'thread-ren',
        project_id: 'project-1',
        title: 'Renamed Title',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-02T00:00:00Z',
      },
    })
    const listSpy = vi.spyOn(agentApi, 'listThreads').mockResolvedValueOnce({
      threads: [
        {
          id: 'thread-ren',
          project_id: 'project-1',
          title: 'Renamed Title',
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-02T00:00:00Z',
        },
      ],
    })

    await store.renameThread('thread-ren', 'Renamed Title', 'project-1')

    expect(agentApi.renameThread).toHaveBeenCalledWith('thread-ren', 'Renamed Title')
    expect(listSpy).toHaveBeenCalledWith('project-1')
    expect(store.currentThread?.title).toBe('Renamed Title')
  })

  it('renameThread does not change currentThread when renaming another thread', async () => {
    const store = useAgentStore()
    store.threads = [
      {
        id: 'thread-current',
        project_id: 'project-1',
        title: 'Current',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      },
      {
        id: 'thread-other',
        project_id: 'project-1',
        title: 'Other',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      },
    ]
    store.currentThread = store.threads[0]

    vi.spyOn(agentApi, 'renameThread').mockResolvedValueOnce({
      thread: {
        id: 'thread-other',
        project_id: 'project-1',
        title: 'Renamed Other',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-02T00:00:00Z',
      },
    })
    vi.spyOn(agentApi, 'listThreads').mockResolvedValueOnce({
      threads: [
        {
          id: 'thread-current',
          project_id: 'project-1',
          title: 'Current',
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        },
        {
          id: 'thread-other',
          project_id: 'project-1',
          title: 'Renamed Other',
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-02T00:00:00Z',
        },
      ],
    })

    await store.renameThread('thread-other', 'Renamed Other', 'project-1')

    expect(store.currentThread?.id).toBe('thread-current')
    expect(store.currentThread?.title).toBe('Current')
  })

  describe('setAutoApprove', () => {
    it('updates locally without an active thread', async () => {
      const store = useAgentStore()

      await store.setAutoApprove(true)

      expect(store.autoApprove).toBe(true)
      expect(vi.mocked(client.put)).not.toHaveBeenCalled()
    })

    it('sends the flag to the backend when a thread is active', async () => {
      const store = useAgentStore()
      await store.ensureThread('project-1', '')
      vi.mocked(client.put).mockResolvedValue({ data: { auto_approve: true } })

      await store.setAutoApprove(true)

      expect(client.put).toHaveBeenCalledWith('/agent/threads/thread-1/auto-approve', {
        enabled: true,
      })
      expect(store.autoApprove).toBe(true)
    })

    it('rolls back on API failure', async () => {
      const store = useAgentStore()
      await store.ensureThread('project-1', '')
      vi.mocked(client.put).mockRejectedValue(new Error('boom'))

      await expect(store.setAutoApprove(true)).rejects.toThrow('boom')

      expect(store.autoApprove).toBe(false)
    })

    it('includes auto_approve when creating a thread', async () => {
      const store = useAgentStore()
      await store.setAutoApprove(true)

      await store.createThread('project-1', 'sk-test')

      expect(client.post).toHaveBeenCalledWith(
        '/agent/threads',
        { api_key: 'sk-test', auto_approve: true },
        { params: { project_id: 'project-1' } }
      )
    })

    it('exposes syncing state during the API call', async () => {
      const store = useAgentStore()
      await store.ensureThread('project-1', '')
      let resolvePut: (value: { data: { auto_approve: boolean } }) => void = () => {}
      vi.mocked(client.put).mockImplementation(
        () =>
          new Promise((resolve) => {
            resolvePut = resolve
          })
      )

      const pending = store.setAutoApprove(true)
      expect(store.autoApproveSyncing).toBe(true)
      resolvePut({ data: { auto_approve: true } })
      await pending

      expect(store.autoApproveSyncing).toBe(false)
      expect(store.autoApprove).toBe(true)
    })

    it('includes auto_approve when loading a thread', async () => {
      const store = useAgentStore()
      await store.setAutoApprove(true)
      vi.spyOn(agentApi, 'resumeThread').mockResolvedValueOnce({
        thread_id: 'thread-load',
        ...mockState(),
      })

      await store.loadThread('thread-load', 'sk-test')

      expect(agentApi.resumeThread).toHaveBeenCalledWith('thread-load', {
        api_key: 'sk-test',
        auto_approve: true,
      })
    })

    it('keeps autoApprove across thread switches', async () => {
      const store = useAgentStore()
      await store.ensureThread('project-1', '')
      vi.mocked(client.put).mockResolvedValue({ data: { auto_approve: true } })
      await store.setAutoApprove(true)

      vi.spyOn(agentApi, 'resumeThread').mockResolvedValueOnce({
        thread_id: 'thread-load',
        ...mockState(),
      })
      await store.loadThread('thread-load', 'sk-test')

      expect(store.autoApprove).toBe(true)
    })
  })

  describe('thread running status', () => {
    const threadSummary = (overrides: Record<string, unknown> = {}) => ({
      id: 't-1',
      project_id: 'p-1',
      title: '',
      created_at: '',
      updated_at: '',
      ...overrides,
    })

    it('tracks running threads from list responses', async () => {
      const store = useAgentStore()
      vi.mocked(client.get).mockResolvedValue({
        data: { threads: [threadSummary({ running: true })] },
      })

      await store.loadProjectThreads('p-1')

      expect(store.runningThreadIds.has('t-1')).toBe(true)
      expect(store.finishedThreadIds.has('t-1')).toBe(false)
    })

    it('moves a finished background thread into finishedThreadIds', async () => {
      const store = useAgentStore()
      vi.mocked(client.get).mockResolvedValue({
        data: { threads: [threadSummary({ running: true })] },
      })
      await store.loadProjectThreads('p-1')

      vi.mocked(client.get).mockResolvedValue({
        data: { threads: [threadSummary({ running: false })] },
      })
      await store.loadProjectThreads('p-1')

      expect(store.runningThreadIds.has('t-1')).toBe(false)
      expect(store.finishedThreadIds.has('t-1')).toBe(true)
    })

    it('does not flag completion for the currently open thread', async () => {
      const store = useAgentStore()
      store.threadId = 't-1'
      vi.mocked(client.get).mockResolvedValue({
        data: { threads: [threadSummary({ running: true })] },
      })
      await store.loadProjectThreads('p-1')

      vi.mocked(client.get).mockResolvedValue({
        data: { threads: [threadSummary({ running: false })] },
      })
      await store.loadProjectThreads('p-1')

      expect(store.runningThreadIds.has('t-1')).toBe(false)
      expect(store.finishedThreadIds.has('t-1')).toBe(false)
    })

    it('clears the finished dot when the thread is opened', async () => {
      const store = useAgentStore()
      store.finishedThreadIds.add('t-1')
      vi.spyOn(agentApi, 'resumeThread').mockResolvedValueOnce({
        thread_id: 't-1',
        ...mockState(),
      })

      await store.loadThread('t-1', 'sk-test')

      expect(store.finishedThreadIds.has('t-1')).toBe(false)
    })

    it('marks the current thread running on sendMessage and clears it on stream end', async () => {
      const store = useAgentStore()
      await store.ensureThread('project-1', 'sk-test')
      await store.sendMessage('Hello')

      expect(store.runningThreadIds.has('thread-1')).toBe(true)

      MockEventSource.instances[0].emit('agent_end', {})
      expect(store.runningThreadIds.has('thread-1')).toBe(false)
      expect(store.finishedThreadIds.has('thread-1')).toBe(false)
    })

    it('removes deleted threads from the status sets', async () => {
      const store = useAgentStore()
      store.runningThreadIds.add('t-9')
      store.finishedThreadIds.add('t-9')
      vi.mocked(client.get).mockResolvedValue({ data: { threads: [] } })

      await store.deleteThread('t-9', 'p-1')

      expect(store.runningThreadIds.has('t-9')).toBe(false)
      expect(store.finishedThreadIds.has('t-9')).toBe(false)
    })
  })
})
