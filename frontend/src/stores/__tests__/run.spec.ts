import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useRunStore } from '../run'
import client from '@/api/client'
import type { RunRecord, AnalysisConfig } from '@/api/runs'

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
  API_BASE: '/api',
}))

const mockConfig: AnalysisConfig = {
  image_dir: '',
  clinical_path: '',
  output_dir: './outputs',
  modality: 'auto',
  covariates: '',
  model: 'deepseek-v4-pro',
  api_key: '',
}

const mockRun = (id: string, projectId: string): RunRecord => ({
  id,
  project_id: projectId,
  ...mockConfig,
  status: 'completed',
  log_summary: '',
  report_path: `/reports/${id}.pdf`,
  started_at: new Date().toISOString(),
  finished_at: new Date().toISOString(),
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

describe('useRunStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('EventSource', MockEventSource)
    MockEventSource.instances = []
    vi.mocked(client.post).mockResolvedValue({ data: { run_id: 'run-1' } })
    vi.mocked(client.get).mockResolvedValue({
      data: mockRun('run-1', 'project-1'),
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('startRun sets running and creates a current run', async () => {
    const store = useRunStore()
    const runId = await store.startRun('project-1', mockConfig)

    expect(client.post).toHaveBeenCalledWith(
      '/projects/project-1/runs',
      mockConfig
    )
    expect(runId).toBe('run-1')
    expect(store.running).toBe(true)
    expect(store.currentRun?.id).toBe('run-1')
  })

  it('appends pipeline_log messages to logs', async () => {
    const store = useRunStore()
    await store.startRun('project-1', mockConfig)
    const es = MockEventSource.instances[0]

    es.emit('pipeline', { type: 'pipeline_log', message: 'Step 1 done' })

    expect(store.logs).toEqual(['Step 1 done'])
  })

  it('completes the run and updates state', async () => {
    const completedRun = mockRun('run-1', 'project-1')
    vi.mocked(client.get).mockResolvedValue({ data: completedRun })
    const store = useRunStore()
    await store.startRun('project-1', mockConfig)
    const es = MockEventSource.instances[0]

    es.emit('pipeline', { type: 'pipeline_complete' })
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(client.get).toHaveBeenCalledWith('/runs/run-1')
    expect(store.currentRun).toEqual(completedRun)
    expect(store.running).toBe(false)
    expect(store.reportUrl).toBe(`/reports/${completedRun.id}.pdf`)
  })
})
