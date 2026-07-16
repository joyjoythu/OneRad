import { ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import * as api from '@/api/agent'
import type {
  AgentState,
  AgentMessage,
  PendingPlan,
  PendingCommand,
  PendingScript,
  PendingRadiomicsPlan,
  PendingRadiomicsExecution,
  PendingRadiomicsAnalysis,
  RadiomicsProgress,
  ThreadSummary,
} from '@/api/agent'

export const useAgentStore = defineStore('agent', () => {
  const threadId = ref<string | null>(null)
  const messages = ref<AgentMessage[]>([])
  const interrupt = ref<string | null>(null)
  const operationLog = ref<string[]>([])
  const pendingPlan = ref<PendingPlan | null>(null)
  const pendingCommand = ref<PendingCommand | null>(null)
  const pendingScript = ref<PendingScript | null>(null)
  const pendingRadiomicsPlan = ref<PendingRadiomicsPlan | null>(null)
  const pendingRadiomicsExecution = ref<PendingRadiomicsExecution | null>(null)
  const pendingRadiomicsAnalysis = ref<PendingRadiomicsAnalysis | null>(null)

  const threads = ref<ThreadSummary[]>([])
  const currentThread = ref<ThreadSummary | null>(null)
  // 智能体是否正在处理中（流式运行期间为 true），用于禁用输入并展示状态。
  const busy = ref(false)
  // 影像组学特征提取的实时进度（由后端节点线程推送，null 表示无提取在进行）。
  const radiomicsProgress = ref<RadiomicsProgress | null>(null)

  let es: EventSource | null = null

  function applyState(state: Partial<AgentState>): void {
    if (state.error) {
      // 流式运行出错：保留现有消息，仅提示错误并解除忙碌。
      busy.value = false
      ElMessage.error(state.error)
    }
    // 错误载荷中的 messages 为空数组，不能直接覆盖现有消息。
    if (state.messages && (state.messages.length > 0 || !state.error)) {
      messages.value = state.messages
    }
    if (state.interrupt_type !== undefined) {
      interrupt.value = state.interrupt_type
    }
    if (state.running !== undefined) {
      // 运行状态以后端显式上报为准；不能用 interrupt_type 推断——
      // 确认后 execute_confirmed 清除前的中间快照仍带 interrupt_type。
      busy.value = state.running
    }
    if (state.operation_log) {
      operationLog.value = state.operation_log
    }
    if (state.pending_plan !== undefined) {
      pendingPlan.value = state.pending_plan
    }
    if (state.pending_command !== undefined) {
      pendingCommand.value = state.pending_command
    }
    if (state.pending_script !== undefined) {
      pendingScript.value = state.pending_script
    }
    if (state.pending_radiomics_plan !== undefined) {
      pendingRadiomicsPlan.value = state.pending_radiomics_plan
    }
    if (state.pending_radiomics_execution !== undefined) {
      pendingRadiomicsExecution.value = state.pending_radiomics_execution
    }
    if (state.pending_radiomics_analysis !== undefined) {
      pendingRadiomicsAnalysis.value = state.pending_radiomics_analysis
    }
    if (state.radiomics_progress !== undefined) {
      radiomicsProgress.value = state.radiomics_progress
    }
  }

  function resetInternalState(): void {
    disconnect()
    threadId.value = null
    messages.value = []
    interrupt.value = null
    operationLog.value = []
    pendingPlan.value = null
    pendingCommand.value = null
    pendingScript.value = null
    pendingRadiomicsPlan.value = null
    pendingRadiomicsExecution.value = null
    pendingRadiomicsAnalysis.value = null
    currentThread.value = null
    busy.value = false
    radiomicsProgress.value = null
  }

  async function ensureThread(
    projectId: string,
    apiKey: string,
    llmModel: string
  ): Promise<string> {
    if (threadId.value) {
      if (!currentThread.value) {
        currentThread.value =
          threads.value.find((t) => t.id === threadId.value) || {
            id: threadId.value,
            project_id: projectId,
            title: '',
            llm_model: llmModel,
            created_at: '',
            updated_at: '',
          }
      }
      return threadId.value
    }
    const { thread_id } = await api.createThread(projectId, {
      api_key: apiKey,
      llm_model: llmModel,
    })
    threadId.value = thread_id
    currentThread.value = {
      id: thread_id,
      project_id: projectId,
      title: '',
      llm_model: llmModel,
      created_at: '',
      updated_at: '',
    }
    await syncThread()
    await listThreads(projectId)
    currentThread.value =
      threads.value.find((t) => t.id === threadId.value) || currentThread.value
    connect()
    return thread_id
  }

  async function syncThread(): Promise<void> {
    if (!threadId.value) return
    const state = await api.getThread(threadId.value)
    applyState(state)
  }

  async function listThreads(projectId: string): Promise<void> {
    const data = await api.listThreads(projectId)
    threads.value = data.threads ?? []
  }

  async function loadThread(
    threadIdToLoad: string,
    apiKey: string,
    llmModel: string
  ): Promise<void> {
    resetInternalState()
    const state = await api.resumeThread(threadIdToLoad, {
      api_key: apiKey,
      llm_model: llmModel,
    })
    threadId.value = state.thread_id
    currentThread.value =
      threads.value.find((t) => t.id === threadIdToLoad) || {
        id: threadIdToLoad,
        project_id: '',
        title: '',
        llm_model: llmModel,
        created_at: '',
        updated_at: '',
      }
    applyState(state)
    connect()
  }

  async function createThread(
    projectId: string,
    apiKey: string,
    llmModel: string
  ): Promise<string> {
    resetInternalState()
    const { thread_id } = await api.createThread(projectId, {
      api_key: apiKey,
      llm_model: llmModel,
    })
    threadId.value = thread_id
    currentThread.value = {
      id: thread_id,
      project_id: projectId,
      title: '',
      llm_model: llmModel,
      created_at: '',
      updated_at: '',
    }
    await listThreads(projectId)
    currentThread.value =
      threads.value.find((t) => t.id === threadId.value) || currentThread.value
    connect()
    return thread_id
  }

  async function deleteThread(
    threadIdToDelete: string,
    projectId: string
  ): Promise<void> {
    await api.deleteThread(threadIdToDelete)
    if (currentThread.value?.id === threadIdToDelete) {
      resetInternalState()
    }
    await listThreads(projectId)
  }

  async function renameThread(
    threadIdToRename: string,
    title: string,
    projectId: string
  ): Promise<void> {
    await api.renameThread(threadIdToRename, title)
    await listThreads(projectId)
    if (currentThread.value?.id === threadIdToRename) {
      currentThread.value =
        threads.value.find((t) => t.id === threadIdToRename) || currentThread.value
    }
  }

  function connect(): void {
    if (!threadId.value || es) return
    es = api.connectAgentEvents(threadId.value, {
      onState: (state) => applyState(state),
      onEnd: () => {
        // 本轮流式运行结束（正常完成或在中断处暂停）。
        busy.value = false
        radiomicsProgress.value = null
      },
      onError: () => {
        disconnect()
      },
    })
  }

  async function sendMessage(content: string, role = 'user'): Promise<void> {
    if (!threadId.value) {
      throw new Error('No active agent thread')
    }
    busy.value = true
    messages.value.push({ role, content })
    try {
      await api.sendMessage(threadId.value, role, content)
    } catch (err) {
      // 后端拒绝（如 409 忙碌/待确认）：回滚乐观追加的消息。
      messages.value.pop()
      busy.value = false
      throw err
    }
    connect()
  }

  async function updatePlan(plan: PendingPlan): Promise<void> {
    if (!threadId.value) {
      throw new Error('No active agent thread')
    }
    const state = await api.updatePlan(threadId.value, plan)
    applyState(state)
  }

  async function confirm(): Promise<void> {
    if (!threadId.value) {
      throw new Error('No active agent thread')
    }
    busy.value = true
    try {
      await api.confirm(threadId.value)
    } catch (err) {
      busy.value = false
      throw err
    }
    connect()
  }

  async function cancel(): Promise<void> {
    if (!threadId.value) {
      throw new Error('No active agent thread')
    }
    busy.value = true
    try {
      await api.cancel(threadId.value)
    } catch (err) {
      busy.value = false
      throw err
    }
    connect()
  }

  async function stop(): Promise<void> {
    if (!threadId.value) {
      throw new Error('No active agent thread')
    }
    try {
      await api.stopAgent(threadId.value)
    } finally {
      // 无论成功与否都复位忙碌；失败原因由 axios 拦截器 toast，
      // 若后端仍在运行，后续发送会被 409 兜底，状态自愈。
      busy.value = false
      radiomicsProgress.value = null
    }
  }

  function disconnect(): void {
    if (es) {
      es.close()
      es = null
    }
  }

  async function reconnect(): Promise<void> {
    await syncThread()
    connect()
  }

  function resetThread(): void {
    resetInternalState()
    threads.value = []
  }

  return {
    threadId,
    messages,
    interrupt,
    operationLog,
    pendingPlan,
    pendingCommand,
    pendingScript,
    pendingRadiomicsPlan,
    pendingRadiomicsExecution,
    pendingRadiomicsAnalysis,
    radiomicsProgress,
    threads,
    currentThread,
    busy,
    ensureThread,
    reconnect,
    sendMessage,
    updatePlan,
    confirm,
    cancel,
    stop,
    disconnect,
    resetThread,
    listThreads,
    loadThread,
    createThread,
    deleteThread,
    renameThread,
  }
})
