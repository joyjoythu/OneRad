# Analysis Agent 实现方案

> 对应文件：`app/analysis.py`  
> 负责人：同学 B（临床分析模块）  
> 依赖：`scikit-learn`, `lifelines`, `pandas`, `numpy`, `scipy`, `sklearn`  
> 上游输入：Merge Agent 输出的 `merged_df`（影像组学特征 + 临床特征 + 标签列）  
> 下游输出：Report Agent 所需的 `statistical_result` 字典

---

## 一、职责与定位

Analysis Agent 是整个 AutoRadiomics 流水线中**最核心的统计计算节点**，位于流水线倒数第二位：

```
Discovery → Clinical → Matching → QC → Feature → Merge → Analysis → Report
```

### 核心职责
1. **分析类型自动判断**：根据合并后数据中 Label 列的值分布，自动判断应走二分类分支（LASSO + Logistic Regression）还是生存分析分支（LASSO + CoxPH）。
2. **特征筛选**：使用 LASSO 回归从大量影像组学特征中筛选出非零系数的重要特征。
3. **统计建模**：
   - 二分类任务：Logistic Regression（可选结合临床协变量），输出 OR、95% CI、p 值、AUC。
   - 生存分析任务：Cox Proportional Hazards（CoxPH），输出 HR、95% CI、p 值、C-index。
4. **结果封装**：将所有统计量格式化为结构化字典，供 Report Agent 直接填入 Word 模板。

### 分析类型判断规则

| 条件 | 分析类型 | 算法路径 | 输出指标 |
|------|----------|----------|----------|
| Label 列仅有 0/1 两个取值 | 二分类（Binary Classification） | LASSO → Logistic Regression | AUC, 灵敏度, 特异度, OR, 95% CI, p 值 |
| 数据同时包含 `time`（时间）和 `event`（事件）列 | 生存分析（Survival Analysis） | LASSO → CoxPH | C-index, HR, 95% CI, p 值, Kaplan-Meier 描述 |

**注意**：系统**暂不支持多分类**（Label 有 >2 个类别时直接中断，提示用户）。

---

## 二、上下游接口契约

### 2.1 上游输入（来自 Merge Agent）

Merge Agent 将影像组学特征矩阵、临床特征表、ID 对齐后的标签列合并为一个 `pandas.DataFrame`，通过 `state` 字典传递给 Analysis Agent。

```python
# 从 state 字典中读取的输入
merged_df: pd.DataFrame      # 合并后的数据，列包括：
                             #   - ID 列（如 PatientID）
                             #   - 影像组学特征列（如 original_firstorder_Mean...）
                             #   - 临床特征列（如 Age, Sex, Stage...）
                             #   - 标签列：Label（0/1）或 Time + Event（生存）

# 列名已由 Clinical Agent 通过 LLM 识别，由 Merge Agent 统一重命名
# 生存分析时：Label 被拆分为 time_col（如 "OS_months"）和 event_col（如 "OS_event"）

# 额外元信息（由 Merge Agent 写入 state）
clinical_info: dict = {
    "id_col": str,           # 如 "PatientID"
    "label_col": str,        # 二分类时为 "Label"；生存分析时为 None
    "time_col": str,         # 生存分析时，如 "OS_months"
    "event_col": str,        # 生存分析时，如 "OS_event"
    "feature_cols": List[str],  # 临床特征列名（不含影像组学特征）
    "n_samples": int,        # 样本数
    "n_radiomic_features": int,  # 影像组学特征数（由 Feature Agent 输出）
    "n_clinical_features": int,  # 临床特征数
}

user_prompt: str             # 用户原始任务描述，如"预测生存，调整 Age 和 Stage"
```

### 2.2 下游输出（传递给 Report Agent）

Analysis Agent 执行完成后，将以下 `statistical_result` 字典写入 `state`：

```python
statistical_result: dict = {
    # === 元信息 ===
    "analysis_type": str,          # "binary_classification" | "survival_analysis"
    "n_samples": int,              # 最终进入分析的样本数
    "n_features_before_lasso": int,  # LASSO 前特征总数
    "n_features_after_lasso": int,   # LASSO 后保留特征数
    "covariates_used": List[str],  # 用户指定的调整协变量
    
    # === LASSO 筛选结果 ===
    "lasso_selected_features": List[str],  # 被 LASSO 选中的特征名
    "lasso_alpha": float,          # 最优 alpha 值（通过交叉验证）
    "lasso_cv_scores": List[float],  # 交叉验证得分（可选）
    
    # === 二分类结果（analysis_type == "binary_classification" 时） ===
    "binary": {
        "model_type": str,         # "logistic_regression"
        "coefficients": Dict[str, float],   # 特征名 → 回归系数
        "odds_ratios": Dict[str, float],    # 特征名 → OR 值
        "ci_lower": Dict[str, float],       # OR 95% CI 下限
        "ci_upper": Dict[str, float],       # OR 95% CI 上限
        "p_values": Dict[str, float],       # 特征名 → p 值（Wald 检验）
        "auc": float,              # 测试集 AUC（或交叉验证平均 AUC）
        "auc_ci": Tuple[float, float],  # AUC 95% CI（DeLong 方法或 Bootstrap）
        "sensitivity": float,        # 灵敏度
        "specificity": float,        # 特异度
        "threshold": float,          # 最优阈值（Youden index）
        "confusion_matrix": List[List[int]],  # 2×2 混淆矩阵
    },
    
    # === 生存分析结果（analysis_type == "survival_analysis" 时） ===
    "survival": {
        "model_type": str,         # "coxph"
        "coefficients": Dict[str, float],   # 特征名 → 回归系数
        "hazard_ratios": Dict[str, float],  # 特征名 → HR 值
        "ci_lower": Dict[str, float],       # HR 95% CI 下限
        "ci_upper": Dict[str, float],       # HR 95% CI 上限
        "p_values": Dict[str, float],       # 特征名 → p 值（log-rank / Wald）
        "c_index": float,          # C-index（Harrell's concordance index）
        "c_index_ci": Tuple[float, float],  # C-index 95% CI（Bootstrap）
        "median_survival_time": float,  # 中位生存时间（可选）
    },
    
    # === 异常标记（如有） ===
    "warnings": List[str],         # 警告信息列表，如样本量偏小、特征全零等
    "errors": List[str],           # 错误信息列表（非致命，可继续报告）
}
```

### 2.3 与 Orchestrator 的交互契约

Analysis Agent 必须遵循 Orchestrator 定义的状态机接口：

```python
# Orchestrator 调用的入口函数（由同学 B 实现，负责人 review）
def run_analysis_agent(state: dict) -> dict:
    """
    Analysis Agent 主入口。
    
    Args:
        state: 共享状态字典，包含上游所有输出。
        
    Returns:
        更新后的 state，新增/更新 key:
        - "statistical_result": 统计结果字典
        - "analysis_status": "success" | "failed" | "skipped"
        - "analysis_error": 失败时的错误信息（str 或 None）
    """
    pass
```

**约定**：
- `state` 字典通过引用传递，Analysis Agent 直接修改 `state` 并返回（或返回新 dict）。
- 如果执行失败，必须设置 `state["analysis_status"] = "failed"` 和 `state["analysis_error"] = "..."`。
- Orchestrator 检测到失败后，向用户展示中断界面，用户选择"跳过"或"终止"。
- 如果用户选择"跳过"，Orchestrator 设置 `state["analysis_status"] = "skipped"`，后续 Report Agent 需处理空统计结果。

---

## 三、核心模块设计与函数签名

### 3.1 模块总览

```python
# app/analysis.py

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Union
from dataclasses import dataclass, field
from sklearn.linear_model import LogisticRegression, LassoCV
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, confusion_matrix, roc_curve
from sklearn.model_selection import StratifiedKFold, cross_val_score
from lifelines import CoxPHFitter
from lifelines.utils import concordance_index
from scipy import stats
import warnings

# 从 llm.py 导入（由负责人封装）
from llm import parse_intent_with_llm

# 常量定义
MIN_SAMPLE_SIZE = 30  # 样本量不足阈值
MAX_LASSO_FEATURES = 100  # LASSO 最大特征数（防止高维崩溃）
CV_FOLDS = 5  # 交叉验证折数
```

### 3.2 数据类定义

```python
@dataclass
class AnalysisConfig:
    """分析配置，由 LLM 意图解析 + 自动推断生成。"""
    task_type: str  # "binary_classification" | "survival_analysis"
    covariates: List[str] = field(default_factory=list)  # 用户指定的调整协变量
    time_col: Optional[str] = None  # 生存分析时间列
    event_col: Optional[str] = None  # 生存分析事件列
    label_col: Optional[str] = None  # 二分类标签列
    id_col: str = "PatientID"
    use_clinical: bool = True  # 是否将临床特征纳入建模（作为协变量）

@dataclass
class LassoResult:
    """LASSO 筛选结果。"""
    selected_features: List[str]
    alpha: float
    coefficients: Dict[str, float]
    cv_mean_score: float
    cv_std_score: float

@dataclass
class BinaryResult:
    """二分类分析结果。"""
    coefficients: Dict[str, float]
    odds_ratios: Dict[str, float]
    ci_lower: Dict[str, float]
    ci_upper: Dict[str, float]
    p_values: Dict[str, float]
    auc: float
    auc_ci: Tuple[float, float]
    sensitivity: float
    specificity: float
    threshold: float
    confusion_matrix: np.ndarray

@dataclass
class SurvivalResult:
    """生存分析结果。"""
    coefficients: Dict[str, float]
    hazard_ratios: Dict[str, float]
    ci_lower: Dict[str, float]
    ci_upper: Dict[str, float]
    p_values: Dict[str, float]
    c_index: float
    c_index_ci: Tuple[float, float]
```

### 3.3 主入口函数

```python
def run_analysis_agent(state: dict) -> dict:
    """
    Analysis Agent 主入口。
    
    执行流程：
    1. 从 state 提取数据与元信息
    2. 检查样本量（<30 则中断）
    3. 调用 LLM 解析用户意图（确定 task_type 和 covariates）
    4. 自动推断分析类型（验证 LLM 结果与数据一致性）
    5. 数据预处理（标准化、缺失值处理）
    6. LASSO 特征筛选
    7. 根据分析类型执行 Logistic Regression 或 CoxPH
    8. 封装结果写入 state
    
    Args:
        state: 共享状态字典，必须包含：
            - "merged_df": pd.DataFrame
            - "clinical_info": dict
            - "user_prompt": str
            
    Returns:
        更新后的 state，新增 key：
            - "statistical_result": dict
            - "analysis_status": "success" | "failed" | "skipped"
            - "analysis_error": str | None
            - "warnings": List[str]
    """
    state["analysis_status"] = "running"
    state["analysis_error"] = None
    state["warnings"] = []
    
    try:
        # 1. 提取数据
        merged_df = state.get("merged_df")
        clinical_info = state.get("clinical_info", {})
        user_prompt = state.get("user_prompt", "")
        
        if merged_df is None or merged_df.empty:
            raise ValueError("merged_df 为空或不存在，请检查上游 Merge Agent 输出。")
        
        n_samples = len(merged_df)
        if n_samples < MIN_SAMPLE_SIZE:
            raise InsufficientSampleError(
                f"样本量不足：当前 n={n_samples}，最低要求 n={MIN_SAMPLE_SIZE}。"
                f"请补充数据后重新运行，或选择跳过此步骤。"
            )
        
        # 2. 解析意图（LLM 调用点 #1：意图解析）
        config = _parse_intent(
            user_prompt=user_prompt,
            clinical_info=clinical_info,
            merged_df=merged_df
        )
        
        # 3. 自动推断与验证分析类型
        config = _validate_and_infer_task_type(config, merged_df, clinical_info)
        
        # 4. 数据预处理
        X, y, time, event, feature_names = _prepare_data(
            merged_df=merged_df,
            config=config,
            clinical_info=clinical_info
        )
        
        # 5. LASSO 特征筛选
        lasso_result = _run_lasso(
            X=X, y=y,
            task_type=config.task_type,
            feature_names=feature_names
        )
        
        # 6. 根据分析类型执行建模
        if config.task_type == "binary_classification":
            result = _run_binary_analysis(
                X=X, y=y,
                lasso_result=lasso_result,
                config=config,
                feature_names=feature_names
            )
        elif config.task_type == "survival_analysis":
            result = _run_survival_analysis(
                X=X, time=time, event=event,
                lasso_result=lasso_result,
                config=config,
                feature_names=feature_names
            )
        else:
            raise ValueError(f"不支持的分析类型: {config.task_type}")
        
        # 7. 封装结果
        statistical_result = _package_results(
            config=config,
            lasso_result=lasso_result,
            result=result,
            n_samples=n_samples,
            feature_names=feature_names
        )
        
        state["statistical_result"] = statistical_result
        state["analysis_status"] = "success"
        
    except InsufficientSampleError as e:
        state["analysis_status"] = "failed"
        state["analysis_error"] = str(e)
        # 样本量不足属于可中断异常，需让用户选择
        raise  # 抛给 Orchestrator 处理
        
    except Exception as e:
        state["analysis_status"] = "failed"
        state["analysis_error"] = f"Analysis Agent 异常: {type(e).__name__}: {str(e)}"
        state["warnings"].append(str(e))
        # 其他异常：记录后允许 Orchestrator 决定是否中断
        
    return state
```

### 3.4 意图解析（LLM 调用点）

```python
def _parse_intent(
    user_prompt: str,
    clinical_info: dict,
    merged_df: pd.DataFrame
) -> AnalysisConfig:
    """
    调用 LLM 解析用户意图，确定分析类型和协变量。
    
    如果 user_prompt 为空或模糊，自动推断为最常见的分析类型。
    """
    # 先尝试自动推断（无需 LLM）
    auto_type = _auto_infer_task_type(merged_df, clinical_info)
    
    # 如果用户未提供 prompt，直接返回自动推断结果
    if not user_prompt or user_prompt.strip() == "":
        return AnalysisConfig(
            task_type=auto_type,
            covariates=[],
            time_col=clinical_info.get("time_col"),
            event_col=clinical_info.get("event_col"),
            label_col=clinical_info.get("label_col"),
            id_col=clinical_info.get("id_col", "PatientID"),
        )
    
    # 构造 LLM 调用
    column_names = list(merged_df.columns)
    prompt = _build_intent_prompt(user_prompt, column_names, auto_type)
    
    # 调用 LLM（通过 llm.py 封装）
    response = parse_intent_with_llm(prompt)
    
    # 解析 LLM 返回的 JSON
    config = AnalysisConfig(
        task_type=response.get("task_type", auto_type),
        covariates=response.get("covariates", []),
        time_col=clinical_info.get("time_col"),
        event_col=clinical_info.get("event_col"),
        label_col=clinical_info.get("label_col"),
        id_col=clinical_info.get("id_col", "PatientID"),
    )
    
    return config


def _auto_infer_task_type(
    merged_df: pd.DataFrame,
    clinical_info: dict
) -> str:
    """
    根据数据自动推断分析类型（无需 LLM）。
    
    优先级：
    1. 如果存在 time_col 和 event_col，且 event 有 0/1 → survival_analysis
    2. 如果 label_col 存在且只有 0/1 → binary_classification
    3. 否则 → 抛出异常（不支持的分析类型）
    """
    time_col = clinical_info.get("time_col")
    event_col = clinical_info.get("event_col")
    label_col = clinical_info.get("label_col")
    
    if time_col and event_col and time_col in merged_df.columns and event_col in merged_df.columns:
        event_unique = merged_df[event_col].dropna().unique()
        if set(event_unique).issubset({0, 1}):
            return "survival_analysis"
    
    if label_col and label_col in merged_df.columns:
        label_unique = merged_df[label_col].dropna().unique()
        if set(label_unique).issubset({0, 1}):
            return "binary_classification"
    
    raise ValueError(
        "无法自动推断分析类型。数据既无有效的 0/1 Label 列，"
        "也无 Time + Event 列。请检查 Clinical Agent 的列名识别结果。"
    )
```

---

## 四、LLM Prompt 模板（意图解析）

这是 Analysis Agent 唯一的 LLM 调用点。Prompt 需通过 `llm.py` 中负责人封装的接口发送给 DeepSeek V4 API。

### 4.1 System Message

```python
INTENT_SYSTEM_PROMPT = """You are an expert biostatistician and radiomics researcher. 
Your task is to parse the user's natural language description of a radiomics analysis task 
and extract structured intent parameters.

Rules:
1. The output must be a valid JSON object with no markdown formatting.
2. task_type must be exactly one of: "binary_classification" or "survival_analysis".
3. covariates should be a list of column names mentioned by the user that should be adjusted for in the regression model. If none are mentioned, return an empty list [].
4. Do not guess column names that are not in the provided column list.
5. If the user mentions "survival", "OS", "PFS", "DFS", "time-to-event", "Cox", or "hazard", task_type is "survival_analysis".
6. If the user mentions "predict", "classification", "diagnosis", "binary", "AUC", or "logistic", task_type is "binary_classification".
7. If the user's description is ambiguous, use the auto_inferred_type as default.
8. Respond in English only for JSON output; reasoning is not needed.
"""
```

### 4.2 User Message Template

```python
def _build_intent_prompt(user_prompt: str, column_names: List[str], auto_inferred_type: str) -> str:
    """构建意图解析的 user message。"""
    columns_str = "\n".join([f"  - {col}" for col in column_names])
    
    prompt = f"""User request: "{user_prompt}"

Available columns in the dataset:
{columns_str}

Auto-inferred analysis type: {auto_inferred_type}

Please extract the following and return as JSON:
{{
  "task_type": "binary_classification" or "survival_analysis",
  "covariates": ["ColumnName1", "ColumnName2"],
  "reasoning": "Brief explanation of why this task type was chosen"
}}

Requirements:
- covariates must be exact names from the Available columns list above.
- If the user did not mention any covariates to adjust for, return [] and set "adjust_for_clinical" to false.
- If the user explicitly says "adjust for Age and Stage", include ["Age", "Stage"] in covariates.
"""
    return prompt
```

### 4.3 LLM 调用封装（预期由 `llm.py` 提供）

```python
# 在 llm.py 中由负责人实现，对外暴露以下接口：

def parse_intent_with_llm(prompt: str) -> dict:
    """
    调用 DeepSeek V4 API 解析意图。
    
    Args:
        prompt: 完整的 user message（含 system prompt 拼接）。
        
    Returns:
        JSON 解析后的 dict，包含 task_type, covariates 等。
        
    Raises:
        LLMError: API 调用失败或返回非 JSON 时抛出。
    """
    # 实现细节由 llm.py 负责，可能使用 LangChain 或原生 OpenAI SDK
    pass
```

**回退策略**：如果 LLM 调用失败（网络错误、超时、非 JSON 返回），Analysis Agent 使用 `_auto_infer_task_type` 的结果继续执行，并在 `warnings` 中记录 "LLM 意图解析失败，已使用自动推断结果"。

---

## 五、数据预处理

```python
def _prepare_data(
    merged_df: pd.DataFrame,
    config: AnalysisConfig,
    clinical_info: dict
) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray], Optional[np.ndarray], List[str]]:
    """
    数据预处理：提取特征矩阵 X、标签 y / 生存数据 (time, event)。
    
    Returns:
        X: 特征矩阵 (n_samples, n_features)，已标准化
        y: 二分类标签 (n_samples,)，或 None（生存分析）
        time: 生存时间 (n_samples,)，或 None
        event: 事件指示 (n_samples,)，或 None
        feature_names: 特征名列表（含影像组学 + 临床协变量）
    """
    # 1. 识别影像组学特征列（命名约定：以 "original_" 或 "wavelet-" 或 "log-sigma_" 开头）
    radiomic_cols = [
        col for col in merged_df.columns
        if any(col.startswith(prefix) for prefix in ["original_", "wavelet-", "log-sigma_"])
    ]
    
    # 2. 识别临床协变量（config.covariates 中指定，且存在于数据中）
    clinical_cov_cols = [c for c in config.covariates if c in merged_df.columns]
    
    # 3. 合并特征列
    feature_cols = radiomic_cols + clinical_cov_cols
    
    if len(feature_cols) == 0:
        raise ValueError("未找到任何可用的特征列（影像组学或临床协变量）。请检查 Feature Agent 和 Clinical Agent 输出。")
    
    # 4. 提取特征矩阵
    X = merged_df[feature_cols].copy()
    
    # 5. 处理缺失值：中位数填充（数值型）/ 众数填充（分类型）
    for col in X.columns:
        if X[col].dtype in ["float64", "int64"]:
            X[col] = X[col].fillna(X[col].median())
        else:
            X[col] = X[col].fillna(X[col].mode()[0] if not X[col].mode().empty else "Unknown")
    
    # 6. 检查常数/全零特征
    constant_cols = X.columns[X.nunique() <= 1].tolist()
    if constant_cols:
        warnings.warn(f"以下特征为常数（无变异），将被移除: {constant_cols}")
        X = X.drop(columns=constant_cols)
        feature_cols = [c for c in feature_cols if c not in constant_cols]
    
    zero_variance_cols = X.columns[X.var() == 0].tolist()
    if zero_variance_cols:
        X = X.drop(columns=zero_variance_cols)
        feature_cols = [c for c in feature_cols if c not in zero_variance_cols]
    
    # 7. 标准化（Z-score）
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # 8. 提取标签/生存数据
    y = None
    time = None
    event = None
    
    if config.task_type == "binary_classification":
        label_col = config.label_col or clinical_info.get("label_col", "Label")
        if label_col not in merged_df.columns:
            raise ValueError(f"Label 列 '{label_col}' 不存在于合并数据中。")
        y = merged_df[label_col].values.astype(int)
        # 检查标签是否只有 0/1
        if not set(np.unique(y)).issubset({0, 1}):
            raise ValueError(f"Label 列包含非 0/1 值: {np.unique(y)}。当前仅支持二分类。")
            
    elif config.task_type == "survival_analysis":
        time_col = config.time_col or clinical_info.get("time_col")
        event_col = config.event_col or clinical_info.get("event_col")
        if time_col not in merged_df.columns or event_col not in merged_df.columns:
            raise ValueError(f"生存分析需要 '{time_col}' 和 '{event_col}' 列，但数据缺失。")
        time = merged_df[time_col].values.astype(float)
        event = merged_df[event_col].values.astype(int)
        # 检查 event 是否只有 0/1
        if not set(np.unique(event)).issubset({0, 1}):
            raise ValueError(f"Event 列包含非 0/1 值: {np.unique(event)}。")
        # 检查时间是否全为正
        if np.any(time <= 0):
            raise ValueError(f"生存时间必须 > 0，发现 {np.sum(time <= 0)} 个非正值。")
    
    return X_scaled, y, time, event, feature_cols
```

---

## 六、LASSO 特征筛选（核心算法）

LASSO 用于从高维影像组学特征中筛选出与结局最相关的特征。使用 `LassoCV` 自动通过交叉验证选择最优 `alpha`。

```python
def _run_lasso(
    X: np.ndarray,
    y: np.ndarray,
    task_type: str,
    feature_names: List[str],
    cv_folds: int = CV_FOLDS
) -> LassoResult:
    """
    使用 LASSO 进行特征筛选。
    
    对于二分类任务，使用 LogisticRegression(penalty='l1', solver='saga') + LassoCV 逻辑；
    对于生存任务，使用标准 LassoCV（Linear regression LASSO）。
    
    Args:
        X: 标准化后的特征矩阵 (n_samples, n_features)
        y: 标签（二分类时）或 None（生存分析时，此时需外部处理）
        task_type: 分析类型
        feature_names: 特征名列表
        cv_folds: 交叉验证折数
        
    Returns:
        LassoResult，包含被选中的特征列表和系数
    """
    # 样本量检查
    n_samples, n_features = X.shape
    if n_samples < MIN_SAMPLE_SIZE:
        raise InsufficientSampleError(f"LASSO 要求样本数 ≥ {MIN_SAMPLE_SIZE}，当前 n={n_samples}")
    
    # 特征数限制：如果特征数 > 样本数，LASSO 仍可运行，但需警告
    if n_features > n_samples:
        warnings.warn(
            f"特征数 ({n_features}) > 样本数 ({n_samples})，LASSO 可能过拟合。"
            "建议减少特征或增加样本。"
        )
    
    # 根据任务类型选择 LASSO 实现
    if task_type == "binary_classification":
        # 二分类：使用 LogisticRegression with L1 penalty
        # LassoCV 不支持 L1 Logistic，需手动搜索 alpha
        alphas = np.logspace(-4, 1, 50)  # 1e-4 到 10
        best_alpha = None
        best_score = -np.inf
        best_coefs = None
        
        cv = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=42)
        
        for alpha in alphas:
            model = LogisticRegression(
                penalty='l1',
                solver='saga',
                C=1.0/alpha,  # C = 1/alpha
                max_iter=10000,
                random_state=42,
                n_jobs=1
            )
            scores = cross_val_score(model, X, y, cv=cv, scoring='roc_auc')
            mean_score = scores.mean()
            
            if mean_score > best_score:
                best_score = mean_score
                best_alpha = alpha
                # 拟合全量数据获取系数
                model.fit(X, y)
                best_coefs = model.coef_[0]
        
        # 获取非零系数特征
        selected_indices = np.where(np.abs(best_coefs) > 1e-6)[0]
        selected_features = [feature_names[i] for i in selected_indices]
        coefficients = {feature_names[i]: best_coefs[i] for i in selected_indices}
        
        return LassoResult(
            selected_features=selected_features,
            alpha=best_alpha,
            coefficients=coefficients,
            cv_mean_score=best_score,
            cv_std_score=0.0  # 可扩展为记录标准差
        )
        
    else:  # survival_analysis
        # 生存分析：使用标准 LassoCV（Linear regression）
        # 注意：lifelines 无内置 LASSO，用 sklearn 的 LassoCV 对 time（可能需变换）
        # 实际做法：对 event=1 的样本拟合，或用 CoxPH + L1 正则化（更复杂）
        # 简化方案：使用 LassoCV 对 time 做回归，然后筛选特征，再用 CoxPH
        
        # 更合理的方案：使用 CoxPH 的 L1 正则化（通过罚函数）
        # 但 lifelines 原生不支持 L1 正则化，需手动实现
        # 替代方案：用 LogisticRegression L1 近似（将 time 分桶为二分类）——不推荐
        
        # 最佳实践：使用 sksurv（scikit-survival）的 CoxnetSurvivalAnalysis
        # 但为了避免引入新依赖，使用以下策略：
        # 1. 用 LassoCV 对 event 加权后的 time 进行筛选
        # 2. 或：对 event=1 的样本用 LassoCV 筛选
        
        # 这里采用标准 LassoCV 对 event=1 的样本的 time 做回归
        # 这不是完美的生存 LASSO，但能在无 sksurv 时工作
        # 如果团队允许安装 sksurv，建议替换为 CoxnetSurvivalAnalysis
        
        event_mask = (y == 1) if y is not None else np.ones(X.shape[0], dtype=bool)
        # 注意：生存分析时 y 传入的是 time，这里修正
        # 实际上对于生存分析，_run_lasso 的 y 参数应该是 time
        # 重新设计： survival 时传入 time 和 event
        
        raise NotImplementedError(
            "生存分析的 LASSO 需使用 sksurv.CoxnetSurvivalAnalysis 或手动实现。"
            "详见下方算法细节。"
        )
```

### 6.1 生存分析 LASSO 的改进实现（推荐）

由于 `lifelines` 不原生支持 L1 正则化的 CoxPH，推荐以下方案之一：

**方案 A：安装 `scikit-survival`（推荐，如果允许新增依赖）**

```python
# 需要安装：pip install scikit-survival
from sksurv.linear_model import CoxnetSurvivalAnalysis

def _run_lasso_survival(
    X: np.ndarray,
    time: np.ndarray,
    event: np.ndarray,
    feature_names: List[str],
    cv_folds: int = 5
) -> LassoResult:
    """
    使用 CoxnetSurvivalAnalysis（L1 正则化 CoxPH）进行特征筛选。
    """
    # 构造生存数据格式（sksurv 需要结构化数组）
    y_surv = np.array([
        (bool(e), t) for e, t in zip(event, time)
    ], dtype=[("event", bool), ("time", float)])
    
    # 搜索 alphas
    alphas = np.logspace(-3, 1, 30)
    
    model = CoxnetSurvivalAnalysis(l1_ratio=1.0, alphas=alphas, fit_baseline_model=True)
    
    # 交叉验证选择最优 alpha
    from sklearn.model_selection import cross_val_score
    # sksurv 需要自定义 scoring：concordance_index_censored
    
    # 简化：直接拟合，选择使非零系数适中的 alpha
    model.fit(X, y_surv)
    
    # 选择最优 alpha（例如，使 C-index 最大的 alpha）
    # 实际实现需根据 sksurv API 调整
    
    # 获取最优模型的系数
    best_coefs = model.coef_
    selected_indices = np.where(np.abs(best_coefs) > 1e-6)[0]
    selected_features = [feature_names[i] for i in selected_indices]
    coefficients = {feature_names[i]: best_coefs[i] for i in selected_indices}
    
    return LassoResult(
        selected_features=selected_features,
        alpha=model.alphas_[0],  # 需调整为最优 alpha
        coefficients=coefficients,
        cv_mean_score=0.0,
        cv_std_score=0.0
    )
```

**方案 B：不引入新依赖，用两步法（LASSO + CoxPH）**

```python
def _run_lasso_survival_fallback(
    X: np.ndarray,
    time: np.ndarray,
    event: np.ndarray,
    feature_names: List[str],
    cv_folds: int = 5
) -> LassoResult:
    """
    不依赖 sksurv 的生存分析 LASSO 回退方案。
    
    策略：
    1. 对 event=1 的样本，用标准 LassoCV 对 log(time) 做回归，筛选特征。
    2. 这是一种近似，但在高维数据上通常能有效筛选。
    3. 筛选后，用保留的特征拟合 CoxPH（无正则化）。
    """
    event_mask = event.astype(bool)
    
    if event_mask.sum() < 10:
        raise ValueError(f"事件数不足：仅 {event_mask.sum()} 例 event=1，无法做 LASSO 筛选。")
    
    # 对 event=1 的样本，取 log(time) 作为目标
    y_lasso = np.log(time[event_mask] + 1e-6)  # + epsilon 防止 log(0)
    X_event = X[event_mask]
    
    # 标准 LassoCV
    lasso = LassoCV(cv=cv_folds, random_state=42, max_iter=10000, n_jobs=1)
    lasso.fit(X_event, y_lasso)
    
    # 获取非零系数
    selected_indices = np.where(np.abs(lasso.coef_) > 1e-6)[0]
    selected_features = [feature_names[i] for i in selected_indices]
    coefficients = {feature_names[i]: lasso.coef_[i] for i in selected_indices}
    
    return LassoResult(
        selected_features=selected_features,
        alpha=lasso.alpha_,
        coefficients=coefficients,
        cv_mean_score=lasso.score(X_event, y_lasso),
        cv_std_score=0.0
    )
```

**推荐**：如果项目允许，使用 **方案 A（sksurv）** 更严谨；如果时间紧迫且不想增加依赖，使用 **方案 B** 并在 Limitations 中说明。

---

## 七、二分类分析：LASSO + Logistic Regression

```python
def _run_binary_analysis(
    X: np.ndarray,
    y: np.ndarray,
    lasso_result: LassoResult,
    config: AnalysisConfig,
    feature_names: List[str]
) -> BinaryResult:
    """
    执行二分类分析：基于 LASSO 筛选后的特征，拟合 Logistic Regression。
    
    支持：
    - 仅影像组学特征
    - 影像组学 + 临床协变量（协变量不经过 LASSO 筛选，强制保留）
    - 输出 OR、95% CI、p 值、AUC、灵敏度、特异度
    """
    # 1. 构建最终特征集：LASSO 选中的影像组学特征 + 强制保留的临床协变量
    selected_radiomic = lasso_result.selected_features
    clinical_covs = [c for c in config.covariates if c in feature_names]
    
    # 从 feature_names 中找出索引
    final_feature_names = list(dict.fromkeys(selected_radiomic + clinical_covs))
    final_indices = [feature_names.index(f) for f in final_feature_names]
    X_selected = X[:, final_indices]
    
    if X_selected.shape[1] == 0:
        raise ValueError("LASSO 未筛选出任何特征，且未指定临床协变量。无法建模。")
    
    # 2. 拟合 Logistic Regression
    # 注意：如果特征数很少，可关闭正则化（C=1e6）；但通常保留 mild L2
    model = LogisticRegression(
        penalty='l2',
        C=1.0,
        solver='lbfgs',
        max_iter=10000,
        random_state=42
    )
    model.fit(X_selected, y)
    
    # 3. 计算预测概率
    y_prob = model.predict_proba(X_selected)[:, 1]
    y_pred = model.predict(X_selected)
    
    # 4. AUC 和 95% CI（DeLong 检验或 Bootstrap）
    auc = roc_auc_score(y, y_prob)
    auc_ci = _bootstrap_auc_ci(y, y_prob, n_bootstrap=1000)
    
    # 5. 最优阈值（Youden Index）
    fpr, tpr, thresholds = roc_curve(y, y_prob)
    j_scores = tpr - fpr
    optimal_idx = np.argmax(j_scores)
    optimal_threshold = thresholds[optimal_idx]
    
    # 6. 灵敏度和特异度（基于最优阈值）
    y_pred_thresh = (y_prob >= optimal_threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, y_pred_thresh).ravel()
    sensitivity = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    
    # 7. 回归系数、OR、95% CI、p 值
    coefs = model.coef_[0]
    intercept = model.intercept_[0]
    
    # 标准误：通过逆 Hessian 近似
    # 简化计算：使用 statsmodels 获取更准确的 SE，或手动计算
    # 这里使用 sklearn 的系数，SE 通过信息矩阵近似
    X_with_intercept = np.column_stack([np.ones(X_selected.shape[0]), X_selected])
    pred_probs = model.predict_proba(X_selected)[:, 1]
    W = np.diag(pred_probs * (1 - pred_probs))
    
    try:
        cov_matrix = np.linalg.inv(X_with_intercept.T @ W @ X_with_intercept)
        se = np.sqrt(np.diag(cov_matrix))[1:]  # 去掉 intercept 的 SE
    except np.linalg.LinAlgError:
        se = np.zeros(len(coefs))
        warnings.warn("Logistic Regression 的协方差矩阵奇异，SE 和 p 值可能不可靠。")
    
    coefficients = {}
    odds_ratios = {}
    ci_lower = {}
    ci_upper = {}
    p_values = {}
    
    for i, feat in enumerate(final_feature_names):
        coef = coefs[i]
        or_value = np.exp(coef)
        coefficients[feat] = float(coef)
        odds_ratios[feat] = float(or_value)
        
        if len(se) > i and se[i] > 0:
            se_coef = se[i]
            z = coef / se_coef
            p_val = 2 * (1 - stats.norm.cdf(abs(z)))
            ci_lo = np.exp(coef - 1.96 * se_coef)
            ci_hi = np.exp(coef + 1.96 * se_coef)
        else:
            p_val = 1.0
            ci_lo = ci_hi = np.nan
        
        ci_lower[feat] = float(ci_lo) if not np.isnan(ci_lo) else None
        ci_upper[feat] = float(ci_hi) if not np.isnan(ci_hi) else None
        p_values[feat] = float(p_val)
    
    return BinaryResult(
        coefficients=coefficients,
        odds_ratios=odds_ratios,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        p_values=p_values,
        auc=float(auc),
        auc_ci=auc_ci,
        sensitivity=float(sensitivity),
        specificity=float(specificity),
        threshold=float(optimal_threshold),
        confusion_matrix=confusion_matrix(y, y_pred_thresh)
    )


def _bootstrap_auc_ci(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_bootstrap: int = 1000,
    confidence: float = 0.95
) -> Tuple[float, float]:
    """
    Bootstrap 计算 AUC 的置信区间。
    """
    rng = np.random.RandomState(42)
    bootstrapped_scores = []
    
    for i in range(n_bootstrap):
        indices = rng.randint(0, len(y_true), len(y_true))
        if len(np.unique(y_true[indices])) < 2:
            continue
        score = roc_auc_score(y_true[indices], y_prob[indices])
        bootstrapped_scores.append(score)
    
    if len(bootstrapped_scores) == 0:
        return (0.0, 1.0)
    
    alpha = 1 - confidence
    ci_lower = np.percentile(bootstrapped_scores, alpha/2 * 100)
    ci_upper = np.percentile(bootstrapped_scores, (1 - alpha/2) * 100)
    
    return (float(ci_lower), float(ci_upper))
```

---

## 八、生存分析：CoxPH

```python
def _run_survival_analysis(
    X: np.ndarray,
    time: np.ndarray,
    event: np.ndarray,
    lasso_result: LassoResult,
    config: AnalysisConfig,
    feature_names: List[str]
) -> SurvivalResult:
    """
    执行生存分析：基于 LASSO 筛选后的特征，拟合 CoxPH。
    
    输出：HR、95% CI、p 值、C-index。
    """
    # 1. 构建最终特征集
    selected_radiomic = lasso_result.selected_features
    clinical_covs = [c for c in config.covariates if c in feature_names]
    final_feature_names = list(dict.fromkeys(selected_radiomic + clinical_covs))
    final_indices = [feature_names.index(f) for f in final_feature_names]
    X_selected = X[:, final_indices]
    
    if X_selected.shape[1] == 0:
        raise ValueError("LASSO 未筛选出任何特征，且未指定临床协变量。无法建模。")
    
    # 2. 构造 DataFrame（lifelines 需要 pandas DataFrame）
    df = pd.DataFrame(X_selected, columns=final_feature_names)
    df["time"] = time
    df["event"] = event
    
    # 3. 拟合 CoxPH
    cph = CoxPHFitter(penalizer=0.0)  # LASSO 已筛选，此处无正则化
    
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cph.fit(df, duration_col="time", event_col="event", show_progress=False)
    
    # 4. 提取结果
    summary = cph.summary
    
    coefficients = {}
    hazard_ratios = {}
    ci_lower = {}
    ci_upper = {}
    p_values = {}
    
    for feat in final_feature_names:
        if feat in summary.index:
            row = summary.loc[feat]
            coef = row["coef"]
            hr = np.exp(coef)
            ci_lo = np.exp(row["coef lower 95%"])
            ci_hi = np.exp(row["coef upper 95%"])
            p = row["p"]
            
            coefficients[feat] = float(coef)
            hazard_ratios[feat] = float(hr)
            ci_lower[feat] = float(ci_lo)
            ci_upper[feat] = float(ci_hi)
            p_values[feat] = float(p)
    
    # 5. C-index（Harrell's concordance index）
    c_index = concordance_index(
        event_times=df["time"],
        predicted_scores=-cph.predict_partial_hazard(df),  # 负号因为 hazard 越大风险越高
        event_observed=df["event"]
    )
    
    # 6. C-index 95% CI（Bootstrap）
    c_index_ci = _bootstrap_cindex_ci(
        df=df,
        feature_names=final_feature_names,
        n_bootstrap=500
    )
    
    return SurvivalResult(
        coefficients=coefficients,
        hazard_ratios=hazard_ratios,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        p_values=p_values,
        c_index=float(c_index),
        c_index_ci=c_index_ci
    )


def _bootstrap_cindex_ci(
    df: pd.DataFrame,
    feature_names: List[str],
    n_bootstrap: int = 500,
    confidence: float = 0.95
) -> Tuple[float, float]:
    """
    Bootstrap 计算 C-index 的置信区间。
    """
    rng = np.random.RandomState(42)
    bootstrapped_scores = []
    
    for i in range(n_bootstrap):
        sample = df.sample(n=len(df), replace=True, random_state=rng)
        if sample["event"].sum() < 2:
            continue
        try:
            cph = CoxPHFitter(penalizer=0.01)  # mild 正则化防止奇异
            cph.fit(sample, duration_col="time", event_col="event", show_progress=False)
            c_idx = concordance_index(
                sample["time"],
                -cph.predict_partial_hazard(sample),
                sample["event"]
            )
            bootstrapped_scores.append(c_idx)
        except Exception:
            continue
    
    if len(bootstrapped_scores) == 0:
        return (0.0, 1.0)
    
    alpha = 1 - confidence
    ci_lower = np.percentile(bootstrapped_scores, alpha/2 * 100)
    ci_upper = np.percentile(bootstrapped_scores, (1 - alpha/2) * 100)
    
    return (float(ci_lower), float(ci_upper))
```

---

## 九、结果封装

```python
def _package_results(
    config: AnalysisConfig,
    lasso_result: LassoResult,
    result: Union[BinaryResult, SurvivalResult],
    n_samples: int,
    feature_names: List[str]
) -> dict:
    """
    将分析结果封装为统一字典，供 Report Agent 使用。
    """
    base = {
        "analysis_type": config.task_type,
        "n_samples": n_samples,
        "n_features_before_lasso": len(feature_names),
        "n_features_after_lasso": len(lasso_result.selected_features),
        "covariates_used": config.covariates,
        "lasso_selected_features": lasso_result.selected_features,
        "lasso_alpha": float(lasso_result.alpha),
        "lasso_cv_scores": [float(lasso_result.cv_mean_score)],
        "warnings": [],
        "errors": [],
    }
    
    if isinstance(result, BinaryResult):
        base["binary"] = {
            "model_type": "logistic_regression",
            "coefficients": result.coefficients,
            "odds_ratios": result.odds_ratios,
            "ci_lower": result.ci_lower,
            "ci_upper": result.ci_upper,
            "p_values": result.p_values,
            "auc": result.auc,
            "auc_ci": result.auc_ci,
            "sensitivity": result.sensitivity,
            "specificity": result.specificity,
            "threshold": result.threshold,
            "confusion_matrix": result.confusion_matrix.tolist(),
        }
        base["survival"] = None
    elif isinstance(result, SurvivalResult):
        base["survival"] = {
            "model_type": "coxph",
            "coefficients": result.coefficients,
            "hazard_ratios": result.hazard_ratios,
            "ci_lower": result.ci_lower,
            "ci_upper": result.ci_upper,
            "p_values": result.p_values,
            "c_index": result.c_index,
            "c_index_ci": result.c_index_ci,
        }
        base["binary"] = None
    
    return base
```

---

## 十、异常处理体系

### 10.1 自定义异常类

```python
class AnalysisError(Exception):
    """Analysis Agent 基类异常。"""
    pass

class InsufficientSampleError(AnalysisError):
    """
    样本量不足异常。
    
    触发条件：
    - n_samples < MIN_SAMPLE_SIZE (30)
    - event=1 的样本数 < 10（生存分析）
    
    处理：Orchestrator 中断，提示用户补充数据或跳过。
    """
    pass

class NoFeatureSelectedError(AnalysisError):
    """
    LASSO 未筛选出任何特征。
    
    触发条件：
    - LASSO 所有系数为零
    - 用户未指定临床协变量作为备选
    
    处理：记录错误，尝试无 LASSO 直接建模（全特征），或中断。
    """
    pass

class ModelConvergenceError(AnalysisError):
    """
    模型未收敛。
    
    触发条件：
    - Logistic Regression max_iter 达到上限未收敛
    - CoxPH 的 Hessian 矩阵奇异
    
    处理：增加 max_iter、增加 mild 正则化、或中断。
    """
    pass

class InvalidLabelError(AnalysisError):
    """
    标签列格式错误。
    
    触发条件：
    - Label 包含非 0/1 值
    - Event 列包含非 0/1 值
    - 生存时间存在非正值
    
    处理：Orchestrator 中断，提示用户检查 Clinical Agent 的列名识别。
    """
    pass
```

### 10.2 异常处理逻辑（在主入口中）

```python
def run_analysis_agent(state: dict) -> dict:
    state["analysis_status"] = "running"
    state["analysis_error"] = None
    state["warnings"] = []
    
    try:
        # ... 正常执行流程 ...
        pass
        
    except InsufficientSampleError as e:
        state["analysis_status"] = "failed"
        state["analysis_error"] = str(e)
        # 必须抛出，让 Orchestrator 捕获并中断
        raise
        
    except InvalidLabelError as e:
        state["analysis_status"] = "failed"
        state["analysis_error"] = str(e)
        raise
        
    except NoFeatureSelectedError as e:
        state["analysis_status"] = "failed"
        state["analysis_error"] = str(e)
        # 可选：尝试回退到全特征建模
        # state["warnings"].append("LASSO 未筛选特征，尝试使用全部特征建模。")
        # 这里选择抛出，让用户决定
        raise
        
    except ModelConvergenceError as e:
        state["analysis_status"] = "failed"
        state["analysis_error"] = str(e)
        raise
        
    except ValueError as e:
        # 一般性数值错误，记录但不强制中断（Orchestrator 决定）
        state["analysis_status"] = "failed"
        state["analysis_error"] = str(e)
        state["warnings"].append(str(e))
        
    except Exception as e:
        # 未预见异常
        state["analysis_status"] = "failed"
        state["analysis_error"] = f"未预期异常: {type(e).__name__}: {str(e)}"
        state["warnings"].append(state["analysis_error"])
        
    return state
```

### 10.3 各阶段的防御性检查清单

| 阶段 | 检查项 | 失败处理 |
|------|--------|----------|
| 数据提取 | `merged_df` 是否为空 | `ValueError` |
| 样本量 | `n_samples >= MIN_SAMPLE_SIZE (30)` | `InsufficientSampleError`，中断 |
| 特征存在 | `feature_cols` 是否为空 | `ValueError` |
| 常数特征 | `X.nunique() <= 1` 的列 | 移除 + `warnings` 记录 |
| 零方差 | `X.var() == 0` 的列 | 移除 + `warnings` 记录 |
| Label 格式 | 是否只有 0/1 | `InvalidLabelError`，中断 |
| 生存时间 | 是否全 > 0 | `InvalidLabelError`，中断 |
| LASSO 筛选 | 选中特征数是否 > 0 | `NoFeatureSelectedError`，中断或回退 |
| Logistic 收敛 | `max_iter` 是否足够 | `ModelConvergenceError`，尝试增加迭代次数 |
| CoxPH 收敛 | Hessian 是否可逆 | `ModelConvergenceError`，增加 `penalizer` |
| Event 数 | `event.sum() >= 10` | `InsufficientSampleError`（事件不足） |

---

## 十一、性能优化

### 11.1 LASSO 交叉验证加速

```python
# 如果特征数 > 1000，使用稀疏矩阵或降维
from sklearn.decomposition import PCA

def _reduce_dimensionality_if_needed(X, y, max_features=1000):
    """如果特征数过高，先用 PCA 降维。"""
    if X.shape[1] > max_features:
        pca = PCA(n_components=max_features, random_state=42)
        X_reduced = pca.fit_transform(X)
        return X_reduced, pca
    return X, None
```

### 11.2 Bootstrap 并行化

```python
from joblib import Parallel, delayed

def _bootstrap_auc_ci_parallel(y_true, y_prob, n_bootstrap=1000, n_jobs=-1):
    """并行化 Bootstrap AUC CI 计算。"""
    def _single_bootstrap(seed):
        rng = np.random.RandomState(seed)
        indices = rng.randint(0, len(y_true), len(y_true))
        if len(np.unique(y_true[indices])) < 2:
            return None
        return roc_auc_score(y_true[indices], y_prob[indices])
    
    scores = Parallel(n_jobs=n_jobs)(
        delayed(_single_bootstrap)(seed) for seed in range(n_bootstrap)
    )
    scores = [s for s in scores if s is not None]
    return (float(np.percentile(scores, 2.5)), float(np.percentile(scores, 97.5)))
```

---

## 十二、依赖清单

```
# requirements.txt（analysis 相关）

pandas>=1.5.0
numpy>=1.23.0
scikit-learn>=1.2.0
scipy>=1.9.0
lifelines>=0.27.0
# 可选：scikit-survival>=0.22.0  # 用于更严谨的 Cox LASSO
```

---

## 十三、实现检查清单（Checklist）

同学在实现 `app/analysis.py` 时，请逐项确认：

- [ ] 1. `_parse_intent()` 能正确调用 `llm.py` 的接口，并处理返回失败回退。
- [ ] 2. `_auto_infer_task_type()` 无需 LLM 也能正确推断分析类型。
- [ ] 3. `_prepare_data()` 正确处理缺失值、常数特征、零方差特征。
- [ ] 4. `_run_lasso()` 二分类分支使用 `LogisticRegression(penalty='l1')` + 手动 alpha 搜索。
- [ ] 5. `_run_lasso()` 生存分支有明确实现（sksurv 或 fallback 两步法）。
- [ ] 6. `_run_binary_analysis()` 输出 OR（而非 raw coefficient）、95% CI、p 值、AUC、灵敏度、特异度。
- [ ] 7. `_run_survival_analysis()` 输出 HR、95% CI、p 值、C-index。
- [ ] 8. 所有统计量的 CI 通过 Bootstrap 计算（n=1000 for AUC, n=500 for C-index）。
- [ ] 9. `InsufficientSampleError` 在 n<30 时正确抛出，供 Orchestrator 中断。
- [ ] 10. `NoFeatureSelectedError` 在 LASSO 全零时正确抛出或回退。
- [ ] 11. 最终 `statistical_result` 字典的 key 命名和类型与 Report Agent 的期望一致。
- [ ] 12. 所有函数都有类型注解和 docstring。
- [ ] 13. 不引入 LangGraph / AutoGen / CrewAI，仅用原生 Python + scikit-learn + lifelines。
- [ ] 14. 如果 `lifelines` 的 CoxPH 报错，增加 `penalizer=0.01` 后重试一次。
- [ ] 15. 代码中所有 `random_state` 固定为 42，保证可复现。

---

## 十四、附录：函数签名速查表

```python
# 主入口
def run_analysis_agent(state: dict) -> dict

# 意图解析
def _parse_intent(user_prompt: str, clinical_info: dict, merged_df: pd.DataFrame) -> AnalysisConfig
def _auto_infer_task_type(merged_df: pd.DataFrame, clinical_info: dict) -> str
def _build_intent_prompt(user_prompt: str, column_names: List[str], auto_inferred_type: str) -> str

# 数据预处理
def _prepare_data(merged_df: pd.DataFrame, config: AnalysisConfig, clinical_info: dict) 
    -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray], Optional[np.ndarray], List[str]]

# LASSO 特征筛选
def _run_lasso(X: np.ndarray, y: np.ndarray, task_type: str, feature_names: List[str], cv_folds: int = 5) 
    -> LassoResult

# 二分类分析
def _run_binary_analysis(X: np.ndarray, y: np.ndarray, lasso_result: LassoResult, 
                         config: AnalysisConfig, feature_names: List[str]) -> BinaryResult
def _bootstrap_auc_ci(y_true: np.ndarray, y_prob: np.ndarray, n_bootstrap: int = 1000) 
    -> Tuple[float, float]

# 生存分析
def _run_survival_analysis(X: np.ndarray, time: np.ndarray, event: np.ndarray, 
                           lasso_result: LassoResult, config: AnalysisConfig, 
                           feature_names: List[str]) -> SurvivalResult
def _bootstrap_cindex_ci(df: pd.DataFrame, feature_names: List[str], n_bootstrap: int = 500) 
    -> Tuple[float, float]

# 结果封装
def _package_results(config: AnalysisConfig, lasso_result: LassoResult, 
                     result: Union[BinaryResult, SurvivalResult], n_samples: int, 
                     feature_names: List[str]) -> dict
```
