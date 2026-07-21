# 影像组学流程重排 + resampledPixelSpacing 参数确认 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 agent 工作流改为"参数确认→提取→临床核对",并新增只读工具 `inspect_image_spacing` 支撑参数确认阶段的 spacing 检测与询问。

**Architecture:** 只改提示词流程(`skills/radiomics-workflow/SKILL.md`)+ 新增独立只读模块 `app/image_spacing.py`,经 tools.py 注册、nodes.py `_run_system_command` 执行的既有 pending 工具模式接入 agent;提取/分析/前端不动。

**Tech Stack:** Python, SimpleITK(只读 NIfTI 头), LangGraph agent, pytest。

参考 spec:`docs/superpowers/specs/2026-07-21-radiomics-workflow-reorder-spacing-design.md`

---

### Task 1: `app/image_spacing.py` 核心模块

**Files:**
- Create: `app/image_spacing.py`
- Test: `tests/test_image_spacing.py`

- [ ] **Step 1: 写失败测试**

```python
import numpy as np
import SimpleITK as sitk

from app.image_spacing import inspect_spacing


def _write_nii(path, spacing, ndim=3):
    shape = (4, 5, 6) if ndim == 3 else (5, 6)
    img = sitk.GetImageFromArray(np.zeros(shape, dtype=np.uint8))
    img.SetSpacing(tuple(float(s) for s in spacing))
    sitk.WriteImage(img, str(path))


def test_scan_images_dir_summary(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    _write_nii(images / "a.nii.gz", (0.5, 0.5, 1.0))
    _write_nii(images / "b.nii.gz", (1.0, 1.0, 2.0))
    result = inspect_spacing(str(tmp_path))
    assert result["success"] is True
    assert result["n_cases"] == 2
    assert result["suggested_spacing"] == [0.75, 0.75, 1.5]
    assert result["summary"]["min"] == [0.5, 0.5, 1.0]
    assert result["summary"]["max"] == [1.0, 1.0, 2.0]
    assert result["failed"] == []
    assert len(result["cases"]) == 2


def test_image_paths_filter_and_relative_display(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    kept = images / "kept.nii.gz"
    _write_nii(kept, (0.4, 0.4, 0.4))
    _write_nii(images / "other.nii.gz", (2.0, 2.0, 2.0))
    result = inspect_spacing(str(tmp_path), image_paths=[str(kept)])
    assert result["n_cases"] == 1
    assert result["cases"][0]["path"] == "images/kept.nii.gz"


def test_unreadable_and_2d_go_to_failed(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "bad.nii.gz").write_bytes(b"not a nifti")
    _write_nii(images / "2d.nii.gz", (1.0, 1.0), ndim=2)
    _write_nii(images / "good.nii.gz", (1.0, 1.0, 1.0))
    result = inspect_spacing(str(tmp_path))
    assert result["success"] is True
    assert result["n_cases"] == 1
    assert len(result["failed"]) == 2


def test_no_images_returns_failure(tmp_path):
    assert inspect_spacing(str(tmp_path))["success"] is False
    (tmp_path / "images").mkdir()
    assert inspect_spacing(str(tmp_path))["success"] is False


def test_cases_truncated_over_50(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    for i in range(55):
        _write_nii(images / f"case_{i:03d}.nii.gz", (1.0, 1.0, 1.0))
    result = inspect_spacing(str(tmp_path))
    assert result["n_cases"] == 55
    assert "cases" not in result
    assert result["cases_truncated"] is True
```

- [ ] **Step 2: 运行确认失败** — `python -m pytest tests/test_image_spacing.py -x -q`,预期 `ModuleNotFoundError: No module named 'app.image_spacing'`。

- [ ] **Step 3: 实现 `app/image_spacing.py`**

```python
"""读取队列影像的像素间距(spacing)分布,为重采样参数确认提供依据。"""

import statistics
from pathlib import Path
from typing import Dict, List, Optional

import SimpleITK as sitk

_CASES_DETAIL_LIMIT = 50


def inspect_spacing(project_path: str, image_paths: Optional[List[str]] = None) -> Dict:
    """统计影像 spacing 分布并给出 resampledPixelSpacing 建议值。

    image_paths 为 None 时扫描项目 images/ 目录下的 .nii.gz;
    传入时必须是项目内的绝对路径(沙箱校验由调用方负责)。
    只读 NIfTI 头信息,不加载像素数据。
    """
    root = Path(project_path)
    if image_paths is None:
        images_dir = root / "images"
        if not images_dir.is_dir():
            return {"success": False, "error": "影像目录不存在: images/"}
        paths = sorted(images_dir.rglob("*.nii.gz"))
    else:
        paths = [Path(p) for p in image_paths]
    if not paths:
        return {"success": False, "error": "未找到任何 .nii.gz 影像"}

    cases = []
    failed = []
    for p in paths:
        rel = _relative_display(root, p)
        try:
            reader = sitk.ImageFileReader()
            reader.SetFileName(str(p))
            reader.ReadImageInformation()
            spacing = tuple(float(s) for s in reader.GetSpacing())
            if len(spacing) != 3:
                raise ValueError(f"非 3D 影像(维度={len(spacing)})")
            cases.append({"path": rel, "spacing": [round(s, 6) for s in spacing]})
        except Exception as e:
            failed.append({"path": rel, "error": str(e)})

    if not cases:
        return {"success": False, "error": "没有可读取的影像", "failed": failed}

    axes = list(zip(*(c["spacing"] for c in cases)))
    summary = {
        "axis_labels": ["x", "y", "z"],
        "median": [round(statistics.median(a), 4) for a in axes],
        "min": [round(min(a), 4) for a in axes],
        "max": [round(max(a), 4) for a in axes],
        "n_distinct": len({tuple(c["spacing"]) for c in cases}),
    }
    result = {
        "success": True,
        "n_cases": len(cases),
        "summary": summary,
        "suggested_spacing": summary["median"],
        "failed": failed,
    }
    if len(cases) <= _CASES_DETAIL_LIMIT:
        result["cases"] = cases
    else:
        result["cases_truncated"] = True
    return result


def _relative_display(root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(p)
```

- [ ] **Step 4: 运行确认通过** — `python -m pytest tests/test_image_spacing.py -q`,预期 5 passed。

### Task 2: tools.py 注册只读工具

**Files:**
- Modify: `app/agent/tools.py`(在 `discover_radiomics_pairs` 工具后新增;注册进只读工具集)
- Test: `tests/test_agent_tools.py`

- [ ] **Step 1: 写失败测试**(追加到 `tests/test_agent_tools.py`)

```python
def test_inspect_image_spacing_registered_in_all_tool_sets(tmp_path):
    fake_llm = MagicMock()
    full = build_tools(str(tmp_path), fake_llm)
    readonly = build_tools(str(tmp_path), fake_llm, readonly=True)
    assert "inspect_image_spacing" in full
    assert "inspect_image_spacing" in readonly


def test_inspect_image_spacing_returns_pending(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    data = json.loads(tools["inspect_image_spacing"].invoke({}))
    assert data["_pending_tool"] == "inspect_image_spacing"
    assert data["args"] == {}
    data = json.loads(tools["inspect_image_spacing"].invoke(
        {"pairs": [{"image_path": "images/a.nii.gz", "mask_path": "masks/a.nii.gz"}]}))
    assert data["args"]["pairs"][0]["image_path"] == "images/a.nii.gz"
```

- [ ] **Step 2: 运行确认失败** — `python -m pytest tests/test_agent_tools.py -k inspect_image_spacing -q`。

- [ ] **Step 3: 实现**(在 `discover_radiomics_pairs` 定义后插入工具定义,并在注册区 `tools["discover_radiomics_pairs"] = ...` 之后加一行注册)

```python
    @tool
    def inspect_image_spacing(pairs: List[Dict[str, str]] = None) -> str:
        """检测队列影像的实际像素间距(spacing),为确认 resampledPixelSpacing 提供依据。
        pairs 可选:与 extract_radiomics_features 相同的配对列表(只读取其中的
        image_path);不传则扫描项目 images/ 目录下的全部 .nii.gz。
        返回各轴 spacing 的中位数/范围/不同取值数、逐例明细(病例数 ≤50 时)、
        建议值与读取失败列表。执行前需要用户确认。"""
        args: Dict[str, Any] = {}
        if pairs:
            args["pairs"] = pairs
        return json.dumps(
            {"_pending_tool": "inspect_image_spacing", "args": args},
            ensure_ascii=False,
        )
```

注册(只读工具集,放在 `if not readonly:` 之前):

```python
    tools["inspect_image_spacing"] = inspect_image_spacing
```

- [ ] **Step 4: 运行确认通过** — `python -m pytest tests/test_agent_tools.py -q`。

### Task 3: nodes.py 接入确认流程与执行分支

**Files:**
- Modify: `app/agent/nodes.py`(`needs_confirmation` 集合、`system_command` 分组集合、`_run_system_command` 新增分支)
- Test: `tests/test_agent_nodes.py`

- [ ] **Step 1: 写失败测试**(追加到 `tests/test_agent_nodes.py`,参照该文件现有 `_run_system_command` 测试的写法)

```python
def test_run_system_command_inspect_image_spacing(tmp_path):
    import numpy as np
    import SimpleITK as sitk
    from app.agent.nodes import _run_system_command

    images = tmp_path / "images"
    images.mkdir()
    img = sitk.GetImageFromArray(np.zeros((4, 5, 6), dtype=np.uint8))
    img.SetSpacing((0.5, 0.5, 1.0))
    sitk.WriteImage(img, str(images / "a.nii.gz"))

    # 扫描模式
    out = _run_system_command(
        {"_pending_tool": "inspect_image_spacing", "args": {}}, str(tmp_path))
    assert out["tool"] == "inspect_image_spacing"
    assert out["result"]["suggested_spacing"] == [0.5, 0.5, 1.0]

    # pairs 模式 + 沙箱越界拒绝
    out = _run_system_command(
        {"_pending_tool": "inspect_image_spacing",
         "args": {"pairs": [{"image_path": "images/a.nii.gz",
                             "mask_path": "masks/a.nii.gz"}]}},
        str(tmp_path))
    assert out["result"]["n_cases"] == 1
    out = _run_system_command(
        {"_pending_tool": "inspect_image_spacing",
         "args": {"pairs": [{"image_path": "../outside.nii.gz"}]}},
        str(tmp_path))
    assert "error" in out
```

- [ ] **Step 2: 运行确认失败** — `python -m pytest tests/test_agent_nodes.py -k inspect_image_spacing -q`。

- [ ] **Step 3: 实现**(三处修改)

`needs_confirmation` 集合(约 nodes.py:308-321)加入 `"inspect_image_spacing"`;`system_command` 分组集合(约 nodes.py:340-341)加入 `"inspect_image_spacing"`;`_run_system_command` 在 `update_yaml` 分支后、`return {"error": f"unknown command {tool}"}` 前加入:

```python
        elif tool == "inspect_image_spacing":
            from app.image_spacing import inspect_spacing
            pairs = args.get("pairs") or []
            image_paths = []
            for pair in pairs:
                rel = pair.get("image_path") if isinstance(pair, dict) else None
                if not rel:
                    return {"error": "pair missing image_path"}
                image_paths.append(str(sandbox.resolve(rel, must_exist=False)))
            result = inspect_spacing(str(sandbox.root), image_paths=image_paths or None)
            return {"tool": tool, "result": result}
```

- [ ] **Step 4: 运行确认通过** — `python -m pytest tests/test_agent_nodes.py -q`。

### Task 4: 重写 `skills/radiomics-workflow/SKILL.md` 流程

**Files:**
- Modify: `skills/radiomics-workflow/SKILL.md`(全文替换,保持英文与 frontmatter 风格)

- [ ] **Step 1: 替换内容**

```markdown
---
name: radiomics-workflow
description: Workflow guidance for radiomics discovery, parameter confirmation, feature extraction, clinical matching, modeling, and reporting. Apply on every main agent model call.
---

# Radiomics Workflow

Reason about a radiomics study as a traceable sequence:

0. When asked to start the analysis, first survey the project with `dispatch_subagent(mode="explore")`: fan out independent read-only subtasks covering discovery candidates, pairing status, extraction parameters, and clinical table structure, and reconcile their conclusions before touching any write or extraction step.
1. Discover image and segmentation candidates and verify patient-level pairing.
2. Confirm extraction parameters before extracting. Feature extraction depends only on images, masks, and the parameter YAML — it does not need clinical data.
   - Run `inspect_image_spacing` on the confirmed pairs and compare the measured spacing distribution with the YAML's current `resampledPixelSpacing`.
   - Always ask the user whether to adjust `resampledPixelSpacing`, reporting the current value, the measured distribution, and the suggested value. Never change it on your own.
   - If the user wants a different value, apply it with `update_yaml` on the project YAML before extraction. Changing the YAML invalidates cached h5 results, so affected cases re-extract automatically.
3. Extract reproducible radiomic features with the project YAML configuration.
4. Inspect the clinical table after extraction and before analysis; identify the patient ID, binary outcome, and requested covariates. Reconcile identifiers and report unmatched or ambiguous cases before analysis.
5. Run the configured feature selection and cross-validated model analysis.
6. Interpret performance, calibration, decision curves, limitations, and generated artifacts without overstating evidence.

Prefer the dedicated discovery, extraction, and analysis tools for these stages. Do not skip a failed prerequisite or manufacture missing measurements. When reusing existing outputs, verify their paths and relevance to the current cohort first.
```

- [ ] **Step 2: 确认没有其他地方引用旧步骤顺序** — `grep -rn "Reconcile identifiers" skills/ app/ docs/AI文件操作需求文档.md`,旧文本只应出现在本文件的 git 历史中。

### Task 5: 全量回归

- [ ] **Step 1:** `python -m pytest tests/ -q`,全部通过。
- [ ] **Step 2:** `python smoke_test.py`(若该脚本为项目既有冒烟入口),确认 agent 图可正常编译。
