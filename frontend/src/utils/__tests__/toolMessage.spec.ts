import { describe, expect, it } from 'vitest'
import { formatToolMessage } from '../toolMessage'

describe('formatToolMessage', () => {
  it('decodes escaped Unicode and extracts a Markdown result', () => {
    const display = formatToolMessage(
      '{"success":true,"result":"\\u4ee5\\u4e0b\\u662f\\u62a5\\u544a\\n\\n## \\u9879\\u76ee\\u76ee\\u5f55"}'
    )

    expect(display).toEqual({
      text: '以下是报告\n\n## 项目目录',
      format: 'markdown',
    })
  })

  it('formats structured payloads as readable fields instead of JSON', () => {
    const display = formatToolMessage('{"stdout":"ok","returncode":0}')

    expect(display).toEqual({
      text: '**标准输出**：ok\n\n**返回码**：0',
      format: 'markdown',
    })
    expect(display.text).not.toContain('{')
  })

  it('formats find_files results as a counted path list', () => {
    const display = formatToolMessage(
      JSON.stringify({
        tool: 'find_files',
        result: ['project.yaml', 'outputs\\radiomics_report.docx'],
      })
    )

    expect(display).toEqual({
      text:
        '找到 **2** 个文件或目录：\n\n- `project.yaml`\n- `outputs\\radiomics_report.docx`',
      format: 'markdown',
    })
    expect(display.text).not.toContain('"tool"')
  })

  it('uses an error message instead of exposing its JSON wrapper', () => {
    expect(formatToolMessage('{"success":false,"error":"执行失败"}')).toEqual({
      text: '执行失败',
      format: 'plain',
    })
  })

  it('keeps non-JSON content unchanged', () => {
    expect(formatToolMessage('plain output')).toEqual({
      text: 'plain output',
      format: 'plain',
    })
  })
})
