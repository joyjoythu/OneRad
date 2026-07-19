import MarkdownIt from 'markdown-it'
import type { RenderRule } from 'markdown-it/lib/renderer.mjs'

// 安全基线：html:false 转义模型输出中的原始 HTML（防注入），
// linkify 只放行 http/https/mailto 等安全协议的裸链接。
const md: MarkdownIt = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true, // 单个换行渲染为 <br>，保持聊天式排版
})

// 链接一律新窗口打开，避免跳出当前会话。
const defaultLinkOpen: RenderRule =
  md.renderer.rules.link_open ??
  ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options))

md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx].attrSet('target', '_blank')
  tokens[idx].attrSet('rel', 'noopener noreferrer')
  return defaultLinkOpen(tokens, idx, options, env, self)
}

/** 把 Markdown 文本渲染为 HTML 字符串（供 v-html 使用）。 */
export function renderMarkdown(text: string): string {
  return md.render(text)
}
