# 结果解读与可解释性

## LLM 结果解读

### 设计动机与三段式结构

`metrics.json` 包含大量数值（AUC、敏感度、OR、p 值、SHAP 重要性……），对临床研究者不够直观。LLM 结果解读系统将这些数值转化为结构化的中文解读文本并自动注入报告——让报告不只是「数字的堆砌」，而是「有结论的发现」。

系统通过 `skills/result-interpretation/SKILL.md` 的 prompt 模板驱动 LLM 输出三段解读：

- **【模型性能解读】**：判别能力（AUC + 95%CI）、误差结构（混淆矩阵 → 漏诊 vs 误诊）、跨折稳定性（Mean±SD 小 → 折间表现稳定），明确所有指标来自 out-of-fold 内部验证
- **【特征意义解读】**：逐一解释特征影像组学含义（特征类 + 滤波器）、方向性（系数符号与 OR，OR>1 → 特征升高 → 阳性概率升高）、与 SHAP 方向的一致性比对
- **【SHAP可解释性解读】**：按 mean|SHAP| 重要性排序解读 top 特征，折覆盖次数反映跨折稳定性
- 三段末尾附**局限性声明**：相关 ≠ 因果、样本量限制、需外部验证

### 实现流程

`app/interpretation.py` 分三步：

1. **build_summary()**：聚合纯数值摘要——metrics、cv_metrics（逐折）、coefficients（系数/OR/CI/p）、shap（跨折 mean|SHAP| + 方向 + 与系数一致性）。SHAP 聚合逻辑：读取 `shap/shap_values_fold*.csv`，每特征逐折计算 mean|SHAP|，跨折平均得到全局重要性（取 top 15），折覆盖次数为该特征在几折出现，方向取逐折 mean SHAP 符号，并与回归系数方向比对给出 `direction_consistent` 标记
2. **interpret()**：调 LLM 生成三段中文解读，按 SECTION_MARKERS 分隔标记解析输出
3. **apply_to_reports()**：重写 `report.md`（追加「结果解读」小节）和 `report.docx`（同步更新），幂等——重复调用不会叠加小节

`interpret_analysis_results` 是**免确认工具**，在 `process_tool_calls` 中直接执行；任何失败（无 API key、LLM 异常、返回格式异常、旧输出目录缺 `analysis_result.json`）都优雅返回错误说明，不影响既有产物。

### SHAP 可解释性分析（逐折）与报告重建

在 `app/analysis.py` 的交叉验证循环中，每折训练完成后自动执行 SHAP 分析：选用 explainer（**LinearExplainer 优先，KernelExplainer 回退**），计算训练集 SHAP 值（取正类），落盘：

- `shap_summary_fold{N}.png`（beeswarm 散点图）
- `shap_bar_fold{N}.png`（mean|SHAP| 柱状图）
- `shap_values_fold{N}.csv`（每例每特征 SHAP 值）

SHAP 图通过 `plot_paths` 嵌入报告，在 `report.md` 中作为「SHAP 可解释性」小节。

**报告重建的上下文恢复**：`apply_to_reports()` 重新生成报告时所需的上下文（协变量、折数、特征总数、图表路径）从输出目录的磁盘产物恢复——`analysis_params.json` → covariates/n_splits/feature_csv；标准命名 PNG → roc_curve/calibration_curve/dca_curve；`lasso/lasso_path_fold*.png` → lasso_paths；`shap/*.png` → shap_plots。这保证了即使不在分析刚完成的调用上下文中（例如用户稍后要求「重新解读」），也能正确重建完整报告。

## 临床列名自动中译英

临床研究者常使用中文列名（如「年龄」「性别」「病理分级」）。这些列名进入分析流程后会导致：

1. **matplotlib 渲染乱码**：ROC/SHAP 图中文标注在无中文字体环境中显示为方块
2. **报告可读性差**：英文报告中中文别名不一致
3. **复现性问题**：中文路径/列名在不同操作系统间行为不一致

`app/clinical.py` 的 `translate_column_names()` 用一次 LLM 调用把中文等非 ASCII 临床列名翻译为医学通用英文，仅保留纯 ASCII、非空的译名（非法译名不出现在结果中，调用方对其保持原名）。在 `run_radiomics_cv_analysis()` 中，合并特征与临床数据后自动检测非 ASCII 列名并翻译，同步更新 `id_col`、`label_col` 映射。

**复现保证**：翻译映射写入 `analysis_params.json` 的 `column_name_mapping` 字段；复跑时按映射直接重命名临床列，**不调用 LLM**，保证复现的确定性。报告中协变量以双语对照形式展示（如 `Age（年龄）`，通过反向映射 `{英文: 中文}` 查找）。
