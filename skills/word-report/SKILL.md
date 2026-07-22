---
name: word-report
description: Word 文档的中文学术论文格式规范，以及 word_create / word_append / reformat_report 三个工具的使用指引。
---

# Word 报告格式规范与工具

## 格式规范（所有 Word 产出统一遵守）

- 正文：中文宋体、西文/数字 Times New Roman、小四（12pt）、黑色、1.5 倍行距。
- 标题（Title）：黑体三号（16pt）、加粗、居中。
- 一级标题（Heading 1）：黑体四号（14pt）、加粗、黑色（不用 Word 默认蓝色）。
- 二级标题（Heading 2）：黑体小四（12pt）、加粗。
- 表格：五号（10.5pt）；表头加粗、居中。
- 图片：段落居中。

## 工具使用指引

- `word_create(filename, content_markdown)`：在项目目录下新建 docx 并自动套用上述
  格式。文件已存在会报错不覆盖；需要用户确认。
- `word_append(filename, content_markdown)`：向已有 docx 追加内容；文件必须已存在；
  需要用户确认。
- `reformat_report()`：把最近一次分析输出的 AutoRadiomics_Report.docx 重排为上述
  格式。免确认、幂等，原文件自动备份为 .bak.docx。用户反馈报告格式混乱或要求
  "排版/重排报告"时调用。

content_markdown 一律用 markdown 组织：`#`/`##`/`###` 为各级标题，`- ` 或 `* ` 为
列表项，`**粗体**` 会保留加粗，其余为正文段落。

需要从零写一份 Word 文档时用 word_create；后续补充章节用 word_append；只修格式、
不动内容时用 reformat_report。
