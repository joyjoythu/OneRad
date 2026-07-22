# 逐折 SHAP 可解释性 + 逐折产物 — 设计文档

日期：2026-07-22
状态：已批准

## 背景与目标

`run radiomic analysis`（`app/radiomics_analysis.py` 的 `run_radiomics_cv_analysis` + `app/analysis.py` 的 `AnalysisAgent`）目前只产出 OOF 级别的结果：汇总的 `case_predictions.csv`、ROC/校准/DCA 曲线、逐折 LASSO path 图。缺乏特征可解释性分析，逐折的预测与曲线也不落盘。

参考 `reference_code/Classify/Classify_ALL_clean_v4_clinical_subsets_equal_weight.py:973-1011` 的逐折 SHAP 实现，为分析流程增加：

1. 逐折 SHAP 可解释性分析（beeswarm + bar 图 + SHAP 数值 CSV），SHAP 图全部进入 Word/Markdown 报告。
2. 逐折产物落盘：每折验证集 predictions CSV、每折 ROC/校准/DCA 曲线（仅存文件，不入报告）。
3. 产物按类型组织到子文件夹。

## 需求决策（用户已确认）

| 决策点 | 结论 |
|---|---|
| SHAP 分析对象 | 逐折 SHAP（复刻参考代码方式），每折训练后对当折模型计算 |
| SHAP 产物 | 图 + SHAP 数值 CSV |
| SHAP 图进报告 | 10 张逐折 SHAP 图全部进入 report.docx / report.md |
| SHAP 特征范围 | 当折模型全部输入特征（LASSO 选中影像组学特征 + 临床协变量），真实特征名，不匿名化 |
| 逐折曲线类型 | ROC + 校准 + DCA，每折各一张 |
| 逐折曲线/预测进报告 | 不入报告，仅存文件 |
| 实现方案 | 方案 A：在 `AnalysisAgent.run()` 的 CV 循环内集成 |

## 架构

采用方案 A（循环内集成），与现有 `lasso_path_foldN.png` 逐折绘图模式一致：

- `app/analysis.py`（`AnalysisAgent.run()` 的 CV 循环）：每折 LR 训练后立即——
  1. 计算 SHAP 并保存两张图 + 数值 CSV；
  2. 收集当折验证集 predictions 并保存 CSV；
  3. 画当折 ROC/校准/DCA 曲线。
- `app/curves.py`：新增 `plot_shap_beeswarm()` / `plot_shap_bar()`，封装 `shap.summary_plot`（Agg backend、英文标签、`savefig(dpi=150, bbox_inches="tight")`、`plt.close` 放 finally），风格与现有绘图函数一致。
- `app/radiomics_analysis.py`（`run_radiomics_cv_analysis`）：创建子目录、把新图路径汇总进 `outputs` 和 `plot_paths`；SHAP 图路径追加进 `plot_paths` 后自动进入 ReportAgent（Word）和 report.md。

## SHAP 计算细节

复刻参考代码逻辑（`Classify_ALL_clean_v4_clinical_subsets_equal_weight.py:983-996`）：

```python
try:
    explainer = shap.LinearExplainer(fold_model, X_train_scaled)
    shap_values = explainer.shap_values(X_train_scaled)
except Exception:
    background = shap.sample(X_train_scaled, min(50, len(X_train_scaled)))
    explainer = shap.KernelExplainer(
        lambda x: fold_model.predict_proba(x)[:, 1], background)
    shap_values = explainer.shap_values(X_train_scaled)
if isinstance(shap_values, list):
    shap_values = shap_values[1]  # 正类
```

- 数据：当折训练集（已 StandardScaler 标准化、已含临床协变量、已按当折 LASSO 掩码筛选影像组学特征）。
- 图：`shap.summary_plot(..., show=False)`，`max_display=20`，beeswarm 与 `plot_type="bar"` 各一张，dpi=150（跟随项目约定，不沿用参考代码的 600）。
- CSV：`shap_values_fold{N}.csv`，行=当折训练集病例（含 `patient_id` 列），列=特征 SHAP 值。
- 容错：单折 SHAP 失败仅记 warning，不中断流程（同参考代码与现有 curve_specs 模式）。

## 输出目录结构

```
radiomics_analysis/
├── case_predictions.csv                # 现有 OOF 汇总，保留
├── selected_features.csv               # 现有
├── roc_curve.png                       # 现有 OOF 图
├── calibration_curve.png               # 现有
├── dca_curve.png                       # 现有
├── lasso/
│   └── lasso_path_fold1..5.png         # 从根目录迁入
├── curves/
│   ├── roc/roc_fold1..5.png
│   ├── calibration/calibration_fold1..5.png
│   └── dca/dca_fold1..5.png
├── shap/
│   ├── shap_summary_fold1..5.png
│   ├── shap_bar_fold1..5.png
│   └── shap_values_fold1..5.csv
└── predictions/
    └── case_predictions_fold1..5.csv   # 列同现有：patient_id, y_true, prob, y_pred
```

**注意**：`lasso_path_foldN.png` 从根目录迁入 `lasso/` 改变了现有输出路径契约，引用旧路径的测试与文档需同步更新。

## 逐折曲线与 predictions

- 每折用当折模型在**当折验证集**上的预测概率画 ROC / 校准 / DCA，存 `curves/`。
- 当折验证集 predictions 存 `predictions/case_predictions_fold{N}.csv`，列：`patient_id, y_true, prob, y_pred`。其中 `y_pred` 使用**当折自身的 Youden 最优阈值**（由当折验证集 prob 计算，与 OOF 汇总 CSV 的阈值口径同源但逐折独立），因为循环内尚无全局 OOF 阈值。
- 仅落盘，不进入报告。

## 报告集成

- report.docx / report.md 新增 "SHAP Interpretability" 小节：先用一段英文文字说明 SHAP 的含义与读图方法（beeswarm 中点色表示特征值高低、横向位置表示对预测为正类的推动方向与幅度；bar 图表示平均绝对贡献度排序），再按 fold1..5 顺序嵌入全部 10 张 SHAP 图（每折 beeswarm + bar）。
- LASSO path 图：报告中**只展示 fold1 一张**作为代表（附说明其余各折见 `lasso/` 目录），不再把 5 张全部嵌入；`lasso_path_fold1..5.png` 仍全部落盘到 `lasso/`。

## 依赖

- `requirements.txt` 增加 `shap`（间接引入 numba 等，安装较重）；同步更新 `requirements.lock`。
- 无需引入 xgboost/lightgbm——模型为 LogisticRegression，`LinearExplainer` 即可。

## 测试

- 新增 `tests/test_shap_analysis.py`：
  - 小合成数据集跑完整 `run_radiomics_cv_analysis`，断言 `shap/`、`curves/roc/`、`curves/calibration/`、`curves/dca/`、`predictions/`、`lasso/` 产物齐全；
  - 断言 `shap_values_fold{N}.csv` 含 `patient_id` 列且特征列数与当折模型输入一致；
  - mock shap 抛异常，断言流程不中断且其余产物正常；
  - 断言 `outputs` / `plot_paths` 包含全部 SHAP 图，且 `plot_paths` 中 LASSO path 图只有 fold1 一张。
- 更新引用旧 `lasso_path_foldN.png` 根目录路径的既有测试。
- 现有测试套件保持全绿。

## 错误处理

- 任何单折的 SHAP / 逐折曲线 / 逐折 CSV 保存失败：记 warning，继续后续折与整体流程（与现有"单图失败不中断"约定一致）。
- 子目录在导出阶段统一 `mkdir(parents=True, exist_ok=True)`。
