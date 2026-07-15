# Agent 影像组学工具实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 agent 增加影像组学特征提取工具，支持自动发现 image/mask 路径对、交互确认、批量提取，输出 CSV + h5 到 `./radiomics_features/`。

**架构：** 新增 `app/radiomics_discovery.py` 负责目录扫描与启发式匹配；扩展 `app/feature.py` 的 `FeatureAgent` 增加 h5 输出；在 `app/agent/tools.py` 注册两个新工具 `discover_radiomics_pairs` 和 `extract_radiomics_features`；在 `app/agent/state.py` 与 `app/agent/nodes.py` 中补充中断、确认与执行逻辑。

**Tech Stack:** Python 3.11+, PyRadiomics, h5py, pandas, pytest, LangGraph/LangChain

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `app/radiomics_discovery.py`（新建） | 递归扫描 `images/`、`masks/`，按规则生成高/中/低置信度候选对 |
| `app/feature.py`（修改） | 扩展 `FeatureAgent.run()`，在输出 CSV 的同时输出每对 `.h5` |
| `app/agent/tools.py`（修改） | 注册 `discover_radiomics_pairs`、`extract_radiomics_features` 两个工具 |
| `app/agent/state.py`（修改） | 新增 `pending_radiomics_plan` 与 `pending_radiomics_execution` 状态字段 |
| `app/agent/nodes.py`（修改） | 处理新工具的中断、确认、执行与 ToolMessage 生成 |
| `tests/test_radiomics_discovery.py`（新建） | 覆盖发现与匹配规则 |
| `tests/test_feature_h5.py`（新建） | 覆盖 `FeatureAgent` 的 h5 输出 |
| `tests/test_radiomics_tools.py`（新建） | 覆盖 agent 工具的 pending/执行流程 |

---

## Task 1: 实现路径发现与匹配模块

**Files:**
- Create: `app/radiomics_discovery.py`
- Test: `tests/test_radiomics_discovery.py`

### Step 1.1: 编写测试

```python
# tests/test_radiomics_discovery.py
import pytest
from pathlib import Path
from app.radiomics_discovery import discover_pairs, _match_confidence


def test_high_confidence_exact_match(tmp_path):
    (tmp_path / "images" / "case_001").mkdir(parents=True)
    (tmp_path / "masks" / "case_001").mkdir(parents=True)
    (tmp_path / "images" / "case_001" / "T1.nii.gz").write_text("img")
    (tmp_path / "masks" / "case_001" / "T1.nii.gz").write_text("mask")

    result = discover_pairs(str(tmp_path))
    assert result["success"] is True
    assert len(result["pairs"]["high"]) == 1
    assert result["pairs"]["high"][0]["patient_id"] == "case_001"
    assert result["pairs"]["high"][0]["sequence"] == "T1"


def test_medium_confidence_suffix(tmp_path):
    (tmp_path / "images" / "case_001").mkdir(parents=True)
    (tmp_path / "masks" / "case_001").mkdir(parents=True)
    (tmp_path / "images" / "case_001" / "T1.nii.gz").write_text("img")
    (tmp_path / "masks" / "case_001" / "T1_mask.nii.gz").write_text("mask")

    result = discover_pairs(str(tmp_path))
    assert len(result["pairs"]["medium"]) == 1


def test_medium_confidence_token_intersection(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "masks").mkdir()
    (tmp_path / "images" / "sub-01_T1w.nii.gz").write_text("img")
    (tmp_path / "masks" / "sub-01_seg.nii.gz").write_text("mask")

    result = discover_pairs(str(tmp_path))
    assert len(result["pairs"]["medium"]) == 1
    assert result["pairs"]["medium"][0]["patient_id"] == "sub-01"


def test_low_confidence_multiple_candidates(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "masks").mkdir()
    (tmp_path / "images" / "abc.nii.gz").write_text("img")
    (tmp_path / "masks" / "xyz_mask.nii.gz").write_text("mask1")
    (tmp_path / "masks" / "xyz_seg.nii.gz").write_text("mask2")

    result = discover_pairs(str(tmp_path))
    assert len(result["pairs"]["low"]) == 1
    assert len(result["pairs"]["low"][0]["candidates"]) == 2


def test_missing_images_dir(tmp_path):
    result = discover_pairs(str(tmp_path))
    assert result["success"] is False
    assert "images" in result["message"].lower()
```

### Step 1.2: 运行测试，确认失败

```bash
pytest tests/test_radiomics_discovery.py -v
```

Expected: 5 failures, mostly `ModuleNotFoundError` / function not defined.

### Step 1.3: 实现 `app/radiomics_discovery.py`

```python
# app/radiomics_discovery.py
import os
import re
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional


MASK_SUFFIXES = {"_mask", "_seg", "_label", "_roi"}


def _token_set(name: str) -> set:
    """按下划线或连字符分割文件名并返回非空字段集合。"""
    return set(re.split(r"[_\-]", name)) - {"", "nii", "gz"}


def _strip_mask_suffix(name: str) -> str:
    """去掉常见 mask 后缀。"""
    base = name
    for suffix in MASK_SUFFIXES:
        if base.lower().endswith(suffix.lower()):
            base = base[: -len(suffix)]
    return base


def _match_confidence(
    image_rel: Path,
    mask_rel: Path,
) -> Tuple[str, Optional[str]]:
    """判定 image 与 mask 的匹配置信度。

    返回 (confidence, patient_id_or_none)。
    confidence 取值：high / medium / low。
    """
    # 高置信度：相对路径完全相同
    if image_rel == mask_rel:
        patient_id = _infer_patient_id(image_rel)
        return "high", patient_id

    # 中置信度：去掉 mask 后缀后文件名相同
    image_name = image_rel.stem
    mask_name = mask_rel.stem
    if _strip_mask_suffix(mask_name) == image_name:
        patient_id = _infer_patient_id(image_rel)
        return "medium", patient_id

    # 中置信度：字段交集且能唯一对应
    image_tokens = _token_set(image_name)
    mask_tokens = _token_set(mask_name)
    common = image_tokens & mask_tokens
    if common:
        # 取第一个共同字段作为 patient_id
        patient_id = sorted(common)[0]
        return "medium", patient_id

    return "low", None


def _infer_patient_id(image_rel: Path) -> str:
    """从 image 相对路径推断 patient_id。"""
    parts = image_rel.parts
    if len(parts) > 1:
        return parts[0]
    name = image_rel.stem
    tokens = sorted(_token_set(name))
    return tokens[0] if tokens else name


def _scan_nifti_files(root: Path) -> List[Path]:
    """递归扫描 root 下所有 .nii.gz 文件，返回相对于 root 的路径列表。"""
    if not root.exists():
        return []
    return sorted([
        p.relative_to(root)
        for p in root.rglob("*.nii.gz")
        if p.is_file()
    ])


def discover_pairs(project_path: str) -> Dict[str, Any]:
    """扫描项目 images/ 与 masks/，生成候选 image/mask 对。"""
    root = Path(project_path)
    images_dir = root / "images"
    masks_dir = root / "masks"

    if not images_dir.exists():
        return {"success": False, "message": f"images 目录不存在: {images_dir}"}
    if not masks_dir.exists():
        return {"success": False, "message": f"masks 目录不存在: {masks_dir}"}

    image_files = _scan_nifti_files(images_dir)
    mask_files = _scan_nifti_files(masks_dir)

    high, medium, low = [], [], []
    matched_masks = set()

    for img_rel in image_files:
        best_matches = []
        for mask_rel in mask_files:
            conf, patient_id = _match_confidence(img_rel, mask_rel)
            if conf == "high":
                best_matches = [("high", mask_rel, patient_id)]
                break
            if conf in ("medium", "low"):
                best_matches.append((conf, mask_rel, patient_id))

        # 优先取高置信度，其次中，最后低
        high_matches = [m for m in best_matches if m[0] == "high"]
        medium_matches = [m for m in best_matches if m[0] == "medium"]
        low_matches = [m for m in best_matches if m[0] == "low"]

        if high_matches:
            conf, mask_rel, patient_id = high_matches[0]
            matched_masks.add(mask_rel)
            high.append(_make_pair(img_rel, mask_rel, patient_id, images_dir, masks_dir))
        elif medium_matches:
            # 若中置信度唯一，则直接匹配；否则降为低置信度
            if len(medium_matches) == 1:
                conf, mask_rel, patient_id = medium_matches[0]
                matched_masks.add(mask_rel)
                medium.append(_make_pair(img_rel, mask_rel, patient_id, images_dir, masks_dir))
            else:
                low.append(_make_low_pair(img_rel, [m[1] for m in medium_matches], images_dir, masks_dir))
        elif low_matches:
            low.append(_make_low_pair(img_rel, [m[1] for m in low_matches], images_dir, masks_dir))

    unmatched_images = [
        str(images_dir / p) for p in image_files
        if not any(p == Path(pair["image_path"]).relative_to(images_dir) for pair in high + medium)
    ]
    matched_mask_paths = {Path(pair["mask_path"]).relative_to(masks_dir) for pair in high + medium}
    unmatched_masks = [
        str(masks_dir / p) for p in mask_files if p not in matched_mask_paths
    ]

    return {
        "success": True,
        "images_found": len(image_files),
        "masks_found": len(mask_files),
        "pairs": {"high": high, "medium": medium, "low": low},
        "unmatched_images": unmatched_images,
        "unmatched_masks": unmatched_masks,
    }


def _make_pair(
    img_rel: Path,
    mask_rel: Path,
    patient_id: str,
    images_dir: Path,
    masks_dir: Path,
) -> Dict[str, Any]:
    return {
        "patient_id": patient_id,
        "sequence": img_rel.stem,
        "image_path": str(images_dir / img_rel),
        "mask_path": str(masks_dir / mask_rel),
    }


def _make_low_pair(
    img_rel: Path,
    candidates: List[Path],
    images_dir: Path,
    masks_dir: Path,
) -> Dict[str, Any]:
    return {
        "patient_id": _infer_patient_id(img_rel),
        "sequence": img_rel.stem,
        "image_path": str(images_dir / img_rel),
        "candidates": [str(masks_dir / c) for c in candidates],
    }
```

### Step 1.4: 运行测试，确认通过

```bash
pytest tests/test_radiomics_discovery.py -v
```

Expected: 5 passed.

### Step 1.5: 提交

```bash
git add app/radiomics_discovery.py tests/test_radiomics_discovery.py
git commit -m "feat(radiomics): add directory discovery and image-mask pair matching"
```

---

## Task 2: 扩展 FeatureAgent 输出 h5

**Files:**
- Modify: `app/feature.py`
- Test: `tests/test_feature_h5.py`

### Step 2.1: 编写测试

```python
# tests/test_feature_h5.py
import os
import h5py
import pytest
from unittest.mock import patch
from app.feature import FeatureAgent


@patch("app.feature.cir_get_features")
def test_feature_agent_outputs_h5(mock_extractor, tmp_path):
    mock_extractor.return_value = {"feature_a": 1.0, "feature_b": 2.0}

    pairs = [
        {"patient_id": "case_001", "image_path": str(tmp_path / "img.nii.gz"), "mask_path": str(tmp_path / "mask.nii.gz")}
    ]
    (tmp_path / "img.nii.gz").write_text("img")
    (tmp_path / "mask.nii.gz").write_text("mask")

    agent = FeatureAgent(output_dir=str(tmp_path / "out"))
    result = agent.run(pairs, yaml_path=str(tmp_path / "params.yaml"))

    assert result["success"] is True
    assert os.path.exists(os.path.join(tmp_path / "out", "radiomics_features.csv"))

    h5_path = os.path.join(tmp_path / "out", "h5", "img.h5")
    assert os.path.exists(h5_path)
    with h5py.File(h5_path, "r") as f:
        assert "f_values" in f
        assert f["f_values"].shape[1] == 2
```

注意：需要临时 YAML 文件。在测试 setUp 中创建：

```python
import yaml

@pytest.fixture
def yaml_path(tmp_path):
    path = tmp_path / "params.yaml"
    path.write_text(yaml.safe_dump({"setting": {"label": 1}}))
    return str(path)
```

由于 `FeatureAgent` 会读取 YAML，测试中需确保 YAML 内容合法。更简单的方式是 mock `_get_extractor` 返回 fake extractor：

```python
@patch.object(FeatureAgent, "_get_extractor")
@patch.object(FeatureAgent, "_prepare_yaml", return_value="/tmp/fake.yaml")
def test_feature_agent_outputs_h5(...):
    ...
```

为保持测试简洁，完整测试如下：

```python
# tests/test_feature_h5.py
import os
import h5py
import yaml
import pytest
from unittest.mock import patch
from app.feature import FeatureAgent


@pytest.fixture
def yaml_path(tmp_path):
    p = tmp_path / "params.yaml"
    yaml.safe_dump({"setting": {"label": 1, "binWidth": 25}}, p.open("w"))
    return str(p)


@patch("app.feature.cir_get_features")
def test_feature_agent_outputs_h5(mock_extractor, tmp_path, yaml_path):
    mock_extractor.return_value = {"feature_a": 1.0, "feature_b": 2.0}

    out_dir = tmp_path / "out"
    img = tmp_path / "case_001_T1.nii.gz"
    mask = tmp_path / "case_001_T1_mask.nii.gz"
    img.write_text("img")
    mask.write_text("mask")

    pairs = [
        {"patient_id": "case_001", "image_path": str(img), "mask_path": str(mask)}
    ]

    agent = FeatureAgent(output_dir=str(out_dir))
    result = agent.run(pairs, yaml_path=yaml_path)

    assert result["success"] is True
    assert (out_dir / "radiomics_features.csv").exists()
    assert (out_dir / "h5" / "case_001_T1.h5").exists()

    with h5py.File(out_dir / "h5" / "case_001_T1.h5", "r") as f:
        assert "f_values" in f
        assert f["f_values"].shape == (1, 2)
```

### Step 2.2: 运行测试，确认失败

```bash
pytest tests/test_feature_h5.py -v
```

Expected: FAIL, `h5/case_001_T1.h5` not exists.

### Step 2.3: 修改 `app/feature.py`

在 `FeatureAgent.run()` 中，在保存 CSV 之前/之后为每个成功样本写入 `.h5`。

关键修改点：

1. 导入 `h5py` 和 `numpy`。
2. 在生成 `rows` 后，对每个成功的 pair 写入 `h5/{stem}.h5`。
3. `h5_dir = os.path.join(save_dir, "h5")`。

代码片段（插入到 `df = pd.DataFrame(rows)...` 之前）：

```python
import h5py
import numpy as np

# ... existing code ...

rows = []
failed_ids = []
h5_dir = None
if save_dir:
    h5_dir = os.path.join(save_dir, "h5")
    os.makedirs(h5_dir, exist_ok=True)

for pid, feats, err, img_path in results:
    if err:
        failed_ids.append(pid)
        logger.warning("特征提取失败 %s: %s", pid, err)
    else:
        row = {"patient_id": pid}
        row.update(feats)
        rows.append(row)
        if h5_dir:
            _save_h5(h5_dir, img_path, feats)
```

注意这里 `_extract_single` 返回需要增加 `image_path`。修改 `_extract_single`：

```python
def _extract_single(self, args):
    extractor = self._get_extractor()
    if extractor is None:
        patient_id = args[0]
        return patient_id, None, "cir_get_features 不可用（导入失败）", args[1]

    patient_id, image_path, mask_path, yaml_path = args
    try:
        if not os.path.exists(image_path):
            return patient_id, None, f"影像不存在: {image_path}", image_path
        if not os.path.exists(mask_path):
            return patient_id, None, f"Mask 不存在: {mask_path}", image_path
        feats = extractor(image_path, mask_path, yaml_path)
        return patient_id, feats, None, image_path
    except Exception as e:
        return patient_id, None, str(e), image_path
```

新增辅助函数 `_save_h5`：

```python
def _save_h5(h5_dir: str, image_path: str, feats: Dict[str, float]) -> None:
    """根据原 image 文件名生成 h5 文件。"""
    rel = Path(image_path).name.replace(".nii.gz", "")
    # 若需要保留目录信息，可传入 rel_path；当前按原文件名命名
    h5_name = f"{rel}.h5"
    h5_path = os.path.join(h5_dir, h5_name)
    values = np.array(list(feats.values())).reshape(1, -1)
    with h5py.File(h5_path, "w") as f:
        f.create_dataset("f_values", data=values)
```

由于设计文档要求“按原图像文件名命名”，嵌套结构时目录名也要拼接。更健壮的实现：

```python
def _h5_stem(image_path: str, images_root: Optional[str] = None) -> str:
    path = Path(image_path)
    if images_root:
        rel = path.relative_to(images_root)
        parts = rel.with_suffix("").with_suffix("").parts
    else:
        parts = (path.name.replace(".nii.gz", ""),)
    return "_".join(parts)
```

为简化，先在 `FeatureAgent.run` 中接收可选的 `images_root` 参数，默认从 `pairs` 的 `image_path` 推断共同根目录。若无法推断，则只用文件名。

完整修改后的 `FeatureAgent.run` 开头：

```python
def run(
    self,
    pairs: List[Dict[str, str]],
    yaml_path: str = "",
    n_jobs: int = -1,
    resampled_pixel_spacing: Optional[Tuple[float, float, float]] = None,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
```

保持签名不变，内部推断 `images_root`：

```python
image_paths = [p["image_path"] for p in pairs]
images_root = _common_parent(image_paths)
```

新增 `_common_parent`：

```python
def _common_parent(paths: List[str]) -> Optional[str]:
    if not paths:
        return None
    common = Path(paths[0]).parent
    for p in paths[1:]:
        while not Path(p).is_relative_to(common):
            common = common.parent
            if common == common.parent:
                return None
    return str(common)
```

### Step 2.4: 运行测试，确认通过

```bash
pytest tests/test_feature_h5.py -v
```

Expected: 1 passed.

### Step 2.5: 提交

```bash
git add app/feature.py tests/test_feature_h5.py
git commit -m "feat(feature): output per-case h5 files alongside CSV"
```

---

## Task 3: 注册 Agent 工具

**Files:**
- Modify: `app/agent/tools.py`
- Test: `tests/test_agent_tools.py`（扩展已有测试）

### Step 3.1: 编写测试

在 `tests/test_agent_tools.py` 末尾添加：

```python
def test_discover_radiomics_pairs_tool_exists(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    assert "discover_radiomics_pairs" in tools
    assert "extract_radiomics_features" in tools


def test_discover_radiomics_pairs_returns_pending(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    result = tools["discover_radiomics_pairs"].invoke({})
    data = __import__("json").loads(result)
    assert data["_pending_tool"] == "discover_radiomics_pairs"


def test_extract_radiomics_features_returns_pending(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    pairs = [{"patient_id": "case_001", "image_path": "a.nii.gz", "mask_path": "b.nii.gz"}]
    result = tools["extract_radiomics_features"].invoke({"pairs": pairs})
    data = __import__("json").loads(result)
    assert data["_pending_tool"] == "extract_radiomics_features"
```

### Step 3.2: 运行测试，确认失败

```bash
pytest tests/test_agent_tools.py -v
```

Expected: new 3 tests fail with KeyError.

### Step 3.3: 修改 `app/agent/tools.py`

导入 `discover_pairs`：

```python
from app.radiomics_discovery import discover_pairs
```

在 `build_tools` 中添加两个工具：

```python
    @tool
    def discover_radiomics_pairs() -> str:
        """扫描项目 images/ 与 masks/，自动发现 image/mask 路径对并返回匹配计划。执行前需要用户确认。"""
        result = discover_pairs(project_path)
        return json.dumps({"_pending_tool": "discover_radiomics_pairs", "result": result})

    @tool
    def extract_radiomics_features(pairs: List[Dict[str, str]], yaml_path: str = "") -> str:
        """根据确认后的 image/mask 路径对批量提取影像组学特征，输出 CSV 和 h5。执行前需要用户确认。"""
        if not yaml_path:
            yaml_path = str(Path(project_path) / "Params_labels.yaml")
        meta = {
            "pairs": pairs,
            "yaml_path": yaml_path,
            "output_dir": str(Path(project_path) / "radiomics_features"),
        }
        return json.dumps({"_pending_tool": "extract_radiomics_features", "meta": meta})

    tools["discover_radiomics_pairs"] = discover_radiomics_pairs
    tools["extract_radiomics_features"] = extract_radiomics_features
```

### Step 3.4: 运行测试，确认通过

```bash
pytest tests/test_agent_tools.py -v
```

Expected: all tests pass.

### Step 3.5: 提交

```bash
git add app/agent/tools.py tests/test_agent_tools.py
git commit -m "feat(agent): register radiomics discovery and extraction tools"
```

---

## Task 4: 更新 Agent 状态

**Files:**
- Modify: `app/agent/state.py`

### Step 4.1: 修改状态定义

```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    project_path: str
    base_url: str
    model: str
    api_key: Optional[str]

    interrupt_type: Optional[str]
    pending_plan: Optional[Dict[str, Any]]
    pending_command: Optional[Dict[str, Any]]
    pending_script: Optional[Dict[str, Any]]
    script_risk_level: Optional[str]

    # 新增
    pending_radiomics_plan: Optional[Dict[str, Any]]
    pending_radiomics_execution: Optional[Dict[str, Any]]

    confirmed: Optional[bool]
    tool_outputs: Annotated[list, lambda x, y: (x or []) + y]
    operation_log: Annotated[list, lambda x, y: (x or []) + y]
```

### Step 4.2: 提交

```bash
git add app/agent/state.py
git commit -m "feat(agent): add pending radiomics fields to AgentState"
```

---

## Task 5: 实现中断、确认与执行逻辑

**Files:**
- Modify: `app/agent/nodes.py`
- Test: `tests/test_agent_nodes.py`（扩展已有测试）

### Step 5.1: 编写测试

新建/扩展 `tests/test_radiomics_nodes.py`：

```python
# tests/test_radiomics_nodes.py
import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage, ToolMessage
from app.agent.nodes import process_tool_calls, execute_confirmed
from app.agent.state import AgentState


def test_process_discover_radiomics_pairs(tmp_path):
    state = AgentState(
        messages=[
            AIMessage(content="", tool_calls=[{
                "id": "tc1",
                "name": "discover_radiomics_pairs",
                "args": {}
            }])
        ],
        project_path=str(tmp_path),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        api_key="",
    )
    (tmp_path / "images").mkdir()
    (tmp_path / "masks").mkdir()

    with patch("app.agent.nodes._resolve_api_key", return_value=""), \
         patch("app.agent.nodes.ChatOpenAI") as mock_llm_cls:
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm
        result = process_tool_calls(state)

    assert result["interrupt_type"] == "radiomics_plan"
    assert result["pending_radiomics_plan"]["tool_call_id"] == "tc1"


def test_execute_confirmed_radiomics_plan(tmp_path):
    state = AgentState(
        messages=[],
        project_path=str(tmp_path),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        api_key="",
        interrupt_type="radiomics_plan",
        confirmed=True,
        pending_radiomics_plan={
            "tool_call_id": "tc1",
            "result": {
                "success": True,
                "pairs": {"high": [], "medium": [], "low": []}
            }
        },
    )

    result = execute_confirmed(state)
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], ToolMessage)
    assert result["interrupt_type"] is None
```

### Step 5.2: 运行测试，确认失败

```bash
pytest tests/test_radiomics_nodes.py -v
```

Expected: failures, `radiomics_plan` interrupt type not handled.

### Step 5.3: 修改 `app/agent/nodes.py`

#### 5.3.1 导入 FeatureAgent

```python
from app.feature import FeatureAgent
```

#### 5.3.2 更新 `process_tool_calls`

在 `needs_confirmation` 集合中加入两个新工具：

```python
needs_confirmation = name in {
    "list_directory",
    "find_files",
    "get_file_info",
    "plan_file_operations",
    "discover_radiomics_pairs",
    "extract_radiomics_features",
} or (
    name == "execute_python_script"
    ...
)
```

在确认分支中添加处理：

```python
            elif name == "discover_radiomics_pairs":
                interrupt_type = "radiomics_plan"
                updates["pending_radiomics_plan"] = {"tool_call_id": tool_call_id, **parsed}
            elif name == "extract_radiomics_features":
                interrupt_type = "radiomics_execution"
                updates["pending_radiomics_execution"] = {"tool_call_id": tool_call_id, **parsed["meta"]}
```

#### 5.3.3 更新 `human_review`

返回中保留新的 pending 字段：

```python
    pending_radiomics_plan = state.get("pending_radiomics_plan")
    if "plan" in value and pending_radiomics_plan:
        pending_radiomics_plan = {"tool_call_id": pending_radiomics_plan["tool_call_id"], "plan": value["plan"]}

    return {
        "confirmed": value.get("action") == "confirm",
        "pending_plan": pending_plan,
        "pending_radiomics_plan": pending_radiomics_plan,
        "pending_radiomics_execution": state.get("pending_radiomics_execution"),
    }
```

注意：`human_review` 返回的字典会合并到 state，因此需要保留原有 pending 字段不被清空。

#### 5.3.4 更新 `execute_confirmed`

在开头解析 `pending_radiomics_plan` 和 `pending_radiomics_execution`：

```python
    pending_plan = state.get("pending_plan")
    pending_command = state.get("pending_command")
    pending_script = state.get("pending_script")
    pending_radiomics_plan = state.get("pending_radiomics_plan")
    pending_radiomics_execution = state.get("pending_radiomics_execution")
```

添加对应分支：

```python
    elif itype == "radiomics_plan":
        tool_call_id = (pending_radiomics_plan or {}).get("tool_call_id", "") or _resolve_tool_call_id(state)
        if not pending_radiomics_plan:
            ...  # 返回错误
    elif itype == "radiomics_execution":
        tool_call_id = (pending_radiomics_execution or {}).get("tool_call_id", "") or _resolve_tool_call_id(state)
        if not pending_radiomics_execution:
            ...  # 返回错误
```

在执行分支：

```python
    if itype == "file_plan":
        results = execute_plan(state["pending_plan"]["plan"], state["project_path"])
    elif itype == "system_command":
        results = _run_system_command(state["pending_command"], state["project_path"])
    elif itype == "python_script":
        results = execute_script_if_safe(state["pending_script"], state["project_path"])
    elif itype == "radiomics_plan":
        results = state["pending_radiomics_plan"]["result"]
    elif itype == "radiomics_execution":
        results = _run_radiomics_extraction(state["pending_radiomics_execution"], state["project_path"])
```

#### 5.3.5 新增 `_run_radiomics_extraction`

```python
def _run_radiomics_execution(execution: dict, project_path: str) -> dict:
    pairs = execution.get("pairs", [])
    yaml_path = execution.get("yaml_path") or str(Path(project_path) / "Params_labels.yaml")
    output_dir = execution.get("output_dir") or str(Path(project_path) / "radiomics_features")

    if not pairs:
        return {"error": "没有可提取的路径对", "success": False}
    if not Path(yaml_path).exists():
        return {"error": f"YAML 配置不存在: {yaml_path}", "success": False}

    try:
        agent = FeatureAgent(output_dir=output_dir)
        result = agent.run(pairs, yaml_path=yaml_path)
        return result
    except Exception as e:
        return {"error": str(e), "success": False}
```

#### 5.3.6 更新 `_clear_interrupt`

```python
        "pending_radiomics_plan": None,
        "pending_radiomics_execution": None,
```

### Step 5.4: 运行测试，确认通过

```bash
pytest tests/test_radiomics_nodes.py -v
```

Expected: all tests pass.

### Step 5.5: 提交

```bash
git add app/agent/nodes.py tests/test_radiomics_nodes.py
git commit -m "feat(agent): handle radiomics tool interrupts and execution"
```

---

## Task 6: 端到端集成测试

**Files:**
- Test: `tests/test_radiomics_integration.py`

### Step 6.1: 编写测试

```python
# tests/test_radiomics_integration.py
import json
from pathlib import Path
from unittest.mock import patch
from app.radiomics_discovery import discover_pairs
from app.feature import FeatureAgent


def test_end_to_end_discovery_and_extraction(tmp_path):
    (tmp_path / "images" / "case_001").mkdir(parents=True)
    (tmp_path / "masks" / "case_001").mkdir(parents=True)
    (tmp_path / "images" / "case_001" / "T1.nii.gz").write_text("img")
    (tmp_path / "masks" / "case_001" / "T1.nii.gz").write_text("mask")

    import yaml
    yaml_path = tmp_path / "Params_labels.yaml"
    yaml.safe_dump({"setting": {"label": 1, "binWidth": 25}}, yaml_path.open("w"))

    discovery = discover_pairs(str(tmp_path))
    assert discovery["success"]
    pairs = discovery["pairs"]["high"]

    with patch("app.feature.cir_get_features") as mock_extract:
        mock_extract.return_value = {"original_firstorder_Mean": 1.0}
        agent = FeatureAgent(output_dir=str(tmp_path / "radiomics_features"))
        result = agent.run(pairs, yaml_path=str(yaml_path))

    assert result["success"]
    assert (tmp_path / "radiomics_features" / "radiomics_features.csv").exists()
    assert (tmp_path / "radiomics_features" / "h5" / "case_001_T1.h5").exists()
```

### Step 6.2: 运行测试

```bash
pytest tests/test_radiomics_integration.py -v
```

Expected: 1 passed.

### Step 6.3: 提交

```bash
git add tests/test_radiomics_integration.py
git commit -m "test(radiomics): add end-to-end discovery and extraction test"
```

---

## Task 7: 运行完整测试套件

### Step 7.1: 运行测试

```bash
pytest tests/ -q
```

Expected: all tests pass (or existing failures remain unchanged).

### Step 7.2: 提交（如有必要）

若测试通过，无需额外提交；若有 lint/format 调整：

```bash
git add -A
git commit -m "chore: ensure full test suite passes"
```

---

## 自检清单

1. **Spec coverage:**
   - 自动扫描 `images/`、`masks/` → Task 1
   - 高/中/低置信度匹配 → Task 1
   - 下划线/连字符字段交集 → Task 1 `_token_set`
   - 低置信度用户询问 → Task 5 `radiomics_plan` 中断
   - 批量提取 CSV + h5 → Task 2
   - 输出到 `./radiomics_features/` → Task 2, Task 5
   - 默认使用 `Params_labels.yaml` → Task 3, Task 5
   - 返回结果给 LLM → Task 5 `_run_radiomics_execution`

2. **Placeholder scan:** 无 TBD/TODO，每步均有代码/命令。

3. **Type consistency:**
   - `discover_pairs` 返回结构与设计文档一致。
   - `FeatureAgent.run` 签名未变，新增内部 h5 输出。
   - `AgentState` 新增字段在 `process_tool_calls`、`human_review`、`execute_confirmed`、`_clear_interrupt` 中一致使用。

---

## 执行方式选择

计划已保存到 `docs/superpowers/plans/2026-07-15-agent-radiomics-tool-plan.md`。

**两种执行方式：**

1. **Subagent-Driven（推荐）** — 每个 Task 分配一个子代理，逐步执行并复核
2. **Inline Execution** — 在当前会话中批量执行，关键节点复核

请选择一种方式开始实施。
