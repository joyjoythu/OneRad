# LLM 结果解读注入报告 — 设计文档

日期：2026-07-22
状态：已批准

## 背景与目标

当前分析报告（report.md / report.docx）由固定模板生成，只有数值表格和图片，缺少解读。本功能让 LLM 自动解读分析结果——模型性能、特征意义、SHAP 可解释性——生成中文解读文字填入报告，使报告更直观清晰。

## 需求决策（用户已确认）

| 决策点 | 结论 |
|---|---|
| 解读范围 | 模型性能（基于指标数值，不读 PNG 图）+ 特征意义 + SHAP 解读（基于 shap_values 表格聚合） |
| 语言 | 统一中文（report.md 与 report.docx 一致） |
| 架构 | Agent 工具 + 底层独立模块（工具为薄封装，核心逻辑在 `app/interpretation.py`，直接调用路径可复用） |
| 调用时机 | 分析成功后 agent 自动调用解读工具补全报告；用户可随时要求重新解读 |
| 性能图 | 不做图像理解（DeepSeek 无 vision 能力），仅基于数值 |

## 架构

### 1. 核心模块 `app/interpretation.py`

- `build_summary(analysis_result, output_dir) -> dict`：聚合纯数值摘要：
  - 完整 `metrics`（AUC+95%CI、accuracy、sensitivity、specificity、PPV、NPV、F1、threshold、混淆矩阵）；
  - `cv_metrics`（逐折指标 + Mean±SD，用于稳定性判断）；
  - 选中特征表：feature、coefficient、OR、95%CI、p 值（来自 `model_results`）；
  - 特征名结构化解析：如 `wavelet-LLH_glcm_Contrast` 拆为 滤波器/特征类/特征名 三段；
  - SHAP 聚合（读 `shap/shap_values_foldN.csv`）：每特征 mean|SHAP| 跨折平均 → 全局重要性 top 15、折覆盖次数（该特征在几折被选中）、SHAP 方向（mean SHAP 符号）与系数方向是否一致；
  - 上下文：n_samples、oof 正负例数。
- `interpret(summary, llm_client) -> dict[str, str]`：一次 `LLMClient.call`（system prompt 来自 `skills/result-interpretation/SKILL.md`），返回 `{"performance": ..., "features": ..., "shap": ...}` 三段中文 markdown 文字。用分隔标记或 `call_json` 解析，格式异常时回退。
- `apply_to_reports(analysis_result, output_dir, interpretation)`：重新生成 report.md（`_render_markdown_report`）与 report.docx（`ReportAgent.run`），注入解读小节。幂等：重复调用结果一致，不产生重复小节。

### 2. 数据持久化

- `run_radiomics_cv_analysis` 导出阶段新增写 `analysis_result.json` 到输出目录，内容为 JSON 安全子集：`metrics`、`cv_metrics`、`model_results`、`selected_features`、`n_samples`、`oof_probabilities`。
- `outputs` dict 增加 `analysis_result_json` 键。
- 解读原文保存为输出目录下 `interpretation.md`，`outputs` 增加 `interpretation` 键（由工具调用后写入/更新）。

### 3. Agent 工具 `interpret_analysis_results`（`app/agent/tools.py`）

- 无参数；从 agent 会话上下文中取当前项目路径与最新分析输出目录（沿用现有分析工具的定位逻辑，不接受用户传入路径）。
- 加载 `analysis_result.json` → `build_summary`（读 `shap/` CSV）→ `interpret`（LLMClient，api key 走现有 state/config 解析链）→ `apply_to_reports` → 写 `interpretation.md`。
- 返回：成功时返回生成的小节摘要与报告路径；`analysis_result.json` 不存在（旧输出目录）时返回明确错误提示用户先重新运行分析。
- 报告生成函数签名扩展：`_render_markdown_report` 与 `ReportAgent.run` 增加可选 `interpretation=None` 参数；为 None 时不生成解读小节（现状行为）。

### 4. 报告集成

- report.md：末尾新增 `## 6. 结果解读` 小节，含 `### 模型性能解读`、`### 特征意义解读`、`### SHAP 可解释性解读` 三个子节。
- report.docx：新增 `结果解读` 小节，同样三段中文文字（markdown 转 docx 段落，按现有 ReportAgent 的文字添加方式）。
- 小节编号顺延问题：沿用现有硬编码编号方式处理（md 中 SHAP 为 5，解读为 6）。

### 5. workflow 指引

- `skills/radiomics-workflow/SKILL.md` 增加一条：分析成功、报告生成后，自动调用 `interpret_analysis_results` 工具为报告补充 LLM 解读；告知用户报告已更新。用户之后说"重新解读/再解读一次"时再次调用。

### 6. prompt 模板 `skills/result-interpretation/SKILL.md`

- 仅基于给定数值，不得编造数据或引用未提供的信息；
- 性能部分：按指标数值解读（AUC+95%CI 的判别能力、敏感度/特异度平衡、逐折 Mean±SD 的稳定性），不夸大证据强度；
- 特征部分：逐特征解释影像组学含义（特征类 + 滤波器）与方向性（系数/OR 方向、与 SHAP 方向是否一致）；
- SHAP 部分：按 mean|SHAP| 重要性排序解读 top 特征，指出折覆盖次数反映的跨折稳定性；
- 结尾附局限性声明（相关性非因果、样本量限制、需外部验证）；
- 中文、markdown 输出，三段用约定分隔标记。

## 错误处理

- 无 API key / LLM 调用失败 / 返回格式异常：记 warning，工具返回失败说明；基础报告与既有产物不受影响。
- 解读工具重复执行：幂等重生成报告，不叠加小节。
- `shap/` CSV 缺失或部分折缺失：按可用折聚合，摘要中注明折数。

## 依赖

- 无新增第三方依赖（复用现有 `LLMClient` / openai SDK）。

## 测试

- 新增 `tests/test_interpretation.py`：
  - `analysis_result.json` 在分析流程后正确落盘且可加载；
  - mock LLMClient：解读三段文字正确注入 report.md（含小节标题）与 report.docx，重复调用幂等；
  - LLM 抛异常 / 返回格式错误：工具优雅失败，基础报告不受影响；
  - `build_summary` 聚合正确性：合成 shap_values CSV，验证 top 排名、折覆盖次数、方向一致性；
  - 工具在缺少 `analysis_result.json` 时返回明确错误。
- 工具注册与 agent 集成测试参照现有 `tests/test_agent_*.py` 的模式。
- 现有测试套件保持全绿。
