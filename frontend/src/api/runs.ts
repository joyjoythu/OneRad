import client from './client'
import type { AnalysisConfig } from './projects'

export interface RunRecord {
  id: string
  project_id: string
  image_dir: string
  clinical_path: string
  output_dir: string
  modality: string
  covariates: string
  model: string
  status: string
  log_summary: string
  report_path: string
  started_at: string
  finished_at?: string
}

export interface StartRunResponse {
  run_id: string
}

export interface RunEventCallbacks {
  onEvent?: (data: Record<string, unknown>) => void
  onLog?: (log: string) => void
  onComplete?: (run: RunRecord) => void
  onError?: (error: Record<string, unknown>) => void
}

export const startRun = async (
  projectId: string,
  config: AnalysisConfig
): Promise<StartRunResponse> => {
  const res = await client.post(`/projects/${projectId}/runs`, config)
  return res.data
}

export const getRun = async (runId: string): Promise<RunRecord> => {
  const res = await client.get(`/runs/${runId}`)
  return res.data
}

export const connectRunEvents = (
  runId: string,
  callbacks: RunEventCallbacks = {}
): EventSource => {
  const es = new EventSource(`/api/runs/${runId}/events`)

  es.addEventListener('pipeline', (event: MessageEvent) => {
    try {
      const data = JSON.parse(event.data) as Record<string, unknown>
      callbacks.onEvent?.(data)

      if (data.type === 'pipeline_log' && typeof data.message === 'string') {
        callbacks.onLog?.(data.message)
      } else if (data.type === 'pipeline_complete') {
        getRun(runId)
          .then((run) => callbacks.onComplete?.(run))
          .catch(() => {})
      } else if (data.type === 'pipeline_error') {
        callbacks.onError?.(data)
      }
    } catch {
      // Ignore malformed SSE payloads.
    }
  })

  es.addEventListener('run', (event: MessageEvent) => {
    try {
      const data = JSON.parse(event.data) as Record<string, unknown>
      callbacks.onEvent?.(data)
    } catch {
      // Ignore malformed SSE payloads.
    }
  })

  es.onerror = () => {
    callbacks.onError?.({ message: 'EventSource error' })
  }

  return es
}
