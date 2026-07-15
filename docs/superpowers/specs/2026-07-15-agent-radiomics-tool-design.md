# Agent 影像组学特征提取工具设计文档

- 日期：2026-07-15
- 作者：Kimi Code
- 状态：待实现

## 1. 背景与目标

项目已存在基于 PyRadiomics 的影像组学特征提取能力：

- `app/cir_features.py` 提供 `cir_get_features(image, mask, yaml)` 单例提取函数。
- `app/feature.py` 提供 `FeatureAgent`，可批量提取并输出 CSV。
- `reference_code/DONGGUAN_NEW_Radiomic/extract_radiomics.py` 演示了按 `images/<phase>/<case>/<seq>.nii.gz` 与 `masks/<phase>/<case>/<seq>.nii.gz` 结构批量提取并输出 `.h5` 的做法。

本设计目标是为 agent 增加一个**影像组学工具**，使其能够：

1. 自动扫描项目目录，发现 image/mask 路径对；
2. 支持多种目录结构与文件名后缀差异；
3. 对不确定的匹配向用户询问；
4. 用户确认后批量提取特征；
5. 同时输出 CSV 汇总表与每个病例的 `.h5` 文件到 `./radiomics_features/`；
6. 将提取结果返回给 LLM，驱动下一步交互。

## 2. 总体架构

新增两个 agent 工具：

| 工具名 | 作用 | 是否需要确认 |
|---|---|---|
| `discover_radiomics_pairs` | 扫描 `images/` 与 `masks/`，按规则生成高/中/低置信度候选对 | 是（展示匹配计划） |
| `extract_radiomics_features` | 接收确认后的路径对，批量提取并输出 CSV + h5 | 是（展示执行计划） |

数据流：

```
用户: "提取影像组学特征"
    ↓
LLM 调用 discover_radiomics_pairs
    ↓
返回 image 列表、mask 列表、候选对（高/中/低置信度）
    ↓
高置信度对：默认参与提取
中置信度对：展示给用户，默认参与，可取消
低置信度对：逐个询问用户“该 image 对应哪个 mask？”
    ↓
用户确认/修正后，LLM 调用 extract_radiomics_features
    ↓
再次展示执行计划（病例数、输出目录、YAML 路径）
    ↓
用户确认后批量提取
    ↓
输出到 ./radiomics_features/
    ↓
返回结果给 LLM，LLM 提示用户下一步
```

涉及文件：

- `app/agent/tools.py`：注册两个新工具。
- `app/agent/nodes.py`：处理新工具的中断、确认与执行。
- `app/agent/state.py`：新增 pending 字段存放待确认的影像组学计划。
- `app/radiomics_discovery.py`（新建）：目录扫描、启发式匹配、置信度分级。
- `app/feature.py`：扩展 `FeatureAgent.run()`，增加 `.h5` 输出能力。
- `tests/test_radiomics_tools.py`（新建）：覆盖发现、匹配、提取流程的单元测试。

## 3. 路径发现与匹配规则

### 3.1 扫描范围

递归扫描项目根目录下：

- `images/` 中所有 `.nii.gz` 文件
- `masks/` 中所有 `.nii.gz` 文件

若任一目录不存在，工具返回错误，不进入确认流程。

### 3.2 匹配规则

对每个 image 文件，在 masks 中寻找对应文件，按以下优先级判定置信度：

1. **高置信度（high）**
   - image 与 mask 的相对路径完全相同（相对于 `images/` 和 `masks/`）。
   - 例如：`images/case_001/T1.nii.gz` ↔ `masks/case_001/T1.nii.gz`

2. **中置信度（medium）**
   满足以下任一条件：
   - 去掉常见 mask 后缀（`_mask`、`_seg`、`_label`、`_roi`）后，image 与 mask 文件名相同；
   - image 与 mask 文件名按下划线 `_` 或连字符 `-` 分割后，存在非空字段交集，且能唯一对应。
   - 例如：`images/case_001/T1.nii.gz` ↔ `masks/case_001/T1_mask.nii.gz`
   - 例如：`images/sub-01_T1w.nii.gz` ↔ `masks/sub-01_mask.nii.gz`

3. **低置信度（low）**
   - 其余所有情况，需要用户交互确认。

### 3.3 元信息推断

- `patient_id`：优先取 image 相对路径第一级目录名；若无法推断（扁平结构），取文件名中第一个匹配的字段（按 `_`/`-` 分割后的第一个字段）。
- `sequence` / `modality`：取 image 文件名去掉 `.nii.gz` 后的部分。

## 4. 确认与提取流程

### 4.1 `discover_radiomics_pairs` 返回结构

```json
{
  "success": true,
  "images_found": 50,
  "masks_found": 52,
  "pairs": {
    "high": [
      {"patient_id": "case_001", "sequence": "T1", "image_path": "images/case_001/T1.nii.gz", "mask_path": "masks/case_001/T1.nii.gz"}
    ],
    "medium": [
      {"patient_id": "case_002", "sequence": "T1", "image_path": "images/case_002/T1.nii.gz", "mask_path": "masks/case_002/T1_mask.nii.gz"}
    ],
    "low": [
      {"patient_id": "case_003", "sequence": "T2", "image_path": "images/case_003/T2.nii.gz", "candidates": ["masks/case_003/T2_seg.nii.gz", "masks/case_003/T2_roi.nii.gz"]}
    ]
  },
  "unmatched_images": [...],
  "unmatched_masks": [...]
}
```

### 4.2 用户交互策略

- 高置信度对：默认参与提取，在确认计划中列出，用户可取消其中某些对。
- 中置信度对：展示给用户，默认参与，用户可取消。
- 低置信度对：`discover_radiomics_pairs` 返回候选 mask 列表；由 LLM/前端逐个询问用户“`images/case_003/T2.nii.gz` 应该对应哪个 mask？”，用户选择一个候选或跳过。

### 4.3 `extract_radiomics_features` 执行计划

LLM 在拿到用户确认后的路径对列表后，调用 `extract_radiomics_features`，工具再次展示执行计划：

- 待提取病例数
- YAML 配置文件路径（默认项目根目录 `Params_labels.yaml`）
- 输出目录 `./radiomics_features/`
- 预计输出文件：`radiomics_features.csv`、`failed_cases.csv`、`h5/*.h5`

用户确认后批量执行。

### 4.4 批量提取实现

使用 `app.feature.FeatureAgent` 批量提取 CSV，并在循环中为每对额外生成 `.h5` 文件（直接调用 `cir_get_features` 或复用 `FeatureAgent` 的内部提取逻辑）。

```python
# 伪代码
agent = FeatureAgent(output_dir="./radiomics_features")
result = agent.run(confirmed_pairs, yaml_path="./Params_labels.yaml")
# FeatureAgent 内部同时为每对生成 h5/{stem}.h5
```

## 5. 输出格式

所有输出写入项目根目录 `./radiomics_features/`。

| 文件/目录 | 说明 |
|---|---|
| `radiomics_features.csv` | 汇总特征表，列包括 `patient_id`、`sequence`、所有影像组学特征 |
| `failed_cases.csv` | 失败记录，包括 `patient_id`、`image_path`、`mask_path`、`reason` |
| `h5/*.h5` | 每个成功病例的 h5 文件，文件名基于原 image 文件名 |

### h5 命名规则

- 嵌套结构：`images/case_001/T1.nii.gz` → `h5/case_001_T1.h5`
- 扁平结构：`images/case_001_T1.nii.gz` → `h5/case_001_T1.h5`

即保留 image 相对路径中的各级目录名与文件名（去掉 `.nii.gz`），按原顺序用下划线 `_` 连接。例如 `images/phase_A/case_001/T1.nii.gz` → `h5/phase_A_case_001_T1.h5`。

## 6. 错误处理

- **单例失败**：记录到 `failed_cases.csv`，不中断整体流程。
- **YAML 不存在/格式错误**：`extract_radiomics_features` 直接返回错误，不进入确认。
- **`images/` 或 `masks/` 不存在**：`discover_radiomics_pairs` 返回友好错误提示。
- **所有候选对都是低置信度且用户未确认**：返回取消信息，不执行提取。

## 7. 工具返回给 LLM 的摘要

```json
{
  "success": true,
  "message": "特征提取完成: 47/50 成功, 3 失败",
  "feature_path": "./radiomics_features/radiomics_features.csv",
  "failed_path": "./radiomics_features/failed_cases.csv",
  "h5_dir": "./radiomics_features/h5",
  "n_samples": 50,
  "n_success": 47,
  "n_failed": 3,
  "failed_examples": ["case_003_T2", "case_010_T1", "case_021_FLAIR"]
}
```

LLM 收到摘要后，可提示用户下一步，例如：

- “特征提取完成，47/50 成功，失败 3 例。是否查看失败原因？”
- “是否需要基于 `radiomics_features.csv` 继续 LASSO + logistic 分析？”

## 8. 安全与权限

- 所有路径解析通过 `app.agent.safety.Sandbox` 限制在项目目录内。
- `extract_radiomics_features` 属于中风险工具（写文件），需要用户确认后执行。
- 生成的 `.h5` 与 CSV 文件权限与项目其他输出一致。

## 9. 测试策略

新增 `tests/test_radiomics_tools.py`：

- 测试高置信度、中置信度、低置信度匹配规则。
- 测试嵌套结构与扁平结构的路径发现。
- 测试 h5 命名规则。
- 测试 `discover_radiomics_pairs` 返回 pending 待确认。
- 测试 `extract_radiomics_features` 在用户取消时正确返回取消信息。
- 使用临时目录和 mock `cir_get_features` 避免依赖真实影像文件。

## 10. 替代方案

### 方案 B：复用 `execute_python_script`

让 agent 自己生成 Python 脚本完成发现与提取，通过现有 `execute_python_script` 执行。

- 优点：改动最小。
- 缺点：agent 必须每次写对脚本；无法在确认前结构化展示路径对；失败定位困难。

### 方案 C：发现 + 提取两个独立工具

`discover_radiomics_pairs` 只返回候选，`extract_radiomics_features` 接收显式路径对。

- 优点：职责清晰，可支持用户直接传入路径。
- 缺点：对“自动发现后批量提取”场景增加了交互步骤。

最终选择方案 A（本设计），因为它兼顾了批量执行效率、用户体验和可维护性。
