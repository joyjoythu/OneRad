# Orchestrator 实现方案

> 版本：v1.0
> 对应开发计划：AutoRadiomics Agent 开发计划
> 作者：负责人
> 职责边界：Orchestrator 是整个系统的中央状态机，负责按固定顺序调度 8 个 Agent，管理全局 `state dict`，处理中断/恢复，并通过 SSE 向 Gradio 前端推送进度事件。**Orchestrator 不直接调用 LLM，不直接提取影像特征，不直接做统计分析**——这些职责由下游 Agent 封闭实现。

---

## 目录

1. [设计原则](#1-设计原则)
2. [全局数据结构定义](#2-全局数据结构定义)
3. [PipelineStage 枚举与状态转换](#3-pipelinestage-枚举与状态转换)
4. [Orchestrator 类：核心实现](#4-orchestrator-类核心实现)
5. [与各 Agent 的接口契约](#5-与各-agent-的接口契约)
6. [SSE 事件协议（前端通信）](#6-sse-事件协议前端通信)
7. [中断与恢复机制](#7-中断与恢复机制)
8. [LLM Prompt 模板（3 个调用点）](#8-llm-prompt-模板3-个调用点)
9. [异常处理清单](#9-异常处理清单)
10. [完整可运行骨架代码](#10-完整可运行骨架代码)

---

## 1. 设计原则

| 原则 | 说明 |
|------|------|
| **原生 Python 状态机** | 用 `Enum` + `while` 循环实现，不引入 LangGraph / CrewAI / AutoGen |
| **共享状态字典** | 一个 `Dict[str, Any]` 在各阶段间传递，Agent 只读/写自己负责的 key |
| **函数式 Agent 接口** | 每个 Agent 对外暴露为纯函数 `def agent_name(state: dict) -> dict:`，输入输出都是 dict |
| **失败即中断** | 任一阶段抛异常或返回 `success=False`，状态机进入 `INTERRUPTED`，等待用户决策 |
| **SSE 流式推送** | 每进入/离开一个阶段都发送事件，前端据此渲染进度条和日志 |
| **样本量硬门槛** | 进入 Analysis 前，Orchestrator 检查有效样本数 `< 30` 则中断提示用户 |

---

## 2. 全局数据结构定义

### 2.1 PipelineStage（阶段枚举）

```python
from enum import Enum, auto

class PipelineStage(Enum):
    """流水线阶段枚举。顺序固定，不可跳过中间阶段（用户选择 skip 除外）。"""
    IDLE = auto()           # 初始状态
    DISCOVERY = auto()      # 扫描文件夹，配对 image/mask
    CLINICAL = auto()       # 读取临床表格，LLM 识别列名
    MATCHING = auto()       # ID 对齐（精确 + 模糊）
    QC = auto()             # 质控：mask 非空、spacing、resample
    FEATURE = auto()        # PyRadiomics 特征提取
    MERGE = auto()          # 特征矩阵 + 临床表格合并
    ANALYSIS = auto()       # LASSO + 回归分析
    REPORT = auto()         # 生成 Word 报告
    COMPLETED = auto()      # 全部完成
    INTERRUPTED = auto()    # 等待用户决策
    FAILED = auto()         # 用户选择终止
```

### 2.2 全局状态字典（Global State）schema

Orchestrator 维护一个 `state: Dict[str, Any]`，各阶段 Agent 只操作自己命名的 key。**严禁跨阶段直接读写他人 key。**

```python
# state 字典的完整 schema（文档约束，运行时不强校验）
STATE_SCHEMA = {
    # === 元数据（Orchestrator 维护）===
    "stage": PipelineStage,           # 当前阶段
    "previous_stage": PipelineStage,  # 中断前阶段，用于恢复
    "user_request": str,              # 用户原始自然语言描述，如 "做生存分析，调整 Age"
    "work_dir": str,                  # 工作目录路径
    
    # === 配置（用户输入 + 默认值）===
    "config": {
        "image_dir": str,             # 影像文件夹路径
        "clinical_path": str,         # 临床表格路径（CSV/Excel）
        "output_dir": str,            # 输出目录，默认 ./output
        "modality": str,              # "CT" | "MRI" | "auto"（Feature Agent 推断）
        "task_type": str,             # "classification" | "survival" | None（由 Analysis Agent 判断）
        "covariates": List[str],      # 用户指定需调整的协变量
        "skip_stages": List[str],     # 用户选择跳过的阶段名
        "n_jobs": int,                # PyRadiomics 并行核数，默认 -1
        "target_spacing": Optional[Tuple[float, float, float]],  # QC resample 目标 spacing
    },
    
    # === Discovery Agent 输出 ===
    "discovery": {
        "pairs": List[Dict],          # [{"patient_id": str, "image_path": str, "mask_path": str}, ...]
        "unpaired_images": List[str], # 未配对的 image 文件
        "unpaired_masks": List[str],  # 未配对的 mask 文件
        "success": bool,
        "message": str,
    },
    
    # === Clinical Agent 输出 ===
    "clinical": {
        "df": pd.DataFrame,           # 原始临床表格（内存中）
        "id_col": str,                # 患者 ID 列名
        "label_col": str,             # Label / Event 列名
        "feature_cols": List[str],    # 临床特征列名
        "time_col": Optional[str],    # 生存时间列名（生存分析时必填）
        "event_col": Optional[str],   # 生存事件列名（生存分析时必填）
        "success": bool,
        "message": str,
    },
    
    # === Matching Agent 输出 ===
    "matching": {
        "matched_df": pd.DataFrame,   # 对齐后的 DataFrame（含 patient_id + 临床列）
        "matched_ids": List[str],     # 成功匹配的 ID 列表
        "unmatched_image_ids": List[str],   # 影像有但表格没有的 ID
        "unmatched_clinical_ids": List[str],# 表格有但影像没有的 ID
        "fuzzy_matches": List[Tuple[str, str, float]],  # [(image_id, clinical_id, ratio), ...]
        "success": bool,
        "message": str,
    },
    
    # === QC Agent 输出 ===
    "qc": {
        "passed_pairs": List[Dict],   # 质检通过的 pairs
        "failed_checks": List[Dict],  # [{"pair": Dict, "reason": str}, ...]
        "resampled": bool,            # 是否执行过 resample
        "original_spacings": List[Tuple],  # 原始 spacing 记录
        "success": bool,
        "message": str,
    },
    
    # === Feature Agent 输出 ===
    "feature": {
        "feature_df": pd.DataFrame,   # 影像组学特征矩阵（行：样本，列：特征）
        "feature_names": List[str],   # 特征名列表
        "settings": Dict,             # PyRadiomics 实际使用的参数设置
        "extraction_time_seconds": float,
        "success": bool,
        "message": str,
    },
    
    # === Merge 阶段输出（Orchestrator 直接做，无独立 Agent）===
    "merged": {
        "df": pd.DataFrame,           # 合并后的完整数据（特征 + 临床 + Label）
        "n_samples": int,             # 样本数
        "n_features": int,            # 特征数
        "success": bool,
        "message": str,
    },
    
    # === Analysis Agent 输出 ===
    "analysis": {
        "task_type": str,             # "classification" | "survival"
        "selected_features": List[str],       # LASSO 筛选后的特征
        "model_results": Dict,        # 回归结果，见 5.6 节
        "metrics": Dict,              # {"AUC": float, "95CI": tuple} 或 {"C_index": float}
        "n_samples": int,             # 实际参与分析的样本数
        "success": bool,
        "message": str,
    },
    
    # === Report Agent 输出 ===
    "report": {
        "report_path": str,           # 生成的 Word 文件路径
        "success": bool,
        "message": str,
    },
    
    # === 中断/恢复相关 ===
    "interrupted_at": Optional[PipelineStage],
    "error_log": List[str],           # 累积错误信息
    "user_decision": Optional[str],   # "retry" | "skip" | "abort"
}
```

---

## 3. PipelineStage 枚举与状态转换

### 3.1 正常流程状态转换图

```
IDLE ──► DISCOVERY ──► CLINICAL ──► MATCHING ──► QC ──► FEATURE ──► MERGE ──► ANALYSIS ──► REPORT ──► COMPLETED
                                    ▲                                                                        │
                                    └────────────────────────────────────────────────────────────────────────┘
                                                      （用户选择 retry 时回退到中断点）
```

### 3.2 中断/恢复状态转换图

```
任意阶段失败/样本量不足
        │
        ▼
   INTERRUPTED ◄──────┐
        │             │
   等待用户决策        │
        │             │
   ┌────┴────┐        │
   │         │        │
 retry    skip     abort
   │         │        │
   ▼         ▼        ▼
回退到      进入      FAILED
中断点      下一阶段
```

### 3.3 阶段推进映射表

```python
# 阶段 → 下一阶段的映射（正常推进）
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
    """获取正常流程的下一个阶段。"""
    try:
        idx = STAGE_ORDER.index(current)
        return STAGE_ORDER[idx + 1] if idx + 1 < len(STAGE_ORDER) else PipelineStage.COMPLETED
    except ValueError:
        return None
```

---

## 4. Orchestrator 类：核心实现

### 4.1 类定义与构造函数

```python
from typing import Dict, Any, Optional, Callable, Generator
from enum import Enum, auto
import pandas as pd
from dataclasses import dataclass, field
import traceback


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
        return STAGE_ORDER[idx + 1] if idx + 1 < len(STAGE_ORDER) else None
    except ValueError:
        return None


class Orchestrator:
    """
    AutoRadiomics Agent 中央状态机。
    
    职责：
    1. 维护全局 state dict，按固定顺序调度各 Agent；
    2. 每阶段前后发送 SSE 事件供前端渲染；
    3. 捕获异常并进入 INTERRUPTED 状态，等待用户决策；
    4. 样本量 < 30 时主动中断；
    5. 支持 retry / skip / abort 三种恢复策略。
    
    非职责：
    - 不直接读取 DICOM/NIfTI 文件（Discovery/QC/Feature Agent）
    - 不直接调用 LLM（Clinical/Analysis/Report Agent）
    - 不直接生成 Word（Report Agent）
    """
    
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
    ):
        """
        Parameters
        ----------
        image_dir : str
            影像文件夹路径，内含 image/ 和 mask/ 子文件夹（或混放）。
        clinical_path : str
            临床表格路径（.csv 或 .xlsx）。
        user_request : str
            用户自然语言描述，如 "预测病理完全缓解，调整年龄"。
        output_dir : str
            输出目录。
        modality : str
            "CT" | "MRI" | "auto"
        covariates : list[str] | None
            需调整的协变量列名。
        n_jobs : int
            PyRadiomics 并行核数，-1 表示全部。
        target_spacing : tuple[float, float, float] | None
            QC 阶段统一 resample 的目标 spacing，None 表示不强制 resample。
        """
        self.state: Dict[str, Any] = {
            "stage": PipelineStage.IDLE,
            "previous_stage": PipelineStage.IDLE,
            "user_request": user_request,
            "work_dir": output_dir,
            "config": {
                "image_dir": image_dir,
                "clinical_path": clinical_path,
                "output_dir": output_dir,
                "modality": modality,
                "task_type": None,
                "covariates": covariates or [],
                "skip_stages": [],
                "n_jobs": n_jobs,
                "target_spacing": target_spacing,
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
        
        # 阶段名 → 执行函数的映射。由 Orchestrator 初始化时注册。
        self._stage_handlers: Dict[PipelineStage, Callable[[Dict], Dict]] = {}
        
        # SSE 回调函数，由外部（ui.py）注入
        self._sse_emitter: Optional[Callable[[Dict], None]] = None
    
    def register_handler(self, stage: PipelineStage, handler: Callable[[Dict], Dict]) -> None:
        """
        注册阶段执行函数。各 Agent 模块在导入时注册。
        
        Parameters
        ----------
        stage : PipelineStage
            要注册的阶段。
        handler : Callable[[Dict], Dict]
            执行函数，签名必须是 handler(state: dict) -> result_dict: dict。
            result_dict 必须包含 "success": bool 和 "message": str。
        """
        if stage in STAGE_ORDER:
            self._stage_handlers[stage] = handler
        else:
            raise ValueError(f"无法注册非流水线阶段: {stage}")
    
    def set_sse_emitter(self, emitter: Callable[[Dict], None]) -> None:
        """
        注入 SSE 推送回调。
        
        emitter 接收一个 dict 事件，由 ui.py 将其转为 SSE format 推送到前端。
        """
        self._sse_emitter = emitter
    
    def _emit(self, event: Dict[str, Any]) -> None:
        """内部方法：发送事件。若 emitter 未设置则静默丢弃。"""
        if self._sse_emitter:
            self._sse_emitter(event)
```

### 4.2 核心驱动循环：`run()` 与 `_run_stage()`

```python
    def run(self) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
        """
        主驱动循环。Generator，yield SSE 事件，return 最终 state。
        
        Usage（在 ui.py 中）：
            for event in orchestrator.run():
                yield f"data: {json.dumps(event)}\n\n"
            final_state = orchestrator.state
        """
        # 初始化
        self.state["stage"] = PipelineStage.IDLE
        self._emit(self._make_event("pipeline_start", "流水线启动"))
        
        current = PipelineStage.DISCOVERY
        
        while current is not None and current not in (
            PipelineStage.COMPLETED,
            PipelineStage.FAILED,
        ):
            self.state["stage"] = current
            
            # 检查用户是否选择 skip
            if current.name in self.state["config"]["skip_stages"]:
                self._emit(self._make_event("stage_skip", f"跳过阶段: {current.name}"))
                current = get_next_stage(current)
                continue
            
            # 执行阶段
            success, error_msg = self._run_stage(current)
            
            if not success:
                # 进入中断状态
                self.state["interrupted_at"] = current
                self.state["previous_stage"] = current
                self.state["stage"] = PipelineStage.INTERRUPTED
                self.state["error_log"].append(f"[{current.name}] {error_msg}")
                
                self._emit(self._make_event(
                    "stage_interrupt",
                    f"阶段 {current.name} 中断: {error_msg}",
                    {"error": error_msg, "stage": current.name}
                ))
                
                # yield 控制权，等待前端传入 user_decision
                # 外部 ui.py 会在收到 interrupt 事件后暂停生成器，等待用户点击按钮
                # 用户决策后通过 resume() 方法恢复
                return self.state  # Generator 提前结束，外部调用 resume() 重新驱动
            
            # 阶段成功，推进到下一阶段
            current = get_next_stage(current)
        
        # 完成或失败
        if current == PipelineStage.COMPLETED or current is None:
            self.state["stage"] = PipelineStage.COMPLETED
            self._emit(self._make_event("pipeline_complete", "流水线完成"))
        else:
            self.state["stage"] = PipelineStage.FAILED
            self._emit(self._make_event("pipeline_fail", "流水线终止"))
        
        return self.state
    
    def _run_stage(self, stage: PipelineStage) -> tuple[bool, str]:
        """
        执行单个阶段，返回 (success: bool, error_message: str)。
        
        封装了统一的异常捕获和 SSE 发送逻辑。
        """
        handler = self._stage_handlers.get(stage)
        if handler is None:
            return False, f"阶段 {stage.name} 未注册 handler"
        
        # 阶段开始事件
        self._emit(self._make_event("stage_start", f"开始: {stage.name}", {"stage": stage.name}))
        
        try:
            # === 特殊前置检查：ANALYSIS 阶段前强制样本量校验 ===
            if stage == PipelineStage.ANALYSIS:
                n_samples = self._get_merged_sample_count()
                if n_samples < 30:
                    return False, f"有效样本量不足: 仅 {n_samples} 例，要求 ≥ 30。建议扩充数据或调整纳入标准。"
            
            # 调用 Agent handler
            result = handler(self.state)
            
            # 校验 result 格式
            if not isinstance(result, dict):
                return False, f"阶段 {stage.name} 返回非 dict: {type(result)}"
            if "success" not in result:
                return False, f"阶段 {stage.name} 返回缺少 'success' 字段"
            
            # 将 result 写入 state 的对应 key
            stage_key = stage.name.lower()
            self.state[stage_key] = result
            
            if not result["success"]:
                return False, result.get("message", "未知错误")
            
            # 阶段成功事件
            self._emit(self._make_event(
                "stage_complete",
                f"完成: {stage.name}",
                {"stage": stage.name, "details": result.get("message", "")}
            ))
            return True, ""
            
        except Exception as e:
            tb = traceback.format_exc()
            error_msg = f"{stage.name} 阶段异常: {str(e)}\n{tb}"
            self.state["error_log"].append(error_msg)
            self._emit(self._make_event(
                "stage_error",
                error_msg,
                {"stage": stage.name, "error": str(e), "traceback": tb}
            ))
            return False, error_msg
    
    def _get_merged_sample_count(self) -> int:
        """
        在 ANALYSIS 前计算有效样本数。
        如果 MERGE 已完成直接取，否则根据 MATCHING + QC 结果估算。
        """
        if self.state.get("merged") and isinstance(self.state["merged"], dict):
            return self.state["merged"].get("n_samples", 0)
        
        # 估算：QC 通过数与 Matching 成功数的交集
        qc_passed = self.state.get("qc", {}).get("passed_pairs", [])
        matched_ids = self.state.get("matching", {}).get("matched_ids", [])
        
        # 取配对中有 image/mask 且通过 QC 的
        qc_ids = {p["patient_id"] for p in qc_passed}
        common_ids = set(matched_ids) & qc_ids
        return len(common_ids)
```

### 4.3 中断恢复：`resume()`

```python
    def resume(self, user_decision: str) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
        """
        用户在中断后做出决策，恢复流水线。
        
        Parameters
        ----------
        user_decision : str
            "retry" - 重试当前阶段
            "skip"  - 跳过当前阶段（进入下一阶段）
            "abort" - 终止整个流水线
        
        Usage（在 ui.py 中）：
            # 用户点击 "重试"
            for event in orchestrator.resume("retry"):
                yield f"data: {json.dumps(event)}\n\n"
        """
        if self.state["stage"] != PipelineStage.INTERRUPTED:
            self._emit(self._make_event("error", "resume() 只能在 INTERRUPTED 状态下调用"))
            return self.state
        
        self.state["user_decision"] = user_decision
        interrupted_stage = self.state.get("interrupted_at")
        
        if user_decision == "abort":
            self.state["stage"] = PipelineStage.FAILED
            self._emit(self._make_event("pipeline_fail", "用户终止流水线"))
            return self.state
        
        elif user_decision == "skip":
            # 记录跳过的阶段
            if interrupted_stage:
                self.state["config"]["skip_stages"].append(interrupted_stage.name)
            self._emit(self._make_event("stage_skip", f"用户选择跳过: {interrupted_stage.name if interrupted_stage else '未知'}"))
            # 进入下一阶段
            next_stage = get_next_stage(interrupted_stage) if interrupted_stage else None
            if next_stage is None:
                self.state["stage"] = PipelineStage.COMPLETED
                self._emit(self._make_event("pipeline_complete", "流水线完成（末尾阶段被跳过）"))
                return self.state
            # 递归/继续驱动
            return self._continue_from(next_stage)
        
        elif user_decision == "retry":
            self._emit(self._make_event("stage_retry", f"重试阶段: {interrupted_stage.name if interrupted_stage else '未知'}"))
            # 回到中断阶段重试
            return self._continue_from(interrupted_stage)
        
        else:
            self._emit(self._make_event("error", f"未知决策: {user_decision}"))
            return self.state
    
    def _continue_from(self, stage: PipelineStage) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
        """
        从指定阶段继续驱动循环（内部使用）。
        逻辑与 run() 的 while 循环相同，但起始点不同。
        """
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
                    {"error": error_msg, "stage": current.name}
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
    
    def _make_event(self, event_type: str, message: str, payload: Optional[Dict] = None) -> Dict:
        """
        构造标准化 SSE 事件字典。
        
        event_type 枚举：
        - pipeline_start / pipeline_complete / pipeline_fail
        - stage_start / stage_complete / stage_skip / stage_retry
        - stage_interrupt / stage_error
        - progress（Feature/Analysis 等长耗时阶段的进度百分比）
        """
        event = {
            "type": event_type,
            "message": message,
            "stage": self.state["stage"].name,
            "timestamp": None,  # ui.py 可注入 ISO 时间
        }
        if payload:
            event["payload"] = payload
        return event
```

---

## 5. 与各 Agent 的接口契约

> **铁律：** Orchestrator 只通过 `register_handler()` 注册各 Agent 的入口函数，不直接调用 Agent 内部函数。以下契约定义了 Orchestrator 期望的 handler 签名和 result schema。

### 5.1 Discovery Agent 契约

**Handler 签名：**
```python
def run_discovery(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parameters
    ----------
    state : dict
        需读取 state["config"]["image_dir"]。
    
    Returns
    -------
    dict
        {
            "success": bool,
            "message": str,
            "pairs": List[{"patient_id": str, "image_path": str, "mask_path": str}],
            "unpaired_images": List[str],
            "unpaired_masks": List[str],
        }
    """
```

**配对规则：**
- 从文件夹中识别 `image/` 和 `mask/` 子目录，或按文件名模式匹配（如 `*_image.nii.gz` / `*_mask.nii.gz`）。
- 患者 ID 从文件名中提取（如 `P001_image.nii.gz` → `P001`）。
- 返回 `pairs` 列表，每个元素含 `patient_id`（字符串，去重）。

### 5.2 Clinical Agent 契约

**Handler 签名：**
```python
def run_clinical(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parameters
    ----------
    state : dict
        需读取 state["config"]["clinical_path"]、state["user_request"]。
    
    Returns
    -------
    dict
        {
            "success": bool,
            "message": str,
            "df": pd.DataFrame,           # 原始表格（内存中，供下游使用）
            "id_col": str,                # 如 "PatientID"
            "label_col": str,             # 二分类 Label 列名
            "feature_cols": List[str],    # 临床特征列名
            "time_col": Optional[str],    # 生存时间列名
            "event_col": Optional[str],   # 生存事件列名
        }
    """
```

**LLM 调用说明：**
- Clinical Agent 内部调用 LLM 识别列名（见第 8 节 Prompt 模板）。
- Orchestrator 不感知 LLM 调用细节，只检查返回的 `id_col` 是否存在于 `df.columns`。

### 5.3 Matching Agent 契约

**Handler 签名：**
```python
def run_matching(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parameters
    ----------
    state : dict
        需读取 state["discovery"]["pairs"] 和 state["clinical"]["df"]、state["clinical"]["id_col"]。
    
    Returns
    -------
    dict
        {
            "success": bool,
            "message": str,
            "matched_df": pd.DataFrame,       # 对齐后的表格（含 patient_id）
            "matched_ids": List[str],         # 成功匹配的 ID
            "unmatched_image_ids": List[str], # 影像有但表格无
            "unmatched_clinical_ids": List[str], # 表格有但影像无
            "fuzzy_matches": List[Tuple[str, str, float]],  # 模糊匹配结果
        }
    """
```

**匹配策略：**
1. **精确匹配**：影像 ID（来自 Discovery）与表格 ID 列做集合交集。
2. **模糊匹配**：对未匹配的影像 ID，用 `difflib.get_close_matches` 在表格 ID 中找相似项，ratio ≥ 0.8 视为候选。
3. 返回的 `matched_df` 必须包含 `patient_id` 列（字符串），与 `pairs` 中的 `patient_id` 一致。

### 5.4 QC Agent 契约

**Handler 签名：**
```python
def run_qc(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parameters
    ----------
    state : dict
        需读取 state["matching"]["matched_df"]、state["discovery"]["pairs"]、
        state["config"]["target_spacing"]。
    
    Returns
    -------
    dict
        {
            "success": bool,
            "message": str,
            "passed_pairs": List[{"patient_id": str, "image_path": str, "mask_path": str}],
            "failed_checks": List[{"pair": Dict, "reason": str}],
            "resampled": bool,
            "original_spacings": List[Tuple[float, float, float]],
        }
    """
```

**QC 检查项（必须全部通过才算 passed）：**
| 检查项 | 失败处理 |
|--------|----------|
| mask 非空 | 失败，记录原因 |
| image 与 mask 尺寸一致 | 失败 |
| spacing 一致性（所有样本是否相同） | 不一致时若设了 target_spacing 则 resample，否则警告 |
| mask 值域（必须是 0/1 或 0/正整数） | 失败 |
| image 值域（CT 检查 HU 范围） | 警告（不阻塞） |

**Resample 逻辑：**
```python
# QC Agent 内部逻辑示意（供同学 A 实现）
import SimpleITK as sitk

def resample_to_spacing(image_path, mask_path, target_spacing, output_dir):
    image = sitk.ReadImage(image_path)
    mask = sitk.ReadImage(mask_path)
    
    original_spacing = image.GetSpacing()
    
    # 如果 spacing 已与目标一致，跳过
    if all(abs(a - b) < 1e-4 for a, b in zip(original_spacing, target_spacing)):
        return image_path, mask_path, False
    
    # 计算新尺寸
    original_size = image.GetSize()
    new_size = [
        int(round(original_size[i] * (original_spacing[i] / target_spacing[i])))
        for i in range(3)
    ]
    
    # Resample image（线性插值）
    resample_filter = sitk.ResampleImageFilter()
    resample_filter.SetOutputSpacing(target_spacing)
    resample_filter.SetSize(new_size)
    resample_filter.SetOutputDirection(image.GetDirection())
    resample_filter.SetOutputOrigin(image.GetOrigin())
    resample_filter.SetInterpolator(sitk.sitkLinear)
    resampled_image = resample_filter.Execute(image)
    
    # Resample mask（最近邻，保持标签值）
    resample_filter.SetInterpolator(sitk.sitkNearestNeighbor)
    resampled_mask = resample_filter.Execute(mask)
    
    # 保存到 output_dir
    ...
    return new_image_path, new_mask_path, True
```

### 5.5 Feature Agent 契约

**Handler 签名：**
```python
def run_feature(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parameters
    ----------
    state : dict
        需读取 state["qc"]["passed_pairs"]、state["config"]["modality"]、state["config"]["n_jobs"]。
    
    Returns
    -------
    dict
        {
            "success": bool,
            "message": str,
            "feature_df": pd.DataFrame,  # index=patient_id, columns=feature_names
            "feature_names": List[str],
            "settings": Dict,             # PyRadiomics 实际参数
            "extraction_time_seconds": float,
        }
    """
```

**模态自动推断与参数选择：**
```python
# Feature Agent 内部逻辑示意（供同学 B 实现）
from radiomics import featureextractor

def get_extractor_settings(modality: str) -> Dict:
    """
    按模态返回 PyRadiomics 参数设置。
    """
    base_settings = {
        "binWidth": 25,
        "resampledPixelSpacing": None,  # QC 已处理
        "interpolator": "sitkBSpline",
        "verbose": False,
    }
    
    if modality == "CT":
        base_settings.update({
            "binWidth": 25,
            "normalization": True,
            "normalizationScale": 100,  # HU 标准化常用
        })
    elif modality == "MRI":
        base_settings.update({
            "binWidth": 5,  # MRI 信号范围窄
            "normalization": True,
            "normalizationScale": 100,
        })
    
    # 启用全部特征类
    enabled_features = {
        "shape": True,
        "firstorder": True,
        "glcm": True,
        "glrlm": True,
        "glszm": True,
        "gldm": True,
        "ngtdm": True,
    }
    
    return {"setting": base_settings, "featureClass": enabled_features}

# 多进程并行提取
from multiprocessing import Pool

def extract_features_parallel(pairs, settings, n_jobs):
    if n_jobs == -1:
        n_jobs = None  # 使用全部核
    
    extractor = featureextractor.RadiomicsFeatureExtractor(**settings)
    
    with Pool(processes=n_jobs) as pool:
        results = pool.starmap(
            _extract_single,
            [(extractor, p["image_path"], p["mask_path"], p["patient_id"]) for p in pairs]
        )
    
    # 组装 DataFrame
    rows = []
    for patient_id, feature_dict in results:
        row = {"patient_id": patient_id}
        row.update(feature_dict)
        rows.append(row)
    
    df = pd.DataFrame(rows).set_index("patient_id")
    return df
```

### 5.6 Analysis Agent 契约

**Handler 签名：**
```python
def run_analysis(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parameters
    ----------
    state : dict
        需读取 state["merged"]["df"]、state["user_request"]（用于 LLM 意图解析）。
    
    Returns
    -------
    dict
        {
            "success": bool,
            "message": str,
            "task_type": str,              # "classification" | "survival"
            "selected_features": List[str],       # LASSO 筛选后的特征名
            "model_results": Dict,         # 回归结果
            "metrics": Dict,               # 性能指标
            "n_samples": int,
        }
    """
```

**模型结果 schema：**

```python
# 二分类（Logistic Regression）
model_results_classification = {
    "intercept": float,
    "coefficients": Dict[str, float],  # {feature_name: coef_value, ...}
    "odds_ratios": Dict[str, float],   # {feature_name: OR, ...}
    "confidence_intervals": Dict[str, Tuple[float, float]],  # {feature_name: (lower, upper), ...}
    "p_values": Dict[str, float],
    "AUC": float,
    "AUC_95CI": Tuple[float, float],
}

# 生存分析（CoxPH）
model_results_survival = {
    "coefficients": Dict[str, float],      # {feature_name: log(HR), ...}
    "hazard_ratios": Dict[str, float],     # {feature_name: HR, ...}
    "confidence_intervals": Dict[str, Tuple[float, float]],
    "p_values": Dict[str, float],
    "C_index": float,
    "C_index_95CI": Tuple[float, float],
}
```

**自动判断分析类型：**
```python
# Analysis Agent 内部逻辑示意
def infer_task_type(df: pd.DataFrame, label_col: str, time_col: Optional[str], event_col: Optional[str]) -> str:
    """
    自动判断分析类型：
    - 若 df[label_col] 只有 0/1 且 time_col is None → "classification"
    - 若 time_col 和 event_col 都存在且非空 → "survival"
    - 冲突时调用 LLM 意图解析（见第 8 节 Prompt）
    """
    unique_labels = df[label_col].dropna().unique()
    is_binary = set(unique_labels) == {0, 1}
    
    has_survival_cols = time_col is not None and event_col is not None
    if has_survival_cols and time_col in df.columns and event_col in df.columns:
        return "survival"
    elif is_binary:
        return "classification"
    else:
        # 需要 LLM 意图解析
        return call_llm_intent_parse(...)
```

**LASSO + Logistic Regression 完整代码：**
```python
import numpy as np
from sklearn.linear_model import LogisticRegression, LassoCV
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import cross_val_predict
from sklearn.metrics import roc_auc_score
from scipy import stats

def lasso_logistic_analysis(df, feature_cols, label_col, covariates=None, n_lasso_alphas=100):
    """
    Parameters
    ----------
    df : pd.DataFrame
        合并后的数据。
    feature_cols : List[str]
        影像组学特征列名。
    label_col : str
        二分类 Label 列名。
    covariates : List[str] | None
        需调整的协变量列名（不参与 LASSO，直接进入回归）。
    
    Returns
    -------
    dict
        符合 5.6 节 schema 的结果字典。
    """
    X_radiomics = df[feature_cols].values
    y = df[label_col].values
    
    # 1. 标准化影像特征
    scaler = StandardScaler()
    X_radiomics_scaled = scaler.fit_transform(X_radiomics)
    
    # 2. LASSO 筛选
    lasso = LassoCV(cv=5, max_iter=10000, n_alphas=n_lasso_alphas, random_state=42)
    lasso.fit(X_radiomics_scaled, y)
    
    # 取非零系数特征
    selected_mask = np.abs(lasso.coef_) > 1e-6
    selected_features = [feature_cols[i] for i in np.where(selected_mask)[0]]
    
    if len(selected_features) == 0:
        raise ValueError("LASSO 未筛选出任何特征，可能所有特征与 Label 无关或样本量过小。")
    
    X_selected = X_radiomics_scaled[:, selected_mask]
    
    # 3. 拼接协变量（如有）
    if covariates:
        X_cov = df[covariates].values
        X_cov_scaled = StandardScaler().fit_transform(X_cov)
        X_final = np.hstack([X_selected, X_cov_scaled])
        final_feature_names = selected_features + covariates
    else:
        X_final = X_selected
        final_feature_names = selected_features
    
    # 4. Logistic Regression
    lr = LogisticRegression(max_iter=10000, solver="lbfgs")
    lr.fit(X_final, y)
    
    # 5. AUC（交叉验证）
    y_pred_proba = cross_val_predict(lr, X_final, y, cv=5, method="predict_proba")[:, 1]
    auc = roc_auc_score(y, y_pred_proba)
    
    # AUC 95% CI（DeLong test 简化版：Bootstrap）
    auc_ci = _bootstrap_auc_ci(y, y_pred_proba, n_bootstrap=1000)
    
    # 6. 提取结果
    coefs = dict(zip(final_feature_names, lr.coef_[0]))
    odds_ratios = {k: np.exp(v) for k, v in coefs.items()}
    
    # 标准误和 95% CI（基于 Fisher Information）
    n_samples, n_features = X_final.shape
    pred_proba = lr.predict_proba(X_final)[:, 1]
    W = np.diag(pred_proba * (1 - pred_proba))
    X_design = np.column_stack([np.ones(n_samples), X_final])
    
    try:
        cov_matrix = np.linalg.inv(X_design.T @ W @ X_design)
        se = np.sqrt(np.diag(cov_matrix))[1:]  # 去掉截距项
        
        cis = {}
        pvals = {}
        for i, name in enumerate(final_feature_names):
            ci_lower = coefs[name] - 1.96 * se[i]
            ci_upper = coefs[name] + 1.96 * se[i]
            cis[name] = (ci_lower, ci_upper)
            
            z = coefs[name] / se[i]
            pvals[name] = 2 * (1 - stats.norm.cdf(abs(z)))
    except np.linalg.LinAlgError:
        # 矩阵奇异，退化为简单估计
        cis = {name: (None, None) for name in final_feature_names}
        pvals = {name: None for name in final_feature_names}
    
    return {
        "success": True,
        "message": f"LASSO 筛选 {len(selected_features)} 个特征，Logistic Regression AUC={auc:.3f}",
        "task_type": "classification",
        "selected_features": selected_features,
        "model_results": {
            "intercept": float(lr.intercept_[0]),
            "coefficients": coefs,
            "odds_ratios": odds_ratios,
            "confidence_intervals": cis,
            "p_values": pvals,
            "AUC": float(auc),
            "AUC_95CI": auc_ci,
        },
        "metrics": {"AUC": float(auc), "95CI": auc_ci},
        "n_samples": n_samples,
    }


def _bootstrap_auc_ci(y_true, y_pred_proba, n_bootstrap=1000, confidence=0.95):
    """Bootstrap 计算 AUC 的置信区间。"""
    rng = np.random.RandomState(42)
    bootstrapped_aucs = []
    
    for _ in range(n_bootstrap):
        indices = rng.randint(0, len(y_true), len(y_true))
        if len(np.unique(y_true[indices])) < 2:
            continue
        bootstrapped_aucs.append(roc_auc_score(y_true[indices], y_pred_proba[indices]))
    
    sorted_aucs = np.sort(bootstrapped_aucs)
    lower_idx = int((1 - confidence) / 2 * len(sorted_aucs))
    upper_idx = int((1 + confidence) / 2 * len(sorted_aucs))
    
    return (float(sorted_aucs[lower_idx]), float(sorted_aucs[upper_idx]))
```

**LASSO + CoxPH 完整代码：**
```python
from lifelines import CoxPHFitter
from sklearn.linear_model import LassoCV

def lasso_cox_analysis(df, feature_cols, time_col, event_col, covariates=None, n_lasso_alphas=100):
    """
    Cox Proportional Hazards with LASSO feature selection.
    
    Parameters
    ----------
    df : pd.DataFrame
    feature_cols : List[str]
    time_col : str
    event_col : str
    covariates : List[str] | None
    
    Returns
    -------
    dict
        符合 survival schema 的结果字典。
    """
    X_radiomics = df[feature_cols].values
    time = df[time_col].values
    event = df[event_col].values
    
    # 1. LASSO（对数时间作为伪回归目标，近似筛选）
    # 注意：严格来说 LASSO 不能直接用于 Cox，这里用加速失效时间近似
    log_time = np.log(time + 1e-6)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_radiomics)
    
    lasso = LassoCV(cv=5, max_iter=10000, n_alphas=n_lasso_alphas, random_state=42)
    lasso.fit(X_scaled, log_time)
    
    selected_mask = np.abs(lasso.coef_) > 1e-6
    selected_features = [feature_cols[i] for i in np.where(selected_mask)[0]]
    
    if len(selected_features) == 0:
        raise ValueError("LASSO 未筛选出任何特征。")
    
    # 2. 构建 CoxPH DataFrame
    cox_df = pd.DataFrame()
    cox_df[selected_features] = df[selected_features]
    if covariates:
        cox_df[covariates] = df[covariates]
    cox_df["time"] = time
    cox_df["event"] = event
    
    # 3. CoxPH
    cph = CoxPHFitter(penalizer=0.1)
    all_cols = selected_features + (covariates or [])
    cph.fit(cox_df[all_cols + ["time", "event"]], duration_col="time", event_col="event")
    
    # 4. C-index
    c_index = cph.concordance_index_
    
    # Bootstrap CI for C-index
    c_index_ci = _bootstrap_cindex_ci(cox_df, all_cols, n_bootstrap=500)
    
    # 5. 提取结果
    summary = cph.summary
    
    coefs = {}
    hrs = {}
    cis = {}
    pvals = {}
    
    for name in all_cols:
        coefs[name] = float(summary.loc[name, "coef"])
        hrs[name] = float(np.exp(summary.loc[name, "coef"]))
        
        ci_low = summary.loc[name, "coef lower 95%"]
        ci_high = summary.loc[name, "coef upper 95%"]
        cis[name] = (float(ci_low), float(ci_high))
        
        pvals[name] = float(summary.loc[name, "p"])
    
    return {
        "success": True,
        "message": f"LASSO 筛选 {len(selected_features)} 个特征，C-index={c_index:.3f}",
        "task_type": "survival",
        "selected_features": selected_features,
        "model_results": {
            "coefficients": coefs,
            "hazard_ratios": hrs,
            "confidence_intervals": cis,
            "p_values": pvals,
            "C_index": float(c_index),
            "C_index_95CI": c_index_ci,
        },
        "metrics": {"C_index": float(c_index), "95CI": c_index_ci},
        "n_samples": len(df),
    }


def _bootstrap_cindex_ci(df, cols, n_bootstrap=500, confidence=0.95):
    """Bootstrap 计算 C-index 的置信区间。"""
    rng = np.random.RandomState(42)
    c_indices = []
    
    for _ in range(n_bootstrap):
        boot_df = df.sample(n=len(df), replace=True, random_state=rng)
        if boot_df["event"].sum() < 2:
            continue
        try:
            cph = CoxPHFitter(penalizer=0.1)
            cph.fit(boot_df[cols + ["time", "event"]], duration_col="time", event_col="event")
            c_indices.append(cph.concordance_index_)
        except Exception:
            continue
    
    if len(c_indices) < 100:
        return (None, None)
    
    sorted_c = np.sort(c_indices)
    lower_idx = int((1 - confidence) / 2 * len(sorted_c))
    upper_idx = int((1 + confidence) / 2 * len(sorted_c))
    return (float(sorted_c[lower_idx]), float(sorted_c[upper_idx]))
```

### 5.7 Report Agent 契约

**Handler 签名：**
```python
def run_report(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parameters
    ----------
    state : dict
        需读取 state["analysis"]、state["merged"]、state["feature"]、state["config"]。
    
    Returns
    -------
    dict
        {
            "success": bool,
            "message": str,
            "report_path": str,  # 如 "./output/report_20250701_143022.docx"
        }
    """
```

**Word 报告结构（python-docx）：**
```python
from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

def generate_word_report(analysis_result, merged_info, feature_info, config, output_dir):
    doc = Document()
    
    # 标题
    title = doc.add_heading("AutoRadiomics 分析报告", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    # 1. 基本信息
    doc.add_heading("1. 基本信息", level=1)
    doc.add_paragraph(f"分析类型: {'二分类' if analysis_result['task_type'] == 'classification' else '生存分析'}")
    doc.add_paragraph(f"样本量: {analysis_result['n_samples']}")
    doc.add_paragraph(f"特征数: {merged_info['n_features']}")
    doc.add_paragraph(f"LASSO 筛选特征数: {len(analysis_result['selected_features'])}")
    
    # 2. 方法学（调用 LLM 润色，见第 8 节 Prompt）
    doc.add_heading("2. 方法学", level=1)
    methodology_text = call_llm_methodology_polish(analysis_result, feature_info)
    doc.add_paragraph(methodology_text)
    
    # 3. 结果表格
    doc.add_heading("3. 分析结果", level=1)
    
    # 3.1 特征筛选表
    doc.add_heading("3.1 LASSO 特征筛选", level=2)
    table = doc.add_table(rows=1, cols=2)
    table.style = "Light Grid Accent 1"
    hdr_cells = table.rows[0].cells
    hdr_cells[0].text = "特征名"
    hdr_cells[1].text = "说明"
    for feat in analysis_result["selected_features"]:
        row_cells = table.add_row().cells
        row_cells[0].text = feat
        row_cells[1].text = ""
    
    # 3.2 回归系数表
    doc.add_heading("3.2 回归分析结果", level=2)
    model = analysis_result["model_results"]
    
    if analysis_result["task_type"] == "classification":
        table = doc.add_table(rows=1, cols=5)
        table.style = "Light Grid Accent 1"
        hdr = table.rows[0].cells
        hdr[0].text, hdr[1].text, hdr[2].text, hdr[3].text, hdr[4].text = \
            "特征", "回归系数", "OR", "95% CI", "p 值"
        
        for feat in model["coefficients"]:
            row = table.add_row().cells
            row[0].text = feat
            row[1].text = f"{model['coefficients'][feat]:.3f}"
            row[2].text = f"{model['odds_ratios'][feat]:.3f}"
            ci = model["confidence_intervals"][feat]
            row[3].text = f"({ci[0]:.3f}, {ci[1]:.3f})" if ci[0] is not None else "N/A"
            p = model["p_values"][feat]
            row[4].text = f"{p:.4f}" if p is not None else "N/A"
        
        doc.add_paragraph(f"AUC = {model['AUC']:.3f} (95% CI: {model['AUC_95CI'][0]:.3f}-{model['AUC_95CI'][1]:.3f})")
    
    else:  # survival
        table = doc.add_table(rows=1, cols=5)
        table.style = "Light Grid Accent 1"
        hdr = table.rows[0].cells
        hdr[0].text, hdr[1].text, hdr[2].text, hdr[3].text, hdr[4].text = \
            "特征", "回归系数", "HR", "95% CI", "p 值"
        
        for feat in model["coefficients"]:
            row = table.add_row().cells
            row[0].text = feat
            row[1].text = f"{model['coefficients'][feat]:.3f}"
            row[2].text = f"{model['hazard_ratios'][feat]:.3f}"
            ci = model["confidence_intervals"][feat]
            row[3].text = f"({ci[0]:.3f}, {ci[1]:.3f})"
            p = model["p_values"][feat]
            row[4].text = f"{p:.4f}"
        
        doc.add_paragraph(f"C-index = {model['C_index']:.3f} (95% CI: {model['C_index_95CI'][0]:.3f}-{model['C_index_95CI'][1]:.3f})")
    
    # 保存
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = f"{output_dir}/report_{timestamp}.docx"
    doc.save(report_path)
    
    return report_path
```

### 5.8 Merge 阶段（Orchestrator 直接实现）

Merge 阶段逻辑简单，不独立为 Agent，由 Orchestrator 直接执行：

```python
def run_merge(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 feature_df 与 matched clinical_df 按 patient_id 合并。
    这是 Orchestrator 的内置方法，不通过 register_handler 注册。
    """
    feature_df = state["feature"]["feature_df"]  # index=patient_id
    clinical_df = state["matching"]["matched_df"]  # 含 patient_id 列
    
    # 确保 clinical_df 的 patient_id 为字符串，设为 index
    clinical_df = clinical_df.copy()
    clinical_df["patient_id"] = clinical_df["patient_id"].astype(str)
    clinical_df = clinical_df.set_index("patient_id")
    
    # 合并
    merged = clinical_df.join(feature_df, how="inner")
    
    n_samples = len(merged)
    n_features = len(state["feature"]["feature_names"])
    
    return {
        "success": True,
        "message": f"合并完成: {n_samples} 样本 × {n_features} 影像特征 + {len(clinical_df.columns)} 临床变量",
        "df": merged,
        "n_samples": n_samples,
        "n_features": n_features,
    }
```

---

## 6. SSE 事件协议（前端通信）

### 6.1 事件格式

Orchestrator 通过 `_emit()` 发送的事件是 JSON 对象，ui.py 将其包装为 SSE：

```
event: stage_start
data: {"type": "stage_start", "message": "开始: DISCOVERY", "stage": "DISCOVERY", "timestamp": "2025-07-01T14:30:22Z"}
```

### 6.2 事件类型完整列表

| event_type | 触发时机 | payload |
|------------|----------|---------|
| `pipeline_start` | run() 开始时 | — |
| `stage_start` | 每个阶段开始前 | `{"stage": "DISCOVERY"}` |
| `stage_complete` | 每个阶段成功完成 | `{"stage": "DISCOVERY", "details": "..."}` |
| `stage_skip` | 用户选择跳过或 config 中预设 | `{"stage": "QC"}` |
| `stage_retry` | 用户选择重试 | `{"stage": "QC"}` |
| `stage_interrupt` | 阶段失败/样本量不足 | `{"stage": "ANALYSIS", "error": "..."}` |
| `stage_error` | 阶段抛异常 | `{"stage": "...", "error": "...", "traceback": "..."}` |
| `progress` | 长耗时阶段（Feature/Analysis） | `{"percent": 45, "current": 45, "total": 100}` |
| `pipeline_complete` | 全部完成 | — |
| `pipeline_fail` | 用户终止或最终失败 | — |

### 6.3 Gradio 前端渲染逻辑（供同学 C 参考）

```python
# ui.py 中的 SSE 消费者示例
import json
import gradio as gr

def create_ui():
    with gr.Blocks() as demo:
        # ... 布局 ...
        
        def on_message(message):
            event = json.loads(message)
            etype = event["type"]
            
            if etype == "stage_start":
                stage_name = event["payload"]["stage"]
                progress_bar.update(stage_name)
                log_box.append(f"▶ {event['message']}")
            
            elif etype == "stage_complete":
                progress_bar.complete(event["payload"]["stage"])
                log_box.append(f"✓ {event['message']}")
            
            elif etype == "stage_interrupt":
                stage_name = event["payload"]["stage"]
                error_msg = event["payload"]["error"]
                # 显示三个按钮：重试 / 跳过 / 终止
                interrupt_box.visible = True
                interrupt_msg.value = f"阶段 {stage_name} 中断: {error_msg}"
            
            elif etype == "pipeline_complete":
                download_btn.visible = True
                log_box.append("✓ 分析完成！")
            
            elif etype == "progress":
                progress_bar.percent = event["payload"]["percent"]
```

---

## 7. 中断与恢复机制

### 7.1 中断触发条件

| 条件 | 触发阶段 | 中断后建议 |
|------|----------|------------|
| Agent handler 返回 `success=False` | 任意 | retry / skip / abort |
| Agent handler 抛异常 | 任意 | retry（调试）/ skip / abort |
| 有效样本数 < 30 | ANALYSIS 前 | 建议 abort（数据不足无法继续） |
| 特征全零（LASSO 无选中） | ANALYSIS 内 | retry（调参数）/ abort |
| ID 匹配率 < 50% | MATCHING | skip（只用有匹配的）/ retry（检查文件名） |
| QC 通过率 < 30% | QC | skip / abort |

### 7.2 恢复策略

```python
# 恢复策略的语义：

# retry: 清除当前阶段的输出，重新执行同一阶段
#   - Orchestrator 不自动清除 state[stage_key]，由 handler 幂等处理
#   - 实际实现：直接重新调用 handler

# skip: 标记阶段为跳过，进入下一阶段
#   - 将阶段名加入 state["config"]["skip_stages"]
#   - 风险：跳过 FEATURE 则 ANALYSIS 无数据；跳过 ANALYSIS 则 REPORT 无内容
#   - Orchestrator 不负责检查 skip 的合理性，由用户承担风险

# abort: 终止流水线，进入 FAILED 状态
#   - 最终 state 保留，可供调试
#   - 前端显示 "分析已终止"
```

### 7.3 状态持久化（可选，Day 3 以后有余力再加）

```python
import pickle
import os

def save_state(self, path: str = "./checkpoint.pkl") -> None:
    """将当前 state 序列化到磁盘，用于崩溃恢复。"""
    # 注意：pd.DataFrame 可以用 pickle，但生产环境建议 parquet + json
    with open(path, "wb") as f:
        pickle.dump(self.state, f)

def load_state(self, path: str = "./checkpoint.pkl") -> None:
    """从磁盘恢复 state。"""
    if os.path.exists(path):
        with open(path, "rb") as f:
            self.state = pickle.load(f)
```

---

## 8. LLM Prompt 模板（3 个调用点）

> 虽然 Orchestrator 不直接调用 LLM，但以下 Prompt 模板是全局设计的一部分，由 Orchestrator 定义并写入 `llm.py`，供 Clinical/Analysis/Report Agent 调用。

### 8.1 调用点 1：意图解析（Analysis Agent）

**目的：** 从用户自然语言描述中提取 `task_type` 和 `covariates`。

**Prompt：**
```python
INTENT_PARSE_SYSTEM = """You are a clinical research assistant specialized in radiomics analysis.
Your task is to parse the user's natural language request and extract structured parameters.
Respond ONLY in valid JSON format. Do not include markdown code blocks or explanations.

Valid task_type values:
- "classification": binary outcome prediction (e.g., pCR yes/no, recurrence yes/no)
- "survival": time-to-event analysis (e.g., overall survival, progression-free survival)
- "unknown": cannot determine from the description

Valid covariates are clinical variables the user wants to adjust for (e.g., Age, Sex, Stage).
If no covariates are mentioned, return an empty list.
"""

INTENT_PARSE_USER_TEMPLATE = """User request: {user_request}

Available columns in the clinical table: {column_names}

Based on the request, determine:
1. What type of analysis is being requested?
2. Which columns should be used as covariates (adjustment variables)?

Respond in this exact JSON format:
{{
  "task_type": "classification" | "survival" | "unknown",
  "covariates": ["ColumnName1", "ColumnName2"],
  "reasoning": "brief explanation"
}}
"""
```

**调用封装（`llm.py`）：**
```python
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
import json
import os

def create_llm_chain():
    """
    用 LangChain LCEL 创建 LLM 调用链。
    Day 3 前搭不起来就回退到原生 OpenAI SDK。
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    
    llm = ChatOpenAI(
        model="deepseek-v4",  # 或 "deepseek-chat" 作为 fallback
        api_key=api_key,
        base_url=base_url,
        temperature=0.0,
        max_tokens=512,
    )
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", INTENT_PARSE_SYSTEM),
        ("user", INTENT_PARSE_USER_TEMPLATE),
    ])
    
    chain = prompt | llm
    return chain

def parse_intent(user_request: str, column_names: list) -> dict:
    """
    对外暴露的普通函数。低年级同学无感知。
    
    Returns
    -------
    dict
        {"task_type": str, "covariates": List[str], "reasoning": str}
    """
    chain = create_llm_chain()
    response = chain.invoke({
        "user_request": user_request,
        "column_names": ", ".join(column_names),
    })
    
    # 解析 JSON
    content = response.content
    # 去除可能的 markdown code block
    content = content.replace("```json", "").replace("```", "").strip()
    
    try:
        result = json.loads(content)
        # 校验字段
        assert "task_type" in result
        assert "covariates" in result
        return result
    except (json.JSONDecodeError, AssertionError) as e:
        # 回退到默认值
        return {
            "task_type": "unknown",
            "covariates": [],
            "reasoning": f"LLM 返回解析失败: {e}. Raw: {content[:200]}"
        }
```

### 8.2 调用点 2：列名识别（Clinical Agent）

**目的：** 从临床表格的列名中自动识别 `id_col`、`label_col`、`feature_cols`、`time_col`、`event_col`。

**Prompt：**
```python
COLUMN_IDENTIFY_SYSTEM = """You are a clinical data analyst. Given a list of column names from a clinical table, identify which columns correspond to:
- Patient ID
- Outcome label (binary: 0/1)
- Survival time (continuous, in months or days)
- Survival event indicator (binary: 0=censored, 1=event)
- Clinical features (covariates like Age, Sex, Stage, etc.)

Respond ONLY in valid JSON. If a column type is not present, use null.
"""

COLUMN_IDENTIFY_USER_TEMPLATE = """Column names: {column_names}

Sample data (first 3 rows):
{sample_data}

User request hint: {user_request}

Respond in this exact JSON format:
{{
  "id_col": "ColumnName" | null,
  "label_col": "ColumnName" | null,
  "time_col": "ColumnName" | null,
  "event_col": "ColumnName" | null,
  "feature_cols": ["ColumnName1", "ColumnName2"],
  "reasoning": "brief explanation"
}}
"""
```

**调用封装：**
```python
def identify_columns(column_names: list, sample_data: str, user_request: str) -> dict:
    """
    识别临床表格列名。
    
    Returns
    -------
    dict
        {"id_col": str|None, "label_col": str|None, "time_col": str|None,
         "event_col": str|None, "feature_cols": List[str], "reasoning": str}
    """
    chain = create_llm_chain()  # 复用相同的 LLM 配置
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", COLUMN_IDENTIFY_SYSTEM),
        ("user", COLUMN_IDENTIFY_USER_TEMPLATE),
    ])
    
    response = (prompt | chain).invoke({  # 注意：这里 chain 已包含 LLM，所以直接用 prompt | llm
        "column_names": ", ".join(column_names),
        "sample_data": sample_data,
        "user_request": user_request,
    })
    
    content = response.content.replace("```json", "").replace("```", "").strip()
    
    try:
        result = json.loads(content)
        # 校验：id_col 和 label_col（或 time_col+event_col）至少有一组
        return result
    except json.JSONDecodeError:
        return {
            "id_col": None, "label_col": None, "time_col": None,
            "event_col": None, "feature_cols": [],
            "reasoning": f"解析失败，原始响应: {content[:200]}"
        }
```

> **注意：** 上面代码中 `create_llm_chain()` 返回的是 `prompt | llm`，所以 `identify_columns` 应该直接创建新的 chain：
> ```python
> llm = ChatOpenAI(...)
> prompt = ChatPromptTemplate.from_messages([...])
> chain = prompt | llm
> response = chain.invoke({...})
> ```

### 8.3 调用点 3：报告润色（Report Agent）

**目的：** 将统计结果翻译成学术化的方法学描述段落。

**Prompt：**
```python
METHODOLOGY_POLISH_SYSTEM = """You are a medical writing expert specializing in radiomics research papers.
Your task is to generate a concise, academic methodology paragraph based on the analysis parameters provided.
Write in formal academic English. Keep it under 200 words.
"""

METHODOLOGY_POLISH_USER_TEMPLATE = """Analysis parameters:
- Task type: {task_type}
- Modality: {modality}
- Total samples: {n_samples}
- Radiomics features extracted: {n_radiomics_features}
- Features selected by LASSO: {n_selected}
- Selected feature names: {selected_features}
- Covariates adjusted: {covariates}
- Statistical model: {model_name}
- Performance metric: {metric_name} = {metric_value} (95% CI: {ci_lower}-{ci_upper})

Generate a methodology paragraph describing:
1. Feature extraction approach (PyRadiomics, modality-specific settings)
2. Feature selection method (LASSO with 5-fold cross-validation)
3. Statistical modeling (Logistic Regression or Cox Proportional Hazards)
4. Performance evaluation (AUC or C-index with 95% CI)
"""
```

**调用封装：**
```python
def polish_methodology(analysis_result: dict, feature_info: dict, config: dict) -> str:
    """
    润色方法学描述。
    
    Returns
    -------
    str
        学术化方法学段落（英文）。
    """
    task_type = analysis_result["task_type"]
    model = analysis_result["model_results"]
    
    if task_type == "classification":
        model_name = "Multivariable Logistic Regression"
        metric_name = "AUC"
        metric_value = f"{model['AUC']:.3f}"
        ci = model["AUC_95CI"]
    else:
        model_name = "Cox Proportional Hazards Model"
        metric_name = "C-index"
        metric_value = f"{model['C_index']:.3f}"
        ci = model["C_index_95CI"]
    
    llm = ChatOpenAI(model="deepseek-v4", temperature=0.3, max_tokens=500)
    prompt = ChatPromptTemplate.from_messages([
        ("system", METHODOLOGY_POLISH_SYSTEM),
        ("user", METHODOLOGY_POLISH_USER_TEMPLATE),
    ])
    
    chain = prompt | llm
    response = chain.invoke({
        "task_type": task_type,
        "modality": config.get("modality", "unknown"),
        "n_samples": analysis_result["n_samples"],
        "n_radiomics_features": len(feature_info.get("feature_names", [])),
        "n_selected": len(analysis_result["selected_features"]),
        "selected_features": ", ".join(analysis_result["selected_features"][:5]) + ("..." if len(analysis_result["selected_features"]) > 5 else ""),
        "covariates": ", ".join(config.get("covariates", [])) or "None",
        "model_name": model_name,
        "metric_name": metric_name,
        "metric_value": metric_value,
        "ci_lower": f"{ci[0]:.3f}" if ci[0] is not None else "N/A",
        "ci_upper": f"{ci[1]:.3f}" if ci[1] is not None else "N/A",
    })
    
    return response.content.strip()
```

### 8.4 原生 OpenAI SDK 回退方案

```python
# llm.py — 若 LangChain 搭不起来，用这个版本
import openai
import os

def call_deepseek(messages: list, temperature: float = 0.0, max_tokens: int = 512) -> str:
    """
    原生 OpenAI SDK 调用 DeepSeek V4。
    
    Parameters
    ----------
    messages : list[dict]
        OpenAI 格式的 messages 列表。
    
    Returns
    -------
    str
        LLM 返回的文本内容。
    """
    client = openai.OpenAI(
        api_key=os.environ.get("DEEPSEEK_API_KEY"),
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    )
    
    response = client.chat.completions.create(
        model="deepseek-v4",  # fallback: "deepseek-chat"
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    
    return response.choices[0].message.content


# 意图解析（原生版本）
def parse_intent_native(user_request: str, column_names: list) -> dict:
    import json
    
    messages = [
        {"role": "system", "content": INTENT_PARSE_SYSTEM},
        {"role": "user", "content": INTENT_PARSE_USER_TEMPLATE.format(
            user_request=user_request,
            column_names=", ".join(column_names),
        )},
    ]
    
    content = call_deepseek(messages, temperature=0.0)
    content = content.replace("```json", "").replace("```", "").strip()
    
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"task_type": "unknown", "covariates": [], "reasoning": "Parse error"}
```

---

## 9. 异常处理清单

### 9.1 Orchestrator 层级异常

| 异常场景 | 触发位置 | 处理逻辑 | 用户可见信息 |
|----------|----------|----------|--------------|
| 阶段未注册 handler | `_run_stage()` | 返回 False，进入 INTERRUPTED | "阶段 X 未注册 handler，请联系负责人" |
| Agent 返回非 dict | `_run_stage()` | 返回 False | "阶段 X 返回格式异常" |
| Agent 返回缺 `success` | `_run_stage()` | 返回 False | "阶段 X 返回缺少 success 字段" |
| 样本量 < 30 | `ANALYSIS` 前 | 返回 False | "有效样本仅 N 例，需要 ≥ 30 例才能进行可靠的 LASSO 分析" |
| 用户决策非法 | `resume()` | 忽略，保持 INTERRUPTED | — |
| resume() 在非中断状态调用 | `resume()` | 发送 error 事件，不操作 | "只能在流水线中断后调用恢复" |

### 9.2 跨阶段一致性检查

Orchestrator 在阶段推进时自动执行以下检查（在 `_run_stage()` 的成功分支中）：

```python
# 在 _run_stage 中，阶段成功后增加跨阶段校验

if stage == PipelineStage.MATCHING:
    # 检查匹配率
    matched = len(self.state["matching"]["matched_ids"])
    total = len(self.state["discovery"]["pairs"])
    ratio = matched / total if total > 0 else 0
    if ratio < 0.5:
        self._emit(self._make_event("warning", f"ID 匹配率仅 {ratio*100:.1f}%，建议检查文件名或表格 ID 列"))

if stage == PipelineStage.QC:
    # 检查 QC 通过率
    passed = len(self.state["qc"]["passed_pairs"])
    total = len(self.state["matching"]["matched_ids"])
    ratio = passed / total if total > 0 else 0
    if ratio < 0.3:
        # 不中断，但强烈警告
        self._emit(self._make_event("warning", f"QC 通过率仅 {ratio*100:.1f}%，大量样本被排除"))

if stage == PipelineStage.FEATURE:
    # 检查特征矩阵是否全零
    feature_df = self.state["feature"]["feature_df"]
    if (feature_df == 0).all().all():
        return False, "特征矩阵全为零，请检查 mask 是否正确勾画"
```

### 9.3 下游 Agent 异常（供各 Agent 实现参考）

| 异常 | 触发 Agent | 建议行为 |
|------|-----------|----------|
| 空 mask（全零） | QC | `failed_checks.append({"reason": "Empty mask"})` |
| image/mask 尺寸不匹配 | QC | `failed_checks.append({"reason": "Size mismatch"})` |
| 影像读取失败（损坏文件） | QC | `failed_checks.append({"reason": "Read error"})` |
| 临床表格无 ID 列 | Clinical | `success=False, message="未识别到患者 ID 列"` |
| 表格 ID 全重复 | Matching | `success=False, message="ID 列存在重复值"` |
| LASSO 未选中任何特征 | Analysis | 抛异常 `ValueError`，被 Orchestrator 捕获 |
| CoxPH 收敛失败 | Analysis | `success=False, message="CoxPH 模型不收敛，可能存在完全分离"` |
| 回归矩阵奇异 | Analysis | `success=False, message="特征存在多重共线性"` |
| Word 模板缺失 | Report | `success=False, message="报告模板文件缺失"` |

---

## 10. 完整可运行骨架代码

以下是 `orchestrator.py` 的完整骨架，**可直接复制作为开发起点**。

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
orchestrator.py — AutoRadiomics Agent 中央状态机

职责：
- 维护全局 state dict，按固定顺序调度 8 个 Agent
- 通过 SSE 向前端推送进度事件
- 处理中断（retry / skip / abort）与恢复

非职责：
- 不直接读取医学影像
- 不直接调用 LLM
- 不直接生成 Word 报告
"""

from __future__ import annotations

import os
import traceback
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

import pandas as pd


# =============================================================================
# 1. PipelineStage 枚举
# =============================================================================

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


STAGE_ORDER: List[PipelineStage] = [
    PipelineStage.DISCOVERY,
    PipelineStage.CLINICAL,
    PipelineStage.MATCHING,
    PipelineStage.QC,
    PipelineStage.FEATURE,
    PipelineStage.MERGE,
    PipelineStage.ANALYSIS,
    PipelineStage.REPORT,
]


def _get_next_stage(current: PipelineStage) -> Optional[PipelineStage]:
    try:
        idx = STAGE_ORDER.index(current)
        return STAGE_ORDER[idx + 1] if idx + 1 < len(STAGE_ORDER) else None
    except ValueError:
        return None


# =============================================================================
# 2. Orchestrator 类
# =============================================================================

class Orchestrator:
    """AutoRadiomics Agent 中央状态机。"""

    def __init__(
        self,
        image_dir: str,
        clinical_path: str,
        user_request: str = "",
        output_dir: str = "./output",
        modality: str = "auto",
        covariates: Optional[List[str]] = None,
        n_jobs: int = -1,
        target_spacing: Optional[Tuple[float, float, float]] = None,
    ):
        self.state: Dict[str, Any] = {
            "stage": PipelineStage.IDLE,
            "previous_stage": PipelineStage.IDLE,
            "user_request": user_request,
            "work_dir": output_dir,
            "config": {
                "image_dir": image_dir,
                "clinical_path": clinical_path,
                "output_dir": output_dir,
                "modality": modality,
                "task_type": None,
                "covariates": covariates or [],
                "skip_stages": [],
                "n_jobs": n_jobs,
                "target_spacing": target_spacing,
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

    # -------------------------------------------------------------------------
    # 注册与配置
    # -------------------------------------------------------------------------

    def register_handler(self, stage: PipelineStage, handler: Callable[[Dict], Dict]) -> None:
        if stage in STAGE_ORDER:
            self._stage_handlers[stage] = handler
        else:
            raise ValueError(f"Cannot register non-pipeline stage: {stage}")

    def set_sse_emitter(self, emitter: Callable[[Dict], None]) -> None:
        self._sse_emitter = emitter

    # -------------------------------------------------------------------------
    # 核心驱动
    # -------------------------------------------------------------------------

    def run(self) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
        """主驱动循环。"""
        self.state["stage"] = PipelineStage.IDLE
        self._emit(self._make_event("pipeline_start", "Pipeline started"))

        current: Optional[PipelineStage] = PipelineStage.DISCOVERY

        while current is not None and current not in (
            PipelineStage.COMPLETED,
            PipelineStage.FAILED,
        ):
            self.state["stage"] = current

            if current.name in self.state["config"]["skip_stages"]:
                self._emit(self._make_event("stage_skip", f"Skip stage: {current.name}"))
                current = _get_next_stage(current)
                continue

            success, error_msg = self._run_stage(current)

            if not success:
                self.state["interrupted_at"] = current
                self.state["previous_stage"] = current
                self.state["stage"] = PipelineStage.INTERRUPTED
                self.state["error_log"].append(f"[{current.name}] {error_msg}")
                self._emit(self._make_event(
                    "stage_interrupt",
                    f"Stage {current.name} interrupted: {error_msg}",
                    {"error": error_msg, "stage": current.name},
                ))
                return self.state

            current = _get_next_stage(current)

        if current is None:
            self.state["stage"] = PipelineStage.COMPLETED
            self._emit(self._make_event("pipeline_complete", "Pipeline completed"))
        else:
            self.state["stage"] = PipelineStage.FAILED
            self._emit(self._make_event("pipeline_fail", "Pipeline failed"))

        return self.state

    def _run_stage(self, stage: PipelineStage) -> Tuple[bool, str]:
        """Execute a single stage."""
        handler = self._stage_handlers.get(stage)
        if handler is None:
            return False, f"Stage {stage.name} has no registered handler"

        self._emit(self._make_event("stage_start", f"Start: {stage.name}", {"stage": stage.name}))

        try:
            # Pre-check sample size before ANALYSIS
            if stage == PipelineStage.ANALYSIS:
                n = self._get_merged_sample_count()
                if n < 30:
                    return False, f"Insufficient samples: {n} (required ≥ 30)"

            result = handler(self.state)

            if not isinstance(result, dict):
                return False, f"Stage {stage.name} returned non-dict: {type(result)}"
            if "success" not in result:
                return False, f"Stage {stage.name} result missing 'success' key"

            stage_key = stage.name.lower()
            self.state[stage_key] = result

            if not result["success"]:
                return False, result.get("message", "Unknown error")

            # Cross-stage validation
            self._validate_stage_transition(stage)

            self._emit(self._make_event(
                "stage_complete",
                f"Complete: {stage.name}",
                {"stage": stage.name, "details": result.get("message", "")},
            ))
            return True, ""

        except Exception as e:
            tb = traceback.format_exc()
            error_msg = f"{stage.name} exception: {str(e)}\n{tb}"
            self.state["error_log"].append(error_msg)
            self._emit(self._make_event(
                "stage_error",
                error_msg,
                {"stage": stage.name, "error": str(e), "traceback": tb},
            ))
            return False, error_msg

    def _validate_stage_transition(self, stage: PipelineStage) -> None:
        """Cross-stage consistency checks after a stage succeeds."""
        if stage == PipelineStage.MATCHING:
            matched = len(self.state["matching"]["matched_ids"])
            total = len(self.state["discovery"]["pairs"])
            ratio = matched / total if total > 0 else 0
            if ratio < 0.5:
                self._emit(self._make_event(
                    "warning",
                    f"Low matching ratio: {ratio*100:.1f}%",
                ))

        if stage == PipelineStage.QC:
            passed = len(self.state["qc"]["passed_pairs"])
            total = len(self.state["matching"]["matched_ids"])
            ratio = passed / total if total > 0 else 0
            if ratio < 0.3:
                self._emit(self._make_event(
                    "warning",
                    f"Low QC pass rate: {ratio*100:.1f}%",
                ))

        if stage == PipelineStage.FEATURE:
            df = self.state["feature"]["feature_df"]
            if (df == 0).all().all():
                raise ValueError("Feature matrix is all zeros")

    # -------------------------------------------------------------------------
    # 中断恢复
    # -------------------------------------------------------------------------

    def resume(self, user_decision: str) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
        """Resume pipeline after user decision."""
        if self.state["stage"] != PipelineStage.INTERRUPTED:
            self._emit(self._make_event("error", "resume() called but not interrupted"))
            return self.state

        self.state["user_decision"] = user_decision
        interrupted_stage = self.state.get("interrupted_at")

        if user_decision == "abort":
            self.state["stage"] = PipelineStage.FAILED
            self._emit(self._make_event("pipeline_fail", "User aborted"))
            return self.state

        if user_decision == "skip":
            if interrupted_stage:
                self.state["config"]["skip_stages"].append(interrupted_stage.name)
            self._emit(self._make_event("stage_skip", f"Skip: {interrupted_stage.name if interrupted_stage else 'unknown'}"))
            next_stage = _get_next_stage(interrupted_stage) if interrupted_stage else None
            if next_stage is None:
                self.state["stage"] = PipelineStage.COMPLETED
                self._emit(self._make_event("pipeline_complete", "Completed (last stage skipped)"))
                return self.state
            return self._continue_from(next_stage)

        if user_decision == "retry":
            self._emit(self._make_event("stage_retry", f"Retry: {interrupted_stage.name if interrupted_stage else 'unknown'}"))
            return self._continue_from(interrupted_stage)

        self._emit(self._make_event("error", f"Unknown decision: {user_decision}"))
        return self.state

    def _continue_from(self, stage: PipelineStage) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
        """Internal driver continuation from a given stage."""
        current: Optional[PipelineStage] = stage

        while current is not None and current not in (
            PipelineStage.COMPLETED,
            PipelineStage.FAILED,
        ):
            self.state["stage"] = current

            if current.name in self.state["config"]["skip_stages"]:
                self._emit(self._make_event("stage_skip", f"Skip stage: {current.name}"))
                current = _get_next_stage(current)
                continue

            success, error_msg = self._run_stage(current)

            if not success:
                self.state["interrupted_at"] = current
                self.state["previous_stage"] = current
                self.state["stage"] = PipelineStage.INTERRUPTED
                self.state["error_log"].append(f"[{current.name}] {error_msg}")
                self._emit(self._make_event(
                    "stage_interrupt",
                    f"Stage {current.name} interrupted: {error_msg}",
                    {"error": error_msg, "stage": current.name},
                ))
                return self.state

            current = _get_next_stage(current)

        if current is None:
            self.state["stage"] = PipelineStage.COMPLETED
            self._emit(self._make_event("pipeline_complete", "Pipeline completed"))
        else:
            self.state["stage"] = PipelineStage.FAILED
            self._emit(self._make_event("pipeline_fail", "Pipeline failed"))

        return self.state

    # -------------------------------------------------------------------------
    # 辅助方法
    # -------------------------------------------------------------------------

    def _get_merged_sample_count(self) -> int:
        """Estimate valid sample count before ANALYSIS."""
        if self.state.get("merged") and isinstance(self.state["merged"], dict):
            return self.state["merged"].get("n_samples", 0)

        qc_passed = self.state.get("qc", {}).get("passed_pairs", [])
        matched_ids = self.state.get("matching", {}).get("matched_ids", [])
        qc_ids = {p["patient_id"] for p in qc_passed}
        return len(set(matched_ids) & qc_ids)

    def _emit(self, event: Dict[str, Any]) -> None:
        if self._sse_emitter:
            self._sse_emitter(event)

    def _make_event(
        self,
        event_type: str,
        message: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        event: Dict[str, Any] = {
            "type": event_type,
            "message": message,
            "stage": self.state["stage"].name,
        }
        if payload:
            event["payload"] = payload
        return event


# =============================================================================
# 3. Merge 阶段（Orchestrator 内置）
# =============================================================================

def run_merge(state: Dict[str, Any]) -> Dict[str, Any]:
    """Merge feature matrix with clinical data on patient_id."""
    feature_df = state["feature"]["feature_df"]
    clinical_df = state["matching"]["matched_df"].copy()

    clinical_df["patient_id"] = clinical_df["patient_id"].astype(str)
    clinical_df = clinical_df.set_index("patient_id")

    merged = clinical_df.join(feature_df, how="inner")

    return {
        "success": True,
        "message": f"Merged: {len(merged)} samples × {len(state['feature']['feature_names'])} features",
        "df": merged,
        "n_samples": len(merged),
        "n_features": len(state["feature"]["feature_names"]),
    }


# =============================================================================
# 4. 注册辅助函数（在 main.py 中使用）
# =============================================================================

def create_orchestrator_with_handlers(
    image_dir: str,
    clinical_path: str,
    user_request: str = "",
    **kwargs,
) -> Orchestrator:
    """
    工厂函数：创建 Orchestrator 并注册所有 Agent handlers。
    在 main.py 中调用。
    """
    orch = Orchestrator(
        image_dir=image_dir,
        clinical_path=clinical_path,
        user_request=user_request,
        **kwargs,
    )

    # 延迟导入各 Agent 模块，避免循环依赖
    # from discovery import run_discovery
    # from clinical import run_clinical
    # from matching import run_matching
    # from qc import run_qc
    # from feature import run_feature
    # from analysis import run_analysis
    # from report import run_report

    # orch.register_handler(PipelineStage.DISCOVERY, run_discovery)
    # orch.register_handler(PipelineStage.CLINICAL, run_clinical)
    # orch.register_handler(PipelineStage.MATCHING, run_matching)
    # orch.register_handler(PipelineStage.QC, run_qc)
    # orch.register_handler(PipelineStage.FEATURE, run_feature)
    # orch.register_handler(PipelineStage.ANALYSIS, run_analysis)
    # orch.register_handler(PipelineStage.REPORT, run_report)

    # MERGE 不注册为 handler，由 Orchestrator 内置执行
    # 在 FEATURE 之后、ANALYSIS 之前自动调用

    return orch


# =============================================================================
# 5. 主入口（命令行测试用）
# =============================================================================

if __name__ == "__main__":
    # 终端测试：python orchestrator.py --dir /data --clinical clinical.csv
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True, help="Image directory")
    parser.add_argument("--clinical", required=True, help="Clinical table path")
    parser.add_argument("--prompt", default="", help="User request")
    parser.add_argument("--output", default="./output", help="Output directory")
    args = parser.parse_args()

    orch = Orchestrator(
        image_dir=args.dir,
        clinical_path=args.clinical,
        user_request=args.prompt,
        output_dir=args.output,
    )

    # 打印 SSE 事件到终端（无前端时的调试方式）
    orch.set_sse_emitter(lambda e: print(f"[SSE] {e['type']}: {e['message']}"))

    # 注册 Mock handlers（Day 1 调试用）
    def mock_handler(state):
        import time
        time.sleep(0.5)
        return {"success": True, "message": f"Mock {state['stage'].name} done"}

    for stage in STAGE_ORDER:
        if stage != PipelineStage.MERGE:
            orch.register_handler(stage, mock_handler)

    # 运行
    for event in orch.run():
        pass  # Generator 已消费

    print(f"\nFinal state: {orch.state['stage'].name}")
    print(f"Errors: {orch.state['error_log']}")
```

---

## 附录 A：文件结构建议

```
app/
├── __init__.py
├── main.py                    # 入口：解析 CLI 参数，创建 Orchestrator，启动 Gradio
├── orchestrator.py            # 本文档对应的实现文件
├── llm.py                     # DeepSeek API 封装（PromptTemplate + Runnable / 原生 SDK）
├── discovery.py               # Discovery Agent（同学 A）
├── qc.py                      # QC Agent（同学 A）
├── clinical.py                # Clinical Agent（同学 B）
├── matching.py                # Matching Agent（同学 B）
├── feature.py                 # Feature Agent（同学 B）
├── analysis.py                # Analysis Agent（同学 B）
├── report.py                  # Report Agent（同学 B）
├── ui.py                      # Gradio 前端（同学 C）
└── templates/
    └── report_template.docx   # Word 报告模板（可选）
```

## 附录 B：main.py 示例

```python
#!/usr/bin/env python3
"""main.py — AutoRadiomics Agent 入口"""

import argparse
import os
from orchestrator import Orchestrator, PipelineStage

def main():
    parser = argparse.ArgumentParser(description="AutoRadiomics Agent")
    parser.add_argument("--dir", required=True, help="影像文件夹路径")
    parser.add_argument("--clinical", required=True, help="临床表格路径")
    parser.add_argument("--prompt", default="", help="分析意图描述")
    parser.add_argument("--output", default="./output", help="输出目录")
    parser.add_argument("--modality", default="auto", choices=["CT", "MRI", "auto"])
    parser.add_argument("--n-jobs", type=int, default=-1, help="并行核数")
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    orch = Orchestrator(
        image_dir=args.dir,
        clinical_path=args.clinical,
        user_request=args.prompt,
        output_dir=args.output,
        modality=args.modality,
        n_jobs=args.n_jobs,
    )

    # 注册各 Agent handler
    from discovery import run_discovery
    from clinical import run_clinical
    from matching import run_matching
    from qc import run_qc
    from feature import run_feature
    from analysis import run_analysis
    from report import run_report

    orch.register_handler(PipelineStage.DISCOVERY, run_discovery)
    orch.register_handler(PipelineStage.CLINICAL, run_clinical)
    orch.register_handler(PipelineStage.MATCHING, run_matching)
    orch.register_handler(PipelineStage.QC, run_qc)
    orch.register_handler(PipelineStage.FEATURE, run_feature)
    orch.register_handler(PipelineStage.ANALYSIS, run_analysis)
    orch.register_handler(PipelineStage.REPORT, run_report)

    # SSE 打印到终端
    orch.set_sse_emitter(lambda e: print(f"[{e['stage']}] {e['type']}: {e['message']}"))

    # 运行流水线
    for _ in orch.run():
        pass

    print(f"\n✓ 流水线结束，状态: {orch.state['stage'].name}")
    if orch.state['stage'] == PipelineStage.COMPLETED:
        print(f"报告路径: {orch.state['report']['report_path']}")

if __name__ == "__main__":
    main()
```

---

*文档结束。本文档作为 Orchestrator 的详细实现蓝图，各 Agent 开发者应同时阅读本文档中与自己相关的接口契约部分。*
