# 设计目标与原则

> 本章节内容提炼自《OneRad 智能体设计文档》（`docs/OneRad智能体设计文档.docx`，2026-07-24 版，基于 `app/agent/`、`app/api/`、`skills/`、`frontend/src/` 实际代码反向提炼），面向研发人员、技术评审与二次开发维护者。

## 领域背景

影像组学（Radiomics）是从 CT、MRI、PET 等医学影像中高通量提取定量特征，并在此基础上建立预测模型的技术。其基本假设是：医学影像中蕴含着肉眼无法分辨的微观信息——灰度分布、纹理模式、病灶形态等定量特征能够刻画肿瘤的异质性，从而在无创条件下辅助预测病理分型、分子标志物、治疗反应与预后结局。

一次典型的影像组学分析可产出数百至上千个特征：描述病灶几何形态的**形状特征**（shape）、刻画体素灰度分布的**一阶统计特征**（first order），以及描述灰度空间依赖关系的**纹理特征**（GLCM、GLRLM、GLSZM、GLDM、NGTDM 等）。对原图施加 LoG 滤波或小波分解等变换后再提取，可进一步捕捉不同空间尺度下的影像模式。

在方法学上，一次完整的影像组学分析涉及多个环节的串联：

**格式转换（DICOM → NIfTI，按需）→ 图像/mask 配对 → 参数确认 → 特征提取 → 临床表解析 → 特征筛选+建模 → 模型评估与报告生成**

传统做法需要研究者手动切换多个 Python 脚本完成上述流程：每一步都涉及参数判断与文件路径管理，对缺乏编程经验的临床研究者门槛较高；中间产物分散、参数记录不全又使流程难以复现；新增病例或调整参数时往往需要从头梳理，重复劳动量大。

OneRad Agent 正是针对这些痛点而设计：**让临床研究者用自然语言描述分析意图**，Agent 在理解项目上下文后自主规划并执行流程，识别可复用的中间产物并增量推进，同时在关键操作节点（文件修改、脚本执行、耗时计算）征得用户确认。

## 核心设计原则

| 原则 | 说明 | 在代码中的体现 |
|------|------|---------------|
| **安全可控** | 所有副作用操作均需用户确认；路径活动被沙箱限制 | `Sandbox.resolve()` 拒绝越界路径；`process_tool_calls` 中 `confirmation_pending` 阻止静默执行 |
| **人机协同** | 采用 LangGraph `interrupt()` 挂起-确认-恢复循环，而非事后通知 | `human_review` 节点调用 `interrupt()` 序列化中断状态；前端渲染对应审批面板；用户操作通过 `Command(resume=...)` 恢复 |
| **可观测** | 思考链、提取进度、子 Agent 状态通过 SSE 实时推送 | `_publish_thinking` / `_publish_agent_progress` / `_publish_subagent` 三个旁路发布函数 |
| **上下文高效** | 子 Agent 在隔离上下文中运行，只有结论回到主对话 | `_run_subagent` 独立图 + 独立 MemorySaver；`_SUBAGENT_RESULT_MAX_CHARS = 4000` |
| **热更新友好** | System prompt 每次从磁盘读取，编辑即生效 | `skills.py` 的 `load_skill()` 无缓存设计 |

## 章节导读（对应设计文档七大部分）

| 页面 | 对应部分 | 内容 |
|------|---------|------|
| [整体架构](/design/architecture) | 第一部分 | 系统四层架构、技术栈、部署架构 |
| [LangGraph 状态机](/design/state-machine) | 第二部分 | 5 节点循环、superstep 流转、AgentState、checkpoint |
| [人机协同机制](/design/human-loop) | 第二部分 | interrupt 生命周期、审批面板映射、取消语义 |
| [运行时上下文与取消](/design/runtime-cancel) | 第二部分 | 跨线程通信、协作式取消、/stop 收尾清理 |
| [子 Agent 系统](/design/subagent-system) | 第三部分 | 并行探索、上下文隔离、取消传播 |
| [Skills 与项目记忆](/design/skills-memory) | 第三、六部分 | 技能加载机制、跨线程记忆提取与注入 |
| [流式通信与前端](/design/streaming) | 第四部分 | 思考链保留、SSE 事件体系、前端状态管理 |
| [增量分析与状态感知](/design/incremental) | 第五部分 | 0–6 工作流、断点续提、路径约定 |
| [结果解读与可解释性](/design/interpretation) | 第五部分 | 三段式解读、逐折 SHAP、列名中译英 |
| [安全与数据支撑](/design/security-data) | 第六部分 | 路径沙箱、纵深防御、数据库设计、对话导出 |
| [关键设计决策](/design/decisions) | 第七部分 | 技术选型权衡、API 参考、术语对照 |
