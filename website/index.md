---
layout: home

hero:
  name: OneRad
  text: 影像组学智能体使用指南
  tagline: 用自然语言快速处理和整理医学影像数据，一键提取影像组学特征并完成统计验证
  actions:
    - theme: brand
      text: 快速上手 →
      link: /guide/installation
    - theme: alt
      text: 在 GitHub 查看
      link: https://github.com/joyjoythu/OneRad

features:
  - icon: 💬
    title: 自然语言驱动
    details: 一句「开始分析」，Agent 自动完成配对发现、特征提取、建模分析、报告生成的全流程，无需手写脚本。
  - icon: 🤝
    title: 人机协同
    details: 文件修改、脚本执行、耗时计算等关键操作逐一审批；文件计划可编辑，Python 脚本带风险分级标记。
  - icon: 🔍
    title: 并行子 Agent 探索
    details: 多个只读子 Agent 并行扫描目录结构、配对情况、临床表格，中间过程隔离，只有结论回到主对话。
  - icon: 🛠️
    title: 专有工具内置
    details: DICOM 转 NIfTI、影像组学特征提取、统计分析等专用工具开箱即用，一句话调用，无需手写脚本。
  - icon: 🧠
    title: 项目记忆
    details: 分析偏好与确认过的项目事实一次记录，项目内所有对话共享——跨线程的记忆，而非简单的历史记录。
  - icon: 📄
    title: Word 统计报告
    details: 自动生成 Word 统计报告：方法描述、统计结果表格、ROC / 校准 / DCA 等图表一站式汇总，省去手动整理。
---

## 什么是 OneRad？

OneRad 是一个基于大语言模型（LLM）的端到端影像组学分析平台。它把影像组学研究中的七个环节——

**图像/Mask 配对 → 临床表解析 → 参数确认 → QC → 特征提取 → 特征筛选 + 建模 → 报告生成**

——封装进一个对话式智能体。临床研究者用自然语言描述分析意图，Agent 在理解项目上下文后自主规划并执行流程，同时在关键操作节点征得用户确认。

## 三分钟了解 OneRad

| 场景 | 你只需要说 | Agent 会做什么 |
|------|-----------|---------------|
| 数据预处理 | 「帮我把这些 DICOM 转成 nii.gz」 | 扫描目录、识别序列、批量转换 |
| 全流程分析 | 「开始分析」 | 探索 → 配对 → 参数 → 提取 → 建模 → 统计报告 |
| 增量分析 | 「继续分析」 | 检测已有产物，从断点继续 |
| 文件定位 | 「那个包含 LASSO 结果的报告在哪」 | @ 文件索引快速定位 |
| 重复实验 | 「用同样的数据再做一次分析」 | 项目记忆注入已知事实，无需重复确认 |

## 技术栈

| 层 | 技术 |
|---|------|
| Agent 框架 | LangGraph（状态机 + 人工中断 + SQLite 持久化） |
| LLM | DeepSeek（兼容 OpenAI SDK，保留思考链） |
| 后端 | Python 3.12 / FastAPI / SSE 流式推送 |
| 前端 | Vue 3 + TypeScript + Element Plus |
| 影像 | PyRadiomics / SimpleITK |
| 建模 | scikit-learn（LASSO + 逻辑回归 + 分层交叉验证） |
| 部署 | Docker 单容器一体化 |

准备好开始了？前往 [安装部署](/guide/installation)。
