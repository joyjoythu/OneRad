# 影像组学流程重排与 resampledPixelSpacing 参数确认 — 设计文档

日期:2026-07-21
状态:已获用户批准(方案 A)

## 背景与目标

当前 agent 工作流(`skills/radiomics-workflow/SKILL.md`)的顺序是:配对发现 → 临床核对 → 参数确认 → 特征提取 → 分析。但特征提取只依赖影像、掩膜和提取参数,不依赖临床数据;临床核对提前会阻塞提取。

两个改动目标:

1. **流程重排**:参数确认与特征提取提前,临床核对移到提取之后、分析之前。
2. **spacing 参数确认**:参数确认阶段,agent 先检测队列影像的实际 spacing,向用户汇报 YAML 当前 `resampledPixelSpacing` 与实测分布的对比,主动询问是否调整;用户要求调整时用 `update_yaml` 直接修改项目的 `Params_labels.yaml`,再执行提取。

## 新工作流顺序(写入 SKILL.md)

0. 只读探索(`dispatch_subagent(mode="explore")`,可并行覆盖目录/配对/临床表/参数的现状摸底——探索本身是只读的,阶段顺序不受影响)
1. 配对发现与确认(`discover_radiomics_pairs`,用户确认面板可编辑)
2. **参数确认**:调用 `inspect_image_spacing` 检测 spacing → 汇报 YAML 当前值 vs 实测分布 → 询问用户是否调整 `resampledPixelSpacing` → 需要调整则用 `update_yaml` 修改 `Params_labels.yaml`
3. **特征提取**(`extract_radiomics_features`)
4. **临床表核对**(`read_tabular_file` 预览,确认 patient_id / 标签列 / 协变量;报告不匹配或歧义)
5. 分析(`run_radiomics_analysis` 等)
6. 结果解读与报告

要点表述:提取只需影像 + 掩膜 + 参数,不依赖临床数据;临床核对必须在分析前完成。

## 修改 YAML 的缓存语义(为什么直接改文件是对的)

`app/feature.py` 的断点续提签名(`extraction_settings.json`)基于 YAML 内容的 SHA256。`update_yaml` 修改 `Params_labels.yaml` 后签名自动变化,旧 h5 缓存自然失效并重新提取,无需额外处理。同时修改留痕在配置文件中,可追溯、可复现。不采用"提取时临时覆盖"(`_prepare_yaml` 现有能力,仅 CLI 路径使用)。

## 新工具 `inspect_image_spacing`(只读)

### 核心函数:`app/image_spacing.py`

```
inspect_spacing(project_path: str, pairs: list[dict] | None = None) -> dict
```

- `pairs` 可选,结构与提取工具相同(每项含 `image_path`/`mask_path` 相对路径,只用 `image_path`);不传则扫描项目下 `images/` 目录的 `.nii.gz`。
- 用 `sitk.ReadImageInformation`(SimpleITK,pyradiomics 既有依赖)只读 NIfTI 头,不加载像素,大队列开销可忽略。
- 返回字段:
  - `success`
  - `n_cases`
  - `summary`:各轴 spacing 的 median/min/max、distinct spacing 组合数
  - `suggested_spacing`:各轴中位数组成的 `[x, y, z]` 建议值
  - `cases`:逐例明细(`path`、`spacing`),仅当 `n_cases <= 50` 时返回,超出则省略并置 `cases_truncated: true`(防上下文膨胀)
  - `failed`:读头失败的文件及原因列表
- 路径经 `Sandbox` 校验,不得越出项目目录。

### agent 工具注册:`app/agent/tools.py`

- 新增 `@tool inspect_image_spacing(pairs=None)`,返回 pending 命令 `{"_pending_tool": "inspect_image_spacing", "args": {...}}`,与现有只读工具同模式。
- 注册进只读工具集(readonly/explore 子 agent 可用)与完整工具集。

### 执行分支:`app/agent/nodes.py`

- `_run_system_command` 增加 `inspect_image_spacing` 分支,调用 `inspect_spacing` 并返回结果。

## 不改动的部分

- `app/feature.py`、提取/分析执行链路、前端确认面板、临床相关分析输入检查(`inspect_analysis_inputs`)均不动。
- `docs/plans/` 下的旧设计文档不回改(它们是 orchestrator 架构的历史文档)。

## 测试

- 新增 `tests/test_image_spacing.py`:
  - 用 SimpleITK 在临时目录合成不同 spacing 的小 NIfTI,验证汇总统计与建议值;
  - 损坏/非影像文件进入 `failed` 而不中断整体;
  - `pairs` 参数过滤与越界路径拒绝;
  - 大队列(>50)时 `cases` 截断行为。
- 工具层:注册检查(readonly 与完整工具集都包含)、pending 命令结构、`_run_system_command` 分支执行。
- 现有测试不受影响(无接口变更)。

## 风险与边界

- spacing 建议值只是中位数启发式,最终取值由用户决定;SKILL.md 措辞要求 agent 汇报分布并询问,不得自行改 YAML。
- 非 `.nii.gz` 影像(如 `.nii`/`.mha`)本期不支持,与 `discover_pairs` 现有扫描范围保持一致。
