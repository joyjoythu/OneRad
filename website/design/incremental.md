# 增量分析与状态感知

影像组学分析是多步骤流程，每一步的产出是下一步的输入。实际使用中用户很少一次性跑通全流程——更常见的场景是：上次提取了特征但没做分析、已有特征 CSV 想换参数重新建模、新增病例需要增量提取、不确定中间文件是否可用。因此 Agent 被设计为**具备项目状态感知能力**：执行前扫描项目已有文件，识别可复用的中间产物，推断当前流程的真实起点，并在此基础上增量推进。

## 影像组学 0–6 步标准工作流

在 `radiomics-workflow` SKILL.md 的引导下，Agent 执行以下标准工作流：

### 步骤 0 · 项目探索

- 并行派发 2–4 个只读子 Agent（`dispatch_subagent`, mode="explore"）：扫描目录结构列出 `.nii.gz`/`.csv`/`.xlsx`/`.yaml`；检查 `images/` 与 `masks/` 评估配对情况；读取 `Params_labels.yaml` 总结提取参数；搜索临床表格列出列名和样本数
- **关键判断**：`radiomics_features/radiomics_features.csv`、`h5/*.h5`、`radiomics_analysis/`、`feature_statistics/` 是否存在可复用产出
- 有可复用产出：`update_todo_list` 将已完成步骤标记 completed，从实际断点开始 in_progress；无可复用产出：建立完整 6 步清单

### 步骤 1 · 配对发现

- **DICOM 预处理（按需）**：配对发现只识别 `.nii.gz`——若步骤 0 发现项目含 `.dcm` 数据，先用 `convert_dicom_to_nifti` 转换（需确认；输出镜像输入目录结构，转换进度实时推送前端），再对转换输出做配对发现
- `discover_radiomics_pairs()` 递归扫描 `images/` + `masks/`，输出三级置信度配对（high/medium/low）与未匹配列表
- 确认后面板展示配对结果，用户可**修改配对、移除低置信度配对、添加手动配对**
- 已有产出检测：若此前配对过，discover 结果应与上次一致；如有新增病例则重新扫描

### 步骤 2 · 参数确认（spacing 检查 + YAML 配置）

- 对已确认的 pairs 做 `inspect_image_spacing`：输出各轴 spacing 中位数/范围/不同取值数（≤50 例附逐例明细），给出 `resampledPixelSpacing` 建议值
- 比较当前 YAML 中的 `resampledPixelSpacing`：一致则确认参数进入提取；不一致则用 `ask_user_choice` 询问是否调整（"当前 YAML spacing=[3,3,3]，实测中位数=[1,1,5]，建议改为 [1,1,5]"）
- 用户要调整时 `update_yaml()` 修改——注意 **YAML 修改会使旧 h5 缓存失效**（参数 hash 变化），下次提取时这些病例自动重提
- spacing 检查在配对之后而非之前：spacing 依赖于已确认的配对列表，先确定「要分析哪些病例」，再逐个检查它们的 spacing

### 步骤 3 · 特征提取

- `extract_radiomics_features(pairs, yaml_path, force_rerun)`（后端 `app/feature.py` → `FeatureAgent.run()`）
- **断点续提**：每例提取后特征向量写入 `h5/<patient_id>.h5`；下次提取前检查 h5 存在性与参数 hash 一致性，都满足则跳过（resumed），`force_rerun=True` 忽略检查全部重提
- **进度推送**：每完成一个病例经 `progress_callback` → `_publish_agent_progress` → SSE → 前端进度条（current/total/patient_id）
- **取消支持**：每例完成后检查 `cancel_event`，已提取的 h5 保留，下次可从此处续提，/stop 不浪费已完成的工作
- **错误容忍**：单例失败记录到 `failed_cases.csv` 并继续，不因一个坏数据打断整批提取
- 产物：`radiomics_features.csv`（合并特征矩阵）、`failed_cases.csv`、`h5/<patient_id>.h5`（每例缓存）

### 步骤 4 · 临床表审查

- 自动搜索项目内临床 CSV/Excel，读取列名后由 LLM（`clinical-columns` skill）识别 ID 列、Label 列、可用协变量
- 若有歧义（多列候选）→ `need_clarification` → LLM 向用户提问，确认后进入分析
- 注意：提取特征不需要临床表，但建模需要，所以这一步在提取之后

### 步骤 5 · 建模分析

- `run_radiomics_analysis(...)`：LASSO + LogisticRegression 五折交叉验证（`app/radiomics_analysis.py`）+ 逐折 SHAP 可解释性分析（`app/analysis.py`）
- **分析前参数询问**：调用前必须先用 `ask_user_choice` 询问是否调整参数（`n_splits` 默认 5、`max_lasso_features` 默认 100、`random_state` 默认 42、`covariates`），不调整时留空使用默认值
- **参数自动推断**：`feature_csv` 缺省取默认路径，`clinical` 缺省自动搜索，`id_col`/`label_col` 缺省自动识别；有歧义返回 `need_clarification` 向用户确认
- **临床列名中译英**：合并数据后自动检测非 ASCII 临床列名 → LLM 翻译为英文（避免 matplotlib SHAP 图中文乱码），`column_name_mapping` 写入 `analysis_params.json` 保证复现确定性
- **SHAP 可解释性（逐折）**：LinearExplainer 优先（线性模型），KernelExplainer 回退；每折落盘 `shap_summary_fold{N}.png` / `shap_bar_fold{N}.png` / `shap_values_fold{N}.csv`；报告嵌入 fold-1 LASSO path 与全部逐折 SHAP 图
- **复现保证**：输出目录保存 `analysis_params.json`（参数快照）+ `run_analysis.py`（完整复跑脚本）
- **已有产出检测**：`radiomics_analysis/` 下已有结果时，Agent 报告已有结果并询问用户：覆盖重跑 / 仅查看 / 用新参数重跑
- 产物：`selected_features.csv`、`metrics.json`、`analysis_params.json`、`run_analysis.py`、`report.md`、`report.docx`、`interpretation.md`、`figures/`（ROC/校准/DCA）、`lasso/`、`shap/`、`predictions/`、`curves/`

### 步骤 6 · 结果解读与报告

- Agent 读取分析结果（`metrics.json` + `report.md`）向用户做结构化总结：模型性能（AUC、准确率、敏感性、特异性）、关键特征、校准与临床获益（校准曲线 + DCA）、产物路径、局限性与后续建议
- **自动补全**：分析成功后主动调用 `interpret_analysis_results` → 生成三段中文解读 → 注入 `report.md` 与 `report.docx`，`interpretation.md` 落地纯文本存档（幂等）
- 可选：`run_feature_statistics` 对选中特征做 t 检验 + MWU（产物 `feature_statistics/` 统计表格 .docx）；`reformat_report` 把分析报告重排为中文学术格式（免确认、幂等、原地保存）

## 项目状态感知

### 探索阶段的全景扫描

用户说「开始分析」，Agent 的第一步永远是 `dispatch_subagent(mode="explore")`。explore 子 Agent 的典型扫描逻辑：`list_directory(".")` 了解顶层结构；`find_files("*.nii.gz", "images")` 统计图像文件；检查 `radiomics_features/` 与 `radiomics_analysis/` 下是否已有产物；`read_yaml("Params_labels.yaml")` 读取提取参数；glob 搜索临床表格。

| 扫描结果 | 推断起点 |
|---------|---------|
| 完全没有中间产物 | 全新分析，从步骤 1 开始 |
| 有配对 + YAML，无 features | 从步骤 3（提取）开始 |
| 有 features CSV，无 analysis | 从步骤 5（分析）开始 |
| 全部都有 | 询问用户：查看报告？换参数重跑？新增病例？ |

### 提取阶段的缓存感知（断点续提）

`FeatureAgent.run()` 对每个病例检查 h5 缓存是否存在且缓存中的提取参数 hash 与当前 YAML 参数 hash 一致——都满足则跳过，否则重新提取。这是一种**基于内容哈希的缓存失效策略**：不依赖时间戳，而是检查提取参数是否真正变化。用户改了 YAML 中的 `resampledPixelSpacing` 后，受影响的病例自动重提；没改参数则直接复用。

### 分析阶段的输入自动推断

`run_radiomics_analysis` 的参数推断逻辑体现「约定优于配置」：

- `feature_csv` 缺省：先找 `radiomics_features/radiomics_features.csv`；不存在则搜索项目内所有 CSV，优先选列名含 `original_` 前缀的 PyRadiomics 特征文件
- `clinical` 缺省：搜索 CSV/Excel，排除特征 CSV 和系统文件后选取临床表
- `id_col` 缺省：LLM 辅助识别；`label_col` 缺省：找值为 0/1 的二值列
- 遇到歧义时仍以 `need_clarification` / `ask_user_choice` 向用户确认，**减少输入负担但不擅自决定**

### 三种增量场景与 Todo 状态同步

| 场景 | 用户操作 | Agent 行为 |
|------|---------|-----------|
| **新增病例** | 把新 .nii.gz 放进 images/ + masks/，说「继续提取新病例」 | discover_pairs 重新扫描发现新增病例；extract 时已有 h5 缓存跳过旧病例，只提新的 |
| **换参数重分析** | 说「把 binWidth 改成 15 重新分析」 | update_yaml 修改后 hash 变化，已缓存的病例自动重提，然后重新分析 |
| **已有特征 CSV，换临床表分析** | 说「用新的 clinical_v2.xlsx 做分析」 | 跳过提取，直接用指定临床表跑分析 |

Agent 通过 `update_todo_list` 向用户透明展示步骤完成情况，例如发现已有 h5 缓存 + 特征 CSV + 分析结果时，前 5 步标记 completed（特征提取标注 30/30 已完成），建模分析标记 in_progress；只有部分病例已提取时，特征提取步骤标注「22/30 已完成，断点续提中」。

### 路径推断的约定体系

Agent 在文件查找和产物引用上依赖一套**松散约定**，这些约定在 `radiomics-workflow` SKILL.md 中被编码为工作流知识，而非硬编码的路径常量：

| 产物 | 默认路径 | 推断逻辑 |
|------|---------|---------|
| 提取参数 YAML | `Params_labels.yaml` | 项目根目录下的 YAML 文件 |
| 图像 / Mask 文件 | `images/*.nii.gz` / `masks/*.nii.gz` | 递归搜索 |
| 特征 CSV | `radiomics_features/radiomics_features.csv` | 列名包含 `original_` 前缀的特征文件 |
| 失败记录 | `radiomics_features/failed_cases.csv` | 与特征 CSV 同目录 |
| 每例缓存 | `radiomics_features/h5/*.h5` | FeatureAgent 固定输出 |
| 分析结果 | `radiomics_analysis/` | 含 selected_features.csv + metrics.json + report.docx + analysis_params.json + run_analysis.py |
| SHAP 可解释性 | `radiomics_analysis/shap/` | 逐折 SHAP beeswarm/bar 图 + shap_values_fold{N}.csv |
| 逐折预测 / 曲线 | `radiomics_analysis/predictions/` / `curves/` | 每折 OOF 预测概率 / ROC·校准·DCA 图 |
| LLM 解读 | `radiomics_analysis/interpretation.md` | 三段式中文解读纯文本 |
| 统计结果 | `feature_statistics/` | 含统计表格 .docx（docx_style 学术格式） |
| 对话导出 | `conversation_exports/` | 对话导出为 Markdown/Word 的目标目录 |
| 脚本存档 | `agent_scripts/` | `execute_python_script` 工具固定输出目录 |
| 文件操作备份 | `.onerad_backup/<timestamp>/` | `execute_plan` 自动创建 |

这套约定使 Agent 在绝大多数情况下**不需要用户逐一指定文件路径**——它自己会找到。

### 设计原则总结

| 原则 | 体现 |
|------|------|
| **先看再做** | 任何操作前先探索项目已有文件，避免盲目重跑 |
| **缓存友好** | 特征提取基于内容哈希断点续提；参数不变就不重跑 |
| **路径推断优先** | 约定 > 用户指定 > 报错，减少用户的输入负担 |
| **歧义时确认** | 自动推断不确定时用 `need_clarification` 或 `ask_user_choice` 确认 |
| **错误不扩散** | 单个病例提取失败记录到 `failed_cases.csv`，不影响其他病例 |
| **进度透明** | 通过 `update_todo_list` + `radiomics_progress` 持续报告宏观进度和微观进度 |
