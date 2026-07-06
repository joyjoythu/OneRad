# AutoRadiomics Agent 设计文档（简化版）

> 版本：v1.0  
> 日期：2026-07-06  
> 状态：待实现  
> 基于：开发计划.md + 各 Agent 实现方案 + 用户现有代码（`Classify/`、`DONGGUAN_NEW_Radiomic/`）

---

## 1. 设计决策摘要

| 决策项 | 选择 | 原因 |
|--------|------|------|
| 任务类型 | **仅二分类** | 20 天、4 人团队，生存分析实现复杂且需额外依赖；二分类足够完成赛道 B 核心目标 |
| Agent 数量 | **保留 8 个** | Orchestrator + Discovery + Clinical + Matching + QC + Feature + Analysis + Report |
| LLM 调用点 | **3 处** | Discovery ID 正则推断、Clinical 列名识别、Report 方法学润色；**去掉意图解析 LLM** |
| Discovery LLM | **仅保留 ID 正则推断** | 兜底配对 LLM 去掉，避免 token 和复杂度；ID 推断只在规则失败时触发 |
| LLM 封装 | **LangChain PromptTemplate + 原生 SDK** | 只管理 prompt，调用仍走原生接口，降低学习成本 |
| 特征提取 | **复用 `Atsea_def.cir_get_features()` + YAML 配置** | 用户已有稳定代码，避免重写 |
| 分析建模 | **LASSO + Logistic Regression，5 折 CV** | 复用 `calculate_metrics()`；自带 train/val 分割，避免过拟合 |
| 状态传递 | **统一 plain dict，路径全为字符串** | 消除各 Agent 方案中的 Path/dataclass 不一致 |
| Merge 阶段 | **Orchestrator 内置函数** | 逻辑简单，无需独立 Agent |
| 第一次端到端 | **Day 3 前 stub 跑通** | 提前暴露接口问题 |

---

## 2. 范围

### 2.1 In Scope

- 用户上传影像文件夹 + 临床表格 + 任务描述（描述可忽略，系统直接按二分类处理）
- 自动 Discovery image/mask 配对
- Clinical 表格读取与列名识别（ID、Label、临床特征）
- 影像 ID 与表格 ID 对齐（精确 + 模糊）
- QC：mask 非空、尺寸一致、spacing 一致性、CT/MRI 值域检查、可选 resample
- 影像组学特征提取（复用现有 `cir_get_features`）
- LASSO 特征筛选 + Logistic Regression
- 输出 AUC、Acc、Sen、Spc、OR、95% CI、p 值
- 标准化 Word 报告（方法学、特征表、回归表、性能指标）
- Gradio 前端：上传、进度条、中断/恢复、报告下载
- Docker 一键部署

### 2.2 Out of Scope

- 生存分析（CoxPH）
- 多分类任务
- 多模态融合（PET/CT 融合）
- ICC 稳定性检查
- Deep Learning 特征（CLIP 等）
- 复杂图像预处理（除 resample 外）
- 外部测试集拆分（系统内部 5 折 CV，不提供用户指定 test 集）

---

## 3. 架构

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Gradio    │────▶│ Orchestrator│────▶│  Discovery  │────▶│   Clinical  │
│    UI       │◀────│  (状态机)    │◀────│    Agent    │◀────│    Agent    │
└─────────────┘     └──────┬──────┘     └─────────────┘     └─────────────┘
                           │
                           ▼
    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │ Matching │───▶│   QC     │───▶│ Feature  │───▶│ Analysis │───▶│  Report  │
    │  Agent   │    │  Agent   │    │  Agent   │    │  Agent   │    │  Agent   │
    └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
                                                                           │
                                                                           ▼
                                                                    Word Report
```

### 3.1 文件结构

```
app/
├── __init__.py
├── orchestrator.py      # 状态机 + Merge 函数 + SSE 事件构造
├── llm.py               # LangChain PromptTemplate + 原生 DeepSeek SDK 封装
├── discovery.py         # Discovery Agent（ID 提取、配对）
├── clinical.py          # Clinical Agent + Matching Agent
├── qc.py                # QC Agent
├── feature.py           # Feature Agent（包装 cir_get_features）
├── analysis.py          # Analysis Agent（LASSO + LR）
├── report.py            # Report Agent（Word 生成）
├── ui.py                # Gradio 前端
└── metrics.py           # 从现有分类代码提取的 calculate_metrics 等工具函数

Classify/                # 用户现有分类代码（只读参考）
└── Classify_ALL_clean_v4_clinical_subsets_equal_weight.py

DONGGUAN_NEW_Radiomic/   # 用户现有影像组学代码（只读引用）
├── __init__.py          # 需要添加，使目录成为 Python 包
├── Atsea_def.py
├── Params_labels_qian.yaml
└── extract_radiomics.py

tests/                   # 单元测试 + 冒烟测试
├── test_orchestrator.py
├── test_discovery.py
├── test_clinical.py
├── test_matching.py
├── test_qc.py
├── test_feature.py
├── test_analysis.py
└── test_report.py

main.py                  # CLI 入口
Dockerfile
docker-compose.yml
requirements.txt
README.md
```

### 3.2 分工调整

| 角色 | 负责文件 | 说明 |
|------|----------|------|
| 负责人 | `orchestrator.py`, `llm.py`, `main.py` | 状态机、LLM 封装、接口契约、Code Review |
| 同学 A | `discovery.py`, `qc.py` | 文件扫描、配对、质控 |
| 同学 B | `clinical.py`, `feature.py`, `analysis.py`, `report.py` | 表格、匹配、特征、分析、报告 |
| 同学 C | `ui.py`, `Dockerfile`, `docker-compose.yml` | 前端、部署 |

**同学 B 任务较重**：建议 Feature Agent 仅做薄包装（调用现有 `cir_get_features`），Analysis Agent 复用 `calculate_metrics()`，重点放在数据流衔接而非算法重写。

---

## 4. 统一 State Schema

Orchestrator 维护一个 `state: dict`，所有 Agent 通过 `register_handler` 注册。State 中所有路径为字符串。

```python
state = {
    # === 元数据 ===
    "stage": "DISCOVERY",              # 当前阶段名（字符串）
    "previous_stage": "IDLE",
    "user_request": "预测病理完全缓解",
    "work_dir": "./output",

    # === 配置 ===
    "config": {
        "image_dir": "./data/images",
        "clinical_path": "./data/clinical.xlsx",
        "output_dir": "./output",
        "modality": "CT",              # "CT" | "MRI" | "auto"
        "covariates": ["Age", "Sex"],  # 用户指定协变量
        "skip_stages": [],
        "n_jobs": -1,
        "target_spacing": [1.0, 1.0, 1.0],  # None 表示不强制 resample
        "yaml_path": "./DONGGUAN_NEW_Radiomic/Params_labels_qian.yaml",
    },

    # === Discovery Agent 输出 ===
    "discovery": {
        "success": True,
        "message": "配对完成",
        "pairs": [
            {
                "patient_id": "P001",
                "image_path": ".../P001_image.nii.gz",
                "mask_path": ".../P001_mask.nii.gz",
                "modality": "CT",
            }
        ],
        "unpaired_images": ["..."],
        "unpaired_masks": ["..."],
    },

    # === Clinical Agent 输出 ===
    "clinical": {
        "success": True,
        "message": "列名识别完成",
        "df": pd.DataFrame,            # 原始表格
        "id_col": "PatientID",
        "label_col": "Label",          # 二分类标签列
        "feature_cols": ["Age", "Sex"],
        "id_dtype": "str",
        "n_samples": 120,
    },

    # === Matching Agent 输出 ===
    "matching": {
        "success": True,
        "message": "匹配完成",
        "matched_df": pd.DataFrame,    # 含 patient_id, image_path, mask_path, 临床列
        "matched_ids": ["P001", ...],
        "unmatched_image_ids": [],
        "unmatched_clinical_ids": [],
        "match_method": "exact",
    },

    # === QC Agent 输出 ===
    "qc": {
        "success": True,
        "message": "质检完成",
        "passed_pairs": [...],         # 与 discovery.pairs 同结构
        "failed_checks": [
            {"patient_id": "P003", "reason": "mask 全零", "fail_stage": "mask_empty"}
        ],
        "resampled": False,
        "original_spacings": [...],
    },

    # === Feature Agent 输出 ===
    "feature": {
        "success": True,
        "message": "特征提取完成",
        "feature_df": pd.DataFrame,    # index=patient_id, columns=feature_names
        "feature_names": [...],
        "failed_ids": [],
        "zero_variance_features": [],
        "settings_used": {...},
        "extraction_time_seconds": 45.3,
    },

    # === Merge 输出（Orchestrator 直接写入）===
    "merged": {
        "success": True,
        "message": "合并完成",
        "df": pd.DataFrame,            # 特征 + 临床 + Label
        "n_samples": 100,
        "n_features": 107,
    },

    # === Analysis Agent 输出 ===
    "analysis": {
        "success": True,
        "message": "分析完成",
        "task_type": "binary_classification",
        "selected_features": [...],
        "model_results": {
            "intercept": 0.5,
            "coefficients": {...},
            "odds_ratios": {...},
            "ci_lower": {...},
            "ci_upper": {...},
            "p_values": {...},
        },
        "metrics": {
            "auc": 0.85,
            "auc_ci": [0.78, 0.91],
            "accuracy": 0.80,
            "sensitivity": 0.82,
            "specificity": 0.78,
            "threshold": 0.45,
            "confusion_matrix": [[40, 10], [8, 42]],
        },
        "n_samples": 100,
    },

    # === Report Agent 输出 ===
    "report": {
        "success": True,
        "message": "报告生成完成",
        "report_path": "./output/AutoRadiomics_Report.docx",
    },

    # === 中断/恢复 ===
    "interrupted_at": None,
    "error_log": [],
    "user_decision": None,
}
```

### 4.1 Handler 注册契约

每个 Agent 暴露一个入口函数，签名统一为：

```python
def run_xxx(state: dict) -> dict:
    """
    读取 state["config"] 和上游 state key，返回结果 dict。
    结果必须包含 "success": bool 和 "message": str。
    """
```

Orchestrator 注册：

```python
from app import discovery, clinical, qc, feature, analysis, report

orch.register_handler(PipelineStage.DISCOVERY, discovery.run_discovery)
orch.register_handler(PipelineStage.CLINICAL, clinical.run_clinical)
orch.register_handler(PipelineStage.MATCHING, clinical.run_matching)
orch.register_handler(PipelineStage.QC, qc.run_qc)
orch.register_handler(PipelineStage.FEATURE, feature.run_feature)
orch.register_handler(PipelineStage.ANALYSIS, analysis.run_analysis)
orch.register_handler(PipelineStage.REPORT, report.run_report)
```

---

## 5. 各 Agent 设计

### 5.1 Discovery Agent

**职责**：扫描 `image_dir`，识别 image/mask 文件，按 patient_id 配对。

**输入**：`state["config"]["image_dir"]`

**输出**：写入 `state["discovery"]`

**LLM 使用**：
- 仅在规则引擎无法提取 patient_id 时调用一次 LLM，推断 ID 提取正则
- 去掉兜底配对 LLM

**核心逻辑**：
1. 递归扫描 `.nii.gz`、`.nii`、`.dcm` 等
2. 按 mask 关键词（mask/seg/label/roi）分类
3. 用正则提取 patient_id：
   - 用户自定义正则
   - 纯数字序列
   - 字母+数字组合（P001）
   - 去掉 mask 后缀后的文件名
4. 按 patient_id 1:1 配对；多 mask 时选文件名最相似的
5. 返回配对列表 + 未配对文件

**注意**：如果用户数据是 `phase/case/sequence.nii.gz` 结构，Discovery 应将 `case` 作为 patient_id，`phase` 和 `sequence` 作为可选元数据保留在 pair 中。

### 5.2 Clinical Agent

**职责**：读取 CSV/Excel，调用 LLM 识别 `id_col`、`label_col`、`feature_cols`。

**输入**：`state["config"]["clinical_path"]`、`state["user_request"]`（仅作 hint）

**输出**：写入 `state["clinical"]`

**LLM 调用**：`call_llm_column_identification(prompt)` → JSON

**期望输出**：
```json
{
  "id_col": "PatientID",
  "label_col": "Label",
  "feature_cols": ["Age", "Sex"],
  "reasoning": "..."
}
```

**校验**：
- id_col/label_col/feature_cols 必须存在于表格
- label_col 值域应为 {0, 1}
- feature_cols 不包含 id/label

### 5.3 Matching Agent

**职责**：将 Discovery 的 patient_id 与 Clinical 的 id_col 对齐。

**输入**：`state["discovery"]["pairs"]`、`state["clinical"]`

**输出**：写入 `state["matching"]`

**策略**：
1. 精确匹配（大小写不敏感、去空白、去扩展名）
2. 模糊匹配：difflib.SequenceMatcher，阈值 0.8，贪心策略
3. 无匹配时返回失败，Orchestrator 中断

### 5.4 QC Agent

**职责**：逐对检查 image/mask 质量。

**输入**：`state["matching"]["matched_df"]`、`state["discovery"]["pairs"]`、`state["config"]["target_spacing"]`

**输出**：写入 `state["qc"]`

**检查项**：
| 检查项 | 失败处理 |
|--------|----------|
| 文件存在 | 失败 |
| mask 非空 | 失败 |
| image/mask 尺寸一致 | 失败 |
| spacing 一致 | 不一致时 resample 到 target_spacing 或 image spacing |
| mask 值域（0/正整数） | 失败 |
| CT HU 值域 | 警告 |
| MRI 信号单一 | 失败 |
| NaN/Inf | 失败 |

**Resample**：image 用线性插值，mask 用最近邻，输出到 `./output/qc_resampled/`。

> 原因：image 强度是连续值（HU / MRI 信号），线性插值可保持灰度关系；mask 是离散标签（0/1 或 ROI 编号），若用线性插值会产生 0.3、0.7 等非法值，必须用最近邻保持标签整数性。

### 5.5 Feature Agent

**职责**：调用现有 `cir_get_features` 提取影像组学特征。

**输入**：`state["qc"]["passed_pairs"]`、`state["config"]["yaml_path"]`、`state["config"]["n_jobs"]`

**输出**：写入 `state["feature"]`

**实现**：

```python
from DONGGUAN_NEW_Radiomic.Atsea_def import cir_get_features

def extract_single(patient_id, image_path, mask_path, yaml_path):
    feature_dict = cir_get_features(image_path, mask_path, yaml_path)
    return patient_id, feature_dict
```

**注意**：
- `cir_get_features` 内部使用 PyRadiomics YAML 配置，Feature Agent 不再动态构建 settings
- 多进程并行提取，失败样本记录到 `failed_ids`
- 移除零方差特征
- 输出 DataFrame index 为 patient_id

### 5.6 Merge（Orchestrator 内置）

**职责**：将 `feature_df` 与 `matched_df` 按 patient_id 合并。

**输入**：`state["feature"]`、`state["matching"]`

**输出**：写入 `state["merged"]`

**实现**：

```python
def merge_data(state):
    feature_df = state["feature"]["feature_df"]
    matched_df = state["matching"]["matched_df"]
    merged = matched_df.set_index("patient_id").join(feature_df, how="inner")
    # 重置索引，保留 patient_id 列
    merged = merged.reset_index()
    return {
        "success": True,
        "message": f"合并完成: {len(merged)} 样本, {len(feature_df.columns)} 影像特征",
        "df": merged,
        "n_samples": len(merged),
        "n_features": len(feature_df.columns),
    }
```

### 5.7 Analysis Agent

**职责**：LASSO 筛选 + Logistic Regression，输出 OR/95% CI/p 值/AUC 等。

**输入**：`state["merged"]["df"]`、`state["clinical"]`、`state["config"]["covariates"]`

**输出**：写入 `state["analysis"]`

**算法流程**：
1. 从 `merged.df` 分离：
   - 影像组学特征：列名以 `original_` / `wavelet-` / `log-sigma_` 开头
   - 临床协变量：`config.covariates` 中指定且存在的列
   - Label：`clinical.label_col`
2. 缺失值中位数/众数填充
3. 标准化（StandardScaler）
4. **5 折 Stratified CV**：每折内部独立 LASSO + LR，计算每折验证集概率
5. 聚合各折验证集概率，计算最终 AUC、Acc、Sen、Spc（此即模型性能指标）
6. **最终模型**：在全量数据上拟合 LASSO 选中的特征 + 强制保留的临床协变量，再拟合 LR，输出 OR、95% CI、p 值

> 注：步骤 6 的 LR 系数仅用于解释和报告；性能指标来自步骤 5 的交叉验证，避免过拟合。

**复用现有代码**：
- `calculate_metrics()` 来自 `Classify_ALL_clean_v4_clinical_subsets_equal_weight.py`
- LASSO 路径图、特征权重图可参考现有 `FeatureSelector` 的绘图函数

**注意**：
- 影像组学特征进入 LASSO 筛选
- 用户指定的临床协变量强制保留，不经过 LASSO
- 若 LASSO 未选中任何影像组学特征且未指定协变量，则中断

### 5.8 Report Agent

**职责**：生成学术 Word 报告。

**输入**：`state["analysis"]`、`state["feature"]`、`state["clinical"]`、`state["config"]`

**输出**：写入 `state["report"]`

**LLM 调用**：润色方法学段落（可选，失败降级为模板文本）

**报告章节**：
1. Methodology（LLM 润色）
2. Feature Selection（LASSO 选中特征表）
3. Regression Results（OR / 95% CI / p 值表）
4. Model Performance（AUC、Acc、Sen、Spc）
5. Conclusion

---

## 6. LLM 调用点

### 6.1 Discovery ID 正则推断

**触发条件**：规则引擎提取 patient_id 失败（如所有文件 ID 为空或冲突）

**输入**：采样文件名（≤20 个）

**输出**：`{"pattern": "...", "explanation": "..."}`

**Prompt**：要求只返回 JSON，正则只提取患者 ID。

### 6.2 Clinical 列名识别

**输入**：列名 + 统计摘要 + 用户任务 hint

**输出**：`{"id_col": "...", "label_col": "...", "feature_cols": [...], "reasoning": "..."}`

**Prompt**：要求返回 JSON，明确区分 id/label/feature。

### 6.3 Report 方法学润色

**输入**：模板化方法学文本

**输出**：润色后的学术段落

**Prompt**：要求保留数值、不编造信息、200-400 词。

---

## 7. Orchestrator 状态机

### 7.1 阶段顺序

```
IDLE → DISCOVERY → CLINICAL → MATCHING → QC → FEATURE → MERGE → ANALYSIS → REPORT → COMPLETED
```

### 7.2 中断与恢复

任一 Agent 返回 `success=False` 或抛异常时：
1. 进入 `INTERRUPTED` 状态
2. 通过 SSE 推送错误信息
3. 等待用户决策：`retry` / `skip` / `abort`

| 决策 | 行为 |
|------|------|
| retry | 重试当前阶段 |
| skip | 将当前阶段加入 skip_stages，进入下一阶段 |
| abort | 进入 FAILED 状态 |

### 7.3 特殊检查点

- **ANALYSIS 前**：检查 `merged.n_samples < 30`，若不足则中断
- **FEATURE 后**：若 `failed_ids` 非空但非全部失败，记录 warning，继续
- **REPORT 前**：若 `analysis.success=False` 且未被 skip，中断

---

## 8. 现有代码集成

### 8.1 影像组学特征提取

直接调用 `DONGGUAN_NEW_Radiomic.Atsea_def.cir_get_features`（该目录需添加 `__init__.py`）：

```python
from DONGGUAN_NEW_Radiomic.Atsea_def import cir_get_features

def run_feature(state):
    yaml_path = state["config"]["yaml_path"]
    pairs = state["qc"]["passed_pairs"]
    # 多进程/串行调用 cir_get_features
    ...
```

YAML 配置默认使用 `DONGGUAN_NEW_Radiomic/Params_labels_qian.yaml`。

### 8.2 分类指标计算

`Classify_ALL_clean_v4_clinical_subsets_equal_weight.py` 中的 `calculate_metrics()` 函数逻辑清晰、无重依赖，将其复制/适配到 `app/metrics.py`：

```python
from app.metrics import calculate_metrics

metrics = calculate_metrics(y_true, y_prob)
# metrics.auc, metrics.accuracy, metrics.sensitivity, metrics.specificity, metrics.best_threshold
```

**为什么不直接 import `Classify/...` 文件？**：该文件依赖 `shap`、`torch` 等重型库，直接 import 会拖慢启动并引入未使用的复杂度。只抽取 `calculate_metrics` 即可。

### 8.3 不继承的复杂度

以下现有代码功能本次不纳入：
- CLIP 等深度学习特征
- 多 task（task 0 / task 6）融合
- 多 seed 运行
- 临床指标子集分析（ER/PR/Her2/Ki67）
- SHAP 分析（可作为增强项，但不阻塞主流程）

---

## 9. 测试策略

### 9.1 冒烟测试（Day 3 目标）

使用 mock 数据跑完整流水线，所有 Agent 先返回占位结果：

```python
# tests/test_smoke.py
def test_pipeline_with_mocks():
    orch = Orchestrator(...)
    # 注册 mock handlers
    ...
    for event in orch.run():
        pass
    assert state["stage"] == "COMPLETED"
    assert state["report"]["report_path"].endswith(".docx")
```

### 9.2 单元测试

每个 Agent 至少覆盖：
- 正常输入
- 空输入
- 边界/失败场景

### 9.3 集成测试

使用 3 组真实或合成数据：
1. 二分类 CT
2. 二分类 MRI
3. 纯影像（无临床协变量）

---

## 10. 修订后的 20 天排期

### Week 1（Day 1-7）：骨架 + 端到端 stub

| 天数 | 负责人 | 同学 A | 同学 B | 同学 C |
|------|--------|--------|--------|--------|
| Day 1 | 项目结构、`orchestrator.py` 骨架、`llm.py` | 读现有 `extract_radiomics.py` | 读现有分类代码、整理指标函数 | 学 Gradio |
| Day 2 | 定义统一 state schema、注册 handler 接口 | `discovery.py` 规则引擎 | `clinical.py` 表格读取 + LLM 列名识别 | Gradio 布局 |
| Day 3 | **端到端 stub 跑通**（mock 数据） | `qc.py` 骨架 | `feature.py` 包装 `cir_get_features` | SSE 进度显示 |
| Day 4 | Review A/B 代码、修复接口 | QC 完整检查项 | `analysis.py` LASSO + LR | 中断按钮 |
| Day 5 | 联调 Discovery→QC→Feature | 配合联调 | `report.py` Word 生成 | 报告下载 |
| Day 6 | 联调 Clinical→Matching→Merge→Analysis | 配合联调 | 指标计算对接现有代码 | 前端细节 |
| Day 7 | **Week 1 验收**：真实数据跑通到 Word | — | — | — |

### Week 2（Day 8-14）：真实数据 + 稳定化

- Day 8-10：真实数据端到端测试、修复 bug
- Day 11：CT/MRI 参数通过 YAML 配置化
- Day 12：异常处理（样本不足、全零特征、ID 不匹配）
- Day 13：并行优化、性能测试
- Day 14：**Week 2 验收**：完整流水线稳定输出 Word

### Week 3（Day 15-20）：Docker + 答辩

- Day 15-16：Dockerfile、docker-compose
- Day 17：README、部署验证
- Day 18-19：答辩 PPT、演示视频
- Day 20：最终交付

---

## 11. 风险清单

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| DeepSeek V4 API 未发布/不稳定 | 中 | LLM 调用失败 | 降级到 `deepseek-chat`；列名识别失败时允许用户手动指定 |
| 现有 `cir_get_features` 与 Agent 输入结构不匹配 | 中 | Feature Agent 需大量改造 | Day 3 stub 提前验证接口 |
| PyRadiomics Windows 安装失败 | 中 | 特征提取跑不通 | 统一用 Docker；提前准备 whl |
| 同学 B 任务过重 | 高 | 进度延迟 | Feature 只做薄包装；Analysis 复用现有指标函数 |
| 样本量 < 30 | 中 | ANALYSIS 中断 | 明确提示用户，允许 skip 但报告标注统计效力不足 |
| ID 匹配失败 | 中 | MATCHING 中断 | 精确 + 模糊匹配；失败时展示未匹配 ID |
| 影像/_mask spacing 不一致 | 中 | QC resample 复杂 | 默认以 image spacing 为参考；target_spacing 可选 |
| LLM 返回 JSON 格式错误 | 中 | Clinical Agent 失败 | 带重试 + JSON 解析兜底 |

---

## 12. 默认假设与设计决策

为避免实现阶段反复确认，以下事项按如下默认值执行：

| 事项 | 默认决策 |
|------|----------|
| 多层目录结构 | Discovery 递归扫描所有支持的影像文件；每个 image-mask 文件对视为一个独立样本。若同一患者有多个序列，v1 按文件对分别处理（不入 scope 的序列融合）。patient_id 从文件名提取。 |
| YAML 配置 | 默认使用 `./DONGGUAN_NEW_Radiomic/Params_labels_qian.yaml`。如后续需区分 CT/MRI，通过 `config.yaml_path` 指定不同 YAML 文件，Feature Agent 不自行构建 settings。 |
| 报告语言 | Word 报告正文为英文（学术风格）。Gradio 前端界面为中文。 |
| 临床协变量 | 默认不纳入。用户通过 UI 输入框或 prompt 指定，解析后放入 `config.covariates`。若未指定，Analysis Agent 仅使用影像组学特征。 |

---

## 13. 下一步

1. 负责人/用户确认本设计文档
2. 按设计文档创建 `app/` 骨架和统一接口
3. Day 3 前完成端到端 stub 跑通
4. 逐个 Agent 替换真实实现
