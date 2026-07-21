import { ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import * as api from '@/api/agent'
import type {
  AgentState,
  AgentMessage,
  ContextUsage,
  PendingPlan,
  PendingCommand,
  PendingScript,
  PendingRadiomicsPlan,
  PendingRadiomicsExecution,
  PendingRadiomicsAnalysis,
  PendingFeatureStatistics,
  PendingSubagent,
  SubagentStatus,
  RadiomicsProgress,
  ThinkingState,
  ThreadSummary,
} from '@/api/agent'

export const AUTO_APPROVE_STORAGE_KEY = 'onerad:agent:autoApprove'
export const MODEL_STORAGE_KEY = 'onerad:agent:model'
export const DEFAULT_MODEL = 'deepseek-v4-flash'
export const AVAILABLE_MODELS = ['deepseek-v4-flash', 'deepseek-v4-pro'] as const

function loadAutoApprovePreference(): boolean {
  try {
    return localStorage.getItem(AUTO_APPROVE_STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

function saveAutoApprovePreference(enabled: boolean): void {
  try {
    localStorage.setItem(AUTO_APPROVE_STORAGE_KEY, String(enabled))
  } catch {
    // 浏览器禁用本地存储时仍允许当前会话切换该选项。
  }
}

function loadModelPreference(): string {
  try {
    const saved = localStorage.getItem(MODEL_STORAGE_KEY)
    if (saved && (AVAILABLE_MODELS as readonly string[]).includes(saved)) return saved
  } catch {
    // 浏览器禁用本地存储时使用默认模型。
  }
  return DEFAULT_MODEL
}

function saveModelPreference(model: string): void {
  try {
    localStorage.setItem(MODEL_STORAGE_KEY, model)
  } catch {
    // 浏览器禁用本地存储时仍允许当前会话切换模型。
  }
}

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
  const pendingFeatureStatistics = ref<PendingFeatureStatistics | null>(null)
  const pendingSubagent = ref<PendingSubagent | null>(null)
  // 各子 agent 的运行状态（key 为派生子线程 id）：运行中经 SSE 滚动推送
  // （含中间过程条目）。终态只用于说明父 agent 当前所处的内部阶段；
  // 父流程结束或新一轮开始时清空，避免它看起来像一条独立的最终回复。
  // 并行分派时会有多个。
  const subagentStatuses = ref<Record<string, SubagentStatus>>({})

  const threads = ref<ThreadSummary[]>([])
  // 按项目分组的对话列表缓存，供合并侧边栏懒加载展示；
  // listThreads 会同步对应项目的缓存，保证增删改后一致。
  const threadsByProject = ref<Record<string, ThreadSummary[]>>({})
  // 扁平 threads 列表所属的项目 id；只有该项目的列表才允许覆盖 threads。
  const threadsProjectId = ref<string | null>(null)
  // 期望打开的对话 id：跨项目点击对话时由侧边栏设置，
  // AgentView 的项目切换 watcher 消费后完成加载（保证只加载一次）。
  const preferredThreadId = ref<string | null>(null)
  const currentThread = ref<ThreadSummary | null>(null)
  // 智能体是否正在处理中（流式运行期间为 true），用于禁用输入并展示状态。
  const busy = ref(false)
  // 正在运行的对话 id 集合：侧边栏据此显示转圈。来源：本地发起运行时即时
  // 标记 + 对话列表响应里的 running 标志（后端内存态，轮询收敛）。
  const runningThreadIds = ref<Set<string>>(new Set())
  // 运行已结束但用户尚未点进去看的对话 id 集合：侧边栏据此显示提示点，
  // 点进对话（loadThread）即清除。内存态，刷新即清。
  const finishedThreadIds = ref<Set<string>>(new Set())
  // 自动审批：应用初始化时恢复上次选择；创建或恢复线程时同步给后端。
  const autoApprove = ref(loadAutoApprovePreference())
  // 本次会话使用的 LLM 模型：恢复上次选择，发送消息时随请求带给后端。
  const selectedModel = ref(loadModelPreference())
  // 自动审批同步请求进行中：用于禁用开关，防止快速连点导致前后端状态乱序。
  const autoApproveSyncing = ref(false)
  // 影像组学特征提取的实时进度（由后端节点线程推送，null 表示无提取在进行）。
  const radiomicsProgress = ref<RadiomicsProgress | null>(null)
  // 当前轮 LLM 的流式思考内容（推理模型的 reasoning_content；null 表示无）。
  // 独立于 messages：快照会整体替换 messages，流式文本必须走独立 ref。
  const currentThinking = ref<ThinkingState | null>(null)
  // 最近一次 LLM 调用的 token 用量与模型上下文窗口（null 表示尚无数据）。
  const contextUsage = ref<ContextUsage | null>(null)
  const contextWindow = ref<number | null>(null)

  let es: EventSource | null = null

  const RUNNING_POLL_INTERVAL_MS = 3000
  let runningPollTimer: ReturnType<typeof setInterval> | null = null

  /** 仅在有对话运行时轮询其所在项目的列表，让运行状态随响应收敛。 */
  function updateRunningPolling(): void {
    if (runningThreadIds.value.size > 0 && runningPollTimer === null) {
      runningPollTimer = setInterval(() => {
        void pollRunningProjects()
      }, RUNNING_POLL_INTERVAL_MS)
    } else if (runningThreadIds.value.size === 0 && runningPollTimer !== null) {
      clearInterval(runningPollTimer)
      runningPollTimer = null
    }
  }

  function stopRunningPolling(): void {
    if (runningPollTimer !== null) {
      clearInterval(runningPollTimer)
      runningPollTimer = null
    }
  }

  async function pollRunningProjects(): Promise<void> {
    // 只刷新「缓存中且含运行中对话」的项目；运行中对话必然已被标记，
    // 其项目未缓存时等用户展开该项目后再由首次加载带上 running 标志。
    const projectIds = new Set<string>()
    for (const [pid, list] of Object.entries(threadsByProject.value)) {
      if (list.some((t) => runningThreadIds.value.has(t.id))) {
        projectIds.add(pid)
      }
    }
    for (const pid of projectIds) {
      try {
        if (pid === threadsProjectId.value) {
          await listThreads(pid)
        } else {
          await loadProjectThreads(pid)
        }
      } catch {
        // 轮询失败（如后端不可达）：停掉轮询避免反复打扰，
        // 下次用户操作触发的列表拉取会经 updateRunningPolling 重启。
        stopRunningPolling()
        return
      }
    }
  }

  /** 把列表响应里的 running 标志合并进 runningThreadIds/finishedThreadIds。 */
  function syncRunningFromList(list: ThreadSummary[]): void {
    for (const t of list) {
      const wasRunning = runningThreadIds.value.has(t.id)
      if (t.running) {
        runningThreadIds.value.add(t.id)
      } else if (wasRunning) {
        runningThreadIds.value.delete(t.id)
        // 刚结束的对话：用户正看着当前线程则不加提示点。
        if (t.id !== threadId.value) {
          finishedThreadIds.value.add(t.id)
        }
      }
    }
    updateRunningPolling()
  }

  function applyState(state: Partial<AgentState>): void {
    if (state.error) {
      // 流式运行出错：保留现有消息，仅提示错误并解除忙碌。
      busy.value = false
      currentThinking.value = null
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
    if (state.pending_feature_statistics !== undefined) {
      pendingFeatureStatistics.value = state.pending_feature_statistics
    }
    if (state.pending_subagent !== undefined) {
      pendingSubagent.value = state.pending_subagent
    }
    if (state.subagent) {
      // 并行分派时各子 agent 独立推送，按 id 归组；条目列表每次全量滚动替换。
      subagentStatuses.value = {
        ...subagentStatuses.value,
        [state.subagent.id]: state.subagent,
      }
    }
    if (state.radiomics_progress !== undefined) {
      radiomicsProgress.value = state.radiomics_progress
    }
    if (state.thinking !== undefined) {
      currentThinking.value = state.thinking
    }
    if (state.context_usage !== undefined) {
      contextUsage.value = state.context_usage
    }
    if (state.context_window !== undefined) {
      contextWindow.value = state.context_window
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
    pendingFeatureStatistics.value = null
    pendingSubagent.value = null
    subagentStatuses.value = {}
    currentThread.value = null
    busy.value = false
    radiomicsProgress.value = null
    currentThinking.value = null
    contextUsage.value = null
    contextWindow.value = null
  }

  /** 新一轮父流程开始时清除上一轮残留的子任务阶段。 */
  function clearSubagentStatus(): void {
    subagentStatuses.value = {}
  }

  async function ensureThread(projectId: string): Promise<string> {
    if (threadId.value) {
      if (!currentThread.value) {
        currentThread.value =
          threads.value.find((t) => t.id === threadId.value) || {
            id: threadId.value,
            project_id: projectId,
            title: '',
            created_at: '',
            updated_at: '',
          }
      }
      return threadId.value
    }
    const { thread_id } = await api.createThread(projectId, {
      auto_approve: autoApprove.value,
    })
    threadId.value = thread_id
    currentThread.value = {
      id: thread_id,
      project_id: projectId,
      title: '',
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
    threadsByProject.value[projectId] = threads.value
    threadsProjectId.value = projectId
    syncRunningFromList(threads.value)
  }

  async function loadProjectThreads(projectId: string): Promise<void> {
    const data = await api.listThreads(projectId)
    threadsByProject.value[projectId] = data.threads ?? []
    syncRunningFromList(threadsByProject.value[projectId])
  }

  function clearProjectThreads(projectId: string): void {
    delete threadsByProject.value[projectId]
  }

  async function loadThread(threadIdToLoad: string): Promise<void> {
    resetInternalState()
    // 点进对话即视为已读：清除完成提示点。
    finishedThreadIds.value.delete(threadIdToLoad)
    const state = await api.resumeThread(threadIdToLoad, {
      auto_approve: autoApprove.value,
    })
    threadId.value = state.thread_id
    currentThread.value =
      threads.value.find((t) => t.id === threadIdToLoad) ||
      Object.values(threadsByProject.value)
        .flat()
        .find((t) => t.id === threadIdToLoad) || {
        id: threadIdToLoad,
        project_id: '',
        title: '',
        created_at: '',
        updated_at: '',
      }
    applyState(state)
    connect()
  }

  async function createThread(projectId: string): Promise<string> {
    resetInternalState()
    const { thread_id } = await api.createThread(projectId, {
      auto_approve: autoApprove.value,
    })
    threadId.value = thread_id
    currentThread.value = {
      id: thread_id,
      project_id: projectId,
      title: '',
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
    runningThreadIds.value.delete(threadIdToDelete)
    finishedThreadIds.value.delete(threadIdToDelete)
    updateRunningPolling()
    if (currentThread.value?.id === threadIdToDelete) {
      resetInternalState()
    }
    if (projectId === threadsProjectId.value) {
      await listThreads(projectId)
    } else {
      await loadProjectThreads(projectId)
    }
  }

  async function renameThread(
    threadIdToRename: string,
    title: string,
    projectId: string
  ): Promise<void> {
    await api.renameThread(threadIdToRename, title)
    if (projectId === threadsProjectId.value) {
      await listThreads(projectId)
    } else {
      await loadProjectThreads(projectId)
    }
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
        // 子任务阶段面板在结束后保留（定格在终态），下一轮运行开始时
        // 才由 clearSubagentStatus 清除。
        radiomicsProgress.value = null
        currentThinking.value = null
        // 当前线程的结束由用户实时看着，转入完成提示点集合无意义。
        if (threadId.value) {
          runningThreadIds.value.delete(threadId.value)
          updateRunningPolling()
        }
        // SSE 只推订阅后的新事件；订阅空窗内漏掉的事件没有回放兜底，
        // 流结束时同步一次最终状态保证收敛。
        void syncThread()
        // 首轮对话后后端会生成摘要标题，刷新列表让侧边栏及时显示；
        // 非当前项目只刷缓存，避免污染扁平列表。
        const pid = currentThread.value?.project_id
        if (pid) {
          if (pid === threadsProjectId.value) {
            void listThreads(pid)
          } else {
            void loadProjectThreads(pid)
          }
        }
      },
      onError: () => {
        // 断连后陈旧 thinking 无快照兜底纠正，直接清空；重连后由新一轮重置事件重建。
        currentThinking.value = null
        disconnect()
      },
    })
  }

  async function sendMessage(content: string, role = 'user'): Promise<void> {
    if (!threadId.value) {
      throw new Error('No active agent thread')
    }
    clearSubagentStatus()
    busy.value = true
    messages.value.push({ role, content })
    // 先订阅再发起运行，避免漏掉运行初期发布的事件。
    connect()
    try {
      await api.sendMessage(threadId.value, role, content, selectedModel.value)
      // 发起成功即标记运行中：侧边栏转圈即时出现，不等待下次列表拉取。
      runningThreadIds.value.add(threadId.value)
      updateRunningPolling()
    } catch (err) {
      // 后端拒绝（如 409 忙碌/待确认）：回滚乐观追加的消息。
      messages.value.pop()
      busy.value = false
      throw err
    }
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
    clearSubagentStatus()
    busy.value = true
    connect()
    try {
      await api.confirm(threadId.value)
      runningThreadIds.value.add(threadId.value)
      updateRunningPolling()
    } catch (err) {
      busy.value = false
      throw err
    }
  }

  async function cancel(): Promise<void> {
    if (!threadId.value) {
      throw new Error('No active agent thread')
    }
    clearSubagentStatus()
    busy.value = true
    connect()
    try {
      await api.cancel(threadId.value)
      runningThreadIds.value.add(threadId.value)
      updateRunningPolling()
    } catch (err) {
      busy.value = false
      throw err
    }
  }

  async function other(instruction: string): Promise<void> {
    if (!threadId.value) {
      throw new Error('No active agent thread')
    }
    clearSubagentStatus()
    busy.value = true
    connect()
    try {
      await api.other(threadId.value, instruction)
      runningThreadIds.value.add(threadId.value)
      updateRunningPolling()
    } catch (err) {
      busy.value = false
      throw err
    }
  }

  async function setAutoApprove(enabled: boolean): Promise<void> {
    const previous = autoApprove.value
    autoApprove.value = enabled
    saveAutoApprovePreference(enabled)
    if (!threadId.value) return
    autoApproveSyncing.value = true
    try {
      await api.setAutoApprove(threadId.value, enabled)
    } catch (err) {
      // 回滚乐观更新；错误提示由 axios 拦截器统一 toast。
      autoApprove.value = previous
      saveAutoApprovePreference(previous)
      throw err
    } finally {
      autoApproveSyncing.value = false
    }
  }

  function setModel(model: string): void {
    if (!(AVAILABLE_MODELS as readonly string[]).includes(model)) return
    selectedModel.value = model
    saveModelPreference(model)
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
      // 子任务面板保留并定格：仍在“运行中”的按已停止处理。
      subagentStatuses.value = Object.fromEntries(
        Object.entries(subagentStatuses.value).map(([id, s]) => [
          id,
          s.status === 'running' ? { ...s, status: 'cancelled' as const } : s,
        ])
      )
      radiomicsProgress.value = null
      currentThinking.value = null
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
    threadsProjectId.value = null
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
    pendingFeatureStatistics,
    pendingSubagent,
    subagentStatuses,
    radiomicsProgress,
    currentThinking,
    contextUsage,
    contextWindow,
    threads,
    threadsByProject,
    threadsProjectId,
    preferredThreadId,
    currentThread,
    busy,
    runningThreadIds,
    finishedThreadIds,
    autoApprove,
    autoApproveSyncing,
    selectedModel,
    ensureThread,
    reconnect,
    sendMessage,
    updatePlan,
    confirm,
    cancel,
    other,
    setAutoApprove,
    setModel,
    stop,
    disconnect,
    resetThread,
    listThreads,
    loadProjectThreads,
    clearProjectThreads,
    loadThread,
    createThread,
    deleteThread,
    renameThread,
  }
})
