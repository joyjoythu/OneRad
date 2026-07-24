# Skills 系统与项目记忆

## Skills 系统

### 设计理念与加载机制

System prompt 不是硬编码在 Python 中的字符串，而是放在 `skills/<name>/SKILL.md` 下的 Markdown 文件，**每次 LLM 调用时从磁盘实时读取，无任何缓存**。好处：

- 调整 Agent 行为只需编辑 Markdown 文件，无需重启服务
- 非编程人员也可修改 prompt（调整工作流步骤、措辞风格等）
- Git 版本控制友好，prompt 变更可追溯

`app/skills.py` 的 `load_skill(name)` 读取 `skills/<name>/SKILL.md` 并剥离 YAML frontmatter；`load_skill_bundle(names)` 将多个 skill 以注释标记拼接。主 Agent 调用 `load_skill_bundle(("agent-core", "radiomics-workflow"))`。skill 名须匹配 `^[a-z0-9]+(?:-[a-z0-9]+)*$`。

### Skill 清单

| Skill | 核心职责 |
|-------|---------|
| `agent-core` | Agent 角色定义与工作行为准则（先探索再修改、工具结果为准、executed 标记含义、安全边界不可绕过），约 1KB |
| `radiomics-workflow` | 影像组学工作流 0–6 步骤：先 explore 探索 →（输入为 DICOM 时先转 .nii.gz）配对发现 → spacing 检查 → 参数确认 → 特征提取 → 临床表审查 → 建模 → 报告；强调每进入/完成阶段调用 `update_todo_list`，约 2KB |
| `file-operations` | `plan_file_operations` 工具的 prompt 模板：如何从用户需求生成 move/copy/rename/mkdir 计划 |
| `clinical-columns` | 帮助 LLM 从临床表列名中识别患者 ID、二分类 Label、协变量 |
| `filename-id` | 从 NIfTI 文件名中推断患者 ID 的正则模式 |
| `report-writing` | Word 报告的方法学描述润色提示 |
| `thread-title` | 从用户首条消息生成 15 字以内的对话标题 |
| `word-report` | Word 文档中文学术论文格式规范及 `word_create`/`word_append`/`reformat_report` 使用指引 |
| `result-interpretation` | 三段式中文解读 prompt（性能/特征/SHAP），三段末尾附局限性声明；严格禁止编造数据或引用未提供的信息 |

### agent-core SKILL.md 的关键指令

- 收到「开始分析」类请求时，优先用 `dispatch_subagent(mode="explore")` 并行探索项目
- 工具结果是唯一真相源——不要声称文件/分析存在，除非工具结果确认了它
- 被 `{"executed": true, ...}` 包裹的结果表示操作已执行，总结给用户，不要再问确认
- 遇到需要向用户澄清的问题时，使用 `ask_user_choice` 让用户在几个明确方案中选择
- 尊重每一个确认步骤、沙箱边界、schema 约束和风险决策，不要绕过被拒绝的操作

---

## 项目长期记忆

### 设计动机与架构

用户常在同一项目下开启多个对话线程，但上下文并不互通。例如第一个对话中用户确认了「患者 ID 是 PATIENT_ID 列，Label 列是 Label（1=阳性，0=阴性）」，换到新对话后这些信息需要重新告知——既浪费上下文窗口，也降低用户体验。项目记忆系统在**项目粒度**上跨线程共享已知事实，实现「一次确认，项目内所有对话自动回忆」。

```
对话线程 1 ── 流结束 ──▶ extract_memories() ──▶ SQLite memories 表
对话线程 2 ── call_llm ──▶ build_memory_prompt() ──▶ System Prompt 注入"项目记忆"块
```

### 提取（Extraction）

每次对话流正常结束（非异常、非取消）后，`_maybe_extract_memories()` 被调用：

1. 检查全局记忆开关（`settings_store.is_memory_enabled()`）
2. 用 LLM 从本轮对话（只取 user/assistant 消息）中提取关键事实——提取 prompt 要求**只提取客观的、结论性的信息**，忽略临时问答/调试/问候
3. 持久化到 SQLite（同 project+category+fact 去重）

五类记忆：

| 类别 | 含义 | 示例 |
|------|------|------|
| `clinical` | 临床信息 | "Label 列的值 1 表示恶性，0 表示良性" |
| `decision` | 过往决策 | "用户选择使用 binWidth=15 而不是默认的 25，因为病灶较小" |
| `finding` | 分析发现 | "上一轮 LASSO 筛选出 wavelet-LLH_glcm_Contrast 为最重要特征" |
| `preference` | 用户偏好 | "用户偏好中文报告，分析方法使用五折交叉验证" |
| `general` | 其他 | "该项目使用 3T MRI 扫描，序列为 T2-FLAIR" |

### 注入（Injection）与全局开关

每次 `call_llm` 节点开始前，从数据库读取记忆并注入 system prompt：`build_memory_prompt()` 按类别标签顺序组织记忆为 Markdown 格式，最多注入 **20 条**（`MAX_MEMORIES`），在 skills 之前插入 system prompt。

用户可在**设置页面**通过开关控制记忆功能（`~/.onerad/settings.yaml` 中 `features.memory_enabled`，缺省为 true）。关闭后：新对话不再提取记忆，已有对话的 system prompt 中不再注入记忆；但已存储的记忆**不会删除**，重新开启后自动恢复。前端 `SettingsView.vue` 通过 `PUT /api/settings` 切换开关。

### 设计原则

| 原则 | 体现 |
|------|------|
| **项目隔离** | 记忆表以 `project_id` 关联项目，不同项目间不共享 |
| **最低权限** | 开关状态仅影响提取和注入，不删除已存数据 |
| **静默失败** | 提取/注入任一步骤失败只记日志，不影响对话主流程 |
| **截断保护** | 消息过长时截断（user 1000 字符/assistant 2000 字符），对话只取最后 100 行，控制提取成本 |
| **用户可控** | 设置页一键开关，功能行为透明 |
