import { ref } from 'vue'
import { defineStore } from 'pinia'
import * as api from '@/api/runs'
import { DEFAULT_RUN_LLM_MODEL } from '@/api/runs'
import type { RunRecord } from '@/api/runs'
import type { AnalysisConfig } from '@/api/projects'

export const useRunStore = defineStore('run', () => {
  const currentRun = ref<RunRecord | null>(null)
  const logs = ref<string[]>([])
  const running = ref(false)
  const cancelling = ref(false)
  const reportUrl = ref<string | null>(null)

  let es: EventSource | null = null

  function disconnect(): void {
    if (es) {
      es.close()
      es = null
    }
  }

  async function startRun(projectId: string, config: AnalysisConfig): Promise<string> {
    disconnect()
    logs.value = []
    reportUrl.value = null
    running.value = true

    const { run_id } = await api.startRun(projectId, config)

    currentRun.value = {
      id: run_id,
      project_id: projectId,
      ...config,
      llm_model: DEFAULT_RUN_LLM_MODEL,
      status: 'running',
      log_summary: '',
      report_path: '',
      started_at: new Date().toISOString(),
    } as RunRecord

    es = api.connectRunEvents(run_id, {
      onEvent: (data) => {
        if (data.type === 'pipeline_log' && typeof data.message === 'string') {
          logs.value.push(data.message)
        }
        if (data.type === 'pipeline_cancelled') {
          if (currentRun.value) {
            currentRun.value.status = 'cancelled'
          }
          running.value = false
          disconnect()
          return
        }
        if (typeof data.report_path === 'string' && data.report_path) {
          reportUrl.value = data.report_path
        }
      },
      onComplete: (run) => {
        currentRun.value = run
        running.value = false
        reportUrl.value = run.report_path || null
        disconnect()
      },
      onError: () => {
        if (currentRun.value) {
          currentRun.value.status = 'failed'
        }
        running.value = false
        disconnect()
      },
    })

    return run_id
  }

  async function stopRun(runId: string): Promise<void> {
    cancelling.value = true
    try {
      await api.cancelRun(runId)
    } finally {
      disconnect()
      running.value = false
      cancelling.value = false
      if (currentRun.value) {
        currentRun.value.status = 'cancelled'
      }
    }
  }

  function clearLogs(): void {
    logs.value = []
  }

  return {
    currentRun,
    logs,
    running,
    cancelling,
    reportUrl,
    startRun,
    stopRun,
    disconnect,
    clearLogs,
  }
})
