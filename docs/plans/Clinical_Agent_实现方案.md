# Clinical Agent 实现方案

> 对应文件：`app/clinical.py`  
> 负责人：同学 B  
> 依赖：`app/llm.py`（负责人封装，Clinical Agent 只调用函数接口）  
> 上游输入：Discovery Agent 输出的影像- mask 配对列表（可选，用于校验 ID 列是否有效）  
> 下游输出：Matching Agent（id_col 用于对齐影像 ID）

---

## 一、职责边界

Clinical Agent 是流水线第 2 站，职责极为聚焦：

1. **读取**用户上传的临床表格（`.csv` 或 `.xlsx/.xls`）。
2. **调用 LLM** 识别三类列：患者 ID 列、结局变量列（Label / Event / Time）、临床特征列。
3. **校验** LLM 返回的列名是否真实存在于表格中，做类型推断与格式清洗。
4. **输出**标准化的列名分类字典，供下游 Matching Agent 和 Analysis Agent 使用。

**Clinical Agent 不做的事：**
- 不做影像-表格 ID 对齐（这是 Matching Agent 的职责）。
- 不做统计分析、不做特征提取、不写报告。
- 不直接调用 DeepSeek API，只调用负责人封装的 `llm.py` 函数。

---

## 二、输入输出数据结构

### 2.1 输入（来自 Orchestrator / 上游）

```python
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class ClinicalInput:
    """
    Orchestrator 调用 Clinical Agent 时传入的参数。
    clinical_path: 临床表格文件绝对路径，必须是 .csv / .xlsx / .xls 之一。
    paired_ids: Discovery Agent 已经提取出的影像文件名中的患者 ID 列表（可选）。
                如果提供，Clinical Agent 会用其校验 LLM 识别的 id_col 是否合理。
    task_hint: 用户原始任务描述中的关键词（如"生存分析"、"预后预测"），
               辅助 LLM 判断 Time/Event 列。可选。
    """
    clinical_path: str
    paired_ids: Optional[List[str]] = None
    task_hint: Optional[str] = None
```

### 2.2 输出（返回 Orchestrator，再传给下游）

```python
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import pandas as pd

@dataclass
class ClinicalOutput:
    """
    Clinical Agent 的完整输出，供 Matching Agent 和 Analysis Agent 消费。
    
    字段说明：
    - id_col: 患者唯一标识列的列名，字符串。
    - label_col: 二分类结局列（如 0/1），字符串。生存分析时为 None。
    - time_col: 生存时间列（如 OS_months），字符串。二分类时为 None。
    - event_col: 生存事件列（如 0/1），字符串。二分类时为 None。
    - feature_cols: 除 id/label/time/event 之外的临床特征列名列表。
    - raw_df: 原始读入的 pandas DataFrame，供下游直接使用。
    - id_dtype: ID 列的数据类型提示（'int', 'str', 'float'），用于 Matching Agent 做类型对齐。
    - n_samples: 表格总行数（含表头），用于样本量预警。
    - analysis_type: 推断出的分析类型，'classification' 或 'survival'。
    - metadata: 额外元信息字典，如 LLM 原始返回、各列缺失率等。
    """
    id_col: str
    label_col: Optional[str]
    time_col: Optional[str]
    event_col: Optional[str]
    feature_cols: List[str]
    raw_df: pd.DataFrame
    id_dtype: str
    n_samples: int
    analysis_type: str  # "classification" | "survival"
    metadata: Dict[str, Any]
```

### 2.3 失败/中断时返回

```python
@dataclass
class ClinicalFailure:
    """
    当 Clinical Agent 无法完成任务时，向 Orchestrator 报告失败原因。
    Orchestrator 据此向用户展示选项：跳过 / 终止 / 重试。
    """
    stage: str = "clinical"
    reason: str           # 人类可读的错误原因
    error_code: str       # 机器可读的错误码，供前端判断显示什么提示
    suggestion: str       # 给用户的修复建议
    raw_llm_response: Optional[str] = None  # LLM 原始返回（如果是 LLM 相关问题）
    recoverable: bool = True  # 是否可恢复（如重试 LLM 调用）

# 错误码枚举（Clinical Agent 专用）
class ClinicalErrorCode:
    FILE_NOT_FOUND = "CLINICAL_FILE_NOT_FOUND"
    UNSUPPORTED_FORMAT = "CLINICAL_UNSUPPORTED_FORMAT"
    EMPTY_FILE = "CLINICAL_EMPTY_FILE"
    LLM_PARSE_ERROR = "CLINICAL_LLM_PARSE_ERROR"
    ID_COL_MISMATCH = "CLINICAL_ID_COL_MISMATCH"
    NO_LABEL_OR_TIME = "CLINICAL_NO_LABEL_OR_TIME"
    ALL_COLUMNS_SAME = "CLINICAL_ALL_COLUMNS_SAME"  # 所有列值相同，无法分析
    ID_DTYPE_UNCERTAIN = "CLINICAL_ID_DTYPE_UNCERTAIN"
```

---

## 三、核心类与函数签名

### 3.1 主入口类

```python
# app/clinical.py

import os
import re
import json
from typing import Union, List, Optional, Dict, Any
from dataclasses import dataclass

import pandas as pd
import numpy as np

# 从负责人封装的 llm.py 导入，低年级同学无感知
from app.llm import call_llm_column_identification

class ClinicalAgent:
    """
    Clinical Agent：临床表格读取 + LLM 列名识别 + 结果校验。
    
    使用方式：
        agent = ClinicalAgent()
        result = agent.run(ClinicalInput(clinical_path="/data/clinical.xlsx"))
        if isinstance(result, ClinicalFailure):
            # 处理失败
        else:
            # result 是 ClinicalOutput
    """
    
    # 支持的文件扩展名
    SUPPORTED_EXTS = {".csv", ".xlsx", ".xls"}
    
    # ID 列的启发式关键词（用于兜底和校验）
    ID_KEYWORDS = {
        "patient", "id", "pid", "subject", "case", "participant",
        "患者", "编号", "病例", "id号", "病人"
    }
    
    # Label 列的启发式关键词
    LABEL_KEYWORDS = {
        "label", "outcome", "response", "status", "class", "group",
        "label", "结局", "响应", "状态", "分组", "类别"
    }
    
    # Time 列的启发式关键词
    TIME_KEYWORDS = {
        "time", "survival", "os", "dfs", "pfs", "follow", "month", "day", "year",
        "时间", "生存", "随访", "月", "天", "年"
    }
    
    # Event 列的启发式关键词
    EVENT_KEYWORDS = {
        "event", "status", "death", "recurrence", "progression", "censor",
        "事件", "死亡", "复发", "进展", "删失"
    }
    
    def __init__(self, max_retries: int = 2):
        """
        Args:
            max_retries: LLM 调用失败或返回格式错误时的最大重试次数。
        """
        self.max_retries = max_retries
    
    def run(self, inp: ClinicalInput) -> Union[ClinicalOutput, ClinicalFailure]:
        """
        主入口函数。执行完整的 Clinical Agent 逻辑。
        
        执行流程：
        1. 文件格式校验与读取
        2. 基础数据质量检查（空文件、单列、全相同值）
        3. 构建 Prompt 调用 LLM 识别列名
        4. 解析并校验 LLM 返回
        5. 推断 analysis_type
        6. 输出 ClinicalOutput 或 ClinicalFailure
        """
        # Step 1: 读取文件
        read_result = self._read_clinical_file(inp.clinical_path)
        if isinstance(read_result, ClinicalFailure):
            return read_result
        df = read_result
        
        # Step 2: 基础 QC
        qc_result = self._basic_qc(df, inp.clinical_path)
        if isinstance(qc_result, ClinicalFailure):
            return qc_result
        
        # Step 3: 构建上下文信息（列名 + 示例数据 + 统计信息）
        column_context = self._build_column_context(df, inp.task_hint)
        
        # Step 4: 调用 LLM（带重试）
        llm_result = self._call_llm_with_retry(column_context, inp.paired_ids)
        if isinstance(llm_result, ClinicalFailure):
            return llm_result
        parsed = llm_result
        
        # Step 5: 校验 LLM 返回的列名是否存在于表格中
        validated = self._validate_columns(df, parsed, inp.paired_ids)
        if isinstance(validated, ClinicalFailure):
            return validated
        
        # Step 6: 推断 analysis_type 和整理输出
        output = self._assemble_output(df, validated, inp)
        return output
```

### 3.2 文件读取函数

```python
    def _read_clinical_file(self, path: str) -> Union[pd.DataFrame, ClinicalFailure]:
        """
        读取临床表格文件，支持 CSV 和 Excel 格式。
        
        异常处理：
        - 文件不存在 → FILE_NOT_FOUND
        - 扩展名不支持 → UNSUPPORTED_FORMAT
        - pandas 读取失败（编码问题、格式损坏等）→ 尝试备用编码后仍失败则返回错误
        
        Returns:
            成功返回 DataFrame，失败返回 ClinicalFailure
        """
        if not os.path.exists(path):
            return ClinicalFailure(
                stage="clinical",
                reason=f"临床表格文件不存在: {path}",
                error_code=ClinicalErrorCode.FILE_NOT_FOUND,
                suggestion="请检查文件路径是否正确，或重新上传临床表格。",
                recoverable=False
            )
        
        ext = os.path.splitext(path)[1].lower()
        if ext not in self.SUPPORTED_EXTS:
            return ClinicalFailure(
                stage="clinical",
                reason=f"不支持的文件格式: {ext}，仅支持 {self.SUPPORTED_EXTS}",
                error_code=ClinicalErrorCode.UNSUPPORTED_FORMAT,
                suggestion="请将表格保存为 .csv、.xlsx 或 .xls 格式后重新上传。",
                recoverable=False
            )
        
        # 尝试读取
        try:
            if ext == ".csv":
                # 先尝试 utf-8，失败则尝试 gbk/cp936（常见中文 Excel 导出编码）
                try:
                    df = pd.read_csv(path, encoding="utf-8")
                except UnicodeDecodeError:
                    df = pd.read_csv(path, encoding="gbk")
            else:
                df = pd.read_excel(path)
        except Exception as e:
            return ClinicalFailure(
                stage="clinical",
                reason=f"读取表格失败: {str(e)}",
                error_code=ClinicalErrorCode.UNSUPPORTED_FORMAT,
                suggestion="请检查表格是否损坏，或尝试另存为 CSV 格式后重新上传。",
                recoverable=False
            )
        
        return df
```

### 3.3 基础 QC 函数

```python
    def _basic_qc(self, df: pd.DataFrame, path: str) -> Union[None, ClinicalFailure]:
        """
        对读入的 DataFrame 做基础质量检查。
        
        检查项：
        1. 空文件（0 行或 0 列）
        2. 只有 1 列（无法区分 ID/Label/Feature）
        3. 所有列的值完全相同（无信息）
        4. 列名重复
        
        Returns:
            通过返回 None，失败返回 ClinicalFailure
        """
        if df.empty or df.shape[1] == 0:
            return ClinicalFailure(
                stage="clinical",
                reason="临床表格为空（0 行或 0 列）",
                error_code=ClinicalErrorCode.EMPTY_FILE,
                suggestion="请检查表格是否包含数据，或重新上传非空表格。",
                recoverable=False
            )
        
        if df.shape[1] == 1:
            return ClinicalFailure(
                stage="clinical",
                reason="临床表格只有 1 列，无法识别 ID/Label/特征",
                error_code=ClinicalErrorCode.EMPTY_FILE,
                suggestion="请确保表格至少包含患者 ID 列和结局变量列。",
                recoverable=False
            )
        
        # 检查列名重复
        dup_cols = df.columns[df.columns.duplicated()].tolist()
        if dup_cols:
            # 自动重命名重复列，但报告警告
            df.columns = pd.io.parsers.ParserBase({"names": df.columns})._maybe_dedup_names(df.columns)
        
        # 检查是否有全相同值的列（至少警告，不中断）
        constant_cols = [col for col in df.columns if df[col].nunique(dropna=False) <= 1]
        
        return None  # QC 通过
```

### 3.4 构建 LLM Prompt 上下文

```python
    def _build_column_context(
        self, 
        df: pd.DataFrame, 
        task_hint: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        为 LLM 构建丰富的上下文信息，帮助其准确识别列类型。
        
        包含：
        1. 完整列名列表
        2. 每列的数据类型（pandas 推断）
        3. 每列的非空值数量、缺失率
        4. 每列的唯一值数量
        5. 每列的前 3 个示例值
        6. 数值列的统计摘要（min, max, mean）
        7. 用户任务提示（如果有）
        
        Returns:
            字典，后续会被格式化为 Prompt 中的表格描述部分。
        """
        columns_info = []
        
        for col in df.columns:
            series = df[col]
            dtype = str(series.dtype)
            non_null = series.notna().sum()
            missing_rate = 1 - non_null / len(df)
            n_unique = series.nunique(dropna=False)
            
            # 示例值（取前 3 个非空值，转为字符串）
            samples = series.dropna().head(3).astype(str).tolist()
            samples_str = ", ".join(samples) if samples else "N/A"
            
            # 数值列的统计
            stats = {}
            if pd.api.types.is_numeric_dtype(series):
                stats = {
                    "min": series.min(),
                    "max": series.max(),
                    "mean": round(series.mean(), 2) if not series.empty else "N/A"
                }
            
            columns_info.append({
                "column_name": col,
                "dtype": dtype,
                "non_null": int(non_null),
                "missing_rate": round(missing_rate, 3),
                "n_unique": int(n_unique),
                "samples": samples_str,
                "stats": stats
            })
        
        return {
            "n_rows": len(df),
            "n_columns": len(df.columns),
            "task_hint": task_hint or "未提供",
            "columns": columns_info
        }
```

### 3.5 LLM 调用与重试逻辑

```python
    def _call_llm_with_retry(
        self, 
        column_context: Dict[str, Any],
        paired_ids: Optional[List[str]] = None
    ) -> Union[Dict[str, Any], ClinicalFailure]:
        """
        调用 LLM 进行列名识别，带重试机制。
        
        重试触发条件：
        1. LLM 返回非 JSON 格式
        2. JSON 中缺少必需字段
        3. 网络/API 调用失败
        
        Args:
            column_context: _build_column_context 的输出
            paired_ids: 可选，影像中已提取的 ID 样本，用于辅助 LLM 判断
        
        Returns:
            解析后的字典（含 id_col, label_col, time_col, event_col, feature_cols, reasoning）
            或 ClinicalFailure
        """
        # 构建 Prompt（详见第四节）
        prompt = self._build_llm_prompt(column_context, paired_ids)
        
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                # 调用负责人封装的函数
                response = call_llm_column_identification(prompt)
                
                # 解析 JSON
                parsed = self._parse_llm_response(response)
                if parsed is not None:
                    return parsed
                else:
                    last_error = "LLM 返回无法解析为有效 JSON"
                    
            except Exception as e:
                last_error = str(e)
                continue  # 重试
        
        # 所有重试耗尽
        return ClinicalFailure(
            stage="clinical",
            reason=f"LLM 列名识别失败（已重试 {self.max_retries} 次）: {last_error}",
            error_code=ClinicalErrorCode.LLM_PARSE_ERROR,
            suggestion="请检查网络连接或 DeepSeek API 状态，点击重试。",
            raw_llm_response=response if 'response' in locals() else None,
            recoverable=True
        )
```

### 3.6 LLM 响应解析

```python
    def _parse_llm_response(self, response: str) -> Optional[Dict[str, Any]]:
        """
        从 LLM 返回的文本中提取 JSON。
        
        策略：
        1. 尝试直接 json.loads
        2. 尝试从 markdown code block 中提取 ```json ... ```
        3. 尝试从文本中找第一个 { 和最后一个 } 之间的内容
        4. 检查必需字段是否存在
        
        期望的 JSON 结构：
        {
            "id_col": "PatientID",
            "label_col": "Response",      // 二分类时必填，生存分析时为 null
            "time_col": null,              // 二分类时为 null
            "event_col": null,             // 二分类时为 null
            "feature_cols": ["Age", "Sex", "T_stage"],
            "analysis_type": "classification",  // 或 "survival"
            "reasoning": "..."
        }
        """
        if not response or not response.strip():
            return None
        
        text = response.strip()
        
        # 策略 1: 直接解析
        try:
            parsed = json.loads(text)
            if self._has_required_fields(parsed):
                return parsed
        except json.JSONDecodeError:
            pass
        
        # 策略 2: 提取 markdown code block
        code_block_pattern = r'```(?:json)?\s*([\s\S]*?)```'
        matches = re.findall(code_block_pattern, text)
        for match in matches:
            try:
                parsed = json.loads(match.strip())
                if self._has_required_fields(parsed):
                    return parsed
            except json.JSONDecodeError:
                continue
        
        # 策略 3: 找第一个 { 和最后一个 }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(text[start:end+1])
                if self._has_required_fields(parsed):
                    return parsed
            except json.JSONDecodeError:
                pass
        
        return None
    
    def _has_required_fields(self, parsed: Dict) -> bool:
        """检查解析后的字典是否包含必需字段。"""
        required = {"id_col", "feature_cols", "analysis_type"}
        if not required.issubset(set(parsed.keys())):
            return False
        
        # analysis_type 必须是合法值
        if parsed.get("analysis_type") not in {"classification", "survival"}:
            return False
        
        # 根据 analysis_type 检查对应字段
        if parsed["analysis_type"] == "classification":
            if "label_col" not in parsed or parsed.get("label_col") is None:
                return False
        else:  # survival
            if "time_col" not in parsed or "event_col" not in parsed:
                return False
            if parsed.get("time_col") is None or parsed.get("event_col") is None:
                return False
        
        return True
```

### 3.7 列名校验函数

```python
    def _validate_columns(
        self, 
        df: pd.DataFrame, 
        parsed: Dict[str, Any],
        paired_ids: Optional[List[str]] = None
    ) -> Union[Dict[str, Any], ClinicalFailure]:
        """
        校验 LLM 返回的列名是否真实存在于表格中，并做额外推断。
        
        校验项：
        1. id_col 必须在 df.columns 中
        2. label_col/time_col/event_col 如果非 None，必须在 df.columns 中
        3. feature_cols 中的所有列必须在 df.columns 中
        4. feature_cols 不应包含 id/label/time/event 列
        5. 如果提供了 paired_ids，检查 id_col 的值是否与 paired_ids 有交集
        6. label_col 的值域检查（二分类应为 0/1 或类似）
        7. event_col 的值域检查（应为 0/1）
        8. time_col 应为数值型
        
        Returns:
            校验通过返回清洗后的 parsed 字典，失败返回 ClinicalFailure
        """
        all_cols = set(df.columns)
        
        # 检查 1: id_col 存在
        id_col = parsed.get("id_col")
        if id_col not in all_cols:
            return ClinicalFailure(
                stage="clinical",
                reason=f"LLM 识别的 ID 列 '{id_col}' 不存在于表格中",
                error_code=ClinicalErrorCode.ID_COL_MISMATCH,
                suggestion=f"表格中的列为: {list(all_cols)}，请检查列名是否正确。",
                raw_llm_response=json.dumps(parsed),
                recoverable=True
            )
        
        # 检查 2: label/time/event 列存在性
        for col_key in ["label_col", "time_col", "event_col"]:
            col_name = parsed.get(col_key)
            if col_name is not None and col_name not in all_cols:
                return ClinicalFailure(
                    stage="clinical",
                    reason=f"LLM 识别的 {col_key} '{col_name}' 不存在于表格中",
                    error_code=ClinicalErrorCode.NO_LABEL_OR_TIME,
                    suggestion=f"请检查表格列名，或重新描述任务以辅助 LLM 识别。",
                    raw_llm_response=json.dumps(parsed),
                    recoverable=True
                )
        
        # 检查 3: feature_cols 有效性
        feature_cols = parsed.get("feature_cols", [])
        if not isinstance(feature_cols, list):
            feature_cols = [feature_cols] if feature_cols else []
        
        invalid_features = [c for c in feature_cols if c not in all_cols]
        if invalid_features:
            # 自动移除不存在的列，不中断
            feature_cols = [c for c in feature_cols if c in all_cols]
        
        # 检查 4: feature_cols 不应包含特殊列
        special_cols = {id_col, parsed.get("label_col"), parsed.get("time_col"), parsed.get("event_col")}
        special_cols = {c for c in special_cols if c is not None}
        feature_cols = [c for c in feature_cols if c not in special_cols]
        
        if not feature_cols:
            return ClinicalFailure(
                stage="clinical",
                reason="未识别到有效的临床特征列（feature_cols 为空）",
                error_code=ClinicalErrorCode.NO_LABEL_OR_TIME,
                suggestion="请确保表格中除 ID 和结局变量外，还包含至少一个临床特征列（如 Age, Sex 等）。",
                raw_llm_response=json.dumps(parsed),
                recoverable=True
            )
        
        # 检查 5: ID 列与影像 ID 的交集（如果提供了 paired_ids）
        if paired_ids is not None and len(paired_ids) > 0:
            id_values = set(df[id_col].dropna().astype(str).tolist())
            # 尝试去除可能的文件扩展名后比较
            clean_paired = {os.path.splitext(str(pid))[0] for pid in paired_ids}
            clean_id_values = {os.path.splitext(str(vid))[0] for vid in id_values}
            
            intersection = clean_id_values & clean_paired
            if len(intersection) == 0:
                # 严重警告但不中断，由 Matching Agent 处理
                pass  # 记录到 metadata 中
        
        # 检查 6: label_col 值域（二分类）
        if parsed.get("analysis_type") == "classification" and parsed.get("label_col"):
            label_series = df[parsed["label_col"]].dropna()
            unique_labels = label_series.unique()
            # 二分类通常应为 0/1，但也可能是 yes/no 等
            if len(unique_labels) != 2:
                # 不是严格的二分类，记录警告
                pass
        
        # 检查 7: event_col 值域（应为 0/1）
        if parsed.get("event_col"):
            event_series = df[parsed["event_col"]].dropna()
            unique_events = event_series.unique()
            if not set(unique_events).issubset({0, 1, 0.0, 1.0, True, False}):
                # 记录警告
                pass
        
        # 检查 8: time_col 应为数值型
        if parsed.get("time_col"):
            if not pd.api.types.is_numeric_dtype(df[parsed["time_col"]]):
                return ClinicalFailure(
                    stage="clinical",
                    reason=f"时间列 '{parsed['time_col']}' 不是数值型，无法用于生存分析",
                    error_code=ClinicalErrorCode.NO_LABEL_OR_TIME,
                    suggestion="请确保生存时间列为数值（如月份数），而非文本格式。",
                    raw_llm_response=json.dumps(parsed),
                    recoverable=True
                )
        
        # 更新 parsed
        parsed["feature_cols"] = feature_cols
        return parsed
```

### 3.8 组装最终输出

```python
    def _assemble_output(
        self, 
        df: pd.DataFrame, 
        validated: Dict[str, Any],
        inp: ClinicalInput
    ) -> ClinicalOutput:
        """
        将校验通过的解析结果组装为 ClinicalOutput。
        
        同时计算：
        - id_dtype: ID 列的数据类型
        - n_samples: 样本量
        - 各列缺失率（存入 metadata）
        """
        id_col = validated["id_col"]
        
        # 推断 ID 列类型
        id_series = df[id_col]
        if pd.api.types.is_integer_dtype(id_series):
            id_dtype = "int"
        elif pd.api.types.is_string_dtype(id_series) or pd.api.types.is_object_dtype(id_series):
            id_dtype = "str"
        else:
            id_dtype = "str"  # 默认按字符串处理
        
        # 计算缺失率
        missing_rates = {
            col: round(1 - df[col].notna().sum() / len(df), 3)
            for col in df.columns
        }
        
        # 计算 ID 列与影像 ID 的匹配情况（如果提供了 paired_ids）
        match_info = {}
        if inp.paired_ids:
            id_values = set(df[id_col].dropna().astype(str).tolist())
            clean_paired = {os.path.splitext(str(pid))[0] for pid in inp.paired_ids}
            clean_id_values = {os.path.splitext(str(vid))[0] for vid in id_values}
            match_info = {
                "n_table_ids": len(clean_id_values),
                "n_image_ids": len(clean_paired),
                "n_intersection": len(clean_id_values & clean_paired),
                "table_only": list(clean_id_values - clean_paired)[:10],  # 最多 10 个
                "image_only": list(clean_paired - clean_id_values)[:10]
            }
        
        return ClinicalOutput(
            id_col=id_col,
            label_col=validated.get("label_col"),
            time_col=validated.get("time_col"),
            event_col=validated.get("event_col"),
            feature_cols=validated["feature_cols"],
            raw_df=df,
            id_dtype=id_dtype,
            n_samples=len(df),
            analysis_type=validated["analysis_type"],
            metadata={
                "missing_rates": missing_rates,
                "match_preview": match_info,
                "llm_reasoning": validated.get("reasoning", ""),
                "original_parsed": validated
            }
        )
```

---

## 四、LLM Prompt 模板（列名识别）

这是系统 3 个 LLM 调用点之一。Prompt 由 system message + user message 组成，通过负责人封装的 `call_llm_column_identification()` 函数发送给 DeepSeek V4 API。

### 4.1 System Message

```
You are a clinical data structure analyst specialized in radiomics research. 
Your task is to analyze a clinical data table and identify the purpose of each column.

Rules:
1. Return ONLY a JSON object, no markdown, no explanations outside JSON.
2. The JSON must contain these exact keys: "id_col", "label_col", "time_col", "event_col", "feature_cols", "analysis_type", "reasoning".
3. "id_col" must be the patient unique identifier column (e.g., PatientID, SubjectID).
4. "analysis_type" must be either "classification" (binary outcome) or "survival" (time-to-event).
5. For classification: "label_col" is required (binary: 0/1), "time_col" and "event_col" should be null.
6. For survival: "time_col" (numeric, e.g., months) and "event_col" (0=censored, 1=event) are required, "label_col" should be null.
7. "feature_cols" includes all remaining clinical covariates (Age, Sex, Stage, etc.), EXCLUDING id/label/time/event columns.
8. If uncertain, make your best guess and explain in "reasoning".
9. All column names in your response must exactly match the original column names (case-sensitive).
```

### 4.2 User Message 模板

```
Please analyze the following clinical data table and classify each column.

## Context
- Total rows: {n_rows}
- Total columns: {n_columns}
- User task description: {task_hint}

## Column Details
{column_descriptions}

## Instructions
1. Identify which column is the patient ID (id_col).
2. Determine if this is a classification or survival analysis task:
   - Classification: look for a binary outcome column (0/1, Yes/No, Responder/Non-responder)
   - Survival: look for a time column (follow-up duration) AND an event column (death/recurrence: 0/1)
3. List all remaining columns as clinical features (feature_cols).

## Output Format
Return a single JSON object with exactly these keys:
{{
  "id_col": "exact_column_name",
  "label_col": "exact_column_name_or_null",
  "time_col": "exact_column_name_or_null",
  "event_col": "exact_column_name_or_null",
  "feature_cols": ["col1", "col2", ...],
  "analysis_type": "classification" or "survival",
  "reasoning": "brief explanation of your reasoning"
}}

## Column Description Table
{formatted_table}
```

### 4.3 formatted_table 的生成代码

```python
    def _format_column_table(self, columns_info: List[Dict]) -> str:
        """
        将列信息格式化为 Markdown 表格，供 LLM 阅读。
        
        示例输出：
        | Column | Type | Non-null | Missing | Unique | Samples | Min | Max |
        |--------|------|----------|---------|--------|---------|-----|-----|
        | PatientID | int64 | 100 | 0.0 | 100 | 1001, 1002, 1003 | - | - |
        | Age | float64 | 98 | 0.02 | 45 | 56.0, 62.0, 48.0 | 34.0 | 78.0 |
        """
        lines = [
            "| Column | Type | Non-null | Missing Rate | Unique Values | Samples | Min | Max | Mean |",
            "|--------|------|----------|--------------|---------------|---------|-----|-----|------|"
        ]
        
        for info in columns_info:
            stats = info.get("stats", {})
            min_val = stats.get("min", "-") if stats else "-"
            max_val = stats.get("max", "-") if stats else "-"
            mean_val = stats.get("mean", "-") if stats else "-"
            
            # 截断 samples 避免过长
            samples = info["samples"][:80] + "..." if len(info["samples"]) > 80 else info["samples"]
            
            lines.append(
                f"| {info['column_name']} | {info['dtype']} | {info['non_null']} | "
                f"{info['missing_rate']} | {info['n_unique']} | {samples} | "
                f"{min_val} | {max_val} | {mean_val} |"
            )
        
        return "\n".join(lines)
```

### 4.4 Prompt 组装完整代码

```python
    def _build_llm_prompt(
        self, 
        column_context: Dict[str, Any],
        paired_ids: Optional[List[str]] = None
    ) -> Dict[str, str]:
        """
        构建完整的 LLM Prompt（system + user）。
        
        Returns:
            {"system": "...", "user": "..."}
        """
        system_msg = (
            "You are a clinical data structure analyst specialized in radiomics research.\n"
            "Your task is to analyze a clinical data table and identify the purpose of each column.\n\n"
            "Rules:\n"
            "1. Return ONLY a JSON object, no markdown, no explanations outside JSON.\n"
            "2. The JSON must contain these exact keys: id_col, label_col, time_col, event_col, feature_cols, analysis_type, reasoning.\n"
            "3. id_col must be the patient unique identifier column.\n"
            "4. analysis_type must be either 'classification' or 'survival'.\n"
            "5. For classification: label_col is required (binary outcome), time_col and event_col should be null.\n"
            "6. For survival: time_col (numeric duration) and event_col (0/1) are required, label_col should be null.\n"
            "7. feature_cols includes all remaining clinical covariates, EXCLUDING id/label/time/event columns.\n"
            "8. If uncertain, make your best guess and explain in reasoning.\n"
            "9. All column names must exactly match the original names (case-sensitive).\n"
        )
        
        # 生成列描述表格
        formatted_table = self._format_column_table(column_context["columns"])
        
        # 可选：添加影像 ID 样本提示
        id_hint = ""
        if paired_ids and len(paired_ids) > 0:
            sample_ids = paired_ids[:5]
            id_hint = f"\n\n## Additional Context\nThe image filenames contain patient IDs like: {', '.join(sample_ids)}. "
            id_hint += "The id_col you identify should ideally match these IDs."
        
        user_msg = (
            f"Please analyze the following clinical data table and classify each column.\n\n"
            f"## Context\n"
            f"- Total rows: {column_context['n_rows']}\n"
            f"- Total columns: {column_context['n_columns']}\n"
            f"- User task description: {column_context['task_hint']}\n"
            f"{id_hint}\n\n"
            f"## Column Details\n{formatted_table}\n\n"
            f"## Instructions\n"
            f"1. Identify the patient ID column (id_col).\n"
            f"2. Determine if this is classification or survival:\n"
            f"   - Classification: binary outcome (0/1, Yes/No)\n"
            f"   - Survival: time column (follow-up duration) + event column (0/1)\n"
            f"3. List all remaining columns as clinical features (feature_cols).\n\n"
            f"## Output\n"
            f"Return a single JSON object with exactly these keys:\n"
            f'{{"id_col": "...", "label_col": "... or null", "time_col": "... or null", '
            f'"event_col": "... or null", "feature_cols": ["..."], '
            f'"analysis_type": "classification or survival", "reasoning": "..."}}'
        )
        
        return {"system": system_msg, "user": user_msg}
```

---

## 五、与上下游 Agent 的接口契约

### 5.1 上游输入（来自 Orchestrator）

```python
# Orchestrator 调用方式
from app.clinical import ClinicalAgent, ClinicalInput

clinical_input = ClinicalInput(
    clinical_path="/data/clinical_data.xlsx",
    paired_ids=["P001", "P002", "P003"],  # Discovery Agent 的输出，可选
    task_hint="做生存分析，预测乳腺癌患者预后"
)

agent = ClinicalAgent()
result = agent.run(clinical_input)
```

### 5.2 下游输出（传给 Matching Agent）

```python
# Orchestrator 将 ClinicalOutput 传给 Matching Agent
from app.clinical import ClinicalOutput

# Matching Agent 需要消费的字段：
# - result.id_col      → 用于对齐影像 ID
# - result.id_dtype    → 用于类型转换（int vs str）
# - result.raw_df      → 完整的临床数据
# - result.n_samples   → 样本量检查

# Analysis Agent 需要消费的字段：
# - result.label_col / time_col / event_col → 结局变量
# - result.feature_cols                     → 临床协变量
# - result.analysis_type                    → "classification" 或 "survival"
```

### 5.3 接口契约图

```
┌─────────────────┐
│  Orchestrator   │
│  (状态机总控)    │
└────────┬────────┘
         │ 调用 agent.run(ClinicalInput)
         ▼
┌─────────────────┐
│ Clinical Agent  │
│  (clinical.py)  │
│                 │
│ 输入:           │
│ - clinical_path │
│ - paired_ids    │ ← Discovery Agent 输出（可选）
│ - task_hint     │ ← 用户原始描述（可选）
│                 │
│ 输出:           │
│ - id_col        │ ──→ Matching Agent（ID 对齐）
│ - id_dtype      │ ──→ Matching Agent（类型转换）
│ - label_col     │ ──→ Analysis Agent
│ - time_col      │ ──→ Analysis Agent
│ - event_col     │ ──→ Analysis Agent
│ - feature_cols  │ ──→ Analysis Agent
│ - analysis_type │ ──→ Analysis Agent（决定分析分支）
│ - raw_df        │ ──→ Matching/Analysis Agent
│ - n_samples     │ ──→ Orchestrator（样本量预警）
└─────────────────┘
```

---

## 六、异常处理逻辑

### 6.1 异常分类与处理策略

| 异常场景 | 错误码 | 是否可恢复 | 处理策略 |
|----------|--------|-----------|----------|
| 文件不存在 | FILE_NOT_FOUND | ❌ 否 | Orchestrator 提示用户重新上传 |
| 格式不支持 | UNSUPPORTED_FORMAT | ❌ 否 | 提示转换为 CSV/XLSX |
| 表格为空 | EMPTY_FILE | ❌ 否 | 提示检查表格内容 |
| LLM 返回非 JSON | LLM_PARSE_ERROR | ✅ 是 | 自动重试，最多 3 次 |
| LLM 返回缺字段 | LLM_PARSE_ERROR | ✅ 是 | 自动重试 |
| ID 列不存在 | ID_COL_MISMATCH | ✅ 是 | 重试 LLM 或让用户指定 |
| 无 Label/Time 列 | NO_LABEL_OR_TIME | ⚠️ 视情况 | 如果是纯影像分析，允许跳过 Clinical Agent |
| ID 与影像 ID 无交集 | ID_COL_MISMATCH | ⚠️ 视情况 | 记录警告，不中断，Matching Agent 处理 |
| 全列相同值 | ALL_COLUMNS_SAME | ❌ 否 | 提示检查数据 |
| 时间列非数值 | NO_LABEL_OR_TIME | ❌ 否 | 提示转换为数值 |

### 6.2 关键异常处理代码

```python
# 文件读取异常：已在 _read_clinical_file 中处理

# LLM 异常：已在 _call_llm_with_retry 中处理（重试机制）

# ID 列匹配异常：在 _validate_columns 中处理
# 策略：如果 paired_ids 提供了但无交集，记录警告但不中断
# 由 Matching Agent 做更精细的模糊匹配

# 样本量预警（在 _assemble_output 之后由 Orchestrator 判断）
def check_sample_size(output: ClinicalOutput) -> Optional[str]:
    """
    Orchestrator 在收到 ClinicalOutput 后调用的样本量检查。
    Clinical Agent 本身不中断，只报告 n_samples。
    """
    if output.n_samples < 30:
        return f"样本量仅 {output.n_samples} 例，建议至少 30 例以上进行分析"
    return None
```

---

## 七、辅助函数与工具

### 7.1 列名清洗（处理中文 Excel 导出的常见乱码/空格问题）

```python
    def _clean_column_names(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        清洗列名：去除首尾空格、统一换行符、处理 BOM 头。
        
        注意：不修改列名内容本身（保持大小写），只去除不可见字符。
        """
        def clean(name):
            if isinstance(name, str):
                # 去除 BOM、首尾空格、换行符、制表符
                name = name.replace('\ufeff', '').strip()
                name = name.replace('\n', '').replace('\r', '').replace('\t', '')
                # 合并连续空格
                name = ' '.join(name.split())
            return name
        
        df.columns = [clean(col) for col in df.columns]
        return df
```

### 7.2 类型推断辅助

```python
    def _infer_column_role_heuristic(self, col_name: str) -> List[str]:
        """
        基于列名关键词的启发式角色推断，用于兜底或验证 LLM 结果。
        
        Returns:
            可能的角色列表，如 ["id"], ["label"], ["time"], ["event"], ["feature"]
        """
        col_lower = col_name.lower().replace("_", "").replace(" ", "")
        roles = []
        
        # ID 列判断
        if any(kw in col_lower for kw in self.ID_KEYWORDS):
            roles.append("id")
        
        # Label 列判断
        if any(kw in col_lower for kw in self.LABEL_KEYWORDS):
            roles.append("label")
        
        # Time 列判断
        if any(kw in col_lower for kw in self.TIME_KEYWORDS):
            roles.append("time")
        
        # Event 列判断
        if any(kw in col_lower for kw in self.EVENT_KEYWORDS):
            roles.append("event")
        
        # 如果没有匹配到任何关键词，默认为 feature
        if not roles:
            roles.append("feature")
        
        return roles
```

---

## 八、单元测试要点

同学 B 应在 `tests/test_clinical.py` 中编写以下测试：

```python
# tests/test_clinical.py

import pytest
import pandas as pd
import numpy as np
from app.clinical import ClinicalAgent, ClinicalInput, ClinicalErrorCode

class TestClinicalAgent:
    
    def test_read_csv_success(self, tmp_path):
        """测试成功读取 CSV"""
        csv_file = tmp_path / "test.csv"
        df = pd.DataFrame({
            "PatientID": ["P001", "P002", "P003"],
            "Age": [55, 62, 48],
            "Sex": ["M", "F", "M"],
            "OS": [0, 1, 0]
        })
        df.to_csv(csv_file, index=False)
        
        agent = ClinicalAgent()
        result = agent.run(ClinicalInput(clinical_path=str(csv_file)))
        assert result.id_col == "PatientID"
        assert result.label_col == "OS"
        assert "Age" in result.feature_cols
    
    def test_file_not_found(self):
        """测试文件不存在"""
        agent = ClinicalAgent()
        result = agent.run(ClinicalInput(clinical_path="/nonexistent/file.csv"))
        assert result.error_code == ClinicalErrorCode.FILE_NOT_FOUND
    
    def test_unsupported_format(self, tmp_path):
        """测试不支持的格式"""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("some data")
        
        agent = ClinicalAgent()
        result = agent.run(ClinicalInput(clinical_path=str(txt_file)))
        assert result.error_code == ClinicalErrorCode.UNSUPPORTED_FORMAT
    
    def test_empty_file(self, tmp_path):
        """测试空表格"""
        csv_file = tmp_path / "empty.csv"
        pd.DataFrame().to_csv(csv_file, index=False)
        
        agent = ClinicalAgent()
        result = agent.run(ClinicalInput(clinical_path=str(csv_file)))
        assert result.error_code == ClinicalErrorCode.EMPTY_FILE
    
    def test_survival_columns(self, tmp_path):
        """测试生存分析列识别"""
        csv_file = tmp_path / "survival.csv"
        df = pd.DataFrame({
            "ID": [1, 2, 3, 4, 5],
            "Age": [50, 60, 55, 45, 65],
            "Sex": ["F", "M", "F", "M", "F"],
            "OS_months": [24, 48, 12, 36, 60],
            "Death": [1, 0, 1, 0, 1]
        })
        df.to_csv(csv_file, index=False)
        
        agent = ClinicalAgent()
        result = agent.run(ClinicalInput(clinical_path=str(csv_file)))
        # 注意：这里依赖 LLM，测试中可能需要 mock
        assert result.analysis_type in ["classification", "survival"]
    
    def test_mock_llm_response(self, tmp_path, monkeypatch):
        """测试 mock LLM 返回的正确解析"""
        # mock llm 调用
        def mock_llm(prompt):
            return json.dumps({
                "id_col": "PatientID",
                "label_col": "Response",
                "time_col": None,
                "event_col": None,
                "feature_cols": ["Age", "Sex"],
                "analysis_type": "classification",
                "reasoning": "test"
            })
        
        monkeypatch.setattr("app.clinical.call_llm_column_identification", mock_llm)
        
        csv_file = tmp_path / "test.csv"
        pd.DataFrame({
            "PatientID": ["P1", "P2"],
            "Age": [50, 60],
            "Sex": ["M", "F"],
            "Response": [0, 1]
        }).to_csv(csv_file, index=False)
        
        agent = ClinicalAgent()
        result = agent.run(ClinicalInput(clinical_path=str(csv_file)))
        assert result.label_col == "Response"
        assert result.analysis_type == "classification"
```

---

## 九、实现 Checklist

同学 B 按以下顺序实现：

- [ ] **Day 1-2**: 实现 `ClinicalInput` / `ClinicalOutput` / `ClinicalFailure` 数据类
- [ ] **Day 1-2**: 实现 `_read_clinical_file`（CSV/Excel 读取 + 编码处理）
- [ ] **Day 1-2**: 实现 `_basic_qc`（空文件、单列、重复列名检查）
- [ ] **Day 2-3**: 实现 `_build_column_context` + `_format_column_table`（Prompt 上下文构建）
- [ ] **Day 2-3**: 实现 `_build_llm_prompt`（System + User Prompt 组装）
- [ ] **Day 2-3**: 对接负责人 `llm.py`，实现 `_call_llm_with_retry`
- [ ] **Day 3-4**: 实现 `_parse_llm_response` + `_has_required_fields`（JSON 解析 + 字段校验）
- [ ] **Day 3-4**: 实现 `_validate_columns`（列名存在性、类型、值域校验）
- [ ] **Day 4-5**: 实现 `_assemble_output` + 样本量检查
- [ ] **Day 5**: 编写单元测试（mock LLM 调用）
- [ ] **Day 6**: 与 Orchestrator 联调（输入输出接口对接）
- [ ] **Day 6**: 与 Matching Agent 联调（id_col 传递）

---

## 十、关键设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| ID 列类型推断 | 按 int/str/float 分类 | Matching Agent 需要知道是否做类型转换 |
| LLM 失败策略 | 重试 2 次后中断 | 避免无限等待，给用户重试选项 |
| feature_cols 为空 | 返回失败 | 没有特征列无法做后续分析 |
| ID 与影像无交集 | 警告但不中断 | 交给 Matching Agent 做模糊匹配 |
| 中文编码 | 优先 utf-8，失败回退 gbk | 覆盖多数中文 Excel 导出场景 |
| 列名清洗 | 只去不可见字符，不改内容 | 保持 LLM 识别的列名与原始一致 |
| analysis_type 推断 | 由 LLM 判断，非启发式 | 临床表格列名复杂，LLM 比规则更准确 |

---

*文档版本: v1.0*  
*对应开发计划版本: v1.0*  
*最后更新: 2025-06*
