import client from './client'
import { API_BASE } from './client'

export interface ToolCall {
  id?: string
  name?: string
  args?: Record<string, unknown>
}

export interface AgentMessage {
  role: string
  content: string
  timestamp?: string
  tool_calls?: ToolCall[]
  tool_call_id?: string
  reasoning_content?: string
}

export interface ContextUsage {
  input_tokens: number
  output_tokens: number
  total_tokens: number
}

export interface PlanItem {
  action: string
  source?: string
  target?: string
  reason?: string
}

export interface PendingPlan {
  tool_call_id: string
  plan: PlanItem[]
}

export interface PendingCommand {
  tool_call_id: string
  _pending_tool: string
  args: Record<string, unknown>
}

export interface PendingScript {
  tool_call_id: string
  code: string
  risk_level: 'low' | 'medium' | 'high'
  description: string
}

export interface RadiomicsProgress {
  stage: 'start' | 'extracting' | 'finalizing' | string
  current: number
  total: number
  patient_id?: string
}

export interface ThinkingState {
  text: string
  done: boolean
}

export interface PendingSubagent {
  tool_call_id: string
  tasks: string[]
}

export interface SubagentEntry {
  role: string
  text: string
}

/** 单个子 agent 的运行状态（运行中经 SSE 滚动推送，结束时定格）。
 * id 为派生的子线程 id，并行分派时用于区分多个子任务。
 * tool_call_id 为发起 dispatch_subagent 的工具调用 id，前端据此把面板
 * 锚定回对应 assistant 消息；缺失时面板兜底渲染在消息列表末尾。 */
export interface SubagentStatus {
  id: string
  task: string
  status: 'running' | 'done' | 'failed' | 'cancelled'
  entries: SubagentEntry[]
  tool_call_id?: string | null
}

export interface RadiomicsPair {
  patient_id: string
  sequence?: string
  image_path?: string
  mask_path?: string
  candidates?: string[]
}

export interface PendingRadiomicsPlan {
  tool_call_id: string
  _pending_tool?: string
  success?: boolean
  images_found?: number
  masks_found?: number
  pairs?: {
    high?: RadiomicsPair[]
    medium?: RadiomicsPair[]
    low?: RadiomicsPair[]
  }
  unmatched_images?: string[]
  unmatched_masks?: string[]
}

export interface PendingRadiomicsExecution {
  tool_call_id: string
  pairs: RadiomicsPair[]
  n_cases: number
  yaml_path: string
  output_dir: string
  expected_outputs?: string[]
}

export interface PendingRadiomicsAnalysis {
  tool_call_id: string
  feature_csv: string
  clinical: string
  id_col: string
  label_col: string
  covariates: string[]
  output_dir: string
  n_feature_cases: number
  n_features: number
  n_matched: number
  // 分析超参；旧会话快照可能缺失，展示时回退默认值
  n_splits?: number
  max_lasso_features?: number
  random_state?: number
  available_clinical_columns: string[]
}

export interface PendingFeatureStatistics {
  tool_call_id: string
  feature_csv: string
  clinical: string
  id_col: string
  label_col: string
  selected_features_csv: string
  selected_features: string[]
  output_dir: string
  n_feature_cases: number
  n_matched: number
  n_selected: number
}

export interface PendingChoice {
  tool_call_id: string
  question: string
  options: string[]
}

export interface TodoItem {
  content: string
  // cancelled：步骤进行中被用户停止，由 /stop 定格，面板显示黄色标识
  status: 'pending' | 'in_progress' | 'completed' | 'cancelled'
}

export interface OperationLogEntry {
  time?: string
  text: string
}

export interface AgentState {
  thread_id?: string
  messages: AgentMessage[]
  interrupt_type: string | null
  // 旧会话中的条目为纯字符串，新条目为 {time, text}。
  operation_log: (string | OperationLogEntry)[]
  todos?: TodoItem[]
  pending_plan: PendingPlan | null
  pending_command: PendingCommand | null
  pending_script: PendingScript | null
  pending_radiomics_plan?: PendingRadiomicsPlan | null
  pending_radiomics_execution?: PendingRadiomicsExecution | null
  pending_radiomics_analysis?: PendingRadiomicsAnalysis | null
  pending_feature_statistics?: PendingFeatureStatistics | null
  pending_subagent?: PendingSubagent | null
  pending_choice?: PendingChoice | null
  subagent?: SubagentStatus | null
  radiomics_progress?: RadiomicsProgress | null
  thinking?: ThinkingState | null
  context_usage?: ContextUsage | null
  context_window?: number
  running?: boolean
  error?: string
}

export interface CreateThreadRequest {
  auto_approve: boolean
}

export interface CreateThreadResponse {
  thread_id: string
}

export interface MessageRequest {
  role: string
  content: string
  model?: string
}

export interface UpdatePlanRequest {
  plan: PendingPlan
}

export interface ThreadSummary {
  id: string
  project_id: string
  title: string
  created_at: string
  updated_at: string
  /** 该线程当前是否有正在运行的流式任务（后端内存态）。 */
  running?: boolean
}

export interface LoadThreadRequest {
  auto_approve: boolean
}

export interface AgentEventCallbacks {
  onState?: (state: AgentState) => void
  onEnd?: () => void
  onError?: (error: Record<string, unknown>) => void
}

export const createThread = async (
  projectId: string,
  payload: CreateThreadRequest
): Promise<CreateThreadResponse> => {
  const res = await client.post('/agent/threads', payload, {
    params: { project_id: projectId },
  })
  return res.data
}

export const getThread = async (
  threadId: string
): Promise<AgentState & { thread_id: string }> => {
  const res = await client.get(`/agent/threads/${encodeURIComponent(threadId)}`)
  return res.data
}

export const sendMessage = async (
  threadId: string,
  role: string,
  content: string,
  model?: string
): Promise<{ thread_id: string }> => {
  const payload: MessageRequest = { role, content }
  if (model) payload.model = model
  const res = await client.post(
    `/agent/threads/${encodeURIComponent(threadId)}/messages`,
    payload
  )
  return res.data
}

export const updatePlan = async (
  threadId: string,
  plan: PendingPlan
): Promise<AgentState> => {
  const payload: UpdatePlanRequest = { plan }
  const res = await client.put(
    `/agent/threads/${encodeURIComponent(threadId)}/plan`,
    payload
  )
  return res.data
}

export const confirm = async (threadId: string): Promise<{ thread_id: string }> => {
  const res = await client.post(`/agent/threads/${encodeURIComponent(threadId)}/confirm`)
  return res.data
}

export const cancel = async (threadId: string): Promise<{ thread_id: string }> => {
  const res = await client.post(`/agent/threads/${encodeURIComponent(threadId)}/cancel`)
  return res.data
}

export const other = async (
  threadId: string,
  instruction: string
): Promise<{ thread_id: string }> => {
  const res = await client.post(
    `/agent/threads/${encodeURIComponent(threadId)}/other`,
    { instruction }
  )
  return res.data
}

export const answer = async (
  threadId: string,
  answerText: string
): Promise<{ thread_id: string }> => {
  const res = await client.post(
    `/agent/threads/${encodeURIComponent(threadId)}/answer`,
    { answer: answerText }
  )
  return res.data
}

export const exportConversation = async (
  threadId: string,
  format: 'md' | 'docx'
): Promise<{ path: string; format: string }> => {
  const res = await client.post(
    `/agent/threads/${encodeURIComponent(threadId)}/export`,
    { format }
  )
  return res.data
}

export const setAutoApprove = async (
  threadId: string,
  enabled: boolean
): Promise<{ auto_approve: boolean }> => {
  const res = await client.put(
    `/agent/threads/${encodeURIComponent(threadId)}/auto-approve`,
    { enabled }
  )
  return res.data
}

export const stopAgent = async (
  threadId: string
): Promise<{ thread_id: string; status: string }> => {
  const res = await client.post(
    `/agent/threads/${encodeURIComponent(threadId)}/stop`
  )
  return res.data
}

export const listThreads = async (
  projectId: string
): Promise<{ threads: ThreadSummary[] }> => {
  const res = await client.get('/agent/threads', {
    params: { project_id: projectId },
  })
  return res.data
}

export const deleteThread = async (threadId: string): Promise<void> => {
  await client.delete(`/agent/threads/${encodeURIComponent(threadId)}`)
}

export const renameThread = async (
  threadId: string,
  title: string
): Promise<{ thread: ThreadSummary }> => {
  const res = await client.patch(
    `/agent/threads/${encodeURIComponent(threadId)}`,
    { title }
  )
  return res.data
}

export const resumeThread = async (
  threadId: string,
  payload: LoadThreadRequest
): Promise<AgentState & { thread_id: string }> => {
  const res = await client.post(
    `/agent/threads/${encodeURIComponent(threadId)}/resume`,
    payload
  )
  return res.data
}

export const connectAgentEvents = (
  threadId: string,
  callbacks: AgentEventCallbacks = {}
): EventSource => {
  const es = new EventSource(
    `${API_BASE}/agent/threads/${encodeURIComponent(threadId)}/events`
  )

  es.addEventListener('agent', (event: MessageEvent) => {
    try {
      const data = JSON.parse(event.data) as AgentState
      callbacks.onState?.(data)
    } catch (err) {
      console.error('Failed to parse agent SSE payload', err)
    }
  })

  es.addEventListener('agent_end', () => {
    callbacks.onEnd?.()
  })

  // Keep the connection open on transient errors; the browser will reconnect
  // automatically per the EventSource spec. close() is only called from the
  // consumer when the stream is truly finished.
  es.onerror = () => {
    callbacks.onError?.({ message: 'EventSource error' })
  }

  return es
}
