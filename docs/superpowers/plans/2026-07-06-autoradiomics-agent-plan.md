# AutoRadiomics Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一个端到端影像组学分析 Agent 系统：用户上传影像文件夹 + 临床表格，系统自动完成 image/mask 配对、质控、特征提取、LASSO+Logistic Regression 分析，并输出标准化 Word 报告。

**Architecture:** 原生 Python 状态机（Orchestrator）按固定流水线调度 8 个 Agent；Agent 间通过统一 `state: dict` 传递数据；Feature Agent 复用用户现有 `cir_get_features`；Analysis Agent 复用现有 `calculate_metrics`；LLM 仅用于 Discovery ID 推断、Clinical 列名识别、Report 方法学润色。

**Tech Stack:** Python 3.10+, DeepSeek API (OpenAI-compatible), LangChain PromptTemplate, SimpleITK, PyRadiomics, scikit-learn, pandas, python-docx, Gradio, Docker

---

## 文件结构

```
app/
├── __init__.py
├── orchestrator.py      # PipelineStage 枚举 + Orchestrator 类 + merge_data
├── llm.py               # LLMClient + PromptTemplate 管理
├── discovery.py         # DiscoveryAgent
├── clinical.py          # ClinicalAgent + MatchingAgent
├── qc.py                # QCAgent
├── feature.py           # FeatureAgent（包装 cir_get_features）
├── analysis.py          # AnalysisAgent（LASSO + LR）
├── report.py            # ReportAgent（Word 生成）
├── ui.py                # Gradio 前端
└── metrics.py           # 从现有代码提取的 calculate_metrics

Classify/
└── Classify_ALL_clean_v4_clinical_subsets_equal_weight.py

DONGGUAN_NEW_Radiomic/
├── __init__.py
├── Atsea_def.py
├── Params_labels_qian.yaml
└── extract_radiomics.py

tests/
├── conftest.py
├── test_orchestrator.py
├── test_discovery.py
├── test_clinical.py
├── test_matching.py
├── test_qc.py
├── test_feature.py
├── test_analysis.py
└── test_report.py

main.py
Dockerfile
docker-compose.yml
requirements.txt
README.md
```

---

## Phase 1: 项目骨架与统一接口

### Task 1: 创建项目基础结构与 requirements.txt

**Files:**
- Create: `requirements.txt`
- Create: `main.py`
- Create: `app/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: 创建 requirements.txt**

```txt
# Core
numpy>=1.24.0
pandas>=2.0.0
scikit-learn>=1.3.0
scipy>=1.10.0

# Medical imaging
SimpleITK>=2.3.0
pyradiomics>=3.0.1

# LLM
openai>=1.0.0
langchain>=0.2.0
langchain-openai>=0.1.0

# Report & UI
python-docx>=1.1.0
gradio>=4.0.0

# Utils
openpyxl>=3.1.0
h5py>=3.8.0
```

- [ ] **Step 2: 创建 main.py CLI 入口骨架**

```python
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="AutoRadiomics Agent")
    parser.add_argument("--image-dir", required=True)
    parser.add_argument("--clinical", required=True)
    parser.add_argument("--output-dir", default="./output")
    parser.add_argument("--modality", default="auto")
    parser.add_argument("--covariates", default="", help="逗号分隔的协变量列名")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--base-url", default="https://api.deepseek.com/v1")
    parser.add_argument("--model", default="deepseek-chat")
    args = parser.parse_args()

    # Task 18 将在此处实例化 Orchestrator 并运行


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 创建 app/__init__.py 和 tests/conftest.py**

`app/__init__.py` 可为空。

`tests/conftest.py`：
```python
import pytest
import tempfile
import shutil
from pathlib import Path


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d)
```

- [ ] **Step 4: 运行基础导入测试**

Run: `python -c "import app; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add requirements.txt main.py app/__init__.py tests/conftest.py
git commit -m "chore: project scaffold and requirements"
```

---

### Task 2: 实现 PipelineStage 枚举与 Orchestrator 骨架

**Files:**
- Create: `app/orchestrator.py`
- Create: `tests/test_orchestrator.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_orchestrator.py`:
```python
from app.orchestrator import PipelineStage, Orchestrator, get_next_stage


def test_stage_order():
    assert get_next_stage(PipelineStage.DISCOVERY) == PipelineStage.CLINICAL
    assert get_next_stage(PipelineStage.REPORT) == PipelineStage.COMPLETED


def test_orchestrator_init():
    orch = Orchestrator(
        image_dir="./data/images",
        clinical_path="./data/clinical.csv",
    )
    assert orch.state["stage"] == PipelineStage.IDLE
    assert orch.state["config"]["image_dir"] == "./data/images"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_orchestrator.py -v`
Expected: ImportError / function not defined

- [ ] **Step 3: 实现 PipelineStage 和 Orchestrator 骨架**

`app/orchestrator.py`:
```python
from enum import Enum, auto
from typing import Dict, Any, Optional, Callable, Generator


class PipelineStage(Enum):
    IDLE = auto()
    DISCOVERY = auto()
    CLINICAL = auto()
    MATCHING = auto()
    QC = auto()
    FEATURE = auto()
    MERGE = auto()
    ANALYSIS = auto()
    REPORT = auto()
    COMPLETED = auto()
    INTERRUPTED = auto()
    FAILED = auto()


STAGE_ORDER = [
    PipelineStage.DISCOVERY,
    PipelineStage.CLINICAL,
    PipelineStage.MATCHING,
    PipelineStage.QC,
    PipelineStage.FEATURE,
    PipelineStage.MERGE,
    PipelineStage.ANALYSIS,
    PipelineStage.REPORT,
]


def get_next_stage(current: PipelineStage) -> Optional[PipelineStage]:
    try:
        idx = STAGE_ORDER.index(current)
        return STAGE_ORDER[idx + 1] if idx + 1 < len(STAGE_ORDER) else PipelineStage.COMPLETED
    except ValueError:
        return None


class Orchestrator:
    def __init__(
        self,
        image_dir: str,
        clinical_path: str,
        user_request: str = "",
        output_dir: str = "./output",
        modality: str = "auto",
        covariates: Optional[list] = None,
        n_jobs: int = -1,
        target_spacing: Optional[tuple] = None,
        yaml_path: str = "./DONGGUAN_NEW_Radiomic/Params_labels_qian.yaml",
        api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
    ):
        self.state: Dict[str, Any] = {
            "stage": PipelineStage.IDLE,
            "previous_stage": PipelineStage.IDLE,
            "user_request": user_request,
            "config": {
                "image_dir": image_dir,
                "clinical_path": clinical_path,
                "output_dir": output_dir,
                "modality": modality,
                "covariates": covariates or [],
                "skip_stages": [],
                "n_jobs": n_jobs,
                "target_spacing": target_spacing,
                "yaml_path": yaml_path,
                "llm": {
                    "api_key": api_key,
                    "base_url": base_url,
                    "model": model,
                },
            },
            "discovery": None,
            "clinical": None,
            "matching": None,
            "qc": None,
            "feature": None,
            "merged": None,
            "analysis": None,
            "report": None,
            "interrupted_at": None,
            "error_log": [],
            "user_decision": None,
        }
        self._stage_handlers: Dict[PipelineStage, Callable[[Dict], Dict]] = {}
        self._sse_emitter: Optional[Callable[[Dict], None]] = None

    def register_handler(self, stage: PipelineStage, handler: Callable[[Dict], Dict]) -> None:
        if stage in STAGE_ORDER:
            self._stage_handlers[stage] = handler
        else:
            raise ValueError(f"无法注册非流水线阶段: {stage}")

    def set_sse_emitter(self, emitter: Callable[[Dict], None]) -> None:
        self._sse_emitter = emitter

    def _emit(self, event: Dict[str, Any]) -> None:
        if self._sse_emitter:
            self._sse_emitter(event)

    def _make_event(self, event_type: str, message: str, payload: Optional[Dict] = None) -> Dict:
        return {
            "type": event_type,
            "message": message,
            "stage": self.state["stage"].name,
            "payload": payload or {},
        }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add PipelineStage enum and Orchestrator skeleton"
```

---

### Task 3: 实现 Orchestrator 主循环与中断恢复

**Files:**
- Modify: `app/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_orchestrator.py` 追加：
```python
def test_run_with_mock_handlers():
    orch = Orchestrator(image_dir="./data", clinical_path="./data/clinical.csv")

    def mock_discovery(state):
        return {"success": True, "message": "ok"}

    orch.register_handler(PipelineStage.DISCOVERY, mock_discovery)

    events = list(orch.run())
    assert any(e["type"] == "pipeline_start" for e in events)
    assert orch.state["stage"] == PipelineStage.INTERRUPTED  # 后续阶段未注册
```

- [ ] **Step 2: 实现 run()、_run_stage()、resume()**

在 `Orchestrator` 类中添加：

```python
    def run(self) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
        self.state["stage"] = PipelineStage.IDLE
        self._emit(self._make_event("pipeline_start", "流水线启动"))
        current = PipelineStage.DISCOVERY
        return self._continue_from(current)

    def _continue_from(self, stage: PipelineStage) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
        current = stage
        while current is not None and current not in (
            PipelineStage.COMPLETED,
            PipelineStage.FAILED,
        ):
            self.state["stage"] = current

            if current.name in self.state["config"]["skip_stages"]:
                self._emit(self._make_event("stage_skip", f"跳过阶段: {current.name}"))
                current = get_next_stage(current)
                continue

            success, error_msg = self._run_stage(current)

            if not success:
                self.state["interrupted_at"] = current
                self.state["previous_stage"] = current
                self.state["stage"] = PipelineStage.INTERRUPTED
                self.state["error_log"].append(f"[{current.name}] {error_msg}")
                self._emit(self._make_event(
                    "stage_interrupt",
                    f"阶段 {current.name} 中断: {error_msg}",
                    {"error": error_msg, "stage": current.name},
                ))
                return self.state

            current = get_next_stage(current)

        if current == PipelineStage.COMPLETED or current is None:
            self.state["stage"] = PipelineStage.COMPLETED
            self._emit(self._make_event("pipeline_complete", "流水线完成"))
        else:
            self.state["stage"] = PipelineStage.FAILED
            self._emit(self._make_event("pipeline_fail", "流水线终止"))

        return self.state

    def _run_stage(self, stage: PipelineStage) -> tuple[bool, str]:
        handler = self._stage_handlers.get(stage)
        if handler is None:
            return False, f"阶段 {stage.name} 未注册 handler"

        self._emit(self._make_event("stage_start", f"开始: {stage.name}", {"stage": stage.name}))

        try:
            if stage == PipelineStage.ANALYSIS:
                n = self._get_merged_sample_count()
                if n < 30:
                    return False, f"有效样本量不足: 仅 {n} 例，要求 ≥ 30"

            result = handler(self.state)
            if not isinstance(result, dict) or "success" not in result:
                return False, f"阶段 {stage.name} 返回格式错误"

            key = "merged" if stage == PipelineStage.MERGE else stage.name.lower()
            self.state[key] = result

            if not result["success"]:
                return False, result.get("message", "未知错误")

            self._emit(self._make_event(
                "stage_complete",
                f"完成: {stage.name}",
                {"stage": stage.name, "details": result.get("message", "")},
            ))
            return True, ""
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            return False, f"{stage.name} 阶段异常: {e}\n{tb}"

    def _get_merged_sample_count(self) -> int:
        merged = self.state.get("merged")
        if merged and isinstance(merged, dict):
            return merged.get("n_samples", 0)
        qc_passed = self.state.get("qc", {}).get("passed_pairs", [])
        matched_ids = self.state.get("matching", {}).get("matched_ids", [])
        qc_ids = {p["patient_id"] for p in qc_passed}
        return len(set(matched_ids) & qc_ids)

    def resume(self, user_decision: str) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
        if self.state["stage"] != PipelineStage.INTERRUPTED:
            self._emit(self._make_event("error", "resume() 只能在 INTERRUPTED 状态下调用"))
            return self.state

        self.state["user_decision"] = user_decision
        interrupted_stage = self.state.get("interrupted_at")

        if user_decision == "abort":
            self.state["stage"] = PipelineStage.FAILED
            self._emit(self._make_event("pipeline_fail", "用户终止流水线"))
            return self.state

        if user_decision == "skip":
            if interrupted_stage:
                self.state["config"]["skip_stages"].append(interrupted_stage.name)
            next_stage = get_next_stage(interrupted_stage) if interrupted_stage else None
            if next_stage is None:
                self.state["stage"] = PipelineStage.COMPLETED
                self._emit(self._make_event("pipeline_complete", "流水线完成"))
                return self.state
            return self._continue_from(next_stage)

        if user_decision == "retry":
            return self._continue_from(interrupted_stage)

        self._emit(self._make_event("error", f"未知决策: {user_decision}"))
        return self.state
```

- [ ] **Step 3: 运行测试确认通过**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator run/resume loop and stage execution"
```

---

### Task 4: 实现 Merge 函数

**Files:**
- Modify: `app/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_orchestrator.py` 追加：
```python
import pandas as pd


def test_merge_data():
    orch = Orchestrator(image_dir="./data", clinical_path="./data/clinical.csv")
    orch.state["feature"] = {
        "feature_df": pd.DataFrame(
            {"f1": [1.0, 2.0]},
            index=["P001", "P002"],
        )
    }
    orch.state["matching"] = {
        "matched_df": pd.DataFrame({
            "patient_id": ["P001", "P002"],
            "image_path": ["a.nii", "b.nii"],
            "mask_path": ["a_mask.nii", "b_mask.nii"],
            "Label": [0, 1],
        })
    }
    from app.orchestrator import merge_data
    result = merge_data(orch.state)
    assert result["n_samples"] == 2
    assert "f1" in result["df"].columns
    assert "Label" in result["df"].columns
```

- [ ] **Step 2: 实现 merge_data**

`app/orchestrator.py` 添加：
```python
def merge_data(state: Dict[str, Any]) -> Dict[str, Any]:
    feature_df = state["feature"]["feature_df"]
    matched_df = state["matching"]["matched_df"]

    if feature_df is None or feature_df.empty:
        return {"success": False, "message": "特征矩阵为空", "df": None, "n_samples": 0, "n_features": 0}
    if matched_df is None or matched_df.empty:
        return {"success": False, "message": "匹配表格为空", "df": None, "n_samples": 0, "n_features": 0}

    merged = matched_df.set_index("patient_id").join(feature_df, how="inner")
    merged = merged.reset_index()

    return {
        "success": True,
        "message": f"合并完成: {len(merged)} 样本, {len(feature_df.columns)} 影像特征",
        "df": merged,
        "n_samples": len(merged),
        "n_features": len(feature_df.columns),
    }
```

- [ ] **Step 3: 运行测试确认通过**

Run: `pytest tests/test_orchestrator.py::test_merge_data -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add merge_data for feature and clinical tables"
```

---

### Task 5: 实现 LLM 封装

**Files:**
- Create: `app/llm.py`
- Create: `tests/test_llm.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_llm.py`:
```python
from unittest.mock import patch, MagicMock
from app.llm import LLMClient


def test_parse_json_response():
    client = LLMClient(api_key="fake")
    text = '{"id_col": "PatientID", "label_col": "Label", "feature_cols": ["Age"]}'
    result = client._extract_json(text)
    assert result["id_col"] == "PatientID"
```

- [ ] **Step 2: 实现 LLMClient**

`app/llm.py`:
```python
import json
import re
import os
from typing import Optional, Dict, Any, List, Tuple

from langchain.prompts import PromptTemplate
from openai import OpenAI


class LLMClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
    ):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = base_url
        self.model = model
        self.client = None
        if self.api_key:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def call(self, system: str, user: str, temperature: float = 0.1, max_tokens: int = 1500) -> str:
        if not self.client:
            raise RuntimeError("LLMClient 未配置 API key")
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        text = text.strip()

        # 直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Markdown code block
        matches = re.findall(r'```(?:json)?\s*([\s\S]*?)```', text)
        for m in matches:
            try:
                return json.loads(m.strip())
            except json.JSONDecodeError:
                continue

        # 第一个 { 到最后一个 }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                pass

        return None

    def render_prompt(self, template: str, **kwargs) -> str:
        prompt = PromptTemplate.from_template(template)
        return prompt.format(**kwargs)
```

- [ ] **Step 3: 运行测试确认通过**

Run: `pytest tests/test_llm.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/llm.py tests/test_llm.py
git commit -m "feat: add LLMClient with PromptTemplate and JSON extraction"
```

---

## Phase 2: Agent 实现

### Task 6: 实现 Discovery Agent 规则引擎

**Files:**
- Create: `app/discovery.py`
- Create: `tests/test_discovery.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_discovery.py`:
```python
from pathlib import Path
from app.discovery import DiscoveryAgent, extract_patient_id


def test_extract_patient_id():
    assert extract_patient_id("P001_image") == "P001"
    assert extract_patient_id("P001_mask") == "P001"
    assert extract_patient_id("1001") == "1001"


def test_classify_and_pair(tmp_path):
    # 创建临时文件
    (tmp_path / "P001_image.nii.gz").write_text("")
    (tmp_path / "P001_mask.nii.gz").write_text("")
    (tmp_path / "P002_image.nii.gz").write_text("")

    agent = DiscoveryAgent()
    result = agent.run(str(tmp_path))
    assert result["success"] is True
    assert len(result["pairs"]) == 1
    assert result["pairs"][0]["patient_id"] == "P001"
```

- [ ] **Step 2: 实现 DiscoveryAgent 核心**

`app/discovery.py`:
```python
import os
import re
from pathlib import Path
from typing import List, Tuple, Optional


SUPPORTED_EXTENSIONS = (".nii.gz", ".nii", ".nrrd", ".mha", ".mhd", ".dcm", ".img", ".hdr")
MASK_KEYWORDS = ("mask", "seg", "segmentation", "label", "roi", "gt", "annotation", "tumor")


def get_base_name(fpath: Path) -> str:
    name = fpath.name
    if name.lower().endswith(".nii.gz"):
        return name[:-7]
    return fpath.stem


def remove_mask_suffix(name: str) -> str:
    pattern = r'[_\-\.](mask|seg|segmentation|label|roi|gt|annotation|tumor)$'
    return re.sub(pattern, '', name, flags=re.IGNORECASE)


def extract_patient_id(base_name: str, id_pattern: Optional[str] = None) -> str:
    clean = remove_mask_suffix(base_name).strip('_-')
    if id_pattern:
        m = re.search(id_pattern, clean)
        if m:
            return m.group(0)
    num = re.search(r'\b\d{2,}\b', clean)
    if num:
        return num.group(0)
    alphanum = re.search(r'[A-Za-z]+[_\-]?\d+', clean)
    if alphanum:
        return alphanum.group(0)
    return clean or base_name


def infer_modality(base_name: str) -> str:
    name = base_name.lower()
    if any(kw in name for kw in ["ct", "computed"]):
        return "CT"
    if any(kw in name for kw in ["mr", "mri", "t1", "t2", "dwi", "flair", "adc"]):
        return "MRI"
    if "pet" in name:
        return "PET"
    return "UNKNOWN"


class DiscoveryAgent:
    def __init__(self, llm_client=None, id_pattern: Optional[str] = None, recursive: bool = True):
        self.llm_client = llm_client
        self.id_pattern = id_pattern
        self.recursive = recursive

    def run(self, directory: str) -> dict:
        dir_path = Path(directory)
        if not dir_path.exists() or not dir_path.is_dir():
            return {"success": False, "message": f"目录不存在: {directory}", "pairs": []}

        files = self._scan_files(dir_path)
        if not files:
            return {"success": False, "message": "未找到支持的影像文件", "pairs": []}

        images, masks = self._classify_files(files)
        if not images:
            return {"success": False, "message": "未找到 Image 文件", "pairs": []}

        pairs, unpaired_images, unpaired_masks = self._pair_images_masks(images, masks)

        return {
            "success": True,
            "message": f"发现 {len(pairs)} 对配对",
            "pairs": pairs,
            "unpaired_images": unpaired_images,
            "unpaired_masks": unpaired_masks,
        }

    def _scan_files(self, dir_path: Path) -> List[Path]:
        iterator = dir_path.rglob("*") if self.recursive else dir_path.iterdir()
        files = []
        for f in iterator:
            if not f.is_file():
                continue
            s = str(f).lower()
            if s.endswith(".nii.gz"):
                files.append(f)
            elif any(s.endswith(ext) for ext in SUPPORTED_EXTENSIONS if ext != ".nii.gz"):
                files.append(f)
        return sorted(files)

    def _classify_files(self, files: List[Path]) -> Tuple[List[dict], List[dict]]:
        images, masks = [], []
        for f in files:
            base = get_base_name(f)
            name_lower = base.lower()
            is_mask = any(kw in name_lower for kw in MASK_KEYWORDS)
            pid = extract_patient_id(base, self.id_pattern)
            modality = infer_modality(base)
            entry = {
                "file_path": str(f),
                "patient_id": pid,
                "modality": modality,
            }
            if is_mask:
                masks.append(entry)
            else:
                images.append(entry)
        return images, masks

    def _pair_images_masks(self, images: List[dict], masks: List[dict]):
        from difflib import SequenceMatcher
        mask_map = {}
        for m in masks:
            mask_map.setdefault(m["patient_id"], []).append(m)

        pairs = []
        used_image_indices = set()

        for idx, img in enumerate(images):
            pid = img["patient_id"]
            candidates = mask_map.get(pid, [])
            if not candidates:
                continue

            if len(candidates) == 1:
                chosen = candidates[0]
            else:
                best = None
                best_score = -1
                for m in candidates:
                    score = SequenceMatcher(None, get_base_name(Path(img["file_path"])).lower(),
                                            get_base_name(Path(m["file_path"])).lower()).ratio()
                    if score > best_score:
                        best_score = score
                        best = m
                chosen = best

            mask_map[pid].remove(chosen)
            used_image_indices.add(idx)
            pairs.append({
                "patient_id": pid,
                "image_path": img["file_path"],
                "mask_path": chosen["file_path"],
                "modality": img["modality"],
            })

        unpaired_images = [img["file_path"] for i, img in enumerate(images) if i not in used_image_indices]
        unpaired_masks = [m["file_path"] for lst in mask_map.values() for m in lst]
        return pairs, unpaired_images, unpaired_masks
```

- [ ] **Step 3: 运行测试确认通过**

Run: `pytest tests/test_discovery.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/discovery.py tests/test_discovery.py
git commit -m "feat: add DiscoveryAgent rule-based pairing"
```

---

### Task 7: 实现 Discovery Agent 的 LLM ID 正则推断

**Files:**
- Modify: `app/discovery.py`
- Modify: `app/llm.py`
- Modify: `tests/test_discovery.py`

- [ ] **Step 1: 在 llm.py 添加专门 prompt 函数**

`app/llm.py` 添加：
```python
ID_INFERENCE_TEMPLATE = """你是一个医学影像数据命名规范分析专家。
请根据提供的文件名样本，推断患者ID的提取规则，返回一个Python正则表达式字符串。
要求：
1. 正则只提取患者ID部分，不包含模态、序列、mask等后缀
2. 尽可能通用，能覆盖所有样本
3. 只输出纯JSON格式：{{"pattern": "正则表达式字符串", "explanation": "简要说明"}}

文件名样本：
{samples}
"""


def build_id_inference_prompt(filenames: List[str]) -> Tuple[str, str]:
    system = "You are a medical imaging filename analyst. Return only JSON."
    user = ID_INFERENCE_TEMPLATE.format(samples="\n".join(filenames))
    return system, user
```

- [ ] **Step 2: 在 DiscoveryAgent 添加 LLM 推断路径**

`app/discovery.py` 添加：
```python
    def _infer_id_pattern_via_llm(self, files: List[Path]) -> Optional[str]:
        if self.llm_client is None:
            return None
        samples = []
        seen = set()
        for f in files:
            name = get_base_name(f)
            if name not in seen:
                samples.append(name)
                seen.add(name)
            if len(samples) >= 20:
                break
        if len(samples) < 2:
            return None
        from app.llm import build_id_inference_prompt
        system, user = build_id_inference_prompt(samples)
        try:
            response = self.llm_client.call(system, user, temperature=0.1, max_tokens=500)
            parsed = self.llm_client._extract_json(response)
            pattern = parsed.get("pattern", "")
            re.compile(pattern)
            return pattern
        except Exception:
            return None
```

并在 `run()` 中，在 `_classify_files` 之前插入：
```python
        if self.id_pattern is None and self.llm_client is not None:
            inferred = self._infer_id_pattern_via_llm(files)
            if inferred:
                self.id_pattern = inferred
```

- [ ] **Step 3: 添加测试**

`tests/test_discovery.py` 追加：
```python
from unittest.mock import MagicMock


def test_discovery_with_llm_id_inference(tmp_path):
    (tmp_path / "SUB_001_image.nii.gz").write_text("")
    (tmp_path / "SUB_001_mask.nii.gz").write_text("")

    mock_llm = MagicMock()
    mock_llm.call.return_value = '{"pattern": "SUB_\\\\d+", "explanation": "test"}'
    mock_llm._extract_json.return_value = {"pattern": r"SUB_\d+"}

    agent = DiscoveryAgent(llm_client=mock_llm)
    result = agent.run(str(tmp_path))
    assert result["success"] is True
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_discovery.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/discovery.py app/llm.py tests/test_discovery.py
git commit -m "feat: add LLM-based ID pattern inference for Discovery"
```

---

### Task 8: 实现 Clinical Agent

**Files:**
- Create: `app/clinical.py`
- Create: `tests/test_clinical.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_clinical.py`:
```python
import pandas as pd
from app.clinical import ClinicalAgent


def test_clinical_agent_basic():
    df = pd.DataFrame({
        "PatientID": ["P001", "P002"],
        "Age": [50, 60],
        "Sex": ["F", "M"],
        "Label": [0, 1],
    })
    from io import BytesIO
    buf = BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)

    # 使用 mock LLM
    from unittest.mock import MagicMock
    mock_llm = MagicMock()
    mock_llm.call.return_value = '{"id_col": "PatientID", "label_col": "Label", "feature_cols": ["Age", "Sex"]}'
    mock_llm._extract_json.return_value = {"id_col": "PatientID", "label_col": "Label", "feature_cols": ["Age", "Sex"]}

    agent = ClinicalAgent(llm_client=mock_llm)
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        f.write(buf.getvalue())
        path = f.name
    result = agent.run(path)
    os.unlink(path)

    assert result["success"] is True
    assert result["id_col"] == "PatientID"
    assert result["label_col"] == "Label"
```

- [ ] **Step 2: 实现 ClinicalAgent**

`app/clinical.py`:
```python
import os
import json
import re
from typing import Optional, List, Dict, Any

import pandas as pd


class ClinicalAgent:
    SUPPORTED_EXTS = {".csv", ".xlsx", ".xls"}

    def __init__(self, llm_client=None, max_retries: int = 2):
        self.llm_client = llm_client
        self.max_retries = max_retries

    def run(self, clinical_path: str, task_hint: str = "") -> dict:
        if not os.path.exists(clinical_path):
            return {"success": False, "message": f"文件不存在: {clinical_path}"}

        ext = os.path.splitext(clinical_path)[1].lower()
        if ext not in self.SUPPORTED_EXTS:
            return {"success": False, "message": f"不支持的格式: {ext}"}

        try:
            if ext == ".csv":
                try:
                    df = pd.read_csv(clinical_path, encoding="utf-8")
                except UnicodeDecodeError:
                    df = pd.read_csv(clinical_path, encoding="gbk")
            else:
                df = pd.read_excel(clinical_path)
        except Exception as e:
            return {"success": False, "message": f"读取表格失败: {e}"}

        if df.empty or df.shape[1] < 2:
            return {"success": False, "message": "表格为空或列数不足"}

        context = self._build_column_context(df, task_hint)
        parsed = self._call_llm_with_retry(context)
        if isinstance(parsed, dict) and not parsed.get("success", True):
            return parsed

        validated = self._validate_columns(df, parsed)
        if isinstance(validated, dict) and not validated.get("success", True):
            return validated

        id_col = validated["id_col"]
        id_series = df[id_col]
        id_dtype = "int" if pd.api.types.is_integer_dtype(id_series) else "str"

        return {
            "success": True,
            "message": "列名识别完成",
            "df": df,
            "id_col": id_col,
            "label_col": validated.get("label_col"),
            "feature_cols": validated["feature_cols"],
            "id_dtype": id_dtype,
            "n_samples": len(df),
        }

    def _build_column_context(self, df: pd.DataFrame, task_hint: str) -> Dict[str, Any]:
        columns = []
        for col in df.columns:
            s = df[col]
            columns.append({
                "column_name": col,
                "dtype": str(s.dtype),
                "non_null": int(s.notna().sum()),
                "missing_rate": round(1 - s.notna().sum() / len(df), 3),
                "n_unique": int(s.nunique(dropna=False)),
                "samples": ", ".join(s.dropna().head(3).astype(str).tolist()),
            })
        return {
            "n_rows": len(df),
            "n_columns": len(df.columns),
            "task_hint": task_hint or "未提供",
            "columns": columns,
        }

    def _call_llm_with_retry(self, context: Dict[str, Any]) -> Dict[str, Any]:
        if self.llm_client is None:
            return {"success": False, "message": "未配置 LLM，无法自动识别列名"}
        from app.llm import build_column_identification_prompt
        system, user = build_column_identification_prompt(context)
        last_error = None
        for _ in range(self.max_retries + 1):
            try:
                response = self.llm_client.call(system, user, temperature=0.1)
                parsed = self.llm_client._extract_json(response)
                if parsed and {"id_col", "label_col", "feature_cols"}.issubset(parsed.keys()):
                    return parsed
                last_error = "JSON 解析失败或字段缺失"
            except Exception as e:
                last_error = str(e)
        return {"success": False, "message": f"LLM 列名识别失败: {last_error}"}

    def _validate_columns(self, df: pd.DataFrame, parsed: Dict[str, Any]) -> Dict[str, Any]:
        all_cols = set(df.columns)
        id_col = parsed.get("id_col")
        label_col = parsed.get("label_col")
        feature_cols = parsed.get("feature_cols", [])

        if id_col not in all_cols:
            return {"success": False, "message": f"ID 列 '{id_col}' 不存在"}
        if label_col not in all_cols:
            return {"success": False, "message": f"Label 列 '{label_col}' 不存在"}

        if not isinstance(feature_cols, list):
            feature_cols = [feature_cols] if feature_cols else []
        feature_cols = [c for c in feature_cols if c in all_cols]
        special = {id_col, label_col}
        feature_cols = [c for c in feature_cols if c not in special]

        if not feature_cols:
            return {"success": False, "message": "未识别到有效临床特征列"}

        # label 值域检查
        unique_labels = df[label_col].dropna().unique()
        if not set(unique_labels).issubset({0, 1}):
            return {"success": False, "message": f"Label 列值域非 0/1: {unique_labels}"}

        return {
            "success": True,
            "id_col": id_col,
            "label_col": label_col,
            "feature_cols": feature_cols,
        }
```

- [ ] **Step 3: 在 llm.py 添加 Clinical prompt 构建函数**

`app/llm.py` 添加：
```python
COLUMN_IDENTIFICATION_TEMPLATE = """请分析以下临床数据表格，识别 ID 列、二分类标签列和临床特征列。
返回纯 JSON：{{"id_col": "...", "label_col": "...", "feature_cols": ["..."], "reasoning": "..."}}

表格信息：
- 行数: {n_rows}
- 列数: {n_columns}
- 任务描述: {task_hint}

列详情：
{columns}
"""


def _format_columns(columns: List[Dict]) -> str:
    lines = ["| 列名 | 类型 | 非空数 | 缺失率 | 唯一值 | 示例 |"]
    for c in columns:
        lines.append(f"| {c['column_name']} | {c['dtype']} | {c['non_null']} | {c['missing_rate']} | {c['n_unique']} | {c['samples']} |")
    return "\n".join(lines)


def build_column_identification_prompt(context: Dict[str, Any]) -> Tuple[str, str]:
    system = (
        "You are a clinical data analyst for radiomics research. "
        "Return ONLY a JSON object with keys: id_col, label_col, feature_cols, reasoning. "
        "Label_col must be a binary 0/1 outcome. feature_cols must not include id_col or label_col."
    )
    user = COLUMN_IDENTIFICATION_TEMPLATE.format(
        n_rows=context["n_rows"],
        n_columns=context["n_columns"],
        task_hint=context["task_hint"],
        columns=_format_columns(context["columns"]),
    )
    return system, user
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_clinical.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/clinical.py app/llm.py tests/test_clinical.py
git commit -m "feat: add ClinicalAgent for column identification"
```

---

### Task 9: 实现 Matching Agent

**Files:**
- Modify: `app/clinical.py`
- Create: `tests/test_matching.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_matching.py`:
```python
import pandas as pd
from app.clinical import run_matching


def test_run_matching_basic():
    pairs = [
        {"patient_id": "P001", "image_path": "a.nii", "mask_path": "a_mask.nii"},
        {"patient_id": "P002", "image_path": "b.nii", "mask_path": "b_mask.nii"},
    ]
    df = pd.DataFrame({
        "PatientID": ["P001", "P002", "P003"],
        "Age": [50, 60, 70],
        "Label": [0, 1, 0],
    })
    result = run_matching(pairs, df, id_col="PatientID")
    assert result["success"] is True
    assert result["match_stats"]["matched"] == 2
    assert "P003" in result["unmatched_clinical_ids"]
```

- [ ] **Step 2: 实现 run_matching**

`app/clinical.py` 追加：
```python
import difflib


def _normalize_id(id_str: str) -> str:
    if not isinstance(id_str, str):
        id_str = str(id_str)
    s = id_str.strip()
    s = re.sub(r"\.(nii\.gz|nii|dcm|mha|mhd|raw|nrrd)$", "", s, flags=re.IGNORECASE)
    return s.lower()


def run_matching(discovery_pairs: List[dict], clinical_df: pd.DataFrame, id_col: str,
                 fuzzy_threshold: float = 0.8, enable_fuzzy: bool = True) -> dict:
    if not discovery_pairs:
        return {"success": False, "message": "Discovery pairs 为空"}
    if clinical_df is None or clinical_df.empty:
        return {"success": False, "message": "临床表格为空"}
    if id_col not in clinical_df.columns:
        return {"success": False, "message": f"ID 列 '{id_col}' 不存在"}

    image_ids = set()
    for p in discovery_pairs:
        pid = p.get("patient_id")
        if pid is None:
            return {"success": False, "message": "pair 缺少 patient_id"}
        image_ids.add(_normalize_id(pid))

    clinical_ids = set(clinical_df[id_col].astype(str).apply(_normalize_id))

    matched = image_ids & clinical_ids
    unmatched_img = image_ids - matched
    unmatched_cli = clinical_ids - matched

    method = "exact"
    fuzzy_map = {}

    if enable_fuzzy and unmatched_img and unmatched_cli:
        available = list(unmatched_cli)
        for img_id in sorted(unmatched_img):
            best_ratio, best_id = 0.0, None
            for cli_id in available:
                ratio = difflib.SequenceMatcher(None, img_id, cli_id).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_id = cli_id
            if best_id is not None and best_ratio >= fuzzy_threshold:
                fuzzy_map[img_id] = best_id
                available.remove(best_id)
        if fuzzy_map:
            method = "fuzzy"
            matched = matched | set(fuzzy_map.keys())
            unmatched_img = set(unmatched_img) - set(fuzzy_map.keys())
            unmatched_cli = set(unmatched_cli) - set(fuzzy_map.values())

    if not matched:
        return {"success": False, "message": "无任何 ID 匹配成功"}

    # 构建 matched_df
    norm_to_pair = {_normalize_id(p["patient_id"]): p for p in discovery_pairs}
    clinical_df = clinical_df.copy()
    clinical_df["__norm_id__"] = clinical_df[id_col].astype(str).apply(_normalize_id)
    norm_to_original = dict(zip(clinical_df["__norm_id__"], clinical_df[id_col]))

    rows = []
    for norm_id in matched:
        pair = norm_to_pair.get(norm_id)
        if pair is None:
            continue
        target_norm = fuzzy_map.get(norm_id, norm_id)
        original_id = norm_to_original.get(target_norm)
        if original_id is None:
            continue
        row_df = clinical_df[clinical_df[id_col] == original_id]
        if row_df.empty:
            continue
        row = row_df.iloc[0].to_dict()
        row.pop("__norm_id__", None)
        row["patient_id"] = pair["patient_id"]
        row["image_path"] = pair["image_path"]
        row["mask_path"] = pair["mask_path"]
        rows.append(row)

    matched_df = pd.DataFrame(rows)
    matched_df = matched_df.drop_duplicates(subset=["patient_id"], keep="first")

    return {
        "success": True,
        "message": f"匹配完成: {len(matched_df)} 例",
        "matched_df": matched_df,
        "matched_ids": matched_df["patient_id"].tolist(),
        "unmatched_image_ids": sorted(unmatched_img),
        "unmatched_clinical_ids": sorted(unmatched_cli),
        "match_method": method,
        "match_stats": {
            "total_images": len(discovery_pairs),
            "total_clinical": len(clinical_df),
            "matched": len(matched_df),
            "unmatched_images": len(unmatched_img),
            "unmatched_clinical": len(unmatched_cli),
        },
    }
```

- [ ] **Step 3: 运行测试确认通过**

Run: `pytest tests/test_matching.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/clinical.py tests/test_matching.py
git commit -m "feat: add MatchingAgent for ID alignment"
```

---

### Task 10: 实现 QC Agent

**Files:**
- Create: `app/qc.py`
- Create: `tests/test_qc.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_qc.py`:
```python
import pytest
import SimpleITK as sitk
import numpy as np
from pathlib import Path
from app.qc import QCAgent


def test_qc_empty_mask(tmp_path):
    # 创建空 mask
    img = sitk.GetImageFromArray(np.random.randint(0, 100, (10, 10, 10)).astype(np.int16))
    mask = sitk.GetImageFromArray(np.zeros((10, 10, 10), dtype=np.uint8))
    img_path = str(tmp_path / "img.nii.gz")
    mask_path = str(tmp_path / "mask.nii.gz")
    sitk.WriteImage(img, img_path)
    sitk.WriteImage(mask, mask_path)

    pairs = [{"patient_id": "P001", "image_path": img_path, "mask_path": mask_path, "modality": "CT"}]
    agent = QCAgent()
    result = agent.run(pairs)
    assert result["success"] is True
    assert result["passed"] == 0
    assert result["failed"] == 1
    assert result["failed_checks"][0]["fail_stage"] == "mask_empty"
```

- [ ] **Step 2: 实现 QCAgent**

`app/qc.py`:
```python
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

import SimpleITK as sitk
import numpy as np

logger = logging.getLogger(__name__)


class QCAgent:
    def __init__(self, target_spacing: Optional[Tuple[float, float, float]] = None,
                 output_dir: str = "./output/qc_resampled"):
        self.target_spacing = target_spacing
        self.output_dir = Path(output_dir)

    def run(self, pairs: List[Dict[str, str]]) -> Dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        results = []
        for p in pairs:
            results.append(self._check_single(p))

        passed = [r for r in results if r["status"] == "passed"]
        failed = [r for r in results if r["status"] == "failed"]

        passed_pairs = []
        for r in passed:
            passed_pairs.append({
                "patient_id": r["patient_id"],
                "image_path": str(r.get("resampled_image_path", r["image_path"])),
                "mask_path": str(r.get("resampled_mask_path", r["mask_path"])),
                "modality": r["modality"],
            })

        return {
            "success": True,
            "message": f"QC 完成: {len(passed)} 通过, {len(failed)} 失败",
            "passed_pairs": passed_pairs,
            "failed_checks": failed,
            "resampled": any(r.get("resampled", False) for r in passed),
            "original_spacings": [r.get("original_spacing") for r in results],
        }

    def _check_single(self, pair: Dict[str, str]) -> Dict[str, Any]:
        result = {
            "patient_id": pair["patient_id"],
            "image_path": pair["image_path"],
            "mask_path": pair["mask_path"],
            "modality": pair.get("modality", "CT"),
            "status": "passed",
            "messages": [],
            "resampled": False,
        }
        try:
            image = sitk.ReadImage(pair["image_path"])
            mask = sitk.ReadImage(pair["mask_path"])

            result["original_spacing"] = image.GetSpacing()
            result["shape"] = image.GetSize()

            # mask 非空
            mask_arr = sitk.GetArrayFromImage(mask)
            roi = np.count_nonzero(mask_arr > 0)
            if roi == 0:
                return self._fail(result, "mask_empty", "Mask 全零，无 ROI")
            result["roi_voxel_count"] = int(roi)

            # 尺寸一致
            if image.GetSize() != mask.GetSize():
                return self._fail(result, "dimension", f"尺寸不一致: {image.GetSize()} vs {mask.GetSize()}")

            # spacing 对齐
            if image.GetSpacing() != mask.GetSpacing():
                mask = self._resample_to_reference(mask, image, is_mask=True)

            # 目标 spacing resample
            if self.target_spacing and image.GetSpacing() != tuple(self.target_spacing):
                img_out = self.output_dir / f"{pair['patient_id']}_image.nii.gz"
                mask_out = self.output_dir / f"{pair['patient_id']}_mask.nii.gz"
                image = self._resample_to_spacing(image, tuple(self.target_spacing), is_mask=False)
                mask = self._resample_to_spacing(mask, tuple(self.target_spacing), is_mask=True)
                sitk.WriteImage(image, str(img_out))
                sitk.WriteImage(mask, str(mask_out))
                result["resampled_image_path"] = str(img_out)
                result["resampled_mask_path"] = str(mask_out)
                result["resampled"] = True

            # 值域检查
            img_arr = sitk.GetArrayFromImage(image)
            if not np.all(np.isfinite(img_arr)):
                return self._fail(result, "value_range", "影像包含 NaN/Inf")

            if result["modality"].upper() == "CT":
                if img_arr.min() < -1000 or img_arr.max() > 3000:
                    result["messages"].append("CT HU 值域超出常见范围，仅警告")
            elif result["modality"].upper() == "MRI":
                unique_ratio = len(np.unique(img_arr)) / img_arr.size
                if unique_ratio < 0.001:
                    return self._fail(result, "value_range", "MRI 信号过于单一")

            result["messages"].append("全部 QC 检查通过")
            return result
        except Exception as e:
            return self._fail(result, "exception", str(e))

    def _fail(self, result: Dict[str, Any], stage: str, reason: str) -> Dict[str, Any]:
        result["status"] = "failed"
        result["fail_stage"] = stage
        result["fail_reason"] = reason
        result["messages"].append(f"FAIL[{stage}]: {reason}")
        return result

    def _resample_to_spacing(self, image: sitk.Image, target: Tuple[float, float, float], is_mask: bool) -> sitk.Image:
        size = image.GetSize()
        spacing = image.GetSpacing()
        new_size = [max(1, int(round(size[i] * spacing[i] / target[i]))) for i in range(3)]
        interp = sitk.sitkNearestNeighbor if is_mask else sitk.sitkLinear
        resampler = sitk.ResampleImageFilter()
        resampler.SetOutputSpacing(target)
        resampler.SetSize(new_size)
        resampler.SetOutputOrigin(image.GetOrigin())
        resampler.SetOutputDirection(image.GetDirection())
        resampler.SetInterpolator(interp)
        resampler.SetDefaultPixelValue(0)
        return resampler.Execute(image)

    def _resample_to_reference(self, image: sitk.Image, reference: sitk.Image, is_mask: bool) -> sitk.Image:
        interp = sitk.sitkNearestNeighbor if is_mask else sitk.sitkLinear
        resampler = sitk.ResampleImageFilter()
        resampler.SetReferenceImage(reference)
        resampler.SetInterpolator(interp)
        resampler.SetDefaultPixelValue(0)
        return resampler.Execute(image)
```

- [ ] **Step 3: 运行测试确认通过**

Run: `pytest tests/test_qc.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/qc.py tests/test_qc.py
git commit -m "feat: add QCAgent with mask/dimension/spacing/value checks"
```

---

### Task 11: 实现 Feature Agent

**Files:**
- Create: `app/feature.py`
- Create: `tests/test_feature.py`
- Create: `DONGGUAN_NEW_Radiomic/__init__.py`

- [ ] **Step 1: 创建 DONGGUAN_NEW_Radiomic/__init__.py**

Run: `touch DONGGUAN_NEW_Radiomic/__init__.py`

- [ ] **Step 2: 编写失败测试**

`tests/test_feature.py`:
```python
import pytest
import SimpleITK as sitk
import numpy as np
import pandas as pd
from pathlib import Path
from unittest.mock import patch
from app.feature import FeatureAgent


def test_feature_agent_empty_pairs():
    agent = FeatureAgent()
    result = agent.run([])
    assert result["success"] is False
```

- [ ] **Step 3: 实现 FeatureAgent**

`app/feature.py`:
```python
import os
import time
import logging
from typing import List, Dict, Any
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd
import numpy as np

from DONGGUAN_NEW_Radiomic.Atsea_def import cir_get_features

logger = logging.getLogger(__name__)


class FeatureAgent:
    def __init__(self, n_workers: int = -1, timeout_per_case: int = 300):
        import multiprocessing as mp
        self.n_workers = n_workers if n_workers > 0 else max(1, mp.cpu_count() - 1)
        self.timeout_per_case = timeout_per_case

    def run(self, pairs: List[Dict[str, str]], yaml_path: str, n_jobs: int = -1) -> Dict[str, Any]:
        if not pairs:
            return {"success": False, "message": "pairs 为空"}
        if not os.path.exists(yaml_path):
            return {"success": False, "message": f"YAML 配置不存在: {yaml_path}"}

        t0 = time.time()
        n_workers = n_jobs if n_jobs > 0 else self.n_workers

        if n_workers == 1 or len(pairs) == 1:
            results = [self._extract_single((p["patient_id"], p["image_path"], p["mask_path"], yaml_path)) for p in pairs]
        else:
            results = []
            with ProcessPoolExecutor(max_workers=n_workers) as executor:
                futures = {
                    executor.submit(self._extract_single, (p["patient_id"], p["image_path"], p["mask_path"], yaml_path)): p
                    for p in pairs
                }
                for future in as_completed(futures):
                    try:
                        results.append(future.result(timeout=self.timeout_per_case))
                    except Exception as e:
                        p = futures[future]
                        results.append((p["patient_id"], None, str(e)))

        rows = []
        failed_ids = []
        for pid, feats, err in results:
            if err:
                failed_ids.append(pid)
                logger.warning(f"特征提取失败 {pid}: {err}")
            else:
                row = {"patient_id": pid}
                row.update(feats)
                rows.append(row)

        if not rows:
            return {"success": False, "message": "所有样本特征提取均失败"}

        df = pd.DataFrame(rows).set_index("patient_id")
        df = df.apply(pd.to_numeric, errors="coerce")
        nan_cols = df.columns[df.isna().all()].tolist()
        if nan_cols:
            df = df.drop(columns=nan_cols)

        zero_var = [c for c in df.columns if df[c].nunique(dropna=True) <= 1]
        if zero_var:
            df = df.drop(columns=zero_var)

        return {
            "success": True,
            "message": f"特征提取完成: {len(df)}/{len(pairs)} 成功, {len(df.columns)} 特征",
            "feature_df": df,
            "feature_names": df.columns.tolist(),
            "failed_ids": failed_ids,
            "zero_variance_features": zero_var,
            "settings_used": {"yaml_path": yaml_path},
            "extraction_time_seconds": round(time.time() - t0, 2),
        }

    @staticmethod
    def _extract_single(args):
        patient_id, image_path, mask_path, yaml_path = args
        try:
            if not os.path.exists(image_path):
                return patient_id, None, f"影像不存在: {image_path}"
            if not os.path.exists(mask_path):
                return patient_id, None, f"Mask 不存在: {mask_path}"
            feats = cir_get_features(image_path, mask_path, yaml_path)
            return patient_id, feats, None
        except Exception as e:
            return patient_id, None, str(e)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_feature.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/feature.py tests/test_feature.py DONGGUAN_NEW_Radiomic/__init__.py
git commit -m "feat: add FeatureAgent wrapping cir_get_features"
```

---

### Task 12: 实现 metrics.py

**Files:**
- Create: `app/metrics.py`
- Create: `tests/test_metrics.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_metrics.py`:
```python
import numpy as np
from app.metrics import calculate_metrics


def test_calculate_metrics():
    y_true = np.array([0, 0, 1, 1])
    y_prob = np.array([0.1, 0.4, 0.6, 0.9])
    m = calculate_metrics(y_true, y_prob)
    assert m.auc == 1.0
    assert m.accuracy == 1.0
```

- [ ] **Step 2: 复制 calculate_metrics 到 app/metrics.py**

`app/metrics.py`:
```python
from dataclasses import dataclass
from typing import Optional
import numpy as np
from sklearn import metrics


@dataclass
class MetricsResult:
    accuracy: float = 0.0
    sensitivity: float = 0.0
    specificity: float = 0.0
    auc: float = 0.0
    best_threshold: float = 0.5
    tp: int = 0
    tn: int = 0
    fn: int = 0
    fp: int = 0


def calculate_metrics(y_true: np.ndarray, y_prob: np.ndarray, threshold: Optional[float] = None) -> MetricsResult:
    result = MetricsResult()

    if len(np.unique(y_true)) < 2:
        result.auc = 0.0
    else:
        result.auc = metrics.roc_auc_score(y_true, y_prob)

    fpr, tpr, thresholds = metrics.roc_curve(y_true, y_prob)
    youden_index = tpr + (1 - fpr)
    result.best_threshold = thresholds[np.argmax(youden_index)]

    if result.best_threshold > 1:
        result.best_threshold = 0.5
    if threshold is not None:
        result.best_threshold = threshold

    y_pred = (y_prob >= result.best_threshold).astype(int)

    result.tp = int(np.sum((y_true == 1) & (y_pred == 1)))
    result.tn = int(np.sum((y_true == 0) & (y_pred == 0)))
    result.fp = int(np.sum((y_true == 0) & (y_pred == 1)))
    result.fn = int(np.sum((y_true == 1) & (y_pred == 0)))

    result.sensitivity = result.tp / (result.tp + result.fn + 1e-16)
    result.specificity = result.tn / (result.tn + result.fp + 1e-16)
    result.accuracy = (result.tp + result.tn) / (result.tp + result.tn + result.fp + result.fn + 1e-16)

    return result
```

- [ ] **Step 3: 运行测试确认通过**

Run: `pytest tests/test_metrics.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/metrics.py tests/test_metrics.py
git commit -m "feat: add calculate_metrics from existing classify code"
```

---

### Task 13: 实现 Analysis Agent

**Files:**
- Create: `app/analysis.py`
- Create: `tests/test_analysis.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_analysis.py`:
```python
import pandas as pd
import numpy as np
from app.analysis import AnalysisAgent


def test_analysis_agent_basic():
    np.random.seed(42)
    n = 50
    df = pd.DataFrame({
        "patient_id": [f"P{i:03d}" for i in range(n)],
        "Label": np.random.randint(0, 2, n),
    })
    for i in range(10):
        df[f"original_feature_{i}"] = np.random.randn(n)

    agent = AnalysisAgent(covariates=[])
    result = agent.run(df, label_col="Label")
    assert result["success"] is True
    assert "auc" in result["metrics"]
    assert "odds_ratios" in result["model_results"]
```

- [ ] **Step 2: 实现 AnalysisAgent**

`app/analysis.py`:
```python
import logging
import os
from typing import List, Dict, Any, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, LassoCV
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedKFold
from scipy import stats

from app.metrics import calculate_metrics


def bootstrap_auc_ci(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_bootstrap: int = 1000,
    confidence: float = 0.95,
    random_state: int = 42,
) -> List[float]:
    rng = np.random.RandomState(random_state)
    scores = []
    for _ in range(n_bootstrap):
        idx = rng.randint(0, len(y_true), len(y_true))
        if len(np.unique(y_true[idx])) < 2:
            continue
        scores.append(metrics.roc_auc_score(y_true[idx], y_prob[idx]))
    alpha = 1 - confidence
    return [float(np.percentile(scores, alpha / 2 * 100)), float(np.percentile(scores, (1 - alpha / 2) * 100))]


logger = logging.getLogger(__name__)


class AnalysisAgent:
    def __init__(self, covariates: Optional[List[str]] = None, n_splits: int = 5,
                 random_state: int = 42, output_dir: Optional[str] = None):
        self.covariates = covariates or []
        self.n_splits = n_splits
        self.random_state = random_state
        self.output_dir = output_dir

    def run(self, merged_df: pd.DataFrame, label_col: str,
            output_dir: Optional[str] = None) -> Dict[str, Any]:
        if merged_df is None or merged_df.empty:
            return {"success": False, "message": "merged_df 为空"}
        if label_col not in merged_df.columns:
            return {"success": False, "message": f"Label 列 '{label_col}' 不存在"}

        self.output_dir = output_dir or self.output_dir

        y = merged_df[label_col].values.astype(int)
        if not set(np.unique(y)).issubset({0, 1}):
            return {"success": False, "message": f"Label 值域非 0/1: {np.unique(y)}"}

        radiomic_cols = [c for c in merged_df.columns
                         if any(c.startswith(p) for p in ["original_", "wavelet-", "log-sigma_"])]
        clinical_covs = [c for c in self.covariates if c in merged_df.columns]
        feature_cols = radiomic_cols + clinical_covs

        if not feature_cols:
            return {"success": False, "message": "未找到可用特征列"}

        X_raw = merged_df[feature_cols].copy()
        # 缺失值填充
        for col in X_raw.columns:
            if pd.api.types.is_numeric_dtype(X_raw[col]):
                X_raw[col] = X_raw[col].fillna(X_raw[col].median())
            else:
                X_raw[col] = X_raw[col].fillna(X_raw[col].mode()[0] if not X_raw[col].mode().empty else "Unknown")

        X = X_raw.values.astype(float)

        # 5 折 CV
        skf = StratifiedKFold(n_splits=self.n_splits, shuffle=True, random_state=self.random_state)
        val_probs = np.zeros(len(y))
        val_labels = np.zeros(len(y))
        fold_selected_features = []
        plot_paths = []

        for fold_idx, (train_idx, val_idx) in enumerate(skf.split(X, y)):
            X_train, X_val = X[train_idx], X[val_idx]
            y_train, y_val = y[train_idx], y[val_idx]

            scaler = StandardScaler()
            X_train_s = scaler.fit_transform(X_train)
            X_val_s = scaler.transform(X_val)

            # LASSO 只在影像组学特征上
            if len(radiomic_cols) > 0:
                X_train_radio = X_train_s[:, :len(radiomic_cols)]
                lasso = LassoCV(cv=3, random_state=self.random_state, max_iter=10000).fit(X_train_radio, y_train)
                radio_mask = np.abs(lasso.coef_) > 1e-6

                out_dir = self.output_dir or output_dir
                if out_dir:
                    os.makedirs(out_dir, exist_ok=True)
                    plot_path = os.path.join(out_dir, f"lasso_path_fold{fold_idx}.png")
                    plt.figure()
                    plt.semilogx(lasso.alphas_, lasso.coef_.T)
                    plt.axvline(lasso.alpha_, color="black", linestyle="--")
                    plt.xlabel("Alpha")
                    plt.ylabel("Coefficient")
                    plt.title(f"LASSO Path - Fold {fold_idx + 1}")
                    plt.savefig(plot_path)
                    plt.close()
                    plot_paths.append(plot_path)
            else:
                radio_mask = np.zeros(len(radiomic_cols), dtype=bool)

            # 保留临床协变量
            clinical_mask = np.ones(len(clinical_covs), dtype=bool) if clinical_covs else np.zeros(0, dtype=bool)
            mask = np.concatenate([radio_mask, clinical_mask])

            if not np.any(mask):
                return {"success": False, "message": "LASSO 未选中任何特征且未指定协变量"}

            fold_selected_features.append(set(np.array(feature_cols)[mask]))

            X_train_sel = X_train_s[:, mask]
            X_val_sel = X_val_s[:, mask]

            lr = LogisticRegression(max_iter=10000, random_state=self.random_state)
            lr.fit(X_train_sel, y_train)
            val_probs[val_idx] = lr.predict_proba(X_val_sel)[:, 1]
            val_labels[val_idx] = y_val

        # 用稳定出现的特征作为最终选中特征
        selected_features = list(set.intersection(*fold_selected_features) if fold_selected_features else set())
        if not selected_features and clinical_covs:
            selected_features = clinical_covs.copy()

        # 最终全量模型
        scaler_final = StandardScaler()
        X_s = scaler_final.fit_transform(X)
        final_mask = np.array([c in selected_features for c in feature_cols])
        X_final = X_s[:, final_mask]

        final_lr = LogisticRegression(max_iter=10000, random_state=self.random_state)
        final_lr.fit(X_final, y)

        # 计算 OR / CI / p
        coefs = final_lr.coef_[0]
        intercept = final_lr.intercept_[0]
        final_feature_names = [c for c in feature_cols if c in selected_features]

        try:
            X_const = np.column_stack([np.ones(X_final.shape[0]), X_final])
            pred_probs = final_lr.predict_proba(X_final)[:, 1]
            W = np.diag(pred_probs * (1 - pred_probs))
            cov_matrix = np.linalg.inv(X_const.T @ W @ X_const)
            se = np.sqrt(np.diag(cov_matrix))[1:]
        except Exception:
            se = np.zeros(len(coefs))

        model_results = {
            "intercept": float(intercept),
            "coefficients": {},
            "odds_ratios": {},
            "ci_lower": {},
            "ci_upper": {},
            "p_values": {},
        }
        for i, feat in enumerate(final_feature_names):
            coef = coefs[i]
            or_val = np.exp(coef)
            model_results["coefficients"][feat] = float(coef)
            model_results["odds_ratios"][feat] = float(or_val)
            if i < len(se) and se[i] > 0:
                z = coef / se[i]
                p = 2 * (1 - stats.norm.cdf(abs(z)))
                ci_lo = np.exp(coef - 1.96 * se[i])
                ci_hi = np.exp(coef + 1.96 * se[i])
            else:
                p = 1.0
                ci_lo = ci_hi = np.nan
            model_results["p_values"][feat] = float(p)
            model_results["ci_lower"][feat] = float(ci_lo) if not np.isnan(ci_lo) else None
            model_results["ci_upper"][feat] = float(ci_hi) if not np.isnan(ci_hi) else None

        metrics_result = calculate_metrics(val_labels, val_probs)

        return {
            "success": True,
            "message": "分析完成",
            "task_type": "binary_classification",
            "selected_features": selected_features,
            "model_results": model_results,
            "metrics": {
                "auc": float(metrics_result.auc),
                "auc_ci": bootstrap_auc_ci(val_labels, val_probs),
                "accuracy": float(metrics_result.accuracy),
                "sensitivity": float(metrics_result.sensitivity),
                "specificity": float(metrics_result.specificity),
                "threshold": float(metrics_result.best_threshold),
                "confusion_matrix": [[int(metrics_result.tn), int(metrics_result.fp)],
                                      [int(metrics_result.fn), int(metrics_result.tp)]],
            },
            "n_samples": len(y),
            "plot_paths": plot_paths,
        }
```

- [ ] **Step 3: 运行测试确认通过**

Run: `pytest tests/test_analysis.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/analysis.py tests/test_analysis.py
git commit -m "feat: add AnalysisAgent with LASSO and Logistic Regression"
```

---

### Task 14: 实现 Report Agent

**Files:**
- Create: `app/report.py`
- Create: `tests/test_report.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_report.py`:
```python
from pathlib import Path
from app.report import ReportAgent


def test_report_generation(tmp_path):
    analysis_result = {
        "success": True,
        "task_type": "binary_classification",
        "selected_features": ["original_firstorder_Mean"],
        "model_results": {
            "intercept": 0.0,
            "coefficients": {"original_firstorder_Mean": 0.5},
            "odds_ratios": {"original_firstorder_Mean": 1.65},
            "ci_lower": {"original_firstorder_Mean": 1.0},
            "ci_upper": {"original_firstorder_Mean": 2.5},
            "p_values": {"original_firstorder_Mean": 0.01},
        },
        "metrics": {
            "auc": 0.85,
            "auc_ci": [0.78, 0.91],
            "accuracy": 0.80,
            "sensitivity": 0.82,
            "specificity": 0.78,
            "threshold": 0.5,
            "confusion_matrix": [[40, 10], [8, 42]],
        },
        "n_samples": 100,
    }
    agent = ReportAgent()
    result = agent.run(
        analysis_result=analysis_result,
        output_dir=str(tmp_path),
        modality="CT",
        n_features=107,
        covariates=[],
    )
    assert result["success"] is True
    assert Path(result["report_path"]).exists()
```

- [ ] **Step 2: 实现 ReportAgent**

`app/report.py`:
```python
import os
from typing import Dict, Any, List, Optional
from datetime import datetime

import pandas as pd
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH


class ReportAgent:
    def run(self, analysis_result: Dict[str, Any], output_dir: str,
            modality: str, n_features: int, covariates: List[str],
            plot_paths: Optional[List[str]] = None,
            llm_client=None) -> Dict[str, Any]:
        try:
            self.plot_paths = plot_paths or []
            os.makedirs(output_dir, exist_ok=True)
            doc = Document()

            # Title
            title = doc.add_heading(level=0)
            run = title.add_run("Radiomics Analysis Report")
            run.font.size = Pt(18)
            run.bold = True
            title.alignment = WD_ALIGN_PARAGRAPH.CENTER

            # Methodology
            doc.add_heading("1. Methodology", level=1)
            methodology = self._build_methodology(
                analysis_result["n_samples"], modality, n_features,
                len(analysis_result["selected_features"]), covariates,
                analysis_result["metrics"]["auc"]
            )
            if llm_client:
                methodology = self._polish_methodology(methodology, llm_client)
            doc.add_paragraph(methodology)

            # Feature Selection Table
            doc.add_heading("2. Feature Selection", level=1)
            feat_df = pd.DataFrame({
                "Feature Name": analysis_result["selected_features"],
                "Coefficient": [analysis_result["model_results"]["coefficients"].get(f, 0) for f in analysis_result["selected_features"]],
            })
            self._add_table(doc, feat_df)

            # Regression Table
            doc.add_heading("3. Regression Results", level=1)
            rows = []
            for feat in analysis_result["selected_features"]:
                rows.append({
                    "Feature": feat,
                    "OR": f"{analysis_result['model_results']['odds_ratios'].get(feat, 0):.3f}",
                    "95% CI Lower": f"{analysis_result['model_results']['ci_lower'].get(feat, 0):.3f}" if analysis_result['model_results']['ci_lower'].get(feat) is not None else "-",
                    "95% CI Upper": f"{analysis_result['model_results']['ci_upper'].get(feat, 0):.3f}" if analysis_result['model_results']['ci_upper'].get(feat) is not None else "-",
                    "p-value": f"{analysis_result['model_results']['p_values'].get(feat, 1):.4f}",
                })
            self._add_table(doc, pd.DataFrame(rows))

            # Performance
            doc.add_heading("4. Model Performance", level=1)
            m = analysis_result["metrics"]
            perf_text = (
                f"The logistic regression model achieved an AUC of {m['auc']:.3f} "
                f"(95% CI: {m['auc_ci'][0]:.3f}–{m['auc_ci'][1]:.3f}). "
                f"Accuracy = {m['accuracy']:.3f}, Sensitivity = {m['sensitivity']:.3f}, "
                f"Specificity = {m['specificity']:.3f}."
            )
            doc.add_paragraph(perf_text)

            # Visualizations
            if self.plot_paths:
                doc.add_heading("5. Visualizations", level=1)
                for plot_path in self.plot_paths:
                    if os.path.exists(plot_path):
                        doc.add_picture(plot_path, width=Inches(5.5))

            # Save
            report_path = os.path.join(output_dir, "AutoRadiomics_Report.docx")
            doc.save(report_path)
            return {
                "success": True,
                "message": "报告生成完成",
                "report_path": report_path,
            }
        except Exception as e:
            return {"success": False, "message": f"报告生成失败: {e}"}

    def _build_methodology(self, n_samples, modality, n_features, n_selected, covariates, auc) -> str:
        cov_str = ", ".join(covariates) if covariates else "None"
        return (
            f"A total of {n_samples} patients were included. "
            f"Radiomic features were extracted from {modality} images using PyRadiomics, "
            f"yielding {n_features} features. LASSO regression selected {n_selected} features, "
            f"which were entered into a logistic regression model with covariates ({cov_str}). "
            f"The model achieved an AUC of {auc:.3f}."
        )

    def _polish_methodology(self, raw: str, llm_client) -> str:
        try:
            system = "You are an academic writing assistant. Polish the methodology paragraph. Keep all numbers exact. Output only the polished paragraph."
            polished = llm_client.call(system, raw, temperature=0.3, max_tokens=800)
            return polished or raw
        except Exception:
            return raw

    def _add_table(self, doc, df: pd.DataFrame):
        table = doc.add_table(rows=1, cols=len(df.columns))
        table.style = 'Table Grid'
        hdr = table.rows[0].cells
        for i, col in enumerate(df.columns):
            hdr[i].text = str(col)
        for _, row in df.iterrows():
            cells = table.add_row().cells
            for i, val in enumerate(row):
                cells[i].text = str(val)
```

- [ ] **Step 3: 运行测试确认通过**

Run: `pytest tests/test_report.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/report.py tests/test_report.py
git commit -m "feat: add ReportAgent for Word report generation"
```

---

## Phase 3: 集成与端到端

### Task 15: 实现 Orchestrator 与 Agent 的注册/适配函数

**Files:**
- Modify: `app/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: 在 orchestrator.py 中注册真实 Agent handler**

`app/orchestrator.py` 添加：
```python
import os


def _build_llm(state: Dict[str, Any]):
    cfg = state["config"]["llm"]
    if not cfg.get("api_key"):
        return None
    from app.llm import LLMClient
    return LLMClient(api_key=cfg["api_key"], base_url=cfg["base_url"], model=cfg["model"])


def register_default_handlers(orch: Orchestrator) -> None:
    from app import discovery, clinical, qc, feature, analysis, report

    orch.register_handler(PipelineStage.DISCOVERY, lambda state: discovery.DiscoveryAgent(
        llm_client=_build_llm(state) if state["config"]["llm"].get("api_key") else None
    ).run(state["config"]["image_dir"]))

    orch.register_handler(PipelineStage.CLINICAL, lambda state: clinical.ClinicalAgent(
        llm_client=_build_llm(state)
    ).run(state["config"]["clinical_path"], state["user_request"]))

    orch.register_handler(PipelineStage.MATCHING, lambda state: clinical.run_matching(
        state["discovery"]["pairs"],
        state["clinical"]["df"],
        state["clinical"]["id_col"],
    ))

    orch.register_handler(PipelineStage.QC, lambda state: qc.QCAgent(
        target_spacing=state["config"].get("target_spacing"),
        output_dir=os.path.join(state["config"]["output_dir"], "qc_resampled"),
    ).run([
        {
            "patient_id": row["patient_id"],
            "image_path": row["image_path"],
            "mask_path": row["mask_path"],
            "modality": row.get("modality", state["config"].get("modality", "CT")),
        }
        for _, row in state["matching"]["matched_df"].iterrows()
    ]))

    orch.register_handler(PipelineStage.FEATURE, lambda state: feature.FeatureAgent(
        n_workers=state["config"].get("n_jobs", -1),
    ).run(
        state["qc"]["passed_pairs"],
        state["config"]["yaml_path"],
    ))

    orch.register_handler(PipelineStage.MERGE, merge_data)

    orch.register_handler(PipelineStage.ANALYSIS, lambda state: analysis.AnalysisAgent(
        output_dir=state["config"]["output_dir"],
        covariates=state["config"].get("covariates", [])
    ).run(state["merged"]["df"], state["clinical"]["label_col"]))

    orch.register_handler(PipelineStage.REPORT, lambda state: report.ReportAgent().run(
        analysis_result=state["analysis"],
        output_dir=state["config"]["output_dir"],
        modality=state["config"].get("modality", "CT"),
        n_features=len(state["feature"]["feature_names"]),
        covariates=state["config"].get("covariates", []),
        plot_paths=state["analysis"].get("plot_paths", []),
        llm_client=_build_llm(state),
    ))
```

- [ ] **Step 2: 添加集成测试**

`tests/test_orchestrator.py` 追加：
```python
from unittest.mock import patch, MagicMock


def test_orchestrator_default_handlers_registration():
    orch = Orchestrator(image_dir="./data", clinical_path="./data/clinical.csv")
    from app.orchestrator import register_default_handlers
    register_default_handlers(orch)
    assert PipelineStage.DISCOVERY in orch._stage_handlers
```

- [ ] **Step 3: 运行测试确认通过**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: register default agent handlers in orchestrator"
```

---

### Task 16: 实现端到端 smoke test（mock 数据）

**Files:**
- Create: `tests/test_smoke.py`

- [ ] **Step 1: 编写 smoke test**

`tests/test_smoke.py`:
```python
import pytest
import SimpleITK as sitk
import numpy as np
import pandas as pd
from pathlib import Path

from app.orchestrator import Orchestrator, register_default_handlers, PipelineStage


def test_smoke_pipeline(tmp_path):
    # 创建临时数据
    img_dir = tmp_path / "images"
    img_dir.mkdir()

    for pid in ["P001", "P002", "P003"]:
        img = sitk.GetImageFromArray(np.random.randint(0, 100, (8, 8, 8)).astype(np.int16))
        mask = sitk.GetImageFromArray(np.ones((8, 8, 8), dtype=np.uint8))
        sitk.WriteImage(img, str(img_dir / f"{pid}_image.nii.gz"))
        sitk.WriteImage(mask, str(img_dir / f"{pid}_mask.nii.gz"))

    clinical_path = tmp_path / "clinical.csv"
    pd.DataFrame({
        "PatientID": ["P001", "P002", "P003"],
        "Age": [50, 60, 70],
        "Label": [0, 1, 0],
    }).to_csv(clinical_path, index=False)

    # 由于 YAML 配置需要真实 PyRadiomics，这里 mock Feature Agent
    orch = Orchestrator(
        image_dir=str(img_dir),
        clinical_path=str(clinical_path),
        output_dir=str(tmp_path / "output"),
        yaml_path=str(Path(__file__).parent.parent / "DONGGUAN_NEW_Radiomic" / "Params_labels_qian.yaml"),
    )
    register_default_handlers(orch)

    # Mock Feature Agent 以跳过 PyRadiomics
    import app.feature as feature_module
    original_run = feature_module.FeatureAgent.run
    def mock_run(self, pairs, yaml_path, n_jobs=-1):
        import pandas as pd
        rows = []
        for p in pairs:
            rows.append({"patient_id": p["patient_id"], "original_firstorder_Mean": 1.0, "original_shape_VoxelVolume": 2.0})
        df = pd.DataFrame(rows).set_index("patient_id")
        return {"success": True, "message": "mock", "feature_df": df, "feature_names": df.columns.tolist(), "failed_ids": [], "zero_variance_features": [], "settings_used": {}, "extraction_time_seconds": 0.1}
    feature_module.FeatureAgent.run = mock_run

    events = list(orch.run())
    feature_module.FeatureAgent.run = original_run

    assert orch.state["stage"] == PipelineStage.COMPLETED
    assert orch.state["report"]["success"] is True
```

- [ ] **Step 2: 运行 smoke test**

Run: `pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_smoke.py
git commit -m "test: add end-to-end smoke test with mocked feature extraction"
```

---

### Task 17: 修复集成测试中发现的问题

- [ ] **Step 1: 运行完整测试套件**

Run: `pytest tests/ -v`
Expected: 全部 PASS（此处可能需要根据实际失败修复）

- [ ] **Step 2: 修复失败的测试并提交**

针对失败逐一修复。

---

## Phase 4: UI 与部署

### Task 18: 实现 Gradio UI

**Files:**
- Create: `app/ui.py`
- Modify: `main.py`

- [ ] **Step 1: 实现 Gradio 界面**

`app/ui.py`:
```python
import gradio as gr
from app.orchestrator import Orchestrator, register_default_handlers


def create_ui():
    with gr.Blocks(title="AutoRadiomics Agent") as demo:
        gr.Markdown("# AutoRadiomics Agent")

        with gr.Row():
            image_dir = gr.Textbox(label="影像文件夹路径")
            clinical_path = gr.Textbox(label="临床表格路径")
        with gr.Row():
            output_dir = gr.Textbox(label="输出目录", value="./output")
            modality = gr.Dropdown(choices=["auto", "CT", "MRI"], value="auto", label="模态")
            covariates = gr.Textbox(label="协变量（逗号分隔）", value="")
        with gr.Row():
            api_key = gr.Textbox(label="DeepSeek API Key", type="password")
            model = gr.Textbox(label="模型", value="deepseek-chat")

        run_btn = gr.Button("运行分析")
        log = gr.Textbox(label="日志", lines=20, interactive=False)
        report_file = gr.File(label="生成报告")

        def run_analysis(img_dir, clinical, out_dir, mod, covs, key, m):
            orch = Orchestrator(
                image_dir=img_dir,
                clinical_path=clinical,
                output_dir=out_dir,
                modality=mod,
                covariates=[c.strip() for c in covs.split(",") if c.strip()],
                api_key=key,
                model=m,
            )
            register_default_handlers(orch)

            logs = []
            def emitter(event):
                logs.append(f"[{event.get('stage', '')}] {event['type']}: {event['message']}")

            orch.set_sse_emitter(emitter)
            for _ in orch.run():
                pass

            report_path = orch.state.get("report", {}).get("report_path")
            return "\n".join(logs), report_path

        run_btn.click(
            fn=run_analysis,
            inputs=[image_dir, clinical_path, output_dir, modality, covariates, api_key, model],
            outputs=[log, report_file],
        )

    return demo


if __name__ == "__main__":
    demo = create_ui()
    demo.launch()
```

- [ ] **Step 2: 更新 main.py 支持 launch UI**

`main.py` 修改：
```python
import argparse


def main():
    parser = argparse.ArgumentParser(description="AutoRadiomics Agent")
    parser.add_argument("--image-dir", default=None)
    parser.add_argument("--clinical", default=None)
    parser.add_argument("--output-dir", default="./output")
    parser.add_argument("--modality", default="auto")
    parser.add_argument("--covariates", default="")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--base-url", default="https://api.deepseek.com/v1")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--ui", action="store_true", help="启动 Gradio UI")
    args = parser.parse_args()

    if args.ui or args.image_dir is None or args.clinical is None:
        from app.ui import create_ui
        demo = create_ui()
        demo.launch()
        return

    from app.orchestrator import Orchestrator, register_default_handlers
    orch = Orchestrator(
        image_dir=args.image_dir,
        clinical_path=args.clinical,
        output_dir=args.output_dir,
        modality=args.modality,
        covariates=[c.strip() for c in args.covariates.split(",") if c.strip()],
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
    )
    register_default_handlers(orch)
    for event in orch.run():
        print(event)
    print(f"Report: {orch.state.get('report', {}).get('report_path')}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 运行 UI 导入测试**

Run: `python -c "from app.ui import create_ui; print('UI OK')"`
Expected: `UI OK`

- [ ] **Step 4: Commit**

```bash
git add app/ui.py main.py
git commit -m "feat: add Gradio UI and CLI integration"
```

---

### Task 19: 实现 Docker 部署

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Modify: `README.md`

- [ ] **Step 1: 创建 Dockerfile**

```dockerfile
FROM python:3.10-slim

WORKDIR /app

# 安装系统依赖（SimpleITK / PyRadiomics 需要）
RUN apt-get update && apt-get install -y \
    build-essential \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7860

CMD ["python", "main.py", "--ui"]
```

- [ ] **Step 2: 创建 docker-compose.yml**

```yaml
version: '3.8'
services:
  autoradiomics:
    build: .
    ports:
      - "7860:7860"
    volumes:
      - ./data:/app/data
      - ./output:/app/output
    environment:
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
```

- [ ] **Step 3: 创建 README.md 使用说明**

`README.md`:
```markdown
# AutoRadiomics Agent

## 安装

```bash
pip install -r requirements.txt
```

## 运行

### CLI
```bash
python main.py --image-dir ./data/images --clinical ./data/clinical.csv --output-dir ./output
```

### UI
```bash
python main.py --ui
```

### Docker
```bash
docker-compose up --build
```
```

- [ ] **Step 4: Commit**

```bash
git add Dockerfile docker-compose.yml README.md
git commit -m "feat: add Docker deployment and README"
```

---

## Phase 5: 优化与收尾

### Task 20: 添加 LASSO 与结果可视化图

**Files:**
- Modify: `app/analysis.py`
- Modify: `app/report.py`

- [ ] **Step 1: 在 AnalysisAgent 中保存 LASSO 路径图**

在 `AnalysisAgent.run` 中，每折 LASSO 拟合后保存路径图到 output_dir：
```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# 在 LASSO 拟合后
plt.figure()
plt.semilogx(lasso.alphas_, lasso.coef_.T)
plt.axvline(lasso.alpha_, color="black", linestyle="--")
plt.xlabel("Alpha")
plt.ylabel("Coefficient")
plt.savefig(os.path.join(output_dir, f"lasso_path_fold{fold_idx}.png"))
plt.close()
```

- [ ] **Step 2: 在 ReportAgent 中添加图片**

`ReportAgent.run` 接收 `plot_paths: List[str]` 参数，在 Report 中插入图片：
```python
for plot_path in plot_paths:
    if os.path.exists(plot_path):
        doc.add_picture(plot_path, width=Inches(5.5))
```

- [ ] **Step 3: 测试并提交**

Run: `pytest tests/test_analysis.py tests/test_report.py -v`
Expected: PASS

```bash
git add app/analysis.py app/report.py
git commit -m "feat: add LASSO path plots to report"
```

---

### Task 21: 异常处理与日志增强

**Files:**
- Modify: 各 Agent 文件
- Modify: `main.py`

- [ ] **Step 1: 统一日志格式**

在各 Agent 中添加：
```python
import logging
logger = logging.getLogger(__name__)
```

- [ ] **Step 2: main.py 配置日志**

```python
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
```

- [ ] **Step 3: 测试并提交**

```bash
git add app/*.py main.py
git commit -m "chore: unify logging across agents"
```

---

### Task 22: 最终回归测试

**Files:**
- 全部 tests/

- [ ] **Step 1: 运行完整测试套件**

Run: `pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 2: 真实数据端到端测试**

准备 1-2 组真实数据，运行完整流程，确认 Word 报告输出正确。

- [ ] **Step 3: Docker 构建验证**

Run: `docker-compose up --build`
Expected: 服务启动，UI 可访问

- [ ] **Step 4: Commit 最终版本**

```bash
git add .
git commit -m "release: v1.0 AutoRadiomics Agent"
```

---

## 自我审查

### Spec 覆盖检查

| 设计文档章节 | 对应任务 |
|--------------|----------|
| 统一 state schema | Task 2-3 |
| Discovery Agent（规则+LLM） | Task 6-7 |
| Clinical Agent | Task 8 |
| Matching Agent | Task 9 |
| QC Agent | Task 10 |
| Feature Agent（复用 cir_get_features） | Task 11 |
| Analysis Agent（LASSO+LR, 5 折 CV） | Task 12-13, 20 |
| Report Agent（Word + LLM 润色） | Task 14 |
| Orchestrator 注册/Merge | Task 4, 15 |
| UI + Docker | Task 18-19 |

### Placeholder 检查

- 无 "TBD" / "TODO" / "implement later"
- 每个任务包含具体文件路径、代码、测试、运行命令
- 类型/方法名在任务间一致（`DiscoveryAgent`, `ClinicalAgent`, `run_matching`, `QCAgent`, `FeatureAgent`, `AnalysisAgent`, `ReportAgent`）

### 已知边界

- `AnalysisAgent` 的 LASSO feature selection 使用每折 intersection；小样本时可能为空，已兜底使用 covariates。每折拟合后保存 LASSO 路径图，路径列表随分析结果返回并插入报告。
- `QCAgent` 中 modality 优先从 matching.matched_df 的 row 读取并回退到 config；Discovery pair 的 modality 会随 matched_df 透传。
- Docker 中 PyRadiomics 编译可能耗时，已在 Dockerfile 安装 build-essential。

---

## 执行方式选择

Plan complete and saved to `docs/superpowers/plans/2026-07-06-autoradiomics-agent-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach would you like?
