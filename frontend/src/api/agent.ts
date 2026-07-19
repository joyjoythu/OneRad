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
  available_clinical_columns: string[]
}

export interface AgentState {
  thread_id?: string
  messages: AgentMessage[]
  interrupt_type: string | null
  operation_log: string[]
  pending_plan: PendingPlan | null
  pending_command: PendingCommand | null
  pending_script: PendingScript | null
  pending_radiomics_plan?: PendingRadiomicsPlan | null
  pending_radiomics_execution?: PendingRadiomicsExecution | null
  pending_radiomics_analysis?: PendingRadiomicsAnalysis | null
  radiomics_progress?: RadiomicsProgress | null
  thinking?: ThinkingState | null
  context_usage?: ContextUsage | null
  context_window?: number
  running?: boolean
  error?: string
}

export interface CreateThreadRequest {
  api_key: string
  auto_approve: boolean
}

export interface CreateThreadResponse {
  thread_id: string
}

export interface MessageRequest {
  role: string
  content: string
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
  api_key: string
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
  content: string
): Promise<{ thread_id: string }> => {
  const payload: MessageRequest = { role, content }
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
