# 报告生成改进设计:五折交叉验证详细汇报与数值格式统一

日期:2026-07-20

## 背景与问题

当前 agent 系统的影像组学分析报告存在三个不足:

1. 五折交叉验证只汇报一套 OOF 汇总指标(AUC/准确率/敏感度/特异度),没有逐折明细,也没有跨折均值±标准差;
2. 数值小数位不统一(系数、p 值用 4 位,其余 3 位),未统一保存 3 位小数;
3. p 值未做 `<0.001` 归并显示。

## 已确认的需求

- CV 结果:每折指标 + 5 折均值±标准差,同时保留现有 OOF 汇总指标;
- 指标范围:在现有基础上增加 PPV、NPV、F1;
- 小数位:报告与 CSV 数值列统一 3 位小数;**例外:CSV 中 p_value 列保留原始精度**(避免小 p 值被舍入为 0.000 丢失信息);
- p 值展示:p < 0.001 统一显示为 `<0.001`,否则保留 3 位小数;
- `feature_statistics.py` 的统计检验报告(t 检验 / MWU)顺带统一为同样规则。

## 改动设计

### 1. `app/metrics.py`

- `MetricsResult` 增加字段:`ppv`、`npv`、`f1`(默认 0.0);
- `calculate_metrics` 中计算:
  - `ppv = tp / (tp + fp + 1e-16)`
  - `npv = tn / (tn + fn + 1e-16)`
  - `f1 = 2 * ppv * sensitivity / (ppv + sensitivity + 1e-16)`
- 沿用现有 `1e-16` 防除零风格。

### 2. `app/analysis.py`(AnalysisAgent)

- CV 循环内,每折在留出折预测概率上调用 `calculate_metrics(y_val, fold_val_probs)`(每折用各自 Youden 最佳阈值),收集逐折指标;
- 结果字典新增 `cv_metrics`:
  ```python
  {
      "folds": [{"fold": 1, "auc": ..., "accuracy": ..., "sensitivity": ...,
                 "specificity": ..., "ppv": ..., "npv": ..., "f1": ...,
                 "threshold": ...}, ...],
      "mean": {同上指标键},
      "std":  {同上指标键},
  }
  ```
- 现有 OOF 汇总 `metrics` 中补充 `ppv`/`npv`/`f1`(来自 OOF 概率的 `calculate_metrics`),其余字段与语义不变。

### 3. `app/utils.py` — 格式化辅助函数

```python
def fmt_num(x) -> str:      # None/NaN → "-",否则 f"{x:.3f}"
def fmt_p(p) -> str:        # None/NaN → "-";p < 0.001 → "<0.001";否则 f"{p:.3f}"
```

### 4. `app/radiomics_analysis.py`(report.md 链路)

- 「模型性能」节:
  - OOF 汇总表增加 PPV、NPV、F1 行(3 位小数);
  - 新增逐折指标表:每折一行(折号 + 7 项指标 + 阈值),末尾附「均值±标准差」行(格式 `0.888±0.032`,均 3 位小数);
- 「稳定特征与回归系数」表:系数由 `.4f` 改为 3 位小数;p 列用 `fmt_p`;
- `selected_features.csv`:coefficient/odds_ratio/ci_lower/ci_upper 四列四舍五入保留 3 位小数,`p_value` 保留原始精度;
- `case_predictions.csv`:`oof_prob` 保留 3 位小数。

### 5. `app/report.py`(Word 报告链路)

- 「Model Performance」段落增加 PPV/NPV/F1(3 位小数);
- 新增逐折 CV 表格(fold 明细 + mean±std 行);`analysis_result` 缺少 `cv_metrics` 时跳过该表以保持向后兼容;
- 回归表 p-value 用 `fmt_p`,系数相关列统一 3 位小数。

### 6. `app/feature_statistics.py`

- t_pvalue / mw_pvalue 的展示由 `.4f` 改为 `fmt_p` 规则(3 位小数、`<0.001`);该模块其他统计量(t_stat、U 等)同步 3 位小数(若当前已是 3 位则不动)。

### 7. 测试

- `tests/test_metrics.py`(或现有对应文件):新增 PPV/NPV/F1 计算用例;
- 新增 `fmt_num`/`fmt_p` 单元用例(含 `<0.001`、边界 0.001、None);
- `tests/test_analysis.py`:断言结果含 `cv_metrics` 且 folds 数量等于 n_splits、mean/std 键齐全;
- 报告相关测试:断言报告文本含逐折表与 `<0.001` 渲染(构造小 p 值)。

## 兼容性

- `cv_metrics` 为新增键,旧调用方不受影响;
- ReportAgent 对缺失 `cv_metrics` 的输入跳过逐折表,不报错;
- `MetricsResult` 新字段带默认值,旧构造方式不受影响。

## 不做的事

- 不改变 CV 流程本身(折数、阈值策略、特征交集逻辑);
- 不改动 ROC/校准/DCA 曲线绘制;
- CSV 的 p_value 不舍入。
