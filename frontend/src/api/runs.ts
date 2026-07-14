import client from './client'
import { API_BASE } from './client'
import type { AnalysisConfig } from './projects'

export const DEFAULT_RUN_LLM_MODEL = 'deepseek-v4-pro'

export interface RunRecord {
  id: string
  project_id: string
  image_dir: string
  clinical_path: string
  output_dir: string
  modality: string
  covariates: string
  model: string
  analysis_model: string
  llm_model: string
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
  const res = await client.post(`/projects/${encodeURIComponent(projectId)}/runs`, config)
  return res.data
}

export const getRun = async (runId: string): Promise<RunRecord> => {
  const res = await client.get(`/runs/${encodeURIComponent(runId)}`)
  return res.data
}

export const cancelRun = async (runId: string): Promise<void> => {
  await client.post(`/runs/${encodeURIComponent(runId)}/cancel`)
}

export const connectRunEvents = (
  runId: string,
  callbacks: RunEventCallbacks = {}
): EventSource => {
  const es = new EventSource(
    `${API_BASE}/runs/${encodeURIComponent(runId)}/events`
  )

  es.addEventListener('pipeline', (event: MessageEvent) => {
    try {
      const data = JSON.parse(event.data) as Record<string, unknown>
      callbacks.onEvent?.(data)

      if (data.type === 'pipeline_log' && typeof data.message === 'string') {
        callbacks.onLog?.(data.message)
      } else if (data.type === 'pipeline_complete') {
        getRun(runId)
          .then((run) => callbacks.onComplete?.(run))
          .catch((err) => console.error('Failed to fetch completed run', err))
      } else if (data.type === 'pipeline_error') {
        callbacks.onError?.(data)
      }
    } catch (err) {
      console.error('Failed to parse pipeline SSE payload', err)
    }
  })

  es.addEventListener('run', (event: MessageEvent) => {
    try {
      const data = JSON.parse(event.data) as Record<string, unknown>
      callbacks.onEvent?.(data)
    } catch (err) {
      console.error('Failed to parse run SSE payload', err)
    }
  })

  // Keep the connection open on transient errors; the browser will reconnect
  // automatically per the EventSource spec. close() is only called from the
  // consumer when the stream is truly finished.
  es.onerror = () => {
    callbacks.onError?.({ message: 'EventSource error' })
  }

  return es
}
