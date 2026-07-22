# 影像组学分析 Agent 工具设计

日期：2026-07-16
状态：已获用户确认（2026-07-16）

## 1. 背景与目标

项目已有 `AnalysisAgent`（`app/analysis.py`）：分层五折 CV、Mann-Whitney U 预筛（上限 100）、每折 `StandardScaler + LassoCV(cv=3)` 选影像组学特征 + 逻辑回归、各折特征取交集为稳定特征集、全量数据拟合最终 LR 并输出系数/OR/95%CI/p 值、bootstrap AUC CI、混淆矩阵、每折 LASSO path 图。该流水线目前只能经 CLI（`main.py --feature-csv + --clinical` → `run_direct_analysis`）调用，对话式 agent 无法使用。

本次目标：为对话式 agent 新增一个分析工具，使用户在聊天中给出（或不给出）文件路径即可完成：

1. 读取已提取的影像组学特征 CSV 与临床表格；
2. **自动识别两者的对应关系**（哪个文件是临床表、哪列是 ID、哪列是标签、ID 匹配情况），识别不确定时在对话中向用户提问澄清；
3. 随机划分五折交叉验证（沿用现有分层五折方法学，不改）；
4. Lasso（LassoCV）筛选特征 + 逻辑回归分类（沿用现有实现，不改）；
5. 整理分类结果：ROC 曲线、校准曲线、决策曲线（DCA）、每病例预测概率表、特征系数/OR 表；
6. 生成 Word + Markdown 两份报告。

## 2. 总体流程

```
用户对话请求
  → agent 调用工具 run_radiomics_analysis(feature_csv, clinical, id_col, label_col, output_dir)（参数均可空）
  → 工具执行输入识别 inspect_analysis_inputs()
      ├─ 识别不全/有歧义 → 返回 {"status": "need_clarification", ...}，
      │    LLM 在对话中向用户提问，用户回答后 agent 带明确参数重新调用
      └─ 识别齐全 → 返回 {"_pending_tool": "run_radiomics_analysis", "meta": {...摘要...}}
  → human_review 中断，前端 AnalysisPanel 显示摘要，用户确认
  → execute_confirmed 执行 run_radiomics_cv_analysis()
      加载合并 → AnalysisAgent → 增强产物导出 → Word/Markdown 报告
  → JSON 安全摘要（指标、选中特征、产物路径）包成 ToolMessage 回到对话
```

## 3. 智能识别与澄清机制

新增 `inspect_analysis_inputs(project_path, feature_csv="", clinical="", id_col="", label_col="")`（放 `app/radiomics_analysis.py`），返回识别报告。识别规则（确定性启发式，不用 LLM）：

- **特征文件**：`feature_csv` 为空时默认 `<项目>/radiomics_features/radiomics_features.csv`；不存在则报错并提示用户提供路径。
- **临床文件**：`clinical` 为空时扫描项目目录（含一级子目录）的 `*.csv`/`*.xlsx`，候选条件：含至少一个 0/1 二值列，且含至少一个与特征 `patient_id` 有交集的列。唯一候选 → 采用；零个 → 报错请用户提供；多个 → 返回候选路径清单请用户选择。
- **ID 列**：统计临床表各列与特征 `patient_id` 的交集大小，取匹配最多的列；所有列交集均为 0 → 报错请用户指定 `id_col`；最优列与次优列匹配数相同 → 列出候选请用户选择。匹配统计（特征例数、匹配例数）记入识别报告。
- **标签列**：`label_col` 已给则校验其为 0/1；未给时优先名为 `Label`（大小写不敏感）的 0/1 列，否则取唯一 0/1 二值列；多个二值列 → 列出候选请用户选择；没有 → 请用户指定。
- 列识别复用 `app/clinical.py`（ClinicalAgent）现有的 ID/标签列识别逻辑；其不适配的部分（如 ID 交集匹配）在本模块新写。

**澄清返回格式**（不进确认中断，直接作为工具结果回到 LLM）：

```json
{
  "status": "need_clarification",
  "questions": [
    {"field": "label_col", "question": "临床表中有多个 0/1 列，哪一列是分组标签？",
     "candidates": ["Label", "group"]}
  ],
  "detected": {"feature_csv": "...", "clinical": "...", "id_col": "patient_id",
               "n_feature_cases": 120, "n_matched": 118}
}
```

**识别齐全时的 pending 返回**（进入执行确认中断）：

```json
{
  "_pending_tool": "run_radiomics_analysis",
  "meta": {"feature_csv": "...", "clinical": "...", "id_col": "patient_id", "label_col": "Label",
           "output_dir": "<项目>/radiomics_analysis",
           "n_feature_cases": 120, "n_matched": 118, "n_features": 1316,
           "covariates": ["age", "sex"]}
}
```

## 4. 后端改动

### 4.1 `app/analysis.py`（一处小改）

`AnalysisAgent.run` 返回字典新增字段 `"oof_probabilities": List[float]`——按 `merged_df` 行序排列的每病例 out-of-fold 预测概率（即现有局部变量 `val_probs` 转为 list）。纯新增，不改任何现有逻辑；现有测试不受影响。

### 4.2 新增 `app/curves.py`

全部使用现有 matplotlib（Agg）/sklearn/numpy，无新依赖。每个函数保存 PNG 并返回路径：

- `plot_roc_curve(y_true, y_prob, auc, auc_ci, out_path) -> str`：OOF 概率 ROC 曲线，标注 AUC 及 95%CI，含对角参考线。
- `plot_calibration_curve(y_true, y_prob, out_path, n_bins=10) -> str`：等频分箱，各箱平均预测概率 vs 实际阳性率，含对角线。
- `plot_dca(y_true, y_prob, out_path) -> str`：阈值 0.01–0.99 的净获益曲线，含 treat-all / treat-none 参考线。净获益 = TP/n − FP/n × pt/(1−pt)。

### 4.3 新增 `app/radiomics_analysis.py`

- `inspect_analysis_inputs(...)`：见第 3 节。
- `run_radiomics_cv_analysis(feature_csv, clinical, output_dir, id_col=None, label_col=None, covariates=None, max_lasso_features=100, n_splits=5, random_state=42, llm_client=None, should_cancel=None) -> Dict[str, Any]`：
  1. 复用 `app/utils.py` 的 `_load_feature_csv` / `_load_clinical_for_analysis` / `_merge_feature_clinical` / `_infer_covariates` 加载合并；
  2. 每类样本数 < `n_splits` → 返回失败并提示；
  3. 跑 `AnalysisAgent`（方法学参数与现状一致）；
  4. 导出增强产物（见第 5 节）；单张图绘制失败只记 warning 不中断；
  5. 调 `ReportAgent` 生成 Word（新图追加进 `plot_paths` 一并嵌入，与 `run_direct_analysis` 相同方式）；
  6. 新生成 Markdown 报告（`_render_markdown_report`：方法描述、数据概况、指标表、混淆矩阵、稳定特征系数表、图片相对路径引用、OOF 概率说明）；
  7. `should_cancel`（可选回调）在各阶段之间检查，触发则返回取消状态。
  
  返回：`{"success", "message", "analysis_result", "outputs": {各产物路径}}`。

### 4.4 Agent 工具接入（四处接线，仿 `extract_radiomics_features`）

- `app/agent/tools.py`：`build_tools` 内注册 `@tool run_radiomics_analysis(feature_csv="", clinical="", id_col="", label_col="", output_dir="")`。docstring 说明：分析已提取特征 + 临床表、执行前需确认、信息不足会先返回需澄清问题。工具体内做沙箱路径解析后调 `inspect_analysis_inputs`，按结果返回澄清 JSON 或 pending JSON。
- `app/agent/state.py`：`AgentState` 新增 `pending_radiomics_analysis` 字段。
- `app/agent/nodes.py`：
  - `process_tool_calls`：`needs_confirmation` 集合加入该工具名；新增分支 `interrupt_type = "radiomics_analysis"`、`updates["pending_radiomics_analysis"] = {"tool_call_id": ..., **parsed["meta"]}`；
  - `human_review` 的 interrupt payload 增加 `"radiomics_analysis"` 键；
  - `execute_confirmed`：新增分支，解析沙箱路径后调 `run_radiomics_cv_analysis`（传入 runtime 的 cancel_event 派生的 `should_cancel`），结果按 `_json_safe_radiomics_result` 的思路摘要化（指标、auc_ci、n_samples、n_matched、selected_features、产物路径），不含大数组；
  - 末尾状态清理处 `pending_radiomics_analysis` 置 None。
- 路径安全：特征/临床/输出路径均经 `Sandbox` 校验，必须在项目目录内。

## 5. 输出产物

输出目录默认 `<项目>/radiomics_analysis/`（可经 `output_dir` 指定，沙箱内）：

| 文件 | 内容 |
|---|---|
| `case_predictions.csv` | patient_id、真实标签、OOF 预测概率、预测类别（按最佳阈值） |
| `selected_features.csv` | 稳定特征（各折交集）的系数、OR、95%CI、p 值 |
| `roc_curve.png` | ROC 曲线 + AUC(95%CI) 标注 |
| `calibration_curve.png` | 校准曲线 |
| `dca_curve.png` | 决策曲线 |
| `lasso/lasso_path_foldN.png` | 每折 LASSO path（2026-07-22 起迁入 `lasso/` 子目录，报告中仅展示 fold1） |
| `report.docx` | Word 报告（现有 ReportAgent，新图随 `plot_paths` 嵌入） |
| `report.md` | Markdown 报告（新） |

## 6. 前端改动（小）

- 新增 `frontend/src/components/AnalysisPanel.vue`：仿 `RadiomicsPanel.vue`，展示 pending 摘要（特征文件、临床文件、ID/标签列、匹配例数、特征数、协变量、输出目录）+ 确认/取消。
- `frontend/src/views/AgentView.vue`：侧栏加 `interrupt === 'radiomics_analysis'` 分支；`interruptTag` 加条目「待确认分析任务」。
- `frontend/src/stores/agent.ts`：同步 `pending_radiomics_analysis` 字段。
- `frontend/src/api/agent.ts`：类型定义加 `pending_radiomics_analysis`。
- 前端测试 `stores/__tests__/agent.spec.ts` 补状态同步用例。

## 7. 错误处理

- 沿用现有校验并中文报错：文件不存在、缺 ID/标签列、标签值非 0/1、合并后为空、各折特征交集为空且无协变量。
- 某类样本数 < 折数 → 提前返回失败，提示减少折数或检查标签。
- 识别阶段的多候选/无候选 → `need_clarification`（见第 3 节），不算错误。
- 曲线绘制单张失败 → warning，报告照常生成。
- 执行中被 `/stop` 取消 → 返回取消状态，`interrupt_type` 清理（遵循现有 `execute_confirmed` 的异常清理模式，nodes.py:478 注释所述）。

## 8. 测试

- `tests/test_curves.py`：合成数据验证三张 PNG 生成；DCA 净获益在 pt→0 时趋近流行率、treat-none 恒为 0；校准曲线分箱单调性不强制但坐标范围合法。
- `tests/test_radiomics_analysis.py`：
  - 小型合成数据集（含 ID 列、Label 列、若干 original_/wavelet- 特征 + 临床协变量）端到端跑通，断言第 5 节全部产物存在、`case_predictions.csv` 列正确、行数等于样本数；
  - `inspect_analysis_inputs`：唯一候选直接 ready；多 0/1 列 → need_clarification；无 ID 匹配 → need_clarification/error；显式 `label_col` 非 0/1 → error。
- `tests/test_agent_tools.py`：新工具 ready 时返回 `_pending_tool`、缺信息时返回 `need_clarification`。
- `tests/test_agent_nodes.py`：确认分支设置 `interrupt_type`/`pending_radiomics_analysis`；`execute_confirmed` 分支（mock 分析函数）返回 JSON 安全摘要并清理状态。
- 运行方式：`pytest tests/`；前端 `npm run test`（或项目既有命令）。

## 9. 范围外（YAGNI）

- 不改 `AnalysisAgent` 方法学（折数、预筛、LassoCV 内层 cv=3、交集策略均保持）；`run_direct_analysis` CLI 行为不变。
- 不支持多分类、生存分析、多模型对比、嵌套 CV。
- 不做训练/测试集留出（用户已确认不需要）。
- Markdown 报告不做 LLM 润色（Word 报告沿用现有可选润色机制）。
