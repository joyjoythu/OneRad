const pad = (n: number): string => String(n).padStart(2, '0')

/**
 * 消息/会话时间格式化：UTC ISO 转本地时间。
 * 当天的消息显示 HH:MM，更早的显示 MM-DD HH:MM；无效输入返回空串。
 */
export function formatMessageTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  return sameDay ? hm : `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hm}`
}
