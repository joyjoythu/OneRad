export type ToolMessageFormat = 'markdown' | 'plain'

export interface ToolMessageDisplay {
  text: string
  format: ToolMessageFormat
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const FIELD_LABELS: Record<string, string> = {
  result: '结果',
  message: '说明',
  status: '状态',
  path: '路径',
  stdout: '标准输出',
  stderr: '错误输出',
  returncode: '返回码',
  count: '数量',
  created: '已创建',
  modified: '已修改',
  deleted: '已删除',
  skipped: '已跳过',
}

const TOOL_ARRAY_SUMMARIES: Record<string, (count: number) => string> = {
  find_files: (count) => `找到 **${count}** 个文件或目录：`,
  list_directory: (count) => `目录中共有 **${count}** 项：`,
}

function fieldLabel(key: string): string {
  return FIELD_LABELS[key] ?? key.replace(/_/g, ' ')
}

function inlineCode(value: string): string {
  const compact = value.replace(/\r?\n/g, ' ')
  const longestTickRun = Math.max(
    0,
    ...Array.from(compact.matchAll(/`+/g), (match) => match[0].length)
  )
  const fence = '`'.repeat(longestTickRun + 1)
  const padding = compact.startsWith('`') || compact.endsWith('`') ? ' ' : ''
  return `${fence}${padding}${compact}${padding}${fence}`
}

function scalarText(value: unknown): string {
  if (value === null) return '无'
  if (typeof value === 'boolean') return value ? '是' : '否'
  return String(value)
}

function formatArray(items: unknown[]): string {
  if (items.length === 0) return '未找到结果。'

  return items
    .map((item) => {
      if (isRecord(item)) {
        const summary = Object.entries(item)
          .map(([key, value]) => `${fieldLabel(key)}：${scalarText(value)}`)
          .join('；')
        return `- ${summary}`
      }
      if (Array.isArray(item)) {
        return `- ${inlineCode(item.map(scalarText).join('，'))}`
      }
      return `- ${inlineCode(scalarText(item))}`
    })
    .join('\n')
}

function formatRecord(record: Record<string, unknown>): string {
  const entries = Object.entries(record).filter(
    ([key, value]) => key !== 'tool' && !(key === 'success' && value === true)
  )
  if (entries.length === 0) return '操作已完成。'

  return entries
    .map(([key, value]) => {
      const label = fieldLabel(key)
      if (Array.isArray(value)) {
        return `**${label}**（${value.length} 项）：\n\n${formatArray(value)}`
      }
      if (isRecord(value)) {
        const details = Object.entries(value)
          .map(
            ([childKey, childValue]) =>
              `- **${fieldLabel(childKey)}**：${scalarText(childValue)}`
          )
          .join('\n')
        return `**${label}**：\n\n${details || '无'}`
      }
      return `**${label}**：${scalarText(value)}`
    })
    .join('\n\n')
}

function parsedDisplay(value: unknown, depth = 0): ToolMessageDisplay {
  if (typeof value === 'string') {
    if (depth < 2) {
      try {
        return parsedDisplay(JSON.parse(value), depth + 1)
      } catch {
        // It is ordinary prose or Markdown, not another serialized payload.
      }
    }
    return { text: value, format: 'markdown' }
  }

  if (Array.isArray(value)) {
    return { text: formatArray(value), format: 'markdown' }
  }

  if (isRecord(value)) {
    if (typeof value.result === 'string') {
      return parsedDisplay(value.result, depth + 1)
    }
    if (typeof value.error === 'string') {
      return { text: value.error, format: 'plain' }
    }
    if (value.cancelled === true && typeof value.reason === 'string') {
      return { text: value.reason, format: 'plain' }
    }
    if (Array.isArray(value.result)) {
      const toolName = typeof value.tool === 'string' ? value.tool : ''
      const summary =
        TOOL_ARRAY_SUMMARIES[toolName]?.(value.result.length) ??
        `共 **${value.result.length}** 项：`
      return {
        text: `${summary}\n\n${formatArray(value.result)}`,
        format: 'markdown',
      }
    }
    return { text: formatRecord(value), format: 'markdown' }
  }

  return {
    text: scalarText(value),
    format: 'plain',
  }
}

/**
 * Convert a serialized tool payload into user-facing content.
 *
 * Textual `result` values are rendered as Markdown. Arrays and objects are
 * converted to readable summaries so implementation-oriented JSON wrappers do
 * not leak into the conversation. Invalid JSON is kept as plain text.
 */
export function formatToolMessage(content: string): ToolMessageDisplay {
  const trimmed = content.trim()
  if (!trimmed) return { text: '', format: 'plain' }

  try {
    return parsedDisplay(JSON.parse(trimmed))
  } catch {
    return { text: content, format: 'plain' }
  }
}
